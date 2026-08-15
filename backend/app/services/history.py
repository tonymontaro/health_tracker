from copy import deepcopy
from datetime import UTC, date, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select, union
from sqlalchemy.orm import Session

from app.db.models import (
    DailyFoodLog,
    DailyPlan,
    DailyWorkoutLog,
    NutritionEntry,
    PlanModification,
    ProfileSnapshot,
    UserProfile,
    WorkoutEntry,
)
from app.schemas.plan import DailyPlanDocument, proposal_from_document
from app.services.food_log import serialize_food_log
from app.services.inventory import adjust_nutrition_entry_inventory
from app.services.metrics import recalculate_derived_summary
from app.services.planner.domain import validate_plan
from app.services.workout_log import serialize_workout_log


def history_index(db: Session, limit: int = 90) -> list[dict[str, Any]]:
    date_union = union(
        select(DailyPlan.plan_date.label("entry_date")),
        select(NutritionEntry.entry_date.label("entry_date")),
        select(WorkoutEntry.entry_date.label("entry_date")),
        select(DailyFoodLog.log_date.label("entry_date")),
        select(DailyWorkoutLog.log_date.label("entry_date")),
    ).subquery()
    dates = list(
        db.scalars(
            select(date_union.c.entry_date).order_by(date_union.c.entry_date.desc()).limit(limit)
        )
    )
    if not dates:
        return []

    plans = {
        plan.plan_date: plan
        for plan in db.scalars(select(DailyPlan).where(DailyPlan.plan_date.in_(dates)))
    }
    nutrition_counts: dict[date, int] = {
        entry_date: int(count)
        for entry_date, count in db.execute(
            select(NutritionEntry.entry_date, func.count(NutritionEntry.id))
            .where(NutritionEntry.entry_date.in_(dates))
            .group_by(NutritionEntry.entry_date)
        ).all()
    }
    workout_counts = {
        entry_date: {"total": int(total), "strava": int(strava)}
        for entry_date, total, strava in db.execute(
            select(
                WorkoutEntry.entry_date,
                func.count(WorkoutEntry.id),
                func.count(WorkoutEntry.id).filter(WorkoutEntry.source == "strava"),
            )
            .where(WorkoutEntry.entry_date.in_(dates))
            .group_by(WorkoutEntry.entry_date)
        ).all()
    }
    food_log_dates = set(
        db.scalars(select(DailyFoodLog.log_date).where(DailyFoodLog.log_date.in_(dates)))
    )
    workout_log_dates = set(
        db.scalars(select(DailyWorkoutLog.log_date).where(DailyWorkoutLog.log_date.in_(dates)))
    )

    result: list[dict[str, Any]] = []
    for entry_date in dates:
        plan = plans.get(entry_date)
        nutrition_count = int(nutrition_counts.get(entry_date, 0))
        workout_count = workout_counts.get(entry_date, {"total": 0, "strava": 0})
        result.append(
            {
                "date": entry_date.isoformat(),
                "summary": plan.short_summary if plan else "Recorded health activity",
                "source": plan.current_plan_json.get("source") if plan else "recorded",
                "nutrition_count": nutrition_count,
                "workout_count": workout_count["total"],
                "strava_activity_count": workout_count["strava"],
                "has_food_log": entry_date in food_log_dates,
                "has_workout_log": entry_date in workout_log_dates,
            }
        )
    return result


def reconcile_day(db: Session, target_date: date) -> dict[str, int]:
    meals = list(
        db.scalars(
            select(NutritionEntry).where(
                NutritionEntry.entry_date == target_date,
                NutritionEntry.status == "planned",
            )
        )
    )
    assumed_meals = 0
    for entry in meals:
        if entry.meal_slot in {"meal_1", "meal_2"} or entry.expected:
            entry.status = "assumed_consumed"
            adjust_nutrition_entry_inventory(db, entry, direction=-1)
            assumed_meals += 1
    workouts = list(
        db.scalars(
            select(WorkoutEntry).where(
                WorkoutEntry.entry_date == target_date,
                WorkoutEntry.status == "planned",
            )
        )
    )
    for workout_entry in workouts:
        workout_entry.status = "skipped_assumed"
    profile = db.scalar(select(UserProfile))
    if profile:
        recalculate_derived_summary(db, profile, target_date)
    db.commit()
    return {"assumed_meals": assumed_meals, "assumed_skipped_exercises": len(workouts)}


