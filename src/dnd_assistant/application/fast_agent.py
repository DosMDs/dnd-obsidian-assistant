"""One-step Fast Agent decision boundary (S9-02).

This module owns only:

- one-step Fast Agent orchestration
- deterministic model-request construction
- one ``chat_with_tools`` invocation
- turn-local tool allowlist validation
- provider-neutral decision snapshot

It must not own:

- ToolExecutor execution
- handler invocation
- tool argument schema execution
- tool-result conversion / replay
- multi-round loop
- retry policy
- clarification classification
- CLI
- Vault access
- retrieval
- calendar arithmetic
- Ollama transport

Importing this module must NOT eagerly load::

    dnd_assistant.models.ollama
    dnd_assistant.tools.executor
    dnd_assistant.storage
    dnd_assistant.retrieval
    dnd_assistant.cli

PAIM-15 status
──────────────
The shared provider-neutral ``AgentDecision`` DTO, the ``build_agent_request()``
projection and their deterministic serialization helpers now live in
``dnd_assistant.application.agent_contracts``.  The ``FastAgent`` class remains
as explicit test/evidence reference infrastructure only (PAIM-11 parity,
PAIM-13 live comparison) pending PAIM-RETIRE-01.  Production code must import
the shared contracts from ``agent_contracts``, never from this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dnd_assistant.application.agent_contracts import (
    AgentDecision,
    build_agent_request,
)
from dnd_assistant.errors import ModelError
from dnd_assistant.prompts.agent_v2 import PROMPT_VERSION

if TYPE_CHECKING:
    from dnd_assistant.application.agent_context import AgentContextBuilder
    from dnd_assistant.models.gateway import ModelGateway
    from dnd_assistant.tools.catalog import ToolRegistrySchema
    from dnd_assistant.tools.types import ExecutionContext

__all__ = ["AgentDecision", "FastAgent", "build_agent_request"]


# ── FastAgent ───────────────────────────────────────────────────────────────────


class FastAgent:
    """One-step Fast Agent orchestration.

    The ``decide()`` method performs exactly one model decision step:
    tool selection → context building → one ``chat_with_tools`` call →
    tool-name allowlist validation → ``AgentDecision``.
    """

    def __init__(
        self,
        *,
        context_builder: AgentContextBuilder,
        model_gateway: ModelGateway,
        tool_catalog: ToolRegistrySchema,
    ) -> None:
        self._context_builder = context_builder
        self._model_gateway = model_gateway
        self._tool_catalog = tool_catalog

    def decide(
        self,
        user_input: str,
        *,
        execution_context: ExecutionContext,
    ) -> AgentDecision:
        """Perform exactly one model decision step.

        Args:
            user_input: The validated user query string.
            execution_context: Trusted Python execution context for tool
                exposure filtering.

        Returns:
            An ``AgentDecision`` snapshot.

        Raises:
            ModelError: If the model response contains tool calls that
                reference tools not in the turn-local exposure snapshot,
                or if the underlying ``chat_with_tools`` call fails.
        """
        # Deferred runtime imports: keep provider/tool/storage packages out
        # of module-import scope.
        from dnd_assistant.application.agent_tool_selection import select_agent_tools

        # 1. Determine the turn-local exposed-tool snapshot
        exposed_list = select_agent_tools(
            self._tool_catalog,
            context=execution_context,
        )
        exposed_tools = tuple(exposed_list)

        # 2. Build AgentContext
        context = self._context_builder.build(user_input)

        # 3. Build deterministic ChatRequest via shared projection
        request = build_agent_request(context)

        # 4. Call ModelGateway.chat_with_tools() exactly once
        response = self._model_gateway.chat_with_tools(request, exposed_list)

        # 5. Validate all returned ToolCall names against the exact
        #    exposed-tool snapshot
        for call in response.message.tool_calls:
            if not any(call.name == t.name for t in exposed_tools):
                raise ModelError(
                    f"Tool call '{call.name}' is not in the exposed-tool allowlist for this turn"
                )

        # 6. Return AgentDecision
        return AgentDecision(
            prompt_version=PROMPT_VERSION,
            request=request,
            exposed_tools=exposed_tools,
            response=response,
        )
