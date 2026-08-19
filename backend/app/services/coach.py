import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal, TypedDict, cast

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import NotificationEvent, WorkoutCoachFeedback

CoachMoment = Literal["workout_feedback", "morning_email", "evening_email"]
StoryKind = Literal["none", "humorous", "motivational"]


class RecentCoachMessage(TypedDict):
    date: str
    moment: str
    message_excerpt: str
    story_kind: StoryKind
    story_topic: str | None


class StoredCoachStyle(TypedDict):
    story_kind: StoryKind
    story_topic: str | None


STORY_COOLDOWN_DAYS = 4
RECENT_COACH_HISTORY_DAYS = 30
RECENT_COACH_MESSAGES_LIMIT = 10
RECENT_STORY_TOPICS_LIMIT = 12
MESSAGE_EXCERPT_LENGTH = 320

COACH_CHARACTER_PROMPT = """You are Coach Forge, the consistent voice of a personal hybrid-training app.
Coach a serious athlete like a dedicated professional: demanding, direct, observant, invested, and
occasionally dryly witty. Praise must be earned and specific. Criticism must identify the useful next
action, not merely deliver a verdict.
When obligations were missed, say so plainly and challenge the athlete to correct course; do not coddle.
Never insult, humiliate, threaten, moralize about body weight or food, or treat pain/illness as weakness.
Pain, alarming symptoms, and unsafe effort always override toughness. Never invent results or certainty.
Ground every statement in supplied facts. Keep the focus on useful training, recovery, and nutrition.
"""

COACH_SYSTEM_PROMPT = f"""{COACH_CHARACTER_PROMPT}
Feedback and the next useful action are always the substance. Most messages must contain no story.
Use a brief dry joke or playful comparison occasionally when it feels natural, never as filler and never
at the athlete's expense. Keep pain, illness, injury, and safety messages serious.
The supplied style object controls stories. When story_allowed is false, do not tell an anecdote or story.
When it is true, a story is still optional and should be used only when it sharpens a relevant lesson or
motivation. Any story must fit in one or two short sentences. Never imply that you personally witnessed or
experienced an invented event. Frame invented mini-stories clearly as hypothetical illustrations rather
than real events. Do not reuse or closely paraphrase a recent message, joke, image, or story topic supplied
in recent_messages or recent_story_topics.
Return story_kind as none unless the message contains an actual short story or anecdote; a one-line joke
or comparison alone is not a story. When a story is used, return a concise story_topic that can prevent
future repetition. Otherwise return story_topic as null.
Write 2-4 compact sentences in one paragraph. Do not use headings or hidden chain-of-thought.
"""


class CoachMessage(BaseModel):
    message: str = Field(min_length=1, max_length=900)
    story_kind: StoryKind
    story_topic: str | None = Field(max_length=120)

    @model_validator(mode="after")
    def validate_story_metadata(self) -> "CoachMessage":
        if self.story_kind == "none" and self.story_topic is not None:
            raise ValueError("story_topic must be null when no story is used")
        if self.story_kind != "none" and not self.story_topic:
            raise ValueError("story_topic is required when a story is used")
        return self


def coach_style_context(
    db: Session,
    target_date: date,
) -> dict[str, Any]:
    recent_history = _recent_coach_messages(db, target_date)
    recent_messages = recent_history[:RECENT_COACH_MESSAGES_LIMIT]
    cooldown_start = target_date - timedelta(days=STORY_COOLDOWN_DAYS)
    recent_story_dates = [
        date.fromisoformat(item["date"])
        for item in recent_history
        if item["story_kind"] in {"humorous", "motivational"}
    ]
    story_allowed = not any(
        cooldown_start <= item_date <= target_date for item_date in recent_story_dates
    )
    recent_story_topics = list(
        dict.fromkeys(
            item["story_topic"] for item in recent_history if item["story_topic"] is not None
        )
    )[:RECENT_STORY_TOPICS_LIMIT]
    return {
        "story_allowed": story_allowed,
        "story_cooldown_days": STORY_COOLDOWN_DAYS,
        "recent_story_topics": recent_story_topics,
        "recent_messages": recent_messages,
    }


def coach_response(
    settings: Settings,
    *,
    moment: CoachMoment,
    facts: dict[str, Any],
    style: dict[str, Any] | None = None,
) -> CoachMessage:
    style_context = style or {
        "story_allowed": False,
        "story_cooldown_days": STORY_COOLDOWN_DAYS,
        "recent_story_topics": [],
        "recent_messages": [],
    }
    if not settings.openai_key_value:
        return _fallback_response(moment, facts)
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
                    "content": json.dumps(
                        {"moment": moment, "facts": facts, "style": style_context},
                        default=str,
                    ),
                },
            ],
            text_format=CoachMessage,
            store=False,
        )
        if result.output_parsed:
            response = result.output_parsed
            if _story_contract_is_valid(response, facts, style_context):
                return response
    except (OpenAIError, ValidationError):
        pass
    return _fallback_response(moment, facts)


