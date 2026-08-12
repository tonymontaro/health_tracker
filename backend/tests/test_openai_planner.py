from types import SimpleNamespace

import httpx
import pytest
from openai import DEFAULT_MAX_RETRIES, InternalServerError

from app.core.config import Settings
from app.services.planner.openai_planner import (
    OpenAIPlanner,
    PlannerProviderError,
    _provider_error_summary,
)


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
