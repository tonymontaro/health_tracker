import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import TrainingPlanGuide, UserProfile

MAX_GUIDE_ROWS = 730
MAX_WORKOUT_LENGTH = 10_000
KEY_SESSION_PATTERN = re.compile(
    r"\b(race|benchmark|time trial|competition|event|test)\b",
    re.IGNORECASE,
)


class TrainingPlanGuideError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedTrainingPlanGuide:
    days: list[dict[str, str]]
    start_date: date
    end_date: date


def parse_training_plan_csv(csv_text: str) -> ParsedTrainingPlanGuide:
    if "\x00" in csv_text:
        raise TrainingPlanGuideError("The CSV contains an unsupported null character.")
    text = csv_text.removeprefix("\ufeff")
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
    except csv.Error as exc:
        raise TrainingPlanGuideError(f"The CSV could not be read: {exc}") from exc
    if not reader.fieldnames:
        raise TrainingPlanGuideError("The CSV must have a header row.")

    normalized_headers: dict[str, str] = {}
    for original in reader.fieldnames:
        if original is None:
            continue
        normalized = original.strip().casefold()
        if normalized in normalized_headers:
            raise TrainingPlanGuideError(f"The CSV contains duplicate column {original!r}.")
        normalized_headers[normalized] = original
    if "date" not in normalized_headers or "workout" not in normalized_headers:
        raise TrainingPlanGuideError("The CSV must contain Date and Workout columns.")

    date_column = normalized_headers["date"]
    workout_column = normalized_headers["workout"]
    days: list[dict[str, str]] = []
    seen_dates: set[date] = set()
    try:
        for line_number, row in enumerate(reader, start=2):
            raw_date = (row.get(date_column) or "").strip()
            raw_workout = (row.get(workout_column) or "").strip()
            extra_values = row.get(None) or []
            if (
                not raw_date
                and not raw_workout
                and not any(value.strip() for value in extra_values)
            ):
                continue
            if extra_values:
                raise TrainingPlanGuideError(
                    f"Row {line_number} has more values than the header row."
                )
            if not raw_date:
                raise TrainingPlanGuideError(f"Row {line_number} is missing a date.")
            try:
                plan_date = date.fromisoformat(raw_date)
            except ValueError as exc:
                raise TrainingPlanGuideError(
                    f"Row {line_number} has invalid date {raw_date!r}; use YYYY-MM-DD."
                ) from exc
            if plan_date in seen_dates:
                raise TrainingPlanGuideError(
                    f"The date {plan_date.isoformat()} appears more than once."
                )
            if not raw_workout:
                raise TrainingPlanGuideError(
                    f"Row {line_number} is missing its workout guidance. Use Rest for rest days."
                )
            if len(raw_workout) > MAX_WORKOUT_LENGTH:
                raise TrainingPlanGuideError(
                    f"The workout on {plan_date.isoformat()} exceeds {MAX_WORKOUT_LENGTH} characters."
                )
            seen_dates.add(plan_date)
            days.append({"plan_date": plan_date.isoformat(), "workout": raw_workout})
    except csv.Error as exc:
        raise TrainingPlanGuideError(f"The CSV could not be read: {exc}") from exc

    if not days:
        raise TrainingPlanGuideError("The CSV does not contain any training-plan rows.")
    if len(days) > MAX_GUIDE_ROWS:
        raise TrainingPlanGuideError(
            f"The CSV contains more than the supported {MAX_GUIDE_ROWS} rows."
        )
    days.sort(key=lambda item: item["plan_date"])
    return ParsedTrainingPlanGuide(
        days=days,
        start_date=date.fromisoformat(days[0]["plan_date"]),
        end_date=date.fromisoformat(days[-1]["plan_date"]),
    )


