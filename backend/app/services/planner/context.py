from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DailyPlan,
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
from app.schemas.two_week_plan import parse_two_week_plan_document
from app.services.metrics import calculate_goal_progress_evidence, recalculate_derived_summary
from app.services.planner.domain import exercise_equipment_available
from app.services.planner.meal_selection import (
    build_meal_selection_policy,
    eligible_main_meal_templates,
)
from app.services.training_plan_guide import (
    daily_training_plan_guide_context,
    training_plan_guide_context,
)


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


def _compact_mapping(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    compact = {
        key: item for key, item in value.items() if item is not None and item != [] and item != {}
    }
    return compact or None


def _profile_context(profile: UserProfile) -> dict[str, Any]:
    return {
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
    }


def _hard_constraints(profile: UserProfile) -> dict[str, Any]:
    return {
        "max_main_meals": profile.max_main_meals_per_day,
        "max_exercises": profile.max_exercises_per_day,
        "gym_days": profile.gym_days,
        "office_days": profile.office_days,
        "excluded_exercises": profile.excluded_exercises,
    }


def _snapshot_context(snapshot: ProfileSnapshot) -> dict[str, Any]:
    result = snapshot_summary(snapshot).model_dump(mode="json")
    result.pop("recent_training", None)
    result.pop("recent_nutrition", None)
    return result


def _training_evidence(
    snapshot: ProfileSnapshot,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    summary = dict(snapshot.recent_training_summary_json)
    recent_sessions = summary.pop("recent_sessions", [])
    last_run = summary.pop("last_run", None)
    compact_sessions = [
        {
            key: compact
            for key, item in session.items()
            if (compact := _compact_mapping(item) if isinstance(item, dict) else item) is not None
        }
        for session in recent_sessions
    ]
    last_run_outside_sessions = last_run
    if last_run and any(
        session.get("date") == last_run.get("date")
        and session.get("prescription") == last_run.get("prescription")
        and session.get("actual") == last_run.get("actual")
        for session in recent_sessions
    ):
        last_run_outside_sessions = None
    return summary, compact_sessions, _compact_mapping(last_run_outside_sessions)


def _nutrition_evidence(snapshot: ProfileSnapshot) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary = dict(snapshot.recent_nutrition_summary_json)
    recent_meals = summary.pop("recent_meals", [])
    return summary, recent_meals


def _base_context(
    profile: UserProfile,
    snapshot: ProfileSnapshot,
    plan_date: date,
) -> dict[str, Any]:
    return {
        "current_date": plan_date.isoformat(),
        "day_of_week": plan_date.strftime("%A"),
        "timezone": profile.timezone,
        "profile": _profile_context(profile),
        "hard_constraints": _hard_constraints(profile),
        "profile_snapshot": _snapshot_context(snapshot),
        "upcoming_schedule_constraints": {
            "today": plan_date.strftime("%A"),
            "thursday_commute_hours": round(
                float(profile.nutrition_preferences.get("thursday_commute_minutes", 180)) / 60,
                1,
            ),
        },
    }


def _yesterday_plan_summary(db: Session, plan_date: date) -> dict[str, Any] | None:
    yesterday = db.scalar(
        select(DailyPlan).where(DailyPlan.plan_date == plan_date - timedelta(days=1))
    )
    if yesterday is None:
        return None
    plan = yesterday.current_plan_json
    workout = plan.get("workout") or {}
    nutrition = plan.get("nutrition") or {}
    meal_2 = nutrition.get("meal_2") or {}
    return {
        "plan_date": yesterday.plan_date.isoformat(),
        "short_summary": plan.get("short_summary"),
        "workout": {
            key: workout.get(key)
            for key in ("kind", "intensity", "title", "expected_duration_minutes", "summary")
        },
        "main_meal_templates": [
            name
            for name in (
                (nutrition.get("meal_1") or {}).get("template_name"),
                meal_2.get("template_name"),
            )
            if name
        ],
    }


def _meal_templates(
    db: Session,
    profile: UserProfile,
    plan_date: date,
    *,
    include_recipe_inputs: bool,
    window_days: int = 1,
) -> list[dict[str, Any]]:
    templates_by_name: dict[str, MealTemplate] = {}
    for offset in range(window_days):
        for template in eligible_main_meal_templates(
            db, profile, plan_date + timedelta(days=offset)
        ):
            templates_by_name.setdefault(template.name.casefold(), template)
    templates = list(templates_by_name.values())
    result: list[dict[str, Any]] = []
    for meal in templates:
        item = {
            "name": meal.name,
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
        if include_recipe_inputs:
            item["description"] = meal.description
            item["ingredients"] = meal.ingredients_json
        result.append(item)
    return result


def _exercise_catalog(
    db: Session,
    profile: UserProfile,
    plan_date: date,
    *,
    include_future_gym_options: bool,
) -> list[dict[str, Any]]:
    weekday = plan_date.strftime("%A")
    result: list[dict[str, Any]] = []
    for exercise in db.scalars(select(Exercise).where(Exercise.active.is_(True))):
        key = exercise.name.casefold()
        if any(excluded.casefold() in key for excluded in profile.excluded_exercises):
            continue
        if not exercise_equipment_available(db, exercise):
            continue
        if (
            exercise.gym_only
            and not include_future_gym_options
            and (weekday not in {"Saturday", "Sunday"} or weekday not in profile.gym_days)
        ):
            continue
        if (
            exercise.gym_only
            and include_future_gym_options
            and not set(profile.gym_days).intersection({"Saturday", "Sunday"})
        ):
            continue
        catalog_item = {
            "name": exercise.name,
            "category": exercise.category,
            "gym_only": exercise.gym_only,
            "measurement_type": exercise.measurement_type,
            "equipment_required": exercise.equipment_required,
        }
        if not include_future_gym_options:
            catalog_item["available_today"] = True
        result.append(catalog_item)
    return result


def _inventory_context(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(InventoryItem, FoodItem)
        .outerjoin(FoodItem, FoodItem.id == InventoryItem.food_item_id)
        .order_by(InventoryItem.created_at)
    ).all()
    return [
        {
            key: value
            for key, value in {
                "food": food.name if food else row.custom_name,
                "item_type": row.item_type,
                "quantity": row.quantity_estimate,
                "quantity_label": row.quantity_label,
                "unit": row.unit,
                "confidence": row.confidence,
                "expires_on": row.expires_on.isoformat() if row.expires_on else None,
                "location": row.location,
                "notes": row.notes,
            }.items()
            if value is not None
        }
        for row, food in rows
    ]


def _shopping_context(db: Session, plan_date: date) -> list[dict[str, Any]] | None:
    week_start = plan_date - timedelta(days=plan_date.weekday())
    shopping = db.scalar(
        select(ShoppingPlan)
        .where(ShoppingPlan.week_start == week_start)
        .order_by(ShoppingPlan.created_at.desc())
    )
    return shopping.items_json if shopping else None


def _horizon_context(db: Session, plan_date: date) -> dict[str, Any] | None:
    horizon = db.scalar(
        select(TwoWeekPlan)
        .where(
            TwoWeekPlan.anchor_date <= plan_date,
            TwoWeekPlan.window_start <= plan_date,
            TwoWeekPlan.window_end >= plan_date,
        )
        .order_by(TwoWeekPlan.anchor_date.desc(), TwoWeekPlan.revision.desc())
    )
    if horizon is None:
        return None
    document = parse_two_week_plan_document(horizon.plan_json)
    current_index = next(
        (index for index, day in enumerate(document.days) if day.plan_date == plan_date),
        None,
    )
    current_day = document.days[current_index] if current_index is not None else None
    nearby_days = (
        document.days[current_index + 1 : current_index + 4] if current_index is not None else []
    )
    return {
        "anchor_date": horizon.anchor_date.isoformat(),
        "window_end": horizon.window_end.isoformat(),
        "summary": document.summary,
        "training_strategy": document.training_strategy,
        "nutrition_strategy": document.nutrition_strategy,
        "adjustment_summary": document.adjustment_summary,
        "current_day_guidance": (
            current_day.model_dump(mode="json") if current_day is not None else None
        ),
        "next_three_days": [day.model_dump(mode="json") for day in nearby_days],
    }


def build_daily_planner_context(
    db: Session,
    profile: UserProfile,
    snapshot: ProfileSnapshot,
    plan_date: date,
) -> dict[str, Any]:
    training_summary, sessions, last_run = _training_evidence(snapshot)
    nutrition_summary, recent_meals = _nutrition_evidence(snapshot)
    context = _base_context(profile, snapshot, plan_date)
    context.update(
        {
            "yesterday_plan_summary": _yesterday_plan_summary(db, plan_date),
            "nutrition_summary_14d": nutrition_summary,
            "recent_nutrition_entries": recent_meals,
            "training_summary_28d": training_summary,
            "recent_training_sessions": sessions,
            "last_run_outside_recent_sessions": last_run,
            "goal_progress_evidence": calculate_goal_progress_evidence(
                db, plan_date - timedelta(days=1)
            ),
            "meal_selection_policy": build_meal_selection_policy(db, profile, plan_date),
            "current_inventory": _inventory_context(db),
            "active_meal_templates": _meal_templates(
                db, profile, plan_date, include_recipe_inputs=True
            ),
            "active_exercise_catalog": _exercise_catalog(
                db, profile, plan_date, include_future_gym_options=False
            ),
            "shopping_state": _shopping_context(db, plan_date),
            "active_training_plan_guide": daily_training_plan_guide_context(db, profile, plan_date),
            "receding_horizon": _horizon_context(db, plan_date),
        }
    )
    return context


def build_horizon_planner_context(
    db: Session,
    profile: UserProfile,
    snapshot: ProfileSnapshot,
    plan_date: date,
) -> dict[str, Any]:
    training_summary, sessions, last_run = _training_evidence(snapshot)
    nutrition_summary, _ = _nutrition_evidence(snapshot)
    context = _base_context(profile, snapshot, plan_date)
    context.update(
        {
            "nutrition_summary_14d": nutrition_summary,
            "training_summary_28d": training_summary,
            "recent_training_sessions": sessions,
            "last_run_outside_recent_sessions": last_run,
            "goal_progress_evidence": calculate_goal_progress_evidence(
                db, plan_date - timedelta(days=1)
            ),
            "meal_selection_policy": build_meal_selection_policy(db, profile, plan_date),
            "active_meal_templates": _meal_templates(
                db,
                profile,
                plan_date,
                include_recipe_inputs=False,
                window_days=14,
            ),
            "active_exercise_catalog": _exercise_catalog(
                db, profile, plan_date, include_future_gym_options=True
            ),
            "active_training_plan_guide": training_plan_guide_context(db, profile, plan_date),
        }
    )
    return context


def build_workout_regeneration_context(
    db: Session,
    profile: UserProfile,
    snapshot: ProfileSnapshot,
    plan_date: date,
) -> dict[str, Any]:
    training_summary, sessions, last_run = _training_evidence(snapshot)
    context = _base_context(profile, snapshot, plan_date)
    context.update(
        {
            "training_summary_28d": training_summary,
            "recent_training_sessions": sessions,
            "last_run_outside_recent_sessions": last_run,
            "goal_progress_evidence": calculate_goal_progress_evidence(
                db, plan_date - timedelta(days=1)
            ),
            "active_exercise_catalog": _exercise_catalog(
                db, profile, plan_date, include_future_gym_options=False
            ),
            "active_training_plan_guide": daily_training_plan_guide_context(db, profile, plan_date),
            "receding_horizon": _horizon_context(db, plan_date),
        }
    )
    return context


def build_nutrition_regeneration_context(
    db: Session,
    profile: UserProfile,
    snapshot: ProfileSnapshot,
    plan_date: date,
) -> dict[str, Any]:
    nutrition_summary, recent_meals = _nutrition_evidence(snapshot)
    context = _base_context(profile, snapshot, plan_date)
    context.update(
        {
            "nutrition_summary_14d": nutrition_summary,
            "recent_nutrition_entries": recent_meals,
            "meal_selection_policy": build_meal_selection_policy(db, profile, plan_date),
            "current_inventory": _inventory_context(db),
            "active_meal_templates": _meal_templates(
                db, profile, plan_date, include_recipe_inputs=True
            ),
            "shopping_state": _shopping_context(db, plan_date),
        }
    )
    return context


def build_qa_context(
    db: Session,
    profile: UserProfile,
    snapshot: ProfileSnapshot,
    plan_date: date,
) -> dict[str, Any]:
    context = build_daily_planner_context(db, profile, snapshot, plan_date)
    context.pop("yesterday_plan_summary", None)
    return context
