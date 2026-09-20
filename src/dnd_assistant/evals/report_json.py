"""Strict JSON serialization for provider-neutral eval reports.

UTF-8, deterministic ordering, ``ensure_ascii=False`` (Russian readable),
``allow_nan=False``, explicit schema version and strict load validation.

Pydantic is intentionally unavailable inside ``dnd_assistant.evals``; the
loader validates primitive shapes and enum identities manually.  Standard
library + this package only.
"""

from __future__ import annotations

import json
from typing import Any

from dnd_assistant.evals.completeness import CompletenessReport
from dnd_assistant.evals.contracts import (
    DecisionObservation,
    ExposedToolInfo,
    FullTurnObservation,
    ToolCallObservation,
)
from dnd_assistant.evals.metrics import MetricId, MetricSummary
from dnd_assistant.evals.report import (
    REPORT_SCHEMA_VERSION,
    EvalQualityResult,
    EvalReport,
    EvalReportIdentity,
    EvalRuntimeInfo,
    EvalSafetyResult,
    EvalSampleScore,
)

# ── Encoding ───────────────────────────────────────────────────────────────


def report_to_json(report: EvalReport) -> str:
    """Serialize a report to deterministic UTF-8 JSON with a trailing newline."""
    payload = _encode_report(report)
    text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )
    return text + "\n"


def _encode_report(report: EvalReport) -> dict[str, Any]:
    return {
        "identity": _encode_identity(report.identity),
        "runtime": {
            "mode": report.runtime.mode,
            "label": report.runtime.label,
            "metadata": dict(report.runtime.metadata),
        },
        "sample_contract": _encode_completeness(report.sample_contract),
        "decision_observations": [_encode_decision(o) for o in report.decision_observations],
        "full_turn_observations": [_encode_full_turn(o) for o in report.full_turn_observations],
        "metrics": [_encode_metric(m) for m in report.metrics],
        "sample_scores": [
            {
                "scenario_id": s.scenario_id,
                "repetition": s.repetition,
                "decision_pass": s.decision_pass,
                "full_turn_pass": s.full_turn_pass,
            }
            for s in report.sample_scores
        ],
        "safety": {
            "unauthorized_write_handler_execution_count": report.safety.unauthorized_write_handler_execution_count,
            "passed": report.safety.passed,
        },
        "quality": {
            "max_false_write_tool_call_rate": report.quality.max_false_write_tool_call_rate,
            "false_write_rate_value": report.quality.false_write_rate_value,
            "false_write_numerator": report.quality.false_write_numerator,
            "false_write_denominator": report.quality.false_write_denominator,
            "passed": report.quality.passed,
        },
        "runtime_error_count": report.runtime_error_count,
        "accepted": report.accepted,
        "reasons": list(report.reasons),
    }


def _encode_identity(identity: EvalReportIdentity) -> dict[str, Any]:
    return {
        "report_schema_version": identity.report_schema_version,
        "dataset_id": identity.dataset_id,
        "dataset_version": identity.dataset_version,
        "dataset_fingerprint": identity.dataset_fingerprint,
        "sample_plan_id": identity.sample_plan_id,
        "sample_plan_fingerprint": identity.sample_plan_fingerprint,
        "prompt_version": identity.prompt_version,
    }


def _encode_completeness(report: CompletenessReport) -> dict[str, Any]:
    return {
        "expected_sample_count": report.expected_sample_count,
        "observed_decision_count": report.observed_decision_count,
        "observed_full_turn_count": report.observed_full_turn_count,
        "missing": [list(k) for k in report.missing],
        "duplicates": [list(k) for k in report.duplicates],
        "unknown_scenarios": list(report.unknown_scenarios),
        "out_of_range_repetitions": [list(k) for k in report.out_of_range_repetitions],
        "ordering_ok": report.ordering_ok,
        "complete": report.complete,
        "errors": list(report.errors),
    }


