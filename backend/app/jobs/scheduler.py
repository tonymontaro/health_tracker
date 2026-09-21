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
)
from app.services.strava import sync_all_connections

logger = logging.getLogger(__name__)


def run_due_jobs() -> list[str]:
    settings = get_settings()
    local_now = datetime.now(ZoneInfo(settings.app_timezone))
    today = local_now.date()
    completed: list[str] = []
    with SessionLocal() as db:
        sync_result = sync_all_connections(db, settings)
        if sync_result["connections"]:
            completed.append("strava_sync")
        if local_now.hour > 0 or local_now.minute >= 5:
            finalize_day(db, today - timedelta(days=1))
            completed.append("finalize_day")
            generate_morning_plan(db, settings, today)
            completed.append("morning_plan")
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
