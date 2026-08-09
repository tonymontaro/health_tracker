import base64
import hmac
import logging
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import Any, Protocol
from urllib.parse import urlencode
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import new_token, token_digest
from app.db.models import (
    StravaActivity,
    StravaActivityMatch,
    StravaConnection,
    StravaOAuthState,
    UserProfile,
    WorkoutEntry,
)
from app.services.metrics import recalculate_derived_summary

logger = logging.getLogger(__name__)

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_REVOKE_URL = "https://www.strava.com/oauth/revoke"
STRAVA_API_URL = "https://www.strava.com/api/v3"
REQUIRED_SCOPE = "activity:read_all"

RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}
BIKE_TYPES = {
    "EBikeRide",
    "EMountainBikeRide",
    "GravelRide",
    "Handcycle",
    "MountainBikeRide",
    "Ride",
    "Velomobile",
    "VirtualRide",
}
STRENGTH_TYPES = {
    "Crossfit",
    "HighIntensityIntervalTraining",
    "WeightTraining",
    "Workout",
}
MATCHABLE_STATUSES = {"planned", "skipped_assumed", "skipped_by_workout_log"}


class StravaIntegrationError(RuntimeError):
    pass


class StravaProvider(Protocol):
    def exchange_code(self, code: str) -> dict[str, Any]: ...

    def refresh(self, refresh_token: str) -> dict[str, Any]: ...

    def list_activities(
        self, access_token: str, *, after: int, page: int, per_page: int
    ) -> list[dict[str, Any]]: ...

    def get_activity(self, access_token: str, activity_id: int) -> dict[str, Any]: ...

    def revoke(self, token: str) -> None: ...


class StravaClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.strava_configured:
            raise StravaIntegrationError("Strava client credentials are not configured")
        self.client_id = settings.strava_client_id
        self.client_secret = settings.strava_secret_value
        self.timeout = httpx.Timeout(20.0)

    def exchange_code(self, code: str) -> dict[str, Any]:
        return self._json(
            self._request(
                "POST",
                STRAVA_TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                },
                timeout=self.timeout,
            )
        )

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        return self._json(
            self._request(
                "POST",
                STRAVA_TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=self.timeout,
            )
        )

    def list_activities(
        self, access_token: str, *, after: int, page: int, per_page: int
    ) -> list[dict[str, Any]]:
        payload = self._json(
            self._request(
                "GET",
                f"{STRAVA_API_URL}/athlete/activities",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"after": after, "page": page, "per_page": per_page},
                timeout=self.timeout,
            )
        )
        if not isinstance(payload, list):
            raise StravaIntegrationError("Strava returned an invalid activity list")
        return payload

    def get_activity(self, access_token: str, activity_id: int) -> dict[str, Any]:
        payload = self._json(
            self._request(
                "GET",
                f"{STRAVA_API_URL}/activities/{activity_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self.timeout,
            )
        )
        if not isinstance(payload, dict):
            raise StravaIntegrationError("Strava returned an invalid activity")
        return payload

    def revoke(self, token: str) -> None:
        response = self._request(
            "POST",
            STRAVA_REVOKE_URL,
            auth=(str(self.client_id), str(self.client_secret)),
            data={"token": token, "token_type_hint": "refresh_token"},
            timeout=self.timeout,
        )
        self._raise_for_status(response)

    @staticmethod
    def _request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return httpx.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise StravaIntegrationError("Strava could not be reached") from exc

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        StravaClient._raise_for_status(response)
        try:
            return response.json()
        except ValueError as exc:
            raise StravaIntegrationError("Strava returned invalid JSON") from exc

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return
        message = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                message = str(payload.get("message") or payload.get("error") or "")
        except ValueError:
            pass
        detail = f": {message[:300]}" if message else ""
        raise StravaIntegrationError(f"Strava request failed ({response.status_code}){detail}")


