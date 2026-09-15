import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai_codex import ApprovalMode, Sandbox
from openai_codex.generated.v2_all import TurnStatus
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.services import ai
from app.services.ai import AIProviderError, AIResponseError, CodexProvider


class Answer(BaseModel):
    answer: str = Field(min_length=1)
    caution: str | None = None


@pytest.fixture
def sdk(monkeypatch):
    state = SimpleNamespace(
        account_type="chatgpt",
        text='{"answer":"Fictitious response", "caution":null}',
        status=TurnStatus.completed,
        error=None,
        hang_at=None,
        closed=0,
        requests=[],
        threads=[],
        configs=[],
        items=[],
    )

    class FakeThread:
        async def run(self, prompt, **kwargs):
            state.requests.append((prompt, kwargs))
            if state.hang_at == "turn":
                await asyncio.Event().wait()
            if state.error:
                raise state.error
            return SimpleNamespace(
                final_response=state.text, status=state.status, items=state.items, error=None
            )

    class FakeCodex:
        def __init__(self, config):
            state.configs.append(config)

        async def account(self):
            if state.hang_at == "initialize":
                await asyncio.Event().wait()
            account = (
                SimpleNamespace(root=SimpleNamespace(type=state.account_type))
                if state.account_type
                else None
            )
            return SimpleNamespace(account=account)

        async def thread_start(self, **kwargs):
            state.threads.append(kwargs)
            return FakeThread()

        async def close(self):
            state.closed += 1

    monkeypatch.setattr(ai, "AsyncCodex", FakeCodex)
    return state


def generate(settings):
    return CodexProvider(settings).generate(
        model=settings.codex_qa_model,
        instructions="Use only the supplied fictitious facts.",
        prompt="Fictitious health context.",
        response_model=Answer,
    )


def test_subscription_request_validates_json_and_closes_private_session(settings, sdk):
    answer = generate(settings)
    assert answer.answer == "Fictitious response"
    assert sdk.closed == 1
    assert sdk.threads[0]["ephemeral"] is True
    assert sdk.threads[0]["approval_mode"] == ApprovalMode.deny_all
    assert sdk.threads[0]["sandbox"] == Sandbox.read_only
    assert sdk.threads[0]["base_instructions"] == "Use only the supplied fictitious facts."
    schema = sdk.requests[0][1]["output_schema"]
    assert set(schema["required"]) == {"answer", "caution"}
    assert schema["additionalProperties"] is False
    assert not Path(sdk.configs[0].cwd).exists()


def test_runtime_configuration_isolates_personal_tools_and_api_keys(settings, sdk, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unusable-test-api-key")
    monkeypatch.setenv("CODEX_API_KEY", "unusable-test-codex-api-key")
    generate(settings)
    config = sdk.configs[0]
    assert config.codex_bin is None  # Use the SDK's version-matched runtime.
    for key in ("OPENAI_API_KEY", "OPEN_AI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"):
        assert config.env[key] == ""
    for override in (
        'forced_login_method="chatgpt"',
        "mcp_servers={}",
        "model_providers={}",
        "features.shell_tool=false",
        "features.code_mode_host=false",
        "features.plugins=false",
        "features.hooks=false",
        "features.apps=false",
        "features.memories=false",
        "features.skip_host_skill_discovery=true",
        'web_search="disabled"',
        "project_doc_max_bytes=0",
        'history.persistence="none"',
        'otel.exporter="none"',
        "notify=[]",
    ):
        assert override in config.config_overrides


@pytest.mark.parametrize("account_type", [None, "apiKey", "amazonBedrock"])
def test_rejects_missing_or_non_subscription_login_without_starting_turn(
    settings, sdk, account_type
):
    sdk.account_type = account_type
    with pytest.raises(AIProviderError, match="ChatGPT sign-in"):
        generate(settings)
    assert not sdk.requests
    assert not sdk.threads
    assert sdk.closed == 1


@pytest.mark.parametrize("text", [None, "", "not JSON", '{"answer": ""}', '{"caution":null}'])
def test_rejects_missing_malformed_or_schema_invalid_output(settings, sdk, text):
    sdk.text = text
    with pytest.raises(AIResponseError):
        generate(settings)
    assert sdk.closed == 1


def test_validation_error_does_not_echo_sensitive_output(settings, sdk):
    sdk.text = json.dumps({"answer": {"private_health_record": "secret-test-value"}})
    with pytest.raises(AIResponseError) as raised:
        generate(settings)
    assert "secret-test-value" not in str(raised.value)
    assert "private_health_record" not in str(raised.value)
    assert "answer" in str(raised.value)


@pytest.mark.parametrize("status", [TurnStatus.failed, TurnStatus.interrupted])
def test_incomplete_turn_is_not_accepted_even_with_valid_json(settings, sdk, status):
    sdk.status = status
    with pytest.raises(AIProviderError, match="did not finish"):
        generate(settings)


def test_unexpected_tool_action_discards_response(settings, sdk):
    sdk.items = [SimpleNamespace(root=SimpleNamespace(type="commandExecution"))]
    with pytest.raises(AIProviderError, match="unsupported action"):
        generate(settings)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("429 usage limit secret-test-value", "usage limit reached"),
        ("401 unauthorized secret-test-value", "ChatGPT sign-in"),
        ("Connection failure secret-test-value", "unavailable"),
    ],
)
def test_provider_errors_are_actionable_sanitized_and_not_retried(settings, sdk, message, expected):
    sdk.error = RuntimeError(message)
    with pytest.raises(AIProviderError, match=expected) as raised:
        generate(settings)
    assert "secret-test-value" not in str(raised.value)
    assert len(sdk.requests) == 1
    assert sdk.closed == 1


