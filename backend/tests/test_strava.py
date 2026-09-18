import asyncio
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.today import _actual_workouts, _status_maps
from app.core.config import Settings, get_settings
from app.db.models import (
    StravaActivity,
    StravaActivityMatch,
    StravaConnection,
    UserAccount,
    WorkoutEntry,
)
from app.db.session import get_db
from app.main import app
from app.services.history import (
    correct_workout_entry,
    history_day,
    history_index,
    serialize_workout,
)
from app.services.metrics import calculate_training_summary
from app.services.strava import (
    StravaClient,
    StravaIntegrationError,
    StravaTokenCipher,
    complete_authorization,
    create_authorization_url,
    disconnect,
    mark_connection_revoked,
    remove_activity,
    rename_imported_activity,
    set_treadmill_incline,
    sync_connection,
    sync_connection_for_date,
    sync_webhook_activity,
)
from app.services.strava_naming import recommended_activity_name

TARGET = date(2026, 8, 10)
NOW = datetime(2026, 8, 10, 18, tzinfo=UTC)


class FakeStrava:
    def __init__(self, activities: list[dict[str, Any]] | None = None) -> None:
        self.activities = activities or []
        self.refresh_calls = 0
        self.revoked_token: str | None = None
        self.activity_list_calls: list[tuple[int, int]] = []
        self.activity_list_windows: list[tuple[int, int | None]] = []
        self.rename_calls: list[tuple[int, str]] = []

    def exchange_code(self, code: str) -> dict[str, Any]:
        assert code == "oauth-code"
        return {
            "access_token": "initial-access-token",
            "refresh_token": "initial-refresh-token",
            "expires_at": int((NOW + timedelta(hours=6)).timestamp()),
            "scope": "read activity:read_all",
            "athlete": {
                "id": 987654,
                "firstname": "Test",
                "lastname": "Athlete",
                "profile": "https://example.test/profile.jpg",
                "email": "must-not-be-stored@example.test",
            },
        }

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        assert refresh_token in {"initial-refresh-token", "rotated-refresh-token"}
        self.refresh_calls += 1
        return {
            "access_token": "rotated-access-token",
            "refresh_token": "rotated-refresh-token",
            "expires_at": int((NOW + timedelta(hours=6)).timestamp()),
        }

    def list_activities(
        self,
        access_token: str,
        *,
        after: int,
        before: int | None,
        page: int,
        per_page: int,
    ) -> list[dict[str, Any]]:
        assert access_token in {"initial-access-token", "rotated-access-token"}
        assert after < int(NOW.timestamp())
        self.activity_list_calls.append((page, per_page))
        self.activity_list_windows.append((after, before))
        matching = [
            item
            for item in self.activities
            if int(datetime.fromisoformat(item["start_date"].replace("Z", "+00:00")).timestamp())
            > after
            and (
                before is None
                or int(
                    datetime.fromisoformat(item["start_date"].replace("Z", "+00:00")).timestamp()
                )
                < before
            )
        ]
        start = (page - 1) * per_page
        return matching[start : start + per_page]

    def get_activity(self, access_token: str, activity_id: int) -> dict[str, Any]:
        return next(item for item in self.activities if item["id"] == activity_id)

    def rename_activity(self, access_token: str, activity_id: int, name: str) -> str:
        self.rename_calls.append((activity_id, name))
        self.get_activity(access_token, activity_id)["name"] = name
        return name

    def revoke(self, token: str) -> None:
        self.revoked_token = token


def strava_settings(settings: Settings) -> Settings:
    return Settings(
        DATABASE_URL=settings.database_url,
        APP_ENV="test",
        SESSION_SECRET="test-session-secret-with-more-than-32-characters",
        STRAVA_CLIENT_ID=12345,
        STRAVA_CLIENT_SECRET="strava-secret",
        _env_file=None,
    )


