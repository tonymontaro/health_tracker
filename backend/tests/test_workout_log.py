import asyncio
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.today import local_today
from app.core.config import Settings, get_settings
from app.core.security import token_digest
from app.db.models import ApiToken, DailyWorkoutLog, WorkoutEntry
from app.db.session import get_db
from app.main import app
from app.schemas.workout_log import ExtractedWorkout, WorkoutLogExtraction
from app.services.history import correct_workout_entry
from app.services.metrics import calculate_training_summary
from app.services.planner.orchestrator import generate_daily_plan
from app.services.workout_log import (
    WorkoutLogExtractionError,
    analyze_daily_workout_log,
    process_daily_workout_log,
)

TARGET = date(2026, 8, 10)


def extraction(
    *, matched_recommendation_id: str | None = None, include_unplanned: bool = True
) -> WorkoutLogExtraction:
    workouts: list[dict[str, Any]] = [
        {
            "workout_name": "Dumbbell bench press",
            "exercise_type": "strength",
            "duration_seconds": None,
            "distance_km": None,
            "load_kg": 32,
            "external_load_kg": None,
            "sets": 3,
            "reps_per_set": [8, 8, 7],
            "average_power_watts": None,
            "average_heartrate_bpm": None,
            "difficulty_1_to_10": 7,
            "pain_flag": False,
            "notes": "Last repetition was slow.",
            "matched_recommendation_id": matched_recommendation_id,
            "match_confidence": 0.96 if matched_recommendation_id else 0,
            "assumptions": [],
        }
    ]
    if include_unplanned:
        workouts.append(
            {
                "workout_name": "Evening yoga",
                "exercise_type": "recovery",
                "duration_seconds": 1200,
                "distance_km": None,
                "load_kg": None,
                "external_load_kg": None,
                "sets": None,
                "reps_per_set": None,
                "average_power_watts": None,
                "average_heartrate_bpm": None,
                "difficulty_1_to_10": 2,
                "pain_flag": False,
                "notes": None,
                "matched_recommendation_id": None,
                "match_confidence": 0,
                "assumptions": [],
            }
        )
    return WorkoutLogExtraction.model_validate(
        {
            "did_no_workout": False,
            "workouts": workouts,
            "summary": "Strength work and yoga were recorded.",
            "assumptions": [],
        }
    )


class FakeExtractor:
    model = "test-workout-extractor"

    def __init__(self, result: WorkoutLogExtraction) -> None:
        self.result = result

    def extract(self, raw_text: str, recommendations: list[dict[str, Any]]) -> WorkoutLogExtraction:
        assert raw_text
        assert recommendations
        return self.result


class FailingExtractor:
    model = "failing-workout-extractor"

    def extract(self, raw_text: str, recommendations: list[dict[str, Any]]) -> WorkoutLogExtraction:
        raise WorkoutLogExtractionError("provider unavailable")


def no_workout_extraction() -> WorkoutLogExtraction:
    return WorkoutLogExtraction.model_validate(
        {
            "did_no_workout": True,
            "workouts": [],
            "summary": "No workout was completed.",
            "assumptions": [],
        }
    )


def test_workout_log_matches_plan_records_unplanned_and_replaces_atomically(
    db: Session, settings: Settings, seeded
) -> None:
    generate_daily_plan(db, settings, TARGET, use_ai=False)
    planned = list(
        db.scalars(
            select(WorkoutEntry).where(
                WorkoutEntry.entry_date == TARGET,
                WorkoutEntry.planned_recommendation_id.is_not(None),
            )
        )
    )
    assert planned and planned[0].planned_recommendation_id
    matched_id = planned[0].planned_recommendation_id

    first = process_daily_workout_log(
        db,
        settings,
        TARGET,
        "Bench press and twenty minutes of yoga.",
        extractor=FakeExtractor(extraction(matched_recommendation_id=matched_id)),
    )

    assert first.matched_recommendation_ids == [matched_id]
    db.refresh(planned[0])
    assert planned[0].status == "completed"
    assert planned[0].source == "ai_workout_log"
    assert planned[0].actual_json == {
        "workout_name": "Dumbbell bench press",
        "exercise_type": "strength",
        "load_kg": 32.0,
        "sets": 3,
        "reps_per_set": [8, 8, 7],
        "assumptions": [],
        "match_confidence": 0.96,
    }
    entries = list(db.scalars(select(WorkoutEntry).where(WorkoutEntry.entry_date == TARGET)))
    generated = [entry for entry in entries if entry.planned_recommendation_id is None]
    assert len(generated) == 1
    assert generated[0].exercise_name == "Evening yoga"
    assert all(
        entry.status == "skipped_by_workout_log"
        for entry in entries
        if entry.planned_recommendation_id and entry.id != planned[0].id
    )
    assert calculate_training_summary(db, TARGET)["completed_exercise_entries_28d"] == 2

    second = process_daily_workout_log(
        db,
        settings,
        TARGET,
        "I did not work out today.",
        extractor=FakeExtractor(no_workout_extraction()),
    )

    assert second.matched_recommendation_ids == []
    entries = list(db.scalars(select(WorkoutEntry).where(WorkoutEntry.entry_date == TARGET)))
    assert all(entry.planned_recommendation_id is not None for entry in entries)
    assert all(entry.status == "skipped_by_workout_log" for entry in entries)
    assert all(entry.actual_json is None for entry in entries)


