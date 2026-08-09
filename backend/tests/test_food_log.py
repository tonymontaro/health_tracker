import asyncio
from copy import deepcopy
from datetime import date
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.today import local_today
from app.core.config import Settings, get_settings
from app.core.security import token_digest
from app.db.models import (
    ApiToken,
    DailyFoodLog,
    FoodItem,
    InventoryItem,
    NutritionEntry,
)
from app.db.session import get_db
from app.main import app
from app.schemas.food_log import FoodLogExtraction
from app.services.food_log import FoodLogExtractionError, process_daily_food_log
from app.services.history import correct_nutrition_entry
from app.services.metrics import calculate_nutrition_summary
from app.services.planner.orchestrator import generate_daily_plan

TARGET = date(2026, 8, 10)


def extraction(
    *, quantity: float = 200, matched_recommendation_id: str | None = None
) -> FoodLogExtraction:
    return FoodLogExtraction.model_validate(
        {
            "ate_nothing": False,
            "meals": [
                {
                    "meal_name": "Chicken and rice bowl",
                    "meal_slot": "meal_1",
                    "description": "Chicken breast with rice and vegetables.",
                    "portion_count": 1,
                    "quantity_label": "1 average bowl",
                    "components": [
                        {
                            "name": "chicken breast",
                            "quantity_value": quantity,
                            "unit": "g",
                            "quantity_label": f"{quantity:g} g",
                            "catalog_food_name": "Chicken breast",
                            "quantity_is_assumed": True,
                        }
                    ],
                    "estimated_calories_kcal": 620,
                    "estimated_protein_g": 58,
                    "estimated_fiber_g": 8,
                    "matched_recommendation_id": matched_recommendation_id,
                    "match_confidence": 0.92 if matched_recommendation_id else 0,
                    "assumptions": ["An average bowl and cooked weights were assumed."],
                }
            ],
            "summary": "One chicken and rice meal was recorded.",
            "assumptions": ["Unspecified quantities use average adult portions."],
        }
    )


class FakeExtractor:
    model = "test-food-extractor"

    def __init__(self, result: FoodLogExtraction) -> None:
        self.result = result

    def extract(
        self,
        raw_text: str,
        recommendations: list[dict[str, Any]],
        catalog_foods: list[dict[str, Any]],
    ) -> FoodLogExtraction:
        assert raw_text
        assert recommendations
        assert catalog_foods
        return self.result


class FailingExtractor:
    model = "failing-test-extractor"

    def extract(
        self,
        raw_text: str,
        recommendations: list[dict[str, Any]],
        catalog_foods: list[dict[str, Any]],
    ) -> FoodLogExtraction:
        raise FoodLogExtractionError("provider unavailable")


def test_food_log_replaces_actual_meals_and_inventory_atomically(
    db: Session, settings: Settings, seeded
) -> None:
    plan = generate_daily_plan(db, settings, TARGET, use_ai=False)
    original_plan = deepcopy(plan.original_plan_json)
    planned = list(
        db.scalars(
            select(NutritionEntry).where(
                NutritionEntry.entry_date == TARGET,
                NutritionEntry.planned_recommendation_id.is_not(None),
            )
        )
    )
    first_id = planned[0].planned_recommendation_id
    assert first_id
    chicken = db.scalar(select(FoodItem).where(FoodItem.name == "Chicken breast"))
    assert chicken
    inventory = InventoryItem(
        food_item_id=chicken.id,
        quantity_estimate=500,
        unit="g",
        confidence="high",
        location="fridge",
    )
    db.add(inventory)
    db.flush()

    first = process_daily_food_log(
        db,
        settings,
        TARGET,
        "I ate a chicken and rice bowl.",
        extractor=FakeExtractor(extraction(matched_recommendation_id=first_id)),
    )

    db.refresh(plan)
    db.refresh(inventory)
    assert plan.original_plan_json == original_plan
    assert first.matched_recommendation_ids == [first_id]
    assert inventory.quantity_estimate == 300
    entries = list(db.scalars(select(NutritionEntry).where(NutritionEntry.entry_date == TARGET)))
    planned_after = [entry for entry in entries if entry.planned_recommendation_id]
    actual = [entry for entry in entries if entry.food_log_id]
    assert len(actual) == 1
    assert actual[0].quantity_json["components"][0]["quantity_value"] == 200
    assert actual[0].quantity_json["components"][0]["quantity_is_assumed"] is True
    assert (
        next(entry for entry in planned_after if entry.planned_recommendation_id == first_id).status
        == "matched_by_food_log"
    )
    assert all(
        entry.status == "discarded_by_food_log"
        for entry in planned_after
        if entry.planned_recommendation_id != first_id
    )

    corrected_quantity = deepcopy(actual[0].quantity_json)
    corrected_quantity["components"][0]["quantity_value"] = 150
    corrected_quantity["components"][0]["quantity_label"] = "150 g"
    correct_nutrition_entry(
        db,
        actual[0],
        {"quantity": corrected_quantity},
        TARGET,
    )
    db.refresh(inventory)
    assert inventory.quantity_estimate == 350

    second = process_daily_food_log(
        db,
        settings,
        TARGET,
        "Actually, it was a smaller chicken and rice bowl.",
        extractor=FakeExtractor(extraction(quantity=100)),
    )

    db.refresh(inventory)
    assert second.matched_recommendation_ids == []
    assert inventory.quantity_estimate == 400
    actual = list(
        db.scalars(
            select(NutritionEntry).where(
                NutritionEntry.entry_date == TARGET,
                NutritionEntry.food_log_id.is_not(None),
            )
        )
    )
    assert len(actual) == 1
    assert actual[0].quantity_json["components"][0]["quantity_value"] == 100
    summary = calculate_nutrition_summary(db, TARGET)
    assert summary["ai_logged_meal_count"] == 1
    assert summary["discarded_by_food_log_count"] == len(planned)


