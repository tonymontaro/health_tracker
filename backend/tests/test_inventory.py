import asyncio
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import token_digest
from app.db.models import ApiToken, FoodItem, InventoryItem
from app.db.session import get_db
from app.main import app
from app.schemas.inventory import InventoryExtraction
from app.services.inventory_ingestion import (
    InventoryExtractionError,
    process_inventory_text,
)


def extracted_inventory() -> InventoryExtraction:
    return InventoryExtraction.model_validate(
        {
            "items": [
                {
                    "name": "tomatoes",
                    "item_type": "ingredient",
                    "quantity_value": 600,
                    "unit": "g",
                    "catalog_food_name": "Tomatoes",
                    "location": "fridge",
                    "expires_on": None,
                    "notes": None,
                    "assumptions": [],
                },
                {
                    "name": "Nigerian okra soup",
                    "item_type": "prepared_meal",
                    "quantity_value": 2,
                    "unit": "container",
                    "catalog_food_name": None,
                    "location": "fridge",
                    "expires_on": None,
                    "notes": "Homemade",
                    "assumptions": [],
                },
                {
                    "name": "Whole pizza",
                    "item_type": "prepared_meal",
                    "quantity_value": 1,
                    "unit": "item",
                    "catalog_food_name": None,
                    "location": "freezer",
                    "expires_on": None,
                    "notes": None,
                    "assumptions": [],
                },
            ],
            "summary": "Added tomatoes, okra soup, and a pizza.",
            "assumptions": [],
        }
    )


class FakeInventoryExtractor:
    model = "test-inventory-extractor"

    def extract(self, raw_text: str, catalog_foods: list[dict[str, Any]]) -> InventoryExtraction:
        assert "okra soup" in raw_text
        assert any(food["name"] == "Tomatoes" for food in catalog_foods)
        return extracted_inventory()


class FailingInventoryExtractor:
    model = "failing-inventory-extractor"

    def extract(self, raw_text: str, catalog_foods: list[dict[str, Any]]) -> InventoryExtraction:
        raise InventoryExtractionError("provider unavailable")


def test_inventory_text_adds_catalog_foods_and_prepared_meals_atomically(
    db: Session, settings: Settings, seeded
) -> None:
    result = process_inventory_text(
        db,
        settings,
        "I have tomatoes, two containers of okra soup, and a whole pizza.",
        extractor=FakeInventoryExtractor(),
    )

    assert result.extraction.summary == "Added tomatoes, okra soup, and a pizza."
    assert len(result.inventory_items) == 3
    tomatoes = db.scalar(
        select(InventoryItem)
        .join(FoodItem, FoodItem.id == InventoryItem.food_item_id)
        .where(FoodItem.name == "Tomatoes")
    )
    soup = db.scalar(select(InventoryItem).where(InventoryItem.custom_name == "Nigerian okra soup"))
    pizza = db.scalar(select(InventoryItem).where(InventoryItem.custom_name == "Whole pizza"))
    assert tomatoes and tomatoes.quantity_estimate == 600
    assert tomatoes.item_type == "ingredient"
    assert soup and soup.quantity_estimate == 2
    assert soup.item_type == "prepared_meal"
    assert soup.unit == "container"
    assert pizza and pizza.location == "freezer"

    before = db.scalar(select(func.count()).select_from(InventoryItem))
    with pytest.raises(InventoryExtractionError, match="provider unavailable"):
        process_inventory_text(
            db,
            settings,
            "This provider call fails.",
            extractor=FailingInventoryExtractor(),
        )
    after = db.scalar(select(func.count()).select_from(InventoryItem))
    assert after == before


def test_shopping_review_purchase_and_inventory_management_api(
    db: Session, settings: Settings, seeded
) -> None:
    raw_token = "test-inventory-token"
    db.add(
        ApiToken(
            account_id=seeded.account_id,
            name="inventory-test",
            token_hash=token_digest(raw_token, settings),
        )
    )
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings
    headers = {"Authorization": f"Bearer {raw_token}"}

    async def make_requests() -> tuple[Response, ...]:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            unauthenticated = await client.get("/api/v1/inventory")
            plan = await client.get("/api/v1/shopping/current?retailer=Coop", headers=headers)
            plan_id = plan.json()["id"]
            edited = await client.patch(
                f"/api/v1/shopping/{plan_id}/items/0",
                headers=headers,
                json={"quantity": 2, "unit": "kg"},
            )
            removed = await client.delete(f"/api/v1/shopping/{plan_id}/items/1", headers=headers)
            purchased = await client.post(
                f"/api/v1/shopping/{plan_id}/mark-purchased", headers=headers
            )
            purchased_again = await client.post(
                f"/api/v1/shopping/{plan_id}/mark-purchased", headers=headers
            )
            inventory = await client.get("/api/v1/inventory", headers=headers)
            chicken_id = next(
                item["id"] for item in inventory.json() if item["name"] == "Chicken breast"
            )
            updated = await client.patch(
                f"/api/v1/inventory/{chicken_id}",
                headers=headers,
                json={"quantity_estimate": 1500, "location": "freezer"},
            )
            deleted = await client.delete(f"/api/v1/inventory/{chicken_id}", headers=headers)
            inventory_after_delete = await client.get("/api/v1/inventory", headers=headers)
        return (
            unauthenticated,
            plan,
            edited,
            removed,
            purchased,
            purchased_again,
            inventory,
            updated,
            deleted,
            inventory_after_delete,
        )

    try:
        responses = asyncio.run(make_requests())
    finally:
        app.dependency_overrides.clear()

    (
        unauthenticated,
        plan,
        edited,
        removed,
        purchased,
        purchased_again,
        inventory,
        updated,
        deleted,
        inventory_after_delete,
    ) = responses
    assert unauthenticated.status_code == 401
    assert plan.status_code == 200
    assert edited.status_code == 200
    assert edited.json()["items"][0]["quantity_label"] == "2 kg"
    assert edited.json()["estimated_total_chf"] > plan.json()["estimated_total_chf"]
    assert removed.status_code == 204
    assert purchased.status_code == 200
    assert purchased.json()["inventory_items_updated"] == 9
    assert purchased_again.json()["inventory_items_updated"] == 0
    assert inventory.status_code == 200
    assert (
        next(item for item in inventory.json() if item["name"] == "Chicken breast")[
            "quantity_estimate"
        ]
        == 2000
    )
    assert all(item["name"] != "Salmon" for item in inventory.json())
    assert updated.status_code == 200
    assert updated.json()["quantity_label"] == "1.5 kg"
    assert deleted.status_code == 204
    assert all(item["name"] != "Chicken breast" for item in inventory_after_delete.json())
