import json
from contextlib import nullcontext
from copy import deepcopy
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from sqlalchemy import select

from app.api.profile import get_runtime_settings
from app.api.today import _status_maps
from app.core.config import Settings
from app.db.models import (
    DailyFoodLog,
    DailyWorkoutLog,
    NutritionEntry,
    PlanningRun,
    WorkoutCoachFeedback,
    WorkoutEntry,
)
from app.schemas.plan import DailyPlanDocument
from app.schemas.workout_log import WorkoutLogExtraction
from app.services import ai
from app.services.chat import ask_about_plan
from app.services.food_log import FoodLogExtractionError, process_daily_food_log
from app.services.history import serialize_workout
from app.services.meal_planning import ensure_meal_weeks
from app.services.planner.fallback import build_fallback_plan
from app.services.planner.orchestrator import generate_daily_plan
from app.services.planner.two_week import latest_two_week_plan
from app.services.planner.two_week_fallback import build_fallback_two_week_plan
from app.services.workout_log import WorkoutLogExtractionError, process_daily_workout_log
from app.services.workout_regeneration import regenerate_workout


class Measurement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_seconds: int = Field(gt=0)
    pain_flag: bool


@pytest.fixture
def ollama_settings(settings):
    settings.ai_provider = "ollama"
    return settings


@pytest.fixture
def ollama_server(monkeypatch):
    real_client = httpx.Client

    def install(handler):
        def client(**kwargs):
            return real_client(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(ai.httpx, "Client", client)

    return install


def generate(settings, task="workout_log"):
    return ai.generate_structured(
        settings,
        task=task,
        system_prompt="Extract only recorded facts.",
        user_prompt="Walked for 10 minutes. No pain.",
        response_model=Measurement,
    )


def envelope(content='{"duration_seconds":600,"pain_flag":false}', **overrides):
    return {
        "done": True,
        "done_reason": "stop",
        "message": {"content": content, "thinking": "Private reasoning is ignored."},
        **overrides,
    }


@pytest.mark.parametrize("task", ["planner", "qa", "food_log", "workout_log"])
def test_ollama_request_uses_schema_limits_and_no_hosted_credentials(
    ollama_settings, ollama_server, monkeypatch, task
):
    ollama_settings.openai_api_key = SecretStr("hosted-secret-must-not-be-sent")
    monkeypatch.setenv("HTTP_PROXY", "http://invalid-proxy.invalid")

    def no_openai(**kwargs):
        pytest.fail("Ollama mode must not instantiate the OpenAI client")

    monkeypatch.setattr(ai, "OpenAI", no_openai)
    requests = []

    def respond(request):
        requests.append(request)
        body = json.loads(request.content)
        assert str(request.url) == "http://127.0.0.1:11434/api/chat"
        assert "authorization" not in request.headers
        assert "hosted-secret" not in request.content.decode()
        assert body["model"] == "qwen3.8:27b-q4_K_M"
        assert body["format"] == Measurement.model_json_schema()
        assert body["stream"] is False
        assert body["truncate"] is False
        assert body["shift"] is False
        assert body["think"] is (task == "planner")
        assert body["options"] == {"num_ctx": 16384, "num_predict": 8192}
        assert request.extensions["timeout"]["read"] == 600
        assert request.extensions["timeout"]["connect"] == 10
        assert "Extract only recorded facts." in body["messages"][0]["content"]
        assert body["messages"][1]["content"] == "Walked for 10 minutes. No pain."
        return httpx.Response(200, json=envelope())

    ollama_server(respond)
    result = generate(ollama_settings, task)
    assert result.model_dump() == {"duration_seconds": 600, "pain_flag": False}
    assert len(requests) == 1


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"error": "sensitive provider response"},
        envelope(done=False),
        envelope(done_reason="length"),
        envelope(message=None),
        envelope(message={"content": 123}),
        envelope(""),
        envelope("```json\n{}\n```"),
        envelope('{"duration_seconds":-1,"pain_flag":false}'),
        envelope('{"duration_seconds":"sensitive provider response","pain_flag":false}'),
        envelope('{"duration_seconds":600,"pain_flag":false,"unexpected":"private"}'),
    ],
)
def test_ollama_rejects_incomplete_or_invalid_results_without_exposing_content(
    ollama_settings, ollama_server, payload
):
    ollama_server(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(ai.AISchemaError) as exc:
        generate(ollama_settings)
    assert "sensitive provider response" not in str(exc.value)
    assert "private" not in str(exc.value)


@pytest.mark.parametrize("status", [400, 404, 500, 503])
def test_ollama_http_errors_are_sanitized_and_never_retried(ollama_settings, ollama_server, status):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json={"error": "private prompt echoed by server"})

    ollama_server(respond)
    with pytest.raises(ai.AIProviderError, match=f"HTTP {status}") as exc:
        generate(ollama_settings)
    assert "private" not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_ollama_connection_failure_is_sanitized(ollama_settings, ollama_server, error_type):
    def respond(request):
        raise error_type("private request contents", request=request)

    ollama_server(respond)
    with pytest.raises(ai.AIProviderError, match="unreachable or the request timed out"):
        generate(ollama_settings)


