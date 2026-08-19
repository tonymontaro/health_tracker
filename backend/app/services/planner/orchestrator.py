from datetime import date
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    DailyPlan,
    Exercise,
    NutritionEntry,
    PlanningRun,
    UserProfile,
    WorkoutEntry,
)
from app.schemas.plan import DailyPlanDocument, canonicalize_proposal
from app.schemas.two_week_plan import parse_two_week_plan_document
from app.services.planner.context import (
    build_daily_planner_context,
    build_profile_snapshot,
    snapshot_summary,
)
from app.services.planner.domain import validate_plan
from app.services.planner.fallback import build_fallback_plan
from app.services.planner.openai_planner import (
    PLANNER_VERSION,
    OpenAIPlanner,
    PlannerProviderError,
)
from app.services.planner.two_week import (
    ensure_two_week_plan,
    horizon_uses_active_training_plan_guide,
    latest_two_week_plan,
)
from app.services.recording_dates import current_recording_date


def generate_daily_plan(
    db: Session,
    settings: Settings,
    plan_date: date,
    *,
    use_ai: bool = True,
) -> DailyPlan:
    existing = db.scalar(select(DailyPlan).where(DailyPlan.plan_date == plan_date))
    horizon = latest_two_week_plan(db, plan_date)
    if existing and plan_date != current_recording_date(settings):
        return existing
    profile = db.scalar(select(UserProfile))
    if profile is None:
        raise RuntimeError("Profile has not been seeded")
    if existing and horizon and horizon_uses_active_training_plan_guide(db, horizon, profile):
        return existing

    snapshot = build_profile_snapshot(db, profile, plan_date)
    horizon = ensure_two_week_plan(
        db,
        settings,
        plan_date,
        use_ai=use_ai,
        profile=profile,
        snapshot=snapshot,
    )
    if existing:
        return existing
    context = build_daily_planner_context(db, profile, snapshot, plan_date)
    run = PlanningRun(
        plan_date=plan_date,
        model=settings.openai_planner_model if use_ai else "deterministic-fallback",
        planner_version=PLANNER_VERSION,
        status="running",
        context_snapshot_json=context,
        model_output_json={},
        validation_result_json={},
    )
    db.add(run)
    db.flush()

    proposal = None
    source: Literal["openai", "fallback"] = "fallback"
    validation: dict[str, Any] = {"attempts": []}
    if use_ai and settings.openai_key_value:
        planner = OpenAIPlanner(settings)
        correction: dict[str, Any] | None = None
        last_error: str | None = None
        for attempt in (1, 2):
            try:
                candidate = planner.generate(context, correction=correction)
            except PlannerProviderError as exc:
                last_error = str(exc)
                validation["attempts"].append(
                    {"attempt": attempt, "errors": [last_error], "stage": "provider"}
                )
                break
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {str(exc)[:1500]}"
                validation["attempts"].append(
                    {"attempt": attempt, "errors": [last_error], "stage": "schema_or_provider"}
                )
                correction = {
                    "errors": [last_error],
                    "instruction": "Return a fresh response that satisfies every schema constraint.",
                }
                continue
            errors = validate_plan(db, candidate, profile, plan_date)
            validation["attempts"].append({"attempt": attempt, "errors": errors, "stage": "domain"})
            if not errors:
                proposal = candidate
                source = "openai"
                break
            last_error = "; ".join(errors)
            correction = {
                "errors": errors,
                "invalid_candidate": candidate.model_dump(mode="json"),
            }
        if proposal is None and last_error:
            validation["openai_error"] = last_error

    if proposal is None:
        horizon_document = parse_two_week_plan_document(horizon.plan_json)
        current_horizon_day = next(
            (
                day.model_dump(mode="json")
                for day in horizon_document.days
                if day.plan_date == plan_date
            ),
            None,
        )
        proposal = build_fallback_plan(db, plan_date, horizon_day=current_horizon_day)
        fallback_errors = validate_plan(db, proposal, profile, plan_date)
        validation["fallback_errors"] = fallback_errors
        if fallback_errors:
            raise RuntimeError(f"Deterministic fallback is invalid: {fallback_errors}")

    document = canonicalize_proposal(
        proposal,
        plan_date=plan_date,
        snapshot=snapshot_summary(snapshot),
        source=source,
    )
    payload = document.model_dump(mode="json")
    run.status = "succeeded" if source == "openai" else "fallback"
    run.model_output_json = proposal.model_dump(mode="json")
    run.validation_result_json = validation
    plan = DailyPlan(
        plan_date=plan_date,
        profile_snapshot_id=snapshot.id,
        planning_run_id=run.id,
        status="active",
        short_summary=document.short_summary,
        original_plan_json=payload,
        current_plan_json=payload,
    )
    db.add(plan)
    db.flush()
    _materialize_entries(db, document)
    db.commit()
    db.refresh(plan)
    return plan


def _materialize_entries(db: Session, document: DailyPlanDocument) -> None:
    meals = [("meal_1", document.nutrition.meal_1)]
    if document.nutrition.meal_2:
        meals.append(("meal_2", document.nutrition.meal_2))
    for slot, meal in meals:
        db.add(
            NutritionEntry(
                entry_date=document.plan_date,
                meal_slot=slot,
                planned_recommendation_id=meal.recommendation_id,
                food_or_meal_reference=meal.template_name,
                description=meal.description,
                quantity_json={
                    "ingredients": meal.ingredients,
                    "estimated_protein_g": meal.estimated_protein_g,
                    "estimated_fiber_g": meal.estimated_fiber_g,
                    "hands_on_minutes": meal.hands_on_minutes,
                },
                source="recommended",
                status="planned",
                expected=meal.expected,
            )
        )
    for fruit in document.nutrition.fruits:
        db.add(
            NutritionEntry(
                entry_date=document.plan_date,
                meal_slot="fruit",
                planned_recommendation_id=fruit.recommendation_id,
                food_or_meal_reference=fruit.name,
                description=f"{fruit.name}: {fruit.quantity}",
                quantity_json={"quantity": fruit.quantity},
                source="recommended",
                status="planned",
                expected=fruit.expected,
            )
        )
    for snack in document.nutrition.snacks:
        db.add(
            NutritionEntry(
                entry_date=document.plan_date,
                meal_slot="snack",
                planned_recommendation_id=snack.recommendation_id,
                food_or_meal_reference=snack.name,
                description=snack.description,
                quantity_json={"estimated_protein_g": snack.estimated_protein_g},
                source="recommended",
                status="planned",
                expected=snack.expected,
            )
        )
    catalog = {
        exercise.name: exercise
        for exercise in db.scalars(select(Exercise).where(Exercise.active.is_(True)))
    }
    for exercise in document.workout.exercises:
        catalog_item = catalog[exercise.exercise_name]
        db.add(
            WorkoutEntry(
                entry_date=document.plan_date,
                planned_recommendation_id=exercise.recommendation_id,
                exercise_id=catalog_item.id,
                exercise_name=exercise.exercise_name,
                prescription_json=exercise.model_dump(mode="json"),
                status="planned",
                source="recommended",
            )
        )
