from collections import Counter
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Exercise, MealTemplate, TwoWeekPlan, UserProfile, WorkoutEntry
from app.schemas.plan import ExerciseProposal, ExerciseType, WorkoutPlanProposal
from app.schemas.two_week_plan import (
    TwoWeekNutritionGuidance,
    TwoWeekPlanDay,
    TwoWeekPlanDocument,
    TwoWeekPlanProposal,
)
from app.services.planner.fallback import build_fallback_plan
from app.services.planner.meal_selection import (
    eligible_main_meal_templates,
    is_special_meal,
    recommended_main_meal_history,
    special_meal_required_today,
)

SKIPPED_STATUSES = {"skipped", "skipped_assumed"}


def build_fallback_two_week_plan(
    db: Session,
    profile: UserProfile,
    window_start: date,
    previous: TwoWeekPlan | None,
    *,
    preserve_previous: bool = True,
    variation_seed: int = 0,
) -> TwoWeekPlanProposal:
    previous_document = (
        TwoWeekPlanDocument.model_validate(previous.plan_json) if previous is not None else None
    )
    previous_days = (
        {day.plan_date: day for day in previous_document.days} if previous_document else {}
    )
    recent_meals = recommended_main_meal_history(db, window_start)
    meal_counts = Counter(item["template_name"].casefold() for item in recent_meals)
    last_selected = {
        item["template_name"].casefold()
        for item in recent_meals
        if item["date"] == (window_start - timedelta(days=1)).isoformat()
    }
    evidence = _adaptation_evidence(db, window_start)
    missed_workout = _missed_workout(previous_document, evidence)
    days: list[TwoWeekPlanDay] = []

    for offset in range(14):
        plan_date = window_start + timedelta(days=offset)
        prior_day = previous_days.get(plan_date) if preserve_previous or offset == 0 else None
        fallback = build_fallback_plan(db, plan_date)
        workout = prior_day.workout if prior_day else fallback.workout
        workout_adapted = False
        rationale = (
            "Preserved from yesterday's rolling horizon because no new evidence requires a change."
            if prior_day
            else "Added at the edge of the rolling horizon using the established weekly pattern."
        )

        if preserve_previous and offset == 0 and evidence["recovery_cautioned"]:
            workout = _recovery_workout()
            workout_adapted = True
            rationale = "Reduced to recovery after recorded pain or difficulty of 8 or higher."
        elif (
            preserve_previous
            and offset == 0
            and missed_workout is not None
            and _workout_allowed_on_date(db, profile, missed_workout, plan_date)
        ):
            workout = missed_workout
            workout_adapted = True
            rationale = "Moved the missed session forward by one day while preserving its targets."

        if prior_day and not workout_adapted:
            nutrition = prior_day.nutrition
            for name in nutrition.meal_template_names:
                meal_counts[name.casefold()] += 1
            last_selected = {name.casefold() for name in nutrition.meal_template_names}
        else:
            nutrition = _nutrition_guidance(
                db,
                profile,
                plan_date,
                workout,
                meal_counts,
                last_selected,
                variation_seed,
            )
            last_selected = {name.casefold() for name in nutrition.meal_template_names}

        days.append(
            TwoWeekPlanDay(
                plan_date=plan_date,
                commitment="committed" if offset < 7 else "provisional",
                adaptation="adaptive" if offset < 2 else "stable",
                workout=workout,
                nutrition=nutrition,
                rationale=rationale,
            )
        )

    return TwoWeekPlanProposal(
        window_start=window_start,
        window_end=window_start + timedelta(days=13),
        summary=(
            "A rolling hybrid-training and meal horizon with seven visible committed days and "
            "a provisional second week."
        ),
        training_strategy=(
            "Balance home strength, aerobic running and cycling, weekend gym access, and Thursday "
            "recovery while adapting the next session to recorded outcomes."
        ),
        nutrition_strategy=(
            "Rotate one or two exact main-meal templates daily and add simple fueling around the "
            "most demanding sessions."
        ),
        adjustment_summary=(
            "A fresh weekly revision was requested, so safe alternatives were reconsidered."
            if not preserve_previous
            else _adjustment_summary(evidence, previous is not None)
        ),
        days=days,
        assumptions=[
            "Unrecorded sleep, soreness, appetite, and schedule changes are not inferred.",
            "Missing ingredients can be purchased.",
        ],
    )


def _adaptation_evidence(db: Session, window_start: date) -> dict[str, bool]:
    entries = list(
        db.scalars(
            select(WorkoutEntry).where(
                WorkoutEntry.entry_date == window_start - timedelta(days=1),
                WorkoutEntry.planned_recommendation_id.is_not(None),
            )
        )
    )
    return {
        "recovery_cautioned": any(
            entry.pain_flag
            or (entry.status in {"completed", "partial"} and (entry.difficulty_1_to_10 or 0) >= 8)
            for entry in entries
        ),
        "missed": bool(entries) and all(entry.status in SKIPPED_STATUSES for entry in entries),
    }


