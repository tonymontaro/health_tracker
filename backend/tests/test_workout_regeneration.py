from copy import deepcopy
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import PlanModification, PlanningRun, WorkoutEntry
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
    assert (
        run.context_snapshot_json["training_summary_28d"]["recent_sessions"][0]["source"]
        == "strava"
    )
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
