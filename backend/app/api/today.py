from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_auth, require_write_auth
from app.core.config import Settings, get_settings
from app.db.models import (
    DailyFoodLog,
    DailyPlan,
    DailyWorkoutLog,
    NutritionEntry,
    StravaConnection,
    UserProfile,
    WorkoutEntry,
)
from app.db.session import get_db
from app.schemas.api import (
    ManualNutritionRequest,
    ReplaceRecommendationRequest,
    WorkoutCompletionRequest,
)
from app.schemas.food_log import FoodLogRequest, FoodLogResponse
from app.schemas.workout_log import (
    WorkoutLogAnalysisResponse,
    WorkoutLogRequest,
    WorkoutLogResponse,
    WorkoutLogSubmissionRequest,
)
from app.services.emergency_plate import EMERGENCY_PLATE
from app.services.food_log import (
    FoodLogExtractionError,
    process_daily_food_log,
    serialize_food_log,
)
from app.services.history import replace_recommendation, serialize_nutrition, serialize_workout
from app.services.inventory import adjust_nutrition_entry_inventory
from app.services.metrics import recalculate_derived_summary
from app.services.nutrition_regeneration import (
    NutritionRegenerationError,
    regenerate_nutrition,
)
from app.services.planner.orchestrator import generate_daily_plan
from app.services.strava import (
    StravaIntegrationError,
    sync_connection_for_date,
)
from app.services.workout_log import (
    WorkoutLogExtractionError,
    analyze_daily_workout_log,
    process_daily_workout_log,
    serialize_workout_log,
)
from app.services.workout_regeneration import (
    WorkoutRegenerationError,
    regenerate_workout,
)

router = APIRouter(prefix="/today", tags=["today"])


def local_today(settings: Settings) -> date:
    return datetime.now(ZoneInfo(settings.app_timezone)).date()


def _plan(db: Session, settings: Settings) -> DailyPlan:
    return generate_daily_plan(db, settings, local_today(settings))


def _status_maps(db: Session, target: date) -> tuple[dict[str, Any], dict[str, Any]]:
    nutrition = {
        item.planned_recommendation_id: serialize_nutrition(item)
        for item in db.scalars(select(NutritionEntry).where(NutritionEntry.entry_date == target))
        if item.planned_recommendation_id is not None
    }
    workouts = {
        item.planned_recommendation_id: serialize_workout(item)
        for item in db.scalars(select(WorkoutEntry).where(WorkoutEntry.entry_date == target))
        if item.planned_recommendation_id is not None
    }
    return nutrition, workouts


def _food_log(db: Session, target: date) -> DailyFoodLog | None:
    return db.scalar(select(DailyFoodLog).where(DailyFoodLog.log_date == target))


def _actual_nutrition(db: Session, target: date) -> list[dict[str, Any]]:
    return [
        serialize_nutrition(entry)
        for entry in db.scalars(
            select(NutritionEntry)
            .where(
                NutritionEntry.entry_date == target,
                NutritionEntry.food_log_id.is_not(None),
            )
            .order_by(NutritionEntry.created_at)
        )
    ]


def _workout_log(db: Session, target: date) -> DailyWorkoutLog | None:
    return db.scalar(select(DailyWorkoutLog).where(DailyWorkoutLog.log_date == target))


def _actual_workouts(db: Session, target: date) -> list[dict[str, Any]]:
    return [
        serialize_workout(entry)
        for entry in db.scalars(
            select(WorkoutEntry)
            .where(
                WorkoutEntry.entry_date == target,
                WorkoutEntry.planned_recommendation_id.is_(None),
            )
            .order_by(WorkoutEntry.created_at)
        )
    ]


def _reject_if_food_log_exists(db: Session, target: date) -> None:
    if _food_log(db, target):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Today's food text is authoritative. Re-analyze it or correct the entry in History.",
        )


def _reject_if_workout_log_exists(db: Session, target: date) -> None:
    if _workout_log(db, target):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Today's workout text is authoritative. Re-analyze it or correct the entry "
                "in History."
            ),
        )