def test_ollama_rejects_non_json_envelope(ollama_settings, ollama_server):
    ollama_server(lambda request: httpx.Response(200, text="private server output"))
    with pytest.raises(ai.AISchemaError, match="invalid JSON response"):
        generate(ollama_settings)


@pytest.mark.parametrize("notes_length", [2000, 2001])
def test_ollama_workout_schema_compiles_without_relaxing_application_validation(
    ollama_settings, ollama_server, notes_length
):
    original_schema = WorkoutLogExtraction.model_json_schema()
    grammar_schema = deepcopy(original_schema)
    del grammar_schema["$defs"]["ExtractedWorkout"]["properties"]["notes"]["anyOf"][0]["maxLength"]
    result = {
        "did_no_workout": False,
        "workouts": [
            {
                "workout_name": "Walk",
                "exercise_type": "recovery",
                "duration_seconds": 600,
                "pain_flag": False,
                "notes": "x" * notes_length,
                "matched_recommendation_id": None,
                "match_confidence": 0,
                "assumptions": [],
            }
        ],
        "summary": "Walked for ten minutes.",
        "assumptions": [],
    }

    def respond(request):
        body = json.loads(request.content)
        assert body["format"] == grammar_schema
        prompt_schema = json.loads(body["messages"][0]["content"].split("schema:\n", 1)[1])
        assert prompt_schema == original_schema
        return httpx.Response(200, json=envelope(json.dumps(result)))

    ollama_server(respond)
    expectation = (
        pytest.raises(ai.AISchemaError, match="string_too_long")
        if notes_length > 2000
        else nullcontext()
    )
    with expectation:
        extraction = ai.generate_structured(
            ollama_settings,
            task="workout_log",
            system_prompt="Extract the synthetic walk.",
            user_prompt="Walked for ten minutes.",
            response_model=WorkoutLogExtraction,
        )
        assert extraction.workouts[0].notes == result["workouts"][0]["notes"]
    assert WorkoutLogExtraction.model_json_schema() == original_schema


