"""PAIM-11: Stage-9 behavioral parity — scenarios P11-A01 through P11-A11.

Each scenario executes both ``AgentLoop.run()`` and
``PydanticAIAgentRuntime.run()`` via the shared ``stage9_parity`` harness
and asserts equivalent observable outcomes.

Scenarios:
    P11-A01: direct RESPOND (zero tools, 1 model request)
    P11-A02: direct CLARIFY (zero tools, 1 model request)
    P11-A03: single READ -> RESPOND (1 tool, 2 model requests)
    P11-A04: single READ -> CLARIFY (1 tool, 2 model requests)
    P11-A05: single WRITE + audit -> RESPOND (1 tool, 2 model requests)
    P11-A06: WRITE unavailable without audit (hidden tool, direct respond)
    P11-A07: WRITE unavailable with READ permission (hidden tool, direct respond)
    P11-A08: WRITE unavailable in wrong session mode (hidden tool, direct respond)
    P11-A09: 2 READ calls succeed (2 tools, 2 model requests)
    P11-A10: 4 READ calls succeed (4 tools, 2 model requests)
    P11-A11: repeated same READ tool with different args (2 same tools, 2 model requests)
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

from dnd_assistant.application.agent_context import AgentContextBuilder
from dnd_assistant.application.agent_loop import AgentOutcomeKind
from dnd_assistant.tools.registry import ToolRegistry
from tests.support.stage9_parity import (
    HandlerCounters,
    Stage9Scenario,
    ToolRegistrySchema,
    assert_parity,
    build_catalog,
    clarify_json,
    make_context_builder,
    make_read_context,
    make_registry,
    make_tool_aware_response,
    make_tool_call,
    make_write_context,
    make_write_context_no_audit,
    make_wrong_session_mode_context,
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
# P11-A01: direct RESPOND
# ==============================================================================


class TestP11A01DirectRespond:
    """P11-A01: direct RESPOND — zero tool calls, one model request."""

    def test_direct_respond(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        msg = "Hello there!"
        ctx = make_read_context()

        ref_responses = [
            make_tool_aware_response(content=respond_json(msg)),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content=respond_json(msg))])

        scenario = Stage9Scenario(
            user_input="hello",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expected_outcome_kind=AgentOutcomeKind.RESPOND,
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
            expected_outcome_kind=AgentOutcomeKind.RESPOND,
            expected_outcome_message=msg,
            expected_model_requests_ref=1,
            expected_model_requests_pyd=1,
            expected_tool_executions=0,
            expected_handler_counts=(0, 0, 0),
        )


# ==============================================================================
# P11-A02: direct CLARIFY
# ==============================================================================


class TestP11A02DirectClarify:
    """P11-A02: direct CLARIFY — zero tool calls, one model request."""

    def test_direct_clarify(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        msg = "Which one?"
        ctx = make_read_context()

        ref_responses = [
            make_tool_aware_response(content=clarify_json(msg)),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content=clarify_json(msg))])

        scenario = Stage9Scenario(
            user_input="query",
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
# P11-A03: single READ -> RESPOND
# ==============================================================================


class TestP11A03SingleReadRespond:
    """P11-A03: single READ -> RESPOND — 1 tool, 2 model requests."""

    def test_single_read_respond(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        msg = "Found it!"
        ctx = make_read_context()

        tool_call = make_tool_call(
            name="read_alpha",
            arguments={"value": "gandalf"},
            call_id="call-1",
        )
        # Both runtimes use tool-only first response (no TextPart) for
        # equivalent provider-neutral DTOs.
        ref_responses = [
            make_tool_aware_response(
                content="",
                tool_calls=[tool_call],
            ),
            make_tool_aware_response(content=respond_json(msg)),
        ]

        request_count: list[int] = [0]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha",
                            args={"value": "gandalf"},
                            tool_call_id="call-1",
                        )
                    ]
                )
            return ModelResponse(parts=[TextPart(content=respond_json(msg))])

        scenario = Stage9Scenario(
            user_input="find gandalf",
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
# P11-A04: single READ -> CLARIFY
# ==============================================================================


class TestP11A04SingleReadClarify:
    """P11-A04: single READ -> CLARIFY — 1 tool, 2 model requests."""

    def test_single_read_clarify(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        msg = "Which gandalf?"
        ctx = make_read_context()

        tool_call = make_tool_call(
            name="read_alpha",
            arguments={"value": "gandalf"},
            call_id="call-1",
        )
        # Both runtimes use tool-only first response for equivalent DTOs.
        ref_responses = [
            make_tool_aware_response(
                content="",
                tool_calls=[tool_call],
            ),
            make_tool_aware_response(content=clarify_json(msg)),
        ]

        request_count: list[int] = [0]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha",
                            args={"value": "gandalf"},
                            tool_call_id="call-1",
                        )
                    ]
                )
            return ModelResponse(parts=[TextPart(content=clarify_json(msg))])

        scenario = Stage9Scenario(
            user_input="find gandalf",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expected_outcome_kind=AgentOutcomeKind.CLARIFY,
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
            expected_outcome_kind=AgentOutcomeKind.CLARIFY,
            expected_outcome_message=msg,
            expected_model_requests_ref=2,
            expected_model_requests_pyd=2,
            expected_tool_executions=1,
            expected_handler_counts=(1, 0, 0),
            check_tool_calls=True,
        )


# ==============================================================================
# P11-A05: single WRITE + audit -> RESPOND
# ==============================================================================


class TestP11A05SingleWriteRespond:
    """P11-A05: single WRITE + audit -> RESPOND — 1 tool, 2 model requests."""

    def test_single_write_respond(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        msg = "Written!"
        ctx = make_write_context()

        tool_call = make_tool_call(
            name="write_alpha",
            arguments={"value": "save-data"},
            call_id="call-w1",
        )
        # Both runtimes use tool-only first response for equivalent DTOs.
        ref_responses = [
            make_tool_aware_response(
                content="",
                tool_calls=[tool_call],
            ),
            make_tool_aware_response(content=respond_json(msg)),
        ]

        request_count: list[int] = [0]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="write_alpha",
                            args={"value": "save-data"},
                            tool_call_id="call-w1",
                        )
                    ]
                )
            return ModelResponse(parts=[TextPart(content=respond_json(msg))])

        scenario = Stage9Scenario(
            user_input="save data",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expected_outcome_kind=AgentOutcomeKind.RESPOND,
            expected_outcome_message=msg,
            expected_model_requests_ref=2,
            expected_model_requests_pyd=2,
            expected_tool_executions=1,
            expected_handler_counts=(0, 0, 1),
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
            expected_handler_counts=(0, 0, 1),
            check_tool_calls=True,
        )


# ==============================================================================
# P11-A06: WRITE unavailable without audit
# ==============================================================================


class TestP11A06WriteUnavailableNoAudit:
    """P11-A06: WRITE unavailable without audit — hidden tool, direct respond.

    The ExecutionContext has no audit, so write_alpha is not exposed.
    The model falls back to direct respond.
    """

    def test_write_unavailable_no_audit(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        msg = "No write for you"
        ctx = make_write_context_no_audit()

        ref_responses = [
            make_tool_aware_response(content=respond_json(msg)),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content=respond_json(msg))])

        scenario = Stage9Scenario(
            user_input="write something",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expected_outcome_kind=AgentOutcomeKind.RESPOND,
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
            expected_outcome_kind=AgentOutcomeKind.RESPOND,
            expected_outcome_message=msg,
            expected_model_requests_ref=1,
            expected_model_requests_pyd=1,
            expected_tool_executions=0,
            expected_handler_counts=(0, 0, 0),
        )

        # Verify write_alpha is NOT in exposed_tools
        ref_names = tuple(t.name for t in obs.reference.initial_decision.exposed_tools)
        pyd_names = tuple(t.name for t in obs.pydantic.initial_decision.exposed_tools)
        assert "write_alpha" not in ref_names
        assert "write_alpha" not in pyd_names


# ==============================================================================
# P11-A07: WRITE unavailable with READ permission
# ==============================================================================


class TestP11A07WriteUnavailableReadPermission:
    """P11-A07: WRITE unavailable with READ permission — hidden tool, direct respond.

    The ExecutionContext has only READ permission, so write_alpha is not exposed.
    """

    def test_write_unavailable_read_permission(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        msg = "Read only here"
        ctx = make_read_context()

        ref_responses = [
            make_tool_aware_response(content=respond_json(msg)),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content=respond_json(msg))])

        scenario = Stage9Scenario(
            user_input="read only",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expected_outcome_kind=AgentOutcomeKind.RESPOND,
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
            expected_outcome_kind=AgentOutcomeKind.RESPOND,
            expected_outcome_message=msg,
            expected_model_requests_ref=1,
            expected_model_requests_pyd=1,
            expected_tool_executions=0,
            expected_handler_counts=(0, 0, 0),
        )

        # Verify write_alpha is NOT in exposed_tools
        ref_names = tuple(t.name for t in obs.reference.initial_decision.exposed_tools)
        pyd_names = tuple(t.name for t in obs.pydantic.initial_decision.exposed_tools)
        assert "write_alpha" not in ref_names
        assert "write_alpha" not in pyd_names


# ==============================================================================
# P11-A08: WRITE unavailable in wrong session mode
# ==============================================================================


class TestP11A08WriteUnavailableWrongMode:
    """P11-A08: WRITE unavailable in wrong session mode — hidden tool, direct respond.

    The ExecutionContext has WRITE permission + NO_ACTIVE_SESSION + valid
    audit. write_alpha requires ACTIVE_SESSION, so it is hidden solely
    because of session mode.
    """

    def test_write_unavailable_wrong_mode(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        msg = "Need active session"
        ctx = make_wrong_session_mode_context()

        ref_responses = [
            make_tool_aware_response(content=respond_json(msg)),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content=respond_json(msg))])

        scenario = Stage9Scenario(
            user_input="write without session",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expected_outcome_kind=AgentOutcomeKind.RESPOND,
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
            expected_outcome_kind=AgentOutcomeKind.RESPOND,
            expected_outcome_message=msg,
            expected_model_requests_ref=1,
            expected_model_requests_pyd=1,
            expected_tool_executions=0,
            expected_handler_counts=(0, 0, 0),
        )

        # Verify write_alpha is NOT in exposed_tools
        ref_names = tuple(t.name for t in obs.reference.initial_decision.exposed_tools)
        pyd_names = tuple(t.name for t in obs.pydantic.initial_decision.exposed_tools)
        assert "write_alpha" not in ref_names
        assert "write_alpha" not in pyd_names


# ==============================================================================
# P11-A09: 2 READ calls succeed
# ==============================================================================


class TestP11A09TwoReadCalls:
    """P11-A09: 2 READ calls succeed — 2 tools, 2 model requests."""

    def test_two_read_calls(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        msg = "Both done!"
        ctx = make_read_context()

        tool_call_1 = make_tool_call(
            name="read_alpha",
            arguments={"value": "first"},
            call_id="c1",
        )
        tool_call_2 = make_tool_call(
            name="read_beta",
            arguments={"number": 42},
            call_id="c2",
        )
        # Both runtimes use tool-only first response for equivalent DTOs.
        ref_responses = [
            make_tool_aware_response(
                content="",
                tool_calls=[tool_call_1, tool_call_2],
            ),
            make_tool_aware_response(content=respond_json(msg)),
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
                        ToolCallPart(
                            tool_name="read_beta",
                            args={"number": 42},
                            tool_call_id="c2",
                        ),
                    ]
                )
            return ModelResponse(parts=[TextPart(content=respond_json(msg))])

        scenario = Stage9Scenario(
            user_input="read both",
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


# ==============================================================================
# P11-A10: 4 READ calls succeed
# ==============================================================================


class TestP11A10FourReadCalls:
    """P11-A10: 4 READ calls succeed — 4 tools, 2 model requests."""

    def test_four_read_calls(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        msg = "All four done!"
        ctx = make_read_context()

        tool_call_1 = make_tool_call(
            name="read_alpha",
            arguments={"value": "a"},
            call_id="c1",
        )
        tool_call_2 = make_tool_call(
            name="read_beta",
            arguments={"number": 1},
            call_id="c2",
        )
        tool_call_3 = make_tool_call(
            name="read_alpha",
            arguments={"value": "b"},
            call_id="c3",
        )
        tool_call_4 = make_tool_call(
            name="read_beta",
            arguments={"number": 2},
            call_id="c4",
        )
        # Both runtimes use tool-only first response for equivalent DTOs.
        ref_responses = [
            make_tool_aware_response(
                content="",
                tool_calls=[
                    tool_call_1,
                    tool_call_2,
                    tool_call_3,
                    tool_call_4,
                ],
            ),
            make_tool_aware_response(content=respond_json(msg)),
        ]

        request_count: list[int] = [0]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha",
                            args={"value": "a"},
                            tool_call_id="c1",
                        ),
                        ToolCallPart(
                            tool_name="read_beta",
                            args={"number": 1},
                            tool_call_id="c2",
                        ),
                        ToolCallPart(
                            tool_name="read_alpha",
                            args={"value": "b"},
                            tool_call_id="c3",
                        ),
                        ToolCallPart(
                            tool_name="read_beta",
                            args={"number": 2},
                            tool_call_id="c4",
                        ),
                    ]
                )
            return ModelResponse(parts=[TextPart(content=respond_json(msg))])

        scenario = Stage9Scenario(
            user_input="read all four",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expected_outcome_kind=AgentOutcomeKind.RESPOND,
            expected_outcome_message=msg,
            expected_model_requests_ref=2,
            expected_model_requests_pyd=2,
            expected_tool_executions=4,
            expected_handler_counts=(2, 2, 0),
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
            expected_tool_executions=4,
            expected_handler_counts=(2, 2, 0),
            check_tool_calls=True,
        )


# ==============================================================================
# P11-A11: repeated same READ tool with different args
# ==============================================================================


class TestP11A11RepeatedSameRead:
    """P11-A11: repeated same READ tool with different args — 2 same tools, 2 model requests."""

    def test_repeated_same_read(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        msg = "Both lookups done!"
        ctx = make_read_context()

        tool_call_1 = make_tool_call(
            name="read_alpha",
            arguments={"value": "first"},
            call_id="c1",
        )
        tool_call_2 = make_tool_call(
            name="read_alpha",
            arguments={"value": "second"},
            call_id="c2",
        )
        # Both runtimes use tool-only first response for equivalent DTOs.
        ref_responses = [
            make_tool_aware_response(
                content="",
                tool_calls=[tool_call_1, tool_call_2],
            ),
            make_tool_aware_response(content=respond_json(msg)),
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
                        ToolCallPart(
                            tool_name="read_alpha",
                            args={"value": "second"},
                            tool_call_id="c2",
                        ),
                    ]
                )
            return ModelResponse(parts=[TextPart(content=respond_json(msg))])

        scenario = Stage9Scenario(
            user_input="read alpha twice",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expected_outcome_kind=AgentOutcomeKind.RESPOND,
            expected_outcome_message=msg,
            expected_model_requests_ref=2,
            expected_model_requests_pyd=2,
            expected_tool_executions=2,
            expected_handler_counts=(2, 0, 0),
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
            expected_handler_counts=(2, 0, 0),
            check_tool_calls=True,
        )
