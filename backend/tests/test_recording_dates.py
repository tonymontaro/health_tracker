import asyncio
from copy import deepcopy
from datetime import UTC, date, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import token_digest
from app.db.models import ApiToken, DailyPlan, WorkoutEntry
from app.db.session import get_db
from app.main import app
from app.schemas.plan import DailyPlanDocument, DailyPlanProposal
from app.services.planner.orchestrator import generate_daily_plan
from app.services.recording_dates import (
    current_recording_date,
    daily_plan_calendar,
    resolve_recording_date,
)

TODAY = date(2026, 9, 19)


@pytest.fixture
def fixed_today(monkeypatch):
    monkeypatch.setattr("app.services.recording_dates.current_recording_date", lambda _: TODAY)
    monkeypatch.setattr("app.api.today.current_recording_date", lambda _: TODAY)


def test_recording_date_uses_zurich_day_at_utc_midnight_boundary(settings, monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 18, 22, 30, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr("app.services.recording_dates.datetime", FixedDatetime)
    assert current_recording_date(settings) == TODAY


def test_calendar_lists_only_saved_past_plans_and_actual_exercise(
    db: Session, settings: Settings, seeded, fixed_today
) -> None:
    oldest = date(2025, 12, 31)
    saved_dates = [oldest, date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3), TODAY]
    for target in [*saved_dates, date(2026, 9, 20)]:
        generate_daily_plan(db, settings, target, use_ai=False)
    for target, status, source in [
        (date(2026, 9, 1), "completed", "strava"),
        (date(2026, 9, 1), "completed", "manual"),
        (date(2026, 9, 2), "partial", "workout_log"),
        (date(2026, 9, 3), "skipped", "manual"),
        (date(2026, 9, 4), "completed", "strava"),
    ]:
        db.add(
            WorkoutEntry(
                entry_date=target,
                exercise_name="Run",
                prescription_json={},
                status=status,
                source=source,
            )
        )
    db.flush()

    result = daily_plan_calendar(db, settings, None)

    assert result == {
        "today": TODAY.isoformat(),
        "month": "2026-09-01",
        "first_plan_date": oldest.isoformat(),
        "days": [
            {"date": "2026-09-01", "has_plan": True, "exercise_performed": True},
            {"date": "2026-09-02", "has_plan": True, "exercise_performed": True},
            {"date": "2026-09-03", "has_plan": True, "exercise_performed": False},
            {"date": "2026-09-04", "has_plan": False, "exercise_performed": True},
            {"date": TODAY.isoformat(), "has_plan": True, "exercise_performed": False},
        ],
    }
    assert daily_plan_calendar(db, settings, oldest)["days"] == [
        {"date": oldest.isoformat(), "has_plan": True, "exercise_performed": False}
    ]
    assert daily_plan_calendar(db, settings, date(2026, 8, 12))["days"] == []
    assert daily_plan_calendar(db, settings, date(2026, 10, 1))["days"] == []
    assert resolve_recording_date(db, settings, oldest) == oldest
    assert resolve_recording_date(db, settings, None) == TODAY
    for unavailable in [date(2026, 9, 4), date(2026, 9, 20)]:
        with pytest.raises(ValueError, match="saved daily plan"):
            resolve_recording_date(db, settings, unavailable)


def test_calendar_without_plans_and_leap_month(db: Session, settings, seeded, fixed_today):
    assert daily_plan_calendar(db, settings, date(2024, 2, 10)) == {
        "today": TODAY.isoformat(),
        "month": "2024-02-01",
        "first_plan_date": None,
        "days": [],
    }
    generate_daily_plan(db, settings, date(2024, 2, 29), use_ai=False)
    generate_daily_plan(db, settings, date(2024, 3, 1), use_ai=False)
    assert daily_plan_calendar(db, settings, date(2024, 2, 1))["days"] == [
        {"date": "2024-02-29", "has_plan": True, "exercise_performed": False}
    ]


def test_calendar_and_old_daily_pages_require_auth_and_never_generate_missing_plans(
    db: Session, settings: Settings, seeded, fixed_today, monkeypatch
) -> None:
    target = date(2025, 12, 29)
    plan = generate_daily_plan(db, settings, target, use_ai=False)
    legacy_action = {
        "action": "Legacy preparation",
        "active_minutes": 5,
        "when": "Evening",
    }
    legacy = {**plan.current_plan_json, "prep_actions": [legacy_action]}
    plan.current_plan_json = legacy
    plan.original_plan_json = deepcopy(legacy)
    assert (
        DailyPlanDocument.model_validate(legacy).prep_actions[0].action == legacy_action["action"]
    )
    assert "prep_actions" not in DailyPlanProposal.model_json_schema()["properties"]
    entry = db.scalar(select(WorkoutEntry).where(WorkoutEntry.entry_date == target))
    assert entry is not None
    raw_token = "test-calendar-token"
    db.add(
        ApiToken(
            account_id=seeded.account_id,
            name="calendar test",
            token_hash=token_digest(raw_token, settings),
        )
    )
    db.commit()
    original = deepcopy(plan.original_plan_json)

    def unexpected_generation(*args, **kwargs):
        raise AssertionError("Browsing saved history must not generate a daily plan")

    monkeypatch.setattr("app.api.today.generate_daily_plan", unexpected_generation)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings

    async def make_requests():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            assert (await client.get("/api/v1/today/calendar")).status_code == 401
            client.headers["Authorization"] = f"Bearer {raw_token}"
            calendar = await client.get("/api/v1/today/calendar?month=2025-12-01")
            assert calendar.status_code == 200
            assert calendar.json()["days"] == [
                {"date": target.isoformat(), "has_plan": True, "exercise_performed": False}
            ]
            assert (await client.get("/api/v1/today/calendar?month=invalid")).status_code == 422
            for path in ["/api/v1/today", "/api/v1/today/details"]:
                response = await client.get(path, params={"date": target.isoformat()})
                assert response.status_code == 200
                if path == "/api/v1/today":
                    assert response.json()["date"] == target.isoformat()
                    assert response.json()["current_date"] == TODAY.isoformat()
                    assert "next_action" not in response.json()
                    assert response.json()["workout"] == original["workout"]
                    assert response.json()["nutrition"] == original["nutrition"]
                else:
                    assert response.json()["original_plan"] == original
                for unavailable in ["2025-12-28", "2026-09-20"]:
                    assert (await client.get(path, params={"date": unavailable})).status_code == 422
            recorded = await client.post(
                f"/api/v1/today/workout/{entry.planned_recommendation_id}/confirm",
                params={"date": target.isoformat()},
                json={"difficulty_1_to_10": 6},
            )
            assert recorded.status_code == 200
            calendar = await client.get("/api/v1/today/calendar?month=2025-12-01")
            assert calendar.json()["days"][0]["exercise_performed"] is True

    try:
        asyncio.run(make_requests())
    finally:
        app.dependency_overrides.clear()
    db.refresh(plan)
    assert plan.original_plan_json == original
    assert plan.current_plan_json == legacy
    assert db.scalar(select(func.count()).select_from(DailyPlan)) == 1
