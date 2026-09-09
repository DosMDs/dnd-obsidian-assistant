"""PAIM-11: Stage-9 behavioral parity — scenario P11-A23.

P11-A23 was moved here from P2 to keep P2 below the 1000-line hard limit.
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
    assert_parity,
    build_catalog,
    make_context_builder,
    make_read_context,
    make_registry,
    make_tool_aware_response,
    make_tool_call,
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
# P11-A23: mixed allowed + hidden
# ==============================================================================


class TestP11A23MixedAllowedHidden:
    """P11-A23: mixed allowed + hidden — ModelError, zero executions.

    READ context where read_alpha exposed, write_alpha hidden by permission.
    """

    def test_mixed_allowed_hidden(
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
            name="write_alpha",
            arguments={"value": "secret"},
            call_id="c2",
        )
        ref_responses = [
            make_tool_aware_response(
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
