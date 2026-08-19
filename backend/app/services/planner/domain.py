from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Equipment, Exercise, MealTemplate, UserProfile, WorkoutEntry
from app.schemas.plan import DailyPlanProposal, ExerciseProposal
from app.schemas.two_week_plan import TwoWeekPlanProposal
from app.services.planner.meal_selection import (
    eligible_main_meal_templates,
    is_special_meal,
    recommended_main_meal_history,
    special_meal_required_today,
)


def _measurable(exercise: ExerciseProposal) -> bool:
    if exercise.exercise_type.value == "strength":
        return bool(
            exercise.load_kg is not None
            and exercise.sets
            and (
                (exercise.reps_per_set and len(exercise.reps_per_set) == exercise.sets)
                or exercise.duration_seconds
            )
            and exercise.rest_seconds is not None
        )
    if exercise.exercise_type.value == "bodyweight":
        return bool(
            exercise.external_load_kg is not None
            and exercise.sets
            and (
                (exercise.reps_per_set and len(exercise.reps_per_set) == exercise.sets)
                or exercise.duration_seconds
            )
            and exercise.rest_seconds is not None
        )
    if exercise.exercise_type.value == "run":
        return bool(
            exercise.distance_km and exercise.pace_seconds_per_km and exercise.duration_seconds
        )
    if exercise.exercise_type.value == "bike":
        return bool(
            exercise.duration_seconds
            and (
                exercise.target_power_min_watts
                or (exercise.cadence_min_rpm and exercise.cadence_max_rpm)
            )
        )
    if exercise.exercise_type.value == "recovery":
        return bool(exercise.duration_seconds)
    return False


