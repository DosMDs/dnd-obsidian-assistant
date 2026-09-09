"""PAIM-11: Stage-9 behavioral parity — C-equivalent and manual scenarios.

Scenarios P11-A26, A27, A28, and A33 require manual runtime construction
because they test structural boundary conditions (non-finite JSON,
execution failures, second-model failures) that cannot be expressed
through the standard ``run_scenario`` harness.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from dnd_assistant.application.agent_context import AgentContextBuilder
from dnd_assistant.application.agent_loop import AgentLoop
from dnd_assistant.application.agent_tool_execution import (
    AgentToolExecutionService,
)
from dnd_assistant.application.pydantic_ai_agent_runtime import (
    PydanticAIAgentRuntime,
)
from dnd_assistant.application.pydantic_ai_run_deps import (
    DndAgentRunPreparer,
)
from dnd_assistant.application.pydantic_ai_tool_bridge import (
    PydanticAIToolBridge,
)
from dnd_assistant.errors import ModelError
from dnd_assistant.models.types import ToolCall
from dnd_assistant.tools.catalog import ToolPublicDefinition, ToolRegistrySchema
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from tests.support.stage9_parity import (
    HandlerCounters,
    _CountingToolExecutor,
    _FakeModelGateway,
    build_catalog,
    make_context_builder,
    make_read_context,
    make_tool_aware_response,
    make_tool_call,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def ref_counters() -> HandlerCounters:
    return HandlerCounters()


@pytest.fixture
def pyd_counters() -> HandlerCounters:
    return HandlerCounters()


@pytest.fixture
def registry(ref_counters: HandlerCounters) -> ToolRegistry:
    from tests.support.stage9_parity import make_registry

    return make_registry(ref_counters)


@pytest.fixture
def catalog(registry: ToolRegistry) -> ToolRegistrySchema:
    return build_catalog(registry)


@pytest.fixture
def context_builder() -> AgentContextBuilder:
    return make_context_builder()


def _copy_registry_simple(
    source: ToolRegistry,
    dest: ToolRegistry,
    counters: HandlerCounters,
) -> None:
    """Copy tool definitions and handlers from source to dest registry."""
    from tests.support.stage9_parity import ToolOutput as _TO

    for td in source.list_definitions():
        if td.name == "read_alpha":

            def _alpha(inp: Any, ctx: object) -> Any:
                counters.alpha += 1
                return _TO(result=f"alpha:{inp.value}")

            handler = _alpha
        elif td.name == "read_beta":

            def _beta(inp: Any, ctx: object) -> Any:
                counters.beta += 1
                return _TO(result=f"beta:{inp.number}")

            handler = _beta
        elif td.name == "write_alpha":

            def _write(inp: Any, ctx: object) -> Any:
                counters.write_alpha += 1
                return _TO(result=f"write:{inp.value}")

            handler = _write
        else:

            def _other(inp: Any, ctx: object) -> Any:
                counters.alpha += 1
                return _TO(result=f"other:{inp.value}")

            handler = _other

        dest.register(td, handler)


# ==============================================================================
# P11-A26: structurally non-finite JSON argument (C-equivalent)
# ==============================================================================


class TestP11A26NonFiniteJsonArg:
    """P11-A26: structurally non-finite JSON argument — C-equivalent safety.

    Reference ToolCall cannot represent NaN (FiniteJsonValue rejects it).
    Pydantic ToolCallPart can carry NaN but adapt_pydantic_tool_calls
    rejects it. Both fail closed with zero handler execution.
    """

    def test_non_finite_json_arg(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()
        pyd_request_count: list[int] = [0]
        pyd_error: BaseException | None = None

        pyd_registry = ToolRegistry()
        _copy_registry_simple(registry, pyd_registry, pyd_counters)
        tool_bridge = PydanticAIToolBridge(registry=pyd_registry)
        pyd_executor = ToolExecutor(pyd_registry)
        pyd_counting_executor = _CountingToolExecutor(pyd_executor)
        object.__setattr__(tool_bridge, "_executor", pyd_counting_executor)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=catalog,
            tool_bridge=tool_bridge,
        )

        def counting_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            pyd_request_count[0] += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_beta", args={"number": float("nan")}, tool_call_id="c1"
                    )
                ]
            )

        counting_model = FunctionModel(counting_fn)
        pydantic_runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=counting_model)
        try:
            pydantic_runtime.run("read with NaN", execution_context=ctx)
        except BaseException as exc:
            pyd_error = exc

        assert isinstance(pyd_error, ModelError)
        assert pyd_request_count[0] == 1
        assert pyd_counting_executor.execute_count == 0
        assert pyd_counters.beta == 0

        from pydantic import ValidationError as PydValErr

        with pytest.raises(PydValErr):
            ToolCall(name="read_beta", arguments={"number": float("nan")}, call_id="c1")


# ==============================================================================
# P11-A27: structurally non-finite call in batch (C-equivalent)
# ==============================================================================


class TestP11A27StructurallyInvalidBatch:
    """P11-A27: structurally non-finite call in batch — C-equivalent safety.

    Reference batch cannot be constructed with NaN. Pydantic rejects NaN
    during adapt_pydantic_tool_calls preflight before any execution.
    """

    def test_structurally_invalid_batch(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()
        pyd_request_count: list[int] = [0]
        pyd_error: BaseException | None = None

        pyd_registry = ToolRegistry()
        _copy_registry_simple(registry, pyd_registry, pyd_counters)
        tool_bridge = PydanticAIToolBridge(registry=pyd_registry)
        pyd_executor = ToolExecutor(pyd_registry)
        pyd_counting_executor = _CountingToolExecutor(pyd_executor)
        object.__setattr__(tool_bridge, "_executor", pyd_counting_executor)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=catalog,
            tool_bridge=tool_bridge,
        )

        def counting_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            pyd_request_count[0] += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_alpha", args={"value": "ok"}, tool_call_id="c1"),
                    ToolCallPart(
                        tool_name="read_beta", args={"number": float("nan")}, tool_call_id="c2"
                    ),
                    ToolCallPart(
                        tool_name="read_alpha", args={"value": "never"}, tool_call_id="c3"
                    ),
                ]
            )

        counting_model = FunctionModel(counting_fn)
        pydantic_runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=counting_model)
        try:
            pydantic_runtime.run("read with NaN in batch", execution_context=ctx)
        except BaseException as exc:
            pyd_error = exc

        assert isinstance(pyd_error, ModelError)
        assert pyd_request_count[0] == 1
        assert pyd_counting_executor.execute_count == 0
        assert pyd_counters.alpha == 0
        assert pyd_counters.beta == 0

        from pydantic import ValidationError as PydValErr

        with pytest.raises(PydValErr):
            ToolCall(name="read_beta", arguments={"number": float("nan")}, call_id="c2")


# ==============================================================================
# P11-A28: READ #1 succeeds, READ #2 execution fails, READ #3 never runs
# ==============================================================================


class TestP11A28ReadFailFast:
    """P11-A28: READ #1 succeeds, READ #2 execution fails, READ #3 never runs.

    Custom registry where read_beta raises RuntimeError on both runtimes.
    Expected: model_requests=1, executor_attempts=2, handler=(1,1,0).
    """

    def test_read_fail_fast(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()

        from tests.support.stage9_parity import (
            READ_ALPHA_DEF,
            READ_BETA_DEF,
            WRITE_ALPHA_DEF,
            ToolOutput,
        )

        def make_fail_registry(counters: HandlerCounters) -> ToolRegistry:
            reg = ToolRegistry()

            def alpha_ok(inp: Any, ctx_obj: object) -> ToolOutput:
                counters.alpha += 1
                return ToolOutput(result=f"alpha:{inp.value}")

            def beta_fail(inp: Any, ctx_obj: object) -> ToolOutput:
                counters.beta += 1
                raise RuntimeError("simulated handler failure")

            def write_handler(inp: Any, ctx_obj: object) -> ToolOutput:
                counters.write_alpha += 1
                return ToolOutput(result=f"write:{inp.value}")

            reg.register(READ_ALPHA_DEF, alpha_ok)
            reg.register(READ_BETA_DEF, beta_fail)
            reg.register(WRITE_ALPHA_DEF, write_handler)
            return reg

        ref_registry = make_fail_registry(ref_counters)
        pyd_registry = make_fail_registry(pyd_counters)
        ref_catalog_local = build_catalog(ref_registry)
        pyd_catalog_local = build_catalog(pyd_registry)

        tc1 = make_tool_call("read_alpha", {"value": "ok"}, "c1")
        tc2 = make_tool_call("read_beta", {"number": 0}, "c2")
        tc3 = make_tool_call("read_alpha", {"value": "never"}, "c3")
        ref_responses = [make_tool_aware_response(tool_calls=[tc1, tc2, tc3])]

        # Reference
        ref_gateway = _FakeModelGateway(ref_responses)
        ref_executor = ToolExecutor(ref_registry)
        ref_counting = _CountingToolExecutor(ref_executor)
        ref_tool_svc = AgentToolExecutionService(tool_executor=ref_counting)
        ref_loop = AgentLoop(
            context_builder=context_builder,
            model_gateway=ref_gateway,
            tool_catalog=ref_catalog_local,
            tool_execution_service=ref_tool_svc,
        )
        ref_error: BaseException | None = None
        try:
            ref_loop.run("read three with second failing", execution_context=ctx)
        except BaseException as exc:
            ref_error = exc
        ref_model_requests = ref_gateway.call_count

        # Pydantic
        tool_bridge = PydanticAIToolBridge(registry=pyd_registry)
        pyd_executor = ToolExecutor(pyd_registry)
        pyd_counting = _CountingToolExecutor(pyd_executor)
        object.__setattr__(tool_bridge, "_executor", pyd_counting)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=pyd_catalog_local,
            tool_bridge=tool_bridge,
        )
        pyd_request_count: list[int] = [0]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            pyd_request_count[0] += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_alpha", args={"value": "ok"}, tool_call_id="c1"),
                    ToolCallPart(tool_name="read_beta", args={"number": 0}, tool_call_id="c2"),
                    ToolCallPart(
                        tool_name="read_alpha", args={"value": "never"}, tool_call_id="c3"
                    ),
                ]
            )

        counting_model = FunctionModel(pyd_fn)
        pydantic_runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=counting_model)
        pyd_error: BaseException | None = None
        try:
            pydantic_runtime.run("read three with second failing", execution_context=ctx)
        except BaseException as exc:
            pyd_error = exc

        assert ref_error is not None
        assert pyd_error is not None
        assert ref_model_requests == 1
        assert pyd_request_count[0] == 1
        assert ref_counting.execute_count == 2
        assert pyd_counting.execute_count == 2
        assert ref_counters.alpha == 1
        assert ref_counters.beta == 1
        assert pyd_counters.alpha == 1
        assert pyd_counters.beta == 1
        assert isinstance(ref_error, RuntimeError)
        assert isinstance(pyd_error, RuntimeError)


# ==============================================================================
# P11-A33: first tool succeeds, second model request fails
# ==============================================================================


class TestP11A33FirstToolSucceedsSecondFails:
    """P11-A33: first tool succeeds, second model request fails.

    Both runtimes: request #1 -> one READ tool executes, request #2 -> failure.
    Expected: model_requests=2, executor_attempts=1, handler=(1,0,0).
    """

    def test_first_tool_succeeds_second_fails(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()
        tc1 = make_tool_call("read_alpha", {"value": "ok"}, "c1")

        # Reference: fail_on_request=2 raises ModelError
        custom_gateway = _FakeModelGateway(
            [make_tool_aware_response(tool_calls=[tc1])],
            fail_on_request=2,
            fail_exc=ModelError("simulated model failure on second request"),
        )
        ref_executor = ToolExecutor(registry)
        ref_counting = _CountingToolExecutor(ref_executor)
        ref_tool_svc = AgentToolExecutionService(tool_executor=ref_counting)
        public_defs = [
            ToolPublicDefinition(
                name=td.name,
                description=td.description,
                input_schema=td.input_schema.model_json_schema(),
                output_schema=td.output_schema.model_json_schema(),
                permission=td.permission,
                side_effects=list(td.side_effects),
                allowed_session_modes=list(td.allowed_session_modes),
            )
            for td in registry.list_definitions()
        ]
        ref_catalog_local = ToolRegistrySchema(tools=public_defs)
        ref_loop = AgentLoop(
            context_builder=context_builder,
            model_gateway=custom_gateway,
            tool_catalog=ref_catalog_local,
            tool_execution_service=ref_tool_svc,
        )
        ref_error: BaseException | None = None
        try:
            ref_loop.run("tool then crash", execution_context=ctx)
        except BaseException as exc:
            ref_error = exc
        ref_model_requests = custom_gateway.call_count

        # Pydantic
        pyd_error: BaseException | None = None
        pyd_registry = ToolRegistry()
        _copy_registry_simple(registry, pyd_registry, pyd_counters)
        tool_bridge = PydanticAIToolBridge(registry=pyd_registry)
        pyd_executor = ToolExecutor(pyd_registry)
        pyd_counting_executor = _CountingToolExecutor(pyd_executor)
        object.__setattr__(tool_bridge, "_executor", pyd_counting_executor)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=catalog,
            tool_bridge=tool_bridge,
        )
        pyd_request_count: list[int] = [0]

        def counting_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            pyd_request_count[0] += 1
            if pyd_request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha", args={"value": "ok"}, tool_call_id="c1"
                        ),
                    ]
                )
            raise ModelError("simulated second model failure")

        counting_model = FunctionModel(counting_fn)
        pydantic_runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=counting_model)
        try:
            pydantic_runtime.run("tool then crash", execution_context=ctx)
        except BaseException as exc:
            pyd_error = exc

        assert isinstance(ref_error, ModelError)
        assert isinstance(pyd_error, ModelError)
        assert ref_model_requests == 2
        assert pyd_request_count[0] == 2
        assert ref_counting.execute_count == 1
        assert pyd_counting_executor.execute_count == 1
        assert ref_counters.alpha == 1
        assert pyd_counters.alpha == 1


# ==============================================================================
# P11-A29: request #1 -> tool batch, request #2 -> one additional tool call
# ==============================================================================


class TestP11A29SecondRequestOneTool:
    """P11-A29: second request one tool — ModelError.

    Expected: model_requests=2, first batch executes once,
    second batch zero calls, no request #3.
    """

    def test_second_request_one_tool(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()
        from tests.support.stage9_parity import (
            Stage9Scenario,
            assert_parity,
            run_scenario,
        )

        tc1 = make_tool_call("read_alpha", {"value": "first"}, "c1")
        tc2 = make_tool_call("read_alpha", {"value": "second"}, "c2")
        ref_responses = [
            make_tool_aware_response(tool_calls=[tc1]),
            make_tool_aware_response(tool_calls=[tc2]),
        ]
        request_count: list[int] = [0]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha", args={"value": "first"}, tool_call_id="c1"
                        )
                    ]
                )
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha", args={"value": "second"}, tool_call_id="c2"
                    )
                ]
            )

        scenario = Stage9Scenario(
            user_input="second request with tool",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expect_failure=True,
        )
        obs = run_scenario(
            scenario,
            registry=registry,
            catalog=catalog,
            context_builder=context_builder,
            ref_counters=ref_counters,
            pyd_counters=pyd_counters,
        )
        assert_parity(
            obs,
            expect_failure=True,
            expected_model_requests_ref=2,
            expected_model_requests_pyd=2,
            expected_executor_attempts=1,
            expected_handler_counts=(1, 0, 0),
            expected_ref_error_type=ModelError,
            expected_pyd_error_type=ModelError,
        )


# ==============================================================================
# P11-A30: request #1 -> tool batch, request #2 -> multiple additional tool calls
# ==============================================================================


class TestP11A30SecondRequestMultipleTools:
    """P11-A30: second request multiple tools — ModelError.

    Expected: model_requests=2, first batch executes once,
    second batch zero calls, no request #3.
    """

    def test_second_request_multiple_tools(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()
        from tests.support.stage9_parity import (
            Stage9Scenario,
            assert_parity,
            run_scenario,
        )

        tc1 = make_tool_call("read_alpha", {"value": "first"}, "c1")
        tc2 = make_tool_call("read_alpha", {"value": "second"}, "c2")
        tc3 = make_tool_call("read_beta", {"number": 42}, "c3")
        ref_responses = [
            make_tool_aware_response(tool_calls=[tc1]),
            make_tool_aware_response(tool_calls=[tc2, tc3]),
        ]
        request_count: list[int] = [0]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha", args={"value": "first"}, tool_call_id="c1"
                        )
                    ]
                )
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha", args={"value": "second"}, tool_call_id="c2"
                    ),
                    ToolCallPart(tool_name="read_beta", args={"number": 42}, tool_call_id="c3"),
                ]
            )

        scenario = Stage9Scenario(
            user_input="second request with multiple tools",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expect_failure=True,
        )
        obs = run_scenario(
            scenario,
            registry=registry,
            catalog=catalog,
            context_builder=context_builder,
            ref_counters=ref_counters,
            pyd_counters=pyd_counters,
        )
        assert_parity(
            obs,
            expect_failure=True,
            expected_model_requests_ref=2,
            expected_model_requests_pyd=2,
            expected_executor_attempts=1,
            expected_handler_counts=(1, 0, 0),
            expected_ref_error_type=ModelError,
            expected_pyd_error_type=ModelError,
        )
