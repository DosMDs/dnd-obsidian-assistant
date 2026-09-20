"""Strict JSON serialization for provider-neutral eval reports.

This module owns deterministic encoding plus the public ``report_to_json`` /
``report_from_json`` surface.  Strict fixed-shape decoding lives in
``report_json_decode`` and is re-exported here so the public import path is
stable.

UTF-8, deterministic ordering, ``ensure_ascii=False`` (Russian readable),
``allow_nan=False``, explicit schema version.  Pydantic is intentionally
unavailable inside ``dnd_assistant.evals``.  Standard library + this package
only.
"""

from __future__ import annotations

import json
from typing import Any

from dnd_assistant.evals.completeness import CompletenessReport
from dnd_assistant.evals.contracts import (
    DecisionObservation,
    ExposedToolInfo,
    FailureDiagnostic,
    FullTurnObservation,
    ToolCallObservation,
)
from dnd_assistant.evals.latency import LatencyReport, LatencySummary
from dnd_assistant.evals.metrics import MetricSummary
from dnd_assistant.evals.report import EvalReport, EvalReportIdentity
from dnd_assistant.evals.report_json_decode import report_from_json

__all__ = ["report_from_json", "report_to_json"]

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
    include_diagnostics = report.identity.report_schema_version >= 3
    return {
        "identity": _encode_identity(report.identity),
        "runtime": {
            "mode": report.runtime.mode,
            "label": report.runtime.label,
            "metadata": dict(report.runtime.metadata),
        },
        "sample_contract": _encode_completeness(report.sample_contract),
        "decision_observations": [_encode_decision(o) for o in report.decision_observations],
        "full_turn_observations": [
            _encode_full_turn(o, include_diagnostics=include_diagnostics)
            for o in report.full_turn_observations
        ],
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
        "latency": _encode_latency(report.latency),
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
        "run_validity": {
            "runtime_error_count": report.run_validity.runtime_error_count,
            "oracle_consistency_required": report.run_validity.oracle_consistency_required,
            "oracle_consistent": report.run_validity.oracle_consistent,
        },
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


def _encode_full_turn(
    observation: FullTurnObservation, *, include_diagnostics: bool
) -> dict[str, Any]:
    payload: dict[str, Any] = {
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
    if include_diagnostics:
        payload["failure_diagnostic"] = _encode_failure_diagnostic(observation.failure_diagnostic)
    return payload


def _encode_failure_diagnostic(diagnostic: FailureDiagnostic) -> dict[str, Any]:
    return {
        "status": diagnostic.status.value,
        "source_category": (
            None if diagnostic.source_category is None else diagnostic.source_category.value
        ),
        "exception_type": diagnostic.exception_type,
        "cause_chain": list(diagnostic.cause_chain),
        "request_index": diagnostic.request_index,
    }


def _encode_metric(metric: MetricSummary) -> dict[str, Any]:
    return {
        "metric_id": metric.metric_id.value,
        "runtime_label": metric.runtime_label,
        "value": metric.value,
        "numerator": metric.numerator,
        "denominator": metric.denominator,
    }


def _encode_latency_summary(summary: LatencySummary) -> dict[str, Any]:
    return {
        "sample_count": summary.sample_count,
        "p50_seconds": summary.p50_seconds,
        "p95_seconds": summary.p95_seconds,
    }


def _encode_latency(latency: LatencyReport) -> dict[str, Any]:
    return {
        "decision": _encode_latency_summary(latency.decision),
        "full_turn": _encode_latency_summary(latency.full_turn),
    }
