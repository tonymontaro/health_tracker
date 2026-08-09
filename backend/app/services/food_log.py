import json
from datetime import date
from typing import Any, Protocol

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    DailyFoodLog,
    DailyPlan,
    FoodItem,
    NutritionEntry,
    UserProfile,
)
from app.schemas.food_log import FoodLogExtraction, FoodLogResponse
from app.services.inventory import adjust_nutrition_entry_inventory
from app.services.metrics import recalculate_derived_summary

FOOD_LOG_SYSTEM_PROMPT = """Interpret one free-text food diary for a single calendar day.
Extract only food and drink that the user says they consumed. Never invent an unmentioned item.
Group the items into the smallest set of meals that the text supports and give each meal a clear name.
Use meal_1 and meal_2 for main meals, snack for smaller food, and fruit for fruit eaten separately.
Preserve explicit quantities. When a quantity is absent, estimate an average adult portion and mark it assumed.
Break each meal into useful food components with gram, milliliter, or item quantities.
Use catalog_food_name only when the component truly matches one supplied catalog item, and copy its name exactly.
Determine whether each consumed meal followed a supplied recommendation based only on semantic evidence.
Each recommendation may be matched at most once. A partial ingredient overlap is not enough by itself.
Calories, protein, and fiber are approximate estimates, never laboratory measurements.
Set ate_nothing only when the user explicitly says that they consumed no food.
Record important ambiguity and portion estimation in the assumptions fields.
Do not diagnose, give advice, or output hidden reasoning.
"""


class FoodLogExtractionError(RuntimeError):
    pass


class FoodLogExtractionProvider(Protocol):
    model: str

    def extract(
        self,
        raw_text: str,
        recommendations: list[dict[str, Any]],
        catalog_foods: list[dict[str, Any]],
    ) -> FoodLogExtraction: ...


class FoodLogExtractor:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_key_value:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        self.model = settings.openai_food_log_model
        self.client = OpenAI(
            api_key=settings.openai_key_value,
            timeout=120,
            max_retries=0,
        )

    def extract(
        self,
        raw_text: str,
        recommendations: list[dict[str, Any]],
        catalog_foods: list[dict[str, Any]],
    ) -> FoodLogExtraction:
        known_ids = {
            recommendation["recommendation_id"]
            for recommendation in recommendations
            if recommendation.get("recommendation_id")
        }
        canonical_foods = {food["name"].casefold(): food["name"] for food in catalog_foods}
        correction: dict[str, Any] | None = None
        last_errors: list[str] = []
        for _ in range(2):
            payload: dict[str, Any] = {
                "food_log_text": raw_text,
                "today_recommendations": recommendations,
                "food_catalog": catalog_foods,
            }
            if correction:
                payload["correction"] = correction
            try:
                response = self.client.responses.parse(
                    model=self.model,
                    reasoning={"effort": "low"},
                    input=[
                        {"role": "system", "content": FOOD_LOG_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(payload, separators=(",", ":")),
                        },
                    ],
                    text_format=FoodLogExtraction,
                    store=False,
                )
                extraction = response.output_parsed
                if extraction is None:
                    last_errors = ["The model returned no parsed result."]
                else:
                    extraction = _canonicalize_catalog_names(extraction, canonical_foods)
                    last_errors = validate_extraction(
                        extraction, known_ids, set(canonical_foods.values())
                    )
                    if not last_errors:
                        return extraction
            except Exception as exc:  # noqa: BLE001 - provider errors use one bounded repair attempt.
                last_errors = [f"{type(exc).__name__}: {str(exc)[:1000]}"]
            correction = {
                "errors": last_errors,
                "instruction": "Return a fresh result that fixes every error without adding unmentioned food.",
            }
        raise FoodLogExtractionError(
            "AI could not reliably interpret the food log. Nothing was changed."
        )


def validate_extraction(
    extraction: FoodLogExtraction,
    known_recommendation_ids: set[str],
    known_catalog_names: set[str],
) -> list[str]:
    errors: list[str] = []
    if extraction.ate_nothing and extraction.meals:
        errors.append("ate_nothing cannot be true when meals are present")
    if not extraction.ate_nothing and not extraction.meals:
        errors.append("at least one meal is required unless the user explicitly ate nothing")
    matched_ids: list[str] = []
    for meal in extraction.meals:
        if meal.matched_recommendation_id:
            matched_ids.append(meal.matched_recommendation_id)
            if meal.matched_recommendation_id not in known_recommendation_ids:
                errors.append(f"unknown recommendation ID: {meal.matched_recommendation_id}")
        for component in meal.components:
            if (
                component.catalog_food_name
                and component.catalog_food_name not in known_catalog_names
            ):
                errors.append(f"unknown catalog food: {component.catalog_food_name}")
    if len(matched_ids) != len(set(matched_ids)):
        errors.append("a recommendation can be matched at most once")
    return errors


