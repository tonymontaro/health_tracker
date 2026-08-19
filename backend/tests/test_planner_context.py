import json
from datetime import date

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.planner.context import (
    build_daily_planner_context,
    build_horizon_planner_context,
    build_nutrition_regeneration_context,
    build_profile_snapshot,
    build_workout_regeneration_context,
)
from app.services.planner.two_week import ensure_two_week_plan

TARGET = date(2026, 8, 10)


def _serialized_size(value: object) -> int:
    return len(json.dumps(value, default=str, separators=(",", ":")))


def test_ai_tasks_receive_focused_contexts(
    db: Session,
    settings: Settings,
    seeded,
) -> None:
    ensure_two_week_plan(db, settings, TARGET, use_ai=False)
    snapshot = build_profile_snapshot(db, seeded, TARGET)

    daily = build_daily_planner_context(db, seeded, snapshot, TARGET)
    horizon = build_horizon_planner_context(db, seeded, snapshot, TARGET)
    workout = build_workout_regeneration_context(db, seeded, snapshot, TARGET)
    nutrition = build_nutrition_regeneration_context(db, seeded, snapshot, TARGET)

    assert daily["receding_horizon"] is not None
    assert "full_fourteen_day_horizon" not in daily["receding_horizon"]
    assert len(daily["receding_horizon"]["next_three_days"]) == 3
    assert "yesterday_plan" not in daily
    assert "equipment" not in daily

    assert "current_inventory" not in horizon
    assert "shopping_state" not in horizon
    assert "receding_horizon" not in horizon
    assert all("ingredients" not in meal for meal in horizon["active_meal_templates"])
    assert any(
        meal["name"] == "Thursday flexible colleague meal"
        for meal in horizon["active_meal_templates"]
    )

    assert "active_meal_templates" not in workout
    assert "meal_selection_policy" not in workout
    assert "current_inventory" not in workout

    assert "active_exercise_catalog" not in nutrition
    assert "recent_training_sessions" not in nutrition
    assert "goal_progress_evidence" not in nutrition

    assert _serialized_size(daily) < 40_000
    assert _serialized_size(horizon) < 25_000
    assert _serialized_size(workout) < 20_000
    assert _serialized_size(nutrition) < 30_000
