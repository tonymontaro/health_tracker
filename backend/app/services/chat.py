import json
from datetime import date

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import ChatMessage, DailyPlan, UserProfile
from app.schemas.api import QAResponse
from app.services.planner.context import build_planner_context

QA_SYSTEM_PROMPT = """Answer questions about today's personal health and hybrid training plan.
Use only the supplied profile, plan, history, inventory, and constraints.
Be concise and practical. Clearly distinguish recorded facts, calculations, estimates, and goals.
Do not diagnose medical conditions. Concerning symptoms or pain should lead to cautious advice and professional care.
You may propose one structured replacement, but never claim it was applied.
A proposed_change must contain recommendation_id, replacement, and reason, or be null.
The replacement must retain measurable training targets and all daily hard constraints.
"""


def ask_about_plan(
    db: Session,
    settings: Settings,
    question: str,
    target_date: date,
) -> ChatMessage:
    plan = db.scalar(select(DailyPlan).where(DailyPlan.plan_date == target_date))
    profile = db.scalar(select(UserProfile))
    if plan is None or profile is None:
        raise LookupError("Today's plan is not available")
    if not settings.openai_key_value:
        response = QAResponse(
            answer=(
                "AI Q&A is unavailable because no API key is configured. "
                "The persisted plan and deterministic fallback remain available."
            ),
            proposed_change=None,
            caution=None,
        )
    else:
        from app.db.models import ProfileSnapshot

        snapshot = db.get(ProfileSnapshot, plan.profile_snapshot_id)
        if snapshot is None:
            raise RuntimeError("Plan snapshot is missing")
        context = build_planner_context(db, profile, snapshot, target_date)
        client = OpenAI(
            api_key=settings.openai_key_value,
            timeout=120,
            max_retries=1,
        )
        result = client.responses.parse(
            model=settings.openai_qa_model,
            reasoning={"effort": "low"},
            input=[
                {"role": "system", "content": QA_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "question": question,
                            "today_plan": plan.current_plan_json,
                            "context": context,
                        },
                        default=str,
                        separators=(",", ":"),
                    ),
                },
            ],
            text_format=QAResponse,
            store=False,
        )
        if result.output_parsed is None:
            raise ValueError("OpenAI returned no parsed Q&A response")
        response = result.output_parsed
    message = ChatMessage(
        message_date=target_date,
        question=question,
        answer=response.answer,
        proposal_json=(
            response.proposed_change.model_dump(mode="json") if response.proposed_change else None
        ),
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message
