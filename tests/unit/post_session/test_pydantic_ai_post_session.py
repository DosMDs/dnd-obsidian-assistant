"""S11-03 Pydantic AI extraction adapter tests (no Ollama, no network)."""

from __future__ import annotations

import inspect
from typing import Any

import openai
import pytest
from pydantic_ai.exceptions import AgentRunError, ModelAPIError, ModelHTTPError
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from dnd_assistant.application.post_session_extraction import (
    ExtractionFailureReason,
    PostSessionExtractionError,
    build_post_session_extraction_request,
)
from dnd_assistant.application.pydantic_ai_post_session import (
    PydanticAIPostSessionExtractionModel,
)
from dnd_assistant.domain.post_session_extraction import PostSessionExtraction
from tests.unit.post_session.extraction_helpers import (
    make_claim,
    make_extraction,
    make_prepared_input,
)


def _request():
    return build_post_session_extraction_request(make_prepared_input())


def _function_model(behaviour: Any) -> tuple[FunctionModel, dict[str, Any]]:
    seen: dict[str, Any] = {"calls": 0}

    def fn(messages: list[Any], info: Any) -> ModelResponse:
        seen["calls"] += 1
        seen["function_tools"] = tuple(info.function_tools)
        seen["output_tools"] = tuple(tool.name for tool in info.output_tools)
        return behaviour(messages, info)

    return FunctionModel(fn), seen


def _raise(exc: BaseException) -> Any:
    def behaviour(messages: list[Any], info: Any) -> ModelResponse:
        raise exc

    return behaviour


def _valid_output(messages: list[Any], info: Any) -> ModelResponse:
    extraction = make_extraction(claims=(make_claim(),))
    return ModelResponse(
        parts=[
            ToolCallPart(
                info.output_tools[0].name,
                extraction.model_dump(mode="json"),
            )
        ]
    )


# ── Happy path / zero project tools ───────────────────────────────────────


def test_adapter_returns_typed_extraction() -> None:
    model, seen = _function_model(_valid_output)
    adapter = PydanticAIPostSessionExtractionModel(model=model)
    result = adapter.extract(_request())
    assert isinstance(result, PostSessionExtraction)
    assert result.claims[0].claim_id == "c1"
    assert seen["calls"] == 1


def test_adapter_exposes_no_project_action_tools() -> None:
    model, seen = _function_model(_valid_output)
    adapter = PydanticAIPostSessionExtractionModel(model=model)
    adapter.extract(_request())
    # Zero project/function tools; only the framework output schema mechanism.
    assert seen["function_tools"] == ()
    assert seen["output_tools"] == ("final_result",)


def test_adapter_api_has_no_caller_tool_surface() -> None:
    assert set(inspect.signature(PydanticAIPostSessionExtractionModel.__init__).parameters) == {
        "self",
        "model",
    }
    assert set(inspect.signature(PydanticAIPostSessionExtractionModel.extract).parameters) == {
        "self",
        "request",
    }


# ── Retry / request limit ────────────────────────────────────────────────


def test_output_retries_disabled_single_request() -> None:
    def bad(messages: list[Any], info: Any) -> ModelResponse:
        return ModelResponse(parts=[TextPart("not a json object")])

    model, seen = _function_model(bad)
    adapter = PydanticAIPostSessionExtractionModel(model=model)
    with pytest.raises(PostSessionExtractionError) as exc_info:
        adapter.extract(_request())
    assert exc_info.value.reason is ExtractionFailureReason.INVALID_STRUCTURED_OUTPUT
    assert seen["calls"] == 1


def test_unexpected_output_preserves_cause() -> None:
    def bad(messages: list[Any], info: Any) -> ModelResponse:
        return ModelResponse(parts=[TextPart("nope")])

    model, _ = _function_model(bad)
    adapter = PydanticAIPostSessionExtractionModel(model=model)
    with pytest.raises(PostSessionExtractionError) as exc_info:
        adapter.extract(_request())
    assert exc_info.value.__cause__ is not None


# ── Error mapping (observed pydantic_ai 2.39 public path) ─────────────────


def test_model_http_error_maps_to_invocation_failed() -> None:
    model, _ = _function_model(_raise(ModelHTTPError(503, "m")))
    adapter = PydanticAIPostSessionExtractionModel(model=model)
    with pytest.raises(PostSessionExtractionError) as exc_info:
        adapter.extract(_request())
    assert exc_info.value.reason is ExtractionFailureReason.MODEL_INVOCATION_FAILED


def test_model_api_timeout_maps_to_timeout() -> None:
    error = ModelAPIError("m", "Request timed out.")
    error.__cause__ = openai.APITimeoutError(request=None)  # type: ignore[arg-type]
    model, _ = _function_model(_raise(error))
    adapter = PydanticAIPostSessionExtractionModel(model=model)
    with pytest.raises(PostSessionExtractionError) as exc_info:
        adapter.extract(_request())
    assert exc_info.value.reason is ExtractionFailureReason.MODEL_TIMEOUT


def test_model_api_connection_maps_to_unavailable() -> None:
    error = ModelAPIError("m", "Connection error.")
    error.__cause__ = openai.APIConnectionError(request=None)  # type: ignore[arg-type]
    model, _ = _function_model(_raise(error))
    adapter = PydanticAIPostSessionExtractionModel(model=model)
    with pytest.raises(PostSessionExtractionError) as exc_info:
        adapter.extract(_request())
    assert exc_info.value.reason is ExtractionFailureReason.MODEL_UNAVAILABLE


def test_unknown_agent_run_error_maps_to_invocation_failed() -> None:
    model, _ = _function_model(_raise(AgentRunError("boom")))
    adapter = PydanticAIPostSessionExtractionModel(model=model)
    with pytest.raises(PostSessionExtractionError) as exc_info:
        adapter.extract(_request())
    assert exc_info.value.reason is ExtractionFailureReason.MODEL_INVOCATION_FAILED
    assert isinstance(exc_info.value.__cause__, AgentRunError)


def test_non_model_rejected() -> None:
    with pytest.raises(TypeError):
        PydanticAIPostSessionExtractionModel(model=object())  # type: ignore[arg-type]