def test_failed_workout_extraction_leaves_entries_unchanged(
    db: Session, settings: Settings, seeded
) -> None:
    generate_daily_plan(db, settings, TARGET, use_ai=False)
    before = {
        entry.id: (entry.status, entry.actual_json)
        for entry in db.scalars(select(WorkoutEntry).where(WorkoutEntry.entry_date == TARGET))
    }

    with pytest.raises(WorkoutLogExtractionError, match="provider unavailable"):
        process_daily_workout_log(
            db,
            settings,
            TARGET,
            "I trained.",
            extractor=FailingExtractor(),
        )

    after = {
        entry.id: (entry.status, entry.actual_json)
        for entry in db.scalars(select(WorkoutEntry).where(WorkoutEntry.entry_date == TARGET))
    }
    assert after == before
    assert db.scalar(select(DailyWorkoutLog).where(DailyWorkoutLog.log_date == TARGET)) is None


def test_reviewed_workout_analysis_can_correct_delete_and_add_before_submission(
    db: Session, settings: Settings, seeded
) -> None:
    generate_daily_plan(db, settings, TARGET, use_ai=False)
    planned = db.scalar(
        select(WorkoutEntry).where(
            WorkoutEntry.entry_date == TARGET,
            WorkoutEntry.planned_recommendation_id.is_not(None),
        )
    )
    assert planned and planned.planned_recommendation_id
    preview = analyze_daily_workout_log(
        db,
        settings,
        TARGET,
        "Bench press, yoga, and a short run.",
        extractor=FakeExtractor(
            extraction(matched_recommendation_id=planned.planned_recommendation_id)
        ),
    )
    assert db.scalar(select(DailyWorkoutLog).where(DailyWorkoutLog.log_date == TARGET)) is None

    reviewed = preview.extraction.model_copy(deep=True)
    reviewed.workouts = reviewed.workouts[:1]
    reviewed.workouts[0].workout_name = "Corrected dumbbell bench press"
    reviewed.workouts[0].load_kg = 30
    reviewed.workouts.append(
        ExtractedWorkout.model_validate(
            {
                "workout_name": "Short recovery run",
                "exercise_type": "run",
                "duration_seconds": 900,
                "distance_km": 2.1,
                "load_kg": None,
                "external_load_kg": None,
                "sets": None,
                "reps_per_set": None,
                "average_power_watts": None,
                "average_heartrate_bpm": None,
                "difficulty_1_to_10": 3,
                "pain_flag": False,
                "notes": "Added during review.",
                "matched_recommendation_id": None,
                "match_confidence": 0,
                "assumptions": [],
            }
        )
    )
    result = process_daily_workout_log(
        db,
        settings,
        TARGET,
        preview.raw_text,
        extraction=reviewed,
    )

    assert result.extraction.workouts[0].workout_name == "Corrected dumbbell bench press"
    entries = list(db.scalars(select(WorkoutEntry).where(WorkoutEntry.entry_date == TARGET)))
    assert any(entry.exercise_name == "Short recovery run" for entry in entries)
    assert not any(entry.exercise_name == "Evening yoga" for entry in entries)
    workout_log = db.scalar(select(DailyWorkoutLog).where(DailyWorkoutLog.log_date == TARGET))
    assert workout_log and workout_log.model.endswith(":reviewed")