@router.get("")
def get_today(
    _: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    plan = _plan(db, settings)
    document = plan.current_plan_json
    nutrition_status, workout_status = _status_maps(db, plan.plan_date)
    return {
        "date": plan.plan_date.isoformat(),
        "source": document["source"],
        "current_status": document["profile_snapshot"]["short_summary"],
        "recovery_status": document["profile_snapshot"]["recovery_status"],
        "nutrition": document["nutrition"],
        "workout": document["workout"],
        "next_action": document["prep_actions"][0] if document["prep_actions"] else None,
        "shopping": document["shopping"],
        "nutrition_status": nutrition_status,
        "workout_status": workout_status,
        "food_log": serialize_food_log(_food_log(db, plan.plan_date)),
        "actual_nutrition": _actual_nutrition(db, plan.plan_date),
        "workout_log": serialize_workout_log(_workout_log(db, plan.plan_date)),
        "actual_workouts": _actual_workouts(db, plan.plan_date),
        "emergency_plate": EMERGENCY_PLATE,
    }


@router.get("/details")
def get_today_details(
    _: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    plan = _plan(db, settings)
    nutrition_status, workout_status = _status_maps(db, plan.plan_date)
    return {
        "plan": plan.current_plan_json,
        "original_plan": plan.original_plan_json,
        "nutrition_entries": [
            *nutrition_status.values(),
            *_actual_nutrition(db, plan.plan_date),
        ],
        "workout_entries": list(workout_status.values()),
        "food_log": serialize_food_log(_food_log(db, plan.plan_date)),
        "workout_log": serialize_workout_log(_workout_log(db, plan.plan_date)),
        "actual_workouts": _actual_workouts(db, plan.plan_date),
    }


def _nutrition_entry(db: Session, recommendation_id: str, target: date) -> NutritionEntry:
    entry = db.scalar(
        select(NutritionEntry).where(
            NutritionEntry.entry_date == target,
            NutritionEntry.planned_recommendation_id == recommendation_id,
        )
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Nutrition recommendation not found")
    return entry


@router.post("/nutrition/{recommendation_id}/confirm")
def confirm_nutrition(
    recommendation_id: str,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    target = local_today(settings)
    _reject_if_food_log_exists(db, target)
    entry = _nutrition_entry(db, recommendation_id, target)
    if entry.status not in {"confirmed", "assumed_consumed"}:
        adjust_nutrition_entry_inventory(db, entry, direction=-1)
    entry.status = "confirmed"
    profile = db.scalar(select(UserProfile))
    if profile:
        recalculate_derived_summary(db, profile, target)
    db.commit()
    return serialize_nutrition(entry)


@router.post("/nutrition/{recommendation_id}/skip")
def skip_nutrition(
    recommendation_id: str,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    target = local_today(settings)
    _reject_if_food_log_exists(db, target)
    entry = _nutrition_entry(db, recommendation_id, target)
    if entry.status in {"confirmed", "assumed_consumed"}:
        adjust_nutrition_entry_inventory(db, entry, direction=1)
    entry.status = "skipped"
    profile = db.scalar(select(UserProfile))
    if profile:
        recalculate_derived_summary(db, profile, target)
    db.commit()
    return serialize_nutrition(entry)


@router.post("/nutrition/{recommendation_id}/replace")
def replace_nutrition(
    recommendation_id: str,
    payload: ReplaceRecommendationRequest,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    plan = _plan(db, settings)
    _reject_if_food_log_exists(db, plan.plan_date)
    try:
        replace_recommendation(
            db, plan, recommendation_id, payload.replacement, payload.reason, "user"
        )
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return plan.current_plan_json


@router.post("/nutrition/manual", status_code=201)
def manual_nutrition(
    payload: ManualNutritionRequest,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _reject_if_food_log_exists(db, local_today(settings))
    entry = NutritionEntry(
        entry_date=local_today(settings),
        meal_slot=payload.meal_slot,
        description=payload.description,
        quantity_json=payload.quantity,
        source="manual",
        status=payload.status,
        expected=True,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return serialize_nutrition(entry)


@router.post("/nutrition/regenerate")
def regenerate_today_nutrition(
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    plan = _plan(db, settings)
    _reject_if_food_log_exists(db, plan.plan_date)
    try:
        regenerate_nutrition(db, settings, plan)
    except NutritionRegenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return plan.current_plan_json


@router.post("/nutrition/food-log", response_model=FoodLogResponse)
def record_food_log(
    payload: FoodLogRequest,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FoodLogResponse:
    target = local_today(settings)
    _plan(db, settings)
    try:
        return process_daily_food_log(db, settings, target, payload.text)
    except RuntimeError as exc:
        if str(exc) == "OPENAI_API_KEY is not configured":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Food analysis requires an OpenAI API key. Nothing was changed.",
            ) from exc
        if isinstance(exc, FoodLogExtractionError):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc
        raise


@router.post("/workout/complete")
def complete_workout(
    payload: WorkoutCompletionRequest,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict[str, Any]]:
    if not payload.results:
        raise HTTPException(status_code=422, detail="Actual performance evidence is required")
    target = local_today(settings)
    _reject_if_workout_log_exists(db, target)
    entries = list(db.scalars(select(WorkoutEntry).where(WorkoutEntry.entry_date == target)))
    changed: list[WorkoutEntry] = []
    for entry in entries:
        if entry.planned_recommendation_id in payload.results:
            actual = payload.results[entry.planned_recommendation_id]
            if not actual:
                raise HTTPException(status_code=422, detail="Actual performance cannot be empty")
            entry.actual_json = actual
            entry.difficulty_1_to_10 = payload.difficulty_1_to_10
            entry.pain_flag = payload.pain_flag
            entry.notes = payload.notes
            entry.status = "completed"
            entry.source = "manual"
            changed.append(entry)
    if not changed:
        raise HTTPException(status_code=404, detail="No matching workout recommendations")
    profile = db.scalar(select(UserProfile))
    if profile:
        recalculate_derived_summary(db, profile, target)
    db.commit()
    return [serialize_workout(item) for item in changed]


@router.post("/workout/skip")
def skip_workout(
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict[str, Any]]:
    target = local_today(settings)
    _reject_if_workout_log_exists(db, target)
    entries = list(
        db.scalars(
            select(WorkoutEntry).where(
                WorkoutEntry.entry_date == target,
                WorkoutEntry.status == "planned",
            )
        )
    )
    for entry in entries:
        entry.status = "skipped"
    db.commit()
    return [serialize_workout(item) for item in entries]


@router.post("/workout/regenerate")
def regenerate_today_workout(
    auth: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    plan = _plan(db, settings)
    connection = db.scalar(
        select(StravaConnection).where(StravaConnection.account_id == auth.account.id)
    )
    if connection is not None:
        if connection.status != "connected":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Reconnect Strava before regenerating from refreshed activity history.",
            )
        try:
            sync_connection_for_date(
                db,
                settings,
                connection,
                plan.plan_date - timedelta(days=1),
            )
        except StravaIntegrationError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Strava history refresh failed: {exc}. The workout was not regenerated.",
            ) from exc
    try:
        regenerate_workout(db, settings, plan)
    except WorkoutRegenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return plan.current_plan_json


@router.post("/workout/log/analyze", response_model=WorkoutLogAnalysisResponse)
def analyze_workout_log(
    payload: WorkoutLogRequest,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WorkoutLogAnalysisResponse:
    target = local_today(settings)
    _plan(db, settings)
    try:
        return analyze_daily_workout_log(db, settings, target, payload.text)
    except RuntimeError as exc:
        if str(exc) == "OPENAI_API_KEY is not configured":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Workout analysis requires an OpenAI API key. Nothing was changed.",
            ) from exc
        if isinstance(exc, WorkoutLogExtractionError):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc
        raise


@router.post("/workout/log", response_model=WorkoutLogResponse)
def record_workout_log(
    payload: WorkoutLogSubmissionRequest,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WorkoutLogResponse:
    target = local_today(settings)
    _plan(db, settings)
    try:
        return process_daily_workout_log(
            db,
            settings,
            target,
            payload.text,
            extraction=payload.extraction,
        )
    except WorkoutLogExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post("/workout/{recommendation_id}/replace")
def replace_workout(
    recommendation_id: str,
    payload: ReplaceRecommendationRequest,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    plan = _plan(db, settings)
    try:
        replace_recommendation(
            db, plan, recommendation_id, payload.replacement, payload.reason, "user"
        )
    except (LookupError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return plan.current_plan_json
