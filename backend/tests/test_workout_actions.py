import asyncio

from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import token_digest
from app.db.models import ApiToken, WorkoutEntry
from app.db.session import get_db
from app.main import app
from app.services.coach import CoachMessage
from app.services.planner.orchestrator import generate_daily_plan
from app.services.recording_dates import available_recording_dates
from app.services.workout_feedback import ensure_workout_feedback


def test_recommended_exercise_can_be_completed_or_skipped_independently(
    db: Session, seeded
) -> None:
    api_settings = Settings(
        DATABASE_URL="postgresql+psycopg://health:health@localhost:55432/health_test",
        SESSION_SECRET="test-session-secret-with-more-than-32-characters",
        _env_file=None,
    )
    target = next(day for day in available_recording_dates(api_settings) if day.weekday() == 0)
    generate_daily_plan(db, api_settings, target, use_ai=False)
    entries = list(
        db.scalars(
            select(WorkoutEntry)
            .where(WorkoutEntry.entry_date == target)
            .order_by(WorkoutEntry.created_at)
        )
    )
    assert len(entries) >= 2
    recommendation_id = entries[0].planned_recommendation_id
    assert recommendation_id

    raw_token = "test-workout-action-token"
    db.add(
        ApiToken(
            account_id=seeded.account_id,
            name="workout action test",
            token_hash=token_digest(raw_token, api_settings),
        )
    )
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: api_settings

    async def make_requests() -> tuple[Response, Response, Response, Response]:
        transport = ASGITransport(app=app)
        headers = {"Authorization": f"Bearer {raw_token}"}
        path = f"/api/v1/today/workout/{recommendation_id}"
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            completed_with_default = await client.post(
                f"{path}/confirm?date={target.isoformat()}",
                headers=headers,
                json={},
            )
            invalid = await client.post(
                f"{path}/confirm?date={target.isoformat()}",
                headers=headers,
                json={"difficulty_1_to_10": 11},
            )
            completed = await client.post(
                f"{path}/confirm?date={target.isoformat()}",
                headers=headers,
                json={"difficulty_1_to_10": 7},
            )
            skipped = await client.post(
                f"{path}/skip?date={target.isoformat()}",
                headers=headers,
            )
        return completed_with_default, invalid, completed, skipped

    try:
        completed_with_default, invalid, completed, skipped = asyncio.run(make_requests())
    finally:
        app.dependency_overrides.clear()

    assert completed_with_default.status_code == 200
    assert completed_with_default.json()["difficulty_1_to_10"] == 5
    assert invalid.status_code == 422
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["actual"] == entries[0].prescription_json
    assert completed.json()["difficulty_1_to_10"] == 7
    assert completed.json()["pain_flag"] is False
    assert skipped.status_code == 200
    assert skipped.json()["status"] == "skipped"
    assert skipped.json()["actual"] is None
    assert skipped.json()["difficulty_1_to_10"] is None
    db.refresh(entries[1])
    assert entries[1].status == "planned"


def test_batch_completion_records_a_difficulty_for_each_exercise(
    db: Session, seeded
) -> None:
    api_settings = Settings(
        DATABASE_URL="postgresql+psycopg://health:health@localhost:55432/health_test",
        SESSION_SECRET="test-session-secret-with-more-than-32-characters",
        _env_file=None,
    )
    target = next(day for day in available_recording_dates(api_settings) if day.weekday() == 0)
    generate_daily_plan(db, api_settings, target, use_ai=False)
    entries = list(
        db.scalars(
            select(WorkoutEntry)
            .where(WorkoutEntry.entry_date == target)
            .order_by(WorkoutEntry.created_at)
        )
    )
    assert len(entries) >= 2
    first_id = entries[0].planned_recommendation_id
    second_id = entries[1].planned_recommendation_id
    assert first_id and second_id

    raw_token = "test-workout-batch-token"
    db.add(
        ApiToken(
            account_id=seeded.account_id,
            name="workout batch test",
            token_hash=token_digest(raw_token, api_settings),
        )
    )
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: api_settings

    async def make_request() -> Response:
        transport = ASGITransport(app=app)
        headers = {"Authorization": f"Bearer {raw_token}"}
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                f"/api/v1/today/workout/complete?date={target.isoformat()}",
                headers=headers,
                json={
                    "results": {
                        first_id: {
                            "actual": {"summary": "Completed the first exercise"},
                            "difficulty_1_to_10": 3,
                        },
                        second_id: {
                            "actual": {"summary": "Completed the second exercise"},
                            "difficulty_1_to_10": 8,
                        },
                    },
                    "pain_flag": False,
                    "notes": "Recorded together.",
                },
            )

    try:
        response = asyncio.run(make_request())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    completed = {item["recommendation_id"]: item for item in response.json()}
    assert completed[first_id]["difficulty_1_to_10"] == 3
    assert completed[second_id]["difficulty_1_to_10"] == 8


