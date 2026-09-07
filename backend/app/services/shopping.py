import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import MealTemplate, WeeklyMealPlan


def ingredient_quantity(ingredient: dict[str, Any]) -> dict[str, Any]:
    label = str(ingredient["quantity"]).strip()
    match = re.fullmatch(
        r"(\d+(?:\.\d+)?)\s*(kg|g cooked|g|ml|l|items?|eggs?)?", label)
    if not match:
        raise ValueError(f"Ingredient quantity cannot be combined: {label}")
    quantity = Decimal(match[1])
    unit = match[2] or "item"
    if unit in {"kg", "l"}:
        quantity *= 1000
        unit = "g" if unit == "kg" else "ml"
    if unit in {"items", "egg", "eggs"}:
        unit = "item"
    if quantity <= 0:
        raise ValueError("Ingredient quantities must be positive")
    return {"food_name": ingredient["name"], "quantity": float(quantity), "unit": unit}


def shopping_ingredients_for_meal(db: Session, meal: dict[str, Any]) -> list[dict[str, Any]]:
    """Read actual recipe quantities, preserving unparseable legacy lines for manual review."""
    template = db.scalar(select(MealTemplate).where(
        MealTemplate.name == meal["template_name"]))
    if template is None:
        return [{"note": str(line)} for line in meal.get("ingredients", [])]
    result = []
    names = sorted(
        (item["name"] for item in template.ingredients_json), key=len, reverse=True)
    for line in meal.get("ingredients", []):
        name = next((name for name in names if line.endswith(" " + name)), None)
        try:
            if name is None:
                raise ValueError("Unknown ingredient")
            result.append(
                ingredient_quantity(
                    {"name": name, "quantity": line[: -len(name)].strip()})
            )
        except ValueError:
            result.append({"note": line})
    return result


def shopping_list(days: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    notes = set()
    for day in days:
        main_meals = [meal for meal in day["meals"]
                      if meal.get("expected", True)]
        for entry in [*main_meals, *day.get("fruits", []), *day.get("snacks", [])]:
            for ingredient in entry.get("shopping_ingredients", []):
                if "note" in ingredient:
                    notes.add(f"Check recipe quantity: {ingredient['note']}")
                else:
                    totals[(ingredient["food_name"], ingredient["unit"])] += Decimal(
                        str(ingredient["quantity"])
                    )
        if any(not meal.get("ingredients") for meal in main_meals):
            notes.add("Meals eaten out are not included in groceries.")
    items = [
        {
            "food_name": name,
            "quantity": float(quantity),
            "unit": unit,
            "quantity_label": f"{quantity.normalize():f} {'items' if unit == 'item' else unit}",
        }
        for (name, unit), quantity in sorted(totals.items())
    ]
    notes.update(
        []
    )
    return items, sorted(notes)


def shopping_ingredients_for_extra(db: Session, item: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep quantities from daily recommendations after their shopping metadata is stripped."""
    label = item.get("quantity") or item.get("description", "")
    try:
        return [ingredient_quantity({"name": item["name"], "quantity": label.split(",", 1)[0]})]
    except ValueError:
        template = db.scalar(select(MealTemplate).where(
            MealTemplate.name == item["name"]))
        if template:
            return [ingredient_quantity(ingredient) for ingredient in template.ingredients_json]
        return [{"note": f"{item['name']}: {label}"}]


def generate_weekly_shopping_plan(
    db: Session, settings: Settings, week_start: date, retailer: str = "Either"
) -> WeeklyMealPlan:
    from app.services.meal_planning import ensure_meal_weeks

    return ensure_meal_weeks(db, settings, week_start)[0]
