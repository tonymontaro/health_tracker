import logging
from datetime import date
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_auth, require_write_auth
from app.core.config import Settings, get_settings
from app.db.models import StravaConnection
from app.db.session import SessionLocal, get_db
from app.services.recording_dates import resolve_recording_date
from app.services.strava import (
    StravaIntegrationError,
    complete_authorization,
    create_authorization_url,
    disconnect,
    mark_connection_revoked,
    serialize_connection,
    sync_connection,
    sync_connection_for_date,
    sync_webhook_activity,
)

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
    target_date = resolve_recording_date(settings, None)
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
) -> dict[str, int]:
    connection = _connection(db, auth.account.id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Strava is not connected")
    try:
        validated_date = resolve_recording_date(settings, target_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    try:
        return sync_connection_for_date(db, settings, connection, validated_date)
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
