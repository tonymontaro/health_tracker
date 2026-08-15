from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import ShoppingPlan

STANDARD_ITEMS: list[dict[str, Any]] = [
    {
        "food_name": "Chicken breast",
        "quantity": 1200,
        "unit": "g",
        "quantity_label": "1.2 kg",
        "estimated_chf": 28,
        "fresh": False,
        "location": "freezer",
    },
    {
        "food_name": "Salmon",
        "quantity": 500,
        "unit": "g",
        "quantity_label": "500 g",
        "estimated_chf": 20,
        "fresh": False,
        "location": "freezer",
    },
    {
        "food_name": "Skyr / quark",
        "quantity": 2000,
        "unit": "g",
        "quantity_label": "2 kg",
        "estimated_chf": 14,
        "fresh": False,
        "location": "fridge",
    },
    {
        "food_name": "Frozen berries",
        "quantity": 1000,
        "unit": "g",
        "quantity_label": "1 kg",
        "estimated_chf": 10,
        "fresh": False,
        "location": "freezer",
    },
    {
        "food_name": "Oats",
        "quantity": 1000,
        "unit": "g",
        "quantity_label": "1 kg",
        "estimated_chf": 4,
        "fresh": False,
        "location": "pantry",
    },
    {
        "food_name": "Brown rice",
        "quantity": 1000,
        "unit": "g",
        "quantity_label": "1 kg",
        "estimated_chf": 5,
        "fresh": False,
        "location": "pantry",
    },
    {
        "food_name": "Broccoli",
        "quantity": 600,
        "unit": "g",
        "quantity_label": "600 g",
        "estimated_chf": 6,
        "fresh": True,
        "location": "fridge",
    },
    {
        "food_name": "Spinach",
        "quantity": 300,
        "unit": "g",
        "quantity_label": "300 g",
        "estimated_chf": 5,
        "fresh": True,
        "location": "fridge",
    },
    {
        "food_name": "Kiwi",
        "quantity": 6,
        "unit": "item",
        "quantity_label": "6",
        "estimated_chf": 5,
        "fresh": True,
        "location": "counter",
    },
    {
        "food_name": "Tomatoes",
        "quantity": 600,
        "unit": "g",
        "quantity_label": "600 g",
        "estimated_chf": 6,
        "fresh": True,
        "location": "fridge",
    },
]


def update_shopping_item_quantity(
    plan: ShoppingPlan, item_index: int, quantity: float, unit: str
) -> None:
    if plan.status != "draft":
        raise ValueError("Purchased shopping plans cannot be edited.")
    if item_index < 0 or item_index >= len(plan.items_json):
        raise IndexError("Shopping item not found.")
    items = [dict(item) for item in plan.items_json]
    item = items[item_index]
    old_quantity = float(item["quantity"])
    old_unit = str(item["unit"])
    old_base, old_dimension = _shopping_base_quantity(old_quantity, old_unit)
    new_base, new_dimension = _shopping_base_quantity(quantity, unit)
    if old_dimension != new_dimension:
        raise ValueError(f"{item['food_name']} must remain measured in {old_dimension}.")
    unit_price = float(item["estimated_chf"]) / old_base
    item["quantity"] = quantity
    item["unit"] = unit
    item["quantity_label"] = format_shopping_quantity(quantity, unit)
    item["estimated_chf"] = round(unit_price * new_base, 2)
    plan.items_json = items
    _recalculate_shopping_total(plan)


def delete_shopping_item(plan: ShoppingPlan, item_index: int) -> None:
    if plan.status != "draft":
        raise ValueError("Purchased shopping plans cannot be edited.")
    if item_index < 0 or item_index >= len(plan.items_json):
        raise IndexError("Shopping item not found.")
    plan.items_json = [
        dict(item) for index, item in enumerate(plan.items_json) if index != item_index
    ]
    _recalculate_shopping_total(plan)


def format_shopping_quantity(quantity: float, unit: str) -> str:
    return f"{quantity:g} {unit}" if unit != "item" else f"{quantity:g} items"


def _shopping_base_quantity(quantity: float, unit: str) -> tuple[float, str]:
    if unit == "kg":
        return quantity * 1000, "weight"
    if unit == "g":
        return quantity, "weight"
    if unit == "ml":
        return quantity, "volume"
    return quantity, "item count"


def _recalculate_shopping_total(plan: ShoppingPlan) -> None:
    plan.estimated_total_chf = round(
        sum(float(item.get("estimated_chf", 0)) for item in plan.items_json), 2
    )


def generate_weekly_shopping_plan(
    db: Session, settings: Settings, week_start: date, retailer: str = "Coop"
) -> ShoppingPlan:
    total = sum(item["estimated_chf"] for item in STANDARD_ITEMS)
    minimum = (
        settings.coop_online_minimum_chf
        if retailer == "Coop"
        else settings.migros_online_minimum_chf
    )
    durable_total = sum(item["estimated_chf"] for item in STANDARD_ITEMS if not item["fresh"])
    mode = "mixed" if durable_total >= minimum else "in_store"
    items = [
        {
            **item,
            "purchase_mode": "in_store" if item["fresh"] or mode == "in_store" else "online",
            "suggested_day": "Tuesday" if item["fresh"] else "Sunday",
            "expires_on": (week_start + timedelta(days=7)).isoformat() if item["fresh"] else None,
        }
        for item in STANDARD_ITEMS
    ]
    existing = db.scalar(
        select(ShoppingPlan).where(
            ShoppingPlan.week_start == week_start,
            ShoppingPlan.retailer == retailer,
            ShoppingPlan.mode == mode,
        )
    )
    if existing:
        return existing
    legacy_draft = db.scalar(
        select(ShoppingPlan)
        .where(
            ShoppingPlan.week_start == week_start,
            ShoppingPlan.retailer == retailer,
            ShoppingPlan.status == "draft",
        )
        .order_by(ShoppingPlan.created_at.desc())
    )
    if legacy_draft:
        legacy_draft.mode = mode
        legacy_draft.estimated_total_chf = total
        legacy_draft.items_json = items
        db.commit()
        db.refresh(legacy_draft)
        return legacy_draft
    plan = ShoppingPlan(
        week_start=week_start,
        retailer=retailer,
        mode=mode,
        estimated_total_chf=total,
        items_json=items,
        status="draft",
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan
