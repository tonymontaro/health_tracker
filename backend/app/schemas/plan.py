from datetime import date
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Confidence(StrEnum):
    RECORDED = "recorded"
    CALCULATED = "calculated"
    ESTIMATED = "estimated"
    GOAL = "goal"


class MealProposal(BaseModel):
    template_name: str
    description: str
    suggested_window: str
    expected: bool = True
    estimated_protein_g: float = Field(ge=0, le=250)
    estimated_fiber_g: float = Field(ge=0, le=100)
    hands_on_minutes: int = Field(ge=0, le=120)
    ingredients: list[str]
    preparation: str


class MealRecommendation(MealProposal):
    recommendation_id: str


class FruitProposal(BaseModel):
    name: str
    quantity: str
    expected: bool = False


class FruitRecommendation(FruitProposal):
    recommendation_id: str


class SnackProposal(BaseModel):
    name: str
    description: str
    expected: bool = False
    estimated_protein_g: float = Field(ge=0, le=150)


class SnackRecommendation(SnackProposal):
    recommendation_id: str


class NutritionPlanProposal(BaseModel):
    meal_1: MealProposal
    meal_2: MealProposal | None
    fruits: list[FruitProposal] = Field(max_length=5)
    snacks: list[SnackProposal] = Field(max_length=5)
    expected_main_meals: Literal[1, 2]
    approximate_protein_g: float = Field(ge=0, le=350)
    guidance: str

    @model_validator(mode="after")
    def meal_count_matches(self) -> "NutritionPlanProposal":
        actual = 1 + int(self.meal_2 is not None)
        if actual != self.expected_main_meals:
            raise ValueError("expected_main_meals must match the supplied main meals")
        return self


class NutritionPlan(BaseModel):
    meal_1: MealRecommendation
    meal_2: MealRecommendation | None
    fruits: list[FruitRecommendation]
    snacks: list[SnackRecommendation]
    expected_main_meals: Literal[1, 2]
    approximate_protein_g: float
    guidance: str


class ExerciseType(StrEnum):
    STRENGTH = "strength"
    BODYWEIGHT = "bodyweight"
    RUN = "run"
    BIKE = "bike"
    RECOVERY = "recovery"


class ExerciseProposal(BaseModel):
    exercise_name: str
    exercise_type: ExerciseType
    load_kg: float | None = Field(default=None, ge=0, le=500)
    external_load_kg: float | None = Field(default=None, ge=0, le=200)
    sets: int | None = Field(default=None, ge=1, le=20)
    reps_per_set: list[int] | None = None
    rest_seconds: int | None = Field(default=None, ge=0, le=900)
    distance_km: float | None = Field(default=None, gt=0, le=100)
    pace_seconds_per_km: int | None = Field(default=None, ge=180, le=900)
    duration_seconds: int | None = Field(default=None, gt=0, le=21600)
    treadmill_speed_kmh: float | None = Field(default=None, gt=0, le=30)
    incline_percent: float | None = Field(default=None, ge=0, le=20)
    target_power_min_watts: int | None = Field(default=None, gt=0, le=2000)
    target_power_max_watts: int | None = Field(default=None, gt=0, le=2000)
    cadence_min_rpm: int | None = Field(default=None, gt=0, le=200)
    cadence_max_rpm: int | None = Field(default=None, gt=0, le=200)
    expected_difficulty: int = Field(ge=1, le=10)
    instructions: str


class ExercisePrescription(ExerciseProposal):
    recommendation_id: str


class WorkoutPlanProposal(BaseModel):
    kind: Literal[
        "strength",
        "bodyweight",
        "run",
        "bike",
        "interval_run",
        "interval_bike",
        "recovery",
        "rest",
    ]
    intensity: Literal["rest", "very_light", "light", "moderate", "hard"]
    title: str
    exercises: list[ExerciseProposal] = Field(max_length=3)
    expected_duration_minutes: int = Field(ge=0, le=360)
    summary: str

    @model_validator(mode="after")
    def rest_has_no_exercises(self) -> "WorkoutPlanProposal":
        if self.kind == "rest":
            if self.exercises:
                raise ValueError("rest plans cannot contain exercises")
            if self.intensity != "rest" or self.expected_duration_minutes != 0:
                raise ValueError("rest plans require rest intensity and zero duration")
            return self
        if not self.exercises:
            raise ValueError("active workout plans require an exercise")
        if self.intensity == "rest" or self.expected_duration_minutes == 0:
            raise ValueError("active workout plans require active intensity and positive duration")
        if self.kind == "recovery" and any(
            exercise.exercise_type != ExerciseType.RECOVERY for exercise in self.exercises
        ):
            raise ValueError("recovery workout plans may only contain recovery exercises")
        return self


class WorkoutPlan(BaseModel):
    kind: str
    intensity: str
    title: str
    exercises: list[ExercisePrescription]
    expected_duration_minutes: int
    summary: str


class ShoppingPlanSummary(BaseModel):
    action_needed: bool
    retailer: Literal["Coop", "Migros", "Either"]
    mode: Literal["online", "in_store", "mixed", "none"]
    summary: str
    estimated_total_chf: float = Field(ge=0, le=1000)
    items: list[str] = Field(max_length=30)


