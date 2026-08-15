import json
from typing import Any, Protocol

from openai import OpenAI
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import FoodItem, InventoryItem
from app.schemas.inventory import (
    InventoryExtraction,
    InventoryTextResponse,
)
from app.services.inventory import (
    _units_are_compatible,
    food_for_inventory_item,
    format_inventory_quantity,
    serialize_inventory_item,
)

INVENTORY_SYSTEM_PROMPT = """Interpret free text describing food that should be added to inventory.
Extract only food, drink, ingredients, or prepared meals that the user says they have or wants added.
Never invent an unmentioned item.
Classify raw or packaged ingredients as ingredient and cooked dishes or complete foods as prepared_meal.
Prepared meals can be arbitrary dishes such as pizza, stew, or Nigerian okra soup.
Use catalog_food_name only for a true match to one supplied food catalog entry and copy its name exactly.
Use grams or milliliters when the user supplies weight or volume.
Use item for countable whole foods, portion for individual servings, and container for stored batches.
When quantity is missing, use one sensible item, portion, or container and state that assumption.
Respect an explicitly stated fridge, freezer, pantry, or counter location.
Otherwise choose the most practical safe storage location and state the assumption.
Set expires_on only when the user gives a specific date.
Preserve useful preparation, packaging, and condition details in notes without adding facts.
Do not diagnose, give advice, or output hidden reasoning.
"""


class InventoryExtractionError(RuntimeError):
    pass


class InventoryExtractionProvider(Protocol):
    model: str

    def extract(
        self, raw_text: str, catalog_foods: list[dict[str, Any]]
    ) -> InventoryExtraction: ...


class InventoryExtractor:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_key_value:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        self.model = settings.openai_inventory_model
        self.client = OpenAI(
            api_key=settings.openai_key_value,
            timeout=120,
            max_retries=0,
        )

    def extract(self, raw_text: str, catalog_foods: list[dict[str, Any]]) -> InventoryExtraction:
        canonical_foods = {food["name"].casefold(): food["name"] for food in catalog_foods}
        correction: dict[str, Any] | None = None
        last_errors: list[str] = []
        for _ in range(2):
            payload: dict[str, Any] = {
                "inventory_text": raw_text,
                "food_catalog": catalog_foods,
            }
            if correction:
                payload["correction"] = correction
            try:
                response = self.client.responses.parse(
                    model=self.model,
                    reasoning={"effort": "low"},
                    input=[
                        {"role": "system", "content": INVENTORY_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(payload, separators=(",", ":")),
                        },
                    ],
                    text_format=InventoryExtraction,
                    store=False,
                )
                extraction = response.output_parsed
                if extraction is None:
                    last_errors = ["The model returned no parsed result."]
                else:
                    extraction = _canonicalize_catalog_names(extraction, canonical_foods)
                    last_errors = validate_inventory_extraction(
                        extraction, set(canonical_foods.values())
                    )
                    if not last_errors:
                        return extraction
            except Exception as exc:  # noqa: BLE001 - one bounded provider repair attempt.
                last_errors = [f"{type(exc).__name__}: {str(exc)[:1000]}"]
            correction = {
                "errors": last_errors,
                "instruction": "Return a fresh result that fixes every error without adding items.",
            }
        raise InventoryExtractionError(
            "AI could not reliably interpret the inventory text. Nothing was changed."
        )


def validate_inventory_extraction(
    extraction: InventoryExtraction, known_catalog_names: set[str]
) -> list[str]:
    errors: list[str] = []
    if not extraction.items:
        errors.append("at least one inventory item is required")
    for item in extraction.items:
        if item.catalog_food_name and item.catalog_food_name not in known_catalog_names:
            errors.append(f"unknown catalog food: {item.catalog_food_name}")
    return errors


