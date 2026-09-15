"""S11-04 Pydantic AI rendering adapter tests (no Ollama, no network)."""

from __future__ import annotations

import inspect
from typing import Any

import openai
import pytest
from pydantic_ai.exceptions import AgentRunError, ModelAPIError, ModelHTTPError
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from dnd_assistant.application.post_session_rendering import (
    PostSessionRenderingError,
    RenderingFailureReason,
    build_recap_render_request,
    build_summary_render_request,
    serialize_recap_request,
    serialize_summary_request,
)
from dnd_assistant.application.post_session_visibility import (
    project_recap,
    project_summary,
)
from dnd_assistant.application.pydantic_ai_post_session_rendering import (
    PydanticAIPostSessionRenderingModel,
)
from dnd_assistant.domain.post_session_artifacts import PostSessionRenderOutput
from dnd_assistant.domain.post_session_extraction import ExtractionVisibilityHint
from dnd_assistant.domain.types import Visibility
from dnd_assistant.prompts.post_session_recap_v1 import POST_SESSION_RECAP_SYSTEM_PROMPT
from dnd_assistant.prompts.post_session_summary_v1 import POST_SESSION_SUMMARY_SYSTEM_PROMPT
from tests.unit.post_session.extraction_helpers import (
    make_candidate,
    make_claim,
    make_extraction,
    make_mention,
)
from tests.unit.post_session.rendering_helpers import (
    DM_SECRET_CANARY_CANDIDATE,
    DM_SECRET_CANARY_CLAIM_TEXT,
    SYSTEM_SECRET_CANARY_ENTITY_BODY,
    make_accepted,
    make_prepared_input,
    make_render_output,
    prepared_entity,
)

# ── Fixtures ──────────────────────────────────────────────────────────────


def _prepared():
    return make_prepared_input(
        entities=(
            prepared_entity("npc-aria", name="Aria"),
            prepared_entity(
                "npc-hidden",
                name="The Hidden One",
                visibility=Visibility.DM,
                body=DM_SECRET_CANARY_CLAIM_TEXT,
            ),
            prepared_entity(
                "npc-system",
                name="System Entity",
                visibility=Visibility.SYSTEM,
                body=SYSTEM_SECRET_CANARY_ENTITY_BODY,
            ),
        )
    )


def _accepted(prepared):
    claims = (
        make_claim(
            claim_id="c_player",
            text="Aria arrived.",
            entity_mentions=(make_mention(mention_id="m1", candidate_entity_id="npc-aria"),),
            visibility_hint=ExtractionVisibilityHint.PLAYER,
        ),
        make_claim(
            claim_id="c_dm",
            text=DM_SECRET_CANARY_CLAIM_TEXT,
            entity_mentions=(make_mention(mention_id="m2", candidate_entity_id="npc-hidden"),),
            visibility_hint=ExtractionVisibilityHint.DM,
        ),
        make_claim(
            claim_id="c_system",
            entity_mentions=(make_mention(mention_id="m3", candidate_entity_id="npc-system"),),
            visibility_hint=ExtractionVisibilityHint.DM,
        ),
    )
    candidates = (make_candidate(candidate_id="cand1", display_name=DM_SECRET_CANARY_CANDIDATE),)
    return make_accepted(prepared, make_extraction(claims=claims, entity_candidates=candidates))


def _summary_request(prepared, accepted):
    return build_summary_render_request(prepared, project_summary(prepared, accepted))


def _recap_request(prepared, accepted):
    return build_recap_render_request(prepared, project_recap(prepared, accepted))


def _function_model(behaviour: Any) -> tuple[FunctionModel, dict[str, Any]]:
    seen: dict[str, Any] = {"calls": 0}

    def fn(messages: list[Any], info: Any) -> ModelResponse:
        seen["calls"] += 1
        seen["function_tools"] = tuple(info.function_tools)
        seen["output_tools"] = tuple(tool.name for tool in info.output_tools)
        seen["messages"] = messages
        return behaviour(messages, info)

    return FunctionModel(fn), seen


