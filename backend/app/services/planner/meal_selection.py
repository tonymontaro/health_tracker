from collections import Counter
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import MealTemplate, NutritionEntry, UserProfile

SPECIAL_MEAL_TAG = "special"


def conflicts_with_allergies(template: MealTemplate, allergies: list[str]) -> bool:
    terms = [
        template.name,
        template.description,
        *template.tags,
        *(str(item.get("name", "")) for item in template.ingredients_json),
    ]
    return any(allergy.casefold() in term.casefold() for allergy in allergies for term in terms)


def eligible_main_meal_templates(
    db: Session, profile: UserProfile, plan_date: date
) -> list[MealTemplate]:
    templates = list(db.scalars(select(MealTemplate).where(MealTemplate.active.is_(True))))
    return [
        template
        for template in templates
        if not {"emergency", "snack"}.intersection(tag.casefold() for tag in template.tags)
        and (
            "flexible" not in {tag.casefold() for tag in template.tags}
            or plan_date.strftime("%A") in profile.office_days
        )
        and not conflicts_with_allergies(template, profile.allergies)
    ]


def recommended_main_meal_history(
    db: Session, plan_date: date, *, days: int = 14
) -> list[dict[str, str]]:
    rows = db.execute(
        select(
            NutritionEntry.entry_date,
            NutritionEntry.meal_slot,
            NutritionEntry.food_or_meal_reference,
        )
        .where(
            NutritionEntry.entry_date.between(
                plan_date - timedelta(days=days), plan_date - timedelta(days=1)
            ),
            NutritionEntry.meal_slot.in_(["meal_1", "meal_2"]),
            NutritionEntry.planned_recommendation_id.is_not(None),
            NutritionEntry.food_or_meal_reference.is_not(None),
        )
        .order_by(NutritionEntry.entry_date.desc(), NutritionEntry.meal_slot)
    ).all()
    return [
        {"date": entry_date.isoformat(), "slot": meal_slot, "template_name": template_name}
        for entry_date, meal_slot, template_name in rows
        if template_name is not None
    ]


def is_special_meal(template: MealTemplate) -> bool:
    return SPECIAL_MEAL_TAG in {tag.casefold() for tag in template.tags}


def special_meal_required_today(db: Session, profile: UserProfile, plan_date: date) -> bool:
    if plan_date.strftime("%A") in profile.office_days:
        return False
    special_names = {
        template.name.casefold()
        for template in eligible_main_meal_templates(db, profile, plan_date)
        if is_special_meal(template)
    }
    if not special_names:
        return False
    recent = recommended_main_meal_history(db, plan_date, days=6)
    return not any(item["template_name"].casefold() in special_names for item in recent)


def build_meal_selection_policy(
    db: Session, profile: UserProfile, plan_date: date
) -> dict[str, object]:
    history = recommended_main_meal_history(db, plan_date)
    yesterday = (plan_date - timedelta(days=1)).isoformat()
    yesterday_names = [item["template_name"] for item in history if item["date"] == yesterday]
    counts = Counter(item["template_name"] for item in history)
    return {
        "priorities_in_order": [
            "respect allergies, medical constraints, and hard plan limits",
            "honor an explicit regeneration preference when one is supplied and safe",
            "avoid every main meal template recommended yesterday",
            "prefer easy, highly nutritious meals on ordinary days",
            "maximize variety across the recent fourteen-day recommendation history",
            "include at least one special higher-effort meal in every rolling seven-day period",
            "use inventory to reduce waste or effort only as a secondary tie-breaker",
        ],
        "inventory_policy": (
            "Do not restrict recommendations to current inventory. Assume any missing ingredient can "
            "be purchased. Inventory is only a convenience, expiry, and waste-reduction signal."
        ),
        "yesterday_main_meal_templates": yesterday_names,
        "recent_recommended_main_meals_14d": history,
        "recent_template_frequency_14d": dict(sorted(counts.items())),
        "special_meal_required_today": special_meal_required_today(db, profile, plan_date),
        "special_meal_definition": (
            "An active meal template tagged 'special'. It should be delicious, nutrient-dense, and "
            "worth extra preparation effort. On a two-meal day, keep the other meal quick and easy."
        ),
    }
