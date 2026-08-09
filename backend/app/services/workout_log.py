import json
from datetime import date
from typing import Any, Protocol
from uuid import UUID

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import DailyPlan, DailyWorkoutLog, UserProfile, WorkoutEntry
from app.schemas.workout_log import (
    ExtractedWorkout,
    WorkoutLogExtraction,
    WorkoutLogResponse,
)
from app.services.metrics import recalculate_derived_summary

WORKOUT_LOG_SYSTEM_PROMPT = """Interpret one free-text workout diary for a single calendar day.
Extract only exercise that the user says they completed. Never invent an unmentioned activity.
Split distinct exercises into separate workout records when the text supplies exercise-specific results.
Use strength for loaded resistance, bodyweight for calisthenics, run for running, bike for cycling, and recovery for walking, mobility, yoga, or similar low-intensity movement.
Preserve explicit distance, duration, load, sets, repetitions, power, heart rate, difficulty, pain, and notes.
Convert minutes to seconds and miles to kilometers. Do not estimate missing performance measurements.
Determine whether each completed workout followed one supplied recommendation based on activity type, name, and workload.
Each recommendation may be matched at most once. Do not match on a vague similarity alone.
Set did_no_workout only when the user explicitly says that no workout was completed.
Record any unit conversion or meaningful ambiguity in assumptions.
Do not diagnose, give advice, or output hidden reasoning.
"""

MUTABLE_STATUSES = {"planned", "skipped", "skipped_assumed", "skipped_by_workout_log"}


class WorkoutLogExtractionError(RuntimeError):
    pass


class WorkoutLogExtractionProvider(Protocol):
    model: str

    def extract(
        self,
        raw_text: str,
        recommendations: list[dict[str, Any]],
    ) -> WorkoutLogExtraction: ...


class WorkoutLogExtractor:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_key_value:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        self.model = settings.openai_workout_log_model
        self.client = OpenAI(
            api_key=settings.openai_key_value,
            timeout=120,
            max_retries=0,
        )

    def extract(
        self,
        raw_text: str,
        recommendations: list[dict[str, Any]],
    ) -> WorkoutLogExtraction:
        known_ids = {
            recommendation["recommendation_id"]
            for recommendation in recommendations
            if recommendation.get("recommendation_id")
        }
        correction: dict[str, Any] | None = None
        last_errors: list[str] = []
        for _ in range(2):
            payload: dict[str, Any] = {
                "workout_log_text": raw_text,
                "today_recommendations": recommendations,
            }
            if correction:
                payload["correction"] = correction
            try:
                response = self.client.responses.parse(
                    model=self.model,
                    reasoning={"effort": "low"},
                    input=[
                        {"role": "system", "content": WORKOUT_LOG_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(payload, separators=(",", ":")),
                        },
                    ],
                    text_format=WorkoutLogExtraction,
                    store=False,
                )
                extraction = response.output_parsed
                if extraction is None:
                    last_errors = ["The model returned no parsed result."]
                else:
                    last_errors = validate_extraction(extraction, known_ids)
                    if not last_errors:
                        return extraction
            except Exception as exc:  # noqa: BLE001 - one bounded provider repair is intentional.
                last_errors = [f"{type(exc).__name__}: {str(exc)[:1000]}"]
            correction = {
                "errors": last_errors,
                "instruction": (
                    "Return a fresh result that fixes every error without adding "
                    "unmentioned exercise."
                ),
            }
        raise WorkoutLogExtractionError(
            "AI could not reliably interpret the workout log. Nothing was changed."
        )


def validate_extraction(
    extraction: WorkoutLogExtraction, known_recommendation_ids: set[str]
) -> list[str]:
    errors: list[str] = []
    if extraction.did_no_workout and extraction.workouts:
        errors.append("did_no_workout cannot be true when workouts are present")
    if not extraction.did_no_workout and not extraction.workouts:
        errors.append("at least one workout is required unless the user explicitly did no workout")
    matched_ids: list[str] = []
    for workout in extraction.workouts:
        recommendation_id = workout.matched_recommendation_id
        if recommendation_id:
            matched_ids.append(recommendation_id)
            if recommendation_id not in known_recommendation_ids:
                errors.append(f"unknown recommendation ID: {recommendation_id}")
    if len(matched_ids) != len(set(matched_ids)):
        errors.append("a recommendation can be matched at most once")
    return errors


