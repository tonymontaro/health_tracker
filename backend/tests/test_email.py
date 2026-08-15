from datetime import date

import resend
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import NotificationEvent
from app.jobs.tasks import send_morning_email
from app.services.email import ResendEmailService, evening_email, morning_email
from app.services.planner.orchestrator import generate_daily_plan

PLAN = {
    "profile_snapshot": {"short_summary": "Synthetic test profile."},
    "nutrition": {
        "meal_1": {"template_name": "Chicken power bowl"},
        "meal_2": None,
        "fruits": [{"name": "Kiwi"}],
        "snacks": [{"name": "Skyr"}],
        "expected_main_meals": 1,
    },
    "workout": {"kind": "rest", "exercises": []},
    "prep_actions": [],
    "shopping": {"summary": "Nothing needed."},
}


def test_resend_service_sends_both_formats_with_idempotency(monkeypatch) -> None:
    captured: list[tuple[dict[str, object], dict[str, object] | None]] = []

    def fake_send(params, options=None):
        captured.append((params, options))
        return {"id": "email_test_123"}

    monkeypatch.setattr(resend.Emails, "send", fake_send)
    settings = Settings(
        APP_ENV="test",
        RESEND_API_KEY="re_test_only",
        RESEND_FROM="Health Autopilot <health@example.org>",
        RESEND_TO="delivered@resend.dev",
        SESSION_SECRET="test-session-secret-with-more-than-32-characters",
    )
    service = ResendEmailService(settings)
    message_id = service.send(
        "delivered@resend.dev",
        "Test subject",
        "Plain text",
        "<p>HTML</p>",
        idempotency_key="health-autopilot/morning-email/2030-01-01",
    )
    service.send(
        "delivered@resend.dev",
        "Test subject",
        "Plain text",
        "<p>HTML</p>",
        idempotency_key="health-autopilot/morning-email/2030-01-01",
    )
    service.send(
        "delivered@resend.dev",
        "Test subject",
        "Changed plain text",
        "<p>HTML</p>",
        idempotency_key="health-autopilot/morning-email/2030-01-01",
    )

    assert message_id == "email_test_123"
    assert captured[0][0] == {
        "from": "Health Autopilot <health@example.org>",
        "to": ["delivered@resend.dev"],
        "subject": "Test subject",
        "text": "Plain text",
        "html": "<p>HTML</p>",
    }
    first_key = captured[0][1]["idempotency_key"]
    assert first_key.startswith("health-autopilot/morning-email/2030-01-01/")
    assert captured[1][1]["idempotency_key"] == first_key
    assert captured[2][1]["idempotency_key"] != first_key


def test_morning_email_includes_emergency_plate_in_both_formats() -> None:
    _, text, html = morning_email(PLAN, "https://health.example.org")

    assert "Emergency option\nEmergency protein plate" in text
    assert "500 g Skyr / quark" in text
    assert "Emergency protein plate" in html
    assert "500 g Skyr / quark" in html


def test_morning_email_contains_every_exercise_and_actionable_meal_details(
    db: Session, settings: Settings, seeded
) -> None:
    target = date(2026, 8, 8)
    plan = generate_daily_plan(db, settings, target, use_ai=False)
    document = plan.current_plan_json
    exercise_names = [item["exercise_name"] for item in document["workout"]["exercises"]]

    assert len(exercise_names) == 3

    _, text, html = morning_email(document, "https://health.example.org")

    for name in exercise_names:
        assert name in text
        assert name in html
    assert document["workout"]["exercises"][0]["instructions"] in text
    assert document["workout"]["exercises"][0]["instructions"] in html
    meal_ingredients = document["nutrition"]["meal_1"]["ingredients"]
    assert len(meal_ingredients) >= 2
    for ingredient in meal_ingredients:
        assert ingredient in text
        assert ingredient in html
    assert "Ingredients:" in text
    assert "Preparation:" in text
    assert "<strong>Ingredients</strong>" in html
    assert "<strong>Preparation:</strong>" in html


def test_evening_email_includes_emergency_plate_in_both_formats() -> None:
    _, text, html = evening_email(PLAN, "https://health.example.org")

    assert "Emergency option\nEmergency protein plate" in text
    assert "65 g protein - 3 active minutes" in text
    assert "Emergency protein plate" in html
    assert "65 g protein - 3 active minutes" in html


def resend_settings(settings: Settings) -> Settings:
    return Settings(
        DATABASE_URL=settings.database_url,
        APP_ENV="test",
        RESEND_API_KEY="re_test_only",
        RESEND_FROM="Health Autopilot <health@example.org>",
        RESEND_TO="current@example.org",
        SESSION_SECRET="test-session-secret-with-more-than-32-characters",
        _env_file=None,
    )


def test_email_job_retries_legacy_sent_row_for_current_resend_recipient(
    db: Session, settings: Settings, seeded, monkeypatch
) -> None:
    target = date(2026, 8, 10)
    current_settings = resend_settings(settings)
    generate_daily_plan(db, current_settings, target, use_ai=False)
    event = NotificationEvent(
        event_type="morning_email",
        event_date=target,
        status="sent",
        metadata_json={"recipient": "owner@localhost", "subject": "Legacy delivery"},
    )
    db.add(event)
    db.commit()
    calls: list[tuple[str, str]] = []

    def fake_send(self, recipient, subject, text_body, html_body, *, idempotency_key):
        calls.append((recipient, idempotency_key))
        return "email_current_123"

    monkeypatch.setattr(ResendEmailService, "send", fake_send)

    result = send_morning_email(db, current_settings, target)

    assert calls == [("current@example.org", "health-autopilot/morning_email/2026-08-10")]
    assert result.status == "sent"
    assert result.metadata_json["provider"] == "resend"
    assert result.metadata_json["provider_message_id"] == "email_current_123"
    assert result.metadata_json["attempt_count"] == 1


def test_email_job_does_not_repeat_current_resend_delivery(
    db: Session, settings: Settings, seeded, monkeypatch
) -> None:
    target = date(2026, 8, 10)
    current_settings = resend_settings(settings)
    generate_daily_plan(db, current_settings, target, use_ai=False)
    calls = 0

    def fake_send(self, recipient, subject, text_body, html_body, *, idempotency_key):
        nonlocal calls
        calls += 1
        return "email_current_456"

    monkeypatch.setattr(ResendEmailService, "send", fake_send)

    first = send_morning_email(db, current_settings, target)
    second = send_morning_email(db, current_settings, target)

    assert first.id == second.id
    assert calls == 1
    assert second.metadata_json["attempt_count"] == 1
