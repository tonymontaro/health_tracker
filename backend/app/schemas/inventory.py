from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

InventoryUnit = Literal["g", "ml", "item", "portion", "container"]
InventoryLocation = Literal["fridge", "freezer", "pantry", "counter", "multiple"]
InventoryItemType = Literal["ingredient", "prepared_meal"]


class InventoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    quantity_estimate: float | None = Field(default=None, ge=0, le=1_000_000)
    unit: InventoryUnit | None = None
    confidence: Literal["low", "medium", "high"] | None = None
    expires_on: date | None = None
    location: InventoryLocation | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name", "notes")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ShoppingItemQuantityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: float = Field(gt=0, le=1_000_000)
    unit: Literal["g", "kg", "ml", "item"]


class InventoryTextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=5000)

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Inventory text cannot be blank")
        return stripped


class ExtractedInventoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    item_type: InventoryItemType
    quantity_value: float = Field(gt=0, le=1_000_000)
    unit: InventoryUnit
    catalog_food_name: str | None
    location: Literal["fridge", "freezer", "pantry", "counter"]
    expires_on: date | None
    notes: str | None = Field(max_length=2000)
    assumptions: list[str] = Field(max_length=10)


class InventoryExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ExtractedInventoryItem] = Field(max_length=40)
    summary: str
    assumptions: list[str] = Field(max_length=20)


class InventoryEntryResponse(BaseModel):
    id: UUID
    name: str
    food: str
    catalog_item: bool
    item_type: InventoryItemType
    quantity_estimate: float | None
    quantity_label: str | None
    unit: str
    confidence: str
    expires_on: date | None
    location: str
    notes: str | None
    source: str


class InventoryTextResponse(BaseModel):
    raw_text: str
    extraction: InventoryExtraction
    inventory_items: list[InventoryEntryResponse]