def _encode_exposed(exposed: ExposedToolInfo | None) -> dict[str, Any] | None:
    if exposed is None:
        return None
    return {"tool_names": list(exposed.tool_names), "has_write": exposed.has_write}


def _encode_tool_call(call: ToolCallObservation) -> dict[str, Any]:
    return {
        "tool_name": call.tool_name,
        "arguments": call.arguments,
        "call_id": call.call_id,
        "schema_valid": call.schema_valid,
        "is_write": call.is_write,
    }


def _encode_decision(observation: DecisionObservation) -> dict[str, Any]:
    return {
        "scenario_id": observation.scenario_id,
        "repetition": observation.repetition,
        "duration_seconds": observation.duration_seconds,
        "tool_calls": [_encode_tool_call(c) for c in observation.tool_calls],
        "terminal_kind": observation.terminal_kind,
        "terminal_content": observation.terminal_content,
        "exposed_tools": _encode_exposed(observation.exposed_tools),
        "error_type": observation.error_type,
        "error_message": observation.error_message,
    }


def _encode_full_turn(observation: FullTurnObservation) -> dict[str, Any]:
    return {
        "scenario_id": observation.scenario_id,
        "repetition": observation.repetition,
        "duration_seconds": observation.duration_seconds,
        "success": observation.success,
        "terminal_kind": observation.terminal_kind,
        "initial_tool_calls": [_encode_tool_call(c) for c in observation.initial_tool_calls],
        "executed_tool_calls": [_encode_tool_call(c) for c in observation.executed_tool_calls],
        "tool_call_count": observation.tool_call_count,
        "tool_execution_count": observation.tool_execution_count,
        "model_request_count": observation.model_request_count,
        "handler_call_count": observation.handler_call_count,
        "write_handler_count": observation.write_handler_count,
        "exposed_tools": _encode_exposed(observation.exposed_tools),
        "error_type": observation.error_type,
        "error_message": observation.error_message,
    }


def _encode_metric(metric: MetricSummary) -> dict[str, Any]:
    return {
        "metric_id": metric.metric_id.value,
        "runtime_label": metric.runtime_label,
        "value": metric.value,
        "numerator": metric.numerator,
        "denominator": metric.denominator,
    }


# ── Decoding ───────────────────────────────────────────────────────────────


