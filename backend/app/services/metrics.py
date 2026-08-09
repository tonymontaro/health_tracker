from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DerivedSummary, NutritionEntry, UserProfile, WorkoutEntry


def calculate_training_summary(db: Session, as_of: date) -> dict[str, Any]:
    since_28 = as_of - timedelta(days=27)
    entries = list(
        db.scalars(select(WorkoutEntry).where(WorkoutEntry.entry_date.between(since_28, as_of)))
    )
    entries.sort(key=lambda entry: (entry.entry_date, entry.created_at))
    completed = [entry for entry in entries if entry.status in {"completed", "partial"}]
    planned = entries
    difficulties = [
        entry.difficulty_1_to_10 for entry in completed if entry.difficulty_1_to_10 is not None
    ]
    runs = [entry for entry in completed if entry.prescription_json.get("exercise_type") == "run"]
    run_distance = sum(float((entry.actual_json or {}).get("distance_km", 0)) for entry in runs)
    completed_dates = {entry.entry_date for entry in completed}
    planned_dates = {entry.entry_date for entry in planned}
    strength_volume: dict[str, float] = {}
    best_recent_set: dict[str, dict[str, float | int]] = {}
    for entry in completed:
        kind = entry.prescription_json.get("exercise_type")
        if kind not in {"strength", "bodyweight"}:
            continue
        actual = entry.actual_json or {}
        load = float(
            actual.get("load_kg")
            or actual.get("external_load_kg")
            or entry.prescription_json.get("load_kg")
            or entry.prescription_json.get("external_load_kg")
            or 0
        )
        reps = actual.get("reps_per_set") or entry.prescription_json.get("reps_per_set") or []
        total_reps = sum(int(value) for value in reps)
        strength_volume[entry.exercise_name] = round(
            strength_volume.get(entry.exercise_name, 0) + load * total_reps, 1
        )
        prior = best_recent_set.get(entry.exercise_name)
        best_reps = max((int(value) for value in reps), default=0)
        if prior is None or load > float(prior["load_kg"]):
            best_recent_set[entry.exercise_name] = {
                "load_kg": load,
                "reps": best_reps,
            }
    hard_dates = {entry.entry_date for entry in completed if (entry.difficulty_1_to_10 or 0) >= 8}
    consecutive_hard_days = 0
    cursor = as_of
    while cursor in hard_dates:
        consecutive_hard_days += 1
        cursor -= timedelta(days=1)
    return {
        "completed_7d": sum(value >= as_of - timedelta(days=6) for value in completed_dates),
        "completed_14d": sum(value >= as_of - timedelta(days=13) for value in completed_dates),
        "completed_28d": len(completed_dates),
        "planned_28d": len(planned_dates),
        "completed_exercise_entries_28d": len(completed),
        "adherence_rate_28d": (
            round(len(completed_dates) / len(planned_dates), 2) if planned_dates else None
        ),
        "median_difficulty": float(median(difficulties)) if difficulties else None,
        "average_difficulty": (
            round(sum(difficulties) / len(difficulties), 1) if difficulties else None
        ),
        "running_distance_28d_km": round(run_distance, 1),
        "last_run": (
            {
                "date": runs[-1].entry_date.isoformat(),
                "prescription": runs[-1].prescription_json,
                "actual": runs[-1].actual_json,
                "difficulty": runs[-1].difficulty_1_to_10,
            }
            if runs
            else None
        ),
        "strength_volume_28d": strength_volume,
        "best_recent_set": best_recent_set,
        "hard_training_days_28d": len(hard_dates),
        "consecutive_hard_days": consecutive_hard_days,
        "pain_flags_28d": sum(entry.pain_flag for entry in entries),
        "recent_sessions": [
            {
                "date": entry.entry_date.isoformat(),
                "exercise": entry.exercise_name,
                "status": entry.status,
                "difficulty": entry.difficulty_1_to_10,
                "prescription": entry.prescription_json,
                "actual": entry.actual_json,
                "pain": entry.pain_flag,
            }
            for entry in sorted(entries, key=lambda item: item.entry_date, reverse=True)[:12]
        ],
    }


def calculate_nutrition_summary(db: Session, as_of: date) -> dict[str, Any]:
    since_14 = as_of - timedelta(days=13)
    entries = list(
        db.scalars(select(NutritionEntry).where(NutritionEntry.entry_date.between(since_14, as_of)))
    )
    planned_mains = [
        entry
        for entry in entries
        if entry.planned_recommendation_id is not None and entry.meal_slot in {"meal_1", "meal_2"}
    ]
    followed_planned_mains = [
        entry
        for entry in planned_mains
        if entry.status in {"confirmed", "assumed_consumed", "matched_by_food_log"}
    ]
    consumed_all = [entry for entry in entries if entry.status in {"confirmed", "assumed_consumed"}]
    consumed_mains = [entry for entry in consumed_all if entry.meal_slot in {"meal_1", "meal_2"}]
    recorded_dates = {entry.entry_date for entry in consumed_all}
    estimated_protein = sum(
        float(entry.quantity_json.get("estimated_protein_g") or 0) for entry in consumed_all
    )
    fruit_days = {entry.entry_date for entry in consumed_all if entry.meal_slot == "fruit"}
    meal_names: dict[str, int] = {}
    for entry in consumed_mains:
        name = entry.food_or_meal_reference or entry.description
        meal_names[name] = meal_names.get(name, 0) + 1
    return {
        "main_meals_planned_14d": len(planned_mains),
        "main_meals_consumed_14d": len(consumed_mains),
        "adherence_rate_14d": (
            round(len(followed_planned_mains) / len(planned_mains), 2) if planned_mains else None
        ),
        "confirmed_count": sum(entry.status == "confirmed" for entry in consumed_all),
        "assumed_count": sum(entry.status == "assumed_consumed" for entry in consumed_all),
        "skipped_count": sum(entry.status == "skipped" for entry in entries),
        "discarded_by_food_log_count": sum(
            entry.status == "discarded_by_food_log" for entry in entries
        ),
        "matched_by_food_log_count": sum(
            entry.status == "matched_by_food_log" for entry in entries
        ),
        "ai_logged_meal_count": sum(entry.source == "ai_food_log" for entry in consumed_all),
        "manual_replacements": sum(entry.source == "history_correction" for entry in entries),
        "rough_protein_average_g": (
            round(estimated_protein / len(recorded_dates), 1) if recorded_dates else None
        ),
        "fruit_days_14d": len(fruit_days),
        "meal_repetition": meal_names,
        "average_main_meal_effort_minutes": (
            round(
                sum(
                    float(entry.quantity_json.get("hands_on_minutes") or 0)
                    for entry in consumed_mains
                )
                / len(consumed_mains),
                1,
            )
            if consumed_mains
            else None
        ),
        "recent_meals": [
            {
                "date": entry.entry_date.isoformat(),
                "slot": entry.meal_slot,
                "description": entry.description,
                "status": entry.status,
            }
            for entry in sorted(entries, key=lambda item: item.entry_date, reverse=True)[:16]
        ],
    }


def recalculate_derived_summary(db: Session, profile: UserProfile, as_of: date) -> DerivedSummary:
    summary = db.scalar(select(DerivedSummary).where(DerivedSummary.profile_id == profile.id))
    if summary is None:
        summary = DerivedSummary(profile_id=profile.id)
        db.add(summary)
    summary.training_summary_json = calculate_training_summary(db, as_of)
    summary.nutrition_summary_json = calculate_nutrition_summary(db, as_of)
    summary.calculated_at = datetime.now(UTC)
    db.flush()
    return summary
