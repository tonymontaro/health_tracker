from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_write_auth
from app.core.config import Settings, get_settings
from app.db.models import ChatMessage, DailyPlan
from app.db.session import get_db
from app.schemas.api import QuestionRequest, QuestionResponse
from app.services.chat import ask_about_plan
from app.services.history import replace_recommendation

router = APIRouter(prefix="/today", tags=["chat"])


@router.post("/questions", response_model=QuestionResponse)
def ask_question(
    payload: QuestionRequest,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> QuestionResponse:
    today = datetime.now(ZoneInfo(settings.app_timezone)).date()
    try:
        message = ask_about_plan(db, settings, payload.question, today)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return QuestionResponse(
        message_id=message.id,
        answer=message.answer,
        proposed_change=message.proposal_json,
        caution=None,
    )


@router.post("/recommendations/{message_id}/apply-change")
def apply_change(
    message_id: UUID,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    message = db.get(ChatMessage, message_id)
    if message is None or not message.proposal_json:
        raise HTTPException(status_code=404, detail="Proposed change not found")
    if message.applied_at:
        raise HTTPException(status_code=409, detail="Proposed change was already applied")
    proposal = message.proposal_json
    required = {"recommendation_id", "replacement", "reason"}
    if not required.issubset(proposal):
        raise HTTPException(status_code=422, detail="AI proposal is incomplete")
    plan = db.scalar(select(DailyPlan).where(DailyPlan.plan_date == message.message_date))
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    try:
        replace_recommendation(
            db,
            plan,
            str(proposal["recommendation_id"]),
            dict(proposal["replacement"]),
            str(proposal["reason"]),
            "ai_user_approved",
        )
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    message.applied_at = datetime.now(ZoneInfo("UTC"))
    db.commit()
    return {"applied": True, "plan": plan.current_plan_json}
