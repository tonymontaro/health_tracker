from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import Settings

RECORDING_LOOKBACK_DAYS = 7


def current_recording_date(settings: Settings) -> date:
    return datetime.now(ZoneInfo(settings.app_timezone)).date()


def available_recording_dates(settings: Settings) -> list[date]:
    current = current_recording_date(settings)
    return [current - timedelta(days=offset) for offset in range(RECORDING_LOOKBACK_DAYS + 1)]


def resolve_recording_date(settings: Settings, requested: date | None) -> date:
    available = available_recording_dates(settings)
    target = requested or available[0]
    if target not in available:
        raise ValueError("Date must be today or within the previous 7 days.")
    return target
