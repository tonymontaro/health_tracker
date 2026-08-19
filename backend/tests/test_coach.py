import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import NotificationEvent, WorkoutCoachFeedback
from app.services import coach as coach_service
from app.services.chat import QA_SYSTEM_PROMPT
from app.services.coach import (
    COACH_CHARACTER_PROMPT,
    CoachMessage,
    coach_response,
    coach_style_context,
)

TARGET = date(2026, 8, 19)


def test_coach_style_blocks_daily_stories_and_supplies_compact_recent_context(
    db: Session,
) -> None:
    db.add_all(
        [
            WorkoutCoachFeedback(
                feedback_date=TARGET - timedelta(days=2),
                message="A short story about patient hill work. Keep building.",
                model="test-model",
                context_snapshot_json={
                    "coach_style": {
                        "story_allowed": True,
                        "story_kind": "motivational",
                        "story_topic": "patient hill work",
                    }
                },
            ),
            NotificationEvent(
                event_type="morning_email",
                event_date=TARGET - timedelta(days=1),
                sent_at=datetime(2026, 8, 18, 6, 0, tzinfo=UTC),
                status="sent",
                metadata_json={
                    "coach_note": "Yesterday's direct coaching note without a story.",
                    "coach_style": {
                        "story_allowed": False,
                        "story_kind": "none",
                        "story_topic": None,
                    },
                },
            ),
        ]
    )
    db.commit()

    style = coach_style_context(db, TARGET)

    assert style["story_allowed"] is False
    assert style["story_cooldown_days"] == 4
    assert style["recent_story_topics"] == ["patient hill work"]
    assert [item["moment"] for item in style["recent_messages"]] == [
        "morning_email",
        "workout_feedback",
    ]
    assert all(len(item["message_excerpt"]) <= 320 for item in style["recent_messages"])


def test_story_becomes_optional_after_cooldown_but_topic_remains_for_deduplication(
    db: Session,
) -> None:
    db.add(
        WorkoutCoachFeedback(
            feedback_date=TARGET - timedelta(days=5),
            message="An older story about laying one sound brick at a time.",
            model="test-model",
            context_snapshot_json={
                "coach_style": {
                    "story_allowed": True,
                    "story_kind": "motivational",
                    "story_topic": "one sound brick",
                }
            },
        )
    )
    db.commit()

    style = coach_style_context(db, TARGET)

    assert style["story_allowed"] is True
    assert style["recent_story_topics"] == ["one sound brick"]


def test_ai_coach_receives_story_controls_and_returns_structured_metadata(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeResponses:
        def parse(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                output_parsed=CoachMessage(
                    message=(
                        "The work was completed cleanly. Picture two runners at sunrise: one races the "
                        "warm-up, while the other saves the fire for the work that counts. Be the second "
                        "runner when you recover today."
                    ),
                    story_kind="motivational",
                    story_topic="two sunrise runners",
                )
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.responses = FakeResponses()

    monkeypatch.setattr(coach_service, "OpenAI", FakeOpenAI)
    settings = Settings(
        APP_ENV="test",
        OPENAI_API_KEY="test-key",
        SESSION_SECRET="test-session-secret-with-more-than-32-characters",
        _env_file=None,
    )
    style = {
        "story_allowed": True,
        "story_cooldown_days": 4,
        "recent_story_topics": ["old lighthouse"],
        "recent_messages": [
            {
                "date": "2026-08-18",
                "moment": "morning_email",
                "message_excerpt": "Do the useful work before negotiating with yourself.",
                "story_kind": "none",
                "story_topic": None,
            }
        ],
    }

    response = coach_response(
        settings,
        moment="workout_feedback",
        facts={"matched_count": 1, "skipped_count": 0, "pain_flag": False},
        style=style,
    )

    request_payload = json.loads(captured["input"][1]["content"])
    assert response.story_kind == "motivational"
    assert response.story_topic == "two sunrise runners"
    assert request_payload["style"] == style
    assert "Most messages must contain no story" in captured["input"][0]["content"]
    assert captured["text_format"] is CoachMessage
    assert captured["store"] is False


def test_plan_qa_uses_the_same_coach_character() -> None:
    assert COACH_CHARACTER_PROMPT in QA_SYSTEM_PROMPT
    assert "Use dry humor sparingly" in QA_SYSTEM_PROMPT
    assert "Decide for yourself" in QA_SYSTEM_PROMPT
    assert "the athlete does not need to ask" in QA_SYSTEM_PROMPT
    assert "explicitly asks" not in QA_SYSTEM_PROMPT


def test_ai_story_during_cooldown_is_rejected(monkeypatch) -> None:
    class FakeResponses:
        def parse(self, **kwargs):
            return SimpleNamespace(
                output_parsed=CoachMessage(
                    message="The lighthouse story returns. Execute today's plan.",
                    story_kind="motivational",
                    story_topic="old lighthouse",
                )
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr(coach_service, "OpenAI", FakeOpenAI)
    settings = Settings(
        APP_ENV="test",
        OPENAI_API_KEY="test-key",
        SESSION_SECRET="test-session-secret-with-more-than-32-characters",
        _env_file=None,
    )

    response = coach_response(
        settings,
        moment="morning_email",
        facts={"plan_summary": "Easy aerobic training."},
        style={
            "story_allowed": False,
            "recent_story_topics": ["old lighthouse"],
            "recent_messages": [],
        },
    )

    assert response.story_kind == "none"
    assert response.story_topic is None
    assert "lighthouse" not in response.message


def test_fallback_keeps_pain_feedback_serious() -> None:
    fallback_settings = Settings(
        APP_ENV="test",
        OPENAI_API_KEY=None,
        SESSION_SECRET="test-session-secret-with-more-than-32-characters",
        _env_file=None,
    )
    response = coach_response(
        fallback_settings,
        moment="workout_feedback",
        facts={"pain_flag": True, "matched_count": 1, "skipped_count": 0},
        style={"story_allowed": True},
    )

    assert response.story_kind == "none"
    assert response.story_topic is None
    assert "do not push through it" in response.message