def process_daily_food_log(
    db: Session,
    settings: Settings,
    target_date: date,
    raw_text: str,
    *,
    extractor: FoodLogExtractionProvider | None = None,
) -> FoodLogResponse:
    plan = db.scalar(select(DailyPlan).where(DailyPlan.plan_date == target_date))
    if plan is None:
        raise LookupError("Today's plan is not available")
    planned_entries = list(
        db.scalars(
            select(NutritionEntry).where(
                NutritionEntry.entry_date == target_date,
                NutritionEntry.planned_recommendation_id.is_not(None),
            )
        )
    )
    recommendations = [_recommendation_context(entry) for entry in planned_entries]
    catalog_foods = [
        _food_context(food)
        for food in db.scalars(
            select(FoodItem).where(FoodItem.active.is_(True)).order_by(FoodItem.name)
        )
    ]
    active_extractor = extractor or FoodLogExtractor(settings)

    # The external call intentionally happens before the first mutation.
    extraction = active_extractor.extract(raw_text, recommendations, catalog_foods)
    validation_errors = validate_extraction(
        extraction,
        {item["recommendation_id"] for item in recommendations},
        {item["name"] for item in catalog_foods},
    )
    if validation_errors:
        raise FoodLogExtractionError("; ".join(validation_errors))

    try:
        db.scalar(select(DailyPlan).where(DailyPlan.plan_date == target_date).with_for_update())
        food_log = db.scalar(select(DailyFoodLog).where(DailyFoodLog.log_date == target_date))
        if food_log is None:
            food_log = DailyFoodLog(
                log_date=target_date,
                raw_text=raw_text,
                extraction_json={},
                model=active_extractor.model,
                status="processing",
            )
            db.add(food_log)
            db.flush()
        else:
            generated_entries = list(
                db.scalars(select(NutritionEntry).where(NutritionEntry.food_log_id == food_log.id))
            )
            for entry in generated_entries:
                if entry.status in {"confirmed", "assumed_consumed"}:
                    adjust_nutrition_entry_inventory(db, entry, direction=1)
                db.delete(entry)

        matched_ids = {
            meal.matched_recommendation_id
            for meal in extraction.meals
            if meal.matched_recommendation_id
        }
        for entry in planned_entries:
            if entry.status in {"confirmed", "assumed_consumed"}:
                adjust_nutrition_entry_inventory(db, entry, direction=1)
            entry.status = (
                "matched_by_food_log"
                if entry.planned_recommendation_id in matched_ids
                else "discarded_by_food_log"
            )

        food_log.raw_text = raw_text
        food_log.extraction_json = extraction.model_dump(mode="json")
        food_log.model = active_extractor.model
        food_log.status = "processed"
        for meal in extraction.meals:
            quantity = {
                "portion_count": meal.portion_count,
                "quantity_label": meal.quantity_label,
                "components": [component.model_dump(mode="json") for component in meal.components],
                "estimated_calories_kcal": meal.estimated_calories_kcal,
                "estimated_protein_g": meal.estimated_protein_g,
                "estimated_fiber_g": meal.estimated_fiber_g,
                "matched_recommendation_id": meal.matched_recommendation_id,
                "match_confidence": meal.match_confidence,
                "assumptions": meal.assumptions,
            }
            entry = NutritionEntry(
                entry_date=target_date,
                meal_slot=meal.meal_slot,
                food_or_meal_reference=meal.meal_name,
                description=meal.description,
                quantity_json=quantity,
                source="ai_food_log",
                status="confirmed",
                expected=False,
                food_log_id=food_log.id,
            )
            db.add(entry)
            adjust_nutrition_entry_inventory(db, entry, direction=-1)

        profile = db.scalar(select(UserProfile))
        if profile:
            recalculate_derived_summary(db, profile, target_date)
        db.commit()
    except Exception:
        db.rollback()
        raise

    all_planned_ids = {
        entry.planned_recommendation_id
        for entry in planned_entries
        if entry.planned_recommendation_id
    }
    return FoodLogResponse(
        date=target_date.isoformat(),
        raw_text=raw_text,
        extraction=extraction,
        discarded_recommendation_ids=sorted(all_planned_ids - matched_ids),
        matched_recommendation_ids=sorted(matched_ids),
    )


def serialize_food_log(food_log: DailyFoodLog | None) -> dict[str, Any] | None:
    if food_log is None:
        return None
    return {
        "id": str(food_log.id),
        "date": food_log.log_date.isoformat(),
        "raw_text": food_log.raw_text,
        "extraction": food_log.extraction_json,
        "model": food_log.model,
        "status": food_log.status,
        "updated_at": food_log.updated_at.isoformat(),
    }


def _canonicalize_catalog_names(
    extraction: FoodLogExtraction, canonical_foods: dict[str, str]
) -> FoodLogExtraction:
    payload = extraction.model_dump(mode="json")
    for meal in payload["meals"]:
        for component in meal["components"]:
            catalog_name = component.get("catalog_food_name")
            if isinstance(catalog_name, str):
                component["catalog_food_name"] = canonical_foods.get(
                    catalog_name.casefold(), catalog_name
                )
    return FoodLogExtraction.model_validate(payload)


def _recommendation_context(entry: NutritionEntry) -> dict[str, Any]:
    return {
        "recommendation_id": entry.planned_recommendation_id,
        "meal_slot": entry.meal_slot,
        "name": entry.food_or_meal_reference,
        "description": entry.description,
        "quantity": entry.quantity_json,
    }


def _food_context(food: FoodItem) -> dict[str, Any]:
    return {
        "name": food.name,
        "category": food.category,
        "typical_unit": food.typical_unit,
        "protein_g_per_100": food.protein_g_per_100,
        "carbs_g_per_100": food.carbs_g_per_100,
        "fat_g_per_100": food.fat_g_per_100,
        "fiber_g_per_100": food.fiber_g_per_100,
        "calories_per_100": food.calories_per_100,
    }