def activity(
    activity_id: int,
    *,
    name: str = "Evening run",
    sport_type: str = "Run",
    distance: float = 6200,
    moving_time: int = 2280,
    start_date: str = "2026-08-10T16:30:00Z",
) -> dict[str, Any]:
    return {
        "id": activity_id,
        "name": name,
        "sport_type": sport_type,
        "type": "Run" if sport_type == "Run" else "Ride",
        "start_date": start_date,
        "start_date_local": "2026-08-10T18:30:00Z",
        "distance": distance,
        "moving_time": moving_time,
        "elapsed_time": moving_time + 60,
        "total_elevation_gain": 42.5,
        "average_heartrate": 151.2,
        "max_heartrate": 174.0,
        "device_name": "Apple Watch",
        "private": True,
        "map": {"summary_polyline": "must-not-enter-workout-context"},
    }


def authorize(
    db: Session, settings: Settings, account_id, provider: FakeStrava
) -> StravaConnection:
    url = create_authorization_url(db, settings, account_id)
    query = parse_qs(urlparse(url).query)
    assert query["scope"] == ["read,activity:read_all,activity:write"]
    assert query["approval_prompt"] == ["force"]
    return complete_authorization(
        db,
        settings,
        state=query["state"][0],
        code="oauth-code",
        granted_scope="read,activity:read_all",
        provider=provider,
    )


def test_oauth_sync_matches_plan_rotates_tokens_and_is_idempotent(
    db: Session, settings: Settings, seeded
) -> None:
    configured = strava_settings(settings)
    provider = FakeStrava([activity(111)])
    planned = WorkoutEntry(
        entry_date=TARGET,
        planned_recommendation_id="planned-run",
        exercise_name="Outdoor run",
        prescription_json={
            "exercise_type": "run",
            "distance_km": 6,
            "duration_seconds": 2340,
        },
        status="planned",
        source="recommended",
    )
    db.add(planned)
    db.commit()

    connection = authorize(db, configured, seeded.account_id, provider)

    assert connection.access_token_encrypted != "initial-access-token"
    assert connection.refresh_token_encrypted != "initial-refresh-token"
    assert "email" not in connection.athlete_json
    with pytest.raises(StravaIntegrationError, match="expired or is invalid"):
        complete_authorization(
            db,
            configured,
            state="invalid-or-consumed-state",
            code="oauth-code",
            granted_scope="read,activity:read_all",
            provider=provider,
        )
    result = sync_connection(db, configured, connection, provider=provider, now=NOW)

    assert result == {"fetched": 1, "created": 1, "updated": 0, "matched": 1}
    db.refresh(planned)
    assert planned.status == "completed"
    assert planned.source == "strava"
    assert planned.actual_json["distance_km"] == 6.2
    assert planned.actual_json["device_name"] == "Apple Watch"
    assert "map" not in planned.actual_json
    assert db.scalar(select(func.count(StravaActivity.id))) == 1
    assert db.scalar(select(func.count(StravaActivityMatch.id))) == 1

    repeated = sync_connection(
        db, configured, connection, provider=provider, now=NOW + timedelta(minutes=20)
    )
    assert repeated == {"fetched": 1, "created": 0, "updated": 1, "matched": 0}
    assert db.scalar(select(func.count(StravaActivity.id))) == 1
    assert db.scalar(select(func.count(WorkoutEntry.id))) == 1

    connection.access_token_expires_at = NOW
    db.commit()
    sync_connection(db, configured, connection, provider=provider, now=NOW + timedelta(minutes=40))
    assert provider.refresh_calls == 1
    db.refresh(connection)
    cipher = StravaTokenCipher(configured)
    assert cipher.decrypt(connection.access_token_encrypted) == "rotated-access-token"
    assert cipher.decrypt(connection.refresh_token_encrypted) == "rotated-refresh-token"

    remove_activity(db, configured, connection, 111)
    db.refresh(planned)
    assert planned.status == "planned"
    assert planned.source == "recommended"
    assert planned.actual_json is None
    assert db.scalar(select(func.count(StravaActivityMatch.id))) == 0


