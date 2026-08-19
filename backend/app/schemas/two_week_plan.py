from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

WorkoutKind = Literal[
    "strength",
    "bodyweight",
    "run",
    "bike",
    "interval_run",
    "interval_bike",
    "recovery",
    "rest",
]
WorkoutIntensity = Literal["rest", "very_light", "light", "moderate", "hard"]


class TwoWeekWorkoutGuidance(BaseModel):
    """Strategic workout intent that the daily planner expands into a final prescription."""

    model_config = ConfigDict(extra="forbid")

    kind: WorkoutKind
    intensity: WorkoutIntensity
    title: str
    expected_duration_minutes: int = Field(ge=0, le=360)
    requires_gym: bool
    summary: str

    @model_validator(mode="after")
    def validate_rest_shape(self) -> "TwoWeekWorkoutGuidance":
        if self.kind == "rest":
            if self.intensity != "rest" or self.expected_duration_minutes != 0:
                raise ValueError(
                    "strategic rest guidance requires rest intensity and zero duration"
                )
            if self.requires_gym:
                raise ValueError("strategic rest guidance cannot require a gym")
            return self
        if self.intensity == "rest" or self.expected_duration_minutes == 0:
            raise ValueError("active strategic guidance requires active intensity and duration")
        return self


class TwoWeekNutritionGuidance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_main_meals: Literal[1, 2]
    meal_template_names: list[str] = Field(min_length=1, max_length=2)
    focus: str
    fueling_recommendations: list[str] = Field(max_length=4)
    prep_note: str | None = None

    @model_validator(mode="after")
    def validate_meal_count(self) -> "TwoWeekNutritionGuidance":
        if len(self.meal_template_names) != self.expected_main_meals:
            raise ValueError("expected_main_meals must match the supplied meal templates")
        if len({name.casefold() for name in self.meal_template_names}) != len(
            self.meal_template_names
        ):
            raise ValueError("meal templates must be distinct within a day")
        return self


class TwoWeekPlanDay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_date: date
    commitment: Literal["committed", "provisional"]
    adaptation: Literal["adaptive", "stable"]
    workout: TwoWeekWorkoutGuidance
    nutrition: TwoWeekNutritionGuidance
    rationale: str


class TwoWeekPlanProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_start: date
    window_end: date
    summary: str
    training_strategy: str
    nutrition_strategy: str
    adjustment_summary: str
    days: list[TwoWeekPlanDay] = Field(min_length=14, max_length=14)
    assumptions: list[str] = Field(max_length=8)

    @model_validator(mode="after")
    def validate_window(self) -> "TwoWeekPlanProposal":
        expected_dates = [
            self.window_start.fromordinal(self.window_start.toordinal() + offset)
            for offset in range(14)
        ]
        if self.window_end != expected_dates[-1]:
            raise ValueError("window_end must be thirteen days after window_start")
        if [day.plan_date for day in self.days] != expected_dates:
            raise ValueError("days must cover the fourteen-day window in date order")
        expected_commitments = (["committed"] * 7) + (["provisional"] * 7)
        if [day.commitment for day in self.days] != expected_commitments:
            raise ValueError(
                "the first seven days must be committed and the second week provisional"
            )
        expected_adaptation = (["adaptive"] * 2) + (["stable"] * 12)
        if [day.adaptation for day in self.days] != expected_adaptation:
            raise ValueError("days zero and one must be adaptive and the remaining horizon stable")
        return self


class TwoWeekPlanDocument(TwoWeekPlanProposal):
    anchor_date: date
    source: Literal["openai", "fallback"]


def normalize_two_week_plan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert an immutable legacy detailed horizon into the current strategic shape."""

    normalized = dict(payload)
    normalized_days: list[dict[str, Any]] = []
    for raw_day in payload.get("days", []):
        day = dict(raw_day)
        raw_workout = dict(day.get("workout") or {})
        if "requires_gym" not in raw_workout:
            text = " ".join(
                [
                    str(raw_workout.get("title") or ""),
                    str(raw_workout.get("summary") or ""),
                    *(
                        str(item.get("exercise_name") or "")
                        for item in raw_workout.get("exercises", [])
                    ),
                ]
            ).casefold()
            raw_workout["requires_gym"] = "gym" in text or any(
                marker in text for marker in ("barbell bench press", "weighted pull-up", "deadlift")
            )
        day["workout"] = {
            key: raw_workout[key]
            for key in (
                "kind",
                "intensity",
                "title",
                "expected_duration_minutes",
                "requires_gym",
                "summary",
            )
            if key in raw_workout
        }
        normalized_days.append(day)
    normalized["days"] = normalized_days
    return normalized


def parse_two_week_plan_document(payload: dict[str, Any]) -> TwoWeekPlanDocument:
    return TwoWeekPlanDocument.model_validate(normalize_two_week_plan_payload(payload))
