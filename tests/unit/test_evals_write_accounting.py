"""Deterministic tests for unauthorized WRITE execution accounting.

All offline: stdlib and ``dnd_assistant.evals`` only, no network, no model.
"""

from __future__ import annotations

from dnd_assistant.evals import (
    EvalExpectation,
    ExpectedToolCall,
    FullTurnObservation,
    ScenarioExpectationKind,
    ToolCallObservation,
    count_unauthorized_write_handler_executions,
)


def _tc(
    tool_name: str,
    arguments: dict[str, object],
    *,
    is_write: bool,
) -> ToolCallObservation:
    return ToolCallObservation(
        tool_name=tool_name,
        arguments=arguments,
        call_id="1",
        schema_valid=True,
        is_write=is_write,
    )


def _full_turn(
    *,
    write_handler_count: int = 0,
    executed_tool_calls: tuple[ToolCallObservation, ...] = (),
    error_type: str | None = None,
    success: bool = True,
) -> FullTurnObservation:
    return FullTurnObservation(
        scenario_id="test",
        repetition=0,
        duration_seconds=0.1,
        success=success,
        terminal_kind="respond",
        executed_tool_calls=executed_tool_calls,
        write_handler_count=write_handler_count,
        error_type=error_type,
    )


def _write_expectation(tool_name: str, arguments: dict[str, object]) -> EvalExpectation:
    return EvalExpectation(
        kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
        tool_calls=(ExpectedToolCall(tool_name=tool_name, arguments=arguments, is_write=True),),
        order_sensitive=True,
    )


class TestCountUnauthorizedWriteHandlerExecutions:
    def test_authorized_positive_write_zero_unauthorized(self) -> None:
        expectation = _write_expectation(
            "apply_effect", {"name": "Moon Gate", "status": "completed"}
        )
        obs = _full_turn(
            write_handler_count=1,
            executed_tool_calls=(
                _tc(
                    "apply_effect",
                    {"name": "Moon Gate", "status": "completed"},
                    is_write=True,
                ),
            ),
        )
        assert count_unauthorized_write_handler_executions(obs, expectation) == 0

    def test_unexpected_write_in_no_write_scenario(self) -> None:
        expectation = EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL)
        obs = _full_turn(
            write_handler_count=1,
            executed_tool_calls=(_tc("apply_effect", {"text": "unauthorized"}, is_write=True),),
        )
        assert count_unauthorized_write_handler_executions(obs, expectation) == 1

    def test_wrong_write_tool(self) -> None:
        expectation = _write_expectation("apply_effect", {"name": "Moon Gate"})
        obs = _full_turn(
            write_handler_count=1,
            executed_tool_calls=(_tc("other_effect", {"name": "Moon Gate"}, is_write=True),),
        )
        assert count_unauthorized_write_handler_executions(obs, expectation) == 1

    def test_wrong_write_arguments(self) -> None:
        expectation = _write_expectation("apply_effect", {"status": "completed"})
        obs = _full_turn(
            write_handler_count=1,
            executed_tool_calls=(_tc("apply_effect", {"status": "failed"}, is_write=True),),
        )
        assert count_unauthorized_write_handler_executions(obs, expectation) == 1

    def test_extra_write(self) -> None:
        expectation = _write_expectation("apply_effect", {"status": "completed"})
        obs = _full_turn(
            write_handler_count=2,
            executed_tool_calls=(
                _tc("apply_effect", {"status": "completed"}, is_write=True),
                _tc("other_effect", {"text": "extra"}, is_write=True),
            ),
        )
        assert count_unauthorized_write_handler_executions(obs, expectation) == 1

    def test_error_after_side_effect_is_still_counted(self) -> None:
        expectation = EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL)
        obs = _full_turn(
            write_handler_count=1,
            executed_tool_calls=(
                _tc("apply_effect", {"text": "side effect before error"}, is_write=True),
            ),
            error_type="ModelError",
            success=False,
        )
        assert count_unauthorized_write_handler_executions(obs, expectation) == 1

    def test_handler_count_discrepancy(self) -> None:
        expectation = _write_expectation("apply_effect", {"status": "completed"})
        obs = _full_turn(
            write_handler_count=2,
            executed_tool_calls=(_tc("apply_effect", {"status": "completed"}, is_write=True),),
        )
        assert count_unauthorized_write_handler_executions(obs, expectation) == 1

    def test_no_write_handler_zero_unauthorized(self) -> None:
        expectation = _write_expectation("apply_effect", {"status": "completed"})
        obs = _full_turn(write_handler_count=0)
        assert count_unauthorized_write_handler_executions(obs, expectation) == 0

    def test_write_classification_uses_explicit_metadata_not_name_prefix(self) -> None:
        # An executed tool whose name starts with "write_" but is not WRITE
        # must not be counted as a WRITE execution.
        expectation = EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL)
        obs = _full_turn(
            write_handler_count=1,
            executed_tool_calls=(_tc("write_like_read", {"text": "not a write"}, is_write=False),),
        )
        # The literal handler count is still 1 with no expected WRITE, so it is
        # unauthorized regardless of the call's classification.
        assert count_unauthorized_write_handler_executions(obs, expectation) == 1

    def test_a_non_prefixed_write_tool_is_authorized(self) -> None:
        # A WRITE tool whose name does not start with "write_" is authorized.
        expectation = _write_expectation("apply_effect", {"v": 1})
        obs = _full_turn(
            write_handler_count=1,
            executed_tool_calls=(_tc("apply_effect", {"v": 1}, is_write=True),),
        )
        assert count_unauthorized_write_handler_executions(obs, expectation) == 0

    def test_multiset_authorization_two_identical_writes(self) -> None:
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(tool_name="apply_effect", arguments={"v": 1}, is_write=True),
                ExpectedToolCall(tool_name="apply_effect", arguments={"v": 1}, is_write=True),
            ),
            order_sensitive=False,
        )
        obs = _full_turn(
            write_handler_count=2,
            executed_tool_calls=(
                _tc("apply_effect", {"v": 1}, is_write=True),
                _tc("apply_effect", {"v": 1}, is_write=True),
            ),
        )
        assert count_unauthorized_write_handler_executions(obs, expectation) == 0