def report_from_json(text: str) -> EvalReport:
    """Parse and strictly validate a report JSON document.

    Raises:
        ValueError: On malformed JSON, wrong schema version, missing/unknown
            required fields or wrong primitive types.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"report JSON is malformed: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("report JSON root must be an object")

    _require_keys(
        data,
        {
            "identity",
            "runtime",
            "sample_contract",
            "decision_observations",
            "full_turn_observations",
            "metrics",
            "sample_scores",
            "safety",
            "quality",
            "runtime_error_count",
            "accepted",
            "reasons",
        },
        "report",
    )

    identity = _decode_identity(_require_mapping(data, "identity", "report"))
    runtime = _decode_runtime(_require_mapping(data, "runtime", "report"))
    sample_contract = _decode_completeness(_require_mapping(data, "sample_contract", "report"))
    decision_observations = tuple(
        _decode_decision(item) for item in _require_list(data, "decision_observations", "report")
    )
    full_turn_observations = tuple(
        _decode_full_turn(item) for item in _require_list(data, "full_turn_observations", "report")
    )
    metrics = tuple(_decode_metric(item) for item in _require_list(data, "metrics", "report"))
    sample_scores = tuple(
        _decode_sample_score(item) for item in _require_list(data, "sample_scores", "report")
    )
    safety = _decode_safety(_require_mapping(data, "safety", "report"))
    quality = _decode_quality(_require_mapping(data, "quality", "report"))
    runtime_error_count = _require_int(data, "runtime_error_count", "report")
    accepted = _require_bool(data, "accepted", "report")
    reasons = tuple(
        _as_str(item, "reasons entry") for item in _require_list(data, "reasons", "report")
    )

    return EvalReport(
        identity=identity,
        runtime=runtime,
        sample_contract=sample_contract,
        decision_observations=decision_observations,
        full_turn_observations=full_turn_observations,
        metrics=metrics,
        sample_scores=sample_scores,
        safety=safety,
        quality=quality,
        runtime_error_count=runtime_error_count,
        accepted=accepted,
        reasons=reasons,
    )


def _decode_identity(data: dict[str, Any]) -> EvalReportIdentity:
    _require_keys(
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
    version = _require_int(data, "report_schema_version", "identity")
    if version != REPORT_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported report_schema_version {version!r}; expected {REPORT_SCHEMA_VERSION}"
        )
    return EvalReportIdentity(
        report_schema_version=version,
        dataset_id=_require_str(data, "dataset_id", "identity"),
        dataset_version=_require_str(data, "dataset_version", "identity"),
        dataset_fingerprint=_require_str(data, "dataset_fingerprint", "identity"),
        sample_plan_id=_require_str(data, "sample_plan_id", "identity"),
        sample_plan_fingerprint=_require_str(data, "sample_plan_fingerprint", "identity"),
        prompt_version=_require_str(data, "prompt_version", "identity"),
    )


def _decode_runtime(data: dict[str, Any]) -> EvalRuntimeInfo:
    _require_keys(data, {"mode", "label", "metadata"}, "runtime")
    metadata_raw = _require_mapping(data, "metadata", "runtime")
    metadata = tuple(sorted((str(k), str(v)) for k, v in metadata_raw.items()))
    return EvalRuntimeInfo(
        mode=_require_str(data, "mode", "runtime"),
        label=_require_str(data, "label", "runtime"),
        metadata=metadata,
    )


def _decode_completeness(data: dict[str, Any]) -> CompletenessReport:
    _require_keys(
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
        expected_sample_count=_require_int(data, "expected_sample_count", "sample_contract"),
        observed_decision_count=_require_int(data, "observed_decision_count", "sample_contract"),
        observed_full_turn_count=_require_int(data, "observed_full_turn_count", "sample_contract"),
        missing=_decode_keys(data, "missing"),
        duplicates=_decode_keys(data, "duplicates"),
        unknown_scenarios=tuple(
            _as_str(item, "unknown_scenarios entry")
            for item in _require_list(data, "unknown_scenarios", "sample_contract")
        ),
        out_of_range_repetitions=_decode_keys(data, "out_of_range_repetitions"),
        ordering_ok=_require_bool(data, "ordering_ok", "sample_contract"),
        complete=_require_bool(data, "complete", "sample_contract"),
        errors=tuple(
            _as_str(item, "errors entry")
            for item in _require_list(data, "errors", "sample_contract")
        ),
    )


def _decode_keys(data: dict[str, Any], field: str) -> tuple[tuple[str, int], ...]:
    result: list[tuple[str, int]] = []
    for item in _require_list(data, field, "sample_contract"):
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError(f"sample_contract.{field} entries must be [scenario_id, repetition]")
        scenario_id, repetition = item
        if not isinstance(scenario_id, str) or not isinstance(repetition, int):
            raise ValueError(f"sample_contract.{field} entries must be [str, int]")
        result.append((scenario_id, repetition))
    return tuple(result)


def _decode_tool_call(data: Any) -> ToolCallObservation:
    mapping = _as_mapping(data, "tool_calls entry")
    _require_keys(
        mapping, {"tool_name", "arguments", "call_id", "schema_valid", "is_write"}, "tool_calls"
    )
    arguments = _require_mapping(mapping, "arguments", "tool_calls")
    call_id = mapping["call_id"]
    if call_id is not None and not isinstance(call_id, str):
        raise ValueError("tool_calls.call_id must be a string or null")
    return ToolCallObservation(
        tool_name=_require_str(mapping, "tool_name", "tool_calls"),
        arguments=dict(arguments),
        call_id=call_id,
        schema_valid=_require_bool(mapping, "schema_valid", "tool_calls"),
        is_write=_require_bool(mapping, "is_write", "tool_calls"),
    )


def _decode_exposed(data: Any) -> ExposedToolInfo | None:
    if data is None:
        return None
    mapping = _as_mapping(data, "exposed_tools")
    _require_keys(mapping, {"tool_names", "has_write"}, "exposed_tools")
    names = tuple(
        _as_str(item, "tool_names entry")
        for item in _require_list(mapping, "tool_names", "exposed_tools")
    )
    return ExposedToolInfo(
        tool_names=names, has_write=_require_bool(mapping, "has_write", "exposed_tools")
    )


def _decode_decision(data: Any) -> DecisionObservation:
    mapping = _as_mapping(data, "decision_observations entry")
    _require_keys(
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
        scenario_id=_require_str(mapping, "scenario_id", "decision_observations"),
        repetition=_require_int(mapping, "repetition", "decision_observations"),
        duration_seconds=_require_float(mapping, "duration_seconds", "decision_observations"),
        tool_calls=tuple(
            _decode_tool_call(item)
            for item in _require_list(mapping, "tool_calls", "decision_observations")
        ),
        terminal_kind=_opt_str(mapping, "terminal_kind", "decision_observations"),
        terminal_content=_opt_str(mapping, "terminal_content", "decision_observations"),
        exposed_tools=_decode_exposed(mapping["exposed_tools"]),
        error_type=_opt_str(mapping, "error_type", "decision_observations"),
        error_message=_opt_str(mapping, "error_message", "decision_observations"),
    )


def _decode_full_turn(data: Any) -> FullTurnObservation:
    mapping = _as_mapping(data, "full_turn_observations entry")
    _require_keys(
        mapping,
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
        },
        "full_turn_observations",
    )
    return FullTurnObservation(
        scenario_id=_require_str(mapping, "scenario_id", "full_turn_observations"),
        repetition=_require_int(mapping, "repetition", "full_turn_observations"),
        duration_seconds=_require_float(mapping, "duration_seconds", "full_turn_observations"),
        success=_require_bool(mapping, "success", "full_turn_observations"),
        terminal_kind=_opt_str(mapping, "terminal_kind", "full_turn_observations"),
        initial_tool_calls=tuple(
            _decode_tool_call(item)
            for item in _require_list(mapping, "initial_tool_calls", "full_turn_observations")
        ),
        executed_tool_calls=tuple(
            _decode_tool_call(item)
            for item in _require_list(mapping, "executed_tool_calls", "full_turn_observations")
        ),
        tool_call_count=_require_int(mapping, "tool_call_count", "full_turn_observations"),
        tool_execution_count=_require_int(
            mapping, "tool_execution_count", "full_turn_observations"
        ),
        model_request_count=_require_int(mapping, "model_request_count", "full_turn_observations"),
        handler_call_count=_require_int(mapping, "handler_call_count", "full_turn_observations"),
        write_handler_count=_require_int(mapping, "write_handler_count", "full_turn_observations"),
        exposed_tools=_decode_exposed(mapping["exposed_tools"]),
        error_type=_opt_str(mapping, "error_type", "full_turn_observations"),
        error_message=_opt_str(mapping, "error_message", "full_turn_observations"),
    )


def _decode_metric(data: Any) -> MetricSummary:
    mapping = _as_mapping(data, "metrics entry")
    _require_keys(
        mapping, {"metric_id", "runtime_label", "value", "numerator", "denominator"}, "metrics"
    )
    raw_id = _require_str(mapping, "metric_id", "metrics")
    try:
        metric_id = MetricId(raw_id)
    except ValueError as exc:
        raise ValueError(f"unknown MetricId {raw_id!r}") from exc
    denominator = mapping["denominator"]
    if denominator is not None and not isinstance(denominator, int):
        raise ValueError("metrics.denominator must be an int or null")
    return MetricSummary(
        metric_id=metric_id,
        runtime_label=_require_str(mapping, "runtime_label", "metrics"),
        value=_opt_float(mapping, "value", "metrics"),
        numerator=_require_int(mapping, "numerator", "metrics"),
        denominator=denominator,
    )


def _decode_sample_score(data: Any) -> EvalSampleScore:
    mapping = _as_mapping(data, "sample_scores entry")
    _require_keys(
        mapping, {"scenario_id", "repetition", "decision_pass", "full_turn_pass"}, "sample_scores"
    )
    return EvalSampleScore(
        scenario_id=_require_str(mapping, "scenario_id", "sample_scores"),
        repetition=_require_int(mapping, "repetition", "sample_scores"),
        decision_pass=_require_bool(mapping, "decision_pass", "sample_scores"),
        full_turn_pass=_require_bool(mapping, "full_turn_pass", "sample_scores"),
    )


def _decode_safety(data: dict[str, Any]) -> EvalSafetyResult:
    _require_keys(data, {"unauthorized_write_handler_execution_count", "passed"}, "safety")
    return EvalSafetyResult(
        unauthorized_write_handler_execution_count=_require_int(
            data, "unauthorized_write_handler_execution_count", "safety"
        ),
        passed=_require_bool(data, "passed", "safety"),
    )


def _decode_quality(data: dict[str, Any]) -> EvalQualityResult:
    _require_keys(
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
        max_false_write_tool_call_rate=_opt_float(
            data, "max_false_write_tool_call_rate", "quality"
        ),
        false_write_rate_value=_opt_float(data, "false_write_rate_value", "quality"),
        false_write_numerator=_require_int(data, "false_write_numerator", "quality"),
        false_write_denominator=_require_int(data, "false_write_denominator", "quality"),
        passed=_require_bool(data, "passed", "quality"),
    )


# ── Primitive validation helpers ───────────────────────────────────────────


def _require_keys(data: dict[str, Any], expected: set[str], context: str) -> None:
    missing = expected - set(data)
    if missing:
        raise ValueError(f"{context}: missing required keys {sorted(missing)}")


def _as_str(value: Any, context: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a string")
    return value


def _as_mapping(data: Any, context: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError(f"{context} must be an object")
    return data


def _require_mapping(data: dict[str, Any], field: str, context: str) -> dict[str, Any]:
    value = data.get(field)
    if not isinstance(value, dict):
        raise ValueError(f"{context}.{field} must be an object")
    return value


def _require_list(data: dict[str, Any], field: str, context: str) -> list[Any]:
    value = data.get(field)
    if not isinstance(value, list):
        raise ValueError(f"{context}.{field} must be a list")
    return value


def _require_str(data: dict[str, Any], field: str, context: str) -> str:
    value = data.get(field)
    if not isinstance(value, str):
        raise ValueError(f"{context}.{field} must be a string")
    return value


def _opt_str(data: dict[str, Any], field: str, context: str) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{context}.{field} must be a string or null")
    return value


def _require_int(data: dict[str, Any], field: str, context: str) -> int:
    value = data.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{context}.{field} must be an integer")
    return value


def _require_float(data: dict[str, Any], field: str, context: str) -> float:
    return _require_number(data, field, context)


def _opt_float(data: dict[str, Any], field: str, context: str) -> float | None:
    value = data.get(field)
    if value is None:
        return None
    return _require_number(data, field, context)


def _require_number(data: dict[str, Any], field: str, context: str) -> float:
    value = data.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{context}.{field} must be a number")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{context}.{field} must be finite")
    return result


def _require_bool(data: dict[str, Any], field: str, context: str) -> bool:
    value = data.get(field)
    if not isinstance(value, bool):
        raise ValueError(f"{context}.{field} must be a boolean")
    return value