def coach_message(
    settings: Settings,
    *,
    moment: CoachMoment,
    facts: dict[str, Any],
) -> str:
    return coach_response(settings, moment=moment, facts=facts).message


def _recent_coach_messages(db: Session, target_date: date) -> list[RecentCoachMessage]:
    window_start = target_date - timedelta(days=RECENT_COACH_HISTORY_DAYS)
    messages: list[tuple[date, datetime, str, str, StoryKind, str | None]] = []

    feedback_rows = db.scalars(
        select(WorkoutCoachFeedback).where(
            WorkoutCoachFeedback.feedback_date.between(window_start, target_date)
        )
    )
    for feedback_row in feedback_rows:
        style = _stored_style(feedback_row.context_snapshot_json)
        messages.append(
            (
                feedback_row.feedback_date,
                feedback_row.created_at,
                "workout_feedback",
                feedback_row.message,
                style["story_kind"],
                style["story_topic"],
            )
        )

    email_rows = db.scalars(
        select(NotificationEvent).where(
            NotificationEvent.event_date.between(window_start, target_date),
            NotificationEvent.event_type.in_(("morning_email", "evening_email")),
            NotificationEvent.status == "sent",
        )
    )
    for email_row in email_rows:
        note = email_row.metadata_json.get("coach_note")
        if not isinstance(note, str) or not note.strip():
            continue
        style = _stored_style(email_row.metadata_json)
        messages.append(
            (
                email_row.event_date,
                email_row.sent_at or datetime.combine(email_row.event_date, time.min, tzinfo=UTC),
                email_row.event_type,
                note,
                style["story_kind"],
                style["story_topic"],
            )
        )

    messages.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [
        {
            "date": message_date.isoformat(),
            "moment": moment,
            "message_excerpt": _message_excerpt(message),
            "story_kind": story_kind,
            "story_topic": story_topic,
        }
        for message_date, _, moment, message, story_kind, story_topic in messages
    ]


def _stored_style(payload: dict[str, Any]) -> StoredCoachStyle:
    style = payload.get("coach_style")
    if not isinstance(style, dict):
        return {"story_kind": "none", "story_topic": None}
    raw_story_kind = style.get("story_kind")
    story_kind = (
        cast(StoryKind, raw_story_kind)
        if raw_story_kind in {"none", "humorous", "motivational"}
        else "none"
    )
    story_topic = style.get("story_topic")
    if not isinstance(story_topic, str) or not story_topic.strip():
        story_topic = None
    return {"story_kind": story_kind, "story_topic": story_topic}


def _message_excerpt(message: str) -> str:
    compact = " ".join(message.split())
    if len(compact) <= MESSAGE_EXCERPT_LENGTH:
        return compact
    return f"{compact[: MESSAGE_EXCERPT_LENGTH - 3].rstrip()}..."


def _story_contract_is_valid(
    response: CoachMessage,
    facts: dict[str, Any],
    style: dict[str, Any],
) -> bool:
    if response.story_kind == "none":
        return True
    actual_status = facts.get("actual_status")
    pain_recorded = bool(
        facts.get("pain_flag")
        or facts.get("pain_recorded")
        or (isinstance(actual_status, dict) and actual_status.get("pain_recorded"))
    )
    if not style.get("story_allowed") or pain_recorded:
        return False
    story_topic = response.story_topic.casefold() if response.story_topic else ""
    recent_topics = {
        str(topic).casefold()
        for topic in style.get("recent_story_topics", [])
        if isinstance(topic, str)
    }
    return story_topic not in recent_topics


def _fallback_response(moment: str, facts: dict[str, Any]) -> CoachMessage:
    if moment == "workout_feedback":
        if facts.get("pain_flag"):
            message = "Work recorded. Pain is not a test of character - do not push through it. Recover, monitor it, and get professional guidance if it persists or affects movement."
            return CoachMessage(message=message, story_kind="none", story_topic=None)
        matched = int(facts.get("matched_count", 0))
        skipped = int(facts.get("skipped_count", 0))
        if matched and not skipped:
            message = "Session completed and the planned work is on the board. Good - bank the result, recover properly, and be ready to earn the next progression."
            return CoachMessage(message=message, story_kind="none", story_topic=None)
        if skipped:
            message = "The record is honest, but planned work was left undone. No drama and no excuses: recover what you can today, then execute the next obligation properly."
            return CoachMessage(message=message, story_kind="none", story_topic=None)
        message = "Work recorded. Useful consistency beats heroic storytelling; recover well and bring measurable execution to the next session."
        return CoachMessage(message=message, story_kind="none", story_topic=None)
    if moment == "morning_email":
        message = "The plan is set. Read the targets, arrange the food, and execute without renegotiating with yourself halfway through the day."
        return CoachMessage(message=message, story_kind="none", story_topic=None)
    message = "Time to close the ledger. Record what you actually did - not what you intended - and own any gap so tomorrow's plan can be better."
    return CoachMessage(message=message, story_kind="none", story_topic=None)