def correct_nutrition_entry(
    db: Session, entry: NutritionEntry, changes: dict[str, Any], as_of: date
) -> NutritionEntry:
    old_consumed = entry.status in {"confirmed", "assumed_consumed"}
    quantity_changed = "quantity" in changes and changes["quantity"] is not None
    if old_consumed and quantity_changed:
        adjust_nutrition_entry_inventory(db, entry, direction=1)
    if "description" in changes and changes["description"] is not None:
        entry.description = changes["description"]
    if "quantity" in changes and changes["quantity"] is not None:
        entry.quantity_json = changes["quantity"]
    if "status" in changes and changes["status"] is not None:
        entry.status = changes["status"]
    new_consumed = entry.status in {"confirmed", "assumed_consumed"}
    if new_consumed and quantity_changed:
        adjust_nutrition_entry_inventory(db, entry, direction=-1)
    elif old_consumed != new_consumed:
        adjust_nutrition_entry_inventory(db, entry, direction=-1 if new_consumed else 1)
    entry.source = "history_correction"
    profile = db.scalar(select(UserProfile))
    if profile:
        recalculate_derived_summary(db, profile, as_of)
    db.commit()
    db.refresh(entry)
    return entry


def correct_workout_entry(
    db: Session, entry: WorkoutEntry, changes: dict[str, Any], as_of: date
) -> WorkoutEntry:
    requested_status = changes.get("status")
    requested_actual = changes.get("actual")
    if requested_status == "completed" and not (requested_actual or entry.actual_json):
        raise ValueError("A completed workout requires actual performance evidence")
    for field, model_field in (
        ("actual", "actual_json"),
        ("difficulty_1_to_10", "difficulty_1_to_10"),
        ("status", "status"),
        ("pain_flag", "pain_flag"),
        ("notes", "notes"),
    ):
        if field in changes and changes[field] is not None:
            setattr(entry, model_field, changes[field])
    entry.source = "history_correction"
    entry.workout_log_id = None
    profile = db.scalar(select(UserProfile))
    if profile:
        recalculate_derived_summary(db, profile, as_of)
    db.commit()
    db.refresh(entry)
    return entry


def history_day(db: Session, target_date: date) -> dict[str, Any]:
    plan = db.scalar(select(DailyPlan).where(DailyPlan.plan_date == target_date))
    food_log = db.scalar(select(DailyFoodLog).where(DailyFoodLog.log_date == target_date))
    workout_log = db.scalar(select(DailyWorkoutLog).where(DailyWorkoutLog.log_date == target_date))
    nutrition = list(
        db.scalars(
            select(NutritionEntry)
            .where(NutritionEntry.entry_date == target_date)
            .order_by(NutritionEntry.created_at)
        )
    )
    workouts = list(
        db.scalars(
            select(WorkoutEntry)
            .where(WorkoutEntry.entry_date == target_date)
            .order_by(WorkoutEntry.created_at)
        )
    )
    snapshot = db.get(ProfileSnapshot, plan.profile_snapshot_id) if plan else None
    return {
        "date": target_date.isoformat(),
        "original_plan": plan.original_plan_json if plan else None,
        "current_plan": plan.current_plan_json if plan else None,
        "nutrition": [serialize_nutrition(item) for item in nutrition],
        "workouts": [serialize_workout(item) for item in workouts],
        "profile_snapshot": (
            {
                "short_summary": snapshot.short_summary,
                "detailed_summary": snapshot.detailed_summary,
                "source_quality": snapshot.source_quality_json,
            }
            if snapshot
            else None
        ),
        "food_log": serialize_food_log(food_log),
        "workout_log": serialize_workout_log(workout_log),
    }


