from datetime import date
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    DailyPlan,
    MealTemplate,
    NutritionEntry,
    PlanModification,
    PlanningRun,
    ProfileSnapshot,
    UserProfile,
)
from app.schemas.plan import (
    DailyPlanDocument,
    DailyPlanProposal,
    MealProposal,
    MealRecommendation,
    NutritionPlanProposal,
    PrepAction,
    proposal_from_document,
)
from app.services.planner.context import build_planner_context
from app.services.planner.domain import validate_plan
from app.services.planner.fallback import build_fallback_plan
from app.services.planner.meal_recipes import simple_meal_recipe
from app.services.planner.openai_planner import (
    PLANNER_VERSION,
    OpenAIPlanner,
    PlannerProviderError,
)

REGENERATION_VERSION = f"{PLANNER_VERSION}-nutrition-regeneration-v1"
EMERGENCY_TEMPLATE_NAME = "Emergency protein plate"


class NutritionRegenerationError(RuntimeError):
    pass


def regenerate_nutrition(
    db: Session,
    settings: Settings,
    plan: DailyPlan,
    *,
    use_ai: bool = True,
) -> DailyPlan:
    profile = db.scalar(select(UserProfile))
    snapshot = db.get(ProfileSnapshot, plan.profile_snapshot_id)
    if profile is None or snapshot is None:
        raise NutritionRegenerationError("Profile or plan snapshot is missing")
    current = DailyPlanDocument.model_validate(plan.current_plan_json)
    current_meals = _main_meals(current)
    current_names = {meal.template_name for meal in current_meals}
    forbidden_names = current_names | {EMERGENCY_TEMPLATE_NAME}
    _require_unresolved_main_meals(db, plan, current)

    context = build_planner_context(db, profile, snapshot, plan.plan_date)
    context["nutrition_regeneration"] = {
        "requested": True,
        "required_main_meal_count": len(current_meals),
        "forbidden_main_meal_templates": sorted(forbidden_names),
        "instruction": (
            "Regenerate the scheduled main meals only. The emergency protein plate remains an "
            "optional fallback and must not be scheduled as Meal 1 or Meal 2."
        ),
    }
    candidate, source, validation = _generate_candidate(
        db,
        settings,
        profile,
        current,
        context,
        forbidden_names,
        use_ai=use_ai,
    )
    merged = _merge_candidate(current, candidate, source)
    final_errors = validate_plan(db, proposal_from_document(merged), profile, plan.plan_date)
    if final_errors:
        raise NutritionRegenerationError(
            "Regenerated nutrition failed validation: " + "; ".join(final_errors)
        )

    db.refresh(plan)
    if plan.current_plan_json != current.model_dump(mode="json"):
        raise NutritionRegenerationError(
            "Today's plan changed during regeneration. Please try again."
        )
    _require_unresolved_main_meals(db, plan, current)

    run = PlanningRun(
        plan_date=plan.plan_date,
        model=settings.openai_planner_model if source == "openai" else "deterministic-fallback",
        planner_version=REGENERATION_VERSION,
        status="succeeded" if source == "openai" else "fallback",
        context_snapshot_json=context,
        model_output_json=candidate.model_dump(mode="json"),
        validation_result_json=validation,
    )
    db.add(run)
    _update_main_meals(db, plan, current, merged, source)
    plan.current_plan_json = merged.model_dump(mode="json")
    db.commit()
    db.refresh(plan)
    return plan


def _generate_candidate(
    db: Session,
    settings: Settings,
    profile: UserProfile,
    current: DailyPlanDocument,
    context: dict[str, Any],
    forbidden_names: set[str],
    *,
    use_ai: bool,
) -> tuple[DailyPlanProposal, Literal["openai", "fallback"], dict[str, Any]]:
    validation: dict[str, Any] = {"attempts": []}
    if use_ai and settings.openai_key_value:
        planner = OpenAIPlanner(settings)
        correction: dict[str, Any] | None = None
        for attempt in (1, 2):
            try:
                candidate = planner.generate(
                    context,
                    correction=correction,
                    prompt_label=f"FOOD RECOMMENDATION REGENERATION · ATTEMPT {attempt}",
                )
                errors = _candidate_errors(db, candidate, current, profile, forbidden_names)
            except PlannerProviderError as exc:
                errors = [str(exc)]
                validation["attempts"].append(
                    {"attempt": attempt, "source": "openai", "stage": "provider", "errors": errors}
                )
                validation["openai_error"] = str(exc)
                break
            except Exception as exc:  # noqa: BLE001 - bounded provider fallback boundary.
                errors = [f"{type(exc).__name__}: {str(exc)[:1500]}"]
                candidate = None
            validation["attempts"].append(
                {"attempt": attempt, "source": "openai", "errors": errors}
            )
            if candidate is not None and not errors:
                return candidate, "openai", validation
            correction = {
                "instruction": context["nutrition_regeneration"]["instruction"],
                "required_main_meal_count": len(_main_meals(current)),
                "forbidden_main_meal_templates": sorted(forbidden_names),
                "errors": errors,
            }

    candidate = _deterministic_candidate(
        db,
        profile,
        current.plan_date,
        forbidden_names,
        len(_main_meals(current)),
    )
    errors = _candidate_errors(db, candidate, current, profile, forbidden_names)
    validation["fallback_errors"] = errors
    if errors:
        raise NutritionRegenerationError(
            "Deterministic meal regeneration failed: " + "; ".join(errors)
        )
    return candidate, "fallback", validation


