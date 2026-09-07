"""Pydantic AI one-step FastAgent decision boundary (PAIM-07).

This module provides the migration replacement for the custom ``FastAgent``
first-decision mechanics.  It performs exactly one Pydantic AI model request
and adapts the framework response into the existing provider-neutral
``AgentDecision`` DTO.

Architecture
────────────

::

    DndAgentRunPreparer.prepare(user_input, execution_context=...)
        │
        └── PreparedDndAgentRun  (deps + exposed_tools)

    PydanticAIFastAgent.decide(user_input, execution_context=...)
        │
        ├── 1. DndAgentRunPreparer.prepare(...)
        ├── 2. build_agent_request(prepared.deps.agent_context)
        ├── 3. fresh ExternalToolset from issued snapshot
        ├── 4. one Pydantic AI model request (request_limit=1)
        ├── 5. adapt text / DeferredToolRequests to ToolAwareResponse
        └── 6. return AgentDecision

Ownership
─────────

Owned here:
    PydanticAIFastAgent — migration first-decision runtime.

Owned elsewhere (unchanged):
    DndAgentRunPreparer — preparation orchestration.
    build_agent_request — deterministic request projection (fast_agent.py).
    AgentDecision, ToolAwareResponse, ToolCall — provider-neutral DTOs.

This module must not import from::
    dnd_assistant.models.gateway
    dnd_assistant.models.ollama
    dnd_assistant.storage
    dnd_assistant.retrieval
    dnd_assistant.cli
    dnd_assistant.tools.executor
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import Agent, UsageLimits
from pydantic_ai.exceptions import AgentRunError
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.tools import DeferredToolRequests

from dnd_assistant.errors import ModelError
from dnd_assistant.prompts.agent_v2 import PROMPT_VERSION

if TYPE_CHECKING:
    from dnd_assistant.application.fast_agent import AgentDecision
    from dnd_assistant.application.pydantic_ai_run_deps import (
        DndAgentRunPreparer,
        PreparedDndAgentRun,
    )
    from dnd_assistant.models.types import ToolAwareResponse, ToolCall
    from dnd_assistant.tools.types import ExecutionContext


class PydanticAIFastAgent:
    """One-step Pydantic AI FastAgent decision boundary.

    Performs exactly one Pydantic AI model request and adapts the framework
    response into the existing provider-neutral ``AgentDecision`` DTO.

    Args:
        run_preparer: The ``DndAgentRunPreparer`` for context/tool preparation.
        model: A Pydantic AI ``Model`` instance (provider-agnostic).

    Raises:
        TypeError: If ``run_preparer`` is not a ``DndAgentRunPreparer`` or
            ``model`` is not a Pydantic AI ``Model``.
    """

    def __init__(
        self,
        *,
        run_preparer: DndAgentRunPreparer,
        model: Model,
    ) -> None:
        from dnd_assistant.application.pydantic_ai_run_deps import (
            DndAgentRunPreparer as DARP,
        )

        if not isinstance(run_preparer, DARP):
            raise TypeError(
                f"run_preparer must be a DndAgentRunPreparer instance, "
                f"got {type(run_preparer).__name__}"
            )
        if not isinstance(model, Model):
            raise TypeError(
                f"model must be a Pydantic AI Model instance, got {type(model).__name__}"
            )

        self._run_preparer = run_preparer
        self._model = model

    def decide(
        self,
        user_input: str,
        *,
        execution_context: ExecutionContext,
    ) -> AgentDecision:
        """Perform exactly one Pydantic AI model decision step.

        Args:
            user_input: The validated user query string.
            execution_context: Trusted Python execution context for tool
                exposure filtering.

        Returns:
            An ``AgentDecision`` snapshot with provider-neutral DTOs.

        Raises:
            ValidationError: Propagated from ``DndAgentRunPreparer`` for
                malformed input or context.
            ModelError: If the framework model request fails, the model
                requests an unknown/hidden tool, arguments are malformed,
                or any other framework error occurs.
        """
        from dnd_assistant.application.fast_agent import (
            AgentDecision,
            build_agent_request,
        )

        # 1. Prepare run (validates input, builds context, selects tools,
        #    issues snapshot, creates fresh policy)
        prepared = self._run_preparer.prepare(
            user_input,
            execution_context=execution_context,
        )

        # 2. Build exact provider-neutral AgentDecision.request
        request = build_agent_request(prepared.deps.agent_context)

        # 3. Fresh ExternalToolset from the issued snapshot
        external_toolset = prepared.deps.tool_bridge.to_external_toolset(
            prepared.deps.tool_snapshot,
        )

        # 4. Build framework Agent with:
        #    - instructions = SYSTEM_PROMPT only (campaign context is USER data)
        #    - output_type = str | DeferredToolRequests
        #    - retries = 0 (tools and output)
        #    - request_limit = 1 (exactly one model request)
        from dnd_assistant.prompts.agent_v2 import SYSTEM_PROMPT

        agent = Agent(
            self._model,
            deps_type=type(prepared.deps),
            instructions=SYSTEM_PROMPT,
            output_type=str | DeferredToolRequests,
            retries={"tools": 0, "output": 0},
        )

        # 5. Perform exactly one model request
        user_payload = request.messages[1].content or ""
        try:
            result = agent.run_sync(
                user_payload,
                deps=prepared.deps,
                toolsets=[external_toolset],
                usage_limits=UsageLimits(request_limit=1),
            )
        except AgentRunError as exc:
            raise ModelError(
                "Pydantic AI model request failed",
                cause=exc,
            ) from exc

        # 6. Adapt framework result to ToolAwareResponse
        response = _adapt_result(result, prepared)

        # 7. Return AgentDecision
        return AgentDecision(
            prompt_version=PROMPT_VERSION,
            request=request,
            exposed_tools=prepared.exposed_tools,
            response=response,
        )


# ── Framework result adaptation ────────────────────────────────────────────────


def _adapt_result(
    result: object,
    prepared: PreparedDndAgentRun,
) -> ToolAwareResponse:
    """Adapt a Pydantic AI ``AgentRunResult`` to a project ``ToolAwareResponse``.

    Args:
        result: The framework ``AgentRunResult`` from ``run_sync``.
        prepared: The prepared run (for snapshot resolution).

    Returns:
        A ``ToolAwareResponse`` with adapted text and/or tool calls.

    Raises:
        ModelError: If the result type is unexpected or tool-call adaptation
            fails.
    """
    from dnd_assistant.models.types import ChatMessage, MessageRole, ToolAwareResponse

    # Access the public AgentRunResult API
    # result.output is either str or DeferredToolRequests
    output = result.output

    if isinstance(output, str):
        # Text-only response
        return ToolAwareResponse(
            message=ChatMessage(
                role=MessageRole.ASSISTANT,
                content=output,
                tool_calls=(),
            ),
        )

    if isinstance(output, DeferredToolRequests):
        # Tool-only or text+tool response
        # DeferredToolRequests has .calls (external tool calls) and
        # .approvals (empty for external tools)
        calls = list(output.calls)

        # Check for unexpected approval requests
        if output.approvals:
            raise ModelError(
                "Unexpected approval requests in DeferredToolRequests. "
                "This project exposes external tools, not approval tools."
            )

        # Also capture any text from the raw ModelResponse
        # We need to get the raw response to check for TextParts
        from pydantic_ai.messages import TextPart

        raw_response = result.response
        text_parts: list[str] = []
        for part in raw_response.parts:
            if isinstance(part, TextPart):
                text_parts.append(part.content)

        text_content = " ".join(text_parts) if text_parts else None

        # Adapt tool calls
        adapted_calls = _adapt_tool_calls(calls, prepared)

        return ToolAwareResponse(
            message=ChatMessage(
                role=MessageRole.ASSISTANT,
                content=text_content,
                tool_calls=tuple(adapted_calls),
            ),
        )

    raise ModelError(
        f"Unexpected Pydantic AI output type: {type(output).__name__}. "
        "Expected str or DeferredToolRequests."
    )


def _adapt_tool_calls(
    calls: list[ToolCallPart],
    prepared: PreparedDndAgentRun,
) -> list[ToolCall]:
    """Adapt framework ``ToolCallPart`` values to project ``ToolCall`` DTOs.

    Args:
        calls: The framework tool call parts from ``DeferredToolRequests.calls``.
        prepared: The prepared run (for snapshot name validation).

    Returns:
        A list of project ``ToolCall`` instances in the original order.

    Raises:
        ModelError: If any tool name is not in the frozen snapshot, or if
            the arguments cannot be represented as a JSON object.
    """
    from dnd_assistant.models.types import ToolCall as ProjectToolCall

    snapshot_names = prepared.deps.tool_snapshot.names
    adapted: list[ProjectToolCall] = []

    for call in calls:
        # Validate tool name against snapshot
        if call.tool_name not in snapshot_names:
            raise ModelError(
                f"Tool call '{call.tool_name}' is not in the frozen exposure "
                "snapshot. Unknown or hidden tools are not allowed."
            )

        # Convert arguments — fail closed on malformed/non-object JSON
        try:
            args = call.args_as_dict(raise_if_invalid=True)
        except (ValueError, AssertionError) as exc:
            raise ModelError(
                f"Failed to parse arguments for tool '{call.tool_name}': {exc}",
                cause=exc,
            ) from exc

        # Build project ToolCall (validates non-finite JSON values)
        try:
            project_call = ProjectToolCall(
                name=call.tool_name,
                arguments=args,
                call_id=call.tool_call_id,
            )
        except (ValueError, AssertionError) as exc:
            raise ModelError(
                f"Failed to construct ToolCall for '{call.tool_name}': {exc}",
                cause=exc,
            ) from exc

        adapted.append(project_call)

    return adapted
