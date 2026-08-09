from types import SimpleNamespace

import httpx
import pytest
from openai import DEFAULT_MAX_RETRIES, InternalServerError

from app.core.config import Settings
from app.services.planner.openai_planner import (
    SYSTEM_PROMPT,
    OpenAIPlanner,
    PlannerProviderError,
    _provider_error_summary,
    _readable_prompt_log,
)


def test_readable_prompt_log_has_human_friendly_sections() -> None:
    output = _readable_prompt_log(
        "EXERCISE RECOMMENDATION REGENERATION · ATTEMPT 2",
        "test-model",
        "medium",
        {"plan_date": "2030-01-01", "history": {"completed": ["Easy run"]}},
        {"instruction": "Regenerate the workout only.", "errors": ["Use a lower load."]},
    )

    assert "OPENAI PROMPT · EXERCISE RECOMMENDATION REGENERATION · ATTEMPT 2" in output
    assert "Model: test-model" in output
    assert "Reasoning effort: medium" in output
    assert "SYSTEM PROMPT\n" + SYSTEM_PROMPT.strip() in output
    assert "USER PROMPT · PlannerContext" in output
    assert '  "history": {' in output
    assert '    "completed": [' in output
    assert "USER PROMPT · Correction request" in output
    assert '  "errors": [' in output
    assert 'A true rest plan must use kind "rest"' in output
    assert 'Light recovery\nmovement must instead use kind "recovery"' in output


def test_planner_uses_sdk_retries_and_summarizes_exhausted_provider_errors() -> None:
    planner = OpenAIPlanner(
        Settings(
            APP_ENV="test",
            OPENAI_API_KEY="test-key",
            SESSION_SECRET="test-session-secret-with-more-than-32-characters",
            _env_file=None,
        )
    )
    assert planner.client.max_retries == DEFAULT_MAX_RETRIES

    response = httpx.Response(
        520,
        request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
        headers={"x-request-id": "req_test_520"},
    )
    provider_error = InternalServerError(
        "Cloudflare origin error",
        response=response,
        body={"retryable": True},
    )

    assert _provider_error_summary(provider_error) == (
        "OpenAI request failed after automatic retries · HTTP 520 · "
        "request ID req_test_520 · transient provider error"
    )

    class FailingResponses:
        def parse(self, **kwargs):
            raise provider_error

    planner.client = SimpleNamespace(responses=FailingResponses())
    with pytest.raises(PlannerProviderError, match="HTTP 520"):
        planner.generate({}, prompt_label="TEST REGENERATION")