class PrepAction(BaseModel):
    action: str
    active_minutes: int = Field(ge=0, le=120)
    when: str


class AlternativeSummary(BaseModel):
    option: str
    tradeoff: str


class RecommendationRationale(BaseModel):
    summary: str
    objectives: list[str] = Field(max_length=5)
    history_factors: list[str] = Field(max_length=5)
    nutrition_factors: list[str] = Field(max_length=5)
    recovery_factors: list[str] = Field(max_length=5)
    scheduling_factors: list[str] = Field(max_length=5)
    progression_logic: str | None
    alternatives_considered: list[AlternativeSummary] = Field(max_length=3)


class DailyPlanProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nutrition: NutritionPlanProposal
    workout: WorkoutPlanProposal
    shopping: ShoppingPlanSummary
    prep_actions: list[PrepAction] = Field(max_length=1)
    short_summary: str
    rationale: RecommendationRationale
    assumptions: list[str] = Field(max_length=8)


class ProfileSnapshotSummary(BaseModel):
    short_summary: str
    detailed_summary: str
    recovery_status: str
    strength_capacity: dict[str, Any]
    endurance_capacity: dict[str, Any]
    recent_training: dict[str, Any]
    recent_nutrition: dict[str, Any]
    source_quality: dict[str, str]


class DailyPlanDocument(BaseModel):
    plan_date: date
    source: Literal["openai", "fallback"]
    profile_snapshot: ProfileSnapshotSummary
    nutrition: NutritionPlan
    workout: WorkoutPlan
    shopping: ShoppingPlanSummary
    prep_actions: list[PrepAction]
    short_summary: str
    rationale: RecommendationRationale
    assumptions: list[str]


def _recommendation_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def canonicalize_proposal(
    proposal: DailyPlanProposal,
    *,
    plan_date: date,
    snapshot: ProfileSnapshotSummary,
    source: Literal["openai", "fallback"],
) -> DailyPlanDocument:
    nutrition = NutritionPlan(
        meal_1=MealRecommendation(
            **proposal.nutrition.meal_1.model_dump(),
            recommendation_id=_recommendation_id("meal"),
        ),
        meal_2=(
            MealRecommendation(
                **proposal.nutrition.meal_2.model_dump(),
                recommendation_id=_recommendation_id("meal"),
            )
            if proposal.nutrition.meal_2
            else None
        ),
        fruits=[
            FruitRecommendation(**fruit.model_dump(), recommendation_id=_recommendation_id("fruit"))
            for fruit in proposal.nutrition.fruits
        ],
        snacks=[
            SnackRecommendation(**snack.model_dump(), recommendation_id=_recommendation_id("snack"))
            for snack in proposal.nutrition.snacks
        ],
        expected_main_meals=proposal.nutrition.expected_main_meals,
        approximate_protein_g=proposal.nutrition.approximate_protein_g,
        guidance=proposal.nutrition.guidance,
    )
    workout = WorkoutPlan(
        kind=proposal.workout.kind,
        intensity=proposal.workout.intensity,
        title=proposal.workout.title,
        exercises=[
            ExercisePrescription(
                **exercise.model_dump(), recommendation_id=_recommendation_id("exercise")
            )
            for exercise in proposal.workout.exercises
        ],
        expected_duration_minutes=proposal.workout.expected_duration_minutes,
        summary=proposal.workout.summary,
    )
    return DailyPlanDocument(
        plan_date=plan_date,
        source=source,
        profile_snapshot=snapshot,
        nutrition=nutrition,
        workout=workout,
        shopping=proposal.shopping,
        prep_actions=proposal.prep_actions,
        short_summary=proposal.short_summary,
        rationale=proposal.rationale,
        assumptions=proposal.assumptions,
    )


def proposal_from_document(document: DailyPlanDocument) -> DailyPlanProposal:
    return DailyPlanProposal(
        nutrition=NutritionPlanProposal(
            meal_1=MealProposal.model_validate(
                document.nutrition.meal_1.model_dump(exclude={"recommendation_id"})
            ),
            meal_2=(
                MealProposal.model_validate(
                    document.nutrition.meal_2.model_dump(exclude={"recommendation_id"})
                )
                if document.nutrition.meal_2
                else None
            ),
            fruits=[
                FruitProposal.model_validate(item.model_dump(exclude={"recommendation_id"}))
                for item in document.nutrition.fruits
            ],
            snacks=[
                SnackProposal.model_validate(item.model_dump(exclude={"recommendation_id"}))
                for item in document.nutrition.snacks
            ],
            expected_main_meals=document.nutrition.expected_main_meals,
            approximate_protein_g=document.nutrition.approximate_protein_g,
            guidance=document.nutrition.guidance,
        ),
        workout=WorkoutPlanProposal(
            kind=document.workout.kind,
            intensity=document.workout.intensity,
            title=document.workout.title,
            exercises=[
                ExerciseProposal.model_validate(item.model_dump(exclude={"recommendation_id"}))
                for item in document.workout.exercises
            ],
            expected_duration_minutes=document.workout.expected_duration_minutes,
            summary=document.workout.summary,
        ),
        shopping=document.shopping,
        prep_actions=document.prep_actions,
        short_summary=document.short_summary,
        rationale=document.rationale,
        assumptions=document.assumptions,
    )
