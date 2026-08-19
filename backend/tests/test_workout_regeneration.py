from copy import deepcopy
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import PlanModification, PlanningRun, WorkoutEntry
from app.services.planner.openai_planner import OpenAIPlanner, PlannerProviderError
from app.services.planner.orchestrator import generate_daily_plan
from app.services.workout_regeneration import (
    REGENERATION_VERSION,
    WorkoutRegenerationError,
    regenerate_workout,
)

TARGET = date(2026, 8, 11)


def test_regeneration_uses_refreshed_history_and_preserves_nutrition(
    db: Session, settings: Settings, seeded
) -> None:
    plan = generate_daily_plan(db, settings, TARGET, use_ai=False)
    original_plan = deepcopy(plan.original_plan_json)
    original_nutrition = deepcopy(plan.current_plan_json["nutrition"])
    original_snapshot_id = plan.profile_snapshot_id
    original_ids = {
        item["recommendation_id"] for item in plan.current_plan_json["workout"]["exercises"]
    }
    assert plan.current_plan_json["workout"]["exercises"][0]["distance_km"] == 5.0

    db.add(
        WorkoutEntry(
            entry_date=TARGET - timedelta(days=1),
            exercise_name="Outdoor run",
            prescription_json={
                "exercise_type": "run",
                "distance_km": 6.0,
                "pace_seconds_per_km": 390,
                "duration_seconds": 2340,
            },
            actual_json={
                "distance_km": 6.0,
                "duration_seconds": 2340,
                "completion_evidence": "strava_activity",
            },
            difficulty_1_to_10=4,
            status="completed",
            source="strava",
        )
    )
    db.commit()

    regenerate_workout(db, settings, plan, use_ai=False)

    regenerated = plan.current_plan_json
    assert regenerated["nutrition"] == original_nutrition
    assert plan.original_plan_json == original_plan
    assert plan.profile_snapshot_id == original_snapshot_id
    assert regenerated["workout"]["exercises"][0]["distance_km"] == 6.5
    new_ids = {item["recommendation_id"] for item in regenerated["workout"]["exercises"]}
    assert new_ids.isdisjoint(original_ids)
    materialized_ids = set(
        db.scalars(
            select(WorkoutEntry.planned_recommendation_id).where(WorkoutEntry.entry_date == TARGET)
        )
    )
    assert materialized_ids == new_ids
    modifications = list(
        db.scalars(select(PlanModification).where(PlanModification.daily_plan_id == plan.id))
    )
    assert len(modifications) == len(original_ids)
    assert all(item.source == "regenerated_fallback" for item in modifications)
    run = db.scalar(select(PlanningRun).where(PlanningRun.planner_version == REGENERATION_VERSION))
    assert run
    assert run.context_snapshot_json["training_summary_28d"]["completed_28d"] == 1
    assert run.context_snapshot_json["recent_training_sessions"][0]["source"] == "strava"
    assert "recent_sessions" not in run.context_snapshot_json["training_summary_28d"]
    assert "last_run" not in run.context_snapshot_json["training_summary_28d"]
    assert run.context_snapshot_json["last_run_outside_recent_sessions"] is None
    assert "recent_training" not in run.context_snapshot_json["profile_snapshot"]
    assert "recent_nutrition" not in run.context_snapshot_json["profile_snapshot"]
    assert "nutrition_summary_14d" not in run.context_snapshot_json
    assert "active_meal_templates" not in run.context_snapshot_json
    assert "current_inventory" not in run.context_snapshot_json
    assert "comparable_strength_sessions" not in run.context_snapshot_json
    assert "comparable_run_sessions" not in run.context_snapshot_json
    assert "comparable_bike_sessions" not in run.context_snapshot_json
    assert run.context_snapshot_json["workout_regeneration"]["requested"] is True


def test_regeneration_rejects_recorded_workout_without_changing_plan(
    db: Session, settings: Settings, seeded
) -> None:
    plan = generate_daily_plan(db, settings, TARGET, use_ai=False)
    before = deepcopy(plan.current_plan_json)
    entry = db.scalar(
        select(WorkoutEntry).where(
            WorkoutEntry.entry_date == TARGET,
            WorkoutEntry.planned_recommendation_id.is_not(None),
        )
    )
    assert entry
    entry.status = "completed"
    entry.actual_json = {"distance_km": 5.0, "duration_seconds": 1950}
    db.commit()

    with pytest.raises(WorkoutRegenerationError, match="before it is completed"):
        regenerate_workout(db, settings, plan, use_ai=False)

    db.refresh(plan)
    assert plan.current_plan_json == before


def test_provider_failure_falls_back_without_a_bogus_correction_attempt(
    db: Session, settings: Settings, seeded, monkeypatch
) -> None:
    plan = generate_daily_plan(db, settings, TARGET, use_ai=False)
    ai_settings = Settings(
        DATABASE_URL=settings.database_url,
        APP_ENV="test",
        OPENAI_API_KEY="test-key",
        SESSION_SECRET="test-session-secret-with-more-than-32-characters",
        _env_file=None,
    )
    calls: list[dict[str, object] | None] = []

    def fail(self, context, correction=None, *, prompt_label=None):
        calls.append(correction)
        raise PlannerProviderError(
            "OpenAI request failed after automatic retries · HTTP 520 · transient provider error"
        )

    monkeypatch.setattr(OpenAIPlanner, "generate", fail)

    regenerate_workout(db, ai_settings, plan)

    assert len(calls) == 1
    assert calls[0] is None
    run = db.scalar(select(PlanningRun).where(PlanningRun.planner_version == REGENERATION_VERSION))
    assert run
    assert run.status == "fallback"
    assert run.validation_result_json["attempts"] == [
        {
            "attempt": 1,
            "source": "openai",
            "stage": "provider",
            "errors": [
                "OpenAI request failed after automatic retries · HTTP 520 · "
                "transient provider error"
            ],
        }
    ]


def test_regeneration_records_an_optional_high_priority_workout_preference(
    db: Session, settings: Settings, seeded
) -> None:
    plan = generate_daily_plan(db, settings, TARGET, use_ai=False)

    regenerate_workout(
        db,
        settings,
        plan,
        preference="I'd prefer an upper-body strength session today",
        use_ai=False,
    )

    run = db.scalar(select(PlanningRun).where(PlanningRun.planner_version == REGENERATION_VERSION))
    assert run
    regeneration_context = run.context_snapshot_json["workout_regeneration"]
    assert regeneration_context["user_preference"] == (
        "I'd prefer an upper-body strength session today"
    )
    assert "high-priority request" in regeneration_context["preference_priority"]
