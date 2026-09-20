"""Shared strict-decoding primitives and version-agnostic report shapes.

Both the frozen schema-v2 decoder and the current schema-v3 decoder build on
these helpers.  This module owns only shapes that are identical across report
schema versions plus the strict primitive validators.  Standard library + this
package only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from dnd_assistant.evals.completeness import CompletenessReport
from dnd_assistant.evals.contracts import (
    DecisionObservation,
    ExposedToolInfo,
    FullTurnObservation,
    ToolCallObservation,
)
from dnd_assistant.evals.latency import LatencyReport, LatencySummary
from dnd_assistant.evals.metrics import MetricId, MetricSummary
from dnd_assistant.evals.report import (
    EvalQualityResult,
    EvalReport,
    EvalReportIdentity,
    EvalRuntimeInfo,
    EvalRunValidity,
    EvalSafetyResult,
    EvalSampleScore,
)

FullTurnDecoder = Callable[[Any], FullTurnObservation]


def decode_identity(
    data: dict[str, Any], *, allowed_versions: frozenset[int]
) -> EvalReportIdentity:
    """Decode the report identity, enforcing an allowed schema-version set."""
    require_keys(
        data,
        {
            "report_schema_version",
            "dataset_id",
            "dataset_version",
            "dataset_fingerprint",
            "sample_plan_id",
            "sample_plan_fingerprint",
            "prompt_version",
        },
        "identity",
    )
    version = require_int(data, "report_schema_version", "identity")
    if version not in allowed_versions:
        raise ValueError(
            f"unsupported report_schema_version {version!r}; "
            f"expected one of {sorted(allowed_versions)}"
        )
    return EvalReportIdentity(
        report_schema_version=version,
        dataset_id=require_str(data, "dataset_id", "identity"),
        dataset_version=require_str(data, "dataset_version", "identity"),
        dataset_fingerprint=require_str(data, "dataset_fingerprint", "identity"),
        sample_plan_id=require_str(data, "sample_plan_id", "identity"),
        sample_plan_fingerprint=require_str(data, "sample_plan_fingerprint", "identity"),
        prompt_version=require_str(data, "prompt_version", "identity"),
    )


def decode_report(
    data: dict[str, Any],
    *,
    identity: EvalReportIdentity,
    full_turn_decoder: FullTurnDecoder,
) -> EvalReport:
    """Decode a report body given the already-decoded identity."""
    runtime = decode_runtime(require_mapping(data, "runtime", "report"))
    sample_contract = decode_completeness(require_mapping(data, "sample_contract", "report"))
    decision_observations = tuple(
        decode_decision(item) for item in require_list(data, "decision_observations", "report")
    )
    full_turn_observations = tuple(
        full_turn_decoder(item) for item in require_list(data, "full_turn_observations", "report")
    )
    metrics = tuple(decode_metric(item) for item in require_list(data, "metrics", "report"))
    sample_scores = tuple(
        decode_sample_score(item) for item in require_list(data, "sample_scores", "report")
    )
    latency = decode_latency(require_mapping(data, "latency", "report"))
    safety = decode_safety(require_mapping(data, "safety", "report"))
    quality = decode_quality(require_mapping(data, "quality", "report"))
    run_validity = decode_run_validity(require_mapping(data, "run_validity", "report"))
    accepted = require_bool(data, "accepted", "report")
    reasons = tuple(
        as_str(item, "reasons entry") for item in require_list(data, "reasons", "report")
    )

    return EvalReport(
        identity=identity,
        runtime=runtime,
        sample_contract=sample_contract,
        decision_observations=decision_observations,
        full_turn_observations=full_turn_observations,
        metrics=metrics,
        sample_scores=sample_scores,
        latency=latency,
        safety=safety,
        quality=quality,
        run_validity=run_validity,
        accepted=accepted,
        reasons=reasons,
    )


def decode_runtime(data: dict[str, Any]) -> EvalRuntimeInfo:
    require_keys(data, {"mode", "label", "metadata"}, "runtime")
    metadata_raw = require_mapping(data, "metadata", "runtime")
    metadata_keys: list[tuple[str, str]] = []
    for key, value in metadata_raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("runtime.metadata must map string keys to string values")
        metadata_keys.append((key, value))
    return EvalRuntimeInfo(
        mode=require_str(data, "mode", "runtime"),
        label=require_str(data, "label", "runtime"),
        metadata=tuple(sorted(metadata_keys)),
    )


def decode_completeness(data: dict[str, Any]) -> CompletenessReport:
    require_keys(
        data,
        {
            "expected_sample_count",
            "observed_decision_count",
            "observed_full_turn_count",
            "missing",
            "duplicates",
            "unknown_scenarios",
            "out_of_range_repetitions",
            "ordering_ok",
            "complete",
            "errors",
        },
        "sample_contract",
    )
    return CompletenessReport(
        expected_sample_count=require_int(data, "expected_sample_count", "sample_contract"),
        observed_decision_count=require_int(data, "observed_decision_count", "sample_contract"),
        observed_full_turn_count=require_int(data, "observed_full_turn_count", "sample_contract"),
        missing=decode_keys(data, "missing"),
        duplicates=decode_keys(data, "duplicates"),
        unknown_scenarios=tuple(
            as_str(item, "unknown_scenarios entry")
            for item in require_list(data, "unknown_scenarios", "sample_contract")
        ),
        out_of_range_repetitions=decode_keys(data, "out_of_range_repetitions"),
        ordering_ok=require_bool(data, "ordering_ok", "sample_contract"),
        complete=require_bool(data, "complete", "sample_contract"),
        errors=tuple(
            as_str(item, "errors entry") for item in require_list(data, "errors", "sample_contract")
        ),
    )


def decode_keys(data: dict[str, Any], field: str) -> tuple[tuple[str, int], ...]:
    result: list[tuple[str, int]] = []
    for item in require_list(data, field, "sample_contract"):
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError(f"sample_contract.{field} entries must be [scenario_id, repetition]")
        scenario_id, repetition = item
        if not isinstance(scenario_id, str) or not is_int(repetition):
            raise ValueError(f"sample_contract.{field} entries must be [str, int]")
        result.append((scenario_id, repetition))
    return tuple(result)


def decode_tool_call(data: Any) -> ToolCallObservation:
    mapping = as_mapping(data, "tool_calls entry")
    require_keys(
        mapping, {"tool_name", "arguments", "call_id", "schema_valid", "is_write"}, "tool_calls"
    )
    arguments = require_mapping(mapping, "arguments", "tool_calls")
    call_id = mapping["call_id"]
    if call_id is not None and not isinstance(call_id, str):
        raise ValueError("tool_calls.call_id must be a string or null")
    return ToolCallObservation(
        tool_name=require_str(mapping, "tool_name", "tool_calls"),
        arguments=dict(arguments),
        call_id=call_id,
        schema_valid=require_bool(mapping, "schema_valid", "tool_calls"),
        is_write=require_bool(mapping, "is_write", "tool_calls"),
    )


def decode_exposed(data: Any) -> ExposedToolInfo | None:
    if data is None:
        return None
    mapping = as_mapping(data, "exposed_tools")
    require_keys(mapping, {"tool_names", "has_write"}, "exposed_tools")
    names = tuple(
        as_str(item, "tool_names entry")
        for item in require_list(mapping, "tool_names", "exposed_tools")
    )
    return ExposedToolInfo(
        tool_names=names, has_write=require_bool(mapping, "has_write", "exposed_tools")
    )


def decode_decision(data: Any) -> DecisionObservation:
    mapping = as_mapping(data, "decision_observations entry")
    require_keys(
        mapping,
        {
            "scenario_id",
            "repetition",
            "duration_seconds",
            "tool_calls",
            "terminal_kind",
            "terminal_content",
            "exposed_tools",
            "error_type",
            "error_message",
        },
        "decision_observations",
    )
    return DecisionObservation(
        scenario_id=require_str(mapping, "scenario_id", "decision_observations"),
        repetition=require_int(mapping, "repetition", "decision_observations"),
        duration_seconds=require_float(mapping, "duration_seconds", "decision_observations"),
        tool_calls=tuple(
            decode_tool_call(item)
            for item in require_list(mapping, "tool_calls", "decision_observations")
        ),
        terminal_kind=opt_str(mapping, "terminal_kind", "decision_observations"),
        terminal_content=opt_str(mapping, "terminal_content", "decision_observations"),
        exposed_tools=decode_exposed(mapping["exposed_tools"]),
        error_type=opt_str(mapping, "error_type", "decision_observations"),
        error_message=opt_str(mapping, "error_message", "decision_observations"),
    )


def decode_full_turn_fields(mapping: dict[str, Any]) -> dict[str, Any]:
    """Decode the fields shared by every schema version's full-turn shape."""
    return {
        "scenario_id": require_str(mapping, "scenario_id", "full_turn_observations"),
        "repetition": require_int(mapping, "repetition", "full_turn_observations"),
        "duration_seconds": require_float(mapping, "duration_seconds", "full_turn_observations"),
        "success": require_bool(mapping, "success", "full_turn_observations"),
        "terminal_kind": opt_str(mapping, "terminal_kind", "full_turn_observations"),
        "initial_tool_calls": tuple(
            decode_tool_call(item)
            for item in require_list(mapping, "initial_tool_calls", "full_turn_observations")
        ),
        "executed_tool_calls": tuple(
            decode_tool_call(item)
            for item in require_list(mapping, "executed_tool_calls", "full_turn_observations")
        ),
        "tool_call_count": require_int(mapping, "tool_call_count", "full_turn_observations"),
        "tool_execution_count": require_int(
            mapping, "tool_execution_count", "full_turn_observations"
        ),
        "model_request_count": require_int(
            mapping, "model_request_count", "full_turn_observations"
        ),
        "handler_call_count": require_int(mapping, "handler_call_count", "full_turn_observations"),
        "write_handler_count": require_int(
            mapping, "write_handler_count", "full_turn_observations"
        ),
        "exposed_tools": decode_exposed(mapping["exposed_tools"]),
        "error_type": opt_str(mapping, "error_type", "full_turn_observations"),
        "error_message": opt_str(mapping, "error_message", "full_turn_observations"),
    }