def _candidate_errors(
    db: Session,
    candidate: DailyPlanProposal,
    current: DailyPlanDocument,
    profile: UserProfile,
    forbidden_names: set[str],
) -> list[str]:
    meals = [candidate.nutrition.meal_1]
    if candidate.nutrition.meal_2:
        meals.append(candidate.nutrition.meal_2)
    errors: list[str] = []
    if len(meals) != len(_main_meals(current)):
        errors.append("The regenerated plan must preserve the current main-meal count.")
    names = [meal.template_name for meal in meals]
    forbidden_folded = {name.casefold() for name in forbidden_names}
    if any(name.casefold() in forbidden_folded for name in names):
        errors.append(
            "Regenerated main meals must be different and cannot use the emergency plate."
        )
    if len({name.casefold() for name in names}) != len(names):
        errors.append("Regenerated main meals must be distinct.")
    try:
        merged = _merge_candidate(current, candidate, "openai")
    except ValueError as exc:
        errors.append(str(exc))
    else:
        errors.extend(validate_plan(db, proposal_from_document(merged), profile, current.plan_date))
    return errors


def _deterministic_candidate(
    db: Session,
    profile: UserProfile,
    plan_date: date,
    forbidden_names: set[str],
    meal_count: int,
) -> DailyPlanProposal:
    base = build_fallback_plan(db, plan_date)
    forbidden_folded = {name.casefold() for name in forbidden_names}
    templates = [
        template
        for template in db.scalars(select(MealTemplate).where(MealTemplate.active.is_(True)))
        if template.name.casefold() not in forbidden_folded
        and not {"emergency", "snack"}.intersection(tag.casefold() for tag in template.tags)
        and (
            "flexible" not in {tag.casefold() for tag in template.tags}
            or plan_date.strftime("%A") in profile.office_days
        )
        and not _conflicts_with_allergies(template, profile.allergies)
    ]
    templates.sort(
        key=lambda template: (
            template.effort_score,
            template.hands_on_minutes,
            -template.preference_score,
            -template.estimated_protein_g,
            template.name,
        )
    )
    if len(templates) < meal_count:
        raise NutritionRegenerationError("Not enough eligible meal templates are available")
    selected = templates[:meal_count]
    meals = [
        _proposal_from_template(
            template,
            "evening" if index == 1 else "late morning to early afternoon",
        )
        for index, template in enumerate(selected)
    ]
    base.nutrition = NutritionPlanProposal(
        meal_1=meals[0],
        meal_2=meals[1] if len(meals) == 2 else None,
        fruits=base.nutrition.fruits,
        snacks=base.nutrition.snacks,
        expected_main_meals=meal_count,
        approximate_protein_g=min(350, sum(meal.estimated_protein_g for meal in meals) + 30),
        guidance="Fresh main meals were generated from the curated catalog. The emergency plate remains optional.",
    )
    batch_template = next((template for template in selected if template.batch_size > 1), None)
    base.prep_actions = (
        [
            PrepAction(
                action=f"Batch prepare {batch_template.batch_size} servings of {batch_template.name}",
                active_minutes=batch_template.hands_on_minutes,
                when="Today",
            )
        ]
        if batch_template
        else []
    )
    base.rationale.nutrition_factors = [
        f"Regenerated main meals: {', '.join(template.name for template in selected)}",
        "The emergency plate remains an optional fallback rather than a scheduled meal.",
    ]
    return base


def _proposal_from_template(template: MealTemplate, suggested_window: str) -> MealProposal:
    return MealProposal(
        template_name=template.name,
        description=template.description,
        suggested_window=suggested_window,
        expected=True,
        estimated_protein_g=template.estimated_protein_g,
        estimated_fiber_g=template.estimated_fiber_g,
        hands_on_minutes=template.hands_on_minutes,
        ingredients=[f"{item['quantity']} {item['name']}" for item in template.ingredients_json],
        preparation=simple_meal_recipe(template),
    )


