from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    DailyPlan,
    DailyWorkoutLog,
    Exercise,
    PlanModification,
    PlanningRun,
    ProfileSnapshot,
    UserProfile,
    WorkoutEntry,
)
from app.schemas.plan import (
    DailyPlanDocument,
    DailyPlanProposal,
    canonicalize_proposal,
    proposal_from_document,
)
from app.services.planner.context import (
    build_planner_context,
    build_profile_snapshot,
    snapshot_summary,
)
from app.services.planner.domain import validate_plan
from app.services.planner.fallback import build_fallback_plan
from app.services.planner.openai_planner import PLANNER_VERSION, OpenAIPlanner

REGENERATION_VERSION = f"{PLANNER_VERSION}-workout-regeneration-v1"


class WorkoutRegenerationError(RuntimeError):
    pass


def regenerate_workout(
    db: Session,
    settings: Settings,
    plan: DailyPlan,
    *,
    use_ai: bool = True,
) -> DailyPlan:
    profile = db.scalar(select(UserProfile))
    if profile is None:
        raise WorkoutRegenerationError("Profile is missing")
    current = DailyPlanDocument.model_validate(plan.current_plan_json)
    _require_unresolved_workout(db, plan, current)

    refreshed_snapshot = build_profile_snapshot(db, profile, plan.plan_date)
    context = build_planner_context(db, profile, refreshed_snapshot, plan.plan_date)
    context["workout_regeneration"] = {
        "requested": True,
        "instruction": (
            "Regenerate today's workout only. Use the refreshed training history, especially "
            "completed activity from yesterday. Nutrition, shopping, and preparation content "
            "will be preserved by the application."
        ),
    }
    candidate, source, validation = _generate_candidate(
        db,
        settings,
        profile,
        current,
        refreshed_snapshot,
        context,
        use_ai=use_ai,
    )
    candidate_document = canonicalize_proposal(
        candidate,
        plan_date=plan.plan_date,
        snapshot=snapshot_summary(refreshed_snapshot),
        source=source,
    )
    merged = _merge_candidate(current, candidate_document)
    final_errors = validate_plan(db, proposal_from_document(merged), profile, plan.plan_date)
    if final_errors:
        raise WorkoutRegenerationError(
            "Regenerated workout failed validation: " + "; ".join(final_errors)
        )

    db.refresh(plan)
    if plan.current_plan_json != current.model_dump(mode="json"):
        raise WorkoutRegenerationError(
            "Today's plan changed during regeneration. Please try again."
        )
    _require_unresolved_workout(db, plan, current)

    db.add(
        PlanningRun(
            plan_date=plan.plan_date,
            model=(
                settings.openai_planner_model if source == "openai" else "deterministic-fallback"
            ),
            planner_version=REGENERATION_VERSION,
            status="succeeded" if source == "openai" else "fallback",
            context_snapshot_json=context,
            model_output_json=candidate.model_dump(mode="json"),
            validation_result_json=validation,
        )
    )
    _replace_materialized_workout(db, plan, current, merged, source)
    plan.current_plan_json = merged.model_dump(mode="json")
    plan.short_summary = merged.short_summary
    db.commit()
    db.refresh(plan)
    return plan


def _generate_candidate(
    db: Session,
    settings: Settings,
    profile: UserProfile,
    current: DailyPlanDocument,
    refreshed_snapshot: ProfileSnapshot,
    context: dict[str, Any],
    *,
    use_ai: bool,
) -> tuple[DailyPlanProposal, Literal["openai", "fallback"], dict[str, Any]]:
    validation: dict[str, Any] = {"attempts": []}
    if use_ai and settings.openai_key_value:
        planner = OpenAIPlanner(settings)
        correction: dict[str, Any] = {"instruction": context["workout_regeneration"]["instruction"]}
        for attempt in (1, 2):
            try:
                candidate = planner.generate(context, correction=correction)
                errors = _candidate_errors(
                    db, candidate, current, profile, refreshed_snapshot, "openai"
                )
            except Exception as exc:  # noqa: BLE001 - bounded provider fallback boundary.
                errors = [f"{type(exc).__name__}: {str(exc)[:1500]}"]
                candidate = None
            validation["attempts"].append(
                {"attempt": attempt, "source": "openai", "errors": errors}
            )
            if candidate is not None and not errors:
                return candidate, "openai", validation
            correction = {
                "instruction": context["workout_regeneration"]["instruction"],
                "errors": errors,
            }

    candidate = build_fallback_plan(db, current.plan_date)
    errors = _candidate_errors(db, candidate, current, profile, refreshed_snapshot, "fallback")
    validation["fallback_errors"] = errors
    if errors:
        raise WorkoutRegenerationError(
            "Deterministic workout regeneration failed: " + "; ".join(errors)
        )
    return candidate, "fallback", validation


