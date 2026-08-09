import json
from typing import Any

from openai import OpenAI

from app.core.config import Settings
from app.schemas.plan import DailyPlanProposal

PLANNER_VERSION = "planner-v1"

SYSTEM_PROMPT = """You plan one day for a single user's personal health autopilot.
Return a schema-valid planning proposal and concise application-facing rationale.
Use only supplied meal templates and exercise catalog entries.
Use only exercises marked available_today and respect the supplied equipment state.
The user eats one or two main meals. Fruit and optional snacks are separate.
Never prescribe more than three exercises.
Gym-only work is allowed only on Saturday or Sunday.
Thursday is rest or at most very light recovery movement.
Every active exercise must have complete numeric targets for its type.
Strength needs load, sets, per-set reps, and rest. Bodyweight needs external load, sets, reps, and rest.
Running needs distance, pace in seconds per km, duration, treadmill speed when relevant, and incline.
Cycling needs duration plus power when supported, otherwise cadence and expected difficulty for calibration.
Do not invent unknown capacity, FTP, medical facts, recent results, or exact nutrition precision.
Do not progress a movement associated with pain. Change only one major training variable at a time.
Use at most one preparation action. Prefer batch cooking, inventory use, and 5-10 active minutes.
Do not provide medical diagnosis. Recommend professional help for concerning pain or symptoms.
Do not output hidden chain-of-thought. Rationale must be concise and user-facing.
"""


class OpenAIPlanner:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_key_value:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        self.settings = settings
        self.client = OpenAI(
            api_key=settings.openai_key_value,
            timeout=120,
            max_retries=0,
        )

    def generate(
        self,
        context: dict[str, Any],
        correction: dict[str, Any] | None = None,
    ) -> DailyPlanProposal:
        prompt = "PlannerContext:\n" + json.dumps(context, default=str, separators=(",", ":"))
        if correction:
            prompt += "\nThe prior candidate failed domain validation. Correct these issues:\n"
            prompt += json.dumps(correction, default=str, separators=(",", ":"))
        response = self.client.responses.parse(
            model=self.settings.openai_planner_model,
            reasoning={"effort": self.settings.openai_reasoning_effort},
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            text_format=DailyPlanProposal,
            store=False,
        )
        if response.output_parsed is None:
            raise ValueError("OpenAI returned no parsed planning proposal")
        return response.output_parsed
