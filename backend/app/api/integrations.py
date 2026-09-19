import logging
from datetime import date
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_auth, require_write_auth
from app.core.config import Settings, get_settings
from app.db.models import StravaActivity, StravaConnection
from app.db.session import SessionLocal, get_db
from app.services.recording_dates import resolve_recording_date
from app.services.strava import (
    StravaIntegrationError,
    complete_authorization,
    create_authorization_url,
    disconnect,
    mark_connection_revoked,
    rename_imported_activity,
    serialize_connection,
    set_treadmill_incline,
    sync_connection,
    sync_connection_for_date,
    sync_webhook_activity,
)
from app.services.strava_naming import WRITE_SCOPE
from app.services.workout_feedback import ensure_workout_feedback

router = APIRouter(prefix="/integrations/strava", tags=["integrations"])
logger = logging.getLogger(__name__)


class StravaWebhookEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    object_type: str
    object_id: int
    aspect_type: str
    owner_id: int
    subscription_id: int
    event_time: int
    updates: dict[str, Any] = Field(default_factory=dict)


class StravaNameUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=300)

    @field_validator("name")
    @classmethod
    def single_line(cls, value: str | None) -> str | None:
        if value is not None and any(ord(char) < 32 for char in value):
            raise ValueError("The activity name must be a single line")
        return value


class StravaInclineUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incline_percent: float | None = Field(ge=0, le=40, allow_inf_nan=False)


def _connection(db: Session, account_id: UUID) -> StravaConnection | None:
    return db.scalar(select(StravaConnection).where(StravaConnection.account_id == account_id))


@router.get("")
def get_strava_status(
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return serialize_connection(db, _connection(db, auth.account.id), settings)


@router.post("/connect")
def connect_strava(
    auth: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    try:
        return {"authorization_url": create_authorization_url(db, settings, auth.account.id)}
    except StravaIntegrationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.get("/callback")
def strava_callback(
    state: str,
    code: str | None = None,
    scope: str = "",
    error: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    if error or not code:
        query = urlencode({"strava": "denied"})
        return RedirectResponse(f"{settings.app_base_url.rstrip('/')}/settings?{query}")
    try:
        connection = complete_authorization(
            db,
            settings,
            state=state,
            code=code,
            granted_scope=scope,
        )
        sync_result = "ok"
        try:
            sync_connection(db, settings, connection)
        except Exception:  # Connection remains usable and exposes its safe sync error in Settings.
            sync_result = "failed"
    except StravaIntegrationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    query = urlencode({"strava": "connected", "sync": sync_result})
    return RedirectResponse(f"{settings.app_base_url.rstrip('/')}/settings?{query}")


@router.post("/sync")
def sync_strava(
    auth: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, int]:
    connection = _connection(db, auth.account.id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Strava is not connected")
    try:
        return sync_connection(db, settings, connection)
    except StravaIntegrationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/sync-today")
def sync_strava_today(
    auth: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, int]:
    connection = _connection(db, auth.account.id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Strava is not connected")
    target_date = resolve_recording_date(db, settings, None)
    try:
        return sync_connection_for_date(db, settings, connection, target_date)
    except StravaIntegrationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/sync-day")
def sync_strava_day(
    target_date: date = Query(alias="date"),
    auth: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, int | str]:
    connection = _connection(db, auth.account.id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Strava is not connected")
    try:
        validated_date = resolve_recording_date(db, settings, target_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    try:
        result = sync_connection_for_date(db, settings, connection, validated_date)
        response: dict[str, int | str] = dict(result)
        if not result["fetched"]:
            response["coach_feedback"] = ""
            return response
        feedback = ensure_workout_feedback(db, settings, validated_date, force=True)
        response["coach_feedback"] = feedback.message if feedback else ""
        return response
    except StravaIntegrationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.delete("", status_code=204)
def disconnect_strava(
    auth: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    connection = _connection(db, auth.account.id)
    if connection is None:
        return
    try:
        disconnect(db, settings, connection)
    except StravaIntegrationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.put("/activities/{activity_id}/name")
def rename_strava_activity(
    activity_id: int,
    payload: StravaNameUpdate,
    auth: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    connection = _connection(db, auth.account.id)
    if (
        connection is None
        or db.scalar(
            select(StravaActivity.id).where(
                StravaActivity.connection_id == connection.id,
                StravaActivity.strava_activity_id == activity_id,
            )
        )
        is None
    ):
        raise HTTPException(status_code=404, detail="Imported Strava activity not found")
    if connection.status != "connected" or WRITE_SCOPE not in connection.scopes_json:
        raise HTTPException(
            status_code=409, detail="Reconnect Strava in Settings to allow activity renaming."
        )
    try:
        activity = rename_imported_activity(db, settings, connection, activity_id, payload.name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StravaIntegrationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=502,
            detail="Strava could not rename this activity. Try again or reconnect in Settings.",
        ) from exc
    return {"name": activity.name}


@router.patch("/activities/{activity_id}/incline")
def update_strava_treadmill_incline(
    activity_id: int,
    payload: StravaInclineUpdate,
    auth: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, float | None]:
    connection = _connection(db, auth.account.id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Imported Strava activity not found")
    try:
        activity = set_treadmill_incline(
            db, settings, connection, activity_id, payload.incline_percent
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"incline_percent": activity.treadmill_incline_percent}


@router.get("/webhook")
def verify_strava_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_challenge: str = Query(alias="hub.challenge"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    expected = settings.strava_webhook_token_value
    if not expected or hub_mode != "subscribe" or hub_verify_token != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid verify token")
    return {"hub.challenge": hub_challenge}


@router.post("/webhook", status_code=200)
def receive_strava_webhook(
    payload: StravaWebhookEvent,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
) -> dict[str, bool]:
    expected_subscription = settings.strava_webhook_subscription_id
    if expected_subscription is None or payload.subscription_id != expected_subscription:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unknown subscription")
    background_tasks.add_task(_process_webhook_event, payload, settings)
    return {"accepted": True}


def _process_webhook_event(payload: StravaWebhookEvent, settings: Settings) -> None:
    with SessionLocal() as db:
        if payload.object_type == "athlete" and payload.updates.get("authorized") in {
            False,
            "false",
        }:
            mark_connection_revoked(db, settings, payload.owner_id)
            return
        if payload.object_type != "activity" or payload.aspect_type not in {
            "create",
            "update",
            "delete",
        }:
            return
        try:
            sync_webhook_activity(
                db,
                settings,
                owner_id=payload.owner_id,
                activity_id=payload.object_id,
                aspect_type=payload.aspect_type,
            )
        except Exception:
            db.rollback()
            logger.exception("Strava webhook processing failed")