def test_unmatched_strava_activity_is_recorded_as_completed_workout(
    db: Session, settings: Settings, seeded
) -> None:
    configured = strava_settings(settings)
    provider = FakeStrava(
        [
            activity(
                222,
                name="Indoor bike",
                sport_type="VirtualRide",
                distance=18000,
                moving_time=2700,
            )
        ]
    )
    connection = authorize(db, configured, seeded.account_id, provider)

    result = sync_connection(db, configured, connection, provider=provider, now=NOW)

    assert result["created"] == 1
    assert result["matched"] == 0
    imported = db.scalar(select(WorkoutEntry).where(WorkoutEntry.source == "strava"))
    assert imported
    assert imported.planned_recommendation_id is None
    assert imported.exercise_name == "Indoor bike"
    assert imported.status == "completed"
    assert imported.prescription_json["exercise_type"] == "bike"
    assert imported.actual_json["distance_km"] == 18.0
    indexed_day = next(item for item in history_index(db) if item["date"] == TARGET.isoformat())
    assert indexed_day["workout_count"] == 1
    assert indexed_day["strava_activity_count"] == 1
    connection_id = connection.id
    imported_id = imported.id

    disconnect(db, configured, connection, provider=provider)

    assert provider.revoked_token == "initial-refresh-token"
    assert db.get(StravaConnection, connection_id) is None
    assert db.get(WorkoutEntry, imported_id) is None


def test_sync_respects_per_run_activity_cap(db: Session, settings: Settings, seeded) -> None:
    configured = strava_settings(settings)
    configured.strava_sync_max_activities_per_run = 2
    provider = FakeStrava([activity(501), activity(502), activity(503)])
    connection = authorize(db, configured, seeded.account_id, provider)

    result = sync_connection(db, configured, connection, provider=provider, now=NOW)

    assert result == {"fetched": 2, "created": 2, "updated": 0, "matched": 0}
    assert provider.activity_list_calls == [(1, 2)]
    assert db.scalar(select(func.count(StravaActivity.id))) == 2


def test_on_demand_sync_retrieves_only_the_requested_local_day(
    db: Session, settings: Settings, seeded
) -> None:
    configured = strava_settings(settings)
    provider = FakeStrava(
        [
            activity(601, start_date="2026-08-10T16:30:00Z"),
            activity(602, start_date="2026-08-11T16:30:00Z"),
        ]
    )
    connection = authorize(db, configured, seeded.account_id, provider)

    result = sync_connection_for_date(
        db,
        configured,
        connection,
        TARGET,
        provider=provider,
        now=NOW,
    )

    assert result == {"fetched": 1, "created": 1, "updated": 0, "matched": 0}
    imported_ids = set(db.scalars(select(StravaActivity.strava_activity_id)))
    assert imported_ids == {601}
    db.refresh(connection)
    assert connection.last_synced_at is None
    assert provider.activity_list_windows[-1][1] is not None


def test_generic_strava_strength_session_does_not_invent_strength_volume(
    db: Session, settings: Settings, seeded
) -> None:
    configured = strava_settings(settings)
    provider = FakeStrava(
        [
            activity(
                333,
                name="Traditional strength training",
                sport_type="WeightTraining",
                distance=0,
                moving_time=3600,
            )
        ]
    )
    planned = WorkoutEntry(
        entry_date=TARGET,
        planned_recommendation_id="planned-strength",
        exercise_name="Bench press",
        prescription_json={
            "exercise_type": "strength",
            "load_kg": 100,
            "sets": 3,
            "reps_per_set": [8, 8, 8],
        },
        status="planned",
        source="recommended",
    )
    db.add(planned)
    db.commit()
    connection = authorize(db, configured, seeded.account_id, provider)

    sync_connection(db, configured, connection, provider=provider, now=NOW)

    db.refresh(planned)
    assert planned.status == "completed"
    assert "load_kg" not in planned.actual_json
    assert "reps_per_set" not in planned.actual_json
    assert calculate_training_summary(db, TARGET)["strength_volume_28d"] == {}


def test_strava_deauthorization_removes_provider_data(
    db: Session, settings: Settings, seeded
) -> None:
    configured = strava_settings(settings)
    provider = FakeStrava([activity(444)])
    connection = authorize(db, configured, seeded.account_id, provider)
    sync_connection(db, configured, connection, provider=provider, now=NOW)
    imported = db.scalar(
        select(StravaActivity).where(StravaActivity.connection_id == connection.id)
    )
    assert imported
    connection_id = connection.id
    athlete_id = connection.athlete_id
    imported_id = imported.id

    mark_connection_revoked(db, configured, athlete_id)

    assert db.get(StravaConnection, connection_id) is None
    assert db.get(StravaActivity, imported_id) is None
    assert db.scalar(select(func.count(WorkoutEntry.id))) == 0


