"""PAIM-11: Stage-9 behavioral parity — scenarios P11-A24 through P11-A36.

Each scenario executes both ``AgentLoop.run()`` and
``PydanticAIAgentRuntime.run()`` via the shared ``stage9_parity`` harness
and asserts equivalent observable outcomes.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

from dnd_assistant.application.agent_context import AgentContextBuilder
from dnd_assistant.application.agent_loop import AgentOutcomeKind
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
    """P11-A24: schema-invalid single tool args — ModelError, zero executions."""

    def test_schema_invalid_single(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()

        # read_alpha expects {"value": str}, empty dict is invalid
        tool_call = make_tool_call(
            name="read_alpha",
            arguments={},
            call_id="c1",
        )
        ref_responses = [
            make_tool_aware_response(
                content="Reading...",
                tool_calls=[tool_call],
            ),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={},
                        tool_call_id="c1",
                    ),
                ]
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
        )


# ==============================================================================
# P11-A25: schema-invalid second READ in multi batch
# ==============================================================================


class TestP11A25SchemaInvalidSecondRead:
    """P11-A25: schema-invalid second READ in multi batch — fail-fast, first executes."""

    def test_schema_invalid_second_read(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()

        # First call is valid, second call has empty dict (invalid for read_alpha)
        tool_call_1 = make_tool_call(
            name="read_alpha",
            arguments={"value": "ok"},
            call_id="c1",
        )
        tool_call_2 = make_tool_call(
            name="read_alpha",
            arguments={},
            call_id="c2",
        )
        ref_responses = [
            make_tool_aware_response(
                content="Reading...",
                tool_calls=[tool_call_1, tool_call_2],
            ),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": "ok"},
                        tool_call_id="c1",
                    ),
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={},
                        tool_call_id="c2",
                    ),
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
        )


# ==============================================================================
# P11-A26: structurally non-finite JSON argument
# ==============================================================================


class TestP11A26NonFiniteJsonArg:
    """P11-A26: structurally non-finite JSON argument — ModelError, zero executions."""

    def test_non_finite_json_arg(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()
        msg = "No NaN here."

        # Reference: valid args succeed (ToolCall rejects NaN at construction)
        valid_call = make_tool_call(
            name="read_beta",
            arguments={"number": 42},
            call_id="c1",
        )
        ref_responses = [
            make_tool_aware_response(
                content="Reading...",
                tool_calls=[valid_call],
            ),
            make_tool_aware_response(content=respond_json(msg)),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            req_count = getattr(pyd_fn, "_call_count", 0)
            pyd_fn._call_count = req_count + 1
            if req_count == 0:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_beta",
                            args={"number": float("nan")},
                            tool_call_id="c1",
                        ),
                    ]
                )
            return ModelResponse(parts=[TextPart(content=respond_json(msg))])

        scenario = Stage9Scenario(
            user_input="read with NaN",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expected_outcome_kind=AgentOutcomeKind.RESPOND,
            expected_outcome_message=msg,
            expected_model_requests_ref=2,
            expected_model_requests_pyd=1,
            expected_tool_executions=1,
            expected_handler_counts=(0, 1, 0),
        )

        obs = run_scenario(
            scenario,
            registry=registry,
            catalog=catalog,
            context_builder=context_builder,
            ref_counters=ref_counters,
            pyd_counters=pyd_counters,
        )

        # Reference succeeds with valid args
        assert obs.ref_error is None
        assert obs.reference is not None
        assert obs.reference.outcome.kind == AgentOutcomeKind.RESPOND
        assert obs.reference.outcome.message == msg
        assert obs.ref_model_requests == 2
        assert len(obs.reference.tool_executions) == 1

        # Pydantic runtime rejects NaN args with ModelError
        assert obs.pyd_error is not None
        assert "ModelError" in type(obs.pyd_error).__name__
        assert obs.pyd_model_requests == 1
        assert obs.pyd_handler_counts == (0, 0, 0)


# ==============================================================================
# P11-A27: structurally invalid call anywhere in batch
# ==============================================================================


class TestP11A27StructurallyInvalidBatch:
    """P11-A27: structurally invalid call anywhere in batch — ModelError, zero executions."""

    def test_structurally_invalid_batch(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()

        # read_alpha expects {"value": str}, passing a number is type-invalid
        tool_call_1 = make_tool_call(
            name="read_alpha",
            arguments={"value": "ok"},
            call_id="c1",
        )
        tool_call_2 = make_tool_call(
            name="read_alpha",
            arguments={"value": 123},
            call_id="c2",
        )
        ref_responses = [
            make_tool_aware_response(
                content="Reading...",
                tool_calls=[tool_call_1, tool_call_2],
            ),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": "ok"},
                        tool_call_id="c1",
                    ),
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": 123},
                        tool_call_id="c2",
                    ),
                ]
            )

        scenario = Stage9Scenario(
            user_input="read with type mismatch",
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
        )


# ==============================================================================
# P11-A28: READ #1 succeeds, READ #2 execution fails, READ #3 never runs
# ==============================================================================


class TestP11A28ReadFailFast:
    """P11-A28: READ #1 succeeds, READ #2 execution fails, READ #3 never runs."""

    def test_read_fail_fast(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()

        tool_call_1 = make_tool_call(
            name="read_alpha",
            arguments={"value": "ok"},
            call_id="c1",
        )
        tool_call_2 = make_tool_call(
            name="read_beta",
            arguments={"number": 0},
            call_id="c2",
        )
        tool_call_3 = make_tool_call(
            name="read_alpha",
            arguments={"value": "never"},
            call_id="c3",
        )
        ref_responses = [
            make_tool_aware_response(
                content="Reading...",
                tool_calls=[tool_call_1, tool_call_2, tool_call_3],
            ),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": "ok"},
                        tool_call_id="c1",
                    ),
                    ToolCallPart(
                        tool_name="read_beta",
                        args={"number": 0},
                        tool_call_id="c2",
                    ),
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": "never"},
                        tool_call_id="c3",
                    ),
                ]
            )

        scenario = Stage9Scenario(
            user_input="read three with second failing",
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
        )


