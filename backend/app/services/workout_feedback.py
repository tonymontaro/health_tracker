from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import DailyPlan, UserProfile, WorkoutCoachFeedback, WorkoutEntry
from app.services.coach import coach_message


def ensure_workout_feedback(
    db: Session,
    settings: Settings,
    target_date: date,
    *,
    force: bool = False,
) -> WorkoutCoachFeedback | None:
    existing = db.scalar(
        select(WorkoutCoachFeedback).where(WorkoutCoachFeedback.feedback_date == target_date)
    )
    if existing and not force:
        return existing
    entries = list(
        db.scalars(
            select(WorkoutEntry)
            .where(WorkoutEntry.entry_date == target_date)
            .order_by(WorkoutEntry.created_at)
        )
    )
    if not entries:
        return None
    has_outcome = any(
        entry.actual_json is not None
        or entry.status
        in {"completed", "partial", "skipped", "skipped_assumed", "skipped_by_workout_log"}
        for entry in entries
    )
    if not has_outcome:
        return None
    profile = db.scalar(select(UserProfile))
    plan = db.scalar(select(DailyPlan).where(DailyPlan.plan_date == target_date))
    facts: dict[str, Any] = {
        "current_target_goal": profile.current_target_goal if profile else None,
        "planned_workout": plan.current_plan_json.get("workout") if plan else None,
        "recorded_entries": [
            {
                "exercise_name": entry.exercise_name,
                "prescription": entry.prescription_json,
                "actual": entry.actual_json,
                "status": entry.status,
                "source": entry.source,
                "difficulty": entry.difficulty_1_to_10,
                "pain_flag": entry.pain_flag,
                "notes": entry.notes,
            }
            for entry in entries
        ],
        "matched_count": sum(
            entry.planned_recommendation_id is not None and entry.status in {"completed", "partial"}
            for entry in entries
        ),
        "skipped_count": sum("skipped" in entry.status for entry in entries),
        "pain_flag": any(entry.pain_flag for entry in entries),
    }
    message = coach_message(settings, moment="workout_feedback", facts=facts)
    feedback = existing or WorkoutCoachFeedback(feedback_date=target_date)
    feedback.message = message
    feedback.model = (
        settings.openai_qa_model if settings.openai_key_value else "deterministic-fallback"
    )
    feedback.context_snapshot_json = facts
    if existing is None:
        db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback
