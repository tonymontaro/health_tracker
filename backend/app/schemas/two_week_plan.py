from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.plan import WorkoutPlanProposal


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
    workout: WorkoutPlanProposal
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