class StravaTokenCipher:
    def __init__(self, settings: Settings) -> None:
        secret = settings.session_secret.get_secret_value().encode()
        derived = hmac.new(secret, b"health-autopilot/strava-token", sha256).digest()
        self.fernet = Fernet(base64.urlsafe_b64encode(derived))

    def encrypt(self, token: str) -> str:
        return self.fernet.encrypt(token.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self.fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise StravaIntegrationError(
                "Stored Strava credentials cannot be decrypted. Reconnect Strava."
            ) from exc


def create_authorization_url(db: Session, settings: Settings, account_id: UUID) -> str:
    if not settings.strava_configured:
        raise StravaIntegrationError("Strava client credentials are not configured")
    now = datetime.now(UTC)
    db.execute(
        delete(StravaOAuthState).where(
            (StravaOAuthState.account_id == account_id) | (StravaOAuthState.expires_at <= now)
        )
    )
    raw_state = new_token()
    db.add(
        StravaOAuthState(
            account_id=account_id,
            state_hash=token_digest(raw_state, settings),
            expires_at=now + timedelta(minutes=10),
        )
    )
    db.commit()
    redirect_uri = f"{settings.api_base_url.rstrip('/')}/api/v1/integrations/strava/callback"
    query = urlencode(
        {
            "client_id": settings.strava_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "approval_prompt": "force",
            "scope": f"read,{REQUIRED_SCOPE}",
            "state": raw_state,
        }
    )
    return f"{STRAVA_AUTH_URL}?{query}"


def complete_authorization(
    db: Session,
    settings: Settings,
    *,
    state: str,
    code: str,
    granted_scope: str,
    provider: StravaProvider | None = None,
) -> StravaConnection:
    now = datetime.now(UTC)
    oauth_state = db.scalar(
        select(StravaOAuthState).where(
            StravaOAuthState.state_hash == token_digest(state, settings),
            StravaOAuthState.expires_at > now,
        )
    )
    if oauth_state is None:
        raise StravaIntegrationError("The Strava authorization request expired or is invalid")
    account_id = oauth_state.account_id
    db.delete(oauth_state)
    db.commit()

    scopes = _parse_scopes(granted_scope)
    if REQUIRED_SCOPE not in scopes:
        raise StravaIntegrationError(
            "Strava activity access was not granted. Reconnect and allow activity access."
        )
    token_payload = (provider or StravaClient(settings)).exchange_code(code)
    athlete = token_payload.get("athlete")
    if not isinstance(athlete, dict) or not athlete.get("id"):
        raise StravaIntegrationError("Strava did not return an athlete account")
    access_token = token_payload.get("access_token")
    refresh_token = token_payload.get("refresh_token")
    expires_at = token_payload.get("expires_at")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str) or not expires_at:
        raise StravaIntegrationError("Strava did not return complete OAuth credentials")
    response_scopes = _parse_scopes(str(token_payload.get("scope") or ""))
    if response_scopes:
        scopes = response_scopes
    if REQUIRED_SCOPE not in scopes:
        raise StravaIntegrationError("The Strava token is missing activity:read_all access")

    athlete_id = int(athlete["id"])
    owner = db.scalar(select(StravaConnection).where(StravaConnection.athlete_id == athlete_id))
    if owner and owner.account_id != account_id:
        raise StravaIntegrationError("This Strava athlete is already connected")
    connection = db.scalar(
        select(StravaConnection).where(StravaConnection.account_id == account_id)
    )
    cipher = StravaTokenCipher(settings)
    values = {
        "athlete_id": athlete_id,
        "athlete_json": _safe_athlete(athlete),
        "scopes_json": sorted(scopes),
        "access_token_encrypted": cipher.encrypt(access_token),
        "refresh_token_encrypted": cipher.encrypt(refresh_token),
        "access_token_expires_at": datetime.fromtimestamp(int(expires_at), UTC),
        "status": "connected",
        "last_error": None,
    }
    if connection is None:
        connection = StravaConnection(account_id=account_id, **values)
        db.add(connection)
    else:
        for field, value in values.items():
            setattr(connection, field, value)
    db.commit()
    db.refresh(connection)
    return connection


