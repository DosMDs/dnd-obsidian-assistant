"""PAIM-11: Stage-9 behavioral parity — scenarios P11-A24, A25, A31, A32, A34-A36."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

from dnd_assistant.application.agent_context import AgentContextBuilder
from dnd_assistant.application.agent_loop import AgentOutcomeKind
from dnd_assistant.errors import ModelError, ValidationError
from dnd_assistant.tools.catalog import ToolRegistrySchema
from dnd_assistant.tools.registry import ToolRegistry
from tests.support.stage9_parity import (
    HandlerCounters,
    Stage9Scenario,
    assert_parity,
    build_catalog,
    clarify_json,
    make_context_builder,
    make_read_context,
    make_registry,
    make_tool_aware_response,
    make_tool_call,
    make_write_context,
    respond_json,
    run_scenario,
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
    return make_registry(ref_counters)


@pytest.fixture
def catalog(registry: ToolRegistry) -> ToolRegistrySchema:
    return build_catalog(registry)


@pytest.fixture
def context_builder() -> AgentContextBuilder:
    return make_context_builder()


# ==============================================================================
# P11-A24: schema-invalid single tool args
# ==============================================================================


class TestP11A24SchemaInvalidSingle:
    """P11-A24: schema-invalid single tool args — ModelError, 1 executor attempt."""

    def test_schema_invalid_single(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()
        tool_call = make_tool_call(name="read_alpha", arguments={}, call_id="c1")
        ref_responses = [make_tool_aware_response(tool_calls=[tool_call])]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="read_alpha", args={}, tool_call_id="c1")]
            )

        scenario = Stage9Scenario(
            user_input="read with bad args",
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
            expected_model_requests_ref=1,
            expected_model_requests_pyd=1,
            expected_executor_attempts=1,
            expected_handler_counts=(0, 0, 0),
            expected_ref_error_type=ValidationError,
            expected_pyd_error_type=ValidationError,
        )


# ==============================================================================
# P11-A25: schema-invalid second READ in multi batch
# ==============================================================================


class TestP11A25SchemaInvalidSecondRead:
    """P11-A25: schema-invalid second READ — fail-fast, first executes.

    Expected: model_requests=1, executor_attempts=2 (first succeeds,
    second fails schema validation), handler=(1, 0, 0).
    """

    def test_schema_invalid_second_read(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()
        tc1 = make_tool_call(name="read_alpha", arguments={"value": "ok"}, call_id="c1")
        tc2 = make_tool_call(name="read_alpha", arguments={}, call_id="c2")
        ref_responses = [make_tool_aware_response(tool_calls=[tc1, tc2])]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_alpha", args={"value": "ok"}, tool_call_id="c1"),
                    ToolCallPart(tool_name="read_alpha", args={}, tool_call_id="c2"),
                ]
            )

        scenario = Stage9Scenario(
            user_input="read two with second invalid",
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
            expected_model_requests_ref=1,
            expected_model_requests_pyd=1,
            expected_executor_attempts=2,
            expected_handler_counts=(1, 0, 0),
            expected_ref_error_type=ValidationError,
            expected_pyd_error_type=ValidationError,
        )


# ==============================================================================
# P11-A31: malformed direct terminal output
# ==============================================================================


class TestP11A31MalformedDirectOutput:
    """P11-A31: malformed direct terminal output — ModelError, 1 model request."""

    def test_malformed_direct_output(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()
        ref_responses = [make_tool_aware_response(content="not valid JSON at all")]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content="not valid JSON at all")])

        scenario = Stage9Scenario(
            user_input="malformed direct",
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
            expected_model_requests_ref=1,
            expected_model_requests_pyd=1,
            expected_handler_counts=(0, 0, 0),
            expected_executor_attempts=0,
            expected_ref_error_type=ModelError,
            expected_pyd_error_type=ModelError,
        )


# ==============================================================================
# P11-A32: malformed post-tool terminal output
# ==============================================================================


class TestP11A32MalformedPostToolOutput:
    """P11-A32: malformed post-tool terminal output — ModelError, 2 model requests.

    Expected: model_requests=2, executor_attempts=1, handler=(1, 0, 0).
    """

    def test_malformed_post_tool_output(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()
        tc = make_tool_call(name="read_alpha", arguments={"value": "ok"}, call_id="c1")
        ref_responses = [
            make_tool_aware_response(tool_calls=[tc]),
            make_tool_aware_response(content="not valid JSON at all"),
        ]
        request_count: list[int] = [0]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha", args={"value": "ok"}, tool_call_id="c1"
                        )
                    ]
                )
            return ModelResponse(parts=[TextPart(content="not valid JSON at all")])

        scenario = Stage9Scenario(
            user_input="tool then malformed",
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
# P11-A34: direct CLARIFY with WRITE-capable ExecutionContext
# ==============================================================================


class TestP11A34ClarifyWithWriteContext:
    """P11-A34: direct CLARIFY with WRITE-capable context — zero WRITE, zero tools."""

    def test_clarify_with_write_context(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        msg = "Which one?"
        ctx = make_write_context()
        ref_responses = [make_tool_aware_response(content=clarify_json(msg))]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content=clarify_json(msg))])

        scenario = Stage9Scenario(
            user_input="clarify with write context",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expected_outcome_kind=AgentOutcomeKind.CLARIFY,
            expected_outcome_message=msg,
            expected_model_requests_ref=1,
            expected_model_requests_pyd=1,
            expected_tool_executions=0,
            expected_handler_counts=(0, 0, 0),
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
            expected_outcome_kind=AgentOutcomeKind.CLARIFY,
            expected_outcome_message=msg,
            expected_model_requests_ref=1,
            expected_model_requests_pyd=1,
            expected_tool_executions=0,
            expected_handler_counts=(0, 0, 0),
        )


# ==============================================================================
# P11-A35: assistant text + one tool call
# ==============================================================================


class TestP11A35TextAndOneTool:
    """P11-A35: assistant text + one tool call — preserved text + tool."""

    def test_text_and_one_tool(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        msg = "Found it!"
        ctx = make_read_context()
        tc = make_tool_call(name="read_alpha", arguments={"value": "gandalf"}, call_id="c1")
        ref_responses = [
            make_tool_aware_response(content="Looking up Gandalf...", tool_calls=[tc]),
            make_tool_aware_response(content=respond_json(msg)),
        ]
        request_count: list[int] = [0]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        TextPart(content="Looking up Gandalf..."),
                        ToolCallPart(
                            tool_name="read_alpha", args={"value": "gandalf"}, tool_call_id="c1"
                        ),
                    ]
                )
            return ModelResponse(parts=[TextPart(content=respond_json(msg))])

        scenario = Stage9Scenario(
            user_input="find gandalf with text",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expected_outcome_kind=AgentOutcomeKind.RESPOND,
            expected_outcome_message=msg,
            expected_model_requests_ref=2,
            expected_model_requests_pyd=2,
            expected_tool_executions=1,
            expected_handler_counts=(1, 0, 0),
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
            expected_outcome_kind=AgentOutcomeKind.RESPOND,
            expected_outcome_message=msg,
            expected_model_requests_ref=2,
            expected_model_requests_pyd=2,
            expected_tool_executions=1,
            expected_handler_counts=(1, 0, 0),
            check_tool_calls=True,
        )


# ==============================================================================
# P11-A36: assistant text + multiple READ tool calls
# ==============================================================================


class TestP11A36TextAndMultipleTools:
    """P11-A36: assistant text + multiple READ tool calls — preserved text + tools."""

    def test_text_and_multiple_tools(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        msg = "Both done!"
        ctx = make_read_context()
        tc1 = make_tool_call(name="read_alpha", arguments={"value": "first"}, call_id="c1")
        tc2 = make_tool_call(name="read_beta", arguments={"number": 42}, call_id="c2")
        ref_responses = [
            make_tool_aware_response(content="Looking up both...", tool_calls=[tc1, tc2]),
            make_tool_aware_response(content=respond_json(msg)),
        ]
        request_count: list[int] = [0]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        TextPart(content="Looking up both..."),
                        ToolCallPart(
                            tool_name="read_alpha", args={"value": "first"}, tool_call_id="c1"
                        ),
                        ToolCallPart(tool_name="read_beta", args={"number": 42}, tool_call_id="c2"),
                    ]
                )
            return ModelResponse(parts=[TextPart(content=respond_json(msg))])

        scenario = Stage9Scenario(
            user_input="read both with text",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expected_outcome_kind=AgentOutcomeKind.RESPOND,
            expected_outcome_message=msg,
            expected_model_requests_ref=2,
            expected_model_requests_pyd=2,
            expected_tool_executions=2,
            expected_handler_counts=(1, 1, 0),
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
            expected_outcome_kind=AgentOutcomeKind.RESPOND,
            expected_outcome_message=msg,
            expected_model_requests_ref=2,
            expected_model_requests_pyd=2,
            expected_tool_executions=2,
            expected_handler_counts=(1, 1, 0),
            check_tool_calls=True,
        )
