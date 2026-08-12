from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import ImportedActivity, WorkoutEntry
from app.services.garmin_import import import_garmin_csv
from app.services.metrics import calculate_goal_progress_evidence


def test_garmin_csv_import_is_idempotent_and_enters_goal_evidence(
    db: Session, seeded, tmp_path
) -> None:
    export = tmp_path / "Activities.csv"
    export.write_text(
        "Activity Type,Date,Title,Distance,Time,Avg HR,Max HR,Avg Pace,Total Ascent,"
        "Moving Time,Elapsed Time,Avg Power,Aerobic TE,Calories\n"
        "Running,2026-08-08 08:15:00,Morning Run,10.00,01:00:00,150,170,6:00,120,"
        "00:59:30,01:00:30,300,4.0,700\n",
        encoding="utf-8",
    )

    assert import_garmin_csv(db, export) == {"created": 1, "skipped": 0, "total": 1}
    assert import_garmin_csv(db, export) == {"created": 0, "skipped": 1, "total": 1}
    assert db.scalar(select(func.count(ImportedActivity.id))) == 1
    entry = db.scalar(select(WorkoutEntry).where(WorkoutEntry.source == "garmin_csv"))
    assert entry is not None
    assert entry.prescription_json["exercise_type"] == "run"
    assert entry.actual_json["distance_km"] == 10.0
    assert entry.actual_json["elevation_gain_m"] == 120.0
    assert entry.actual_json["completion_evidence"] == "garmin_csv_export"

    evidence = calculate_goal_progress_evidence(db, date(2026, 8, 12))
    assert evidence["run_count"] == 1
    assert evidence["running_distance_28d_km"] == 10.0
    assert evidence["recent_runs"][0]["pace_seconds_per_km"] == 357
