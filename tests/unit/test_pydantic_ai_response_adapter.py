"""Unit tests for the shared Pydantic AI response adapter (PAIM-C15).

Tests the ``adapt_pydantic_tool_calls()`` helper that is shared between
PAIM-07 (PydanticAIFastAgent) and PAIM-08 (PydanticAIAgentRuntime).
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from pydantic_ai.messages import ToolCallPart

from dnd_assistant.application.pydantic_ai_response_adapter import (
    adapt_pydantic_tool_calls,
)
from dnd_assistant.errors import ModelError

# ==============================================================================
# Helpers
# ==============================================================================


def _make_call(
    tool_name: str = "read_alpha",
    args: dict | None = None,
    tool_call_id: str | None = "call-1",
) -> ToolCallPart:
    return ToolCallPart(
        tool_name=tool_name,
        args=args if args is not None else {"value": "hello"},
        tool_call_id=tool_call_id,
    )


# ==============================================================================
# Normal cases
# ==============================================================================


class TestNormalAdaptation:
    """Normal tool-call adaptation scenarios."""

    def test_single_call(self) -> None:
        """Single valid tool call is adapted correctly."""
        calls: Sequence[ToolCallPart] = [_make_call()]
        result = adapt_pydantic_tool_calls(
            calls,
            snapshot_names=("read_alpha", "read_beta"),
        )
        assert len(result) == 1
        assert result[0].name == "read_alpha"
        assert result[0].arguments == {"value": "hello"}
        assert result[0].call_id == "call-1"

    def test_two_calls_preserves_order(self) -> None:
        """Two calls are preserved in exact model order."""
        calls: Sequence[ToolCallPart] = [
            _make_call(tool_name="read_alpha", args={"value": "first"}, tool_call_id="c1"),
            _make_call(tool_name="read_beta", args={"number": 42}, tool_call_id="c2"),
        ]
        result = adapt_pydantic_tool_calls(
            calls,
            snapshot_names=("read_alpha", "read_beta"),
        )
        assert len(result) == 2
        assert result[0].name == "read_alpha"
        assert result[0].arguments == {"value": "first"}
        assert result[0].call_id == "c1"
        assert result[1].name == "read_beta"
        assert result[1].arguments == {"number": 42}
        assert result[1].call_id == "c2"

    def test_none_call_id(self) -> None:
        """A call with None tool_call_id is adapted correctly."""
        calls: Sequence[ToolCallPart] = [
            _make_call(tool_call_id=None),
        ]
        result = adapt_pydantic_tool_calls(
            calls,
            snapshot_names=("read_alpha", "read_beta"),
        )
        assert len(result) == 1
        assert result[0].call_id is None

    def test_empty_args_dict(self) -> None:
        """Empty dict args are adapted correctly."""
        calls: Sequence[ToolCallPart] = [
            _make_call(args={}),
        ]
        result = adapt_pydantic_tool_calls(
            calls,
            snapshot_names=("read_alpha", "read_beta"),
        )
        assert len(result) == 1
        assert result[0].arguments == {}


# ==============================================================================
# Snapshot membership validation
# ==============================================================================


class TestSnapshotMembership:
    """Tool name must be in the frozen snapshot."""

    def test_unknown_tool_name(self) -> None:
        """Unknown tool name raises ModelError."""
        calls: Sequence[ToolCallPart] = [
            _make_call(tool_name="nonexistent_tool"),
        ]
        with pytest.raises(ModelError) as exc_info:
            adapt_pydantic_tool_calls(
                calls,
                snapshot_names=("read_alpha", "read_beta"),
            )
        assert "nonexistent_tool" in str(exc_info.value)
        assert "not in the frozen exposure" in str(exc_info.value)

    def test_hidden_tool_name(self) -> None:
        """A registered-but-not-exposed tool name raises ModelError."""
        calls: Sequence[ToolCallPart] = [
            _make_call(tool_name="write_alpha"),
        ]
        with pytest.raises(ModelError) as exc_info:
            adapt_pydantic_tool_calls(
                calls,
                snapshot_names=("read_alpha", "read_beta"),
            )
        assert "write_alpha" in str(exc_info.value)

    def test_mixed_known_and_unknown(self) -> None:
        """First call valid, second unknown — ModelError, zero adapted."""
        calls: Sequence[ToolCallPart] = [
            _make_call(tool_name="read_alpha", tool_call_id="c1"),
            _make_call(tool_name="unknown_tool", tool_call_id="c2"),
        ]
        with pytest.raises(ModelError):
            adapt_pydantic_tool_calls(
                calls,
                snapshot_names=("read_alpha", "read_beta"),
            )


# ==============================================================================
# Argument validation
# ==============================================================================


class TestArgumentValidation:
    """Malformed/non-object arguments are rejected."""

    def test_non_finite_float_nan(self) -> None:
        """NaN in arguments raises ModelError."""
        calls: Sequence[ToolCallPart] = [
            _make_call(args={"value": float("nan")}),
        ]
        with pytest.raises(ModelError):
            adapt_pydantic_tool_calls(
                calls,
                snapshot_names=("read_alpha", "read_beta"),
            )

    def test_non_finite_float_inf(self) -> None:
        """Infinity in arguments raises ModelError."""
        calls: Sequence[ToolCallPart] = [
            _make_call(args={"value": float("inf")}),
        ]
        with pytest.raises(ModelError):
            adapt_pydantic_tool_calls(
                calls,
                snapshot_names=("read_alpha", "read_beta"),
            )

    def test_non_finite_float_neg_inf(self) -> None:
        """-Infinity in arguments raises ModelError."""
        calls: Sequence[ToolCallPart] = [
            _make_call(args={"value": float("-inf")}),
        ]
        with pytest.raises(ModelError):
            adapt_pydantic_tool_calls(
                calls,
                snapshot_names=("read_alpha", "read_beta"),
            )


# ==============================================================================
# Structural preflight — entire batch before any adaptation
# ==============================================================================


class TestStructuralPreflight:
    """Structural preflight rejects the entire batch before any adaptation."""

    def test_whole_batch_rejected_on_first_invalid(self) -> None:
        """Call 1 valid, call 2 NaN — ModelError, zero adapted calls returned."""
        calls: Sequence[ToolCallPart] = [
            _make_call(tool_name="read_alpha", args={"value": "ok"}, tool_call_id="c1"),
            _make_call(tool_name="read_beta", args={"value": float("nan")}, tool_call_id="c2"),
            _make_call(tool_name="read_alpha", args={"value": "also-ok"}, tool_call_id="c3"),
        ]
        with pytest.raises(ModelError):
            adapt_pydantic_tool_calls(
                calls,
                snapshot_names=("read_alpha", "read_beta"),
            )


# ==============================================================================
# Cause preservation
# ==============================================================================


class TestCausePreservation:
    """Original validation/parsing cause is retained where applicable."""

    def test_nan_cause_retained(self) -> None:
        """NaN value retains the original ValueError/AssertionError as cause."""
        calls: Sequence[ToolCallPart] = [
            _make_call(args={"value": float("nan")}),
        ]
        with pytest.raises(ModelError) as exc_info:
            adapt_pydantic_tool_calls(
                calls,
                snapshot_names=("read_alpha", "read_beta"),
            )
        assert exc_info.value.__cause__ is not None
