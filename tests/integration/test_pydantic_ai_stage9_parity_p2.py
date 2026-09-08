"""PAIM-11: Stage-9 behavioral parity — scenarios P11-A12 through P11-A23.

Each scenario executes both ``AgentLoop.run()`` and
``PydanticAIAgentRuntime.run()`` via the shared ``stage9_parity`` harness
and asserts equivalent observable outcomes.

Scenarios:
    P11-A12: 5 calls rejected (zero executions, ModelError)
    P11-A13: 20 calls rejected (zero executions, ModelError)
    P11-A14: READ + WRITE rejected (zero executions, ModelError)
    P11-A15: WRITE + READ rejected (zero executions, ModelError)
    P11-A16: WRITE + WRITE rejected (zero executions, ModelError)
    P11-A17: READ + READ + WRITE rejected (zero executions, ModelError)
    P11-A18: duplicate non-null call ID rejected (zero executions, ModelError)
    P11-A19: multiple omitted/None model call IDs supported
    P11-A20: completely unknown tool (ModelError, zero executions)
    P11-A21: hidden-but-real tool (ModelError, zero executions)
    P11-A22: mixed allowed + unknown (ModelError, zero executions)
    P11-A23: mixed allowed + hidden (ModelError, zero executions)
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
    make_context_builder,
    make_read_context,
    make_registry,
    make_registry_with_hidden,
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
# P11-A12: 5 calls rejected
# ==============================================================================


class TestP11A12FiveCallsRejected:
    """P11-A12: 5 calls rejected — zero executions, ModelError."""

    def test_five_calls_rejected(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()
        tool_calls = [
            make_tool_call(name="read_alpha", arguments={"value": str(i)}, call_id=f"c{i}")
            for i in range(5)
        ]
        ref_responses = [
            make_tool_aware_response(content="Too many...", tool_calls=tool_calls),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha", args={"value": str(i)}, tool_call_id=f"c{i}"
                    )
                    for i in range(5)
                ]
            )

        scenario = Stage9Scenario(
            user_input="do five things",
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
# P11-A13: 20 calls rejected
# ==============================================================================


class TestP11A13TwentyCallsRejected:
    """P11-A13: 20 calls rejected — zero executions, ModelError."""

    def test_twenty_calls_rejected(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()

        tool_calls = [
            make_tool_call(name="read_alpha", arguments={"value": str(i)}, call_id=f"c{i}")
            for i in range(20)
        ]
        ref_responses = [
            make_tool_aware_response(
                content="Too many...",
                tool_calls=tool_calls,
            ),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": str(i)},
                        tool_call_id=f"c{i}",
                    )
                    for i in range(20)
                ]
            )

        scenario = Stage9Scenario(
            user_input="do twenty things",
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
# P11-A14: READ + WRITE rejected
# ==============================================================================


class TestP11A14ReadWriteRejected:
    """P11-A14: READ + WRITE rejected — zero executions, ModelError."""

    def test_read_write_rejected(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_write_context()

        tool_call_1 = make_tool_call(
            name="read_alpha",
            arguments={"value": "ok"},
            call_id="c1",
        )
        tool_call_2 = make_tool_call(
            name="write_alpha",
            arguments={"value": "bad"},
            call_id="c2",
        )
        ref_responses = [
            make_tool_aware_response(
                content="Mixed batch...",
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
                        tool_name="write_alpha",
                        args={"value": "bad"},
                        tool_call_id="c2",
                    ),
                ]
            )

        scenario = Stage9Scenario(
            user_input="read and write",
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
# P11-A15: WRITE + READ rejected
# ==============================================================================


class TestP11A15WriteReadRejected:
    """P11-A15: WRITE + READ rejected — zero executions, ModelError."""

    def test_write_read_rejected(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_write_context()

        tool_call_1 = make_tool_call(
            name="write_alpha",
            arguments={"value": "a"},
            call_id="c1",
        )
        tool_call_2 = make_tool_call(
            name="read_alpha",
            arguments={"value": "b"},
            call_id="c2",
        )
        ref_responses = [
            make_tool_aware_response(
                content="Mixed batch...",
                tool_calls=[tool_call_1, tool_call_2],
            ),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="write_alpha",
                        args={"value": "a"},
                        tool_call_id="c1",
                    ),
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": "b"},
                        tool_call_id="c2",
                    ),
                ]
            )

        scenario = Stage9Scenario(
            user_input="write then read",
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
# P11-A16: WRITE + WRITE rejected
# ==============================================================================


class TestP11A16WriteWriteRejected:
    """P11-A16: WRITE + WRITE rejected — zero executions, ModelError."""

    def test_write_write_rejected(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_write_context()

        tool_call_1 = make_tool_call(
            name="write_alpha",
            arguments={"value": "a"},
            call_id="c1",
        )
        tool_call_2 = make_tool_call(
            name="write_alpha",
            arguments={"value": "b"},
            call_id="c2",
        )
        ref_responses = [
            make_tool_aware_response(
                content="Double write...",
                tool_calls=[tool_call_1, tool_call_2],
            ),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="write_alpha",
                        args={"value": "a"},
                        tool_call_id="c1",
                    ),
                    ToolCallPart(
                        tool_name="write_alpha",
                        args={"value": "b"},
                        tool_call_id="c2",
                    ),
                ]
            )

        scenario = Stage9Scenario(
            user_input="write twice",
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
# P11-A17: READ + READ + WRITE rejected
# ==============================================================================


class TestP11A17ReadReadWriteRejected:
    """P11-A17: READ + READ + WRITE rejected — zero executions, ModelError."""

    def test_read_read_write_rejected(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_write_context()

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
            name="write_alpha",
            arguments={"value": "bad"},
            call_id="c3",
        )
        ref_responses = [
            make_tool_aware_response(
                content="Mixed batch...",
                tool_calls=[tool_call_1, tool_call_2, tool_call_3],
            ),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
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
                        tool_name="write_alpha",
                        args={"value": "bad"},
                        tool_call_id="c3",
                    ),
                ]
            )

        scenario = Stage9Scenario(
            user_input="read read write",
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
# P11-A18: duplicate non-null call ID rejected
# ==============================================================================


class TestP11A18DuplicateCallIdRejected:
    """P11-A18: duplicate non-null call ID rejected — zero executions, ModelError."""

    def test_duplicate_call_id_rejected(
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
            arguments={"value": "a"},
            call_id="dup",
        )
        tool_call_2 = make_tool_call(
            name="read_beta",
            arguments={"number": 1},
            call_id="dup",
        )
        ref_responses = [
            make_tool_aware_response(
                content="Duplicate IDs...",
                tool_calls=[tool_call_1, tool_call_2],
            ),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": "a"},
                        tool_call_id="dup",
                    ),
                    ToolCallPart(
                        tool_name="read_beta",
                        args={"number": 1},
                        tool_call_id="dup",
                    ),
                ]
            )

        scenario = Stage9Scenario(
            user_input="duplicate ids",
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
# P11-A19: multiple omitted/None model call IDs supported
# ==============================================================================


class TestP11A19OmittedCallIds:
    """P11-A19: multiple omitted/None model call IDs supported — 2 tools, 2 model requests."""

    def test_omitted_call_ids(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        msg = "Both done with None IDs!"
        ctx = make_read_context()

        tool_call_1 = make_tool_call(
            name="read_alpha",
            arguments={"value": "first"},
        )
        tool_call_2 = make_tool_call(
            name="read_beta",
            arguments={"number": 42},
        )
        ref_responses = [
            make_tool_aware_response(
                content="Looking up...",
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
                        ),
                        ToolCallPart(
                            tool_name="read_beta",
                            args={"number": 42},
                        ),
                    ]
                )
            return ModelResponse(parts=[TextPart(content=respond_json(msg))])

        scenario = Stage9Scenario(
            user_input="read with None IDs",
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

        # Verify basic outcome parity (handler counts, model requests)
        assert obs.ref_error is None, f"Reference runtime raised: {obs.ref_error}"
        assert obs.pyd_error is None, f"Pydantic runtime raised: {obs.pyd_error}"
        assert obs.reference is not None
        assert obs.pydantic is not None

        assert obs.ref_model_requests == 2
        assert obs.pyd_model_requests == 2
        assert len(obs.reference.tool_executions) == 2
        assert len(obs.pydantic.tool_executions) == 2
        assert obs.ref_handler_counts == (1, 1, 0)
        assert obs.pyd_handler_counts == (1, 1, 0)

        # Prompt version and exposed tools match
        assert (
            obs.reference.initial_decision.prompt_version
            == obs.pydantic.initial_decision.prompt_version
        )
        ref_names = tuple(t.name for t in obs.reference.initial_decision.exposed_tools)
        pyd_names = tuple(t.name for t in obs.pydantic.initial_decision.exposed_tools)
        assert ref_names == pyd_names

        # Terminal outcome parity
        assert obs.reference.outcome.kind == AgentOutcomeKind.RESPOND
        assert obs.pydantic.outcome.kind == AgentOutcomeKind.RESPOND
        assert obs.reference.outcome.message == msg
        assert obs.pydantic.outcome.message == msg

        # Known framework difference: Pydantic AI auto-assigns unique
        # tool_call_id values when the provider omits them, while the
        # reference runtime preserves None. Both behaviors are safe:
        # the application invariant is that duplicate concrete IDs
        # cannot cause execution ambiguity, and omitted IDs remain
        # uniquely bindable through the framework path.
        ref_ids = [e.tool_call.call_id for e in obs.reference.tool_executions]
        pyd_ids = [e.tool_call.call_id for e in obs.pydantic.tool_executions]
        # Reference: all None
        assert all(cid is None for cid in ref_ids), (
            f"Expected all None IDs in reference, got {ref_ids}"
        )
        # Pydantic: all non-None unique strings
        assert all(cid is not None for cid in pyd_ids), (
            f"Expected all non-None IDs in Pydantic, got {pyd_ids}"
        )
        assert len(set(pyd_ids)) == 2, f"Expected 2 unique Pydantic IDs, got {pyd_ids}"


# ==============================================================================
# P11-A20: completely unknown tool
# ==============================================================================


class TestP11A20UnknownTool:
    """P11-A20: completely unknown tool — ModelError, zero executions."""

    def test_unknown_tool(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()

        tool_call = make_tool_call(
            name="unknown_tool_xyz",
            arguments={"value": "test"},
            call_id="c1",
        )
        ref_responses = [
            make_tool_aware_response(
                content="Using unknown...",
                tool_calls=[tool_call],
            ),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="unknown_tool_xyz",
                        args={"value": "test"},
                        tool_call_id="c1",
                    ),
                ]
            )

        scenario = Stage9Scenario(
            user_input="use unknown tool",
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
# P11-A21: hidden-but-real tool
# ==============================================================================


class TestP11A21HiddenTool:
    """P11-A21: hidden-but-real tool — ModelError, zero executions."""

    def test_hidden_tool(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()

        # Build a registry with a hidden tool
        hidden_registry, hidden_def = make_registry_with_hidden(
            ref_counters,
            hidden_name="hidden_tool",
        )
        hidden_catalog = build_catalog(hidden_registry)

        tool_call = make_tool_call(
            name="hidden_tool",
            arguments={"value": "secret"},
            call_id="c1",
        )
        ref_responses = [
            make_tool_aware_response(
                content="Using hidden...",
                tool_calls=[tool_call],
            ),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="hidden_tool",
                        args={"value": "secret"},
                        tool_call_id="c1",
                    ),
                ]
            )

        scenario = Stage9Scenario(
            user_input="use hidden tool",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expect_failure=True,
        )

        obs = run_scenario(
            scenario,
            registry=hidden_registry,
            catalog=hidden_catalog,
            context_builder=context_builder,
            ref_counters=ref_counters,
            pyd_counters=pyd_counters,
        )

        assert_parity(
            obs,
            expect_failure=True,
        )


# ==============================================================================
# P11-A22: mixed allowed + unknown
# ==============================================================================


class TestP11A22MixedAllowedUnknown:
    """P11-A22: mixed allowed + unknown — ModelError, zero executions."""

    def test_mixed_allowed_unknown(
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
            name="unknown_tool_xyz",
            arguments={"value": "bad"},
            call_id="c2",
        )
        ref_responses = [
            make_tool_aware_response(
                content="Mixed...",
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
                        tool_name="unknown_tool_xyz",
                        args={"value": "bad"},
                        tool_call_id="c2",
                    ),
                ]
            )

        scenario = Stage9Scenario(
            user_input="mixed allowed and unknown",
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
# P11-A23: mixed allowed + hidden
# ==============================================================================


class TestP11A23MixedAllowedHidden:
    """P11-A23: mixed allowed + hidden — ModelError, zero executions."""

    def test_mixed_allowed_hidden(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()

        # Build a registry with a hidden tool
        hidden_registry, hidden_def = make_registry_with_hidden(
            ref_counters,
            hidden_name="hidden_tool",
        )
        hidden_catalog = build_catalog(hidden_registry)

        tool_call_1 = make_tool_call(
            name="read_alpha",
            arguments={"value": "ok"},
            call_id="c1",
        )
        tool_call_2 = make_tool_call(
            name="hidden_tool",
            arguments={"value": "secret"},
            call_id="c2",
        )
        ref_responses = [
            make_tool_aware_response(
                content="Mixed...",
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
                        tool_name="hidden_tool",
                        args={"value": "secret"},
                        tool_call_id="c2",
                    ),
                ]
            )

        scenario = Stage9Scenario(
            user_input="mixed allowed and hidden",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expect_failure=True,
        )

        obs = run_scenario(
            scenario,
            registry=hidden_registry,
            catalog=hidden_catalog,
            context_builder=context_builder,
            ref_counters=ref_counters,
            pyd_counters=pyd_counters,
        )

        assert_parity(
            obs,
            expect_failure=True,
        )
