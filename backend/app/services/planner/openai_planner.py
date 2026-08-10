import json
import logging
from typing import Any

from openai import APIConnectionError, APIStatusError, OpenAI, OpenAIError

from app.core.config import Settings
from app.schemas.plan import DailyPlanProposal

PLANNER_VERSION = "planner-v1"
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You plan one day for a single user's personal health autopilot.
Return a schema-valid planning proposal and concise application-facing rationale.
Use only supplied meal templates and exercise catalog entries.
Use only exercises marked available_today and respect the supplied equipment state.
The user eats one or two main meals. Fruit and optional snacks are separate.
For every selected meal template, copy every ingredient and its quantity from active_meal_templates
into the meal ingredients. The preparation field must be a self-contained, simple recipe with
concise numbered steps. Use every listed ingredient, include cooking times and temperatures when
relevant, and explain how to portion batch recipes. Use as many steps as the recipe needs without
adding unnecessary detail. Do not require unlisted ingredients except optional water or basic
seasoning. Never return only a meal name or generic preparation advice.
Never prescribe more than three exercises.
Gym-only work is allowed only on Saturday or Sunday.
Thursday is rest or at most very light recovery movement.
Workout shape is strict. A true rest plan must use kind "rest", intensity "rest", an empty
exercises list, and zero expected duration. Never attach movement to a rest plan. Light recovery
movement must instead use kind "recovery", very-light or light intensity, one or more supplied
recovery exercises, and a positive expected duration.
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


class PlannerProviderError(RuntimeError):
    """Raised after the OpenAI SDK exhausts retries for a provider or network failure."""


class OpenAIPlanner:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_key_value:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        self.settings = settings
        self.client = OpenAI(
            api_key=settings.openai_key_value,
            timeout=120,
        )

    def generate(
        self,
        context: dict[str, Any],
        correction: dict[str, Any] | None = None,
        *,
        prompt_label: str | None = None,
    ) -> DailyPlanProposal:
        prompt = "PlannerContext:\n" + json.dumps(context, default=str, separators=(",", ":"))
        if correction:
            prompt += "\nThe prior candidate failed domain validation. Correct these issues:\n"
            prompt += json.dumps(correction, default=str, separators=(",", ":"))
        if prompt_label:
            logger.info(
                _readable_prompt_log(
                    prompt_label,
                    self.settings.openai_planner_model,
                    self.settings.openai_reasoning_effort,
                    context,
                    correction,
                )
            )
        try:
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
        except OpenAIError as exc:
            message = _provider_error_summary(exc)
            logger.warning(message)
            raise PlannerProviderError(message) from exc
        if response.output_parsed is None:
            raise ValueError("OpenAI returned no parsed planning proposal")
        return response.output_parsed


def _provider_error_summary(error: OpenAIError) -> str:
    details = ["OpenAI request failed after automatic retries"]
    if isinstance(error, APIStatusError):
        details.append(f"HTTP {error.status_code}")
        if error.request_id:
            details.append(f"request ID {error.request_id}")
        if error.status_code in {408, 409, 429} or error.status_code >= 500:
            details.append("transient provider error")
    elif isinstance(error, APIConnectionError):
        details.append("network or timeout error")
    else:
        details.append(type(error).__name__)
    return " · ".join(details)


def _readable_prompt_log(
    label: str,
    model: str,
    reasoning_effort: str,
    context: dict[str, Any],
    correction: dict[str, Any] | None,
) -> str:
    border = "=" * 88
    divider = "-" * 88
    sections = [
        "",
        border,
        f"OPENAI PROMPT · {label}",
        f"Model: {model}",
        f"Reasoning effort: {reasoning_effort}",
        divider,
        "SYSTEM PROMPT",
        SYSTEM_PROMPT.strip(),
        divider,
        "USER PROMPT · PlannerContext",
        json.dumps(context, default=str, indent=2, sort_keys=True),
    ]
    if correction:
        sections.extend(
            [
                divider,
                "USER PROMPT · Correction request",
                json.dumps(correction, default=str, indent=2, sort_keys=True),
            ]
        )
    sections.append(border)
    return "\n".join(sections)
