import re
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import FoodItem, InventoryItem, MealTemplate, NutritionEntry

QUANTITY_RE = re.compile(r"(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>g|kg|ml|item)?", re.I)


def consume_meal_inventory(db: Session, template_name: str | None) -> None:
    adjust_meal_inventory(db, template_name, direction=-1)


def adjust_meal_inventory(db: Session, template_name: str | None, *, direction: int) -> None:
    if not template_name:
        return
    template = db.scalar(select(MealTemplate).where(MealTemplate.name == template_name))
    if template is None:
        return
    for ingredient in template.ingredients_json:
        food = db.scalar(select(FoodItem).where(FoodItem.name == ingredient["name"]))
        if food is None:
            continue
        inventory = db.scalar(select(InventoryItem).where(InventoryItem.food_item_id == food.id))
        if inventory is None or inventory.quantity_estimate is None:
            continue
        parsed = parse_quantity(ingredient.get("quantity", ""))
        if parsed is None:
            inventory.confidence = "low"
            continue
        amount, unit = parsed
        normalized = amount * 1000 if unit == "kg" else amount
        if (unit in {"g", "kg"} and inventory.unit == "g") or (
            unit == "item" and inventory.unit == "item"
        ):
            inventory.quantity_estimate = max(
                0, inventory.quantity_estimate + (direction * normalized)
            )
        else:
            inventory.confidence = "low"


def adjust_nutrition_entry_inventory(db: Session, entry: NutritionEntry, *, direction: int) -> None:
    """Apply or reverse an entry's inventory delta without losing clamped quantities."""
    quantity = dict(entry.quantity_json)
    if entry.food_log_id is not None:
        components = [dict(component) for component in quantity.get("components", [])]
        quantity["components"] = _adjust_components(db, components, direction=direction)
        entry.quantity_json = quantity
        return

    if direction == -1:
        adjustments = _consume_template_with_receipt(db, entry.food_or_meal_reference)
        quantity["inventory_adjustments"] = adjustments
        entry.quantity_json = quantity
        return

    adjustments = quantity.pop("inventory_adjustments", None)
    if isinstance(adjustments, list):
        _restore_inventory_receipt(db, adjustments)
        entry.quantity_json = quantity
        return

    # Entries recorded before inventory receipts were introduced need the legacy reversal.
    adjust_meal_inventory(db, entry.food_or_meal_reference, direction=1)


def _adjust_components(
    db: Session, components: list[dict[str, Any]], *, direction: int
) -> list[dict[str, Any]]:
    for component in components:
        catalog_name = component.get("catalog_food_name")
        if not isinstance(catalog_name, str):
            continue
        food = db.scalar(select(FoodItem).where(FoodItem.name == catalog_name))
        if food is None:
            continue
        inventory = db.scalar(select(InventoryItem).where(InventoryItem.food_item_id == food.id))
        if inventory is None or inventory.quantity_estimate is None:
            continue
        amount = component.get("quantity_value")
        unit = component.get("unit")
        if not isinstance(amount, int | float) or not isinstance(unit, str):
            continue
        if not _units_are_compatible(unit, inventory.unit):
            inventory.confidence = "low"
            continue
        if direction == -1:
            applied = min(max(inventory.quantity_estimate, 0), float(amount))
            inventory.quantity_estimate -= applied
            component["inventory_consumed_value"] = applied
            component["inventory_consumed_unit"] = inventory.unit
        else:
            applied = component.pop("inventory_consumed_value", 0)
            component.pop("inventory_consumed_unit", None)
            if isinstance(applied, int | float):
                inventory.quantity_estimate += float(applied)
    return components


def _consume_template_with_receipt(db: Session, template_name: str | None) -> list[dict[str, Any]]:
    if not template_name:
        return []
    template = db.scalar(select(MealTemplate).where(MealTemplate.name == template_name))
    if template is None:
        return []
    adjustments: list[dict[str, Any]] = []
    for ingredient in template.ingredients_json:
        food = db.scalar(select(FoodItem).where(FoodItem.name == ingredient["name"]))
        if food is None:
            continue
        inventory = db.scalar(select(InventoryItem).where(InventoryItem.food_item_id == food.id))
        if inventory is None or inventory.quantity_estimate is None:
            continue
        parsed = parse_quantity(ingredient.get("quantity", ""))
        if parsed is None:
            inventory.confidence = "low"
            continue
        amount, unit = parsed
        normalized = amount * 1000 if unit == "kg" else amount
        if not _units_are_compatible("g" if unit == "kg" else unit, inventory.unit):
            inventory.confidence = "low"
            continue
        applied = min(max(inventory.quantity_estimate, 0), normalized)
        inventory.quantity_estimate -= applied
        adjustments.append(
            {
                "food_name": food.name,
                "quantity_value": applied,
                "unit": inventory.unit,
            }
        )
    return adjustments


def _restore_inventory_receipt(db: Session, adjustments: list[dict[str, Any]]) -> None:
    for adjustment in adjustments:
        food_name = adjustment.get("food_name")
        amount = adjustment.get("quantity_value")
        unit = adjustment.get("unit")
        if not isinstance(food_name, str) or not isinstance(amount, int | float):
            continue
        food = db.scalar(select(FoodItem).where(FoodItem.name == food_name))
        if food is None:
            continue
        inventory = db.scalar(select(InventoryItem).where(InventoryItem.food_item_id == food.id))
        if inventory is None or inventory.quantity_estimate is None:
            continue
        if isinstance(unit, str) and unit == inventory.unit:
            inventory.quantity_estimate += float(amount)
        else:
            inventory.confidence = "low"


def _units_are_compatible(component_unit: str, inventory_unit: str) -> bool:
    normalized_inventory = inventory_unit.lower().strip()
    return (
        component_unit == "g"
        and normalized_inventory.startswith("g")
        or component_unit == "ml"
        and normalized_inventory.startswith("ml")
        or component_unit == "item"
        and normalized_inventory == "item"
    )


def parse_quantity(value: str) -> tuple[float, str] | None:
    match = QUANTITY_RE.search(value)
    if not match:
        return None
    return float(match.group("amount")), (match.group("unit") or "item").lower()


def add_purchased_items(db: Session, items: list[dict[str, Any]]) -> None:
    for item in items:
        food = db.scalar(select(FoodItem).where(FoodItem.name == item.get("food_name")))
        if food is None:
            continue
        inventory = db.scalar(select(InventoryItem).where(InventoryItem.food_item_id == food.id))
        if inventory is None:
            inventory = InventoryItem(
                food_item_id=food.id,
                quantity_estimate=0,
                unit=item.get("unit", food.typical_unit),
                confidence="high",
                location=item.get("location", "pantry"),
            )
            db.add(inventory)
        amount = item.get("quantity")
        if isinstance(amount, int | float):
            inventory.quantity_estimate = (inventory.quantity_estimate or 0) + float(amount)
        inventory.quantity_label = item.get("quantity_label")
        inventory.confidence = "high"
        expires = item.get("expires_on")
        if isinstance(expires, str):
            inventory.expires_on = date.fromisoformat(expires)