def decode_metric(data: Any) -> MetricSummary:
    mapping = as_mapping(data, "metrics entry")
    require_keys(
        mapping, {"metric_id", "runtime_label", "value", "numerator", "denominator"}, "metrics"
    )
    raw_id = require_str(mapping, "metric_id", "metrics")
    try:
        metric_id = MetricId(raw_id)
    except ValueError as exc:
        raise ValueError(f"unknown MetricId {raw_id!r}") from exc
    denominator = mapping["denominator"]
    if denominator is not None and not is_int(denominator):
        raise ValueError("metrics.denominator must be an integer or null")
    return MetricSummary(
        metric_id=metric_id,
        runtime_label=require_str(mapping, "runtime_label", "metrics"),
        value=opt_float(mapping, "value", "metrics"),
        numerator=require_int(mapping, "numerator", "metrics"),
        denominator=denominator,
    )


def decode_sample_score(data: Any) -> EvalSampleScore:
    mapping = as_mapping(data, "sample_scores entry")
    require_keys(
        mapping, {"scenario_id", "repetition", "decision_pass", "full_turn_pass"}, "sample_scores"
    )
    return EvalSampleScore(
        scenario_id=require_str(mapping, "scenario_id", "sample_scores"),
        repetition=require_int(mapping, "repetition", "sample_scores"),
        decision_pass=require_bool(mapping, "decision_pass", "sample_scores"),
        full_turn_pass=require_bool(mapping, "full_turn_pass", "sample_scores"),
    )