@pytest.mark.parametrize("task", ["planner", "qa", "food_log", "workout_log"])
def test_openai_retains_task_models_reasoning_and_disabled_storage(settings, monkeypatch, task):
    settings.openai_api_key = SecretStr("test-key")
    captured = {}

    def parse(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(output_parsed=Measurement(duration_seconds=600, pain_flag=False))

    monkeypatch.setattr(
        ai,
        "OpenAI",
        lambda **kwargs: nullcontext(SimpleNamespace(responses=SimpleNamespace(parse=parse))),
    )
    assert generate(settings, task).duration_seconds == 600
    assert captured["model"] == getattr(settings, f"openai_{task}_model")
    assert captured["store"] is False
    assert captured["reasoning"] == {"effort": "low"}
    assert captured["text_format"] is Measurement


def test_local_configuration_needs_no_key_and_settings_report_active_model(settings):
    assert settings.ai_provider == "openai"
    assert settings.ai_enabled is False
    with pytest.raises(ai.AIConfigurationError):
        generate(settings)
    settings.ai_provider = "ollama"
    assert settings.ai_enabled is True
    runtime = get_runtime_settings(_=None, settings=settings)
    assert runtime["ai_provider"] == "ollama"
    assert runtime["ai_configured"] is True
    assert runtime["openai_configured"] is False
    for task in ("planner", "qa", "food_log", "workout_log"):
        assert runtime[f"{task}_model"] == settings.ollama_model


@pytest.mark.parametrize(
    "overrides",
    [
        {"AI_PROVIDER": "unknown"},
        {"OLLAMA_BASE_URL": "ftp://localhost"},
        {"OLLAMA_BASE_URL": "http://localhost:11434/v1"},
        {"OLLAMA_BASE_URL": "http://user:password@localhost:11434"},
        {"OLLAMA_TIMEOUT_SECONDS": 0},
        {"OLLAMA_NUM_CTX": 0},
        {"OLLAMA_NUM_PREDICT": -1},
        {"OLLAMA_MODEL": ""},
    ],
)
def test_invalid_provider_configuration_is_rejected(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_local_daily_and_horizon_planning_preserve_meals_and_provider_provenance(
    db, seeded, ollama_settings, ollama_server
):
    target = date(2026, 8, 10)
    weeks = ensure_meal_weeks(db, ollama_settings, target, use_ai=False)
    saved_meals = [deepcopy(week.plan_json) for week in weeks]
    daily = build_fallback_plan(db, target)
    horizon = build_fallback_two_week_plan(db, seeded, target, None)
    calls = []

    def respond(request):
        title = json.loads(request.content)["format"]["title"]
        calls.append(title)
        proposal = {"DailyPlanProposal": daily, "TwoWeekPlanProposal": horizon}[title]
        return httpx.Response(200, json=envelope(proposal.model_dump_json()))

    ollama_server(respond)
    plan = generate_daily_plan(db, ollama_settings, target)
    document = DailyPlanDocument.model_validate(plan.current_plan_json)
    assert document.source == "ollama"
    assert calls == ["TwoWeekPlanProposal", "DailyPlanProposal"]
    run = db.get(PlanningRun, plan.planning_run_id)
    assert run.status == "succeeded"
    assert run.model == ollama_settings.ollama_model
    assert latest_two_week_plan(db, target).source == "ollama"
    original = deepcopy(plan.original_plan_json)
    regenerate_workout(db, ollama_settings, plan)
    assert plan.current_plan_json["source"] == "ollama"
    assert plan.original_plan_json == original
    assert plan.current_plan_json["nutrition"] == original["nutrition"]
    assert [week.plan_json for week in weeks] == saved_meals


def test_local_workout_extraction_repairs_before_mutation_and_preserves_actuals(
    db, seeded, ollama_settings, ollama_server
):
    target = date(2026, 8, 10)
    plan = generate_daily_plan(db, ollama_settings, target, use_ai=False)
    original = deepcopy(plan.original_plan_json)
    planned = db.scalar(select(WorkoutEntry).where(WorkoutEntry.entry_date == target))
    calls = []

    def respond(request):
        body = json.loads(request.content)
        if body["format"]["title"] == "CoachMessage":
            return httpx.Response(
                200,
                json=envelope(
                    json.dumps(
                        {
                            "message": "Pain was recorded. Keep the next session easy.",
                            "story_kind": "none",
                            "story_topic": None,
                        }
                    )
                ),
            )
        payload = json.loads(body["messages"][1]["content"])
        calls.append(payload)
        assert db.scalar(select(DailyWorkoutLog)) is None
        assert planned.actual_json is None
        result = {
            "did_no_workout": False,
            "workouts": [
                {
                    "workout_name": planned.exercise_name,
                    "exercise_type": "recovery",
                    "duration_seconds": 600,
                    "difficulty_1_to_10": 2,
                    "pain_flag": True,
                    "notes": "Knee pain was recorded.",
                    "matched_recommendation_id": "unknown-id"
                    if len(calls) == 1
                    else planned.planned_recommendation_id,
                    "match_confidence": 1,
                    "assumptions": [],
                }
            ],
            "summary": "Ten minutes recorded with knee pain.",
            "assumptions": [],
        }
        return httpx.Response(200, json=envelope(json.dumps(result)))

    ollama_server(respond)
    result = process_daily_workout_log(
        db, ollama_settings, target, "Completed ten minutes, difficulty 2, with knee pain."
    )
    assert len(calls) == 2
    assert "unknown recommendation ID" in calls[1]["correction"]["errors"][0]
    assert result.matched_recommendation_ids == [planned.planned_recommendation_id]
    assert db.scalar(select(DailyWorkoutLog)).model == ollama_settings.ollama_model
    assert db.scalar(select(WorkoutCoachFeedback)).model == ollama_settings.ollama_model
    assert plan.original_plan_json == original
    _, today_workouts = _status_maps(db, target)
    history_workout = serialize_workout(planned)
    assert today_workouts[planned.planned_recommendation_id] == history_workout
    assert planned.actual_json["duration_seconds"] == 600
    assert planned.pain_flag is True
    assert planned.difficulty_1_to_10 == 2


@pytest.mark.parametrize("kind", ["food", "workout"])
@pytest.mark.parametrize("failure", ["http", "timeout", "incomplete", "schema"])
def test_failed_local_diary_reanalysis_preserves_existing_records(
    db, seeded, ollama_settings, ollama_server, kind, failure
):
    target = date(2026, 8, 10)
    plan = generate_daily_plan(db, ollama_settings, target, use_ai=False)
    if kind == "food":
        result = {
            "ate_nothing": True,
            "meals": [],
            "summary": "No food consumed.",
            "assumptions": [],
        }
        process, error, log_model = process_daily_food_log, FoodLogExtractionError, DailyFoodLog
    else:
        result = {
            "did_no_workout": True,
            "workouts": [],
            "summary": "No workout completed.",
            "assumptions": [],
        }
        process, error, log_model = (
            process_daily_workout_log,
            WorkoutLogExtractionError,
            DailyWorkoutLog,
        )

    def respond(request):
        if json.loads(request.content)["format"]["title"] == "CoachMessage":
            return httpx.Response(503)
        return httpx.Response(200, json=envelope(json.dumps(result)))

    ollama_server(respond)
    process(db, ollama_settings, target, "Nothing today.")
    log = db.scalar(select(log_model))
    assert log.model == ollama_settings.ollama_model
    before = deepcopy(log.extraction_json)
    statuses = [
        (entry.id, entry.status)
        for model in (WorkoutEntry, NutritionEntry)
        for entry in db.scalars(select(model))
    ]
    original = deepcopy(plan.original_plan_json)
    calls = []

    def fail(request):
        calls.append(request)
        if failure == "http":
            return httpx.Response(400, json={"error": "private prompt echoed by server"})
        if failure == "timeout":
            raise httpx.ReadTimeout("private prompt echoed by server", request=request)
        if failure == "schema":
            return httpx.Response(200, json=envelope('{"private":"prompt"}'))
        return httpx.Response(200, json=envelope(done_reason="length"))

    ollama_server(fail)
    expected_detail = {
        "http": "HTTP 400",
        "timeout": "unreachable or the request timed out",
        "incomplete": "check context and output limits",
        "schema": "Structured response failed validation",
    }[failure]
    with pytest.raises(error, match=expected_detail) as exc:
        process(db, ollama_settings, target, "A revised diary.")
    assert "Nothing was changed" in str(exc.value)
    assert "private" not in str(exc.value)
    assert len(calls) == (1 if failure in {"http", "timeout"} else 2)
    db.refresh(log)
    assert log.extraction_json == before
    assert log.raw_text == "Nothing today."
    assert plan.original_plan_json == original
    assert statuses == [
        (entry.id, entry.status)
        for model in (WorkoutEntry, NutritionEntry)
        for entry in db.scalars(select(model))
    ]
    if kind == "workout":
        assert db.scalar(select(WorkoutCoachFeedback)).model == "deterministic-fallback"


def test_local_qa_uses_provider_and_does_not_save_failed_responses(
    db, seeded, ollama_settings, ollama_server
):
    from app.db.models import ChatMessage

    target = date(2026, 8, 10)
    generate_daily_plan(db, ollama_settings, target, use_ai=False)
    ollama_server(
        lambda request: httpx.Response(
            200,
            json=envelope(
                json.dumps(
                    {
                        "answer": "Follow the saved recovery targets.",
                        "proposed_change": None,
                        "caution": None,
                    }
                )
            ),
        )
    )
    message = ask_about_plan(db, ollama_settings, "What is the focus?", target)
    assert message.answer == "Follow the saved recovery targets."
    ollama_server(lambda request: httpx.Response(503))
    with pytest.raises(ai.AIProviderError):
        ask_about_plan(db, ollama_settings, "And tomorrow?", target)
    assert len(list(db.scalars(select(ChatMessage)))) == 1
