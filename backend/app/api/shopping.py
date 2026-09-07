from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_write_auth
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.services.meal_planning import ensure_meal_weeks, serialize_meal_week
from app.services.recording_dates import current_recording_date

router = APIRouter(tags=["meals"])


@router.post("/meals/plan")
def get_meal_plan(
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    today = current_recording_date(settings)
    weeks = ensure_meal_weeks(db, settings, today)
    return {"today": today.isoformat(), "weeks": [serialize_meal_week(db, week) for week in weeks]}
