"""Offline tests for PAIM-13 live eval harness infrastructure.

All offline — no network, no model, no Ollama.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from tests.support.paim13_live_harness import CountingPydanticModel
from tests.support.test_doubles import FakeModel, RaisingFakeModel

if TYPE_CHECKING:
    from dnd_assistant.application.fast_agent import FastAgent
    from dnd_assistant.application.pydantic_ai_fast_agent import (
        PydanticAIFastAgent,
    )

# ==============================================================================
# CountingPydanticModel — literal request counting (C29-M01 through C29-M05)
# ==============================================================================


class TestCountingPydanticModelLiteral:
    """Literal async tests for CountingPydanticModel request counting.

    C29-M01: wrapper is instance of Model (in test_pydantic_ai_eval.py)
    C29-M02: one request → count == 1, delegate called once
    C29-M03: two requests → count == 2
    C29-M04: delegate raises → count == 1, exception propagates
    C29-M05: request_stream delegates and does not corrupt non-stream count
    """

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _run(coro):
        """Run an async coroutine synchronously via asyncio."""
        return asyncio.run(coro)

    # ── C29-M02 ──────────────────────────────────────────────────────────

    def test_one_request_increments_count(self) -> None:
        """C29-M02: one request → count == 1, delegate called once."""

        async def _test() -> None:
            fake = FakeModel()
            counter = CountingPydanticModel(fake)

            pre = fake.invocation_count
            response = await counter.request(
                messages=[],
                model_settings=None,
                model_request_parameters=None,  # type: ignore[arg-type]
            )

            assert counter.state.request_count == 1
            assert fake.invocation_count == pre + 1
            assert response.parts[0].content == "ok"

        self._run(_test())

    # ── C29-M03 ──────────────────────────────────────────────────────────

    def test_two_requests_increments_count(self) -> None:
        """C29-M03: two requests → count == 2."""

        async def _test() -> None:
            fake = FakeModel()
            counter = CountingPydanticModel(fake)

            await counter.request(messages=[], model_settings=None, model_request_parameters=None)  # type: ignore[arg-type]
            await counter.request(messages=[], model_settings=None, model_request_parameters=None)  # type: ignore[arg-type]

            assert counter.state.request_count == 2
            assert fake.invocation_count == 2

        self._run(_test())

    # ── C29-M04 ──────────────────────────────────────────────────────────

    def test_failed_request_is_counted(self) -> None:
        """C29-M04: delegate raises → attempted request count == 1,
        exact exception propagates."""

        async def _test() -> None:
            raising = RaisingFakeModel()
            counter = CountingPydanticModel(raising)

            import pytest

            with pytest.raises(RuntimeError, match="Simulated model failure"):
                await counter.request(
                    messages=[],
                    model_settings=None,
                    model_request_parameters=None,  # type: ignore[arg-type]
                )

            # The failed semantic request is still counted as an attempt
            assert counter.state.request_count == 1

        self._run(_test())

    # ── C29-M05 ──────────────────────────────────────────────────────────

    def test_request_stream_delegates(self) -> None:
        """C29-M05: request_stream delegates correctly and does not
        corrupt non-stream semantic request count.

        Uses ``WrapperModel``'s inherited ``request_stream``
        (``@asynccontextmanager`` that yields a ``StreamedResponse``).
        """

        async def _test() -> None:
            from pydantic_ai.models import ModelRequestParameters

            fake = FakeModel()
            counter = CountingPydanticModel(fake)
            params = ModelRequestParameters(function_tools=[])

            # WrapperModel.request_stream is an @asynccontextmanager
            # that delegates to the wrapped model's request_stream.
            async with counter.request_stream(
                messages=[],
                model_settings=None,
                model_request_parameters=params,
            ) as stream:
                # StreamedResponse is an async iterable; verify it delegates
                # (CompletedStreamedResponse with no events is empty)
                _ = stream

            # request_stream must not increment the non-stream request count
            assert counter.state.request_count == 0

        self._run(_test())

    def test_stream_does_not_affect_non_stream_count(self) -> None:
        """request_stream does not corrupt non-stream semantic request count
        when both paths are used."""

        async def _test() -> None:
            from pydantic_ai.models import ModelRequestParameters

            fake = FakeModel()
            counter = CountingPydanticModel(fake)
            params = ModelRequestParameters(function_tools=[])

            # One stream call (async with, not async for)
            async with counter.request_stream(
                messages=[],
                model_settings=None,
                model_request_parameters=params,
            ) as stream:
                async for _chunk in stream:
                    pass

            # One non-stream call
            await counter.request(messages=[], model_settings=None, model_request_parameters=params)

            # Only the non-stream call should be counted
            assert counter.state.request_count == 1

        self._run(_test())


# ==============================================================================
# CountingPydanticModel — exact response identity/value preservation
# ==============================================================================


class TestCountingPydanticModelResponsePreservation:
    """Verify that CountingPydanticModel preserves exact response."""

    @staticmethod
    def _run(coro):
        return asyncio.run(coro)

    def test_response_identity_preserved(self) -> None:
        """Exact response identity/value preserved through wrapper."""

        async def _test() -> None:
            fake = FakeModel()
            counter = CountingPydanticModel(fake)

            response = await counter.request(
                messages=[],
                model_settings=None,
                model_request_parameters=None,  # type: ignore[arg-type]
            )

            assert response.parts[0].content == "ok"
            assert len(response.parts) == 1

        self._run(_test())


# ==============================================================================
# Architecture assertions — CountingPydanticModel exact type evidence
# ==============================================================================


class TestCountingPydanticModelArchitecture:
    """Offline architecture assertions for CountingPydanticModel.

    These verify that the counting model satisfies the Pydantic AI Model
    contract required by production constructors.
    """

    def test_isinstance_model(self) -> None:
        """CountingPydanticModel is an isinstance of Model."""
        from pydantic_ai.models import Model as PydanticModel

        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        assert isinstance(counter, PydanticModel)

    def test_isinstance_wrapper_model(self) -> None:
        """CountingPydanticModel is an isinstance of WrapperModel."""
        from pydantic_ai.models.wrapper import WrapperModel

        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        assert isinstance(counter, WrapperModel)

    def test_settings_preserved_default(self) -> None:
        """CountingPydanticModel.settings == delegate.settings (default None)."""
        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        assert counter.settings == fake.settings

    def test_settings_preserved_non_default(self) -> None:
        """CountingPydanticModel.settings == delegate.settings (non-default)."""
        from pydantic_ai.settings import ModelSettings

        fake = FakeModel(settings=ModelSettings(temperature=0.5, max_tokens=100))
        counter = CountingPydanticModel(fake)
        assert counter.settings == fake.settings
        assert counter.settings == {"temperature": 0.5, "max_tokens": 100}

    def test_profile_preserved(self) -> None:
        """CountingPydanticModel.profile == delegate.profile."""
        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        assert counter.profile == fake.profile

    def test_model_name_preserved(self) -> None:
        """CountingPydanticModel.model_name == delegate.model_name."""
        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        assert counter.model_name == fake.model_name

    def test_system_preserved(self) -> None:
        """CountingPydanticModel.system == delegate.system."""
        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        assert counter.system == fake.system

    def test_base_url_preserved_with_non_none(self) -> None:
        """CountingPydanticModel forwards a non-None base_url from the delegate."""

        fake = FakeModel(base_url="http://test-ollama:11434/v1")
        counter = CountingPydanticModel(fake)
        assert counter.base_url == "http://test-ollama:11434/v1"
        assert counter.base_url == fake.base_url

    def test_base_url_preserved_none(self) -> None:
        """CountingPydanticModel forwards None base_url from the delegate."""

        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        assert counter.base_url is None
        assert counter.base_url == fake.base_url

    def test_model_id_preserved(self) -> None:
        """CountingPydanticModel.model_id == delegate.model_id."""
        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        assert counter.model_id == fake.model_id

    def test_customize_request_parameters_delegation(self) -> None:
        """CountingPydanticModel delegates customize_request_parameters."""
        from pydantic_ai.models import ModelRequestParameters

        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        params = ModelRequestParameters(function_tools=[])
        result = counter.customize_request_parameters(params)
        assert result == fake.customize_request_parameters(params)

    def test_request_preparation_transparency(self) -> None:
        """CountingPydanticModel does not alter request/tool shape.

        Verifies that ``prepare_request()`` on the wrapper produces the
        same result as on the delegate when given identical inputs.
        """
        from pydantic_ai.models import ModelRequestParameters

        fake = FakeModel()
        counter = CountingPydanticModel(fake)

        params = ModelRequestParameters(function_tools=[])
        fake_result = fake.prepare_request(model_settings=None, model_request_parameters=params)
        counter_result = counter.prepare_request(
            model_settings=None, model_request_parameters=params
        )

        # The merged settings and customized parameters should be equivalent
        assert fake_result[0] == counter_result[0], "merged model_settings must match"
        # ModelRequestParameters dataclass equality works field-by-field
        assert fake_result[1] == counter_result[1], "customized ModelRequestParameters must match"

    def test_pydantic_ai_fast_agent_construction(self) -> None:
        """PydanticAIFastAgent accepts CountingPydanticModel."""
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
        from dnd_assistant.tools.registry import ToolRegistry
        from tests.support.paim13_live_harness import (
            make_deterministic_context_builder,
        )

        registry = ToolRegistry()
        tool_bridge = PydanticAIToolBridge(registry=registry)
        context_builder = make_deterministic_context_builder()
        catalog = build_tool_registry_schema(registry)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=catalog,
            tool_bridge=tool_bridge,
        )

        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        agent = PydanticAIFastAgent(run_preparer=preparer, model=counter)
        assert agent is not None

    def test_pydantic_ai_agent_runtime_construction(self) -> None:
        """PydanticAIAgentRuntime accepts CountingPydanticModel."""
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
        from dnd_assistant.tools.registry import ToolRegistry
        from tests.support.paim13_live_harness import (
            make_deterministic_context_builder,
        )

        registry = ToolRegistry()
        tool_bridge = PydanticAIToolBridge(registry=registry)
        context_builder = make_deterministic_context_builder()
        catalog = build_tool_registry_schema(registry)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=catalog,
            tool_bridge=tool_bridge,
        )

        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=counter)
        assert runtime is not None


# ==============================================================================
# Metric label contract — all 11 labels in fixed order
# ==============================================================================


class TestMetricLabels:
    """Verify that all 11 metric labels map to the intended metric in fixed
    order, independent of numerator values."""

    def test_all_metric_labels_in_fixed_order(self) -> None:
        """All 11 metric labels are in the correct fixed order."""
        # Import the label dict from the decision eval module

        # Use import via path since it's a test module
        from tests.integration.test_pydantic_ai_stage9_live_eval_decision import (
            _METRIC_LABELS,
        )

        expected = {
            0: "SCENARIO_SUCCESS",
            1: "TOOL_NAME_ACCURACY",
            2: "ARGUMENT_EXACT",
            3: "SCHEMA_VALID",
            4: "FALSE_TOOL_CALL",
            5: "MISSED_TOOL_CALL",
            6: "CORRECT_ABSTENTION",
            7: "CLARIFICATION",
            8: "FALSE_WRITE",
            9: "HIDDEN_WRITE",
            10: "UNNECESSARY_CALLS",
        }

        assert _METRIC_LABELS == expected
        assert len(_METRIC_LABELS) == 11

    def test_labels_used_by_position_not_numerator(self) -> None:
        """The label lookup uses position (index), not numerator value."""
        # This test verifies the lookup pattern in the decision eval module
        # uses enumerate-based position lookup, not _METRIC_LABELS.get(numerator, ...)
        import ast
        from pathlib import Path

        decision_path = (
            Path(__file__).resolve().parent.parent.parent
            / "tests"
            / "integration"
            / "test_pydantic_ai_stage9_live_eval_decision.py"
        )
        source = decision_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        # Find the for loop in test_report_aggregate_metrics
        # that iterates over zipped metrics
        found_enumerate = False
        found_numerator_lookup = False
        for node in ast.walk(tree):
            if isinstance(node, ast.For):
                # Check if the target uses enumerate
                if isinstance(node.iter, ast.Call):
                    func = node.iter.func
                    if isinstance(func, ast.Name) and func.id == "enumerate":
                        found_enumerate = True
                        # Check inner body for _METRIC_LABELS[index] pattern
                        for child in ast.walk(node):
                            if isinstance(child, ast.Subscript):
                                if (
                                    isinstance(child.value, ast.Name)
                                    and child.value.id == "_METRIC_LABELS"
                                ):
                                    found_numerator_lookup = (
                                        isinstance(child.slice, ast.Name)
                                        and child.slice.id == "index"
                                    )

        assert found_enumerate, (
            "The metric label loop must use enumerate() for position-based lookup"
        )
        assert found_numerator_lookup, (
            "The metric label lookup must use _METRIC_LABELS[index] "
            "not _METRIC_LABELS.get(numerator, ...)"
        )


# ==============================================================================
# Harness-drift guards — request/context equality
# ==============================================================================


class TestPaim13RequestContextEquality:
    """Harness-drift guards: verify reference and candidate runtimes
    produce equivalent ``AgentDecision.request`` and
    ``AgentDecision.exposed_tools`` for the same scenario input.

    Uses deterministic context builder and deterministic model adapters.
    No network, no Ollama.
    """

    def _build_reference_decision(self, user_input: str, context: Any):
        """Build a reference ``AgentDecision`` using FastAgent + FakeModelGateway."""
        from dnd_assistant.application.fast_agent import FastAgent
        from dnd_assistant.tools.catalog import build_tool_registry_schema
        from tests.support.paim13_live_harness import (
            build_eval_registry,
            make_deterministic_context_builder,
        )
        from tests.support.paim13_scenarios import EvalHandlerState
        from tests.support.test_doubles import FakeModelGateway

        state = EvalHandlerState()
        registry = build_eval_registry(state)
        catalog = build_tool_registry_schema(registry)
        context_builder = make_deterministic_context_builder()

        agent = FastAgent(
            context_builder=context_builder,
            model_gateway=FakeModelGateway(),
            tool_catalog=catalog,
        )
        return agent.decide(user_input, execution_context=context)

    def _build_candidate_decision(self, user_input: str, context: Any):
        """Build a candidate ``AgentDecision`` using PydanticAIFastAgent + FakeModel."""
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
            CountingPydanticModel,
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
        model = CountingPydanticModel(FakeModel())
        agent = PydanticAIFastAgent(run_preparer=preparer, model=model)
        return agent.decide(user_input, execution_context=context)

    def test_direct_query_request_and_tools_match(self) -> None:
        """Direct query: reference and candidate produce same request and exposed_tools."""
        from dnd_assistant.tools.types import (
            ExecutionContext,
            Permission,
            SessionMode,
        )

        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        ref = self._build_reference_decision("Tell me about Arlen", ctx)
        cand = self._build_candidate_decision("Tell me about Arlen", ctx)
        assert ref.request == cand.request, "AgentDecision.request must match"
        assert ref.exposed_tools == cand.exposed_tools, "AgentDecision.exposed_tools must match"

    def test_read_query_request_and_tools_match(self) -> None:
        """READ query: reference and candidate produce same request and exposed_tools."""
        from dnd_assistant.tools.types import (
            ExecutionContext,
            Permission,
            SessionMode,
        )

        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        ref = self._build_reference_decision("What is Black Keep?", ctx)
        cand = self._build_candidate_decision("What is Black Keep?", ctx)
        assert ref.request == cand.request
        assert ref.exposed_tools == cand.exposed_tools

    def test_write_query_request_and_tools_match(self) -> None:
        """WRITE query: reference and candidate produce same request and exposed_tools."""
        from dnd_assistant.tools.types import (
            ExecutionContext,
            Permission,
            SessionMode,
        )

        ctx = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.ACTIVE_SESSION,
        )
        ref = self._build_reference_decision("Mark the Moon Gate quest as completed", ctx)
        cand = self._build_candidate_decision("Mark the Moon Gate quest as completed", ctx)
        assert ref.request == cand.request
        assert ref.exposed_tools == cand.exposed_tools

    def test_clarify_query_request_and_tools_match(self) -> None:
        """CLARIFY query: reference and candidate produce same request and exposed_tools."""
        from dnd_assistant.tools.types import (
            ExecutionContext,
            Permission,
            SessionMode,
        )

        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        ref = self._build_reference_decision("Tell me about the NPC", ctx)
        cand = self._build_candidate_decision("Tell me about the NPC", ctx)
        assert ref.request == cand.request
        assert ref.exposed_tools == cand.exposed_tools


# ==============================================================================
# PAIM-C32 — Offline warm-up preflight tests
# ==============================================================================


class TestWarmupPreflight:
    """Offline warm-up preflight tests (PAIM-C32).

    These tests verify that the shared ``_warmup()`` function works correctly
    with deterministic fakes before any live Ollama run.  All tests run
    without network, without Ollama, without env variables.

    Positive tests:
        reference warm-up succeeds
        candidate warm-up succeeds
        zero tool calls
        valid direct terminal

    Negative tests:
        model/runtime exception propagates (warm-up fails)
        tool-calling warm-up response fails
        malformed terminal response fails
    """

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _build_reference_fast_agent() -> FastAgent:
        """Build a reference FastAgent with WarmupFakeModelGateway."""
        from dnd_assistant.application.fast_agent import FastAgent
        from dnd_assistant.tools.catalog import build_tool_registry_schema
        from tests.support.paim13_live_harness import (
            build_eval_registry,
            make_deterministic_context_builder,
        )
        from tests.support.paim13_scenarios import EvalHandlerState
        from tests.support.test_doubles import WarmupFakeModelGateway

        state = EvalHandlerState()
        registry = build_eval_registry(state)
        catalog = build_tool_registry_schema(registry)
        context_builder = make_deterministic_context_builder()
        agent = FastAgent(
            context_builder=context_builder,
            model_gateway=WarmupFakeModelGateway(),
            tool_catalog=catalog,
        )
        return agent

    @staticmethod
    def _build_candidate_fast_agent() -> PydanticAIFastAgent:
        """Build a candidate PydanticAIFastAgent with WarmupFakeModel."""
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
        agent = PydanticAIFastAgent(run_preparer=preparer, model=model)
        return agent

    @staticmethod
    def _build_candidate_with_raising_model() -> PydanticAIFastAgent:
        """Build a candidate agent with a RaisingFakeModel."""
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
        from tests.support.test_doubles import RaisingFakeModel

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
        model = RaisingFakeModel()
        return PydanticAIFastAgent(run_preparer=preparer, model=model)

    @staticmethod
    def _build_reference_with_tool_calling_gateway() -> FastAgent:
        """Build a reference agent with a gateway that returns tool calls."""
        from dnd_assistant.application.fast_agent import FastAgent
        from dnd_assistant.models.types import ChatMessage, MessageRole, ToolAwareResponse, ToolCall
        from dnd_assistant.tools.catalog import build_tool_registry_schema
        from tests.support.paim13_live_harness import (
            build_eval_registry,
            make_deterministic_context_builder,
        )
        from tests.support.paim13_scenarios import EvalHandlerState

        class _ToolCallingGateway:
            """Gateway that returns a tool call instead of terminal text."""

            def chat_with_tools(self, request: object, tools: object) -> ToolAwareResponse:
                return ToolAwareResponse(
                    message=ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content=None,
                        tool_calls=(
                            ToolCall(
                                name="read_npc",
                                arguments={"name": "Arlen"},
                                call_id="warmup-tool-call",
                            ),
                        ),
                    ),
                )

            def chat(self, request: object) -> object:
                return None

            def generate_structured(self, request: object, schema: type) -> object:
                return schema()

            def embed(self, texts: list[str]) -> list[list[float]]:
                return [[0.0] * 4 for _ in texts]

            def health(self) -> object:
                return {"status": "ok"}

        state = EvalHandlerState()
        registry = build_eval_registry(state)
        catalog = build_tool_registry_schema(registry)
        context_builder = make_deterministic_context_builder()
        return FastAgent(
            context_builder=context_builder,
            model_gateway=_ToolCallingGateway(),  # type: ignore[arg-type]
            tool_catalog=catalog,
        )

    @staticmethod
    def _build_reference_with_malformed_gateway() -> FastAgent:
        """Build a reference agent with a gateway that returns unparseable text."""
        from dnd_assistant.application.fast_agent import FastAgent
        from dnd_assistant.models.types import ChatMessage, MessageRole, ToolAwareResponse
        from dnd_assistant.tools.catalog import build_tool_registry_schema
        from tests.support.paim13_live_harness import (
            build_eval_registry,
            make_deterministic_context_builder,
        )
        from tests.support.paim13_scenarios import EvalHandlerState

        class _MalformedGateway:
            """Gateway that returns unparseable text content."""

            def chat_with_tools(self, request: object, tools: object) -> ToolAwareResponse:
                return ToolAwareResponse(
                    message=ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content="not valid json",
                        tool_calls=(),
                    ),
                )

            def chat(self, request: object) -> object:
                return None

            def generate_structured(self, request: object, schema: type) -> object:
                return schema()

            def embed(self, texts: list[str]) -> list[list[float]]:
                return [[0.0] * 4 for _ in texts]

            def health(self) -> object:
                return {"status": "ok"}

        state = EvalHandlerState()
        registry = build_eval_registry(state)
        catalog = build_tool_registry_schema(registry)
        context_builder = make_deterministic_context_builder()
        return FastAgent(
            context_builder=context_builder,
            model_gateway=_MalformedGateway(),  # type: ignore[arg-type]
            tool_catalog=catalog,
        )

    # ── Positive tests ───────────────────────────────────────────────────

    def test_reference_warmup_succeeds(self) -> None:
        """Reference warm-up: PASS, zero tool calls, valid terminal."""
        from tests.integration.test_pydantic_ai_stage9_live_eval_full_turn import (
            _warmup,
        )

        agent = self._build_reference_fast_agent()
        # Must not raise
        _warmup(agent)

    def test_candidate_warmup_succeeds(self) -> None:
        """Candidate warm-up: PASS, zero tool calls, valid terminal."""
        from tests.integration.test_pydantic_ai_stage9_live_eval_full_turn import (
            _warmup,
        )

        agent = self._build_candidate_fast_agent()
        # Must not raise
        _warmup(agent)

    # ── Negative tests ───────────────────────────────────────────────────

    def test_warmup_raises_on_model_exception(self) -> None:
        """Warm-up exception propagates (warm-up fails)."""
        from dnd_assistant.errors import ModelError
        from tests.integration.test_pydantic_ai_stage9_live_eval_full_turn import (
            _warmup,
        )

        agent = self._build_candidate_with_raising_model()
        import pytest

        with pytest.raises((ModelError, RuntimeError)):
            _warmup(agent)

    def test_warmup_raises_on_tool_call_response(self) -> None:
        """Warm-up fails when the model returns a tool call."""
        from tests.integration.test_pydantic_ai_stage9_live_eval_full_turn import (
            _warmup,
        )

        agent = self._build_reference_with_tool_calling_gateway()
        import pytest

        with pytest.raises(RuntimeError, match="Warm-up produced"):
            _warmup(agent)

    def test_warmup_raises_on_malformed_terminal(self) -> None:
        """Warm-up fails when terminal response is malformed."""
        from tests.integration.test_pydantic_ai_stage9_live_eval_full_turn import (
            _warmup,
        )

        agent = self._build_reference_with_malformed_gateway()
        import pytest

        with pytest.raises(RuntimeError, match="no valid terminal outcome"):
            _warmup(agent)
