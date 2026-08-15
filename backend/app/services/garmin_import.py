import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ImportedActivity, UserProfile, WorkoutEntry
from app.services.metrics import recalculate_derived_summary

RUN_TYPES = {"running", "treadmill running", "trail running", "indoor running"}
BIKE_MARKERS = ("cycling", "biking", "bike")
STRENGTH_MARKERS = ("strength", "weight training")


class GarminImportError(RuntimeError):
    pass


def import_garmin_csv(db: Session, path: Path) -> dict[str, int]:
    profile = db.scalar(select(UserProfile))
    if profile is None:
        raise GarminImportError("Profile must be seeded before importing activities")
    created = 0
    skipped = 0
    affected_dates = []
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or not {"Activity Type", "Date", "Time"}.issubset(
            reader.fieldnames
        ):
            raise GarminImportError("This is not a supported Garmin Activities CSV export")
        for row_number, row in enumerate(reader, start=2):
            normalized = {key: value.strip() for key, value in row.items() if key and value}
            source_id = hashlib.sha256(
                json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if db.scalar(
                select(ImportedActivity.id).where(
                    ImportedActivity.provider == "garmin_csv",
                    ImportedActivity.source_id == source_id,
                )
            ):
                skipped += 1
                continue
            try:
                local_start = datetime.strptime(normalized["Date"], "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=ZoneInfo(profile.timezone)
                )
            except (KeyError, ValueError) as exc:
                raise GarminImportError(f"Invalid activity date on CSV row {row_number}") from exc
            activity_type = normalized.get("Activity Type", "Workout")
            exercise_type = _exercise_type(activity_type)
            duration = _duration(normalized.get("Moving Time")) or _duration(normalized.get("Time"))
            elapsed = _duration(normalized.get("Elapsed Time")) or _duration(normalized.get("Time"))
            distance = _number(normalized.get("Distance"))
            actual: dict[str, Any] = {
                "activity_name": normalized.get("Title") or activity_type,
                "duration_seconds": duration,
                "elapsed_time_seconds": elapsed,
                "sport_type": activity_type,
                "start_at": local_start.isoformat(),
                "completion_evidence": "garmin_csv_export",
                "garmin": {"source_id": source_id, "device": "Garmin Forerunner 965"},
            }
            for key, value in (
                ("distance_km", distance),
                ("elevation_gain_m", _number(normalized.get("Total Ascent"))),
                ("elevation_loss_m", _number(normalized.get("Total Descent"))),
                ("average_heartrate_bpm", _number(normalized.get("Avg HR"))),
                ("max_heartrate_bpm", _number(normalized.get("Max HR"))),
                ("average_power_watts", _number(normalized.get("Avg Power"))),
                ("max_power_watts", _number(normalized.get("Max Power"))),
                ("aerobic_training_effect", _number(normalized.get("Aerobic TE"))),
                ("average_cadence", _number(normalized.get("Avg Run Cadence"))),
                ("calories_kcal", _number(normalized.get("Calories"))),
            ):
                if value is not None:
                    actual[key] = value
            pace = _pace(normalized.get("Avg Pace"))
            if pace is None and distance and duration:
                pace = round(duration / distance)
            if pace is not None:
                actual["pace_seconds_per_km"] = pace
            entry = WorkoutEntry(
                entry_date=local_start.date(),
                exercise_name=(normalized.get("Title") or activity_type)[:160],
                prescription_json={
                    "exercise_type": exercise_type,
                    "duration_seconds": duration,
                    "distance_km": distance,
                    "source_sport_type": activity_type,
                },
                actual_json=actual,
                status="completed",
                source="garmin_csv",
            )
            db.add(entry)
            db.flush()
            db.add(
                ImportedActivity(
                    provider="garmin_csv",
                    source_id=source_id,
                    workout_entry_id=entry.id,
                    activity_date=local_start.date(),
                    start_at=local_start,
                    raw_json=normalized,
                )
            )
            created += 1
            affected_dates.append(local_start.date())
    if affected_dates:
        recalculate_derived_summary(db, profile, max(affected_dates))
    db.commit()
    return {"created": created, "skipped": skipped, "total": created + skipped}


def _exercise_type(value: str) -> str:
    folded = value.casefold()
    if folded in RUN_TYPES or "running" in folded:
        return "run"
    if any(marker in folded for marker in BIKE_MARKERS):
        return "bike"
    if any(marker in folded for marker in STRENGTH_MARKERS):
        return "strength"
    if any(marker in folded for marker in ("walking", "hiking", "yoga", "mobility")):
        return "recovery"
    return "other"


def _number(value: str | None) -> float | None:
    if not value or value in {"--", "No"}:
        return None
    cleaned = value.replace(",", "").removeprefix("'")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _duration(value: str | None) -> int | None:
    if not value or value == "--":
        return None
    parts = value.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
        elif len(parts) == 2:
            hours, minutes, seconds = "0", *parts
        else:
            return None
        return round(int(hours) * 3600 + int(minutes) * 60 + float(seconds))
    except ValueError:
        return None


def _pace(value: str | None) -> int | None:
    return _duration(value)
