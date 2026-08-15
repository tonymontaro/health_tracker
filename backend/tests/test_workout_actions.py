import asyncio

from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import token_digest
from app.db.models import ApiToken, WorkoutEntry
from app.db.session import get_db
from app.main import app
from app.services.planner.orchestrator import generate_daily_plan
from app.services.recording_dates import available_recording_dates


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