class WritableStrava(FakeStrava):
    def exchange_code(self, code: str) -> dict[str, Any]:
        return {**super().exchange_code(code), "scope": "read activity:read_all activity:write"}


def planned_treadmill(db: Session, target: date = TARGET) -> WorkoutEntry:
    entry = WorkoutEntry(
        entry_date=target,
        planned_recommendation_id=f"run-{target}",
        exercise_name="Treadmill easy run",
        prescription_json={"exercise_type": "run", "duration_seconds": 2400, "incline_percent": 3},
        status="planned",
        source="recommended",
    )
    db.add(entry)
    db.commit()
    return entry


@pytest.mark.parametrize("sync_kind", ["scheduled", "day", "webhook"])
def test_auto_name_uses_plan_and_is_not_reapplied(
    db: Session, settings: Settings, seeded, monkeypatch, sync_kind: str
) -> None:
    configured = strava_settings(settings)
    provider = WritableStrava([activity(901)])
    planned = planned_treadmill(db)
    prescription = deepcopy(planned.prescription_json)
    connection = authorize(db, configured, seeded.account_id, provider)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr("app.services.strava.datetime", FixedDatetime)
    if sync_kind == "webhook":
        sync_webhook_activity(
            db,
            configured,
            owner_id=connection.athlete_id,
            activity_id=901,
            aspect_type="create",
            provider=provider,
        )
    elif sync_kind == "day":
        sync_connection_for_date(db, configured, connection, TARGET, provider=provider, now=NOW)
    else:
        sync_connection(db, configured, connection, provider=provider, now=NOW)

    suggested = "Treadmill easy run - 3% incline"
    assert provider.rename_calls == [(901, suggested)]
    db.refresh(planned)
    assert planned.prescription_json == prescription
    assert planned.actual_json["elevation_gain_m"] == 42.5
    assert "incline_percent" not in planned.actual_json
    assert serialize_workout(planned)["actual"]["activity_name"] == suggested
    history = history_day(db, TARGET)["workouts"][0]
    assert history["strava_activity"] == {
        "activity_id": 901,
        "name": suggested,
        "recommended_name": suggested,
        "can_rename": True,
        "can_edit_incline": True,
        "treadmill_incline_percent": None,
    }
    # Even reverting to a generic name on Strava must not trigger another automatic write.
    provider.activities[0]["name"] = "Evening Run"
    sync_connection(db, configured, connection, provider=provider, now=NOW)
    assert len(provider.rename_calls) == 1
    assert history_day(db, TARGET)["workouts"][0]["strava_activity"]["name"] == "Evening Run"


@pytest.mark.parametrize(
    ("start", "renamed"),
    [
        ("2026-08-09T21:59:00Z", False),
        ("2026-08-09T22:00:00Z", True),
        ("2026-08-10T21:59:00Z", True),
        ("2026-08-10T22:00:00Z", False),
    ],
)
def test_auto_name_only_on_current_zurich_date(
    db: Session, settings: Settings, seeded, start: str, renamed: bool
) -> None:
    configured = strava_settings(settings)
    provider = WritableStrava([activity(902, start_date=start)])
    for offset in (-1, 0, 1):
        planned_treadmill(db, TARGET + timedelta(days=offset))
    connection = authorize(db, configured, seeded.account_id, provider)
    sync_connection(db, configured, connection, provider=provider, now=NOW)
    assert bool(provider.rename_calls) is renamed


@pytest.mark.parametrize(
    ("name", "has_plan", "writable"),
    [
        ("My birthday run", True, True),
        ("Evening Run", False, True),
        ("Evening Run", True, False),
    ],
)
def test_auto_name_preserves_custom_unmatched_and_read_only_activities(
    db: Session, settings: Settings, seeded, name: str, has_plan: bool, writable: bool
) -> None:
    configured = strava_settings(settings)
    provider = (WritableStrava if writable else FakeStrava)([activity(903, name=name)])
    if has_plan:
        planned_treadmill(db)
    connection = authorize(db, configured, seeded.account_id, provider)
    sync_connection(db, configured, connection, provider=provider, now=NOW)
    assert provider.rename_calls == []
    assert db.scalar(select(StravaActivity)).name == name
    assert history_day(db, TARGET)["workouts"][0]["strava_activity"]["can_rename"] is writable


