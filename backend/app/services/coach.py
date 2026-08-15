import json
from typing import Any, Literal

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field

from app.core.config import Settings

COACH_SYSTEM_PROMPT = """You are Coach Forge, the consistent voice of a personal hybrid-training app.
You are demanding, direct, observant, and occasionally dryly witty. Praise must be earned and specific.
When obligations were missed, say so plainly and challenge the athlete to correct course; do not coddle.
Never insult, humiliate, threaten, moralize about body weight or food, or treat pain/illness as weakness.
Pain, alarming symptoms, and unsafe effort always override toughness. Never invent results or certainty.
Ground every statement in supplied facts. Keep the focus on useful training, recovery, and nutrition.
Write 2-4 compact sentences in one paragraph. Do not use headings or hidden chain-of-thought.
"""


class CoachMessage(BaseModel):
    message: str = Field(min_length=1, max_length=900)


def coach_message(
    settings: Settings,
    *,
    moment: Literal["workout_feedback", "morning_email", "evening_email"],
    facts: dict[str, Any],
) -> str:
    if not settings.openai_key_value:
        return _fallback_message(moment, facts)
    try:
        result = OpenAI(
            api_key=settings.openai_key_value, timeout=60, max_retries=1
        ).responses.parse(
            model=settings.openai_qa_model,
            reasoning={"effort": "low"},
            input=[
                {"role": "system", "content": COACH_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps({"moment": moment, "facts": facts}, default=str),
                },
            ],
            text_format=CoachMessage,
            store=False,
        )
        if result.output_parsed:
            return result.output_parsed.message
    except OpenAIError:
        pass
    return _fallback_message(moment, facts)


def _fallback_message(moment: str, facts: dict[str, Any]) -> str:
    if moment == "workout_feedback":
        if facts.get("pain_flag"):
            return "Work recorded. Pain is not a test of character—do not push through it. Recover, monitor it, and get professional guidance if it persists or affects movement."
        matched = int(facts.get("matched_count", 0))
        skipped = int(facts.get("skipped_count", 0))
        if matched and not skipped:
            return "Session completed and the planned work is on the board. Good—bank the result, recover properly, and be ready to earn the next progression."
        if skipped:
            return "The record is honest, but planned work was left undone. No drama and no excuses: recover what you can today, then execute the next obligation properly."
        return "Work recorded. Useful consistency beats heroic storytelling; recover well and bring measurable execution to the next session."
    if moment == "morning_email":
        return "The plan is set. Read the targets, arrange the food, and execute without renegotiating with yourself halfway through the day."
    return "Time to close the ledger. Record what you actually did—not what you intended—and own any gap so tomorrow's plan can be better."