def _candidate_errors(
    db: Session,
    candidate: DailyPlanProposal,
    current: DailyPlanDocument,
    profile: UserProfile,
    refreshed_snapshot: ProfileSnapshot,
    source: Literal["openai", "fallback"],
) -> list[str]:
    try:
        document = canonicalize_proposal(
            candidate,
            plan_date=current.plan_date,
            snapshot=snapshot_summary(refreshed_snapshot),
            source=source,
        )
        merged = _merge_candidate(current, document)
    except ValueError as exc:
        return [str(exc)]
    return validate_plan(db, proposal_from_document(merged), profile, current.plan_date)


def _merge_candidate(current: DailyPlanDocument, candidate: DailyPlanDocument) -> DailyPlanDocument:
    payload = current.model_dump(mode="json")
    payload["source"] = candidate.source
    payload["profile_snapshot"] = candidate.profile_snapshot.model_dump(mode="json")
    payload["workout"] = candidate.workout.model_dump(mode="json")
    payload["short_summary"] = f"Workout regenerated: {candidate.workout.summary}"
    payload["rationale"]["summary"] = candidate.rationale.summary
    payload["rationale"]["objectives"] = candidate.rationale.objectives
    payload["rationale"]["history_factors"] = candidate.rationale.history_factors
    payload["rationale"]["recovery_factors"] = candidate.rationale.recovery_factors
    payload["rationale"]["scheduling_factors"] = candidate.rationale.scheduling_factors
    payload["rationale"]["progression_logic"] = candidate.rationale.progression_logic
    payload["rationale"]["alternatives_considered"] = [
        item.model_dump(mode="json") for item in candidate.rationale.alternatives_considered
    ]
    note = "Today's workout was regenerated from refreshed activity history."
    assumptions = list(payload["assumptions"])
    if note not in assumptions:
        assumptions = [*assumptions[:7], note]
    payload["assumptions"] = assumptions
    return DailyPlanDocument.model_validate(payload)


def _replace_materialized_workout(
    db: Session,
    plan: DailyPlan,
    current: DailyPlanDocument,
    merged: DailyPlanDocument,
    source: Literal["openai", "fallback"],
) -> None:
    old_ids = {exercise.recommendation_id for exercise in current.workout.exercises}
    old_entries = list(
        db.scalars(
            select(WorkoutEntry).where(
                WorkoutEntry.entry_date == plan.plan_date,
                WorkoutEntry.planned_recommendation_id.in_(old_ids),
            )
        )
    )
    new_exercises = merged.workout.exercises
    for index, old_exercise in enumerate(current.workout.exercises):
        replacement = (
            new_exercises[index].model_dump(mode="json")
            if index < len(new_exercises)
            else {"removed": True}
        )
        db.add(
            PlanModification(
                daily_plan_id=plan.id,
                recommendation_id=old_exercise.recommendation_id,
                original_json=old_exercise.model_dump(mode="json"),
                replacement_json=replacement,
                reason="User regenerated today's workout from refreshed activity history",
                source=f"regenerated_{source}",
            )
        )
    for entry in old_entries:
        db.delete(entry)

    catalog = {
        exercise.name: exercise
        for exercise in db.scalars(select(Exercise).where(Exercise.active.is_(True)))
    }
    for exercise in new_exercises:
        catalog_item = catalog.get(exercise.exercise_name)
        if catalog_item is None:
            raise WorkoutRegenerationError(
                f"Regenerated exercise is missing from the catalog: {exercise.exercise_name}"
            )
        db.add(
            WorkoutEntry(
                entry_date=plan.plan_date,
                planned_recommendation_id=exercise.recommendation_id,
                exercise_id=catalog_item.id,
                exercise_name=exercise.exercise_name,
                prescription_json=exercise.model_dump(mode="json"),
                status="planned",
                source=f"regenerated_{source}",
            )
        )


def _require_unresolved_workout(db: Session, plan: DailyPlan, document: DailyPlanDocument) -> None:
    if db.scalar(select(DailyWorkoutLog.id).where(DailyWorkoutLog.log_date == plan.plan_date)):
        raise WorkoutRegenerationError(
            "The workout can only be regenerated before exercise is recorded."
        )
    recommendation_ids = {exercise.recommendation_id for exercise in document.workout.exercises}
    entries = list(
        db.scalars(select(WorkoutEntry).where(WorkoutEntry.entry_date == plan.plan_date))
    )
    planned_entries = [
        entry for entry in entries if entry.planned_recommendation_id in recommendation_ids
    ]
    if len(planned_entries) != len(recommendation_ids):
        raise WorkoutRegenerationError("A materialized workout recommendation is missing")
    if any(entry.status != "planned" or entry.actual_json for entry in planned_entries):
        raise WorkoutRegenerationError(
            "The workout can only be regenerated before it is completed, skipped, or recorded."
        )
    if any(
        entry.planned_recommendation_id is None
        and (entry.actual_json is not None or entry.status == "completed")
        for entry in entries
    ):
        raise WorkoutRegenerationError(
            "The workout can only be regenerated before exercise is recorded."
        )
