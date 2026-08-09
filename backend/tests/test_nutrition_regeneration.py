from copy import deepcopy
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    MealTemplate,
    NutritionEntry,
    PlanModification,
    PlanningRun,
)
from app.services.history import replace_recommendation
from app.services.nutrition_regeneration import (
    EMERGENCY_TEMPLATE_NAME,
    REGENERATION_VERSION,
    NutritionRegenerationError,
    regenerate_nutrition,
)
from app.services.planner.orchestrator import generate_daily_plan

TARGET = date(2026, 8, 9)


def meal_replacement(db: Session, template_name: str) -> dict[str, object]:
    template = db.scalar(select(MealTemplate).where(MealTemplate.name == template_name))
    assert template
    return {
        "template_name": template.name,
        "description": template.description,
        "suggested_window": "when convenient",
        "expected": True,
        "estimated_protein_g": template.estimated_protein_g,
        "estimated_fiber_g": template.estimated_fiber_g,
        "hands_on_minutes": template.hands_on_minutes,
        "ingredients": [item["name"] for item in template.ingredients_json],
        "preparation": f"Prepare in about {template.hands_on_minutes} active minutes.",
    }


def test_regeneration_replaces_double_emergency_meals_and_preserves_workout(
    db: Session, settings: Settings, seeded
) -> None:
    plan = generate_daily_plan(db, settings, TARGET, use_ai=False)
    original_plan = deepcopy(plan.original_plan_json)
    original_workout = deepcopy(plan.current_plan_json["workout"])
    meal_ids = [
        plan.current_plan_json["nutrition"]["meal_1"]["recommendation_id"],
        plan.current_plan_json["nutrition"]["meal_2"]["recommendation_id"],
    ]
    emergency = meal_replacement(db, EMERGENCY_TEMPLATE_NAME)
    for recommendation_id in meal_ids:
        replace_recommendation(
            db,
            plan,
            recommendation_id,
            emergency,
            "Legacy emergency-plate action",
            "user",
        )
    assert {
        plan.current_plan_json["nutrition"]["meal_1"]["template_name"],
        plan.current_plan_json["nutrition"]["meal_2"]["template_name"],
    } == {EMERGENCY_TEMPLATE_NAME}

    regenerate_nutrition(db, settings, plan, use_ai=False)

    regenerated_meals = [
        plan.current_plan_json["nutrition"]["meal_1"],
        plan.current_plan_json["nutrition"]["meal_2"],
    ]
    regenerated_names = {meal["template_name"] for meal in regenerated_meals}
    assert EMERGENCY_TEMPLATE_NAME not in regenerated_names
    assert "Thursday flexible colleague meal" not in regenerated_names
    assert len(regenerated_names) == 2
    assert [meal["recommendation_id"] for meal in regenerated_meals] == meal_ids
    assert plan.current_plan_json["workout"] == original_workout
    assert plan.original_plan_json == original_plan
    assert (
        "emergency plate remains optional"
        in plan.current_plan_json["nutrition"]["guidance"].lower()
    )

    entries = list(
        db.scalars(
            select(NutritionEntry)
            .where(
                NutritionEntry.entry_date == TARGET,
                NutritionEntry.planned_recommendation_id.in_(meal_ids),
            )
            .order_by(NutritionEntry.meal_slot)
        )
    )
    assert [entry.food_or_meal_reference for entry in entries] == [
        meal["template_name"] for meal in regenerated_meals
    ]
    assert all(entry.status == "planned" for entry in entries)
    assert all(entry.source == "regenerated_fallback" for entry in entries)
    modifications = list(
        db.scalars(select(PlanModification).where(PlanModification.daily_plan_id == plan.id))
    )
    assert len(modifications) == 4
    assert sum(item.source == "regenerated_fallback" for item in modifications) == 2
    run = db.scalar(select(PlanningRun).where(PlanningRun.planner_version == REGENERATION_VERSION))
    assert run and run.status == "fallback"


def test_regeneration_rejects_a_resolved_meal_without_changing_plan(
    db: Session, settings: Settings, seeded
) -> None:
    plan = generate_daily_plan(db, settings, TARGET, use_ai=False)
    before = deepcopy(plan.current_plan_json)
    first_id = plan.current_plan_json["nutrition"]["meal_1"]["recommendation_id"]
    entry = db.scalar(
        select(NutritionEntry).where(
            NutritionEntry.entry_date == TARGET,
            NutritionEntry.planned_recommendation_id == first_id,
        )
    )
    assert entry
    entry.status = "confirmed"
    db.commit()

    with pytest.raises(NutritionRegenerationError, match="before they are confirmed"):
        regenerate_nutrition(db, settings, plan, use_ai=False)

    db.refresh(plan)
    assert plan.current_plan_json == before
