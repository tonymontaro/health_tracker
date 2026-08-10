from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Equipment, MealTemplate, WorkoutEntry
from app.schemas.plan import (
    DailyPlanProposal,
    ExerciseProposal,
    ExerciseType,
    NutritionPlanProposal,
    WorkoutPlanProposal,
)
from app.services.planner.domain import validate_plan
from app.services.planner.fallback import build_fallback_plan
from app.services.planner.meal_recipes import simple_meal_recipe

MONDAY = date(2026, 8, 10)
THURSDAY = date(2026, 8, 13)
SATURDAY = date(2026, 8, 15)


def test_expected_meal_count_must_match_supplied_meals(db: Session, seeded) -> None:
    plan = build_fallback_plan(db, MONDAY)
    payload = plan.nutrition.model_dump()
    payload["expected_main_meals"] = 1
    with pytest.raises(ValidationError):
        NutritionPlanProposal.model_validate(payload)


def test_fruit_and_snacks_do_not_count_as_main_meals(db: Session, seeded) -> None:
    plan = build_fallback_plan(db, MONDAY)
    assert plan.nutrition.expected_main_meals == 2
    assert len(plan.nutrition.fruits) == 3
    assert len(plan.nutrition.snacks) == 2
    seeded.max_main_meals_per_day = 1
    one_meal_plan = build_fallback_plan(db, MONDAY)
    assert one_meal_plan.nutrition.expected_main_meals == 1


def test_every_catalog_meal_has_a_simple_numbered_recipe(db: Session, seeded) -> None:
    templates = list(db.scalars(select(MealTemplate).where(MealTemplate.active.is_(True))))

    assert templates
    for template in templates:
        recipe = simple_meal_recipe(template)
        assert recipe.startswith("1. ")
        assert "2. " in recipe

    plan = build_fallback_plan(db, MONDAY)
    selected_template = db.scalar(
        select(MealTemplate).where(MealTemplate.name == plan.nutrition.meal_1.template_name)
    )
    assert selected_template
    assert plan.nutrition.meal_1.preparation == simple_meal_recipe(selected_template)


def test_more_than_three_exercises_is_schema_invalid(db: Session, seeded) -> None:
    plan = build_fallback_plan(db, MONDAY)
    payload = plan.model_dump()
    payload["workout"]["exercises"].append(payload["workout"]["exercises"][0])
    with pytest.raises(ValidationError):
        DailyPlanProposal.model_validate(payload)


def test_rest_and_recovery_workouts_have_distinct_valid_shapes() -> None:
    recovery = ExerciseProposal(
        exercise_name="Easy mobility",
        exercise_type=ExerciseType.RECOVERY,
        duration_seconds=900,
        expected_difficulty=2,
        instructions="Move gently.",
    )
    active_recovery = WorkoutPlanProposal(
        kind="recovery",
        intensity="very_light",
        title="Easy mobility",
        exercises=[recovery],
        expected_duration_minutes=15,
        summary="Gentle movement only.",
    )

    assert active_recovery.kind == "recovery"
    with pytest.raises(ValidationError, match="rest plans cannot contain exercises"):
        WorkoutPlanProposal(
            kind="rest",
            intensity="rest",
            title="Contradictory rest",
            exercises=[recovery],
            expected_duration_minutes=15,
            summary="Invalid rest with movement.",
        )


def test_gym_only_exercise_is_rejected_on_weekday(db: Session, seeded) -> None:
    plan = build_fallback_plan(db, SATURDAY)
    errors = validate_plan(db, plan, seeded, MONDAY)
    assert any("Gym-only" in error for error in errors)


def test_gym_only_exercise_is_allowed_on_weekend(db: Session, seeded) -> None:
    plan = build_fallback_plan(db, SATURDAY)
    assert validate_plan(db, plan, seeded, SATURDAY) == []
    gym = db.scalar(select(Equipment).where(Equipment.name == "Commercial gym access"))
    assert gym
    gym.available = False
    db.flush()
    assert any(
        "equipment is unavailable" in error for error in validate_plan(db, plan, seeded, SATURDAY)
    )


def test_thursday_hard_training_is_rejected(db: Session, seeded) -> None:
    plan = build_fallback_plan(db, MONDAY)
    errors = validate_plan(db, plan, seeded, THURSDAY)
    assert any("Thursday" in error for error in errors)


def test_thursday_fallback_is_rest(db: Session, seeded) -> None:
    plan = build_fallback_plan(db, THURSDAY)
    assert plan.workout.kind == "rest"
    assert plan.nutrition.expected_main_meals == 1
    assert validate_plan(db, plan, seeded, THURSDAY) == []


def test_active_workout_requires_measurable_workload(db: Session, seeded) -> None:
    plan = build_fallback_plan(db, MONDAY)
    plan.workout.exercises[0].load_kg = None
    errors = validate_plan(db, plan, seeded, MONDAY)
    assert any("measurable workload" in error for error in errors)


def test_pain_prevents_automatic_progression(db: Session, seeded) -> None:
    db.add(
        WorkoutEntry(
            entry_date=date(2026, 8, 3),
            planned_recommendation_id="old",
            exercise_name="Dumbbell bench press",
            prescription_json={
                "exercise_type": "strength",
                "load_kg": 30,
                "sets": 3,
                "reps_per_set": [8, 8, 8],
            },
            actual_json={"load_kg": 30, "reps_per_set": [8, 8, 8]},
            difficulty_1_to_10=6,
            status="completed",
            source="recommended",
            pain_flag=True,
        )
    )
    db.flush()
    plan = build_fallback_plan(db, MONDAY)
    plan.workout.exercises[0].load_kg = 32
    errors = validate_plan(db, plan, seeded, MONDAY)
    assert any("Pain prevents" in error for error in errors)


def test_run_progresses_distance_without_changing_pace(db: Session, seeded) -> None:
    db.add(
        WorkoutEntry(
            entry_date=date(2026, 8, 4),
            planned_recommendation_id="run-old",
            exercise_name="Treadmill run",
            prescription_json={
                "exercise_type": "run",
                "distance_km": 5,
                "pace_seconds_per_km": 390,
            },
            actual_json={"distance_km": 5, "pace_seconds_per_km": 390},
            difficulty_1_to_10=4,
            status="completed",
            source="recommended",
            pain_flag=False,
        )
    )
    db.flush()
    plan = build_fallback_plan(db, date(2026, 8, 11))
    run = plan.workout.exercises[0]
    assert run.distance_km == 5.5
    assert run.pace_seconds_per_km == 390


def test_unknown_exercise_is_rejected(db: Session, seeded) -> None:
    plan = build_fallback_plan(db, MONDAY)
    plan.workout.exercises[0] = ExerciseProposal(
        exercise_name="Invented lift",
        exercise_type=ExerciseType.STRENGTH,
        load_kg=20,
        sets=3,
        reps_per_set=[8, 8, 8],
        rest_seconds=120,
        expected_difficulty=5,
        instructions="Test",
    )
    assert any("Unknown exercise" in error for error in validate_plan(db, plan, seeded, MONDAY))
