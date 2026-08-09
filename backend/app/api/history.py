from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_auth, require_write_auth
from app.core.config import Settings, get_settings
from app.db.models import NutritionEntry, WorkoutEntry
from app.db.session import get_db
from app.schemas.api import HistoryNutritionUpdate, HistoryWorkoutUpdate
from app.services.history import (
    correct_nutrition_entry,
    correct_workout_entry,
    history_day,
    history_index,
    serialize_nutrition,
    serialize_workout,
)

router = APIRouter(prefix="/history", tags=["history"])


@router.get("")
def list_history(
    _: AuthContext = Depends(require_auth), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    return history_index(db)


@router.get("/{target_date}")
def get_history_day(
    target_date: date,
    _: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return history_day(db, target_date)


@router.patch("/{target_date}/nutrition/{entry_id}")
def patch_nutrition_history(
    target_date: date,
    entry_id: UUID,
    payload: HistoryNutritionUpdate,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    entry = db.get(NutritionEntry, entry_id)
    if entry is None or entry.entry_date != target_date:
        raise HTTPException(status_code=404, detail="Nutrition entry not found")
    if entry.status in {"matched_by_food_log", "discarded_by_food_log"}:
        raise HTTPException(
            status_code=409,
            detail="This recommendation was closed by the day's food text. Correct the actual AI-recorded meal instead.",
        )
    today = datetime.now(ZoneInfo(settings.app_timezone)).date()
    updated = correct_nutrition_entry(db, entry, payload.model_dump(exclude_unset=True), today)
    return serialize_nutrition(updated)


@router.patch("/{target_date}/workout/{entry_id}")
def patch_workout_history(
    target_date: date,
    entry_id: UUID,
    payload: HistoryWorkoutUpdate,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    entry = db.get(WorkoutEntry, entry_id)
    if entry is None or entry.entry_date != target_date:
        raise HTTPException(status_code=404, detail="Workout entry not found")
    today = datetime.now(ZoneInfo(settings.app_timezone)).date()
    try:
        updated = correct_workout_entry(db, entry, payload.model_dump(exclude_unset=True), today)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return serialize_workout(updated)
