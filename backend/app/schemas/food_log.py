from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FoodLogRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Food log text cannot be blank")
        return value


class ExtractedFoodComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    quantity_value: float = Field(gt=0, le=10000)
    unit: Literal["g", "ml", "item"]
    quantity_label: str
    catalog_food_name: str | None
    quantity_is_assumed: bool


class ExtractedMeal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meal_name: str
    meal_slot: Literal["meal_1", "meal_2", "snack", "fruit"]
    description: str
    portion_count: float = Field(gt=0, le=10)
    quantity_label: str
    components: list[ExtractedFoodComponent] = Field(min_length=1, max_length=30)
    estimated_calories_kcal: float = Field(ge=0, le=10000)
    estimated_protein_g: float = Field(ge=0, le=500)
    estimated_fiber_g: float = Field(ge=0, le=200)
    matched_recommendation_id: str | None
    match_confidence: float = Field(ge=0, le=1)
    assumptions: list[str] = Field(max_length=10)


class FoodLogExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ate_nothing: bool
    meals: list[ExtractedMeal] = Field(max_length=12)
    summary: str
    assumptions: list[str] = Field(max_length=20)


class FoodLogResponse(BaseModel):
    date: str
    raw_text: str
    extraction: FoodLogExtraction
    discarded_recommendation_ids: list[str]
    matched_recommendation_ids: list[str]
