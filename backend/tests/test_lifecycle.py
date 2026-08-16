from copy import deepcopy
from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import DailyPlan, NotificationEvent, NutritionEntry, WorkoutEntry
from app.jobs.tasks import finalize_day
from app.schemas.api import HistoryWorkoutUpdate
from app.services.history import correct_workout_entry, reconcile_day
from app.services.planner.orchestrator import generate_daily_plan
from app.services.shopping import STANDARD_ITEMS, generate_weekly_shopping_plan

TARGET = date(2026, 8, 10)


def test_reconciliation_assumes_main_meals_and_workouts_were_skipped(
    db: Session, settings: Settings, seeded
) -> None:
    generate_daily_plan(db, settings, TARGET, use_ai=False)
    result = reconcile_day(db, TARGET)
    meals = list(db.scalars(select(NutritionEntry).where(NutritionEntry.entry_date == TARGET)))
    workouts = list(db.scalars(select(WorkoutEntry).where(WorkoutEntry.entry_date == TARGET)))
    assert result["assumed_skipped_meals"] == 2
    assert all(
        item.status == "skipped_assumed" for item in meals if item.meal_slot.startswith("meal")
    )
    assert all(item.status == "planned" for item in meals if item.meal_slot in {"fruit", "snack"})
    assert all(item.status == "skipped_assumed" for item in workouts)


def test_reconciliation_does_not_overwrite_explicit_logs(
    db: Session, settings: Settings, seeded
) -> None:
    generate_daily_plan(db, settings, TARGET, use_ai=False)
    meal = db.scalar(select(NutritionEntry).where(NutritionEntry.entry_date == TARGET))
    workout = db.scalar(select(WorkoutEntry).where(WorkoutEntry.entry_date == TARGET))
    assert meal and workout
    meal.status = "skipped"
    workout.status = "completed"
    workout.actual_json = {"load_kg": 30, "reps_per_set": [8, 8, 8]}
    db.commit()
    reconcile_day(db, TARGET)
    assert meal.status == "skipped"
    assert workout.status == "completed"


def test_history_correction_preserves_original_daily_plan(
    db: Session, settings: Settings, seeded
) -> None:
    plan = generate_daily_plan(db, settings, TARGET, use_ai=False)
    original = deepcopy(plan.original_plan_json)
    workout = db.scalar(select(WorkoutEntry).where(WorkoutEntry.entry_date == TARGET))
    assert workout
    correct_workout_entry(
        db,
        workout,
        HistoryWorkoutUpdate(
            actual={"load_kg": 30, "reps_per_set": [8, 8, 7]},
            difficulty_1_to_10=7,
            status="completed",
        ).model_dump(exclude_unset=True),
        TARGET,
    )
    db.refresh(plan)
    assert plan.original_plan_json == original
    assert workout.source == "history_correction"


def test_failed_ai_planning_reaches_fallback(db: Session, monkeypatch, seeded) -> None:
    settings = Settings(
        DATABASE_URL="postgresql+psycopg://health:health@localhost:55432/health_test",
        OPENAI_API_KEY="fake-key",
        SESSION_SECRET="test-session-secret-with-more-than-32-characters",
    )

    calls = 0

    def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("app.services.planner.openai_planner.OpenAIPlanner.generate", fail)
    monkeypatch.setattr(
        "app.services.planner.openai_two_week_planner.OpenAITwoWeekPlanner.generate",
        fail,
    )
    plan = generate_daily_plan(db, settings, TARGET, use_ai=True)
    assert plan.current_plan_json["source"] == "fallback"
    assert calls == 4


def test_plan_generation_is_idempotent(db: Session, settings: Settings, seeded) -> None:
    first = generate_daily_plan(db, settings, TARGET, use_ai=False)
    second = generate_daily_plan(db, settings, TARGET, use_ai=False)
    assert first.id == second.id
    assert db.query(DailyPlan).count() == 1


def test_finalize_job_is_idempotent(db: Session, settings: Settings, seeded) -> None:
    generate_daily_plan(db, settings, TARGET, use_ai=False)
    first = finalize_day(db, TARGET)
    second = finalize_day(db, TARGET)
    events = list(
        db.scalars(
            select(NotificationEvent).where(
                NotificationEvent.event_type == "finalize_day",
                NotificationEvent.event_date == TARGET,
            )
        )
    )
    assert first == second
    assert len(events) == 1


def test_historical_completion_requires_actual_evidence(
    db: Session, settings: Settings, seeded
) -> None:
    generate_daily_plan(db, settings, TARGET, use_ai=False)
    workout = db.scalar(select(WorkoutEntry).where(WorkoutEntry.entry_date == TARGET))
    assert workout
    with pytest.raises(ValueError, match="actual performance evidence"):
        correct_workout_entry(db, workout, {"status": "completed"}, TARGET)


def test_small_durable_basket_stays_in_store_without_threshold_padding(
    db: Session, settings: Settings, seeded
) -> None:
    plan = generate_weekly_shopping_plan(db, settings, TARGET, "Migros")
    assert plan.mode == "in_store"
    assert all(item["purchase_mode"] == "in_store" for item in plan.items_json)
    assert plan.estimated_total_chf == sum(item["estimated_chf"] for item in STANDARD_ITEMS)


def test_production_rejects_default_secrets() -> None:
    with pytest.raises(ValidationError, match="Production requires secure configuration"):
        Settings(APP_ENV="production", _env_file=None)