def process_daily_workout_log(
    db: Session,
    settings: Settings,
    target_date: date,
    raw_text: str,
    *,
    extractor: WorkoutLogExtractionProvider | None = None,
) -> WorkoutLogResponse:
    plan = db.scalar(select(DailyPlan).where(DailyPlan.plan_date == target_date))
    if plan is None:
        raise LookupError("Today's plan is not available")
    planned_entries = list(
        db.scalars(
            select(WorkoutEntry).where(
                WorkoutEntry.entry_date == target_date,
                WorkoutEntry.planned_recommendation_id.is_not(None),
            )
        )
    )
    eligible_entries = [
        entry
        for entry in planned_entries
        if entry.status in MUTABLE_STATUSES or entry.source == "ai_workout_log"
    ]
    recommendations = [_recommendation_context(entry) for entry in eligible_entries]
    active_extractor = extractor or WorkoutLogExtractor(settings)

    extraction = active_extractor.extract(raw_text, recommendations)
    validation_errors = validate_extraction(
        extraction,
        {str(item["recommendation_id"]) for item in recommendations if item["recommendation_id"]},
    )
    if validation_errors:
        raise WorkoutLogExtractionError("; ".join(validation_errors))

    try:
        db.scalar(select(DailyPlan).where(DailyPlan.plan_date == target_date).with_for_update())
        workout_log = db.scalar(
            select(DailyWorkoutLog).where(DailyWorkoutLog.log_date == target_date)
        )
        if workout_log is None:
            workout_log = DailyWorkoutLog(
                log_date=target_date,
                raw_text=raw_text,
                extraction_json={},
                previous_entries_json=[_entry_snapshot(entry) for entry in eligible_entries],
                model=active_extractor.model,
                status="processing",
            )
            db.add(workout_log)
            db.flush()
        else:
            _restore_previous_log_entries(db, workout_log)
            db.flush()

        planned_by_id = {
            entry.planned_recommendation_id: entry
            for entry in planned_entries
            if entry.planned_recommendation_id
        }
        matched_ids = {
            workout.matched_recommendation_id
            for workout in extraction.workouts
            if workout.matched_recommendation_id
        }
        extracted_by_id = {
            workout.matched_recommendation_id: workout
            for workout in extraction.workouts
            if workout.matched_recommendation_id
        }
        eligible_ids = {
            entry.planned_recommendation_id
            for entry in eligible_entries
            if entry.planned_recommendation_id
        }
        for recommendation_id in eligible_ids:
            entry = planned_by_id[recommendation_id]
            workout = extracted_by_id.get(recommendation_id)
            entry.workout_log_id = workout_log.id
            entry.source = "ai_workout_log"
            if workout:
                entry.actual_json = _actual_payload(workout)
                entry.difficulty_1_to_10 = workout.difficulty_1_to_10
                entry.pain_flag = workout.pain_flag
                entry.notes = workout.notes
                entry.status = "completed"
            else:
                entry.actual_json = None
                entry.difficulty_1_to_10 = None
                entry.pain_flag = False
                entry.notes = None
                entry.status = "skipped_by_workout_log"

        for workout in extraction.workouts:
            if workout.matched_recommendation_id:
                continue
            db.add(
                WorkoutEntry(
                    entry_date=target_date,
                    exercise_name=workout.workout_name,
                    prescription_json={
                        "exercise_type": workout.exercise_type,
                        "source": "free_text_workout_log",
                    },
                    actual_json=_actual_payload(workout),
                    difficulty_1_to_10=workout.difficulty_1_to_10,
                    status="completed",
                    source="ai_workout_log",
                    pain_flag=workout.pain_flag,
                    notes=workout.notes,
                    workout_log_id=workout_log.id,
                )
            )

        workout_log.raw_text = raw_text
        workout_log.extraction_json = extraction.model_dump(mode="json")
        workout_log.model = active_extractor.model
        workout_log.status = "processed"
        profile = db.scalar(select(UserProfile))
        if profile:
            recalculate_derived_summary(db, profile, target_date)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return WorkoutLogResponse(
        date=target_date.isoformat(),
        raw_text=raw_text,
        extraction=extraction,
        skipped_recommendation_ids=sorted(eligible_ids - matched_ids),
        matched_recommendation_ids=sorted(matched_ids),
    )


def serialize_workout_log(workout_log: DailyWorkoutLog | None) -> dict[str, Any] | None:
    if workout_log is None:
        return None
    return {
        "id": str(workout_log.id),
        "date": workout_log.log_date.isoformat(),
        "raw_text": workout_log.raw_text,
        "extraction": workout_log.extraction_json,
        "model": workout_log.model,
        "status": workout_log.status,
        "updated_at": workout_log.updated_at.isoformat(),
    }


def _restore_previous_log_entries(db: Session, workout_log: DailyWorkoutLog) -> None:
    snapshots = {snapshot["entry_id"]: snapshot for snapshot in workout_log.previous_entries_json}
    entries = list(
        db.scalars(select(WorkoutEntry).where(WorkoutEntry.workout_log_id == workout_log.id))
    )
    for entry in entries:
        if entry.planned_recommendation_id is None:
            db.delete(entry)
            continue
        snapshot = snapshots.get(str(entry.id))
        if snapshot is None:
            continue
        entry.status = snapshot["status"]
        entry.source = snapshot["source"]
        entry.actual_json = snapshot.get("actual")
        entry.difficulty_1_to_10 = snapshot.get("difficulty_1_to_10")
        entry.pain_flag = bool(snapshot.get("pain_flag"))
        entry.notes = snapshot.get("notes")
        prior_log_id = snapshot.get("workout_log_id")
        entry.workout_log_id = UUID(prior_log_id) if prior_log_id else None


def _entry_snapshot(entry: WorkoutEntry) -> dict[str, Any]:
    return {
        "entry_id": str(entry.id),
        "status": entry.status,
        "source": entry.source,
        "actual": entry.actual_json,
        "difficulty_1_to_10": entry.difficulty_1_to_10,
        "pain_flag": entry.pain_flag,
        "notes": entry.notes,
        "workout_log_id": str(entry.workout_log_id) if entry.workout_log_id else None,
    }


def _recommendation_context(entry: WorkoutEntry) -> dict[str, Any]:
    return {
        "recommendation_id": entry.planned_recommendation_id,
        "exercise_name": entry.exercise_name,
        "prescription": entry.prescription_json,
        "status": entry.status,
    }


def _actual_payload(workout: ExtractedWorkout) -> dict[str, Any]:
    payload = workout.model_dump(
        mode="json",
        exclude={
            "matched_recommendation_id",
            "match_confidence",
            "difficulty_1_to_10",
            "pain_flag",
            "notes",
        },
        exclude_none=True,
    )
    payload["match_confidence"] = workout.match_confidence
    return payload
