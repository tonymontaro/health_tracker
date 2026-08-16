from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DailyPlan,
    Equipment,
    Exercise,
    FoodItem,
    InventoryItem,
    MealTemplate,
    ProfileSnapshot,
    ShoppingPlan,
    TwoWeekPlan,
    UserProfile,
)
from app.schemas.plan import ProfileSnapshotSummary
from app.services.metrics import calculate_goal_progress_evidence, recalculate_derived_summary
from app.services.planner.domain import exercise_equipment_available
from app.services.planner.meal_selection import build_meal_selection_policy


def build_profile_snapshot(
    db: Session, profile: UserProfile, snapshot_date: date
) -> ProfileSnapshot:
    derived = recalculate_derived_summary(db, profile, snapshot_date - timedelta(days=1))
    training = derived.training_summary_json
    nutrition = derived.nutrition_summary_json

    if training.get("completed_28d", 0) == 0:
        training_status = "Recent training history is not yet established."
        recovery = "unknown"
        short = "Strength baseline recorded. Endurance history is still being established."
    else:
        adherence = training.get("adherence_rate_28d")
        difficulty = training.get("median_difficulty")
        training_status = (
            f"{training['completed_28d']} completed exercise entries in 28 days; "
            f"median difficulty {difficulty if difficulty is not None else 'unknown'}."
        )
        recovery = "normal" if difficulty is None or difficulty <= 7 else "recovery_cautioned"
        short = "Strength remains a priority. Aerobic consistency is adapting from recent results."
        if adherence is not None and adherence < 0.5:
            short = "Recent training adherence is low. Today favors a conservative, clear action."

    detailed = (
        f"Bodyweight: {profile.weight_kg or 'unknown'} kg. "
        f"Bench capacity: {profile.strength_capacity_json.get('bench_press', 'unknown')}. "
        f"Strict pull-up capacity: {profile.strength_capacity_json.get('strict_pull_up', 'unknown')}. "
        f"Training: {training_status} "
        f"Current target: {profile.current_target_goal or profile.primary_training_goal}."
    )
    snapshot = ProfileSnapshot(
        snapshot_date=snapshot_date,
        weight_kg=profile.weight_kg,
        training_status=training_status,
        strength_capacity_json=profile.strength_capacity_json,
        endurance_capacity_json=profile.endurance_capacity_json,
        recent_training_summary_json=training,
        recent_nutrition_summary_json=nutrition,
        recovery_status=recovery,
        adherence_summary={
            "training_28d": training.get("adherence_rate_28d"),
            "nutrition_14d": nutrition.get("adherence_rate_14d"),
        },
        important_constraints_json=[
            f"At most {profile.max_main_meals_per_day} main meals",
            f"At most {profile.max_exercises_per_day} exercises",
            "Gym only Saturday or Sunday",
            "Thursday rest or very light",
            "Avoid squat-based programming",
            "Pain blocks automatic progression",
        ],
        current_priorities_json=[
            "aerobic consistency",
            "strength retention",
            "low-effort nutrient-dense nutrition",
        ],
        short_summary=short,
        detailed_summary=detailed,
        source_quality_json={
            "weight_kg": "recorded",
            "strength_capacity": "recorded",
            "recent_training": "calculated",
            "recent_nutrition": "calculated",
            "running_goal": "goal",
            "recovery_status": "estimated" if recovery != "unknown" else "estimated",
        },
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def snapshot_summary(snapshot: ProfileSnapshot) -> ProfileSnapshotSummary:
    return ProfileSnapshotSummary(
        short_summary=snapshot.short_summary,
        detailed_summary=snapshot.detailed_summary,
        recovery_status=snapshot.recovery_status,
        strength_capacity=snapshot.strength_capacity_json,
        endurance_capacity=snapshot.endurance_capacity_json,
        recent_training=snapshot.recent_training_summary_json,
        recent_nutrition=snapshot.recent_nutrition_summary_json,
        source_quality=snapshot.source_quality_json,
    )


def build_planner_context(
    db: Session,
    profile: UserProfile,
    snapshot: ProfileSnapshot,
    plan_date: date,
    *,
    include_two_week_plan: bool = True,
) -> dict[str, Any]:
    yesterday = db.scalar(
        select(DailyPlan).where(DailyPlan.plan_date == plan_date - timedelta(days=1))
    )
    meals = list(db.scalars(select(MealTemplate).where(MealTemplate.active.is_(True))))
    exercises = list(db.scalars(select(Exercise).where(Exercise.active.is_(True))))
    equipment = list(db.scalars(select(Equipment).order_by(Equipment.name)))
    inventory_rows = db.execute(
        select(InventoryItem, FoodItem)
        .outerjoin(FoodItem, FoodItem.id == InventoryItem.food_item_id)
        .order_by(InventoryItem.created_at)
    ).all()
    week_start = plan_date - timedelta(days=plan_date.weekday())
    shopping = db.scalar(
        select(ShoppingPlan)
        .where(ShoppingPlan.week_start == week_start)
        .order_by(ShoppingPlan.created_at.desc())
    )
    profile_snapshot = snapshot_summary(snapshot).model_dump(mode="json")
    profile_snapshot.pop("recent_training", None)
    profile_snapshot.pop("recent_nutrition", None)

    training_summary = dict(snapshot.recent_training_summary_json)
    recent_sessions = training_summary.pop("recent_sessions", [])
    last_run = training_summary.pop("last_run", None)
    last_run_outside_recent_sessions = last_run
    if last_run and any(
        session.get("date") == last_run.get("date")
        and session.get("prescription") == last_run.get("prescription")
        and session.get("actual") == last_run.get("actual")
        for session in recent_sessions
    ):
        last_run_outside_recent_sessions = None

    nutrition_summary = dict(snapshot.recent_nutrition_summary_json)
    recent_meals = nutrition_summary.pop("recent_meals", [])
    context = {
        "current_date": plan_date.isoformat(),
        "day_of_week": plan_date.strftime("%A"),
        "timezone": profile.timezone,
        "profile": {
            "location": profile.location,
            "weight_kg": profile.weight_kg,
            "height_cm": profile.height_cm,
            "age": profile.age,
            "sex": profile.sex,
            "body_composition_goal": profile.body_composition_goal,
            "primary_training_goal": profile.primary_training_goal,
            "current_target_goal": profile.current_target_goal,
            "nutrition_preferences": profile.nutrition_preferences,
            "allergies": profile.allergies,
            "medical_constraints": profile.medical_constraints,
        },
        "hard_constraints": {
            "max_main_meals": profile.max_main_meals_per_day,
            "max_exercises": profile.max_exercises_per_day,
            "gym_days": profile.gym_days,
            "office_days": profile.office_days,
            "excluded_exercises": profile.excluded_exercises,
        },
        "profile_snapshot": profile_snapshot,
        "yesterday_plan": yesterday.current_plan_json if yesterday else None,
        "nutrition_summary_14d": nutrition_summary,
        "recent_nutrition_entries": recent_meals,
        "training_summary_28d": training_summary,
        "recent_training_sessions": recent_sessions,
        "last_run_outside_recent_sessions": last_run_outside_recent_sessions,
        "goal_progress_evidence": calculate_goal_progress_evidence(
            db, plan_date - timedelta(days=1)
        ),
        "meal_selection_policy": build_meal_selection_policy(db, profile, plan_date),
        "current_inventory": [
            {
                "food": food.name if food else row.custom_name,
                "item_type": row.item_type,
                "quantity": row.quantity_estimate,
                "quantity_label": row.quantity_label,
                "unit": row.unit,
                "confidence": row.confidence,
                "expires_on": row.expires_on.isoformat() if row.expires_on else None,
                "location": row.location,
                "notes": row.notes,
            }
            for row, food in inventory_rows
        ],
        "active_meal_templates": [
            {
                "name": meal.name,
                "description": meal.description,
                "ingredients": meal.ingredients_json,
                "hands_on_minutes": meal.hands_on_minutes,
                "total_minutes": meal.total_minutes,
                "batch_size": meal.batch_size,
                "freezer_friendly": meal.freezer_friendly,
                "estimated_protein_g": meal.estimated_protein_g,
                "estimated_fiber_g": meal.estimated_fiber_g,
                "produce_portions": meal.produce_portions,
                "effort_score": meal.effort_score,
                "preference_score": meal.preference_score,
                "tags": meal.tags,
            }
            for meal in meals
        ],
        "active_exercise_catalog": [
            {
                "name": exercise.name,
                "category": exercise.category,
                "gym_only": exercise.gym_only,
                "measurement_type": exercise.measurement_type,
                "equipment_required": exercise.equipment_required,
                "available_today": exercise_equipment_available(db, exercise),
            }
            for exercise in exercises
        ],
        "equipment": [
            {"name": item.name, "category": item.category, "available": item.available}
            for item in equipment
        ],
        "upcoming_schedule_constraints": {
            "today": plan_date.strftime("%A"),
            "thursday_commute_hours": round(
                float(profile.nutrition_preferences.get("thursday_commute_minutes", 180)) / 60,
                1,
            ),
        },
        "shopping_state": shopping.items_json if shopping else None,
    }
    if include_two_week_plan:
        horizon = db.scalar(
            select(TwoWeekPlan)
            .where(
                TwoWeekPlan.anchor_date <= plan_date,
                TwoWeekPlan.window_start <= plan_date,
                TwoWeekPlan.window_end >= plan_date,
            )
            .order_by(TwoWeekPlan.anchor_date.desc())
        )
        if horizon is not None:
            days = horizon.plan_json.get("days", [])
            current_day = next(
                (day for day in days if day.get("plan_date") == plan_date.isoformat()), None
            )
            context["receding_horizon"] = {
                "anchor_date": horizon.anchor_date.isoformat(),
                "window_start": horizon.window_start.isoformat(),
                "window_end": horizon.window_end.isoformat(),
                "summary": horizon.plan_json.get("summary"),
                "training_strategy": horizon.plan_json.get("training_strategy"),
                "nutrition_strategy": horizon.plan_json.get("nutrition_strategy"),
                "adjustment_summary": horizon.plan_json.get("adjustment_summary"),
                "current_day_guidance": current_day,
                "full_fourteen_day_horizon": days,
                "daily_adaptation_rule": (
                    "Prefer the current-day guidance, but adapt today's concrete plan when recent "
                    "outcomes or hard constraints justify it. Explain material deviations."
                ),
            }
    return context