def _raise(exc: BaseException) -> Any:
    def behaviour(messages: list[Any], info: Any) -> ModelResponse:
        raise exc

    return behaviour


def _valid_output(messages: list[Any], info: Any) -> ModelResponse:
    output = make_render_output()
    return ModelResponse(
        parts=[ToolCallPart(info.output_tools[0].name, output.model_dump(mode="json"))]
    )


def _messages_text(messages: list[Any]) -> str:
    chunks: list[str] = []
    for message in messages:
        for part in getattr(message, "parts", ()):
            content = getattr(part, "content", None)
            if isinstance(content, str):
                chunks.append(content)
    return "\n".join(chunks)


# ── Happy path / zero project tools ───────────────────────────────────────


def test_adapter_returns_typed_output_for_summary_and_recap() -> None:
    prepared = _prepared()
    accepted = _accepted(prepared)
    model, seen = _function_model(_valid_output)
    adapter = PydanticAIPostSessionRenderingModel(model=model)

    summary = adapter.render(_summary_request(prepared, accepted))
    recap = adapter.render(_recap_request(prepared, accepted))

    assert isinstance(summary, PostSessionRenderOutput)
    assert isinstance(recap, PostSessionRenderOutput)
    assert seen["calls"] == 2


def test_adapter_exposes_no_project_action_tools() -> None:
    prepared = _prepared()
    accepted = _accepted(prepared)
    model, seen = _function_model(_valid_output)
    adapter = PydanticAIPostSessionRenderingModel(model=model)
    adapter.render(_recap_request(prepared, accepted))

    assert seen["function_tools"] == ()
    assert seen["output_tools"] == ("final_result",)


def test_adapter_api_has_no_caller_tool_surface() -> None:
    assert set(inspect.signature(PydanticAIPostSessionRenderingModel.__init__).parameters) == {
        "self",
        "model",
    }
    assert set(inspect.signature(PydanticAIPostSessionRenderingModel.render).parameters) == {
        "self",
        "request",
    }


def test_adapter_selects_python_owned_prompt_by_artifact() -> None:
    prepared = _prepared()
    accepted = _accepted(prepared)
    summary_request = _summary_request(prepared, accepted)
    recap_request = _recap_request(prepared, accepted)

    summary_instructions, summary_prompt = PydanticAIPostSessionRenderingModel._select_prompt(
        summary_request
    )
    recap_instructions, recap_prompt = PydanticAIPostSessionRenderingModel._select_prompt(
        recap_request
    )

    assert summary_instructions == POST_SESSION_SUMMARY_SYSTEM_PROMPT
    assert recap_instructions == POST_SESSION_RECAP_SYSTEM_PROMPT
    assert summary_instructions != recap_instructions
    assert summary_prompt == serialize_summary_request(summary_request)
    assert recap_prompt == serialize_recap_request(recap_request)


# ── Retry / request limit ────────────────────────────────────────────────


def test_output_retries_disabled_single_request() -> None:
    def bad(messages: list[Any], info: Any) -> ModelResponse:
        return ModelResponse(parts=[TextPart("not a json object")])

    prepared = _prepared()
    accepted = _accepted(prepared)
    model, seen = _function_model(bad)
    adapter = PydanticAIPostSessionRenderingModel(model=model)
    with pytest.raises(PostSessionRenderingError) as exc_info:
        adapter.render(_summary_request(prepared, accepted))
    assert exc_info.value.reason is RenderingFailureReason.INVALID_STRUCTURED_OUTPUT
    assert seen["calls"] == 1


def test_unexpected_output_preserves_cause() -> None:
    def bad(messages: list[Any], info: Any) -> ModelResponse:
        return ModelResponse(parts=[TextPart("nope")])

    prepared = _prepared()
    accepted = _accepted(prepared)
    model, _ = _function_model(bad)
    adapter = PydanticAIPostSessionRenderingModel(model=model)
    with pytest.raises(PostSessionRenderingError) as exc_info:
        adapter.render(_recap_request(prepared, accepted))
    assert exc_info.value.__cause__ is not None


