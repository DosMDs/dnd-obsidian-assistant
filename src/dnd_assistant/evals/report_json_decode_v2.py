"""Frozen report schema-v2 strict full-turn decoder.

Schema v2 predates bounded failure diagnostics.  Its fixed shape is preserved
exactly: the ``failure_diagnostic`` key is neither required nor permitted, and
decoding supplies the explicit not-available diagnostic.  Standard library +
this package only.
"""

from __future__ import annotations

from typing import Any

from dnd_assistant.evals.contracts import FullTurnObservation
from dnd_assistant.evals.report_json_decode_shared import (
    as_mapping,
    decode_full_turn_fields,
    require_keys,
)

V2_FULL_TURN_KEYS = frozenset(
    {
        "scenario_id",
        "repetition",
        "duration_seconds",
        "success",
        "terminal_kind",
        "initial_tool_calls",
        "executed_tool_calls",
        "tool_call_count",
        "tool_execution_count",
        "model_request_count",
        "handler_call_count",
        "write_handler_count",
        "exposed_tools",
        "error_type",
        "error_message",
    }
)


def decode_full_turn_v2(data: Any) -> FullTurnObservation:
    """Decode a schema-v2 full-turn observation (no failure diagnostics)."""
    mapping = as_mapping(data, "full_turn_observations entry")
    require_keys(mapping, set(V2_FULL_TURN_KEYS), "full_turn_observations")
    return FullTurnObservation(**decode_full_turn_fields(mapping))
