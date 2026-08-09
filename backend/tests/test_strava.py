from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    StravaActivity,
    StravaActivityMatch,
    StravaConnection,
    WorkoutEntry,
)
from app.services.history import history_index
from app.services.metrics import calculate_training_summary
from app.services.strava import (
    StravaIntegrationError,
    StravaTokenCipher,
    complete_authorization,
    create_authorization_url,
    disconnect,
    mark_connection_revoked,
    remove_activity,
    sync_connection,
    sync_connection_for_date,
)

TARGET = date(2026, 8, 10)
NOW = datetime(2026, 8, 10, 18, tzinfo=UTC)


class FakeStrava:
    def __init__(self, activities: list[dict[str, Any]] | None = None) -> None:
        self.activities = activities or []
        self.refresh_calls = 0
        self.revoked_token: str | None = None
        self.activity_list_calls: list[tuple[int, int]] = []
        self.activity_list_windows: list[tuple[int, int | None]] = []

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
    assert query["scope"] == ["read,activity:read_all"]
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