# ── Error mapping ─────────────────────────────────────────────────────────


def test_model_http_error_maps_to_invocation_failed() -> None:
    prepared = _prepared()
    accepted = _accepted(prepared)
    model, _ = _function_model(_raise(ModelHTTPError(503, "m")))
    adapter = PydanticAIPostSessionRenderingModel(model=model)
    with pytest.raises(PostSessionRenderingError) as exc_info:
        adapter.render(_recap_request(prepared, accepted))
    assert exc_info.value.reason is RenderingFailureReason.MODEL_INVOCATION_FAILED


def test_model_api_timeout_maps_to_timeout() -> None:
    prepared = _prepared()
    accepted = _accepted(prepared)
    error = ModelAPIError("m", "Request timed out.")
    error.__cause__ = openai.APITimeoutError(request=None)  # type: ignore[arg-type]
    model, _ = _function_model(_raise(error))
    adapter = PydanticAIPostSessionRenderingModel(model=model)
    with pytest.raises(PostSessionRenderingError) as exc_info:
        adapter.render(_summary_request(prepared, accepted))
    assert exc_info.value.reason is RenderingFailureReason.MODEL_TIMEOUT


def test_model_api_connection_maps_to_unavailable() -> None:
    prepared = _prepared()
    accepted = _accepted(prepared)
    error = ModelAPIError("m", "Connection error.")
    error.__cause__ = openai.APIConnectionError(request=None)  # type: ignore[arg-type]
    model, _ = _function_model(_raise(error))
    adapter = PydanticAIPostSessionRenderingModel(model=model)
    with pytest.raises(PostSessionRenderingError) as exc_info:
        adapter.render(_recap_request(prepared, accepted))
    assert exc_info.value.reason is RenderingFailureReason.MODEL_UNAVAILABLE


def test_unknown_agent_run_error_maps_to_invocation_failed() -> None:
    prepared = _prepared()
    accepted = _accepted(prepared)
    model, _ = _function_model(_raise(AgentRunError("boom")))
    adapter = PydanticAIPostSessionRenderingModel(model=model)
    with pytest.raises(PostSessionRenderingError) as exc_info:
        adapter.render(_summary_request(prepared, accepted))
    assert exc_info.value.reason is RenderingFailureReason.MODEL_INVOCATION_FAILED
    assert isinstance(exc_info.value.__cause__, AgentRunError)


def test_non_model_rejected() -> None:
    with pytest.raises(TypeError):
        PydanticAIPostSessionRenderingModel(model=object())  # type: ignore[arg-type]


def test_non_request_rejected() -> None:
    model, _ = _function_model(_valid_output)
    adapter = PydanticAIPostSessionRenderingModel(model=model)
    with pytest.raises(TypeError):
        adapter.render(object())  # type: ignore[arg-type]


# ── Actual model-visible canary proof ─────────────────────────────────────


def test_recap_prompt_contains_no_hidden_canary() -> None:
    prepared = _prepared()
    accepted = _accepted(prepared)
    model, seen = _function_model(_valid_output)
    adapter = PydanticAIPostSessionRenderingModel(model=model)

    adapter.render(_recap_request(prepared, accepted))

    text = _messages_text(seen["messages"])
    assert DM_SECRET_CANARY_CLAIM_TEXT not in text
    assert SYSTEM_SECRET_CANARY_ENTITY_BODY not in text
    assert DM_SECRET_CANARY_CANDIDATE not in text


def test_summary_prompt_contains_dm_but_not_system_canary() -> None:
    prepared = _prepared()
    accepted = _accepted(prepared)
    model, seen = _function_model(_valid_output)
    adapter = PydanticAIPostSessionRenderingModel(model=model)

    adapter.render(_summary_request(prepared, accepted))

    text = _messages_text(seen["messages"])
    assert DM_SECRET_CANARY_CLAIM_TEXT in text
    assert SYSTEM_SECRET_CANARY_ENTITY_BODY not in text
    assert DM_SECRET_CANARY_CANDIDATE in text
