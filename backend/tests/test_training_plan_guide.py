import asyncio
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import token_digest
from app.db.models import ApiToken, TrainingPlanGuide
from app.db.session import get_db
from app.main import app
from app.schemas.plan import ExerciseProposal, ExerciseType, WorkoutPlanProposal
from app.services.planner.context import build_daily_planner_context, build_profile_snapshot
from app.services.planner.orchestrator import generate_daily_plan
from app.services.planner.two_week import ensure_two_week_plan, latest_two_week_plan
from app.services.training_plan_guide import (
    TrainingPlanGuideError,
    daily_training_plan_guide_context,
    parse_training_plan_csv,
    replace_training_plan_guide,
    training_plan_guide_context,
)

TARGET = date(2026, 8, 18)
FIRST_CSV = """\ufeffDate,Workout
2026-08-18,Treadmill: run 8 km at 6:20/km with 1% incline.
2026-08-19,"Flat dumbbell bench press: 3 sets of 10 reps with 30 kg in each hand.
Pull-ups: 3 sets of 8 reps at bodyweight."
2026-08-20,Rest.
2026-10-04,RACE: run 17.17 km in under 1:30:00.
"""
SECOND_CSV = """Date,Workout
2026-09-01,Easy run for 30 minutes.
2026-09-02,Rest.
"""


def test_parser_accepts_bom_and_multiline_workouts() -> None:
    parsed = parse_training_plan_csv(FIRST_CSV)

    assert parsed.start_date == TARGET
    assert parsed.end_date == date(2026, 10, 4)
    assert len(parsed.days) == 4
    assert "\nPull-ups" in parsed.days[1]["workout"]


@pytest.mark.parametrize(
    ("csv_text", "message"),
    [
        ("Workout\nRest.\n", "Date and Workout"),
        ("Date,Workout\nnot-a-date,Rest.\n", "use YYYY-MM-DD"),
        ("Date,Workout\n2026-08-18,Rest.\n2026-08-18,Run.\n", "appears more than once"),
        ("Date,Workout\n2026-08-18,\n", "missing its workout guidance"),
    ],
)
def test_parser_rejects_invalid_guides(csv_text: str, message: str) -> None:
    with pytest.raises(TrainingPlanGuideError, match=message):
        parse_training_plan_csv(csv_text)


def test_new_upload_replaces_the_single_guide_and_changes_planner_context(
    db: Session,
    seeded,
) -> None:
    first = replace_training_plan_guide(
        db,
        seeded,
        filename="morat_plan.csv",
        csv_text=FIRST_CSV,
    )
    first_id = first.id
    first_hash = first.source_sha256
    context = training_plan_guide_context(db, seeded, TARGET)

    assert context is not None
    daily_context = daily_training_plan_guide_context(db, seeded, TARGET)
    assert daily_context is not None
    assert daily_context["current_day_guidance"] == {
        "plan_date": "2026-08-18",
        "workout": "Treadmill: run 8 km at 6:20/km with 1% incline.",
    }
    assert context["days_in_planning_window"][0]["workout"].startswith("Treadmill")
    assert context["next_key_session_after_window"]["plan_date"] == "2026-10-04"

    second = replace_training_plan_guide(
        db,
        seeded,
        filename="revised_plan.csv",
        csv_text=SECOND_CSV,
    )

    assert second.id == first_id
    assert second.source_sha256 != first_hash
    assert second.source_filename == "revised_plan.csv"
    assert second.start_date == date(2026, 9, 1)
    assert second.guide_json["days"] == [
        {"plan_date": "2026-09-01", "workout": "Easy run for 30 minutes."},
        {"plan_date": "2026-09-02", "workout": "Rest."},
    ]
    assert db.scalar(select(func.count()).select_from(TrainingPlanGuide)) == 1


def test_guide_is_in_daily_context_and_refreshes_an_existing_horizon(
    db: Session,
    settings: Settings,
    seeded,
) -> None:
    first = ensure_two_week_plan(db, settings, TARGET, use_ai=False)
    replace_training_plan_guide(
        db,
        seeded,
        filename="morat_plan.csv",
        csv_text=FIRST_CSV,
    )
    snapshot = build_profile_snapshot(db, seeded, TARGET)
    daily_context = build_daily_planner_context(db, seeded, snapshot, TARGET)
    second = ensure_two_week_plan(db, settings, TARGET, use_ai=False)

    assert daily_context["active_training_plan_guide"]["current_day_guidance"][
        "workout"
    ].startswith("Treadmill")
    assert second.id != first.id
    assert second.revision == 2
    assert second.context_snapshot_json["generation_reason"] == "guide_replacement"
    guide_context = second.context_snapshot_json["current_evidence_and_constraints"][
        "active_training_plan_guide"
    ]
    assert guide_context["guide_revision"]
    assert ensure_two_week_plan(db, settings, TARGET, use_ai=False).id == second.id


