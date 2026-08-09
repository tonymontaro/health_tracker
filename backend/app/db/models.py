from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class UUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class UserAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_account"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class WebSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "web_session"

    account_id: Mapped[UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApiToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "api_token"

    account_id: Mapped[UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_profile"

    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), unique=True
    )
    timezone: Mapped[str] = mapped_column(String(80), default="Europe/Zurich")
    location: Mapped[str] = mapped_column(String(120), default="Zurich, Switzerland")
    weight_kg: Mapped[float | None] = mapped_column(Float)
    height_cm: Mapped[float | None] = mapped_column(Float)
    age: Mapped[int | None] = mapped_column(Integer)
    sex: Mapped[str | None] = mapped_column(String(40))
    body_composition_goal: Mapped[str | None] = mapped_column(Text)
    primary_training_goal: Mapped[str] = mapped_column(Text)
    max_main_meals_per_day: Mapped[int] = mapped_column(Integer, default=2)
    preferred_main_meals_per_day: Mapped[int] = mapped_column(Integer, default=2)
    max_exercises_per_day: Mapped[int] = mapped_column(Integer, default=3)
    gym_days: Mapped[list[str]] = mapped_column(JSONB, default=list)
    office_days: Mapped[list[str]] = mapped_column(JSONB, default=list)
    excluded_exercises: Mapped[list[str]] = mapped_column(JSONB, default=list)
    nutrition_preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    allergies: Mapped[list[str]] = mapped_column(JSONB, default=list)
    medical_constraints: Mapped[list[str]] = mapped_column(JSONB, default=list)
    strength_capacity_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    endurance_capacity_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    kitchen_equipment_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class Equipment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "equipment"

    name: Mapped[str] = mapped_column(String(160), unique=True)
    category: Mapped[str] = mapped_column(String(40))
    details_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    available: Mapped[bool] = mapped_column(Boolean, default=True)


class FoodItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "food_item"

    name: Mapped[str] = mapped_column(String(160), unique=True)
    category: Mapped[str] = mapped_column(String(60))
    protein_g_per_100: Mapped[float | None] = mapped_column(Float)
    carbs_g_per_100: Mapped[float | None] = mapped_column(Float)
    fat_g_per_100: Mapped[float | None] = mapped_column(Float)
    fiber_g_per_100: Mapped[float | None] = mapped_column(Float)
    calories_per_100: Mapped[float | None] = mapped_column(Float)
    typical_unit: Mapped[str] = mapped_column(String(40), default="g")
    shelf_life_days: Mapped[int | None] = mapped_column(Integer)
    freezer_friendly: Mapped[bool] = mapped_column(Boolean, default=False)
    retailer_notes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MealTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "meal_template"

    name: Mapped[str] = mapped_column(String(160), unique=True)
    description: Mapped[str] = mapped_column(Text)
    ingredients_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    servings: Mapped[int] = mapped_column(Integer, default=1)
    hands_on_minutes: Mapped[int] = mapped_column(Integer)
    total_minutes: Mapped[int] = mapped_column(Integer)
    batch_size: Mapped[int] = mapped_column(Integer, default=1)
    fridge_life_days: Mapped[int | None] = mapped_column(Integer)
    freezer_friendly: Mapped[bool] = mapped_column(Boolean, default=False)
    reheat_method: Mapped[str | None] = mapped_column(String(160))
    estimated_protein_g: Mapped[float] = mapped_column(Float)
    estimated_fiber_g: Mapped[float] = mapped_column(Float)
    produce_portions: Mapped[float] = mapped_column(Float)
    effort_score: Mapped[int] = mapped_column(Integer)
    preference_score: Mapped[int] = mapped_column(Integer, default=5)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Exercise(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "exercise"

    name: Mapped[str] = mapped_column(String(160), unique=True)
    category: Mapped[str] = mapped_column(String(40))
    equipment_required: Mapped[list[str]] = mapped_column(JSONB, default=list)
    gym_only: Mapped[bool] = mapped_column(Boolean, default=False)
    compound: Mapped[bool] = mapped_column(Boolean, default=False)
    measurement_type: Mapped[str] = mapped_column(String(40))
    pain_exclusion_tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class DerivedSummary(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "derived_summary"

    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_profile.id", ondelete="CASCADE"), unique=True
    )
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    training_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    nutrition_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ProfileSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "profile_snapshot"

    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    training_status: Mapped[str] = mapped_column(Text)
    strength_capacity_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    endurance_capacity_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    recent_training_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    recent_nutrition_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    recovery_status: Mapped[str] = mapped_column(String(80))
    adherence_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    important_constraints_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    current_priorities_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    short_summary: Mapped[str] = mapped_column(Text)
    detailed_summary: Mapped[str] = mapped_column(Text)
    source_quality_json: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlanningRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "planning_run"

    plan_date: Mapped[date] = mapped_column(Date, index=True)
    model: Mapped[str] = mapped_column(String(160))
    planner_version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40))
    context_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    model_output_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    validation_result_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DailyPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "daily_plan"
    __table_args__ = (UniqueConstraint("plan_date"),)

    plan_date: Mapped[date] = mapped_column(Date, index=True)
    profile_snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("profile_snapshot.id"))
    planning_run_id: Mapped[UUID] = mapped_column(ForeignKey("planning_run.id"))
    status: Mapped[str] = mapped_column(String(40), default="active")
    short_summary: Mapped[str] = mapped_column(Text)
    original_plan_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    current_plan_json: Mapped[dict[str, Any]] = mapped_column(JSONB)


class DailyFoodLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "daily_food_log"
    __table_args__ = (UniqueConstraint("log_date"),)

    log_date: Mapped[date] = mapped_column(Date, index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    extraction_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    model: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(40), default="processed")


class NutritionEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "nutrition_entry"
    __table_args__ = (UniqueConstraint("entry_date", "planned_recommendation_id"),)

    entry_date: Mapped[date] = mapped_column(Date, index=True)
    meal_slot: Mapped[str] = mapped_column(String(40))
    planned_recommendation_id: Mapped[str | None] = mapped_column(String(80))
    food_or_meal_reference: Mapped[str | None] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    quantity_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    source: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40))
    expected: Mapped[bool] = mapped_column(Boolean, default=True)
    food_log_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("daily_food_log.id", ondelete="CASCADE"), index=True
    )


class WorkoutEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workout_entry"
    __table_args__ = (UniqueConstraint("entry_date", "planned_recommendation_id"),)

    entry_date: Mapped[date] = mapped_column(Date, index=True)
    planned_recommendation_id: Mapped[str | None] = mapped_column(String(80))
    exercise_id: Mapped[UUID | None] = mapped_column(ForeignKey("exercise.id"))
    exercise_name: Mapped[str] = mapped_column(String(160))
    prescription_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    actual_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    difficulty_1_to_10: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(40))
    pain_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)


class PlanModification(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "plan_modification"

    daily_plan_id: Mapped[UUID] = mapped_column(ForeignKey("daily_plan.id", ondelete="CASCADE"))
    recommendation_id: Mapped[str] = mapped_column(String(80))
    original_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    replacement_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(40))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InventoryItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "inventory_item"

    food_item_id: Mapped[UUID] = mapped_column(ForeignKey("food_item.id"), unique=True)
    quantity_estimate: Mapped[float | None] = mapped_column(Float)
    quantity_label: Mapped[str | None] = mapped_column(String(80))
    unit: Mapped[str] = mapped_column(String(40))
    confidence: Mapped[str] = mapped_column(String(20), default="low")
    expires_on: Mapped[date | None] = mapped_column(Date)
    location: Mapped[str] = mapped_column(String(40), default="pantry")


class ShoppingPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "shopping_plan"
    __table_args__ = (UniqueConstraint("week_start", "retailer", "mode"),)

    week_start: Mapped[date] = mapped_column(Date, index=True)
    retailer: Mapped[str] = mapped_column(String(40))
    mode: Mapped[str] = mapped_column(String(20))
    estimated_total_chf: Mapped[float] = mapped_column(Float)
    items_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(30), default="draft")


class NotificationEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "notification_event"
    __table_args__ = (UniqueConstraint("event_type", "event_date"),)

    event_type: Mapped[str] = mapped_column(String(60))
    event_date: Mapped[date] = mapped_column(Date, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ChatMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "chat_message"

    message_date: Mapped[date] = mapped_column(Date, index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    proposal_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