def _merge_candidate(
    current: DailyPlanDocument,
    candidate: DailyPlanProposal,
    source: Literal["openai", "fallback"],
) -> DailyPlanDocument:
    current_meals = _main_meals(current)
    candidate_meals = [candidate.nutrition.meal_1]
    if candidate.nutrition.meal_2:
        candidate_meals.append(candidate.nutrition.meal_2)
    if len(current_meals) != len(candidate_meals):
        raise ValueError("Regeneration cannot change the number of main meals")
    payload = current.model_dump(mode="json")
    payload["source"] = source
    for index, (old_meal, new_meal) in enumerate(zip(current_meals, candidate_meals, strict=True)):
        key = f"meal_{index + 1}"
        payload["nutrition"][key] = {
            **new_meal.model_dump(mode="json"),
            "recommendation_id": old_meal.recommendation_id,
        }
    payload["nutrition"]["expected_main_meals"] = len(candidate_meals)
    payload["nutrition"]["approximate_protein_g"] = candidate.nutrition.approximate_protein_g
    payload["nutrition"]["guidance"] = candidate.nutrition.guidance
    payload["prep_actions"] = [item.model_dump(mode="json") for item in candidate.prep_actions]
    payload["shopping"] = candidate.shopping.model_dump(mode="json")
    payload["rationale"]["nutrition_factors"] = candidate.rationale.nutrition_factors
    assumptions = list(payload["assumptions"])
    note = "Scheduled main meals were regenerated at the user's request."
    if note not in assumptions:
        assumptions = [*assumptions[:7], note]
    payload["assumptions"] = assumptions
    return DailyPlanDocument.model_validate(payload)


def _update_main_meals(
    db: Session,
    plan: DailyPlan,
    current: DailyPlanDocument,
    merged: DailyPlanDocument,
    source: Literal["openai", "fallback"],
) -> None:
    entries = {
        entry.planned_recommendation_id: entry
        for entry in db.scalars(
            select(NutritionEntry).where(
                NutritionEntry.entry_date == plan.plan_date,
                NutritionEntry.meal_slot.in_(["meal_1", "meal_2"]),
            )
        )
    }
    for old_meal, new_meal in zip(_main_meals(current), _main_meals(merged), strict=True):
        entry = entries.get(old_meal.recommendation_id)
        if entry is None:
            raise NutritionRegenerationError("A materialized main-meal entry is missing")
        db.add(
            PlanModification(
                daily_plan_id=plan.id,
                recommendation_id=old_meal.recommendation_id,
                original_json=old_meal.model_dump(mode="json"),
                replacement_json=new_meal.model_dump(mode="json"),
                reason="User regenerated today's scheduled main meals",
                source=f"regenerated_{source}",
            )
        )
        entry.food_or_meal_reference = new_meal.template_name
        entry.description = new_meal.description
        entry.quantity_json = {
            "ingredients": new_meal.ingredients,
            "estimated_protein_g": new_meal.estimated_protein_g,
            "estimated_fiber_g": new_meal.estimated_fiber_g,
            "hands_on_minutes": new_meal.hands_on_minutes,
        }
        entry.source = f"regenerated_{source}"
        entry.expected = new_meal.expected


def _require_unresolved_main_meals(
    db: Session, plan: DailyPlan, document: DailyPlanDocument
) -> None:
    recommendation_ids = {meal.recommendation_id for meal in _main_meals(document)}
    entries = list(
        db.scalars(
            select(NutritionEntry).where(
                NutritionEntry.entry_date == plan.plan_date,
                NutritionEntry.planned_recommendation_id.in_(recommendation_ids),
            )
        )
    )
    if len(entries) != len(recommendation_ids):
        raise NutritionRegenerationError("A materialized main-meal entry is missing")
    if any(entry.status != "planned" for entry in entries):
        raise NutritionRegenerationError(
            "Meals can only be regenerated before they are confirmed, skipped, or recorded."
        )


def _main_meals(document: DailyPlanDocument) -> list[MealRecommendation]:
    meals = [document.nutrition.meal_1]
    if document.nutrition.meal_2:
        meals.append(document.nutrition.meal_2)
    return meals


def _conflicts_with_allergies(template: MealTemplate, allergies: list[str]) -> bool:
    terms = [
        template.name,
        template.description,
        *template.tags,
        *(item["name"] for item in template.ingredients_json),
    ]
    return any(allergy.casefold() in term.casefold() for allergy in allergies for term in terms)
