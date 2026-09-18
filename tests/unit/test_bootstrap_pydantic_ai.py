"""S13-03 Pydantic AI bootstrap extraction adapter tests (no Ollama, no network)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai.exceptions import AgentRunError, ModelAPIError, ModelHTTPError
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from dnd_assistant.application.bootstrap_extraction import (
    BootstrapExtractionFailureReason,
    build_bootstrap_extraction_request,
)
from dnd_assistant.application.bootstrap_input import prepare_bootstrap_input
from dnd_assistant.application.pydantic_ai_bootstrap import (
    PydanticAIBootstrapExtractionModel,
)
from dnd_assistant.application.vault_discovery import SourceClass
from dnd_assistant.domain.bootstrap_extraction import (
    BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
    BootstrapExtraction,
)
from tests.unit.bootstrap.helpers import make_report, make_source


def _request():
    projection = prepare_bootstrap_input(
        make_report("camp-1", [make_source("Notes/a.md", SourceClass.USER_SOURCE, "варос")])
    )
    return build_bootstrap_extraction_request(
        projection, projection.batches[0], processor_version="p", prompt_version="v"
    )


def _function_model(behaviour: Any):
    seen: dict[str, Any] = {"calls": 0}

    def fn(messages: list[Any], info: Any) -> ModelResponse:
        seen["calls"] += 1
        seen["function_tools"] = tuple(info.function_tools)
        seen["output_tools"] = tuple(tool.name for tool in info.output_tools)
        return behaviour(messages, info)

    return FunctionModel(fn), seen


def _valid_output(messages: list[Any], info: Any) -> ModelResponse:
    extraction = BootstrapExtraction(schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION)
    return ModelResponse(
        parts=[ToolCallPart(info.output_tools[0].name, extraction.model_dump(mode="json"))]
    )


def _raise(exc: BaseException) -> Any:
    def behaviour(messages: list[Any], info: Any) -> ModelResponse:
        raise exc

    return behaviour


def test_adapter_returns_typed_extraction_with_no_project_tools() -> None:
    model, seen = _function_model(_valid_output)
    adapter = PydanticAIBootstrapExtractionModel(model=model)
    result = adapter.extract(_request())
    assert isinstance(result, BootstrapExtraction)
    assert seen["calls"] == 1
    assert seen["function_tools"] == ()
    assert seen["output_tools"] == ("final_result",)


def test_invalid_output_fails_closed_without_retry() -> None:
    def bad(messages: list[Any], info: Any) -> ModelResponse:
        return ModelResponse(parts=[TextPart("not a json object")])

    model, seen = _function_model(bad)
    adapter = PydanticAIBootstrapExtractionModel(model=model)
    with pytest.raises(Exception) as exc_info:
        adapter.extract(_request())
    assert seen["calls"] == 1
    assert (
        getattr(exc_info.value, "reason", None)
        is BootstrapExtractionFailureReason.INVALID_STRUCTURED_OUTPUT
    )


def test_model_http_error_maps_to_invocation_failed() -> None:
    model, _ = _function_model(_raise(ModelHTTPError(503, "m")))
    adapter = PydanticAIBootstrapExtractionModel(model=model)
    with pytest.raises(Exception) as exc_info:
        adapter.extract(_request())
    assert (
        getattr(exc_info.value, "reason", None)
        is BootstrapExtractionFailureReason.MODEL_INVOCATION_FAILED
    )


def test_model_api_error_maps_to_invocation_failed() -> None:
    model, _ = _function_model(_raise(ModelAPIError("m", "boom")))
    adapter = PydanticAIBootstrapExtractionModel(model=model)
    with pytest.raises(Exception) as exc_info:
        adapter.extract(_request())
    assert (
        getattr(exc_info.value, "reason", None)
        is BootstrapExtractionFailureReason.MODEL_INVOCATION_FAILED
    )


def test_agent_run_error_maps_to_invocation_failed() -> None:
    model, _ = _function_model(_raise(AgentRunError("boom")))
    adapter = PydanticAIBootstrapExtractionModel(model=model)
    with pytest.raises(Exception) as exc_info:
        adapter.extract(_request())
    assert (
        getattr(exc_info.value, "reason", None)
        is BootstrapExtractionFailureReason.MODEL_INVOCATION_FAILED
    )


def test_non_model_rejected() -> None:
    with pytest.raises(TypeError):
        PydanticAIBootstrapExtractionModel(model=object())  # type: ignore[arg-type]
