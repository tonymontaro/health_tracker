import json
import logging
from typing import Any

from openai import OpenAI, OpenAIError

from app.core.config import Settings
from app.schemas.two_week_plan import TwoWeekPlanProposal
from app.services.planner.openai_planner import PlannerProviderError, _provider_error_summary

TWO_WEEK_PLANNER_VERSION = "two-week-planner-v1"
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You create a rolling receding-horizon health plan for one user.
Return exactly fourteen consecutive days beginning on planning_window.window_start.

The architecture has three layers:
1. Days zero through thirteen are the AI planning horizon. Use all fourteen days to balance training,
recovery, meal variety, preparation, and fueling instead of making isolated daily decisions.
2. Days zero through six are the committed user-facing horizon. Supply exact, measurable workout
prescriptions and exact meal-template selections for these days. Days seven through thirteen are
provisional but must still be complete enough to guide later replanning.
3. Days zero and one are the adaptation zone. Adjust them when recorded completion, skipped work,
difficulty, pain, nutrition adherence, recovery evidence, or schedule context warrants it. Never
invent sleep, soreness, appetite, fatigue, or schedule changes that were not supplied.

When previous_plan is present, preserve its overlapping dates as closely as safety and recent evidence
allow. The adaptation zone can change responsively. Keep days two through six stable unless new
evidence creates a clear reason to alter them. Reconsider the provisional second week more freely.
Explain material changes in adjustment_summary and each affected day's concise rationale.

Use only supplied active meal templates and exercise catalog entries. Use only exercises marked
available_today, respect equipment availability, and never prescribe more than the profile maximum.
Gym-only work is allowed only on a configured gym day that is Saturday or Sunday. Thursday is rest
or very-light recovery. A true rest day has kind rest, rest intensity, no exercises, and zero duration.
Every active exercise needs complete numeric targets for its type. Strength needs load, sets, per-set
reps, and rest. Bodyweight needs external load, sets, reps, and rest. Running needs distance, pace,
and duration. Cycling needs duration plus power when supported, otherwise cadence. Recovery needs
duration. Do not progress a painful movement. Change only one major training variable at a time.

Choose one or two distinct main meal templates per day, respecting allergies and the meal limit.
Favor variety, practical preparation, protein, fiber, produce, and the training demand across the
full horizon. Include concrete fueling recommendations when training demand makes timing or extra
carbohydrate/protein useful. Do not assume missing ingredients cannot be purchased.

Do not invent capacity, medical facts, recent results, or false precision. Do not provide diagnosis.
Do not output hidden chain-of-thought. Keep summaries and rationales concise and user-facing.
"""


class OpenAITwoWeekPlanner:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_key_value:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_key_value, timeout=120)

    def generate(
        self,
        context: dict[str, Any],
        correction: dict[str, Any] | None = None,
    ) -> TwoWeekPlanProposal:
        prompt = "RecedingHorizonContext:\n" + json.dumps(
            context, default=str, separators=(",", ":")
        )
        if correction:
            prompt += "\nThe prior candidate failed validation. Correct these issues:\n"
            prompt += json.dumps(correction, default=str, separators=(",", ":"))
        logger.info(
            "OpenAI receding-horizon request · model=%s · reasoning=%s · correction=%s",
            self.settings.openai_planner_model,
            self.settings.openai_reasoning_effort,
            correction is not None,
        )
        try:
            response = self.client.responses.parse(
                model=self.settings.openai_planner_model,
                reasoning={"effort": self.settings.openai_reasoning_effort},
                input=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                text_format=TwoWeekPlanProposal,
                store=False,
            )
        except OpenAIError as exc:
            message = _provider_error_summary(exc)
            logger.warning(message)
            raise PlannerProviderError(message) from exc
        if response.output_parsed is None:
            raise ValueError("OpenAI returned no parsed receding-horizon plan")
        return response.output_parsed