# ==============================================================================
# P11-A29: request #1 -> tool batch, request #2 -> one additional tool call
# ==============================================================================


class TestP11A29SecondRequestOneTool:
    """P11-A29: request #1 -> tool batch, request #2 -> one additional tool call (ModelError)."""

    def test_second_request_one_tool(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()

        tool_call = make_tool_call(
            name="read_alpha",
            arguments={"value": "first"},
            call_id="c1",
        )
        ref_responses = [
            make_tool_aware_response(
                content="First call...",
                tool_calls=[tool_call],
            ),
            make_tool_aware_response(
                content="Second call...",
                tool_calls=[tool_call],
            ),
        ]

        request_count: list[int] = [0]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha",
                            args={"value": "first"},
                            tool_call_id="c1",
                        ),
                    ]
                )
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": "second"},
                        tool_call_id="c2",
                    ),
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
        )


# ==============================================================================
# P11-A30: request #1 -> tool batch, request #2 -> multiple additional tool calls
# ==============================================================================


class TestP11A30SecondRequestMultipleTools:
    """P11-A30: request #1 -> tool batch, request #2 -> multiple additional tool calls (ModelError)."""

    def test_second_request_multiple_tools(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()
        tool_call_1 = make_tool_call(name="read_alpha", arguments={"value": "first"}, call_id="c1")
        tool_call_2 = make_tool_call(name="read_alpha", arguments={"value": "second"}, call_id="c2")
        ref_responses = [
            make_tool_aware_response(content="First call...", tool_calls=[tool_call_1]),
            make_tool_aware_response(
                content="Second batch...", tool_calls=[tool_call_1, tool_call_2]
            ),
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
        assert_parity(obs, expect_failure=True)


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

        ref_responses = [
            make_tool_aware_response(content="not valid JSON at all"),
        ]

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
        )


# ==============================================================================
# P11-A32: malformed post-tool terminal output
# ==============================================================================


class TestP11A32MalformedPostToolOutput:
    """P11-A32: malformed post-tool terminal output — ModelError, 2 model requests."""

    def test_malformed_post_tool_output(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()

        tool_call = make_tool_call(
            name="read_alpha",
            arguments={"value": "ok"},
            call_id="c1",
        )
        ref_responses = [
            make_tool_aware_response(
                content="Looking up...",
                tool_calls=[tool_call],
            ),
            make_tool_aware_response(content="not valid JSON at all"),
        ]

        request_count: list[int] = [0]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha",
                            args={"value": "ok"},
                            tool_call_id="c1",
                        ),
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
        )


# ==============================================================================
# P11-A33: first tool succeeds, second model request fails
# ==============================================================================


class TestP11A33FirstToolSucceedsSecondFails:
    """P11-A33: first tool succeeds, second model request fails — ModelError, tool executed once."""

    def test_first_tool_succeeds_second_fails(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()

        tool_call = make_tool_call(
            name="read_alpha",
            arguments={"value": "ok"},
            call_id="c1",
        )
        ref_responses = [
            make_tool_aware_response(
                content="Looking up...",
                tool_calls=[tool_call],
            ),
            make_tool_aware_response(content="not valid JSON at all"),
        ]

        request_count: list[int] = [0]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha",
                            args={"value": "ok"},
                            tool_call_id="c1",
                        ),
                    ]
                )
            raise ValueError("Second model request failed")

        scenario = Stage9Scenario(
            user_input="tool then crash",
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
        )


# ==============================================================================
# P11-A34: direct CLARIFY with WRITE-capable ExecutionContext
# ==============================================================================


class TestP11A34ClarifyWithWriteContext:
    """P11-A34: direct CLARIFY with WRITE-capable ExecutionContext — zero WRITE, zero tools."""

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

        ref_responses = [
            make_tool_aware_response(content=clarify_json(msg)),
        ]

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
        tool_call = make_tool_call(name="read_alpha", arguments={"value": "gandalf"}, call_id="c1")
        ref_responses = [
            make_tool_aware_response(content="Looking up Gandalf...", tool_calls=[tool_call]),
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
        tool_call_1 = make_tool_call(name="read_alpha", arguments={"value": "first"}, call_id="c1")
        tool_call_2 = make_tool_call(name="read_beta", arguments={"number": 42}, call_id="c2")
        ref_responses = [
            make_tool_aware_response(
                content="Looking up both...", tool_calls=[tool_call_1, tool_call_2]
            ),
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