def test_failed_extraction_leaves_recommendations_unchanged(
    db: Session, settings: Settings, seeded
) -> None:
    generate_daily_plan(db, settings, TARGET, use_ai=False)
    before = {
        entry.id: entry.status
        for entry in db.scalars(select(NutritionEntry).where(NutritionEntry.entry_date == TARGET))
    }

    with pytest.raises(FoodLogExtractionError, match="provider unavailable"):
        process_daily_food_log(
            db,
            settings,
            TARGET,
            "I ate something.",
            extractor=FailingExtractor(),
        )

    after = {
        entry.id: entry.status
        for entry in db.scalars(select(NutritionEntry).where(NutritionEntry.entry_date == TARGET))
    }
    assert after == before
    assert db.scalar(select(DailyFoodLog).where(DailyFoodLog.log_date == TARGET)) is None


def test_food_log_endpoint_requires_auth_and_records_with_bearer_token(
    db: Session, monkeypatch: pytest.MonkeyPatch, seeded
) -> None:
    api_settings = Settings(
        DATABASE_URL="postgresql+psycopg://health:health@localhost:55432/health_test",
        OPENAI_API_KEY="fake-key",
        SESSION_SECRET="test-session-secret-with-more-than-32-characters",
        _env_file=None,
    )
    target = local_today(api_settings)
    plan = generate_daily_plan(db, api_settings, target, use_ai=False)
    recommendation = db.scalar(
        select(NutritionEntry).where(
            NutritionEntry.entry_date == target,
            NutritionEntry.planned_recommendation_id.is_not(None),
        )
    )
    assert recommendation and recommendation.planned_recommendation_id
    raw_token = "test-food-log-token"
    db.add(
        ApiToken(
            account_id=seeded.account_id,
            name="test",
            token_hash=token_digest(raw_token, api_settings),
        )
    )
    db.commit()

    def fake_extract(self, raw_text, recommendations, catalog_foods):
        return extraction(matched_recommendation_id=recommendation.planned_recommendation_id)

    monkeypatch.setattr("app.services.food_log.FoodLogExtractor.extract", fake_extract)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: api_settings

    async def make_requests() -> tuple[Response, Response, Response]:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            unauthenticated_response = await client.post(
                "/api/v1/today/nutrition/food-log",
                json={"text": "A chicken and rice bowl."},
            )
            authenticated_response = await client.post(
                "/api/v1/today/nutrition/food-log",
                headers={"Authorization": f"Bearer {raw_token}"},
                json={"text": "A chicken and rice bowl."},
            )
            today_response = await client.get(
                "/api/v1/today",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
        return unauthenticated_response, authenticated_response, today_response

    try:
        unauthenticated, response, today_response = asyncio.run(make_requests())
    finally:
        app.dependency_overrides.clear()

    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    assert response.json()["matched_recommendation_ids"] == [
        recommendation.planned_recommendation_id
    ]
    assert today_response.status_code == 200
    assert today_response.json()["emergency_plate"]["name"] == "Emergency protein plate"
    assert today_response.json()["emergency_plate"]["hands_on_minutes"] == 3
    db.refresh(plan)
    assert plan.status == "active"
