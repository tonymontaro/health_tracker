from contextlib import nullcontext
from datetime import datetime, timedelta
from unittest.mock import Mock, call
from zoneinfo import ZoneInfo

import pytest

from app.jobs import scheduler


@pytest.mark.parametrize(
    "hour,minute,due",
    [
        (0, 0, False),
        (0, 1, False),
        (0, 4, False),
        (0, 5, True),
        (0, 6, True),
        (6, 0, True),
        (23, 55, True),
        (23, 59, True),
    ],
)
def test_scheduler_keeps_sync_and_planning_without_sending_emails(
    settings, monkeypatch, hour, minute, due
):
    current = datetime(2026, 9, 21, hour, minute, tzinfo=ZoneInfo(settings.app_timezone))

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return current.astimezone(tz)

    db = object()
    monkeypatch.setattr(scheduler, "datetime", FixedDatetime)
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: nullcontext(db))
    sync = Mock(return_value={"connections": 1})
    plan = Mock()
    finalize = Mock()
    jobs = Mock()
    jobs.attach_mock(sync, "sync")
    jobs.attach_mock(finalize, "finalize")
    jobs.attach_mock(plan, "plan")
    email = Mock(side_effect=AssertionError("Automatic emails must remain disabled"))
    monkeypatch.setattr(scheduler, "sync_all_connections", sync)
    monkeypatch.setattr(scheduler, "generate_morning_plan", plan)
    monkeypatch.setattr(scheduler, "finalize_day", finalize)
    monkeypatch.setattr(scheduler, "send_morning_email", email, raising=False)
    monkeypatch.setattr(scheduler, "send_evening_checkin", email, raising=False)

    completed = scheduler.run_due_jobs()

    sync.assert_called_once_with(db, settings)
    assert completed[0] == "strava_sync"
    assert "morning_email" not in completed and "evening_email" not in completed
    email.assert_not_called()
    if due:
        plan.assert_called_once_with(db, settings, current.date())
        finalize.assert_called_once_with(db, current.date() - timedelta(days=1))
        assert jobs.mock_calls == [
            call.sync(db, settings),
            call.finalize(db, current.date() - timedelta(days=1)),
            call.plan(db, settings, current.date()),
        ]
    else:
        plan.assert_not_called()
        finalize.assert_not_called()
