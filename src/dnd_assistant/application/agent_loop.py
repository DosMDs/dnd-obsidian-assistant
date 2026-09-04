"""Bounded model-tool-model loop for the Fast Agent (S9-04).

This module owns exactly:

- one-step direct respond/clarify path (one model call, zero tools)
- single-tool path (model → ToolExecutor → model)
- terminal AgentTextOutcome parsing from ToolAwareResponse
- hard bound enforcement (max 2 model calls, max 1 tool execution)

It does NOT own:

- ToolExecutor execution (delegates to AgentToolExecutionService)
- ToolRegistry lookup (delegates to ToolExecutor)
- input/output schema validation (delegates to ToolExecutor)
- multi-tool-call semantics (S9-05)
- CLI (S9-06)
- Ollama transport
- Vault access
- retrieval
- calendar arithmetic

Importing this module must NOT eagerly load::

    dnd_assistant.models.ollama
    dnd_assistant.storage
    dnd_assistant.retrieval
    dnd_assistant.cli
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, field_validator

from dnd_assistant.errors import ModelError

if TYPE_CHECKING:
    from dnd_assistant.application.agent_context import AgentContextBuilder
    from dnd_assistant.application.agent_tool_execution import (
        AgentToolExecutionResult,
        AgentToolExecutionService,
    )
    from dnd_assistant.application.fast_agent import AgentDecision, FastAgent
    from dnd_assistant.models.gateway import ModelGateway
    from dnd_assistant.models.types import ToolAwareResponse
    from dnd_assistant.tools.catalog import ToolRegistrySchema
    from dnd_assistant.tools.types import ExecutionContext


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
        tool_execution: The ``AgentToolExecutionResult`` if a tool was
            executed, or ``None`` for the direct path.
        final_response: The final ``ToolAwareResponse`` (either the initial
            decision response or the second model call response).
        outcome: The validated terminal ``AgentTextOutcome``.
    """

    initial_decision: AgentDecision
    tool_execution: AgentToolExecutionResult | None
    final_response: ToolAwareResponse
    outcome: AgentTextOutcome


# ── Terminal content parsing ───────────────────────────────────────────────────


def _parse_agent_outcome(response: ToolAwareResponse) -> AgentTextOutcome:
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
        parsed = json.loads(content)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ModelError(
            "Failed to parse model output as AgentTextOutcome JSON",
            cause=exc,
        ) from exc

    if not isinstance(parsed, dict):
        raise ModelError(f"Expected JSON object for AgentTextOutcome, got {type(parsed).__name__}")

    try:
        return AgentTextOutcome.model_validate(parsed)
    except Exception as exc:
        raise ModelError(
            "Model output failed AgentTextOutcome validation",
            cause=exc,
        ) from exc


# ── AgentLoop ──────────────────────────────────────────────────────────────────


class AgentLoop:
    """Bounded model-tool-model orchestration for the Fast Agent.

    The ``run()`` method performs at most two model calls and at most one
    tool execution:

    - Direct path: one model call, zero tools → terminal outcome.
    - Single-tool path: one model call → one tool execution → one model
      call → terminal outcome.
    - Initial multi-tool response: raises ``ModelError`` before any tool
      execution (S9-04 fail-closed deferral).
    - Post-tool tool call: raises ``ModelError`` without additional execution.
    """

    def __init__(
        self,
        *,
        context_builder: AgentContextBuilder,
        model_gateway: ModelGateway,
        tool_catalog: ToolRegistrySchema,
        tool_execution_service: AgentToolExecutionService,
    ) -> None:
        # Deferred runtime imports: keep provider/tool/storage packages out
        # of module-import scope.
        from dnd_assistant.application.fast_agent import FastAgent as FA

        self._fast_agent: FastAgent = FA(
            context_builder=context_builder,
            model_gateway=model_gateway,
            tool_catalog=tool_catalog,
        )
        self._tool_execution_service = tool_execution_service

    def run(
        self,
        user_input: str,
        *,
        execution_context: ExecutionContext,
    ) -> AgentRunResult:
        """Execute one bounded Fast Agent run.

        Args:
            user_input: The validated user query string.
            execution_context: Trusted Python execution context for tool
                exposure filtering and execution.

        Returns:
            An ``AgentRunResult`` with the decision, optional tool
            execution, final response, and terminal outcome.

        Raises:
            ModelError: If the initial response has multiple tool calls,
                the second response has tool calls, or model output is
                malformed.
            ValidationError: Propagated from context builder or tool
                execution.
            NotFoundError: Propagated from tool execution.
            ConflictError: Propagated from tool execution.
            DndAssistantError: Propagated from tool execution.
            Exception: Propagated from tool execution.
        """
        # 1. First model call via FastAgent.decide()
        initial_decision = self._fast_agent.decide(
            user_input,
            execution_context=execution_context,
        )

        tool_calls = initial_decision.response.message.tool_calls

        # 2. Direct path: zero tool calls → parse terminal outcome
        if not tool_calls:
            outcome = _parse_agent_outcome(initial_decision.response)
            return AgentRunResult(
                initial_decision=initial_decision,
                tool_execution=None,
                final_response=initial_decision.response,
                outcome=outcome,
            )

        # 3. S9-04 fail-closed: multiple tool calls → ModelError
        if len(tool_calls) > 1:
            raise ModelError(
                "S9-04 does not support multiple initial tool calls. "
                "S9-05 will define multi-call semantics."
            )

        # 4. Exactly one tool call → execute
        tool_execution = self._tool_execution_service.execute(
            initial_decision,
            tool_calls[0],
            execution_context=execution_context,
        )

        # 5. Build follow-up request with exact ordered history
        from dnd_assistant.models.types import ChatRequest

        followup_request = ChatRequest(
            messages=(
                *initial_decision.request.messages,
                initial_decision.response.message,
                tool_execution.tool_message,
            )
        )

        # 6. Second model call with exact first-turn exposure snapshot
        second_response = self._fast_agent._model_gateway.chat_with_tools(
            followup_request,
            list(initial_decision.exposed_tools),
        )

        # 7. Bound enforcement: second response must have zero tool calls
        if second_response.message.tool_calls:
            raise ModelError(
                "S9-04 does not support post-tool tool calls. "
                "The model requested another tool after receiving a tool result."
            )

        # 8. Parse terminal outcome from second response
        outcome = _parse_agent_outcome(second_response)

        return AgentRunResult(
            initial_decision=initial_decision,
            tool_execution=tool_execution,
            final_response=second_response,
            outcome=outcome,
        )