def test_auto_name_rechecks_remote_title(db: Session, settings: Settings, seeded) -> None:
    class EditedStrava(WritableStrava):
        def get_activity(self, access_token: str, activity_id: int) -> dict[str, Any]:
            return {**super().get_activity(access_token, activity_id), "name": "Named on my watch"}

    configured = strava_settings(settings)
    provider = EditedStrava([activity(904)])
    planned_treadmill(db)
    connection = authorize(db, configured, seeded.account_id, provider)
    sync_connection(db, configured, connection, provider=provider, now=NOW)
    assert provider.rename_calls == []
    assert db.scalar(select(StravaActivity)).name == "Named on my watch"


def test_auto_name_failure_preserves_import_and_retries_today(
    db: Session, settings: Settings, seeded, monkeypatch
) -> None:
    configured = strava_settings(settings)
    provider = WritableStrava([activity(905)])
    planned = planned_treadmill(db)
    connection = authorize(db, configured, seeded.account_id, provider)
    rename = provider.rename_activity

    def unavailable(*args):
        raise StravaIntegrationError("Strava request failed (429)")

    monkeypatch.setattr(provider, "rename_activity", unavailable)
    sync_connection(db, configured, connection, provider=provider, now=NOW)
    db.refresh(planned)
    assert planned.status == "completed"
    assert planned.actual_json["distance_km"] == 6.2
    assert "renaming failed" in connection.last_error
    assert db.scalar(select(StravaActivity)).name_update_json == {}
    monkeypatch.setattr(provider, "rename_activity", rename)
    sync_connection(db, configured, connection, provider=provider, now=NOW)
    assert len(provider.rename_calls) == 1
    assert connection.last_error is None


def test_manual_name_supports_older_and_corrected_records_without_changing_actuals(
    db: Session, settings: Settings, seeded
) -> None:
    configured = strava_settings(settings)
    provider = WritableStrava([activity(906)])
    planned = planned_treadmill(db)
    connection = authorize(db, configured, seeded.account_id, provider)
    sync_connection(db, configured, connection, provider=provider, now=NOW + timedelta(days=1))
    assert provider.rename_calls == []
    planned.source = "history_correction"
    planned.actual_json = {"summary": "Corrected distance", "distance_km": 5.8}
    planned.difficulty_1_to_10 = 7
    planned.pain_flag = True
    planned.notes = "Saved note"
    db.commit()
    renamed = rename_imported_activity(
        db,
        configured,
        connection,
        906,
        "  Hill practice  ",
        provider=provider,
        now=NOW + timedelta(days=1),
    )
    assert renamed.name == "Hill practice"
    assert renamed.name_update_json["mode"] == "manual"
    db.refresh(planned)
    assert planned.actual_json == {
        "summary": "Corrected distance",
        "distance_km": 5.8,
        "activity_name": "Hill practice",
    }
    assert (planned.source, planned.difficulty_1_to_10, planned.pain_flag, planned.notes) == (
        "history_correction",
        7,
        True,
        "Saved note",
    )
    assert history_day(db, TARGET)["workouts"][0]["strava_activity"]["name"] == "Hill practice"
    rename_imported_activity(db, configured, connection, 906, provider=provider, now=NOW)
    assert provider.rename_calls[-1][1] == "Treadmill easy run - 3% incline"


