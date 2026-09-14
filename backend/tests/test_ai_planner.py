from contextlib import nullcontext
from types import SimpleNamespace

import httpx
import pytest
from openai import DEFAULT_MAX_RETRIES, InternalServerError

from app.core.config import Settings
from app.services.ai import AIProviderError, _provider_error_summary
from app.services.planner.ai_planner import AIPlanner


def test_planner_uses_sdk_retries_and_summarizes_exhausted_provider_errors(monkeypatch) -> None:
    planner = AIPlanner(
        Settings(
            APP_ENV="test",
            OPENAI_API_KEY="test-key",
            SESSION_SECRET="test-session-secret-with-more-than-32-characters",
            _env_file=None,
        )
    )

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

    def client(**kwargs):
        assert kwargs["max_retries"] == DEFAULT_MAX_RETRIES
        return nullcontext(SimpleNamespace(responses=FailingResponses()))

    monkeypatch.setattr("app.services.ai.OpenAI", client)
    with pytest.raises(AIProviderError, match="HTTP 520"):
        planner.generate({}, prompt_label="TEST REGENERATION")
