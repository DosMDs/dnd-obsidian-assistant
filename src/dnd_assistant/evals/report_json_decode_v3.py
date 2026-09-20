"""Current report schema-v3 strict full-turn decoder.

Schema v3 adds one bounded, sanitized per-sample ``failure_diagnostic`` object
to the full-turn observation.  Its fixed shape is strict: unknown or malformed
diagnostic fields are rejected.  Standard library + this package only.
"""

from __future__ import annotations

from typing import Any

from dnd_assistant.evals.contracts import (
    MAX_CAUSE_CHAIN_LENGTH,
    FailureDiagnostic,
    FailureDiagnosticStatus,
    FailureSourceCategory,
    FullTurnObservation,
    is_canonical_type_token,
)
from dnd_assistant.evals.report_json_decode_shared import (
    as_mapping,
    decode_full_turn_fields,
    is_int,
    require_keys,
    require_str,
)

V3_FULL_TURN_KEYS = frozenset(
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
        "failure_diagnostic",
    }
)

_DIAGNOSTIC_KEYS = frozenset(
    {
        "status",
        "source_category",
        "exception_type",
        "cause_chain",
        "request_index",
    }
)


def decode_failure_diagnostic(data: Any) -> FailureDiagnostic:
    """Decode and strictly validate a schema-v3 failure diagnostic."""
    mapping = as_mapping(data, "failure_diagnostic")
    require_keys(mapping, set(_DIAGNOSTIC_KEYS), "failure_diagnostic")

    raw_status = require_str(mapping, "status", "failure_diagnostic")
    try:
        status = FailureDiagnosticStatus(raw_status)
    except ValueError as exc:
        raise ValueError(f"unknown failure_diagnostic.status {raw_status!r}") from exc

    source_category = _decode_source_category(mapping["source_category"])
    exception_type = _decode_opt_str(mapping["exception_type"], "exception_type")
    if exception_type is not None and not is_canonical_type_token(exception_type):
        raise ValueError(
            "failure_diagnostic.exception_type must be a canonical sanitized type token"
        )
    cause_chain = _decode_cause_chain(mapping["cause_chain"])
    request_index = _decode_request_index(mapping["request_index"])

    if status is FailureDiagnosticStatus.NOT_AVAILABLE:
        if (
            source_category is not None
            or exception_type is not None
            or cause_chain
            or request_index is not None
        ):
            raise ValueError("failure_diagnostic not_available must be empty")
    else:
        if source_category is None:
            raise ValueError("failure_diagnostic observed requires source_category")
        if not exception_type:
            raise ValueError("failure_diagnostic observed requires exception_type")

    return FailureDiagnostic(
        status=status,
        source_category=source_category,
        exception_type=exception_type,
        cause_chain=cause_chain,
        request_index=request_index,
    )


def _decode_source_category(value: Any) -> FailureSourceCategory | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("failure_diagnostic.source_category must be a string or null")
    try:
        return FailureSourceCategory(value)
    except ValueError as exc:
        raise ValueError(f"unknown failure_diagnostic.source_category {value!r}") from exc


def _decode_opt_str(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"failure_diagnostic.{field} must be a string or null")
    return value


def _decode_cause_chain(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("failure_diagnostic.cause_chain must be a list")
    if len(value) > MAX_CAUSE_CHAIN_LENGTH:
        raise ValueError(
            f"failure_diagnostic.cause_chain must have at most {MAX_CAUSE_CHAIN_LENGTH} entries"
        )
    entries: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("failure_diagnostic.cause_chain entries must be strings")
        if not is_canonical_type_token(item):
            raise ValueError(
                "failure_diagnostic.cause_chain entries must be canonical sanitized type tokens"
            )
        entries.append(item)
    return tuple(entries)


def _decode_request_index(value: Any) -> int | None:
    if value is None:
        return None
    if not is_int(value):
        raise ValueError("failure_diagnostic.request_index must be an integer or null")
    if value < 0:
        raise ValueError("failure_diagnostic.request_index must be non-negative")
    return value


def decode_full_turn_v3(data: Any) -> FullTurnObservation:
    """Decode a schema-v3 full-turn observation with its failure diagnostic."""
    mapping = as_mapping(data, "full_turn_observations entry")
    require_keys(mapping, set(V3_FULL_TURN_KEYS), "full_turn_observations")
    fields = decode_full_turn_fields(mapping)
    fields["failure_diagnostic"] = decode_failure_diagnostic(mapping["failure_diagnostic"])
    return FullTurnObservation(**fields)
