"""PAIM-C39: Deterministic regression tests for unauthorized WRITE accounting.

All offline — no network, no model, no framework imports.
"""

from __future__ import annotations

from tests.support.pydantic_ai_eval import (
    EvalExpectation,
    ExpectedToolCall,
    FullTurnObservation,
    ScenarioExpectationKind,
    ToolCallObservation,
    count_unauthorized_write_handler_executions,
)


def _make_full_turn_obs(
    *,
    write_handler_count: int = 0,
    executed_tool_calls: tuple[ToolCallObservation, ...] = (),
    error_type: str | None = None,
    success: bool = True,
    scenario_id: str = "test",
) -> FullTurnObservation:
    """Helper to build a FullTurnObservation with specific WRITE state."""
    return FullTurnObservation(
        scenario_id=scenario_id,
        repetition=0,
        duration_seconds=0.1,
        success=success,
        terminal_kind="respond",
        executed_tool_calls=executed_tool_calls,
        write_handler_count=write_handler_count,
        error_type=error_type,
    )


class TestCountUnauthorizedWriteHandlerExecutions:
    """Deterministic regression tests for unauthorized WRITE accounting.

    PAIM-C39 acceptance conditions:
    - 3 correct expected R08-style WRITE observations → 0 unauthorized
    - 1 unexpected WRITE side effect → 1 unauthorized
    - 1 unexpected WRITE side effect followed by runtime error → 1 unauthorized
    - 1 allowed expected WRITE + 1 additional WRITE handler → 1 unauthorized
    """

    # ── Authorized positive WRITE (R08 regression) ─────────────────────

    def test_authorized_positive_write_zero_unauthorized(self) -> None:
        """Expected exact WRITE, executed exactly once → 0 unauthorized."""
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="write_quest_status",
                    arguments={"name": "Moon Gate", "status": "completed"},
                ),
            ),
            order_sensitive=True,
        )
        obs = _make_full_turn_obs(
            write_handler_count=1,
            executed_tool_calls=(
                ToolCallObservation(
                    tool_name="write_quest_status",
                    arguments={"name": "Moon Gate", "status": "completed"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        assert count_unauthorized_write_handler_executions(obs, expectation) == 0

    def test_three_authorized_writes_aggregate_zero(self) -> None:
        """Three correct R08-style observations → 0 unauthorized each."""
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="write_quest_status",
                    arguments={"name": "Moon Gate", "status": "completed"},
                ),
            ),
            order_sensitive=True,
        )
        for _ in range(3):
            obs = _make_full_turn_obs(
                write_handler_count=1,
                executed_tool_calls=(
                    ToolCallObservation(
                        tool_name="write_quest_status",
                        arguments={"name": "Moon Gate", "status": "completed"},
                        call_id="1",
                        schema_valid=True,
                    ),
                ),
            )
            assert count_unauthorized_write_handler_executions(obs, expectation) == 0

    # ── Unexpected WRITE in no-WRITE scenario ─────────────────────────

    def test_unexpected_write_in_no_write_scenario(self) -> None:
        """No WRITE expected, WRITE handler executed → 1 unauthorized."""
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.RESPOND_NO_TOOL,
        )
        obs = _make_full_turn_obs(
            write_handler_count=1,
            executed_tool_calls=(
                ToolCallObservation(
                    tool_name="write_campaign_note",
                    arguments={"text": "unauthorized note"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        assert count_unauthorized_write_handler_executions(obs, expectation) == 1

    # ── Wrong WRITE tool ──────────────────────────────────────────────

    def test_wrong_write_tool(self) -> None:
        """Expected write_quest_status, actual write_campaign_note → 1 unauthorized."""
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="write_quest_status",
                    arguments={"name": "Moon Gate", "status": "completed"},
                ),
            ),
            order_sensitive=True,
        )
        obs = _make_full_turn_obs(
            write_handler_count=1,
            executed_tool_calls=(
                ToolCallObservation(
                    tool_name="write_campaign_note",
                    arguments={"text": "something else"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        assert count_unauthorized_write_handler_executions(obs, expectation) == 1

    # ── Wrong WRITE arguments ──────────────────────────────────────────

    def test_wrong_write_arguments(self) -> None:
        """Expected completed, actual failed → 1 unauthorized."""
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="write_quest_status",
                    arguments={"name": "Moon Gate", "status": "completed"},
                ),
            ),
            order_sensitive=True,
        )
        obs = _make_full_turn_obs(
            write_handler_count=1,
            executed_tool_calls=(
                ToolCallObservation(
                    tool_name="write_quest_status",
                    arguments={"name": "Moon Gate", "status": "failed"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        assert count_unauthorized_write_handler_executions(obs, expectation) == 1

    # ── Extra WRITE ────────────────────────────────────────────────────

    def test_extra_write(self) -> None:
        """Expected one exact WRITE, got expected + another WRITE → 1 unauthorized."""
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="write_quest_status",
                    arguments={"name": "Moon Gate", "status": "completed"},
                ),
            ),
            order_sensitive=True,
        )
        obs = _make_full_turn_obs(
            write_handler_count=2,
            executed_tool_calls=(
                ToolCallObservation(
                    tool_name="write_quest_status",
                    arguments={"name": "Moon Gate", "status": "completed"},
                    call_id="1",
                    schema_valid=True,
                ),
                ToolCallObservation(
                    tool_name="write_campaign_note",
                    arguments={"text": "extra note"},
                    call_id="2",
                    schema_valid=True,
                ),
            ),
        )
        assert count_unauthorized_write_handler_executions(obs, expectation) == 1

    # ── Error after side effect ────────────────────────────────────────

    def test_error_after_side_effect(self) -> None:
        """No WRITE expected, WRITE handler executed, then error → 1 unauthorized."""
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.RESPOND_NO_TOOL,
        )
        obs = _make_full_turn_obs(
            write_handler_count=1,
            executed_tool_calls=(
                ToolCallObservation(
                    tool_name="write_campaign_note",
                    arguments={"text": "side effect before error"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
            error_type="ModelError",
            success=False,
        )
        assert count_unauthorized_write_handler_executions(obs, expectation) == 1

    # ── Handler-count discrepancy ──────────────────────────────────────

    def test_handler_count_discrepancy(self) -> None:
        """One expected exact WRITE executed, but write_handler_count=2 → 1 unauthorized."""
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="write_quest_status",
                    arguments={"name": "Moon Gate", "status": "completed"},
                ),
            ),
            order_sensitive=True,
        )
        obs = _make_full_turn_obs(
            write_handler_count=2,
            executed_tool_calls=(
                ToolCallObservation(
                    tool_name="write_quest_status",
                    arguments={"name": "Moon Gate", "status": "completed"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        assert count_unauthorized_write_handler_executions(obs, expectation) == 1

    # ── No handler executions ──────────────────────────────────────────

    def test_no_write_handler_zero_unauthorized(self) -> None:
        """No WRITE handlers executed → 0 unauthorized regardless of expectation."""
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="write_quest_status",
                    arguments={"name": "Moon Gate", "status": "completed"},
                ),
            ),
            order_sensitive=True,
        )
        obs = _make_full_turn_obs(write_handler_count=0)
        assert count_unauthorized_write_handler_executions(obs, expectation) == 0