def serialize_nutrition(entry: NutritionEntry) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "date": entry.entry_date.isoformat(),
        "meal_slot": entry.meal_slot,
        "recommendation_id": entry.planned_recommendation_id,
        "description": entry.description,
        "quantity": entry.quantity_json,
        "source": entry.source,
        "status": entry.status,
        "expected": entry.expected,
        "food_log_id": str(entry.food_log_id) if entry.food_log_id else None,
    }


def serialize_workout(entry: WorkoutEntry) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "date": entry.entry_date.isoformat(),
        "recommendation_id": entry.planned_recommendation_id,
        "exercise_name": entry.exercise_name,
        "prescription": entry.prescription_json,
        "actual": entry.actual_json,
        "difficulty_1_to_10": entry.difficulty_1_to_10,
        "status": entry.status,
        "source": entry.source,
        "pain_flag": entry.pain_flag,
        "notes": entry.notes,
        "workout_log_id": str(entry.workout_log_id) if entry.workout_log_id else None,
    }


def replace_recommendation(
    db: Session,
    plan: DailyPlan,
    recommendation_id: str,
    replacement: dict[str, Any],
    reason: str,
    source: str,
) -> DailyPlan:
    payload = deepcopy(plan.current_plan_json)
    found = _replace_in_payload(payload, recommendation_id, replacement)
    if found is None:
        raise LookupError("Recommendation was not found in the active plan")
    try:
        document = DailyPlanDocument.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Replacement does not match the plan schema: {exc}") from exc
    profile = db.scalar(select(UserProfile))
    if profile is None:
        raise RuntimeError("Profile is missing")
    errors = validate_plan(
        db,
        proposal_from_document(document),
        profile,
        plan.plan_date,
        enforce_meal_selection_policy=False,
    )
    if errors:
        raise ValueError("Replacement violates domain rules: " + "; ".join(errors))
    db.add(
        PlanModification(
            daily_plan_id=plan.id,
            recommendation_id=recommendation_id,
            original_json=found,
            replacement_json=replacement,
            reason=reason,
            source=source,
        )
    )
    plan.current_plan_json = document.model_dump(mode="json")
    _update_materialized_entry(db, plan.plan_date, recommendation_id, replacement)
    db.commit()
    db.refresh(plan)
    return plan


def _replace_in_payload(
    payload: dict[str, Any], recommendation_id: str, replacement: dict[str, Any]
) -> dict[str, Any] | None:
    nutrition = payload["nutrition"]
    candidates: list[dict[str, Any]] = [nutrition["meal_1"]]
    if nutrition.get("meal_2"):
        candidates.append(nutrition["meal_2"])
    candidates.extend(nutrition.get("fruits", []))
    candidates.extend(nutrition.get("snacks", []))
    candidates.extend(payload["workout"].get("exercises", []))
    for candidate in candidates:
        if candidate.get("recommendation_id") == recommendation_id:
            original = deepcopy(candidate)
            stable_id = candidate["recommendation_id"]
            candidate.update(replacement)
            candidate["recommendation_id"] = stable_id
            return original
    return None


def _update_materialized_entry(
    db: Session, plan_date: date, recommendation_id: str, replacement: dict[str, Any]
) -> None:
    nutrition = db.scalar(
        select(NutritionEntry).where(
            NutritionEntry.entry_date == plan_date,
            NutritionEntry.planned_recommendation_id == recommendation_id,
        )
    )
    if nutrition:
        nutrition.description = replacement.get("description", nutrition.description)
        nutrition.food_or_meal_reference = replacement.get(
            "template_name", replacement.get("name", nutrition.food_or_meal_reference)
        )
        nutrition.source = "manual"
        return
    workout = db.scalar(
        select(WorkoutEntry).where(
            WorkoutEntry.entry_date == plan_date,
            WorkoutEntry.planned_recommendation_id == recommendation_id,
        )
    )
    if workout:
        workout.prescription_json = {**workout.prescription_json, **replacement}
        workout.exercise_name = replacement.get("exercise_name", workout.exercise_name)
        workout.source = "manual"


def now_utc() -> datetime:
    return datetime.now(UTC)
