"""Bounded model-tool-model loop for the Fast Agent (S9-05).

This module owns exactly:

- one-step direct respond/clarify path (one model call, zero tools)
- single-tool path (model -> ToolExecutor -> model)
- multi-READ batch path (model -> ToolExecutor x N -> model)
- terminal AgentTextOutcome parsing from ToolAwareResponse
- hard bound enforcement (max 2 model calls, max 4 tool executions)
- multi-call safety policy (READ-only batches, WRITE-batch rejection)
- duplicate non-None call_id rejection

It does NOT own:

- ToolExecutor execution (delegates to AgentToolExecutionService)
- ToolRegistry lookup (delegates to ToolExecutor)
- input/output schema validation (delegates to ToolExecutor)
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

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, field_validator
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.errors import ModelError

if TYPE_CHECKING:
    from dnd_assistant.application.agent_context import AgentContextBuilder
    from dnd_assistant.application.agent_tool_execution import (
        AgentToolExecutionResult,
        AgentToolExecutionService,
    )
    from dnd_assistant.application.fast_agent import AgentDecision, FastAgent
    from dnd_assistant.models.gateway import ModelGateway
    from dnd_assistant.models.types import ToolAwareResponse, ToolCall
    from dnd_assistant.tools.catalog import ToolPublicDefinition, ToolRegistrySchema
    from dnd_assistant.tools.types import ExecutionContext


# ── Hard bounds ─────────────────────────────────────────────────────────────────


MAX_TOOL_CALLS_PER_RUN: int = 4
"""Maximum number of initial tool calls accepted in one bounded run.

0 calls -> direct terminal outcome.
1 call  -> READ or WRITE through ToolExecutor.
2..4 calls -> READ-only sequential batch.
5+ calls -> rejected before any execution.
"""


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
        return AgentTextOutcome.model_validate_json(content)
    except PydanticValidationError as exc:
        raise ModelError(
            "Model output failed AgentTextOutcome validation",
            cause=exc,
        ) from exc


# ── Multi-call safety helpers ──────────────────────────────────────────────────


def _reject_duplicate_call_ids(
    tool_calls: tuple[ToolCall, ...],
) -> None:
    """Reject a batch with duplicate non-None ``call_id`` values.

    Multiple calls with ``call_id=None`` are permitted.
    Duplicate non-None call IDs are ambiguous and fail closed.

    Raises:
        ModelError: If any non-None ``call_id`` appears more than once.
    """
    seen: set[str] = set()
    for call in tool_calls:
        cid = call.call_id
        if cid is not None:
            if cid in seen:
                raise ModelError(
                    f"Duplicate non-None call_id '{cid}' in initial tool calls. "
                    "Refusing to execute ambiguous batch."
                )
            seen.add(cid)


def _reject_multi_call_containing_write(
    tool_calls: tuple[ToolCall, ...],
    exposed_tools: tuple[ToolPublicDefinition, ...],
) -> None:
    """Reject a multi-call batch that contains any WRITE tool.

    Only READ-only batches of 2..4 calls are permitted.
    The entire batch is rejected before any execution.

    Raises:
        ModelError: If any call in the batch resolves to a WRITE
            ``ToolPublicDefinition`` by exact name match.
    """
    from dnd_assistant.tools.types import Permission as P

    for call in tool_calls:
        matching: ToolPublicDefinition | None = None
        for t in exposed_tools:
            if t.name == call.name:
                matching = t
                break

        if matching is None:
            raise ModelError(
                f"Tool call '{call.name}' has no matching exposed tool definition. "
                "Cannot classify for multi-call safety."
            )

        if matching.permission is not P.READ:
            raise ModelError(
                "Multi-call batches containing WRITE tools are not allowed. "
                f"Tool '{call.name}' has permission '{matching.permission.value}'."
            )


# ── AgentLoop ──────────────────────────────────────────────────────────────────


class AgentLoop:
    """Bounded model-tool-model orchestration for the Fast Agent.

    The ``run()`` method performs at most two model calls and at most
    ``MAX_TOOL_CALLS_PER_RUN`` (4) tool executions:

    - Direct path: one model call, zero tools → terminal outcome.
    - Single-tool path: one model call → one tool execution → one model
      call → terminal outcome.
    - Multi-READ batch (2..4 calls): one model call → sequential READ
      executions → one model call → terminal outcome.
    - Multi-call containing WRITE: raises ``ModelError`` before any
      execution.
    - 5+ initial calls: raises ``ModelError`` before any execution.
    - Duplicate non-None ``call_id``: raises ``ModelError`` before any
      execution.
    - Post-tool tool call: raises ``ModelError`` without additional
      execution.
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

        self._model_gateway: ModelGateway = model_gateway
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
            An ``AgentRunResult`` with the decision, tool execution
            results, final response, and terminal outcome.

        Raises:
            ModelError: If the initial response has 5+ tool calls,
                contains WRITE calls in a multi-call batch, has duplicate
                non-None call_ids, the second response has tool calls,
                or model output is malformed.
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
                tool_executions=(),
                final_response=initial_decision.response,
                outcome=outcome,
            )

        # 3. Hard bound: 5+ initial tool calls → ModelError before execution
        if len(tool_calls) > MAX_TOOL_CALLS_PER_RUN:
            raise ModelError(
                f"Maximum {MAX_TOOL_CALLS_PER_RUN} initial tool calls allowed, "
                f"got {len(tool_calls)}"
            )

        # 4. Duplicate non-None call_id rejection before any execution
        _reject_duplicate_call_ids(tool_calls)

        # 5. Multi-call WRITE safety: reject any batch containing a WRITE
        #    tool before executing any call.
        if len(tool_calls) > 1:
            _reject_multi_call_containing_write(
                tool_calls,
                initial_decision.exposed_tools,
            )

        # 6. Execute tool calls sequentially
        from dnd_assistant.models.types import ChatRequest

        tool_executions: list[AgentToolExecutionResult] = []
        for tool_call in tool_calls:
            execution = self._tool_execution_service.execute(
                initial_decision,
                tool_call,
                execution_context=execution_context,
            )
            tool_executions.append(execution)

        # 7. Build follow-up request with exact ordered history.
        #    Order: SYSTEM, USER, ASSISTANT(tool calls), TOOL(result 0),
        #    TOOL(result 1), ...
        followup_messages = [
            *initial_decision.request.messages,
            initial_decision.response.message,
        ]
        for execution in tool_executions:
            followup_messages.append(execution.tool_message)

        followup_request = ChatRequest(messages=tuple(followup_messages))

        # 8. Second model call with exact first-turn exposure snapshot
        second_response = self._model_gateway.chat_with_tools(
            followup_request,
            list(initial_decision.exposed_tools),
        )

        # 9. Bound enforcement: second response must have zero tool calls
        if second_response.message.tool_calls:
            raise ModelError(
                "S9-05 does not support post-tool tool calls. "
                "The model requested another tool after receiving a tool result."
            )

        # 10. Parse terminal outcome from second response
        outcome = _parse_agent_outcome(second_response)

        return AgentRunResult(
            initial_decision=initial_decision,
            tool_executions=tuple(tool_executions),
            final_response=second_response,
            outcome=outcome,
        )