def test_unmatched_manual_name_and_shared_strength_suggestions(
    db: Session, settings: Settings, seeded
) -> None:
    configured = strava_settings(settings)
    provider = WritableStrava([activity(907, sport_type="WeightTraining", name="Workout")])
    connection = authorize(db, configured, seeded.account_id, provider)
    for index, name in enumerate(["Squat", "Bench press"]):
        db.add(
            WorkoutEntry(
                entry_date=TARGET,
                planned_recommendation_id=f"lift-{index}",
                exercise_name=name,
                prescription_json={"exercise_type": "strength"},
                status="planned",
                source="recommended",
            )
        )
    db.commit()
    sync_connection(db, configured, connection, provider=provider, now=NOW)
    assert len(provider.rename_calls) == 1
    rows = history_day(db, TARGET)["workouts"]
    assert len(rows) == 2
    assert rows[0]["strava_activity"] == rows[1]["strava_activity"]
    assert "Squat" in provider.rename_calls[0][1] and "Bench press" in provider.rename_calls[0][1]
    assert all("load_kg" not in row["actual"] for row in rows)

    provider.activities = [activity(908, sport_type="Ride", name="Morning Ride")]
    sync_connection(db, configured, connection, provider=provider, now=NOW)
    imported = db.scalar(select(StravaActivity).where(StravaActivity.strava_activity_id == 908))
    expected = recommended_activity_name(imported, [])
    rename_imported_activity(db, configured, connection, 908, provider=provider, now=NOW)
    assert provider.rename_calls[-1] == (908, expected)
    generated = db.scalar(
        select(WorkoutEntry).where(WorkoutEntry.planned_recommendation_id.is_(None))
    )
    assert generated.exercise_name == expected


def test_name_update_client_sends_only_name(settings: Settings, monkeypatch) -> None:
    import httpx

    requests = []

    def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        return httpx.Response(200, json={"name": "Treadmill hills"})

    monkeypatch.setattr("httpx.request", request)
    assert (
        StravaClient(strava_settings(settings)).rename_activity(
            "test-token", 999, "Treadmill hills"
        )
        == "Treadmill hills"
    )
    method, url, kwargs = requests[0]
    assert method == "PUT" and url.endswith("/activities/999")
    assert kwargs["json"] == {"name": "Treadmill hills"}


@pytest.mark.parametrize("incline", [0.0, 4.0, 6.5])
def test_actual_incline_overrides_plan_and_survives_sync(
    db: Session, settings: Settings, seeded, incline: float
) -> None:
    configured = strava_settings(settings)
    provider = WritableStrava([activity(910)])
    planned = planned_treadmill(db)
    original = deepcopy(planned.prescription_json)
    connection = authorize(db, configured, seeded.account_id, provider)
    # Historical imports are never automatically renamed.
    sync_connection(db, configured, connection, provider=provider, now=NOW + timedelta(days=1))
    set_treadmill_incline(db, configured, connection, 910, incline)
    planned.difficulty_1_to_10 = 8
    planned.pain_flag = True
    planned.notes = "Original note"
    db.commit()
    sync_connection(db, configured, connection, provider=provider, now=NOW + timedelta(days=1))
    db.refresh(planned)
    assert planned.actual_json["incline_percent"] == incline
    assert planned.actual_json["incline_source"] == "manual"
    assert planned.actual_json["elevation_gain_m"] == 42.5
    assert planned.prescription_json == original
    assert (planned.difficulty_1_to_10, planned.pain_flag, planned.notes) == (
        8,
        True,
        "Original note",
    )
    row = history_day(db, TARGET)["workouts"][0]
    assert (
        row["strava_activity"]["recommended_name"] == f"Treadmill easy run - {incline:g}% incline"
    )
    assert (
        _status_maps(db, TARGET)[1][planned.planned_recommendation_id]["actual"]["incline_percent"]
        == incline
    )
    rename_imported_activity(db, configured, connection, 910, provider=provider, now=NOW)
    assert provider.rename_calls == [(910, f"Treadmill easy run - {incline:g}% incline")]
    set_treadmill_incline(db, configured, connection, 910, None)
    sync_connection(db, configured, connection, provider=provider, now=NOW)
    db.refresh(planned)
    assert "incline_percent" not in planned.actual_json
    assert (
        history_day(db, TARGET)["workouts"][0]["strava_activity"]["recommended_name"]
        == "Treadmill easy run - 3% incline"
    )
    assert len(provider.rename_calls) == 1


