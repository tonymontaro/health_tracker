from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class WorkoutLogRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Workout log text cannot be blank")
        return value


class ExtractedWorkout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workout_name: str = Field(min_length=1, max_length=160)
    exercise_type: Literal["strength", "bodyweight", "run", "bike", "recovery"]
    duration_seconds: int | None = Field(default=None, gt=0, le=43200)
    distance_km: float | None = Field(default=None, gt=0, le=500)
    load_kg: float | None = Field(default=None, ge=0, le=500)
    external_load_kg: float | None = Field(default=None, ge=0, le=200)
    sets: int | None = Field(default=None, ge=1, le=100)
    reps_per_set: list[int] | None = Field(default=None, min_length=1, max_length=100)
    average_power_watts: float | None = Field(default=None, ge=0, le=3000)
    average_heartrate_bpm: float | None = Field(default=None, ge=20, le=260)
    difficulty_1_to_10: int | None = Field(default=None, ge=1, le=10)
    pain_flag: bool
    notes: str | None = Field(default=None, max_length=2000)
    matched_recommendation_id: str | None
    match_confidence: float = Field(ge=0, le=1)
    assumptions: list[str] = Field(max_length=10)

    @model_validator(mode="after")
    def require_performance_evidence(self) -> "ExtractedWorkout":
        evidence = (
            self.duration_seconds,
            self.distance_km,
            self.load_kg,
            self.external_load_kg,
            self.sets,
            self.reps_per_set,
        )
        if not any(value is not None for value in evidence):
            raise ValueError("a workout requires at least one measurable actual result")
        if self.reps_per_set and any(reps <= 0 or reps > 1000 for reps in self.reps_per_set):
            raise ValueError("reps_per_set values must be between 1 and 1000")
        return self


class WorkoutLogExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    did_no_workout: bool
    workouts: list[ExtractedWorkout] = Field(max_length=20)
    summary: str = Field(min_length=1, max_length=1000)
    assumptions: list[str] = Field(max_length=20)


class WorkoutLogAnalysisResponse(BaseModel):
    raw_text: str
    extraction: WorkoutLogExtraction


class WorkoutLogSubmissionRequest(WorkoutLogRequest):
    extraction: WorkoutLogExtraction


class WorkoutLogResponse(BaseModel):
    date: str
    raw_text: str
    extraction: WorkoutLogExtraction
    skipped_recommendation_ids: list[str]
    matched_recommendation_ids: list[str]