def _missed_workout(
    previous: TwoWeekPlanDocument | None, evidence: dict[str, bool]
) -> WorkoutPlanProposal | None:
    if previous is None or not evidence["missed"] or not previous.days:
        return None
    missed = previous.days[0].workout
    return None if missed.kind == "rest" else missed


def _workout_allowed_on_date(
    db: Session,
    profile: UserProfile,
    workout: WorkoutPlanProposal,
    plan_date: date,
) -> bool:
    weekday = plan_date.strftime("%A")
    if weekday == "Thursday" and workout.kind != "recovery":
        return False
    catalog = {
        item.name.casefold(): item
        for item in db.scalars(select(Exercise).where(Exercise.active.is_(True)))
    }
    for prescription in workout.exercises:
        item = catalog.get(prescription.exercise_name.casefold())
        if item is None:
            return False
        if item.gym_only and (
            weekday not in {"Saturday", "Sunday"} or weekday not in profile.gym_days
        ):
            return False
    return True


def _recovery_workout() -> WorkoutPlanProposal:
    return WorkoutPlanProposal(
        kind="recovery",
        intensity="very_light",
        title="Restore before the next effort",
        exercises=[
            ExerciseProposal(
                exercise_name="Walking / easy movement",
                exercise_type=ExerciseType.RECOVERY,
                duration_seconds=1500,
                expected_difficulty=2,
                instructions="Keep the movement easy and stop if symptoms become concerning.",
            )
        ],
        expected_duration_minutes=25,
        summary="A short recovery session protects the next useful training day.",
    )


def _nutrition_guidance(
    db: Session,
    profile: UserProfile,
    plan_date: date,
    workout: WorkoutPlanProposal,
    meal_counts: Counter[str],
    last_selected: set[str],
    variation_seed: int,
) -> TwoWeekNutritionGuidance:
    candidates = eligible_main_meal_templates(db, profile, plan_date)
    if not candidates:
        raise RuntimeError(f"No eligible meal templates are available for {plan_date}")
    meal_count = min(profile.preferred_main_meals_per_day, profile.max_main_meals_per_day)
    if plan_date.strftime("%A") in profile.office_days:
        meal_count = 1

    special_day = plan_date.strftime("%A") == "Sunday" or special_meal_required_today(
        db, profile, plan_date
    )

    ordered_names = sorted(template.name for template in candidates)
    rotated_position = {
        name: (index - variation_seed) % len(ordered_names)
        for index, name in enumerate(ordered_names)
    }

    def rank(template: MealTemplate) -> tuple[int, int, int, int, str]:
        key = template.name.casefold()
        return (
            1 if key in last_selected else 0,
            meal_counts[key],
            template.effort_score,
            rotated_position[template.name],
            template.name,
        )

    flexible = [
        template
        for template in candidates
        if "flexible" in {tag.casefold() for tag in template.tags}
    ]
    if plan_date.strftime("%A") in profile.office_days and flexible:
        selected = [min(flexible, key=rank)]
    elif special_day:
        specials = [template for template in candidates if is_special_meal(template)]
        ordinary = [template for template in candidates if not is_special_meal(template)]
        special = min(specials, key=rank) if specials else None
        if meal_count == 1:
            selected = [special] if special is not None else sorted(candidates, key=rank)[:1]
        else:
            easy = sorted(
                ordinary,
                key=lambda template: (
                    0 if template.effort_score <= 2 and template.hands_on_minutes <= 20 else 1,
                    rank(template),
                ),
            )
            selected = easy[:1] + ([special] if special is not None else [])
            if len(selected) < meal_count:
                selected.extend(
                    template
                    for template in sorted(candidates, key=rank)
                    if template not in selected
                )
                selected = selected[:meal_count]
    else:
        selected = sorted(candidates, key=rank)[:meal_count]
    for template in selected:
        meal_counts[template.name.casefold()] += 1
    demanding = workout.intensity in {"moderate", "hard"} and (
        workout.expected_duration_minutes >= 40 or workout.kind.startswith("interval")
    )
    fueling = (
        [
            "Include a carbohydrate-rich component in the meal before training.",
            "Use the next planned meal for protein and carbohydrate recovery after training.",
        ]
        if demanding
        else ["Normal planned meals are sufficient; use hunger and appetite as recorded signals."]
    )
    batch = next((template for template in selected if template.batch_size > 1), None)
    return TwoWeekNutritionGuidance(
        expected_main_meals=meal_count,
        meal_template_names=[template.name for template in selected],
        focus=(
            "Support the demanding session with accessible carbohydrate and protein."
            if demanding
            else "Keep nutrition simple, varied, and protein-forward."
        ),
        fueling_recommendations=fueling,
        prep_note=(
            f"Prepare {batch.batch_size} servings of {batch.name}." if batch is not None else None
        ),
    )


def _adjustment_summary(evidence: dict[str, bool], has_previous: bool) -> str:
    if evidence["recovery_cautioned"]:
        return "The near-term plan reduces load after recorded pain or unusually high effort."
    if evidence["missed"]:
        return "The near-term plan attempts to carry the missed session forward safely."
    if has_previous:
        return "No material recovery signal required a change, so overlapping committed days stay stable."
    return "This is the first rolling horizon; future revisions will preserve it unless evidence changes."
