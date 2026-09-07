from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.two_week_plan import TwoWeekNutritionGuidance


class MealPlanSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_date: date
    nutrition: TwoWeekNutritionGuidance


class MealPlanProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    days: list[MealPlanSelection] = Field(min_length=14, max_length=14)

    @model_validator(mode="after")
    def consecutive_weeks(self) -> "MealPlanProposal":
        start = self.days[0].plan_date
        if start.weekday() != 0 or [day.plan_date for day in self.days] != [
            start + timedelta(days=offset) for offset in range(14)
        ]:
            raise ValueError("Meals must cover two consecutive Monday-Sunday weeks in date order")
        return self