def decode_latency(data: dict[str, Any]) -> LatencyReport:
    require_keys(data, {"decision", "full_turn"}, "latency")
    return LatencyReport(
        decision=decode_latency_summary(data["decision"], "latency.decision"),
        full_turn=decode_latency_summary(data["full_turn"], "latency.full_turn"),
    )


def decode_latency_summary(data: Any, context: str) -> LatencySummary:
    mapping = as_mapping(data, context)
    require_keys(mapping, {"sample_count", "p50_seconds", "p95_seconds"}, context)
    sample_count = require_int(mapping, "sample_count", context)
    p50 = opt_nonnegative_float(mapping, "p50_seconds", context)
    p95 = opt_nonnegative_float(mapping, "p95_seconds", context)
    if sample_count == 0:
        if p50 is not None or p95 is not None:
            raise ValueError(f"{context}: empty latency set must have null percentiles")
    elif p50 is None or p95 is None:
        raise ValueError(f"{context}: non-empty latency set must have percentiles")
    elif p50 > p95:
        raise ValueError(f"{context}: p50 must not exceed p95")
    return LatencySummary(sample_count=sample_count, p50_seconds=p50, p95_seconds=p95)


def decode_safety(data: dict[str, Any]) -> EvalSafetyResult:
    require_keys(data, {"unauthorized_write_handler_execution_count", "passed"}, "safety")
    return EvalSafetyResult(
        unauthorized_write_handler_execution_count=require_int(
            data, "unauthorized_write_handler_execution_count", "safety"
        ),
        passed=require_bool(data, "passed", "safety"),
    )


