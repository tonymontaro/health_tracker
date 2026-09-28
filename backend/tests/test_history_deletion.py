import asyncio
from copy import deepcopy
from datetime import date, timedelta
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.today import _actual_workouts, _status_maps
from app.core.config import Settings, get_settings
from app.db.models import DerivedSummary, WorkoutCoachFeedback, WorkoutEntry
from app.db.session import get_db
from app.main import app
from app.services.history import delete_workout_entry, history_day, history_index, reconcile_day
from app.services.metrics import calculate_goal_progress_evidence, calculate_training_summary
from app.services.planner.orchestrator import generate_daily_plan
from app.services.planner.two_week_fallback import _adaptation_evidence
from app.services.recording_dates import daily_plan_calendar
from app.services.workout_feedback import ensure_workout_feedback
from app.services.workout_regeneration import regenerate_workout

TARGET = date(2026, 8, 10)


def test_delete_record_preserves_plan_and_excludes_training_evidence(
    db: Session, settings: Settings, seeded
) -> None:
    plan = generate_daily_plan(db, settings, TARGET, use_ai=False)
    original = deepcopy(plan.original_plan_json)
    current = deepcopy(plan.current_plan_json)
    entries = list(db.scalars(select(WorkoutEntry).where(WorkoutEntry.entry_date == TARGET)))
    entry = entries[0]
    entry.status = "completed"
    entry.source = "manual"
    entry.actual_json = {"load_kg": 30, "reps_per_set": [8, 8, 8]}
    entry.difficulty_1_to_10 = 9
    entry.pain_flag = True
    entry.notes = "Incorrect duplicate record"
    db.add(
        WorkoutCoachFeedback(
            feedback_date=TARGET,
            message="Feedback based on the duplicate",
            model="test",
            context_snapshot_json={},
        )
    )
    db.commit()

    delete_workout_entry(db, entry, TARGET)

    assert entry.status == "deleted"
    assert entry.actual_json == {"load_kg": 30, "reps_per_set": [8, 8, 8]}
    assert entry.source == "manual"
    assert entry.difficulty_1_to_10 == 9
    assert entry.pain_flag is True
    db.refresh(plan)
    assert plan.original_plan_json == original
    assert plan.current_plan_json == current
    assert str(entry.id) not in {row["id"] for row in history_day(db, TARGET)["workouts"]}
    assert history_index(db)[0]["workout_count"] == len(entries) - 1
    assert entry.planned_recommendation_id not in _status_maps(db, TARGET)[1]
    assert _actual_workouts(db, TARGET) == []
    summary = db.scalar(select(DerivedSummary)).training_summary_json
    assert summary["completed_exercise_entries_28d"] == 0
    assert summary["pain_flags_28d"] == 0
    assert summary["average_difficulty"] is None
    assert summary["strength_volume_28d"] == {}
    assert not any(row["status"] == "deleted" for row in summary["recent_sessions"])
    assert db.scalar(select(WorkoutCoachFeedback)) is None
    assert ensure_workout_feedback(db, settings, TARGET) is None
    assert _adaptation_evidence(db, TARGET + timedelta(days=1))["recovery_cautioned"] is False
    calendar = daily_plan_calendar(db, settings, TARGET)
    assert (
        next(row for row in calendar["days"] if row["date"] == str(TARGET))["exercise_performed"]
        is False
    )
    reconcile_day(db, TARGET)
    db.refresh(entry)
    assert entry.status == "deleted"


def test_delete_last_unplanned_record_removes_history_date_and_running_totals(
    db: Session, seeded
) -> None:
    entry = WorkoutEntry(
        entry_date=TARGET,
        exercise_name="Duplicate run",
        prescription_json={"exercise_type": "run"},
        actual_json={"distance_km": 6.2, "duration_seconds": 2200},
        status="completed",
        source="manual",
    )
    db.add(entry)
    db.commit()
    assert calculate_training_summary(db, TARGET)["running_distance_28d_km"] == 6.2

    delete_workout_entry(db, entry, TARGET)

    assert history_index(db) == []
    assert history_day(db, TARGET)["workouts"] == []
    assert _actual_workouts(db, TARGET) == []
    assert calculate_training_summary(db, TARGET)["planned_28d"] == 0
    assert calculate_goal_progress_evidence(db, TARGET)["run_count"] == 0


def test_deleted_workout_allows_regeneration_without_discarding_tombstone(
    db: Session, settings: Settings, seeded
) -> None:
    plan = generate_daily_plan(db, settings, TARGET, use_ai=False)
    original = deepcopy(plan.original_plan_json)
    entry = db.scalar(select(WorkoutEntry).where(WorkoutEntry.entry_date == TARGET))
    entry.status = "completed"
    entry.actual_json = {"summary": "Duplicate workout"}
    db.commit()
    delete_workout_entry(db, entry, TARGET)

    regenerate_workout(db, settings, plan, use_ai=False)

    db.refresh(entry)
    assert entry.status == "deleted"
    assert entry.planned_recommendation_id is None
    assert plan.original_plan_json == original
    assert all(row["status"] == "planned" for row in history_day(db, TARGET)["workouts"])


def test_delete_history_api_requires_auth_csrf_and_matching_date(
    db: Session, settings: Settings, seeded
) -> None:
    entry = WorkoutEntry(
        entry_date=TARGET,
        exercise_name="Run to delete",
        prescription_json={"exercise_type": "run"},
        actual_json={"distance_km": 5},
        status="completed",
        source="manual",
    )
    db.add(entry)
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings

    async def requests() -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            path = f"/api/v1/history/{TARGET}/workout/{entry.id}"
            assert (await client.delete(path)).status_code == 401
            login = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": settings.bootstrap_email,
                    "password": settings.bootstrap_password.get_secret_value(),
                },
            )
            assert (await client.delete(path)).status_code == 403
            client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
            wrong_date = f"/api/v1/history/{TARGET - timedelta(days=1)}/workout/{entry.id}"
            assert (await client.delete(wrong_date)).status_code == 404
            assert (
                await client.delete(f"/api/v1/history/{TARGET}/workout/{uuid4()}")
            ).status_code == 404
            db.refresh(entry)
            assert entry.status == "completed"
            response = await client.delete(path)
            assert response.status_code == 204 and response.content == b""
            assert (await client.delete(path)).status_code == 204
            assert (await client.patch(path, json={"status": "completed"})).status_code == 404
            assert (await client.get(f"/api/v1/history/{TARGET}")).json()["workouts"] == []
            assert (await client.get("/api/v1/history")).json() == []

    try:
        asyncio.run(requests())
    finally:
        app.dependency_overrides.clear()
