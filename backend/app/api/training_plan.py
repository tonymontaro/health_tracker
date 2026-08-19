from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_auth, require_write_auth
from app.db.models import UserProfile
from app.db.session import get_db
from app.schemas.api import TrainingPlanGuideResponse, TrainingPlanGuideUpload
from app.services.training_plan_guide import (
    TrainingPlanGuideError,
    get_training_plan_guide,
    replace_training_plan_guide,
    serialize_training_plan_guide,
)

router = APIRouter(prefix="/training-plan", tags=["training plan"])


def _profile(db: Session) -> UserProfile:
    profile = db.scalar(select(UserProfile))
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.get("", response_model=TrainingPlanGuideResponse | None)
def get_active_training_plan(
    _: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict[str, object] | None:
    guide = get_training_plan_guide(db, _profile(db))
    return serialize_training_plan_guide(guide) if guide is not None else None


@router.put("", response_model=TrainingPlanGuideResponse)
def upload_training_plan(
    payload: TrainingPlanGuideUpload,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        guide = replace_training_plan_guide(
            db,
            _profile(db),
            filename=payload.filename,
            csv_text=payload.csv_text,
        )
    except TrainingPlanGuideError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return serialize_training_plan_guide(guide)
