"""Neutral shared agent contracts for the Fast Agent.

This module is the neutral home for the provider-neutral DTOs and
deterministic helpers used by the accepted Pydantic AI agent runtime.

It intentionally contains **no** orchestration classes.

Ownership
─────────

Owned here:
    ``AgentDecision`` / ``build_agent_request`` — deterministic decision
        snapshot + request projection.
    ``AgentOutcomeKind`` / ``AgentTextOutcome`` / ``AgentRunResult`` /
        ``parse_agent_outcome`` — terminal outcome + run result contracts.
    ``AgentToolExecutionResult`` / ``build_agent_tool_execution_result`` —
        deterministic TOOL-result adaptation.

Owned elsewhere:
    ``MAX_TOOL_CALLS_PER_RUN`` — canonical constant in
        ``dnd_assistant.application.dnd_agent_policy``.

This module must not import from::

    dnd_assistant.models.gateway
    dnd_assistant.models.ollama
    dnd_assistant.storage
    dnd_assistant.retrieval
    dnd_assistant.cli
    dnd_assistant.tools.executor
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, field_validator
from pydantic import ValidationError as PydanticValidationError
from pydantic_core import PydanticSerializationError

from dnd_assistant.errors import ModelError, ValidationError
from dnd_assistant.models.types import ChatMessage, ChatRequest, MessageRole
from dnd_assistant.prompts.agent_v3 import SYSTEM_PROMPT

if TYPE_CHECKING:
    from dnd_assistant.application.agent_context import (
        AgentCampaignMemory,
        AgentContext,
        AgentEntityContext,
        AgentEventContext,
        AgentSessionContext,
    )
    from dnd_assistant.models.types import ToolAwareResponse, ToolCall
    from dnd_assistant.tools.catalog import ToolPublicDefinition
    from dnd_assistant.tools.types import BaseModel as ToolBaseModel


# ── Decision contract ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AgentDecision:
    """Provider-neutral snapshot of a single Fast Agent decision step.

    Attributes:
        prompt_version: Reproducible prompt identity for tracing/evals.
        request: Exact conversation history used for the first model turn.
        exposed_tools: Exact allowlist snapshot shown to the model for this turn.
        response: Validated provider-neutral ``ToolAwareResponse``.
    """

    prompt_version: str
    request: ChatRequest
    exposed_tools: tuple[ToolPublicDefinition, ...]
    response: ToolAwareResponse


def build_agent_request(context: AgentContext) -> ChatRequest:
    """Build a deterministic ``ChatRequest`` from an ``AgentContext``.

    This is the shared projection used by the agent runtime.
    It produces the exact provider-neutral ``SYSTEM + USER`` conversation
    snapshot.

    The USER payload is deterministic JSON with ``sort_keys=True``,
    ``separators=(",", ":")``, ``ensure_ascii=False``, and ``allow_nan=False``.
    """
    user_payload = _build_user_json(context)
    return ChatRequest(
        messages=(
            ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
            ChatMessage(role=MessageRole.USER, content=user_payload),
        ),
    )


# ── Deterministic USER JSON payload ────────────────────────────────────────────


def _build_user_json(context: AgentContext) -> str:
    """Build a deterministic JSON string from an ``AgentContext``.

    The payload uses explicit field mapping so that future fields added to
    ``AgentContext`` do not automatically leak into model context.
    """
    payload: dict[str, object] = {
        "user_input": context.user_input,
        "current_world_tick": context.current_world_tick,
        "active_session": _serialize_session(context.active_session),
        "relevant_entities": [_serialize_entity(e) for e in context.relevant_entities],
        "recent_events": [_serialize_event(e) for e in context.recent_events],
        "campaign_memory": _serialize_campaign_memory(context.campaign_memory),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _serialize_session(
    session: AgentSessionContext | None,
) -> dict[str, object] | None:
    """Serialize an ``AgentSessionContext`` or return ``None``."""
    if session is None:
        return None
    # Avoid circular import: AgentSessionContext is a frozen dataclass
    return {
        "session_id": session.session_id,
        "world_tick_start": session.world_tick_start,
    }


def _serialize_entity(entity: AgentEntityContext) -> dict[str, object]:
    """Serialize an ``AgentEntityContext``."""
    return {
        "entity_id": entity.entity_id,
        "entity_type": entity.entity_type,
        "name": entity.name,
        "status": entity.status,
        "knowledge_status": entity.knowledge_status,
        "tags": list(entity.tags),
        "body_excerpt": entity.body_excerpt,
        "body_truncated": entity.body_truncated,
    }


def _serialize_event(event: AgentEventContext) -> dict[str, object]:
    """Serialize an ``AgentEventContext``."""
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "world_tick": event.world_tick,
        "text_excerpt": event.text_excerpt,
        "text_truncated": event.text_truncated,
    }


def _serialize_campaign_memory(
    memory: AgentCampaignMemory | None,
) -> dict[str, object] | None:
    """Serialize an ``AgentCampaignMemory`` or return ``None``.

    The field is always explicitly present (``null`` when unavailable) and is
    kept distinct from ``relevant_entities``: Campaign State memory is
    recently-touched derived memory, not query-derived retrieval relevance.
    """
    if memory is None:
        return None
    return {
        "recently_touched": [
            {
                "entity_id": entity.entity_id,
                "entity_type": entity.entity_type,
                "name": entity.name,
            }
            for entity in memory.recently_touched
        ],
        "total_recently_touched": memory.total_recently_touched,
        "truncated": memory.truncated,
    }


# ── Terminal outcome schema ────────────────────────────────────────────────────


class AgentOutcomeKind(StrEnum):
    """Deterministic terminal outcome classification for a Fast Agent run.

    ``RESPOND`` — the model produced a final answer.
    ``CLARIFY`` — the model needs more information from the user.
    """

    RESPOND = "respond"
    CLARIFY = "clarify"


class AgentTextOutcome(BaseModel):
    """Provider-neutral validated terminal outcome from model output.

    Attributes:
        kind: ``RESPOND`` or ``CLARIFY``.
        message: Non-empty, non-whitespace-only user-facing text.
    """

    kind: AgentOutcomeKind
    message: str

    model_config = {"extra": "forbid", "frozen": True}

    @field_validator("message")
    @classmethod
    def _message_non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("message must not be empty")
        if not value.strip():
            raise ValueError("message must not be whitespace-only")
        return value


# ── AgentRunResult ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    """Complete result of one bounded Fast Agent run.

    Attributes:
        initial_decision: The ``AgentDecision`` from the first model call.
        tool_executions: Tuple of ``AgentToolExecutionResult`` values, one
            per executed tool call.  Empty for the direct path.
        final_response: The final ``ToolAwareResponse`` (either the initial
            decision response or the second model call response).
        outcome: The validated terminal ``AgentTextOutcome``.
    """

    initial_decision: AgentDecision
    tool_executions: tuple[AgentToolExecutionResult, ...]
    final_response: ToolAwareResponse
    outcome: AgentTextOutcome


# ── Terminal content parsing ───────────────────────────────────────────────────


def parse_agent_outcome(response: ToolAwareResponse) -> AgentTextOutcome:
    """Parse a ``ToolAwareResponse`` with zero tool calls into an ``AgentTextOutcome``.

    Args:
        response: A ``ToolAwareResponse`` whose assistant message has zero
            tool calls and whose content is a valid ``AgentTextOutcome`` JSON.

    Returns:
        A validated ``AgentTextOutcome``.

    Raises:
        ModelError: If the response contains tool calls, or the content
            is not valid ``AgentTextOutcome`` JSON.
    """
    if response.message.tool_calls:
        raise ModelError("Cannot parse AgentTextOutcome from a response with tool calls")

    content = response.message.content
    if not content:
        raise ModelError("Cannot parse AgentTextOutcome from empty content")

    try:
        return AgentTextOutcome.model_validate_json(content)
    except PydanticValidationError as exc:
        raise ModelError(
            "Model output failed AgentTextOutcome validation",
            cause=exc,
        ) from exc


# ── Tool execution result contract ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AgentToolExecutionResult:
    """Result of executing one validated tool call.

    Attributes:
        tool_call: The exact ``ToolCall`` that was executed.
        output: The validated typed ``BaseModel`` returned by ``ToolExecutor``.
        tool_message: A provider-neutral ``ChatMessage`` with ``role=TOOL``
            containing the deterministic JSON-serialised output.
    """

    tool_call: ToolCall
    output: ToolBaseModel
    tool_message: ChatMessage


def build_agent_tool_execution_result(
    tool_call: ToolCall,
    output: ToolBaseModel,
) -> AgentToolExecutionResult:
    """Build a frozen ``AgentToolExecutionResult`` from a tool call and output.

    Reuses the deterministic TOOL-message serialisation from
    ``_build_tool_message``.  This is the shared factory used by the
    accepted Pydantic AI agent runtime.

    Args:
        tool_call: The ``ToolCall`` that was executed.
        output: The validated typed ``BaseModel`` from ``ToolExecutor``.

    Returns:
        An ``AgentToolExecutionResult`` with deterministic TOOL message.
    """
    tool_message = _build_tool_message(output, tool_call)
    return AgentToolExecutionResult(
        tool_call=tool_call,
        output=output,
        tool_message=tool_message,
    )


def _build_tool_message(
    output: ToolBaseModel,
    tool_call: ToolCall,
) -> ChatMessage:
    """Build a deterministic TOOL ``ChatMessage`` from a validated output.

    The output is serialised using Pydantic's ``model_dump(mode="json")``
    followed by deterministic ``json.dumps``.

    Args:
        output: The validated typed ``BaseModel`` from ``ToolExecutor``.
        tool_call: The original ``ToolCall`` (for name and call_id).

    Returns:
        A ``ChatMessage`` with ``role=TOOL``.

    Raises:
        ValidationError: If the validated output cannot be serialised to
            model-facing JSON.
    """
    try:
        json_ready = output.model_dump(mode="json", by_alias=True)
    except PydanticSerializationError as exc:
        raise ValidationError(
            "Failed to serialise tool output to JSON",
            cause=exc,
        ) from exc

    try:
        content = json.dumps(
            json_ready,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValidationError(
            "Failed to serialise tool output to JSON",
            cause=exc,
        ) from exc

    return ChatMessage(
        role=MessageRole.TOOL,
        content=content,
        tool_name=tool_call.name,
        tool_call_id=tool_call.call_id,
    )


__all__: list[str] = [
    "AgentDecision",
    "AgentOutcomeKind",
    "AgentRunResult",
    "AgentTextOutcome",
    "AgentToolExecutionResult",
    "build_agent_request",
    "build_agent_tool_execution_result",
    "parse_agent_outcome",
]