def replace_training_plan_guide(
    db: Session,
    profile: UserProfile,
    *,
    filename: str,
    csv_text: str,
) -> TrainingPlanGuide:
    parsed = parse_training_plan_csv(csv_text)
    safe_filename = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].strip()
    if not safe_filename:
        raise TrainingPlanGuideError("The uploaded file needs a filename.")
    name = safe_filename.rsplit(".", 1)[0].replace("_", " ").strip() or "Training plan"
    name = name[:160]
    source_sha256 = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
    guide = db.scalar(select(TrainingPlanGuide).where(TrainingPlanGuide.profile_id == profile.id))
    if guide is None:
        guide = TrainingPlanGuide(
            profile_id=profile.id,
            name=name,
            source_filename=safe_filename,
            source_sha256=source_sha256,
            start_date=parsed.start_date,
            end_date=parsed.end_date,
            guide_json={"days": parsed.days},
            raw_csv_text=csv_text,
        )
        db.add(guide)
    else:
        guide.name = name
        guide.source_filename = safe_filename
        guide.source_sha256 = source_sha256
        guide.start_date = parsed.start_date
        guide.end_date = parsed.end_date
        guide.guide_json = {"days": parsed.days}
        guide.raw_csv_text = csv_text
    db.commit()
    db.refresh(guide)
    return guide


def get_training_plan_guide(db: Session, profile: UserProfile) -> TrainingPlanGuide | None:
    return db.scalar(select(TrainingPlanGuide).where(TrainingPlanGuide.profile_id == profile.id))


def active_training_plan_guide_revision(db: Session, profile: UserProfile) -> str | None:
    guide = get_training_plan_guide(db, profile)
    return guide.source_sha256 if guide is not None else None


def serialize_training_plan_guide(guide: TrainingPlanGuide) -> dict[str, Any]:
    days = list(guide.guide_json.get("days", []))
    return {
        "id": guide.id,
        "name": guide.name,
        "source_filename": guide.source_filename,
        "source_sha256": guide.source_sha256,
        "start_date": guide.start_date,
        "end_date": guide.end_date,
        "row_count": len(days),
        "days": days,
        "created_at": guide.created_at,
        "updated_at": guide.updated_at,
    }


def training_plan_guide_context(
    db: Session,
    profile: UserProfile,
    window_start: date,
    *,
    window_days: int = 14,
) -> dict[str, Any] | None:
    guide = get_training_plan_guide(db, profile)
    if guide is None:
        return None
    window_end = window_start + timedelta(days=window_days - 1)
    all_days = list(guide.guide_json.get("days", []))
    window = [
        item
        for item in all_days
        if window_start.isoformat() <= item["plan_date"] <= window_end.isoformat()
    ]
    next_key_session = next(
        (
            item
            for item in all_days
            if item["plan_date"] > window_end.isoformat()
            and KEY_SESSION_PATTERN.search(item["workout"])
        ),
        None,
    )
    return {
        "guide_id": str(guide.id),
        "guide_revision": guide.source_sha256,
        "name": guide.name,
        "coverage_start": guide.start_date.isoformat(),
        "coverage_end": guide.end_date.isoformat(),
        "days_in_planning_window": window,
        "next_key_session_after_window": next_key_session,
    }


def daily_training_plan_guide_context(
    db: Session,
    profile: UserProfile,
    plan_date: date,
) -> dict[str, Any] | None:
    """Return the raw guide text needed to decide one day without the full horizon payload."""

    guide = get_training_plan_guide(db, profile)
    if guide is None:
        return None
    all_days = list(guide.guide_json.get("days", []))
    current_day = next(
        (item for item in all_days if item["plan_date"] == plan_date.isoformat()),
        None,
    )
    nearby_end = plan_date + timedelta(days=3)
    next_three_days = [
        item
        for item in all_days
        if plan_date.isoformat() < item["plan_date"] <= nearby_end.isoformat()
    ]
    next_key_session = next(
        (
            item
            for item in all_days
            if item["plan_date"] > nearby_end.isoformat()
            and KEY_SESSION_PATTERN.search(item["workout"])
        ),
        None,
    )
    return {
        "guide_id": str(guide.id),
        "guide_revision": guide.source_sha256,
        "name": guide.name,
        "coverage_start": guide.start_date.isoformat(),
        "coverage_end": guide.end_date.isoformat(),
        "current_day_guidance": current_day,
        "next_three_days": next_three_days,
        "next_key_session_after_near_term": next_key_session,
    }
