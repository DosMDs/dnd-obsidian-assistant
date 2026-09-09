"""PAIM-C24: Literal model-visible tool exposure parity evidence.

Verifies that both runtimes expose identical tool sets to the model
for representative execution contexts.

Every test captures the actual tool lists passed to:
- Reference: ``ModelGateway.chat_with_tools(..., tools=...)``
- Candidate: ``agent_info.function_tools`` from ``FunctionModel`` callback

And asserts exact name/order/description/schema parity.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart

from dnd_assistant.application.agent_context import AgentContextBuilder
from dnd_assistant.errors import ModelError
from dnd_assistant.tools.catalog import ToolRegistrySchema
from dnd_assistant.tools.registry import ToolRegistry
from tests.support.stage9_parity import (
    HandlerCounters,
    Stage9Scenario,
    assert_model_visible_tool_parity,
    assert_parity,
    build_catalog,
    make_context_builder,
    make_read_context,
    make_registry,
    make_tool_aware_response,
    make_tool_call,
    make_write_context,
    make_write_context_no_audit,
    make_wrong_session_mode_context,
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
# C24-E01: Single READ context
# ==============================================================================


class TestC24E01SingleReadExposure:
    """Single READ context exposes read_alpha and read_beta."""

    EXPECTED_NAMES: tuple[str, ...] = ("read_alpha", "read_beta")

    def test_single_read_exposure(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()
        ref_responses = [
            make_tool_aware_response(
                tool_calls=[make_tool_call("read_alpha", {"value": "ok"}, "c1")],
            ),
            make_tool_aware_response(content="done"),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_alpha", args={"value": "ok"}, tool_call_id="c1"),
                ]
            )

        scenario = Stage9Scenario(
            user_input="read alpha",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expected_model_requests_ref=2,
            expected_model_requests_pyd=2,
        )

        obs = run_scenario(
            scenario,
            registry=registry,
            catalog=catalog,
            context_builder=context_builder,
            ref_counters=ref_counters,
            pyd_counters=pyd_counters,
        )

        assert_model_visible_tool_parity(
            obs,
            expected_names=self.EXPECTED_NAMES,
            expected_requests=2,
        )


# ==============================================================================
# C24-E02: 2 READ context
# ==============================================================================


class TestC24E02TwoReadExposure:
    """2 READ context exposes read_alpha and read_beta."""

    EXPECTED_NAMES: tuple[str, ...] = ("read_alpha", "read_beta")

    def test_two_read_exposure(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()
        ref_responses = [
            make_tool_aware_response(
                tool_calls=[
                    make_tool_call("read_alpha", {"value": "a"}, "c1"),
                    make_tool_call("read_beta", {"number": 1}, "c2"),
                ],
            ),
            make_tool_aware_response(content="done"),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_alpha", args={"value": "a"}, tool_call_id="c1"),
                    ToolCallPart(tool_name="read_beta", args={"number": 1}, tool_call_id="c2"),
                ]
            )

        scenario = Stage9Scenario(
            user_input="read both",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expected_model_requests_ref=2,
            expected_model_requests_pyd=2,
        )

        obs = run_scenario(
            scenario,
            registry=registry,
            catalog=catalog,
            context_builder=context_builder,
            ref_counters=ref_counters,
            pyd_counters=pyd_counters,
        )

        assert_model_visible_tool_parity(
            obs,
            expected_names=self.EXPECTED_NAMES,
            expected_requests=2,
        )


# ==============================================================================
# C24-E03: WRITE + active session + audit
# ==============================================================================


class TestC24E03WriteWithAuditExposure:
    """WRITE + active session + audit exposes read_alpha, read_beta, write_alpha."""

    EXPECTED_NAMES: tuple[str, ...] = ("read_alpha", "read_beta", "write_alpha")

    def test_write_with_audit_exposure(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_write_context()
        ref_responses = [
            make_tool_aware_response(
                tool_calls=[
                    make_tool_call("write_alpha", {"value": "w"}, "c1"),
                ],
            ),
            make_tool_aware_response(content="written"),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="write_alpha", args={"value": "w"}, tool_call_id="c1"),
                ]
            )

        scenario = Stage9Scenario(
            user_input="write alpha",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expected_model_requests_ref=2,
            expected_model_requests_pyd=2,
        )

        obs = run_scenario(
            scenario,
            registry=registry,
            catalog=catalog,
            context_builder=context_builder,
            ref_counters=ref_counters,
            pyd_counters=pyd_counters,
        )

        assert_model_visible_tool_parity(
            obs,
            expected_names=self.EXPECTED_NAMES,
            expected_requests=2,
        )


# ==============================================================================
# C24-E04: WRITE + no audit (write_alpha hidden)
# ==============================================================================


class TestC24E04WriteNoAuditExposure:
    """WRITE + no audit hides write_alpha; only read_alpha, read_beta exposed."""

    EXPECTED_NAMES: tuple[str, ...] = ("read_alpha", "read_beta")

    def test_write_no_audit_exposure(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_write_context_no_audit()
        ref_responses = [
            make_tool_aware_response(
                tool_calls=[
                    make_tool_call("read_alpha", {"value": "ok"}, "c1"),
                ],
            ),
            make_tool_aware_response(content="done"),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_alpha", args={"value": "ok"}, tool_call_id="c1"),
                ]
            )

        scenario = Stage9Scenario(
            user_input="read without audit",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expected_model_requests_ref=2,
            expected_model_requests_pyd=2,
        )

        obs = run_scenario(
            scenario,
            registry=registry,
            catalog=catalog,
            context_builder=context_builder,
            ref_counters=ref_counters,
            pyd_counters=pyd_counters,
        )

        assert_model_visible_tool_parity(
            obs,
            expected_names=self.EXPECTED_NAMES,
            expected_requests=2,
        )


# ==============================================================================
# C24-E05: READ permission (write_alpha hidden)
# ==============================================================================


class TestC24E05ReadPermissionExposure:
    """READ permission hides write_alpha; only read_alpha, read_beta exposed."""

    EXPECTED_NAMES: tuple[str, ...] = ("read_alpha", "read_beta")

    def test_read_permission_exposure(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()
        ref_responses = [
            make_tool_aware_response(
                tool_calls=[
                    make_tool_call("read_alpha", {"value": "ok"}, "c1"),
                ],
            ),
            make_tool_aware_response(content="done"),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_alpha", args={"value": "ok"}, tool_call_id="c1"),
                ]
            )

        scenario = Stage9Scenario(
            user_input="read with READ permission",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expected_model_requests_ref=2,
            expected_model_requests_pyd=2,
        )

        obs = run_scenario(
            scenario,
            registry=registry,
            catalog=catalog,
            context_builder=context_builder,
            ref_counters=ref_counters,
            pyd_counters=pyd_counters,
        )

        assert_model_visible_tool_parity(
            obs,
            expected_names=self.EXPECTED_NAMES,
            expected_requests=2,
        )


# ==============================================================================
# C24-E06: Wrong session mode (write_alpha hidden)
# ==============================================================================


class TestC24E06WrongSessionModeExposure:
    """Wrong session mode hides write_alpha; only read_alpha, read_beta exposed."""

    EXPECTED_NAMES: tuple[str, ...] = ("read_alpha", "read_beta")

    def test_wrong_session_mode_exposure(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_wrong_session_mode_context()
        ref_responses = [
            make_tool_aware_response(
                tool_calls=[
                    make_tool_call("read_alpha", {"value": "ok"}, "c1"),
                ],
            ),
            make_tool_aware_response(content="done"),
        ]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_alpha", args={"value": "ok"}, tool_call_id="c1"),
                ]
            )

        scenario = Stage9Scenario(
            user_input="read in wrong session mode",
            execution_context=ctx,
            ref_responses=ref_responses,
            pyd_model_fn=pyd_fn,
            expected_model_requests_ref=2,
            expected_model_requests_pyd=2,
        )

        obs = run_scenario(
            scenario,
            registry=registry,
            catalog=catalog,
            context_builder=context_builder,
            ref_counters=ref_counters,
            pyd_counters=pyd_counters,
        )

        assert_model_visible_tool_parity(
            obs,
            expected_names=self.EXPECTED_NAMES,
            expected_requests=2,
        )


# ==============================================================================
# C24-E07: A21 hidden-tool exposure — read_alpha present, write_alpha absent
# ==============================================================================


class TestC24E07HiddenToolExposureA21:
    """A21: hidden-but-real tool — read_alpha, read_beta exposed; write_alpha absent.

    Proves from literal model-facing tool list that write_alpha is absent
    while read_alpha and read_beta are present. Then verifies the model
    deliberately requests write_alpha → ModelError with zero executor attempts.
    """

    READ_NAMES: tuple[str, ...] = ("read_alpha", "read_beta")

    def test_hidden_tool_exposure_a21(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()
        tc = make_tool_call("write_alpha", {"value": "secret"}, "c1")
        ref_responses = [make_tool_aware_response(tool_calls=[tc])]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="write_alpha", args={"value": "secret"}, tool_call_id="c1"
                    ),
                ]
            )

        scenario = Stage9Scenario(
            user_input="use hidden write_alpha",
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

        # Prove literal exposure: read_alpha present, write_alpha absent
        assert_model_visible_tool_parity(
            obs,
            expected_names=self.READ_NAMES,
            expected_requests=1,
        )

        # Prove model deliberately requests write_alpha → ModelError, zero exec
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
# C24-E08: A23 hidden-tool exposure — allowed + hidden batch rejection
# ==============================================================================


class TestC24E08HiddenToolExposureA23:
    """A23: allowed read_alpha + hidden write_alpha — batch rejected.

    Proves from literal model-facing tool list that read_alpha and read_beta
    are present and write_alpha is absent. Then verifies the model requests
    both → ModelError with zero executor attempts (entire batch rejected).
    """

    READ_NAMES: tuple[str, ...] = ("read_alpha", "read_beta")

    def test_hidden_tool_exposure_a23(
        self,
        ref_counters: HandlerCounters,
        pyd_counters: HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
    ) -> None:
        ctx = make_read_context()
        tc1 = make_tool_call("read_alpha", {"value": "ok"}, "c1")
        tc2 = make_tool_call("write_alpha", {"value": "secret"}, "c2")
        ref_responses = [make_tool_aware_response(tool_calls=[tc1, tc2])]

        def pyd_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_alpha", args={"value": "ok"}, tool_call_id="c1"),
                    ToolCallPart(
                        tool_name="write_alpha", args={"value": "secret"}, tool_call_id="c2"
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
            registry=registry,
            catalog=catalog,
            context_builder=context_builder,
            ref_counters=ref_counters,
            pyd_counters=pyd_counters,
        )

        # Prove literal exposure: read_alpha present, write_alpha absent
        assert_model_visible_tool_parity(
            obs,
            expected_names=self.READ_NAMES,
            expected_requests=1,
        )

        # Prove entire batch rejected before execution
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