def test_guide_replacement_refreshes_the_horizon_without_rewriting_today(
    db: Session,
    settings: Settings,
    seeded,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.planner.orchestrator.current_recording_date",
        lambda _: TARGET,
    )
    daily = generate_daily_plan(db, settings, TARGET, use_ai=False)
    first_horizon = latest_two_week_plan(db, TARGET)
    assert first_horizon is not None
    original_today = first_horizon.plan_json["days"][0]
    replace_training_plan_guide(
        db,
        seeded,
        filename="morat_plan.csv",
        csv_text=FIRST_CSV,
    )

    returned = generate_daily_plan(db, settings, TARGET, use_ai=False)
    second_horizon = latest_two_week_plan(db, TARGET)

    assert returned.id == daily.id
    assert returned.original_plan_json == daily.original_plan_json
    assert second_horizon is not None
    assert second_horizon.revision == 2
    assert second_horizon.plan_json["days"][0]["workout"] == original_today["workout"]
    assert second_horizon.plan_json["days"][0]["nutrition"] == original_today["nutrition"]
    assert second_horizon.context_snapshot_json["current_day_preservation"]["required"] is True


def test_training_plan_endpoint_requires_auth_and_replaces_the_guide(
    db: Session,
    seeded,
) -> None:
    api_settings = Settings(
        DATABASE_URL="postgresql+psycopg://health:health@localhost:55432/health_test",
        SESSION_SECRET="test-session-secret-with-more-than-32-characters",
        _env_file=None,
    )
    raw_token = "training-plan-guide-test-token"
    db.add(
        ApiToken(
            account_id=seeded.account_id,
            name="training plan guide test",
            token_hash=token_digest(raw_token, api_settings),
        )
    )
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: api_settings

    async def make_requests():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            anonymous = await client.put(
                "/api/v1/training-plan",
                json={"filename": "plan.csv", "csv_text": FIRST_CSV},
            )
            invalid = await client.put(
                "/api/v1/training-plan",
                headers={"Authorization": f"Bearer {raw_token}"},
                json={"filename": "bad.csv", "csv_text": "Date,Workout\n2026-08-18,\n"},
            )
            uploaded = await client.put(
                "/api/v1/training-plan",
                headers={"Authorization": f"Bearer {raw_token}"},
                json={"filename": "first.csv", "csv_text": FIRST_CSV},
            )
            replaced = await client.put(
                "/api/v1/training-plan",
                headers={"Authorization": f"Bearer {raw_token}"},
                json={"filename": "second.csv", "csv_text": SECOND_CSV},
            )
            fetched = await client.get(
                "/api/v1/training-plan",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
        return anonymous, invalid, uploaded, replaced, fetched

    try:
        anonymous, invalid, uploaded, replaced, fetched = asyncio.run(make_requests())
    finally:
        app.dependency_overrides.clear()

    assert anonymous.status_code == 401
    assert invalid.status_code == 422
    assert uploaded.status_code == 200
    assert uploaded.json()["row_count"] == 4
    assert replaced.status_code == 200
    assert replaced.json()["source_filename"] == "second.csv"
    assert fetched.status_code == 200
    assert fetched.json()["days"] == replaced.json()["days"]
    assert db.scalar(select(func.count()).select_from(TrainingPlanGuide)) == 1


def test_workout_schema_and_seeded_profile_allow_four_exercises(seeded) -> None:
    exercise = ExerciseProposal(
        exercise_name="Dead bug",
        exercise_type=ExerciseType.BODYWEIGHT,
        external_load_kg=0,
        sets=3,
        reps_per_set=[8, 8, 8],
        rest_seconds=60,
        expected_difficulty=4,
        instructions="Controlled repetitions.",
    )
    payload = {
        "kind": "bodyweight",
        "intensity": "moderate",
        "title": "Four movements",
        "exercises": [exercise.model_dump(mode="json")] * 4,
        "expected_duration_minutes": 40,
        "summary": "Four prescribed movements.",
    }

    workout = WorkoutPlanProposal.model_validate(payload)

    assert len(workout.exercises) == 4
    assert seeded.max_exercises_per_day == 4
    with pytest.raises(ValidationError):
        WorkoutPlanProposal.model_validate(
            {**payload, "exercises": payload["exercises"] + [payload["exercises"][0]]}
        )
