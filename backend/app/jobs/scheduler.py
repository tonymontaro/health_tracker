import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.jobs.tasks import (
    finalize_day,
    generate_morning_plan,
    generate_shopping,
    send_evening_checkin,
    send_morning_email,
)

logger = logging.getLogger(__name__)


def run_due_jobs() -> list[str]:
    settings = get_settings()
    local_now = datetime.now(ZoneInfo(settings.app_timezone))
    today = local_now.date()
    completed: list[str] = []
    with SessionLocal() as db:
        if local_now.hour > 5 or (local_now.hour == 5 and local_now.minute >= 50):
            generate_morning_plan(db, settings, today)
            completed.append("morning_plan")
        if local_now.hour >= 6:
            send_morning_email(db, settings, today)
            completed.append("morning_email")
        if local_now.hour >= 21:
            send_evening_checkin(db, settings, today)
            completed.append("evening_email")
        if local_now.hour > 0 or local_now.minute >= 5:
            finalize_day(db, today - timedelta(days=1))
            completed.append("finalize_day")
        if local_now.weekday() == 6 and local_now.hour >= 17:
            week_start = today + timedelta(days=1)
            generate_shopping(db, settings, week_start)
            completed.append("shopping_plan")
    return completed


def run_scheduler() -> None:
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            logger.info("Completed due jobs: %s", run_due_jobs())
        except Exception:
            logger.exception("Scheduled job cycle failed")
        time.sleep(60)