def process_inventory_text(
    db: Session,
    settings: Settings,
    raw_text: str,
    *,
    extractor: InventoryExtractionProvider | None = None,
) -> InventoryTextResponse:
    foods = list(
        db.scalars(select(FoodItem).where(FoodItem.active.is_(True)).order_by(FoodItem.name))
    )
    catalog_foods = [
        {
            "name": food.name,
            "category": food.category,
            "typical_unit": food.typical_unit,
        }
        for food in foods
    ]
    active_extractor = extractor or InventoryExtractor(settings)

    # The provider call and all validation finish before the first mutation.
    extraction = active_extractor.extract(raw_text, catalog_foods)
    errors = validate_inventory_extraction(extraction, {food.name for food in foods})
    if errors:
        raise InventoryExtractionError("; ".join(errors))

    foods_by_name = {food.name: food for food in foods}
    _validate_existing_units(db, extraction, foods_by_name)
    touched: list[InventoryItem] = []
    try:
        for extracted in extraction.items:
            food = foods_by_name.get(extracted.catalog_food_name or "")
            item = _find_existing_item(db, extracted, food)
            if item is None:
                item = InventoryItem(
                    food_item_id=food.id if food else None,
                    custom_name=None if food else extracted.name,
                    item_type=extracted.item_type,
                    notes=extracted.notes,
                    source="ai_text",
                    quantity_estimate=0,
                    quantity_label=None,
                    unit=extracted.unit,
                    confidence="medium",
                    expires_on=extracted.expires_on,
                    location=extracted.location,
                )
                db.add(item)
                db.flush()
            if not _units_are_compatible(extracted.unit, item.unit):
                raise InventoryExtractionError(
                    f"Cannot safely combine {extracted.name} in {extracted.unit} with inventory "
                    f"stored in {item.unit}. Nothing was changed."
                )
            current_quantity = item.quantity_estimate or 0
            item.quantity_estimate = current_quantity + extracted.quantity_value
            item.quantity_label = format_inventory_quantity(item.quantity_estimate, item.unit)
            if item.location != extracted.location:
                item.location = "multiple"
            if extracted.expires_on and (
                item.expires_on is None or extracted.expires_on < item.expires_on
            ):
                item.expires_on = extracted.expires_on
            if not item.notes and extracted.notes:
                item.notes = extracted.notes
            if item not in touched:
                touched.append(item)
        db.commit()
    except Exception:
        db.rollback()
        raise

    response_items = []
    for item in touched:
        db.refresh(item)
        response_items.append(serialize_inventory_item(item, food_for_inventory_item(db, item)))
    return InventoryTextResponse.model_validate(
        {
            "raw_text": raw_text,
            "extraction": extraction,
            "inventory_items": response_items,
        }
    )


def _validate_existing_units(
    db: Session,
    extraction: InventoryExtraction,
    foods_by_name: dict[str, FoodItem],
) -> None:
    for extracted in extraction.items:
        food = foods_by_name.get(extracted.catalog_food_name or "")
        existing = _find_existing_item(db, extracted, food)
        if existing and not _units_are_compatible(extracted.unit, existing.unit):
            name = food.name if food else extracted.name
            raise InventoryExtractionError(
                f"Cannot safely combine {name} in {extracted.unit} with inventory stored in "
                f"{existing.unit}. Nothing was changed."
            )


def _find_existing_item(db: Session, extracted: Any, food: FoodItem | None) -> InventoryItem | None:
    if food:
        return db.scalar(select(InventoryItem).where(InventoryItem.food_item_id == food.id))
    return db.scalar(
        select(InventoryItem).where(
            InventoryItem.food_item_id.is_(None),
            func.lower(InventoryItem.custom_name) == extracted.name.casefold(),
            InventoryItem.item_type == extracted.item_type,
            InventoryItem.location == extracted.location,
            InventoryItem.unit == extracted.unit,
        )
    )


def _canonicalize_catalog_names(
    extraction: InventoryExtraction, canonical_foods: dict[str, str]
) -> InventoryExtraction:
    payload = extraction.model_dump(mode="json")
    for item in payload["items"]:
        catalog_name = item.get("catalog_food_name")
        if isinstance(catalog_name, str):
            item["catalog_food_name"] = canonical_foods.get(catalog_name.casefold(), catalog_name)
    return InventoryExtraction.model_validate(payload)
