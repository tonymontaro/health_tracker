"""Provider boundary for validated, task-specific AI responses."""

import json
from copy import deepcopy
from typing import Any, Literal

import httpx
from openai import APIConnectionError, APIStatusError, OpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

from app.core.config import AITask, Settings

ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]


class AIConfigurationError(RuntimeError):
    pass


class AIProviderError(RuntimeError):
    """A provider failed without returning a usable response; safe to log."""


class AISchemaError(ValueError):
    """A response failed validation; contains no provider body or input values."""


def generate_structured[T: BaseModel](
    settings: Settings,
    *,
    task: AITask,
    system_prompt: str,
    user_prompt: str,
    response_model: type[T],
    reasoning_effort: ReasoningEffort = "low",
    timeout: float = 120,
    max_retries: int = 2,
) -> T:
    if not settings.ai_enabled:
        raise AIConfigurationError(
            "The selected AI provider is not configured")
    try:
        if settings.ai_provider == "ollama":
            return _ollama_response(settings, task, system_prompt, user_prompt, response_model)
        with OpenAI(
            api_key=settings.openai_key_value, timeout=timeout, max_retries=max_retries
        ) as client:
            response = client.responses.parse(
                model=settings.ai_model(task),
                reasoning={"effort": reasoning_effort},
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                text_format=response_model,
                store=False,
            )
        if response.output_parsed is None:
            raise AISchemaError("The model returned no structured result")
        return response.output_parsed
    except OpenAIError as exc:
        raise AIProviderError(_provider_error_summary(exc)) from None
    except ValidationError as exc:
        # Include field locations and error types for the bounded repair attempt,
        # never invalid values, unexpected field names, or validator exception context.
        errors = [
            {
                "loc": error["loc"][:-1] if error["type"] == "extra_forbidden" else error["loc"],
                "type": error["type"],
            }
            for error in exc.errors(include_url=False, include_context=False, include_input=False)
        ]
        raise AISchemaError(
            "Structured response failed validation: " + json.dumps(errors)
        ) from None


def _ollama_response[T: BaseModel](
    settings: Settings,
    task: AITask,
    system_prompt: str,
    user_prompt: str,
    response_model: type[T],
) -> T:
    schema = response_model.model_json_schema()
    message_api = [
        {
            "role": "system",
            "content": system_prompt
            + "\nReturn only JSON matching this schema:\n"
            + json.dumps(schema, separators=(",", ":")),
        },
        {"role": "user", "content": user_prompt},
    ]
    payload = {
        "model": settings.ai_model(task),
        "messages": message_api,
        "format": _ollama_format_schema(schema),
        "stream": False,
        "think": settings.ollama_planner_think if task == "planner" else settings.ollama_think,
        "truncate": False,
        "shift": False,
        "keep_alive": "10m",
        "options": {
            "num_ctx": settings.ollama_num_ctx,
            "num_predict": settings.ollama_num_predict,
        },
    }
    try:
        # Do not inherit HTTP proxies or attach the hosted provider's credentials.
        # Local requests have no transport retries or automatic cloud fallback.
        with httpx.Client(
            timeout=httpx.Timeout(settings.ollama_timeout_seconds, connect=10),
            trust_env=False,
        ) as client:
            response = client.post(
                settings.ollama_base_url + "/api/chat", json=payload)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        hint = " Check that the configured model has been pulled." if status == 404 else ""
        raise AIProviderError(
            f"Ollama request failed: HTTP {status}.{hint}") from None
    except httpx.RequestError:
        raise AIProviderError(
            "Ollama is unreachable or the request timed out") from None
    try:
        result = response.json()
    except ValueError:
        raise AISchemaError(
            "Ollama returned an invalid JSON response") from None
    if not isinstance(result, dict) or result.get("error"):
        raise AISchemaError("Ollama returned an invalid response envelope")
    if result.get("done") is not True or result.get("done_reason") != "stop":
        raise AISchemaError(
            "Ollama did not complete the response; check context and output limits")
    message = result.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise AISchemaError("Ollama returned no response content")
    # Thinking is a separate field and must never become application data.
    return response_model.model_validate_json(message["content"])


def _ollama_format_schema(schema: dict[str, Any]) -> dict[str, Any]:
    # llama.cpp can reject maxLength >= 2000 while compiling JSON grammars.
    # Keep the complete schema in the prompt and enforce it with Pydantic.
    # https://github.com/ggml-org/llama.cpp/issues/27087
    grammar_schema = deepcopy(schema)

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            maximum = node.get("maxLength")
            if node.get("type") == "string" and isinstance(maximum, int) and maximum >= 2000:
                del node["maxLength"]
            for key, value in node.items():
                if key not in {"default", "const", "enum", "examples"}:
                    visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(grammar_schema)
    return grammar_schema


def _provider_error_summary(error: OpenAIError) -> str:
    details = ["OpenAI request failed after automatic retries"]
    if isinstance(error, APIStatusError):
        details.append(f"HTTP {error.status_code}")
        if error.request_id:
            details.append(f"request ID {error.request_id}")
        if error.status_code in {408, 409, 429} or error.status_code >= 500:
            details.append("transient provider error")
    elif isinstance(error, APIConnectionError):
        details.append("network or timeout error")
    else:
        details.append(type(error).__name__)
    return " · ".join(details)
