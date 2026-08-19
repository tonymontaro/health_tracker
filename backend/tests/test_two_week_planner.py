import asyncio
from datetime import date, timedelta

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import token_digest
from app.db.models import ApiToken, TwoWeekPlan, WorkoutEntry
from app.db.session import get_db
from app.main import app
from app.schemas.two_week_plan import TwoWeekPlanDocument, parse_two_week_plan_document
from app.services.planner.orchestrator import generate_daily_plan
from app.services.planner.two_week import (
    ensure_two_week_plan,
    latest_two_week_plan,
    regenerate_two_week_plan,
    serialize_committed_outlook,
)
from app.services.planner.two_week_fallback import build_fallback_two_week_plan
from app.services.recording_dates import current_recording_date

TARGET = date(2026, 8, 10)


def test_fallback_builds_fourteen_day_horizon_with_seven_committed_days(
    db: Session, settings: Settings, seeded
) -> None:
    row = ensure_two_week_plan(db, settings, TARGET, use_ai=False)
    document = TwoWeekPlanDocument.model_validate(row.plan_json)

    assert document.window_start == TARGET
    assert document.window_end == TARGET + timedelta(days=13)
    assert len(document.days) == 14
    assert [day.commitment for day in document.days] == [
        *(["committed"] * 7),
        *(["provisional"] * 7),
    ]
    assert [day.adaptation for day in document.days] == [
        *(["adaptive"] * 2),
        *(["stable"] * 12),
    ]
    assert all(
        day.workout.kind == "rest" or day.workout.expected_duration_minutes > 0
        for day in document.days[:7]
    )
    assert all("exercises" not in day["workout"] for day in row.plan_json["days"])
    assert all(day.nutrition.meal_template_names for day in document.days[:7])
    thursday = next(day for day in document.days if day.plan_date.strftime("%A") == "Thursday")
    assert thursday.nutrition.meal_template_names == ["Thursday flexible colleague meal"]
    outlook = serialize_committed_outlook(row)
    assert len(outlook["days"]) == 7
    assert all(day["commitment"] == "committed" for day in outlook["days"])
    assert ensure_two_week_plan(db, settings, TARGET, use_ai=False).id == row.id
    assert db.query(TwoWeekPlan).count() == 1


def test_daily_fallback_expands_the_committed_horizon_strategy(
    db: Session, settings: Settings, seeded
) -> None:
    daily = generate_daily_plan(db, settings, TARGET, use_ai=False)
    horizon = db.scalar(select(TwoWeekPlan).where(TwoWeekPlan.anchor_date == TARGET))
    assert horizon is not None
    horizon_day = horizon.plan_json["days"][0]

    daily_workout = daily.current_plan_json["workout"]
    for field in ("kind", "intensity", "title", "expected_duration_minutes", "summary"):
        assert daily_workout[field] == horizon_day["workout"][field]
    assert daily_workout["exercises"]
    assert "exercises" not in horizon_day["workout"]
    daily_meals = [daily.current_plan_json["nutrition"]["meal_1"]["template_name"]]
    if daily.current_plan_json["nutrition"]["meal_2"]:
        daily_meals.append(daily.current_plan_json["nutrition"]["meal_2"]["template_name"])
    assert daily_meals == horizon_day["nutrition"]["meal_template_names"]


def test_daily_revision_preserves_overlapping_committed_day_without_new_evidence(
    db: Session, settings: Settings, seeded
) -> None:
    first = ensure_two_week_plan(db, settings, TARGET, use_ai=False)
    first_document = TwoWeekPlanDocument.model_validate(first.plan_json)

    second = ensure_two_week_plan(db, settings, TARGET + timedelta(days=1), use_ai=False)
    second_document = TwoWeekPlanDocument.model_validate(second.plan_json)

    assert second.previous_plan_id == first.id
    assert second_document.days[0].workout == first_document.days[1].workout
    assert second_document.days[0].nutrition == first_document.days[1].nutrition


def test_manual_regeneration_creates_a_new_revision_and_preserves_the_prior_one(
    db: Session, settings: Settings, seeded
) -> None:
    first = ensure_two_week_plan(db, settings, TARGET, use_ai=False)
    second = regenerate_two_week_plan(
        db,
        settings,
        TARGET,
        preference="Favor batch-friendly meals",
        use_ai=False,
    )

    assert first.revision == 1
    assert second.revision == 2
    assert second.previous_plan_id == first.id
    assert db.query(TwoWeekPlan).count() == 2
    latest = latest_two_week_plan(db, TARGET)
    assert latest is not None
    assert latest.id == second.id
    first_document = TwoWeekPlanDocument.model_validate(first.plan_json)
    second_document = TwoWeekPlanDocument.model_validate(second.plan_json)
    assert second_document.days[0].workout == first_document.days[0].workout
    assert second_document.days[0].nutrition == first_document.days[0].nutrition
    assert any(
        revised.nutrition != original.nutrition
        for original, revised in zip(
            first_document.days[1:7], second_document.days[1:7], strict=True
        )
    )
    assert second.context_snapshot_json["manual_regeneration"] == {
        "requested": True,
        "user_preference": "Favor batch-friendly meals",
        "instruction": (
            "Create a materially refreshed but safe horizon. Treat the optional preference as "
            "high priority after all hard constraints."
        ),
    }
    assert serialize_committed_outlook(second)["revision"] == 2

    following = ensure_two_week_plan(db, settings, TARGET + timedelta(days=1), use_ai=False)
    assert following.previous_plan_id == second.id


