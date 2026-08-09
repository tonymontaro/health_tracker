from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_auth, require_write_auth
from app.core.config import Settings, get_settings
from app.db.models import Equipment, UserProfile
from app.db.session import get_db
from app.schemas.api import (
    EquipmentResponse,
    EquipmentUpdate,
    ProfileResponse,
    ProfileUpdate,
)

router = APIRouter(tags=["profile"])


def _profile(db: Session) -> UserProfile:
    profile = db.scalar(select(UserProfile))
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.get("/profile", response_model=ProfileResponse)
def get_profile(
    _: AuthContext = Depends(require_auth), db: Session = Depends(get_db)
) -> UserProfile:
    return _profile(db)


@router.patch("/profile", response_model=ProfileResponse)
def update_profile(
    payload: ProfileUpdate,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> UserProfile:
    profile = _profile(db)
    changes = payload.model_dump(exclude_unset=True)
    for required in ("timezone", "location", "primary_training_goal"):
        if required in changes and not changes[required]:
            raise HTTPException(status_code=422, detail=f"{required} cannot be empty")
    if "timezone" in changes and changes["timezone"]:
        try:
            ZoneInfo(changes["timezone"])
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(status_code=422, detail="Unknown timezone") from exc
    maximum_meals = changes.get("max_main_meals_per_day", profile.max_main_meals_per_day)
    preferred_meals = changes.get(
        "preferred_main_meals_per_day", profile.preferred_main_meals_per_day
    )
    if preferred_meals > maximum_meals:
        raise HTTPException(
            status_code=422,
            detail="preferred_main_meals_per_day cannot exceed max_main_meals_per_day",
        )
    for field, value in changes.items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/settings")
def get_runtime_settings(
    _: AuthContext = Depends(require_auth),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    return {
        "app_timezone": settings.app_timezone,
        "planner_model": settings.openai_planner_model,
        "qa_model": settings.openai_qa_model,
        "reasoning_effort": settings.openai_reasoning_effort,
        "openai_configured": bool(settings.openai_key_value),
        "email_provider": "resend",
        "resend_configured": settings.resend_configured,
        "coop_online_minimum_chf": settings.coop_online_minimum_chf,
        "migros_online_minimum_chf": settings.migros_online_minimum_chf,
    }


@router.get("/equipment", response_model=list[EquipmentResponse])
def get_equipment(
    _: AuthContext = Depends(require_auth), db: Session = Depends(get_db)
) -> list[Equipment]:
    return list(db.scalars(select(Equipment).order_by(Equipment.category, Equipment.name)))


@router.patch("/equipment/{equipment_id}", response_model=EquipmentResponse)
def update_equipment(
    equipment_id: UUID,
    payload: EquipmentUpdate,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> Equipment:
    equipment = db.get(Equipment, equipment_id)
    if equipment is None:
        raise HTTPException(status_code=404, detail="Equipment not found")
    equipment.available = payload.available
    db.commit()
    db.refresh(equipment)
    return equipment
