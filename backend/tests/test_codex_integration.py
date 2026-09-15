import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.today import local_today
from app.core.config import get_settings
from app.core.security import token_digest
from app.db.models import (
    ApiToken,
    ChatMessage,
    DailyFoodLog,
    DailyWorkoutLog,
    NutritionEntry,
    WorkoutEntry,
)
from app.db.session import get_db
from app.main import app
from app.schemas.api import QAResponse
from app.schemas.food_log import FoodLogExtraction
from app.schemas.plan import DailyPlanDocument
from app.schemas.workout_log import WorkoutLogExtraction
from app.services.ai import AIProviderError, AIResponseError, CodexProvider
from app.services.food_log import FoodLogExtractor
from app.services.planner.codex_planner import CodexPlanner
from app.services.planner.fallback import build_fallback_plan
from app.services.planner.orchestrator import generate_daily_plan
from app.services.workout_log import WorkoutLogExtractor


@pytest.fixture
def owner(db, settings, seeded):
    target = local_today(settings)
    plan = generate_daily_plan(db, settings, target, use_ai=False)
    token = "codex-test-owner"
    db.add(
        ApiToken(
            account_id=seeded.account_id, name="test", token_hash=token_digest(token, settings)
        )
    )
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings
    yield SimpleNamespace(target=target, plan=plan, headers={"Authorization": f"Bearer {token}"})
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "failure", [AIProviderError("Codex usage limit reached."), AIResponseError("Invalid response.")]
)
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/today/nutrition/food-log", {"text": "I ate a banana."}),
        ("/today/workout/log/analyze", {"text": "I walked for 20 minutes."}),
        ("/today/questions", {"question": "Explain the plan."}),
    ],
)
def test_ai_endpoint_failure_preserves_records_and_returns_clear_error(
    db, owner, monkeypatch, path, payload, failure
):
    before_plan = deepcopy(owner.plan.original_plan_json)
    before_food = [
        (r.id, r.status, deepcopy(r.quantity_json)) for r in db.scalars(select(NutritionEntry))
    ]
    before_workout = [
        (r.id, r.status, deepcopy(r.actual_json)) for r in db.scalars(select(WorkoutEntry))
    ]
    calls = []

    def fail(self, **kwargs):
        calls.append(kwargs)
        raise failure

    monkeypatch.setattr(CodexProvider, "generate", fail)

    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/v1" + path, headers=owner.headers, json=payload)

    result = asyncio.run(request())
    assert result.status_code == (503 if isinstance(failure, AIProviderError) else 502)
    assert result.json()["detail"]
    assert len(calls) == (
        2 if isinstance(failure, AIResponseError) and "questions" not in path else 1
    )
    assert owner.plan.original_plan_json == before_plan
    assert owner.plan.current_plan_json == before_plan
    assert [
        (r.id, r.status, r.quantity_json) for r in db.scalars(select(NutritionEntry))
    ] == before_food
    assert [
        (r.id, r.status, r.actual_json) for r in db.scalars(select(WorkoutEntry))
    ] == before_workout
    assert db.scalar(select(DailyFoodLog.id)) is None
    assert db.scalar(select(DailyWorkoutLog.id)) is None
    assert db.scalar(select(ChatMessage.id)) is None


@pytest.mark.parametrize(
    ("extractor_type", "response_model", "data", "args"),
    [
        (
            FoodLogExtractor,
            FoodLogExtraction,
            {"ate_nothing": True, "meals": [], "summary": "No food consumed.", "assumptions": []},
            ("I ate nothing.", [], []),
        ),
        (
            WorkoutLogExtractor,
            WorkoutLogExtraction,
            {
                "did_no_workout": True,
                "workouts": [],
                "summary": "No workout completed.",
                "assumptions": [],
            },
            ("I did no workout.", []),
        ),
    ],
)
def test_diary_schema_repair_uses_codex_with_the_original_context(
    settings, monkeypatch, extractor_type, response_model, data, args
):
    calls = []

    def generate(self, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise AIResponseError("Missing required fields.")
        return response_model.model_validate(data)

    monkeypatch.setattr(CodexProvider, "generate", generate)
    result = extractor_type(settings).extract(*args)
    assert result.model_dump() == data
    assert len(calls) == 2
    assert all(c["response_model"] is response_model and args[0] in c["prompt"] for c in calls)
    assert "Missing required fields" in calls[1]["prompt"]


def test_planner_uses_shared_codex_provider_and_preserves_provider_errors(settings, monkeypatch):
    error = AIProviderError("Codex usage limit reached.")

    def fail(self, **kwargs):
        assert kwargs["model"] == settings.codex_planner_model
        assert kwargs["effort"] == settings.codex_reasoning_effort
        assert "Thursday is rest" in kwargs["instructions"]
        assert "Correct these issues" in kwargs["prompt"]
        raise error

    monkeypatch.setattr(CodexProvider, "generate", fail)
    with pytest.raises(AIProviderError) as raised:
        CodexPlanner(settings).generate({}, correction={"errors": ["example"]})
    assert raised.value is error


def test_chat_success_uses_codex_and_preserves_the_original_plan(db, settings, owner, monkeypatch):
    original = deepcopy(owner.plan.original_plan_json)

    def generate(self, **kwargs):
        assert kwargs["response_model"] is QAResponse
        assert kwargs["model"] == settings.codex_qa_model
        return QAResponse(answer="A conservative test plan.", proposed_change=None, caution=None)

    monkeypatch.setattr(CodexProvider, "generate", generate)

    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post(
                "/api/v1/today/questions",
                headers=owner.headers,
                json={"question": "Explain the plan."},
            )

    result = asyncio.run(request())
    assert result.status_code == 200
    assert result.json()["answer"] == "A conservative test plan."
    assert db.scalar(select(ChatMessage)).answer == result.json()["answer"]
    assert owner.plan.original_plan_json == original


def test_settings_report_codex_login_without_exposing_secrets(owner, monkeypatch):
    monkeypatch.setattr(
        CodexProvider,
        "status",
        lambda self: {"codex_authenticated": True, "codex_status": "Signed in with ChatGPT"},
    )

    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            unauthenticated = await client.get("/api/v1/settings")
            authenticated = await client.get("/api/v1/settings", headers=owner.headers)
            return unauthenticated, authenticated

    unauthenticated, authenticated = asyncio.run(request())
    assert unauthenticated.status_code == 401
    assert authenticated.json()["ai_provider"] == "codex"
    assert authenticated.json()["codex_authenticated"] is True
    assert not any("key" in k or "token" in k or "secret" in k for k in authenticated.json())
    assert "openai_configured" not in authenticated.json()


def test_regenerating_a_legacy_plan_preserves_original_openai_history(
    db, settings, owner, monkeypatch
):
    from app.services.workout_regeneration import regenerate_workout

    legacy = deepcopy(owner.plan.original_plan_json)
    legacy["source"] = "openai"
    owner.plan.original_plan_json = legacy
    owner.plan.current_plan_json = deepcopy(legacy)
    db.commit()
    assert DailyPlanDocument.model_validate(legacy).source == "openai"
    candidate = build_fallback_plan(db, owner.target)
    monkeypatch.setattr(CodexPlanner, "generate", lambda self, *args, **kwargs: candidate)
    result = regenerate_workout(db, settings, owner.plan)
    assert result.original_plan_json == legacy
    assert result.current_plan_json["source"] == "codex"
    assert result.current_plan_json["nutrition"] == legacy["nutrition"]