def decode_quality(data: dict[str, Any]) -> EvalQualityResult:
    require_keys(
        data,
        {
            "max_false_write_tool_call_rate",
            "false_write_rate_value",
            "false_write_numerator",
            "false_write_denominator",
            "passed",
        },
        "quality",
    )
    return EvalQualityResult(
        max_false_write_tool_call_rate=opt_float(data, "max_false_write_tool_call_rate", "quality"),
        false_write_rate_value=opt_float(data, "false_write_rate_value", "quality"),
        false_write_numerator=require_int(data, "false_write_numerator", "quality"),
        false_write_denominator=require_int(data, "false_write_denominator", "quality"),
        passed=require_bool(data, "passed", "quality"),
    )


def decode_run_validity(data: dict[str, Any]) -> EvalRunValidity:
    require_keys(
        data,
        {"runtime_error_count", "oracle_consistency_required", "oracle_consistent"},
        "run_validity",
    )
    return EvalRunValidity(
        runtime_error_count=require_int(data, "runtime_error_count", "run_validity"),
        oracle_consistency_required=require_bool(
            data, "oracle_consistency_required", "run_validity"
        ),
        oracle_consistent=require_bool(data, "oracle_consistent", "run_validity"),
    )


# ── Primitive validation helpers ───────────────────────────────────────────


def is_int(value: Any) -> bool:
    """True only for a real ``int`` (never ``bool``)."""
    return isinstance(value, int) and not isinstance(value, bool)


def require_keys(data: dict[str, Any], expected: set[str], context: str) -> None:
    keys = set(data)
    missing = expected - keys
    if missing:
        raise ValueError(f"{context}: missing required keys {sorted(missing)}")
    unexpected = keys - expected
    if unexpected:
        raise ValueError(f"{context}: unexpected keys {sorted(unexpected)}")


def as_str(value: Any, context: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a string")
    return value


def as_mapping(data: Any, context: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError(f"{context} must be an object")
    return data


def require_mapping(data: dict[str, Any], field: str, context: str) -> dict[str, Any]:
    value = data.get(field)
    if not isinstance(value, dict):
        raise ValueError(f"{context}.{field} must be an object")
    return value


def require_list(data: dict[str, Any], field: str, context: str) -> list[Any]:
    value = data.get(field)
    if not isinstance(value, list):
        raise ValueError(f"{context}.{field} must be a list")
    return value


def require_str(data: dict[str, Any], field: str, context: str) -> str:
    value = data.get(field)
    if not isinstance(value, str):
        raise ValueError(f"{context}.{field} must be a string")
    return value


def opt_str(data: dict[str, Any], field: str, context: str) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{context}.{field} must be a string or null")
    return value


def require_int(data: dict[str, Any], field: str, context: str) -> int:
    value = data.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{context}.{field} must be an integer")
    return value


def require_float(data: dict[str, Any], field: str, context: str) -> float:
    return require_number(data, field, context)


def opt_float(data: dict[str, Any], field: str, context: str) -> float | None:
    value = data.get(field)
    if value is None:
        return None
    return require_number(data, field, context)


def opt_nonnegative_float(data: dict[str, Any], field: str, context: str) -> float | None:
    value = opt_float(data, field, context)
    if value is not None and value < 0:
        raise ValueError(f"{context}.{field} must be non-negative")
    return value


def require_number(data: dict[str, Any], field: str, context: str) -> float:
    value = data.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{context}.{field} must be a number")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{context}.{field} must be finite")
    return result


def require_bool(data: dict[str, Any], field: str, context: str) -> bool:
    value = data.get(field)
    if not isinstance(value, bool):
        raise ValueError(f"{context}.{field} must be a boolean")
    return value