def test_workout_log_reanalysis_preserves_later_history_correction(
    db: Session, settings: Settings, seeded
) -> None:
    generate_daily_plan(db, settings, TARGET, use_ai=False)
    planned = db.scalar(
        select(WorkoutEntry).where(
            WorkoutEntry.entry_date == TARGET,
            WorkoutEntry.planned_recommendation_id.is_not(None),
        )
    )
    assert planned and planned.planned_recommendation_id
    process_daily_workout_log(
        db,
        settings,
        TARGET,
        "I completed the first exercise.",
        extractor=FakeExtractor(
            extraction(
                matched_recommendation_id=planned.planned_recommendation_id,
                include_unplanned=False,
            )
        ),
    )
    correct_workout_entry(
        db,
        planned,
        {
            "status": "completed",
            "actual": {"summary": "Corrected exact performance"},
            "difficulty_1_to_10": 6,
        },
        TARGET,
    )

    process_daily_workout_log(
        db,
        settings,
        TARGET,
        "I did not complete any other workout.",
        extractor=FakeExtractor(no_workout_extraction()),
    )

    db.refresh(planned)
    assert planned.status == "completed"
    assert planned.source == "history_correction"
    assert planned.actual_json == {"summary": "Corrected exact performance"}
    assert planned.workout_log_id is None


def test_workout_log_endpoint_requires_auth_and_records_with_bearer_token(
    db: Session, monkeypatch: pytest.MonkeyPatch, seeded
) -> None:
    api_settings = Settings(
        DATABASE_URL="postgresql+psycopg://health:health@localhost:55432/health_test",
        OPENAI_API_KEY="fake-key",
        SESSION_SECRET="test-session-secret-with-more-than-32-characters",
        _env_file=None,
    )
    current = local_today(api_settings)
    target = current - timedelta(days=1)
    generate_daily_plan(db, api_settings, target, use_ai=False)
    recommendation = db.scalar(
        select(WorkoutEntry).where(
            WorkoutEntry.entry_date == target,
            WorkoutEntry.planned_recommendation_id.is_not(None),
        )
    )
    assert recommendation and recommendation.planned_recommendation_id
    raw_token = "test-workout-log-token"
    db.add(
        ApiToken(
            account_id=seeded.account_id,
            name="test",
            token_hash=token_digest(raw_token, api_settings),
        )
    )
    db.commit()

    def fake_extract(self, raw_text, recommendations):
        return extraction(
            matched_recommendation_id=recommendation.planned_recommendation_id,
            include_unplanned=False,
        )

    monkeypatch.setattr("app.services.workout_log.WorkoutLogExtractor.extract", fake_extract)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: api_settings

    async def make_requests() -> tuple[Response, Response, Response, Response]:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            unauthenticated_response = await client.post(
                f"/api/v1/today/workout/log/analyze?date={target.isoformat()}",
                json={"text": "Bench press."},
            )
            analysis_response = await client.post(
                f"/api/v1/today/workout/log/analyze?date={target.isoformat()}",
                headers={"Authorization": f"Bearer {raw_token}"},
                json={"text": "Bench press."},
            )
            authenticated_response = await client.post(
                f"/api/v1/today/workout/log?date={target.isoformat()}",
                headers={"Authorization": f"Bearer {raw_token}"},
                json={
                    "text": "Bench press.",
                    "extraction": analysis_response.json()["extraction"],
                },
            )
            today_response = await client.get(
                f"/api/v1/today?date={target.isoformat()}",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
        return (
            unauthenticated_response,
            analysis_response,
            authenticated_response,
            today_response,
        )

    try:
        unauthenticated, analysis_response, response, today_response = asyncio.run(make_requests())
    finally:
        app.dependency_overrides.clear()

    assert unauthenticated.status_code == 401
    assert analysis_response.status_code == 200
    assert response.status_code == 200
    assert response.json()["matched_recommendation_ids"] == [
        recommendation.planned_recommendation_id
    ]
    assert today_response.status_code == 200
    assert today_response.json()["date"] == target.isoformat()
    assert today_response.json()["workout_log"]["status"] == "processed"
    assert db.scalar(select(DailyWorkoutLog).where(DailyWorkoutLog.log_date == current)) is None