def validate_plan(
    db: Session,
    proposal: DailyPlanProposal,
    profile: UserProfile,
    plan_date: date,
    *,
    enforce_meal_selection_policy: bool = True,
) -> list[str]:
    errors: list[str] = []
    if proposal.nutrition.expected_main_meals not in {1, 2}:
        errors.append("The plan must contain one or two main meals.")
    if proposal.nutrition.expected_main_meals > profile.max_main_meals_per_day:
        errors.append("The plan exceeds the profile's maximum number of main meals.")
    if len(proposal.workout.exercises) > profile.max_exercises_per_day:
        errors.append("The plan exceeds the profile's maximum number of exercises.")
    if len(proposal.prep_actions) > 1:
        errors.append("The plan contains more than one preparation session.")

    weekday = plan_date.strftime("%A")
    exercise_catalog = {
        exercise.name.casefold(): exercise
        for exercise in db.scalars(select(Exercise).where(Exercise.active.is_(True)))
    }
    seen: set[str] = set()
    for prescription in proposal.workout.exercises:
        key = prescription.exercise_name.casefold()
        catalog_item = exercise_catalog.get(key)
        if catalog_item is None:
            errors.append(f"Unknown exercise: {prescription.exercise_name}.")
            continue
        if key in seen:
            errors.append(f"Duplicate exercise: {prescription.exercise_name}.")
        seen.add(key)
        if catalog_item.gym_only and (
            weekday not in {"Saturday", "Sunday"} or weekday not in profile.gym_days
        ):
            errors.append(
                f"Gym-only exercise {prescription.exercise_name} is not allowed on {weekday}."
            )
        if not exercise_equipment_available(db, catalog_item):
            errors.append(f"Required equipment is unavailable for {prescription.exercise_name}.")
        if any(excluded.casefold() in key for excluded in profile.excluded_exercises):
            errors.append(f"Excluded exercise: {prescription.exercise_name}.")
        if not _measurable(prescription):
            errors.append(f"Exercise lacks a measurable workload: {prescription.exercise_name}.")
        previous = db.scalar(
            select(WorkoutEntry)
            .where(func.lower(WorkoutEntry.exercise_name) == key)
            .order_by(WorkoutEntry.entry_date.desc())
        )
        if (
            previous
            and previous.pain_flag
            and _workload_increased(previous.prescription_json, prescription)
        ):
            errors.append(f"Pain prevents automatic progression of {prescription.exercise_name}.")

    if weekday == "Thursday":
        if proposal.workout.intensity not in {"rest", "very_light", "light"}:
            errors.append("Thursday cannot contain moderate or hard training.")
        if any(item.exercise_type.value != "recovery" for item in proposal.workout.exercises):
            errors.append("Thursday may only contain recovery movement.")

    proposed_meals = [proposal.nutrition.meal_1]
    if proposal.nutrition.meal_2:
        proposed_meals.append(proposal.nutrition.meal_2)
    proposed_names = [meal.template_name.casefold() for meal in proposed_meals]
    if enforce_meal_selection_policy and len(set(proposed_names)) != len(proposed_names):
        errors.append("Main meals must use distinct templates.")

    meal_templates = {template.name.casefold(): template for template in _active_meal_templates(db)}
    selected_templates: list[MealTemplate] = []
    for meal in proposed_meals:
        if not meal:
            continue
        template = meal_templates.get(meal.template_name.casefold())
        if template is None:
            errors.append(f"Unknown meal template: {meal.template_name}.")
            continue
        selected_templates.append(template)
        meal_terms = {item["name"].casefold() for item in template.ingredients_json} | {
            template.name.casefold(),
            template.description.casefold(),
            *(tag.casefold() for tag in template.tags),
        }
        for allergy in profile.allergies:
            if any(allergy.casefold() in term for term in meal_terms):
                errors.append(f"Meal {meal.template_name} conflicts with allergy {allergy}.")

    if enforce_meal_selection_policy:
        eligible = eligible_main_meal_templates(db, profile, plan_date)
        yesterday_names = {
            item["template_name"].casefold()
            for item in recommended_main_meal_history(db, plan_date, days=1)
        }
        non_repeating = [
            template for template in eligible if template.name.casefold() not in yesterday_names
        ]
        if len(non_repeating) >= len(proposed_meals):
            for template in selected_templates:
                if template.name.casefold() in yesterday_names:
                    errors.append(
                        f"Meal {template.name} repeats yesterday's recommendation despite available alternatives."
                    )
        available_specials = [template for template in eligible if is_special_meal(template)]
        if (
            available_specials
            and special_meal_required_today(db, profile, plan_date)
            and not any(is_special_meal(template) for template in selected_templates)
        ):
            errors.append(
                "A special higher-effort meal is required today to maintain weekly variety."
            )
    return errors


