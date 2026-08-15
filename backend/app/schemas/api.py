from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.plan import ExerciseProposal, FruitProposal, MealProposal, SnackProposal


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)


class SessionResponse(BaseModel):
    authenticated: bool
    email: str
    csrf_token: str


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timezone: str
    location: str
    weight_kg: float | None
    height_cm: float | None
    age: int | None
    sex: str | None
    body_composition_goal: str | None
    primary_training_goal: str
    current_target_goal: str | None
    max_main_meals_per_day: int
    preferred_main_meals_per_day: int
    max_exercises_per_day: int
    gym_days: list[str]
    office_days: list[str]
    excluded_exercises: list[str]
    nutrition_preferences: dict[str, Any]
    allergies: list[str]
    medical_constraints: list[str]
    strength_capacity_json: dict[str, Any]
    endurance_capacity_json: dict[str, Any]
    kitchen_equipment_json: list[dict[str, Any]]


class ProfileUpdate(BaseModel):
    timezone: str | None = None
    location: str | None = None
    weight_kg: float | None = Field(default=None, gt=0, le=500)
    height_cm: float | None = Field(default=None, gt=0, le=300)
    age: int | None = Field(default=None, ge=18, le=120)
    sex: str | None = None
    body_composition_goal: str | None = None
    primary_training_goal: str | None = None
    current_target_goal: str | None = Field(default=None, max_length=4000)
    max_main_meals_per_day: int | None = Field(default=None, ge=1, le=2)
    preferred_main_meals_per_day: int | None = Field(default=None, ge=1, le=2)
    max_exercises_per_day: int | None = Field(default=None, ge=1, le=3)
    gym_days: list[str] | None = None
    office_days: list[str] | None = None
    excluded_exercises: list[str] | None = None
    nutrition_preferences: dict[str, Any] | None = None
    allergies: list[str] | None = None
    medical_constraints: list[str] | None = None
    kitchen_equipment_json: list[dict[str, Any]] | None = None
    strength_capacity_json: dict[str, Any] | None = None
    endurance_capacity_json: dict[str, Any] | None = None

    @field_validator("gym_days", "office_days")
    @classmethod
    def validate_weekdays(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        weekdays = {
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        }
        unknown = sorted(set(value) - weekdays)
        if unknown:
            raise ValueError("Unknown weekdays: " + ", ".join(unknown))
        return list(dict.fromkeys(value))


class EquipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    category: str
    details_json: dict[str, Any]
    available: bool


class EquipmentUpdate(BaseModel):
    available: bool


class ReplaceRecommendationRequest(BaseModel):
    replacement: dict[str, Any]
    reason: str = Field(min_length=1, max_length=1000)


class RegenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preference: str | None = Field(default=None, max_length=2000)

    @field_validator("preference")
    @classmethod
    def normalize_preference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class WorkoutCompletionRequest(BaseModel):
    results: dict[str, dict[str, Any]]
    difficulty_1_to_10: int = Field(ge=1, le=10)
    pain_flag: bool = False
    notes: str | None = Field(default=None, max_length=2000)


class WorkoutRecommendationCompletionRequest(BaseModel):
    difficulty_1_to_10: int = Field(default=5, ge=1, le=10)


class ManualNutritionRequest(BaseModel):
    meal_slot: str
    description: str = Field(min_length=1, max_length=1000)
    quantity: dict[str, Any] = Field(default_factory=dict)
    status: str = "confirmed"


class HistoryNutritionUpdate(BaseModel):
    description: str | None = None
    quantity: dict[str, Any] | None = None
    status: str | None = None


class HistoryWorkoutUpdate(BaseModel):
    actual: dict[str, Any] | None = None
    difficulty_1_to_10: int | None = Field(default=None, ge=1, le=10)
    status: str | None = None
    pain_flag: bool | None = None
    notes: str | None = None


class QuestionRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)


class RecommendationChange(BaseModel):
    recommendation_id: str
    replacement: MealProposal | FruitProposal | SnackProposal | ExerciseProposal
    reason: str


class QAResponse(BaseModel):
    answer: str
    proposed_change: RecommendationChange | None
    caution: str | None


class QuestionResponse(QAResponse):
    message_id: UUID


class ChatMessageResponse(QuestionResponse):
    message_date: date
    question: str
    created_at: datetime
    applied_at: datetime | None


class ApiTokenResponse(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    revoked_at: datetime | None


class ApiTokenCreated(ApiTokenResponse):
    token: str
