from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Equipment, WorkoutEntry
from app.schemas.plan import (
    DailyPlanProposal,
    ExerciseProposal,
    ExerciseType,
    NutritionPlanProposal,
)
from app.services.planner.domain import validate_plan
from app.services.planner.fallback import build_fallback_plan

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


def test_more_than_three_exercises_is_schema_invalid(db: Session, seeded) -> None:
    plan = build_fallback_plan(db, MONDAY)
    payload = plan.model_dump()
    payload["workout"]["exercises"].append(payload["workout"]["exercises"][0])
    with pytest.raises(ValidationError):
        DailyPlanProposal.model_validate(payload)


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