def validate_two_week_plan(
    db: Session,
    proposal: TwoWeekPlanProposal,
    profile: UserProfile,
    plan_date: date,
) -> list[str]:
    errors: list[str] = []
    if proposal.window_start != plan_date:
        errors.append("The receding horizon must start on the planning date.")

    previous_entries = list(
        db.scalars(
            select(WorkoutEntry).where(WorkoutEntry.entry_date == plan_date - timedelta(days=1))
        )
    )
    recovery_cautioned = any(
        entry.pain_flag
        or (entry.status in {"completed", "partial"} and (entry.difficulty_1_to_10 or 0) >= 8)
        for entry in previous_entries
    )
    gym_access_available = (
        db.scalar(
            select(Equipment.id).where(
                func.lower(Equipment.name) == "commercial gym access",
                Equipment.available.is_(True),
            )
        )
        is not None
    )

    for day in proposal.days:
        weekday = day.plan_date.strftime("%A")
        workout = day.workout
        if weekday == "Thursday" and (
            workout.kind not in {"rest", "recovery"}
            or workout.intensity
            not in {
                "rest",
                "very_light",
                "light",
            }
        ):
            errors.append(f"{day.plan_date}: Thursday cannot contain hard training.")
        if workout.requires_gym and (
            not gym_access_available
            or weekday not in {"Saturday", "Sunday"}
            or weekday not in profile.gym_days
        ):
            errors.append(f"{day.plan_date}: gym training is unavailable on {weekday}.")

        if day.nutrition.expected_main_meals > profile.max_main_meals_per_day:
            errors.append(f"{day.plan_date}: nutrition exceeds the main-meal limit.")
        eligible_meals = {
            template.name.casefold(): template
            for template in eligible_main_meal_templates(db, profile, day.plan_date)
        }
        selected_meals: list[MealTemplate] = []
        for name in day.nutrition.meal_template_names:
            template = eligible_meals.get(name.casefold())
            if template is None:
                errors.append(f"{day.plan_date}: unknown or ineligible meal template {name}.")
            else:
                selected_meals.append(template)
        if day.plan_date == plan_date:
            yesterday_names = {
                item["template_name"].casefold()
                for item in recommended_main_meal_history(db, plan_date, days=1)
            }
            non_repeating = [
                template for key, template in eligible_meals.items() if key not in yesterday_names
            ]
            if len(non_repeating) >= len(selected_meals) and any(
                template.name.casefold() in yesterday_names for template in selected_meals
            ):
                errors.append(
                    f"{day.plan_date}: today's meals repeat yesterday despite available alternatives."
                )
            available_specials = [
                template for template in eligible_meals.values() if is_special_meal(template)
            ]
            if (
                available_specials
                and special_meal_required_today(db, profile, plan_date)
                and not any(is_special_meal(template) for template in selected_meals)
            ):
                errors.append(
                    f"{day.plan_date}: today's meals require one special higher-effort template."
                )

    if recovery_cautioned and proposal.days[0].workout.intensity not in {
        "rest",
        "very_light",
        "light",
    }:
        errors.append("Today's plan must reduce load after pain or a high-effort session.")
    return errors


def _active_meal_templates(db: Session) -> list[MealTemplate]:
    return list(db.scalars(select(MealTemplate).where(MealTemplate.active.is_(True))))


def exercise_equipment_available(db: Session, exercise: Exercise) -> bool:
    available = {
        item.name.casefold()
        for item in db.scalars(select(Equipment).where(Equipment.available.is_(True)))
    }
    if exercise.gym_only:
        return "commercial gym access" in available
    alternatives = {
        "dumbbells": ("dumbbells",),
        "dumbbell": ("dumbbells",),
        "bench": ("home gym bench",),
        "power tower": ("sportsroyals power tower",),
        "pull-up bar": ("sportsroyals power tower",),
        "dip bars": ("sportsroyals power tower",),
        "treadmill": ("decathlon run 500 treadmill",),
        "kickr bike": ("wahoo kickr bike shift",),
    }
    for requirement in exercise.equipment_required:
        accepted = alternatives.get(requirement.casefold(), (requirement.casefold(),))
        if not any(any(token in item for token in accepted) for item in available):
            return False
    return True


def _workload_increased(previous: dict[str, Any], current: ExerciseProposal) -> bool:
    if current.exercise_type.value in {"strength", "bodyweight"}:
        old_load = float(previous.get("load_kg") or previous.get("external_load_kg") or 0)
        new_load = float(current.load_kg or current.external_load_kg or 0)
        old_reps = sum(previous.get("reps_per_set") or [])
        new_reps = sum(current.reps_per_set or [])
        return new_load > old_load or (new_load == old_load and new_reps > old_reps)
    if current.exercise_type.value == "run":
        old_distance = float(previous.get("distance_km") or 0)
        old_pace = int(previous.get("pace_seconds_per_km") or 9999)
        return bool(
            (current.distance_km or 0) > old_distance
            or (current.pace_seconds_per_km or 9999) < old_pace
        )
    if current.exercise_type.value == "bike":
        return (current.duration_seconds or 0) > int(previous.get("duration_seconds") or 0)
    return False
