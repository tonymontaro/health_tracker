"""Run a privacy-safe OpenAI Structured Outputs smoke test with fictitious data."""

import json

from openai import OpenAI

from app.core.config import get_settings
from app.schemas.api import QAResponse
from app.services.chat import QA_SYSTEM_PROMPT
from app.services.planner.openai_planner import OpenAIPlanner

SYNTHETIC_CONTEXT = {
    "synthetic_test_data": True,
    "current_date": "2030-01-07",
    "day_of_week": "Monday",
    "timezone": "Europe/Zurich",
    "profile": {
        "location": "Fictional City",
        "weight_kg": None,
        "height_cm": None,
        "age": None,
        "sex": None,
        "primary_training_goal": "General strength and comfortable aerobic exercise",
    },
    "hard_constraints": {
        "max_main_meals": 2,
        "max_exercises": 3,
        "gym_days": ["Saturday", "Sunday"],
        "office_days": ["Thursday"],
        "excluded_exercises": ["squat"],
    },
    "profile_snapshot": {
        "short_summary": "Fictitious new user with no recorded training history.",
        "recovery_status": "unknown",
        "source_quality": {"all_values": "estimated"},
    },
    "nutrition_summary_14d": {},
    "training_summary_28d": {},
    "current_inventory": [],
    "active_meal_templates": [
        {
            "name": "Chicken power bowl",
            "description": "Chicken, rice, broccoli and peppers",
            "hands_on_minutes": 18,
            "estimated_protein_g": 70,
            "estimated_fiber_g": 11,
        },
        {
            "name": "Emergency protein plate",
            "description": "Skyr, fruit, nuts and wholegrain bread",
            "hands_on_minutes": 3,
            "estimated_protein_g": 65,
            "estimated_fiber_g": 12,
        },
    ],
    "active_exercise_catalog": [
        {
            "name": "Treadmill run",
            "category": "run",
            "gym_only": False,
            "measurement_type": "distance_pace",
            "equipment_required": ["treadmill"],
            "available_today": True,
        },
        {
            "name": "Walking / easy movement",
            "category": "recovery",
            "gym_only": False,
            "measurement_type": "duration",
            "equipment_required": [],
            "available_today": True,
        },
    ],
    "equipment": [{"name": "Fictional treadmill", "category": "exercise", "available": True}],
    "upcoming_schedule_constraints": {"today": "Monday"},
}


def main() -> None:
    settings = get_settings()
    planner = OpenAIPlanner(settings)
    proposal = None
    planner_rejections: list[str] = []
    correction = None
    for _ in range(2):
        try:
            proposal = planner.generate(SYNTHETIC_CONTEXT, correction=correction)
            break
        except Exception as exc:  # noqa: BLE001 - mirrors the production fallback boundary.
            planner_rejections.append(type(exc).__name__)
            correction = {
                "errors": [f"{type(exc).__name__}: {str(exc)[:1000]}"],
                "instruction": "Return a fresh response that satisfies every schema constraint.",
            }
    plan_for_qa = (
        proposal.model_dump(mode="json")
        if proposal
        else {
            "source": "synthetic deterministic fallback",
            "nutrition": {"main_meals": 2},
            "workout": {"kind": "recovery", "duration_minutes": 20},
        }
    )
    client = OpenAI(
        api_key=settings.openai_key_value,
        timeout=120,
        max_retries=1,
    )
    qa_result = client.responses.parse(
        model=settings.openai_qa_model,
        reasoning={"effort": "low"},
        input=[
            {"role": "system", "content": QA_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "synthetic_test_data": True,
                        "question": "Why is this a conservative starting plan?",
                        "today_plan": plan_for_qa,
                        "context": SYNTHETIC_CONTEXT,
                    },
                    separators=(",", ":"),
                ),
            },
        ],
        text_format=QAResponse,
        store=False,
    )
    print(
        {
            "planner_model": settings.openai_planner_model,
            "planner_parsed": proposal is not None,
            "planner_schema_rejections": planner_rejections,
            "qa_model": settings.openai_qa_model,
            "qa_parsed": qa_result.output_parsed is not None,
            "main_meals": proposal.nutrition.expected_main_meals if proposal else None,
            "exercises": len(proposal.workout.exercises) if proposal else None,
        }
    )


if __name__ == "__main__":
    main()
