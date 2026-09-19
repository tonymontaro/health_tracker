from calendar import monthrange
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import DailyPlan, WorkoutEntry


def current_recording_date(settings: Settings) -> date:
    return datetime.now(ZoneInfo(settings.app_timezone)).date()


def resolve_recording_date(db: Session, settings: Settings, requested: date | None) -> date:
    today = current_recording_date(settings)
    target = requested or today
    if target > today or (
        target < today
        and db.scalar(select(DailyPlan.id).where(DailyPlan.plan_date == target)) is None
    ):
        raise ValueError("Choose today or a past day with a saved daily plan.")
    return target


def daily_plan_calendar(db: Session, settings: Settings, month: date | None) -> dict[str, Any]:
    today = current_recording_date(settings)
    start = (month or today).replace(day=1)
    end = start.replace(day=monthrange(start.year, start.month)[1])
    dates = list(
        db.scalars(
            select(DailyPlan.plan_date)
            .where(
                DailyPlan.plan_date >= start,
                DailyPlan.plan_date <= end,
                DailyPlan.plan_date <= today,
            )
            .order_by(DailyPlan.plan_date)
        )
    )
    performed = set(
        db.scalars(
            select(WorkoutEntry.entry_date)
            .where(
                WorkoutEntry.entry_date >= start,
                WorkoutEntry.entry_date <= end,
                WorkoutEntry.entry_date <= today,
                WorkoutEntry.status.in_({"completed", "partial"}),
            )
            .distinct()
        )
    )
    saved_dates = set(dates)
    first = db.scalar(select(func.min(DailyPlan.plan_date)).where(DailyPlan.plan_date <= today))
    return {
        "today": today.isoformat(),
        "month": start.isoformat(),
        "first_plan_date": first.isoformat() if first else None,
        "days": [
            {
                "date": value.isoformat(),
                "has_plan": value in saved_dates,
                "exercise_performed": value in performed,
            }
            for value in sorted(saved_dates | performed)
        ],
    }
