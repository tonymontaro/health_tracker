from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MealNutritionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    main_meal_template_name: str
    optional_meal_template_name: str
    focus: str
    fueling_recommendations: list[str] = Field(max_length=4)

    @property
    def meal_template_names(self) -> list[str]:
        return [self.main_meal_template_name, self.optional_meal_template_name]

    @model_validator(mode="after")
    def distinct_meals(self) -> "MealNutritionSelection":
        if self.main_meal_template_name.casefold() == self.optional_meal_template_name.casefold():
            raise ValueError("The main and optional meals must be distinct")
        return self


class MealPlanSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_date: date
    nutrition: MealNutritionSelection


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