def sync_connection(
    db: Session,
    settings: Settings,
    connection: StravaConnection,
    *,
    provider: StravaProvider | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    active_provider = provider or StravaClient(settings)
    current = now or datetime.now(UTC)
    try:
        access_token = _valid_access_token(db, settings, connection, active_provider, current)
        days = (
            settings.strava_initial_sync_days
            if connection.last_synced_at is None
            else settings.strava_sync_lookback_days
        )
        after = int((current - timedelta(days=days)).timestamp())
        payloads: list[dict[str, Any]] = []
        activity_limit = settings.strava_sync_max_activities_per_run
        for page in range(1, 51):
            per_page = min(200, activity_limit - len(payloads))
            batch = active_provider.list_activities(
                access_token, after=after, page=page, per_page=per_page
            )
            payloads.extend(batch)
            if len(batch) < per_page or len(payloads) >= activity_limit:
                break
        else:
            raise StravaIntegrationError("Strava activity pagination exceeded the safe limit")

        locked_connection = db.scalar(
            select(StravaConnection).where(StravaConnection.id == connection.id).with_for_update()
        )
        if locked_connection is None:
            raise StravaIntegrationError("The Strava connection no longer exists")
        connection = locked_connection
        created = 0
        updated = 0
        matched = 0
        affected_dates: set[date] = set()
        for payload in payloads:
            activity, was_created = _upsert_activity(db, settings, connection, payload, current)
            activity_matches = _materialize_activity(db, activity)
            created += int(was_created)
            updated += int(not was_created)
            matched += activity_matches
            affected_dates.add(activity.activity_date)
        profile = db.scalar(select(UserProfile))
        if profile and affected_dates:
            summary_date = current.astimezone(ZoneInfo(settings.app_timezone)).date()
            recalculate_derived_summary(db, profile, max(summary_date, *affected_dates))
        connection.last_synced_at = current
        connection.last_error = None
        connection.status = "connected"
        db.commit()
        return {
            "fetched": len(payloads),
            "created": created,
            "updated": updated,
            "matched": matched,
        }
    except Exception as exc:
        db.rollback()
        failed_connection = db.get(StravaConnection, connection.id)
        if failed_connection:
            failed_connection.last_error = f"{type(exc).__name__}: {str(exc)[:1000]}"
            if "401" in str(exc):
                failed_connection.status = "reauthorization_required"
            db.commit()
        raise


def sync_connection_if_due(
    db: Session,
    settings: Settings,
    connection: StravaConnection,
    *,
    provider: StravaProvider | None = None,
    now: datetime | None = None,
) -> dict[str, int] | None:
    current = now or datetime.now(UTC)
    if connection.status != "connected":
        return None
    if connection.last_synced_at and connection.last_synced_at > current - timedelta(
        minutes=settings.strava_sync_interval_minutes
    ):
        return None
    return sync_connection(db, settings, connection, provider=provider, now=current)


def sync_all_connections(db: Session, settings: Settings) -> dict[str, int]:
    totals = {"connections": 0, "fetched": 0, "created": 0, "updated": 0, "matched": 0}
    if not settings.strava_configured:
        return totals
    connections = list(
        db.scalars(select(StravaConnection).where(StravaConnection.status == "connected"))
    )
    for connection in connections:
        try:
            result = sync_connection_if_due(db, settings, connection)
        except Exception:
            logger.exception("Scheduled Strava sync failed for connection %s", connection.id)
            continue
        if result is None:
            continue
        totals["connections"] += 1
        for key in ("fetched", "created", "updated", "matched"):
            totals[key] += result[key]
    return totals


def sync_webhook_activity(
    db: Session,
    settings: Settings,
    *,
    owner_id: int,
    activity_id: int,
    aspect_type: str,
    provider: StravaProvider | None = None,
) -> None:
    connection = db.scalar(select(StravaConnection).where(StravaConnection.athlete_id == owner_id))
    if connection is None:
        return
    if aspect_type == "delete":
        remove_activity(db, settings, connection, activity_id)
        return
    active_provider = provider or StravaClient(settings)
    current = datetime.now(UTC)
    access_token = _valid_access_token(db, settings, connection, active_provider, current)
    payload = active_provider.get_activity(access_token, activity_id)
    locked_connection = db.scalar(
        select(StravaConnection).where(StravaConnection.id == connection.id).with_for_update()
    )
    if locked_connection is None:
        return
    connection = locked_connection
    activity, _ = _upsert_activity(db, settings, connection, payload, current)
    _materialize_activity(db, activity)
    profile = db.scalar(select(UserProfile))
    if profile:
        summary_date = current.astimezone(ZoneInfo(settings.app_timezone)).date()
        recalculate_derived_summary(db, profile, max(summary_date, activity.activity_date))
    connection.last_error = None
    db.commit()


def mark_connection_revoked(db: Session, settings: Settings, owner_id: int) -> None:
    connection = db.scalar(select(StravaConnection).where(StravaConnection.athlete_id == owner_id))
    if connection is None:
        return
    activities = list(
        db.scalars(select(StravaActivity).where(StravaActivity.connection_id == connection.id))
    )
    for activity in activities:
        _remove_materialized_activity(db, activity)
    profile = db.scalar(select(UserProfile))
    if profile and activities:
        recalculate_derived_summary(
            db,
            profile,
            datetime.now(ZoneInfo(settings.app_timezone)).date(),
        )
    db.delete(connection)
    db.commit()


def disconnect(
    db: Session,
    settings: Settings,
    connection: StravaConnection,
    *,
    provider: StravaProvider | None = None,
) -> None:
    cipher = StravaTokenCipher(settings)
    refresh_token = cipher.decrypt(connection.refresh_token_encrypted)
    (provider or StravaClient(settings)).revoke(refresh_token)
    activities = list(
        db.scalars(select(StravaActivity).where(StravaActivity.connection_id == connection.id))
    )
    for activity in activities:
        _remove_materialized_activity(db, activity)
    profile = db.scalar(select(UserProfile))
    if profile and activities:
        recalculate_derived_summary(
            db,
            profile,
            datetime.now(ZoneInfo(settings.app_timezone)).date(),
        )
    db.delete(connection)
    db.commit()


def remove_activity(
    db: Session,
    settings: Settings,
    connection: StravaConnection,
    activity_id: int,
) -> None:
    activity = db.scalar(
        select(StravaActivity).where(
            StravaActivity.connection_id == connection.id,
            StravaActivity.strava_activity_id == activity_id,
        )
    )
    if activity is None:
        return
    affected_date = activity.activity_date
    _remove_materialized_activity(db, activity)
    db.delete(activity)
    profile = db.scalar(select(UserProfile))
    if profile:
        summary_date = datetime.now(ZoneInfo(settings.app_timezone)).date()
        recalculate_derived_summary(db, profile, max(summary_date, affected_date))
    db.commit()


def serialize_connection(
    db: Session, connection: StravaConnection | None, settings: Settings
) -> dict[str, Any]:
    if connection is None:
        return {
            "configured": settings.strava_configured,
            "connected": False,
            "status": "not_connected",
            "athlete": None,
            "scopes": [],
            "last_synced_at": None,
            "last_error": None,
            "activity_count": 0,
        }
    count = db.scalar(
        select(func.count(StravaActivity.id)).where(StravaActivity.connection_id == connection.id)
    )
    athlete = connection.athlete_json
    return {
        "configured": settings.strava_configured,
        "connected": connection.status == "connected",
        "status": connection.status,
        "athlete": {
            "id": connection.athlete_id,
            "name": " ".join(
                part for part in (athlete.get("firstname"), athlete.get("lastname")) if part
            ),
            "profile": athlete.get("profile"),
        },
        "scopes": connection.scopes_json,
        "last_synced_at": (
            connection.last_synced_at.isoformat() if connection.last_synced_at else None
        ),
        "last_error": connection.last_error,
        "activity_count": int(count or 0),
    }


def _valid_access_token(
    db: Session,
    settings: Settings,
    connection: StravaConnection,
    provider: StravaProvider,
    now: datetime,
) -> str:
    cipher = StravaTokenCipher(settings)
    if connection.access_token_expires_at > now + timedelta(hours=1):
        return cipher.decrypt(connection.access_token_encrypted)

    locked_connection = db.scalar(
        select(StravaConnection)
        .where(StravaConnection.id == connection.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_connection is None:
        raise StravaIntegrationError("The Strava connection no longer exists")
    if locked_connection.access_token_expires_at > now + timedelta(hours=1):
        return cipher.decrypt(locked_connection.access_token_encrypted)

    refresh_token = cipher.decrypt(locked_connection.refresh_token_encrypted)
    payload = provider.refresh(refresh_token)
    access_token = payload.get("access_token")
    rotated_refresh_token = payload.get("refresh_token")
    expires_at = payload.get("expires_at")
    if (
        not isinstance(access_token, str)
        or not isinstance(rotated_refresh_token, str)
        or not isinstance(expires_at, int | float)
    ):
        raise StravaIntegrationError("Strava returned an incomplete token refresh")
    locked_connection.access_token_encrypted = cipher.encrypt(access_token)
    locked_connection.refresh_token_encrypted = cipher.encrypt(rotated_refresh_token)
    locked_connection.access_token_expires_at = datetime.fromtimestamp(int(expires_at), UTC)
    db.commit()
    return access_token


def _upsert_activity(
    db: Session,
    settings: Settings,
    connection: StravaConnection,
    payload: dict[str, Any],
    synced_at: datetime,
) -> tuple[StravaActivity, bool]:
    try:
        activity_id = int(payload["id"])
        start_at = _parse_datetime(str(payload["start_date"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise StravaIntegrationError(
            "Strava returned an activity without a valid ID or date"
        ) from exc
    entry_date = start_at.astimezone(ZoneInfo(settings.app_timezone)).date()
    activity = db.scalar(
        select(StravaActivity).where(
            StravaActivity.connection_id == connection.id,
            StravaActivity.strava_activity_id == activity_id,
        )
    )
    created = activity is None
    values = {
        "activity_date": entry_date,
        "start_at": start_at,
        "name": str(payload.get("name") or payload.get("sport_type") or "Strava activity")[:300],
        "sport_type": str(payload.get("sport_type") or payload.get("type") or "Workout")[:80],
        "activity_type": str(payload.get("type") or payload.get("sport_type") or "Workout")[:80],
        "distance_m": _number(payload.get("distance")),
        "moving_time_seconds": _integer(payload.get("moving_time")),
        "elapsed_time_seconds": _integer(payload.get("elapsed_time")),
        "elevation_gain_m": _number(payload.get("total_elevation_gain")),
        "average_heartrate": _optional_number(payload.get("average_heartrate")),
        "max_heartrate": _optional_number(payload.get("max_heartrate")),
        "average_watts": _optional_number(payload.get("average_watts")),
        "device_name": str(payload["device_name"])[:160] if payload.get("device_name") else None,
        "trainer": bool(payload.get("trainer")),
        "commute": bool(payload.get("commute")),
        "manual": bool(payload.get("manual")),
        "private": bool(payload.get("private")),
        "raw_json": payload,
        "last_synced_at": synced_at,
    }
    if activity is None:
        activity = StravaActivity(
            connection_id=connection.id,
            strava_activity_id=activity_id,
            **values,
        )
        db.add(activity)
    else:
        for field, value in values.items():
            setattr(activity, field, value)
    db.flush()
    return activity, created


def _materialize_activity(db: Session, activity: StravaActivity) -> int:
    matches = list(
        db.scalars(
            select(StravaActivityMatch).where(StravaActivityMatch.activity_id == activity.id)
        )
    )
    actual = _actual_payload(activity)
    if matches:
        linked_entries = [db.get(WorkoutEntry, match.workout_entry_id) for match in matches]
        planned_entries = [
            entry
            for match, entry in zip(matches, linked_entries, strict=True)
            if entry and not match.previous_entry_json.get("generated")
        ]
        if any(
            entry.entry_date != activity.activity_date
            or not _compatible(entry, _exercise_type(activity.sport_type))
            for entry in planned_entries
        ):
            _remove_materialized_activity(db, activity)
            matches = []
    if matches:
        for match in matches:
            entry = db.get(WorkoutEntry, match.workout_entry_id)
            if entry and entry.source == "strava":
                entry.actual_json = actual
                if match.previous_entry_json.get("generated"):
                    entry.entry_date = activity.activity_date
                    entry.exercise_name = activity.name[:160]
                    entry.prescription_json = _imported_prescription(activity)
        return 0

    candidates = list(
        db.scalars(
            select(WorkoutEntry).where(
                WorkoutEntry.entry_date == activity.activity_date,
                WorkoutEntry.planned_recommendation_id.is_not(None),
                WorkoutEntry.status.in_(MATCHABLE_STATUSES),
            )
        )
    )
    compatible = [
        entry for entry in candidates if _compatible(entry, _exercise_type(activity.sport_type))
    ]
    exercise_type = _exercise_type(activity.sport_type)
    if exercise_type in {"strength", "bodyweight"}:
        selected_entries = compatible
    else:
        best_match = max(compatible, key=lambda item: _match_score(item, activity), default=None)
        selected_entries = [best_match] if best_match else []

    if not selected_entries:
        entry = WorkoutEntry(
            entry_date=activity.activity_date,
            exercise_name=activity.name[:160],
            prescription_json=_imported_prescription(activity),
            actual_json=actual,
            status="completed",
            source="strava",
        )
        db.add(entry)
        db.flush()
        db.add(
            StravaActivityMatch(
                activity_id=activity.id,
                workout_entry_id=entry.id,
                match_kind="unplanned_activity",
                match_score=None,
                previous_entry_json={"generated": True},
            )
        )
        return 0

    for entry in selected_entries:
        previous = _entry_state(entry)
        entry.actual_json = actual
        entry.status = "completed"
        entry.source = "strava"
        entry.workout_log_id = None
        db.add(
            StravaActivityMatch(
                activity_id=activity.id,
                workout_entry_id=entry.id,
                match_kind="planned_recommendation",
                match_score=_match_score(entry, activity),
                previous_entry_json=previous,
            )
        )
    return len(selected_entries)


def _remove_materialized_activity(db: Session, activity: StravaActivity) -> None:
    matches = list(
        db.scalars(
            select(StravaActivityMatch).where(StravaActivityMatch.activity_id == activity.id)
        )
    )
    for match in matches:
        entry = db.get(WorkoutEntry, match.workout_entry_id)
        previous = match.previous_entry_json
        if entry is None:
            continue
        if previous.get("generated"):
            db.delete(entry)
            continue
        if entry.source == "strava":
            entry.status = str(previous.get("status") or "planned")
            entry.source = str(previous.get("source") or "recommended")
            entry.actual_json = previous.get("actual")
            entry.difficulty_1_to_10 = previous.get("difficulty_1_to_10")
            entry.pain_flag = bool(previous.get("pain_flag"))
            entry.notes = previous.get("notes")
            workout_log_id = previous.get("workout_log_id")
            entry.workout_log_id = UUID(workout_log_id) if workout_log_id else None
        db.delete(match)
    db.flush()


def _actual_payload(activity: StravaActivity) -> dict[str, Any]:
    duration = activity.moving_time_seconds or activity.elapsed_time_seconds
    payload: dict[str, Any] = {
        "activity_name": activity.name,
        "duration_seconds": duration,
        "elapsed_time_seconds": activity.elapsed_time_seconds,
        "elevation_gain_m": activity.elevation_gain_m,
        "sport_type": activity.sport_type,
        "start_at": activity.start_at.isoformat(),
        "trainer": activity.trainer,
        "commute": activity.commute,
        "device_name": activity.device_name,
        "completion_evidence": "strava_activity",
        "strava": {
            "activity_id": activity.strava_activity_id,
            "synced_at": activity.last_synced_at.isoformat(),
        },
    }
    if activity.distance_m > 0:
        distance_km = round(activity.distance_m / 1000, 3)
        payload["distance_km"] = distance_km
        if duration > 0:
            payload["pace_seconds_per_km"] = round(duration / distance_km)
    for key, value in (
        ("average_heartrate_bpm", activity.average_heartrate),
        ("max_heartrate_bpm", activity.max_heartrate),
        ("average_power_watts", activity.average_watts),
    ):
        if value is not None:
            payload[key] = value
    return payload


def _imported_prescription(activity: StravaActivity) -> dict[str, Any]:
    actual = _actual_payload(activity)
    return {
        "exercise_type": _exercise_type(activity.sport_type),
        "duration_seconds": actual["duration_seconds"],
        "distance_km": actual.get("distance_km"),
        "source_sport_type": activity.sport_type,
    }


def _entry_state(entry: WorkoutEntry) -> dict[str, Any]:
    return {
        "status": entry.status,
        "source": entry.source,
        "actual": entry.actual_json,
        "difficulty_1_to_10": entry.difficulty_1_to_10,
        "pain_flag": entry.pain_flag,
        "notes": entry.notes,
        "workout_log_id": str(entry.workout_log_id) if entry.workout_log_id else None,
    }


def _compatible(entry: WorkoutEntry, activity_type: str) -> bool:
    planned_type = str(entry.prescription_json.get("exercise_type") or "")
    if activity_type in {"strength", "bodyweight"}:
        return planned_type in {"strength", "bodyweight"}
    return planned_type == activity_type


def _match_score(entry: WorkoutEntry, activity: StravaActivity) -> float:
    prescription = entry.prescription_json
    score = 1.0
    target_distance = _number(prescription.get("distance_km"))
    actual_distance = activity.distance_m / 1000
    if target_distance and actual_distance:
        score -= min(abs(actual_distance - target_distance) / target_distance, 1.0) * 0.35
    target_duration = _integer(prescription.get("duration_seconds"))
    actual_duration = activity.moving_time_seconds or activity.elapsed_time_seconds
    if target_duration and actual_duration:
        score -= min(abs(actual_duration - target_duration) / target_duration, 1.0) * 0.25
    return round(max(score, 0), 3)


def _exercise_type(sport_type: str) -> str:
    if sport_type in RUN_TYPES:
        return "run"
    if sport_type in BIKE_TYPES:
        return "bike"
    if sport_type in STRENGTH_TYPES:
        return "strength"
    return "recovery"


def _safe_athlete(athlete: dict[str, Any]) -> dict[str, Any]:
    allowed = {"id", "firstname", "lastname", "city", "state", "country", "profile"}
    return {key: athlete.get(key) for key in allowed if athlete.get(key) is not None}


def _parse_scopes(value: str) -> set[str]:
    return {item for item in value.replace(",", " ").split() if item}


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _optional_number(value: Any) -> float | None:
    return None if value is None else _number(value)


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