def test_incline_preserves_corrections_and_works_without_write_permission(
    db: Session, settings: Settings, seeded
) -> None:
    configured = strava_settings(settings)
    provider = FakeStrava([activity(911)])
    connection = authorize(db, configured, seeded.account_id, provider)
    sync_connection(db, configured, connection, provider=provider, now=NOW)
    entry = db.scalar(select(WorkoutEntry))
    entry.source = "history_correction"
    entry.actual_json = {"summary": "Corrected actual", "distance_km": 5.5}
    db.commit()
    set_treadmill_incline(db, configured, connection, 911, 4)
    sync_connection(db, configured, connection, provider=provider, now=NOW)
    db.refresh(entry)
    assert entry.actual_json == {
        "summary": "Corrected actual",
        "distance_km": 5.5,
        "incline_percent": 4,
        "incline_source": "manual",
    }
    assert entry.source == "history_correction"
    today = _actual_workouts(db, TARGET)[0]
    assert today["strava_activity"]["recommended_name"] == "Treadmill run - 4% incline"
    assert today["strava_activity"]["treadmill_incline_percent"] == 4
    assert today["strava_activity"]["can_rename"] is False
    assert provider.rename_calls == []
    correct_workout_entry(db, entry, {"actual": {"summary": "A later correction"}}, TARGET)
    db.refresh(entry)
    assert entry.actual_json == {
        "summary": "A later correction",
        "incline_percent": 4,
        "incline_source": "manual",
    }


def test_rename_api_auth_validation_scope_ownership_and_failure(
    db: Session, settings: Settings, seeded, monkeypatch
) -> None:
    configured = strava_settings(settings)
    provider = WritableStrava([activity(909)])
    connection = authorize(db, configured, seeded.account_id, provider)
    sync_connection(db, configured, connection, provider=provider, now=NOW)
    connection.access_token_expires_at = datetime.now(UTC) + timedelta(days=2)
    db.commit()
    monkeypatch.setattr("app.services.strava.StravaClient", lambda _: provider)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: configured

    async def requests() -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            path = "/api/v1/integrations/strava/activities/909/name"
            incline_path = "/api/v1/integrations/strava/activities/909/incline"
            assert (await client.put(path, json={})).status_code == 401
            assert (
                await client.patch(incline_path, json={"incline_percent": 4})
            ).status_code == 401
            login = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": settings.bootstrap_email,
                    "password": settings.bootstrap_password.get_secret_value(),
                },
            )
            assert (await client.put(path, json={})).status_code == 403
            assert (
                await client.patch(incline_path, json={"incline_percent": 4})
            ).status_code == 403
            client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
            for invalid in ["", "   ", "x" * 301, "two\nlines", 42]:
                assert (await client.put(path, json={"name": invalid})).status_code == 422
            missing = path.replace("909", "123456")
            assert (await client.put(missing, json={})).status_code == 404
            connection.scopes_json = ["activity:read_all"]
            db.commit()
            assert (await client.put(path, json={})).status_code == 409
            for invalid in [-1, 41, "no", "NaN", "Infinity"]:
                assert (
                    await client.patch(incline_path, json={"incline_percent": invalid})
                ).status_code == 422
            assert (await client.patch(incline_path, json={})).status_code == 422
            incline_response = await client.patch(incline_path, json={"incline_percent": 4})
            assert incline_response.status_code == 200
            assert incline_response.json() == {"incline_percent": 4}
            imported = db.scalar(select(StravaActivity))
            imported.sport_type = "Ride"
            db.commit()
            assert (
                await client.patch(incline_path, json={"incline_percent": 4})
            ).status_code == 422
            imported.sport_type = "Run"
            db.commit()
            connection.scopes_json = ["activity:read_all", "activity:write"]
            db.commit()
            response = await client.put(path, json={"name": "Custom run"})
            assert response.status_code == 200 and response.json() == {"name": "Custom run"}

            def unavailable(*args):
                raise StravaIntegrationError("Private upstream details")

            monkeypatch.setattr(provider, "rename_activity", unavailable)
            failed = await client.put(path, json={"name": "Another name"})
            assert failed.status_code == 502 and "Private" not in failed.text
            assert db.scalar(select(StravaActivity)).name == "Custom run"

            other = UserAccount(email="other@example.test", password_hash="unused")
            db.add(other)
            db.flush()
            connection.account_id = other.id
            db.commit()
            assert (await client.put(path, json={})).status_code == 404
            assert (
                await client.patch(incline_path, json={"incline_percent": 4})
            ).status_code == 404

    try:
        asyncio.run(requests())
    finally:
        app.dependency_overrides.clear()