def test_coach_feedback_refreshes_after_later_exercise_completion(
    db: Session, settings: Settings, seeded, monkeypatch
) -> None:
    target = next(day for day in available_recording_dates(settings) if day.weekday() == 0)
    generate_daily_plan(db, settings, target, use_ai=False)
    entries = list(
        db.scalars(
            select(WorkoutEntry)
            .where(WorkoutEntry.entry_date == target)
            .order_by(WorkoutEntry.created_at)
        )
    )
    assert len(entries) >= 2

    def feedback_for_state(*args, **kwargs) -> CoachMessage:
        facts = kwargs["facts"]
        return CoachMessage(
            message=f"{facts['matched_count']} planned exercises completed.",
            story_kind="none",
            story_topic=None,
        )

    monkeypatch.setattr("app.services.workout_feedback.coach_response", feedback_for_state)

    entries[0].actual_json = dict(entries[0].prescription_json)
    entries[0].difficulty_1_to_10 = 4
    entries[0].status = "completed"
    entries[0].source = "recommended"
    db.commit()

    first_feedback = ensure_workout_feedback(db, settings, target)
    assert first_feedback is not None
    assert first_feedback.message == "1 planned exercises completed."

    entries[1].actual_json = dict(entries[1].prescription_json)
    entries[1].difficulty_1_to_10 = 7
    entries[1].status = "completed"
    entries[1].source = "recommended"
    db.commit()

    refreshed_feedback = ensure_workout_feedback(db, settings, target)
    assert refreshed_feedback is not None
    assert refreshed_feedback.id == first_feedback.id
    assert refreshed_feedback.message == "2 planned exercises completed."
    assert [
        item["status"] for item in refreshed_feedback.context_snapshot_json["recorded_entries"][:2]
    ] == ["completed", "completed"]


def test_completed_strava_exercise_difficulty_can_be_updated_without_replacing_import(
    db: Session, seeded
) -> None:
    api_settings = Settings(
        DATABASE_URL="postgresql+psycopg://health:health@localhost:55432/health_test",
        SESSION_SECRET="test-session-secret-with-more-than-32-characters",
        _env_file=None,
    )
    target = next(day for day in available_recording_dates(api_settings) if day.weekday() == 0)
    generate_daily_plan(db, api_settings, target, use_ai=False)
    entry = db.scalar(
        select(WorkoutEntry)
        .where(WorkoutEntry.entry_date == target)
        .order_by(WorkoutEntry.created_at)
    )
    assert entry is not None
    imported_actual = {
        "distance_km": 6.2,
        "duration_seconds": 2280,
        "device_name": "Apple Watch",
        "completion_evidence": "strava_activity",
        "strava": {"activity_id": 123456},
    }
    entry.actual_json = imported_actual
    entry.status = "completed"
    entry.source = "strava"

    raw_token = "test-strava-difficulty-token"
    db.add(
        ApiToken(
            account_id=seeded.account_id,
            name="strava difficulty test",
            token_hash=token_digest(raw_token, api_settings),
        )
    )
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: api_settings

    async def make_requests() -> tuple[Response, Response]:
        transport = ASGITransport(app=app)
        headers = {"Authorization": f"Bearer {raw_token}"}
        path = f"/api/v1/today/workout/{entry.id}/difficulty?date={target.isoformat()}"
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            updated = await client.patch(
                path,
                headers=headers,
                json={"difficulty_1_to_10": 8},
            )
            invalid = await client.patch(
                path,
                headers=headers,
                json={"difficulty_1_to_10": 11},
            )
        return updated, invalid

    try:
        updated, invalid = asyncio.run(make_requests())
    finally:
        app.dependency_overrides.clear()

    assert updated.status_code == 200
    assert updated.json()["difficulty_1_to_10"] == 8
    assert updated.json()["source"] == "strava"
    assert updated.json()["status"] == "completed"
    assert updated.json()["actual"] == imported_actual
    assert invalid.status_code == 422
    db.refresh(entry)
    assert entry.difficulty_1_to_10 == 8
    assert entry.source == "strava"
    assert entry.actual_json == imported_actual