def test_regenerate_outlook_endpoint_requires_auth_and_returns_latest_revision(
    db: Session, seeded
) -> None:
    api_settings = Settings(
        DATABASE_URL="postgresql+psycopg://health:health@localhost:55432/health_test",
        OPENAI_API_KEY=None,
        SESSION_SECRET="test-session-secret-with-more-than-32-characters",
        _env_file=None,
    )
    target = current_recording_date(api_settings)
    generate_daily_plan(db, api_settings, target, use_ai=False)
    raw_token = "test-outlook-regeneration-token"
    db.add(
        ApiToken(
            account_id=seeded.account_id,
            name="outlook regeneration test",
            token_hash=token_digest(raw_token, api_settings),
        )
    )
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: api_settings

    async def make_requests():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            unauthenticated = await client.post(
                "/api/v1/today/outlook/regenerate",
                json={"preference": "More cycling"},
            )
            authenticated = await client.post(
                "/api/v1/today/outlook/regenerate",
                headers={"Authorization": f"Bearer {raw_token}"},
                json={"preference": "More cycling"},
            )
            today = await client.get(
                "/api/v1/today",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
        return unauthenticated, authenticated, today

    try:
        unauthenticated, authenticated, today = asyncio.run(make_requests())
    finally:
        app.dependency_overrides.clear()

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 200
    assert authenticated.json()["revision"] == 2
    assert today.status_code == 200
    assert today.json()["outlook"]["revision"] == 2
    latest = latest_two_week_plan(db, target)
    assert latest is not None
    assert latest.context_snapshot_json["manual_regeneration"]["user_preference"] == (
        "More cycling"
    )


def test_missed_session_moves_forward_inside_adaptation_zone(
    db: Session, settings: Settings, seeded
) -> None:
    generate_daily_plan(db, settings, TARGET, use_ai=False)
    first = db.scalar(select(TwoWeekPlan).where(TwoWeekPlan.anchor_date == TARGET))
    assert first is not None
    first_document = TwoWeekPlanDocument.model_validate(first.plan_json)
    entries = list(
        db.scalars(
            select(WorkoutEntry).where(
                WorkoutEntry.entry_date == TARGET,
                WorkoutEntry.planned_recommendation_id.is_not(None),
            )
        )
    )
    assert entries
    for entry in entries:
        entry.status = "skipped"
    db.commit()

    revised = ensure_two_week_plan(db, settings, TARGET + timedelta(days=1), use_ai=False)
    revised_document = TwoWeekPlanDocument.model_validate(revised.plan_json)

    assert revised_document.days[0].workout == first_document.days[0].workout
    assert "missed session" in revised_document.adjustment_summary.lower()


def test_high_effort_session_changes_next_day_to_recovery(
    db: Session, settings: Settings, seeded
) -> None:
    generate_daily_plan(db, settings, TARGET, use_ai=False)
    entry = db.scalar(
        select(WorkoutEntry).where(
            WorkoutEntry.entry_date == TARGET,
            WorkoutEntry.planned_recommendation_id.is_not(None),
        )
    )
    assert entry is not None
    entry.status = "completed"
    entry.difficulty_1_to_10 = 9
    db.commit()

    revised = ensure_two_week_plan(db, settings, TARGET + timedelta(days=1), use_ai=False)
    revised_document = TwoWeekPlanDocument.model_validate(revised.plan_json)

    assert revised_document.days[0].workout.kind == "recovery"
    assert revised_document.days[0].workout.intensity == "very_light"
    assert "high effort" in revised_document.adjustment_summary.lower()


def test_pain_changes_next_day_to_recovery(db: Session, settings: Settings, seeded) -> None:
    generate_daily_plan(db, settings, TARGET, use_ai=False)
    entry = db.scalar(
        select(WorkoutEntry).where(
            WorkoutEntry.entry_date == TARGET,
            WorkoutEntry.planned_recommendation_id.is_not(None),
        )
    )
    assert entry is not None
    entry.status = "completed"
    entry.difficulty_1_to_10 = 5
    entry.pain_flag = True
    db.commit()

    revised = ensure_two_week_plan(db, settings, TARGET + timedelta(days=1), use_ai=False)
    revised_document = TwoWeekPlanDocument.model_validate(revised.plan_json)

    assert revised_document.days[0].workout.kind == "recovery"
    assert "pain" in revised_document.adjustment_summary.lower()


def test_ai_candidate_is_validated_and_persisted(db: Session, monkeypatch, seeded) -> None:
    ai_settings = Settings(
        DATABASE_URL="postgresql+psycopg://health:health@localhost:55432/health_test",
        OPENAI_API_KEY="fake-key",
        SESSION_SECRET="test-session-secret-with-more-than-32-characters",
        _env_file=None,
    )
    profile = seeded
    candidate = build_fallback_two_week_plan(db, profile, TARGET, None)
    calls = 0

    def generate(*args, **kwargs):
        nonlocal calls
        calls += 1
        return candidate

    monkeypatch.setattr(
        "app.services.planner.openai_two_week_planner.OpenAITwoWeekPlanner.generate",
        generate,
    )
    row = ensure_two_week_plan(db, ai_settings, TARGET, use_ai=True)

    assert calls == 1
    assert row.source == "openai"
    assert row.model == ai_settings.openai_planner_model


def test_legacy_detailed_horizon_is_read_as_strategic_context(
    db: Session, settings: Settings, seeded
) -> None:
    row = ensure_two_week_plan(db, settings, TARGET, use_ai=False)
    legacy = dict(row.plan_json)
    legacy["days"] = [dict(day) for day in row.plan_json["days"]]
    for day in legacy["days"]:
        workout = dict(day["workout"])
        workout.pop("requires_gym")
        workout["exercises"] = [{"exercise_name": "Legacy detailed movement"}]
        day["workout"] = workout

    document = parse_two_week_plan_document(legacy)

    assert len(document.days) == 14
    assert all("exercises" not in day.workout.model_dump() for day in document.days)
