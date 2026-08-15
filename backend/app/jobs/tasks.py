from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    DailyPlan,
    NotificationEvent,
    NutritionEntry,
    ShoppingPlan,
    UserProfile,
    WorkoutEntry,
)
from app.services.coach import coach_message
from app.services.email import ResendEmailService, evening_email, morning_email
from app.services.history import reconcile_day
from app.services.planner.orchestrator import generate_daily_plan
from app.services.shopping import generate_weekly_shopping_plan


def generate_morning_plan(
    db: Session, settings: Settings, target_date: date, *, use_ai: bool = True
) -> DailyPlan:
    return generate_daily_plan(db, settings, target_date, use_ai=use_ai)


def send_morning_email(db: Session, settings: Settings, target_date: date) -> NotificationEvent:
    return _send_plan_email(db, settings, target_date, "morning_email")


def send_evening_checkin(db: Session, settings: Settings, target_date: date) -> NotificationEvent:
    return _send_plan_email(db, settings, target_date, "evening_email")


def _send_plan_email(
    db: Session, settings: Settings, target_date: date, event_type: str
) -> NotificationEvent:
    existing = db.scalar(
        select(NotificationEvent).where(
            NotificationEvent.event_type == event_type,
            NotificationEvent.event_date == target_date,
        )
    )
    if existing and _is_current_resend_delivery(existing, settings):
        return existing
    event = existing or NotificationEvent(
        event_type=event_type,
        event_date=target_date,
        status="pending",
        metadata_json={},
    )
    if existing is None:
        db.add(event)
    prior_attempts = int(event.metadata_json.get("attempt_count", 0))
    event.status = "pending"
    event.sent_at = None
    event.metadata_json = {
        "recipient": settings.resend_to,
        "provider": "resend",
        "attempt_count": prior_attempts + 1,
    }
    db.commit()
    plan = db.scalar(select(DailyPlan).where(DailyPlan.plan_date == target_date))
    if plan is None:
        plan = generate_daily_plan(db, settings, target_date)
    profile = db.scalar(select(UserProfile))
    coach_facts = {
        "current_target_goal": profile.current_target_goal if profile else None,
        "plan_summary": plan.current_plan_json.get("short_summary"),
        "workout": plan.current_plan_json.get("workout"),
        "nutrition_guidance": plan.current_plan_json.get("nutrition", {}).get("guidance"),
    }
    if event_type == "morning_email":
        note = coach_message(settings, moment="morning_email", facts=coach_facts)
        subject, text, html = morning_email(plan.current_plan_json, settings.app_base_url, note)
    else:
        workout_entries = list(
            db.scalars(select(WorkoutEntry).where(WorkoutEntry.entry_date == target_date))
        )
        nutrition_entries = list(
            db.scalars(select(NutritionEntry).where(NutritionEntry.entry_date == target_date))
        )
        coach_facts["actual_status"] = {
            "workouts_completed": sum(entry.status in {"completed", "partial"} for entry in workout_entries),
            "workouts_unresolved_or_skipped": sum(entry.status not in {"completed", "partial"} for entry in workout_entries),
            "nutrition_confirmed": sum(entry.status in {"confirmed", "assumed_consumed"} for entry in nutrition_entries),
            "nutrition_unresolved_or_skipped": sum(entry.status not in {"confirmed", "assumed_consumed"} for entry in nutrition_entries),
            "pain_recorded": any(entry.pain_flag for entry in workout_entries),
        }
        note = coach_message(settings, moment="evening_email", facts=coach_facts)
        subject, text, html = evening_email(plan.current_plan_json, settings.app_base_url, note)
    try:
        recipient = settings.resend_to
        if not recipient:
            raise RuntimeError("RESEND_TO is not configured")
        provider_message_id = ResendEmailService(settings).send(
            recipient,
            subject,
            text,
            html,
            idempotency_key=f"health-autopilot/{event_type}/{target_date.isoformat()}",
        )
        event.status = "sent"
        event.sent_at = datetime.now(UTC)
        event.metadata_json = {
            "recipient": recipient,
            "subject": subject,
            "provider": "resend",
            "provider_message_id": provider_message_id,
            "attempt_count": prior_attempts + 1,
        }
    except Exception as exc:
        event.status = "failed"
        event.metadata_json = {
            "recipient": settings.resend_to,
            "provider": "resend",
            "attempt_count": prior_attempts + 1,
            "error": f"{type(exc).__name__}: {exc}",
        }
        db.commit()
        raise
    db.commit()
    db.refresh(event)
    return event


def _is_current_resend_delivery(event: NotificationEvent, settings: Settings) -> bool:
    metadata = event.metadata_json
    return bool(
        event.status == "sent"
        and metadata.get("provider") == "resend"
        and metadata.get("provider_message_id")
        and metadata.get("recipient") == settings.resend_to
    )


def finalize_day(db: Session, target_date: date) -> dict[str, int]:
    existing = db.scalar(
        select(NotificationEvent).where(
            NotificationEvent.event_type == "finalize_day",
            NotificationEvent.event_date == target_date,
        )
    )
    if existing and existing.status == "completed":
        return existing.metadata_json
    result = reconcile_day(db, target_date)
    event = existing or NotificationEvent(
        event_type="finalize_day", event_date=target_date, status="completed"
    )
    if existing is None:
        db.add(event)
    event.status = "completed"
    event.sent_at = datetime.now(UTC)
    event.metadata_json = result
    db.commit()
    return result


def generate_shopping(
    db: Session, settings: Settings, week_start: date, retailer: str = "Coop"
) -> ShoppingPlan:
    return generate_weekly_shopping_plan(db, settings, week_start, retailer)


def previous_day(value: date) -> date:
    return value - timedelta(days=1)
