"""PAIM-C37: Offline candidate object-graph construction preflight.

These tests prove that the exact candidate object-graph constructor paths
used by the PAIM-13 live eval fixtures can be constructed and executed
deterministically without Ollama, network, or environment variables.

A skipped live module is not sufficient evidence that its fixture object
graph can be constructed.  This module provides the authoritative offline
proof for both Layer A and Layer B candidate paths.

All tests are offline-safe: no network, no model, no Ollama.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dnd_assistant.application.pydantic_ai_fast_agent import (
        PydanticAIFastAgent,
    )

# ==============================================================================
# PAIM-C37 — Layer A: PydanticAIFastAgent construction + deterministic decide
# ==============================================================================


class TestPaim13LayerACandidateConstruction:
    """Offline construction preflight for Layer A candidate (decision).

    Proves:
        build_eval_registry(state)
        → build_tool_registry_schema(registry)
        → PydanticAIToolBridge(registry=...)
        → DndAgentRunPreparer
        → PydanticAIFastAgent
        → deterministic decide() succeeds
    """

    @staticmethod
    def _build_layer_a_candidate() -> PydanticAIFastAgent:
        """Build the Layer A candidate object graph matching live fixture."""
        from dnd_assistant.application.pydantic_ai_fast_agent import (
            PydanticAIFastAgent,
        )
        from dnd_assistant.application.pydantic_ai_run_deps import (
            DndAgentRunPreparer,
        )
        from dnd_assistant.application.pydantic_ai_tool_bridge import (
            PydanticAIToolBridge,
        )
        from dnd_assistant.tools.catalog import build_tool_registry_schema
        from tests.support.paim13_live_harness import (
            build_eval_registry,
            make_deterministic_context_builder,
        )
        from tests.support.paim13_scenarios import EvalHandlerState
        from tests.support.test_doubles import FakeModel

        state = EvalHandlerState()
        registry = build_eval_registry(state)
        catalog = build_tool_registry_schema(registry)
        context_builder = make_deterministic_context_builder()

        tool_bridge = PydanticAIToolBridge(registry=registry)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=catalog,
            tool_bridge=tool_bridge,
        )

        model = FakeModel()
        agent = PydanticAIFastAgent(run_preparer=preparer, model=model)
        return agent

    def test_layer_a_candidate_constructs(self) -> None:
        """Layer A candidate object graph constructs without error."""
        agent = self._build_layer_a_candidate()
        assert agent is not None

    def test_layer_a_candidate_decide_succeeds(self) -> None:
        """Layer A candidate one deterministic decide() succeeds."""
        from dnd_assistant.tools.types import (
            ExecutionContext,
            Permission,
            SessionMode,
        )

        agent = self._build_layer_a_candidate()
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        decision = agent.decide("Hello", execution_context=ctx)
        assert decision is not None
        assert decision.response is not None


# ==============================================================================
# PAIM-C37 — Layer B: PydanticAIAgentRuntime construction + deterministic run
# ==============================================================================


class TestPaim13LayerBCandidateConstruction:
    """Offline construction preflight for Layer B candidate (full-turn).

    Proves:
        build_eval_registry(state)
        → build_tool_registry_schema(registry)
        → PydanticAIToolBridge(registry=...)
        → DndAgentRunPreparer
        → PydanticAIFastAgent
        → PydanticAIAgentRuntime
        → deterministic run() succeeds
    """

    @staticmethod
    def _build_layer_b_candidate():
        """Build the Layer B candidate object graph matching live fixture."""
        from dnd_assistant.application.pydantic_ai_agent_runtime import (
            PydanticAIAgentRuntime,
        )
        from dnd_assistant.application.pydantic_ai_fast_agent import (
            PydanticAIFastAgent,
        )
        from dnd_assistant.application.pydantic_ai_run_deps import (
            DndAgentRunPreparer,
        )
        from dnd_assistant.application.pydantic_ai_tool_bridge import (
            PydanticAIToolBridge,
        )
        from dnd_assistant.tools.catalog import build_tool_registry_schema
        from tests.support.paim13_live_harness import (
            build_eval_registry,
            make_deterministic_context_builder,
        )
        from tests.support.paim13_scenarios import EvalHandlerState
        from tests.support.test_doubles import FakeModel

        state = EvalHandlerState()
        registry = build_eval_registry(state)
        catalog = build_tool_registry_schema(registry)
        context_builder = make_deterministic_context_builder()

        tool_bridge = PydanticAIToolBridge(registry=registry)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=catalog,
            tool_bridge=tool_bridge,
        )

        model = FakeModel()

        # Layer B needs both FastAgent (for warm-up) and Runtime
        fast_agent = PydanticAIFastAgent(run_preparer=preparer, model=model)
        runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=model)
        return fast_agent, runtime

    def test_layer_b_candidate_constructs(self) -> None:
        """Layer B candidate object graph constructs without error."""
        fast_agent, runtime = self._build_layer_b_candidate()
        assert fast_agent is not None
        assert runtime is not None

    def test_layer_b_candidate_run_succeeds(self) -> None:
        """Layer B candidate one deterministic run() succeeds."""
        from dnd_assistant.application.pydantic_ai_agent_runtime import (
            PydanticAIAgentRuntime,
        )
        from dnd_assistant.application.pydantic_ai_run_deps import (
            DndAgentRunPreparer,
        )
        from dnd_assistant.application.pydantic_ai_tool_bridge import (
            PydanticAIToolBridge,
        )
        from dnd_assistant.tools.catalog import build_tool_registry_schema
        from dnd_assistant.tools.types import (
            ExecutionContext,
            Permission,
            SessionMode,
        )
        from tests.support.paim13_live_harness import (
            build_eval_registry,
            make_deterministic_context_builder,
        )
        from tests.support.paim13_scenarios import EvalHandlerState
        from tests.support.test_doubles import WarmupFakeModel

        state = EvalHandlerState()
        registry = build_eval_registry(state)
        catalog = build_tool_registry_schema(registry)
        context_builder = make_deterministic_context_builder()

        tool_bridge = PydanticAIToolBridge(registry=registry)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=catalog,
            tool_bridge=tool_bridge,
        )

        model = WarmupFakeModel()
        runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=model)
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        result = runtime.run("Hello", execution_context=ctx)
        assert result is not None
        assert result.initial_decision is not None


# ==============================================================================
# PAIM-C37 — Regression: positional PydanticAIToolBridge call must fail
# ==============================================================================


class TestPydanticAIToolBridgePositionalRegression:
    """Regression: positional PydanticAIToolBridge(registry) must fail.

    The constructor requires keyword-only ``registry=``.  A positional call
    must raise ``TypeError``.  This regression would have caught the PAIM-13
    live eval fixture defect before the first live attempt.
    """

    def test_positional_call_raises_type_error(self) -> None:
        """PydanticAIToolBridge(cand_registry) raises TypeError."""
        import pytest

        from dnd_assistant.application.pydantic_ai_tool_bridge import (
            PydanticAIToolBridge,
        )
        from dnd_assistant.tools.registry import ToolRegistry

        registry = ToolRegistry()
        with pytest.raises(TypeError):
            PydanticAIToolBridge(registry)  # type: ignore[call-arg]

    def test_keyword_call_succeeds(self) -> None:
        """PydanticAIToolBridge(registry=registry) succeeds."""
        from dnd_assistant.application.pydantic_ai_tool_bridge import (
            PydanticAIToolBridge,
        )
        from dnd_assistant.tools.registry import ToolRegistry

        registry = ToolRegistry()
        bridge = PydanticAIToolBridge(registry=registry)
        assert bridge is not None