@pytest.mark.parametrize("hang_at", ["initialize", "turn"])
def test_timeout_closes_runtime_and_releases_capacity(settings, sdk, hang_at):
    settings.codex_timeout_seconds = 0.01
    sdk.hang_at = hang_at
    with pytest.raises(AIProviderError, match="timed out"):
        generate(settings)
    assert sdk.closed == 1
    sdk.hang_at = None
    assert generate(settings).answer
    assert sdk.closed == 2


def test_busy_provider_does_not_spawn_another_process(settings, sdk):
    assert ai._REQUEST_SLOTS.acquire(blocking=False)
    assert ai._REQUEST_SLOTS.acquire(blocking=False)
    try:
        with pytest.raises(AIProviderError, match="busy"):
            generate(settings)
        assert not sdk.configs
    finally:
        ai._REQUEST_SLOTS.release()
        ai._REQUEST_SLOTS.release()
    assert generate(settings).answer


def test_disabled_ai_does_not_start_codex(settings, sdk):
    settings.ai_enabled = False
    with pytest.raises(AIProviderError, match="disabled"):
        generate(settings)
    assert CodexProvider(settings).status()["codex_authenticated"] is False
    assert not sdk.configs


def test_missing_runtime_produces_setup_error(settings, monkeypatch):
    def missing(**kwargs):
        raise FileNotFoundError("secret-test-value")

    monkeypatch.setattr(ai, "AsyncCodex", missing)
    with pytest.raises(AIProviderError, match="Reinstall the backend dependencies"):
        generate(settings)


def test_status_checks_authentication_without_a_model_request(settings, sdk):
    assert CodexProvider(settings).status() == {
        "codex_authenticated": True,
        "codex_status": "Signed in with ChatGPT",
    }
    assert not sdk.requests
    assert sdk.closed == 1


def test_legacy_model_settings_still_work_but_api_key_is_ignored(monkeypatch):
    for key in ("CODEX_PLANNER_MODEL", "OPENAI_PLANNER_MODEL", "AI_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings(
        OPENAI_PLANNER_MODEL="legacy-model",
        OPENAI_API_KEY="unused-test-key",
        _env_file=None,
    )
    assert settings.codex_planner_model == "legacy-model"
    assert settings.ai_enabled
    assert "openai_api_key" not in settings.model_dump()
    configured = Settings(
        CODEX_PLANNER_MODEL="selected-model",
        OPENAI_PLANNER_MODEL="legacy-model",
        _env_file=None,
    )
    assert configured.codex_planner_model == "selected-model"
