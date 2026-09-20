"""Unit tests: eval report DTO, serialization, safety/quality and comparison."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable

import pytest

from dnd_assistant.evals import (
    BaselineStatus,
    EvalReport,
    build_eval_report,
    compare_eval_reports,
    report_from_json,
    report_to_json,
)
from dnd_assistant.evals.contracts import (
    FAILURE_DIAGNOSTIC_NOT_AVAILABLE,
    DecisionObservation,
    EvalExpectation,
    EvalScenario,
    ExposedToolInfo,
    FailureDiagnostic,
    FailureDiagnosticStatus,
    FailureSourceCategory,
    FullTurnObservation,
    ScenarioExpectationKind,
    ToolCallObservation,
)
from dnd_assistant.evals.dataset import (
    EvalCase,
    EvalDataset,
    EvalExecutionSpec,
    EvalPermission,
    EvalQualityPolicy,
    EvalSamplePlan,
    EvalSessionState,
)


def _dataset(
    *,
    expectation: EvalExpectation | None = None,
    permission: EvalPermission = EvalPermission.READ,
    threshold: float | None = 0.0,
    version: str = "1",
) -> EvalDataset:
    scenario = EvalScenario(
        scenario_id="EVAL-U-001",
        user_input="Вопрос?",
        expectation=expectation or EvalExpectation(ScenarioExpectationKind.RESPOND_NO_TOOL),
    )
    case = EvalCase(
        scenario=scenario,
        execution=EvalExecutionSpec(permission, EvalSessionState.NO_ACTIVE),
    )
    return EvalDataset(
        dataset_id="unit",
        dataset_version=version,
        cases=(case,),
        quality_policy=EvalQualityPolicy(threshold),
        sample_plan=EvalSamplePlan("single", 1),
    )


def _decision(**overrides: object) -> DecisionObservation:
    base: dict[str, object] = {
        "scenario_id": "EVAL-U-001",
        "repetition": 0,
        "duration_seconds": 0.1,
        "terminal_kind": "respond",
        "terminal_content": '{"kind":"respond","message":"Готово: Арлен"}',
        "exposed_tools": ExposedToolInfo(("search_entities",), False),
    }
    base.update(overrides)
    return DecisionObservation(**base)  # type: ignore[arg-type]


def _full_turn(**overrides: object) -> FullTurnObservation:
    base: dict[str, object] = {
        "scenario_id": "EVAL-U-001",
        "repetition": 0,
        "duration_seconds": 0.2,
        "success": True,
        "terminal_kind": "respond",
        "exposed_tools": ExposedToolInfo(("search_entities",), False),
    }
    base.update(overrides)
    return FullTurnObservation(**base)  # type: ignore[arg-type]


def _report(
    dataset: EvalDataset,
    decision: DecisionObservation,
    full_turn: FullTurnObservation,
    *,
    oracle: bool = False,
) -> EvalReport:
    return build_eval_report(
        dataset,
        runtime_mode="scripted",
        runtime_label="scripted-oracle",
        prompt_version="agent-v3",
        decision_observations=[decision],
        full_turn_observations=[full_turn],
        oracle_consistency_required=oracle,
    )


def test_report_round_trip() -> None:
    report = _report(_dataset(), _decision(), _full_turn())
    text = report_to_json(report)
    assert report_from_json(text) == report


def test_report_is_readable_russian_utf8() -> None:
    report = _report(_dataset(), _decision(), _full_turn())
    text = report_to_json(report)
    assert "Готово: Арлен" in text
    assert "\\u" not in text


def test_report_has_no_nan_token() -> None:
    report = _report(_dataset(), _decision(), _full_turn())
    text = report_to_json(report)
    assert "NaN" not in text
    assert "Infinity" not in text


def test_strict_schema_version_rejected() -> None:
    report = _report(_dataset(), _decision(), _full_turn())
    payload = json.loads(report_to_json(report))
    payload["identity"]["report_schema_version"] = 999
    with pytest.raises(ValueError, match="unsupported report_schema_version"):
        report_from_json(json.dumps(payload))


def test_missing_required_field_rejected() -> None:
    report = _report(_dataset(), _decision(), _full_turn())
    payload = json.loads(report_to_json(report))
    del payload["safety"]
    with pytest.raises(ValueError, match="missing required keys"):
        report_from_json(json.dumps(payload))


def test_accepts_complete_safe_report() -> None:
    report = _report(_dataset(), _decision(), _full_turn())
    assert report.accepted
    assert report.safety.unauthorized_write_handler_execution_count == 0
    assert report.quality.passed


def test_safety_hard_fail_on_unauthorized_write_execution() -> None:
    expectation = EvalExpectation(ScenarioExpectationKind.RESPOND_NO_TOOL)
    dataset = _dataset(expectation=expectation)
    full_turn = _full_turn(write_handler_count=1)
    report = _report(dataset, _decision(), full_turn)
    assert not report.safety.passed
    assert report.safety.unauthorized_write_handler_execution_count == 1
    assert not report.accepted


def test_quality_fail_on_false_write_tool_call() -> None:
    dataset = _dataset(permission=EvalPermission.WRITE)
    write_call = ToolCallObservation(
        tool_name="record_note",
        arguments={"text": "x"},
        call_id="c1",
        schema_valid=True,
        is_write=True,
    )
    decision = _decision(
        tool_calls=(write_call,),
        terminal_kind=None,
        exposed_tools=ExposedToolInfo(("record_note",), True),
    )
    full_turn = _full_turn(
        exposed_tools=ExposedToolInfo(("record_note",), True),
        initial_tool_calls=(write_call,),
        tool_call_count=1,
    )
    report = _report(dataset, decision, full_turn)
    assert report.quality.false_write_numerator == 1
    assert report.quality.false_write_denominator == 1
    assert not report.quality.passed
    assert not report.accepted


def test_runtime_error_is_persisted_and_blocks_acceptance() -> None:
    decision = _decision(error_type="ModelError", error_message="boom", terminal_kind=None)
    full_turn = _full_turn(success=False, error_type="ModelError", error_message="boom")
    report = _report(_dataset(), decision, full_turn)
    assert report.run_validity.runtime_error_count == 1
    assert report.decision_observations[0].error_type == "ModelError"
    assert report.full_turn_observations[0].error_message == "boom"
    assert not report.accepted


def test_sample_scores_retained() -> None:
    report = _report(_dataset(), _decision(), _full_turn())
    assert len(report.sample_scores) == 1
    assert report.sample_scores[0].decision_pass
    assert report.sample_scores[0].full_turn_pass


def test_incompatible_baseline_rejected() -> None:
    current = _report(_dataset(version="2"), _decision(), _full_turn())
    baseline = _report(_dataset(version="1"), _decision(), _full_turn())
    comparison = compare_eval_reports(current, baseline)
    assert comparison.status is BaselineStatus.INCOMPATIBLE
    assert comparison.incompatible_reasons
    assert comparison.metric_deltas == ()


def test_compatible_baseline_reports_metric_deltas() -> None:
    dataset = _dataset()
    baseline = _report(dataset, _decision(), _full_turn())
    # Current run misses the expected tool (responds no-tool where no-tool is
    # expected); the metrics are identical, so deltas are zero.
    current = _report(dataset, _decision(), _full_turn())
    comparison = compare_eval_reports(current, baseline)
    assert comparison.status is BaselineStatus.COMPATIBLE
    assert comparison.metric_deltas
    assert all(delta.delta == 0.0 for delta in comparison.metric_deltas if delta.delta is not None)


def test_fingerprint_binding_rejects_different_ground_truth() -> None:
    current = _report(_dataset(), _decision(), _full_turn())
    other_case = dataclasses.replace(
        _dataset().cases[0],
        scenario=dataclasses.replace(_dataset().cases[0].scenario, user_input="Другой вопрос?"),
    )
    other_dataset = dataclasses.replace(_dataset(), cases=(other_case,))
    baseline = _report(other_dataset, _decision(), _full_turn())
    comparison = compare_eval_reports(current, baseline)
    assert comparison.status is BaselineStatus.INCOMPATIBLE


# ── Scripted-oracle consistency ────────────────────────────────────────────


def test_oracle_consistency_required_and_consistent() -> None:
    report = _report(_dataset(), _decision(), _full_turn(), oracle=True)
    assert report.run_validity.oracle_consistency_required is True
    assert report.run_validity.oracle_consistent is True
    assert report.accepted


def test_oracle_consistency_failure_rejects_report() -> None:
    # A response with a tool call where no-tool was expected fails the score.
    write_like = ToolCallObservation(
        tool_name="search_entities",
        arguments={"text": "x"},
        call_id="c1",
        schema_valid=True,
        is_write=False,
    )
    decision = _decision(tool_calls=(write_like,), terminal_kind=None)
    full_turn = _full_turn(initial_tool_calls=(write_like,), tool_call_count=1)
    report = _report(_dataset(), decision, full_turn, oracle=True)
    assert report.run_validity.oracle_consistent is False
    assert not report.accepted
    assert any("oracle consistency" in reason for reason in report.reasons)


def test_generic_report_with_score_mismatch_stays_accepted_without_oracle_policy() -> None:
    tool_call = ToolCallObservation(
        tool_name="search_entities",
        arguments={"text": "x"},
        call_id="c1",
        schema_valid=True,
        is_write=False,
    )
    decision = _decision(tool_calls=(tool_call,), terminal_kind=None)
    full_turn = _full_turn(initial_tool_calls=(tool_call,), tool_call_count=1)
    report = _report(_dataset(), decision, full_turn, oracle=False)
    assert report.run_validity.oracle_consistency_required is False
    assert not report.sample_scores[0].decision_pass
    assert report.accepted


# ── Strict JSON decoder ────────────────────────────────────────────────────


def _payload(report: EvalReport) -> dict[str, object]:
    return json.loads(report_to_json(report))


def test_strict_decoder_rejects_unknown_top_level_field() -> None:
    payload = _payload(_report(_dataset(), _decision(), _full_turn()))
    payload["extra_field"] = 1
    with pytest.raises(ValueError, match="unexpected keys"):
        report_from_json(json.dumps(payload))


def test_strict_decoder_rejects_unknown_nested_field() -> None:
    payload = _payload(_report(_dataset(), _decision(), _full_turn()))
    safety = payload["safety"]
    assert isinstance(safety, dict)
    safety["extra_field"] = 1
    with pytest.raises(ValueError, match="unexpected keys"):
        report_from_json(json.dumps(payload))


def test_strict_decoder_rejects_non_string_runtime_metadata() -> None:
    payload = _payload(_report(_dataset(), _decision(), _full_turn()))
    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    runtime["metadata"] = {"build": 7}
    with pytest.raises(ValueError, match="string keys to string values"):
        report_from_json(json.dumps(payload))


def test_strict_decoder_rejects_bool_repetition() -> None:
    payload = _payload(_report(_dataset(), _decision(), _full_turn()))
    observations = payload["decision_observations"]
    assert isinstance(observations, list) and observations
    observations[0]["repetition"] = True
    with pytest.raises(ValueError, match="must be an integer"):
        report_from_json(json.dumps(payload))


def test_strict_decoder_rejects_bool_metric_denominator() -> None:
    payload = _payload(_report(_dataset(), _decision(), _full_turn()))
    metrics = payload["metrics"]
    assert isinstance(metrics, list) and metrics
    metrics[0]["denominator"] = True
    with pytest.raises(ValueError, match="must be an integer or null"):
        report_from_json(json.dumps(payload))


def test_strict_decoder_round_trip_and_russian_preserved() -> None:
    report = _report(_dataset(), _decision(), _full_turn())
    text = report_to_json(report)
    assert "Готово: Арлен" in text
    assert report_from_json(text) == report


# ── Schema v3 latency ──────────────────────────────────────────────────────


def test_schema_version_is_v3() -> None:
    payload = _payload(_report(_dataset(), _decision(), _full_turn()))
    identity = payload["identity"]
    assert isinstance(identity, dict)
    assert identity["report_schema_version"] == 3


def test_schema_v1_rejected() -> None:
    payload = _payload(_report(_dataset(), _decision(), _full_turn()))
    identity = payload["identity"]
    assert isinstance(identity, dict)
    identity["report_schema_version"] = 1
    with pytest.raises(ValueError, match="unsupported report_schema_version"):
        report_from_json(json.dumps(payload))


# ── Schema v3 failure diagnostics ──────────────────────────────────────────


def _observed_diagnostic() -> FailureDiagnostic:
    return FailureDiagnostic(
        status=FailureDiagnosticStatus.OBSERVED,
        source_category=FailureSourceCategory.FRAMEWORK_PROCESSING,
        exception_type="UnexpectedModelBehavior",
        cause_chain=("ModelHTTPError",),
        request_index=1,
    )


def test_schema_v3_round_trip_preserves_diagnostics() -> None:
    full_turn = _full_turn(
        success=False,
        error_type="ModelError",
        error_message="Pydantic AI model request failed",
        failure_diagnostic=_observed_diagnostic(),
    )
    report = _report(_dataset(), _decision(), full_turn)
    decoded = report_from_json(report_to_json(report))
    assert decoded == report
    assert decoded.full_turn_observations[0].failure_diagnostic == _observed_diagnostic()


def test_schema_v3_success_has_explicit_not_available_diagnostic() -> None:
    report = _report(_dataset(), _decision(), _full_turn())
    assert report.full_turn_observations[0].failure_diagnostic == FAILURE_DIAGNOSTIC_NOT_AVAILABLE
    decoded = report_from_json(report_to_json(report))
    assert (
        decoded.full_turn_observations[0].failure_diagnostic.status
        is FailureDiagnosticStatus.NOT_AVAILABLE
    )


def test_schema_v3_rejects_unknown_diagnostic_field() -> None:
    payload = _payload(_report(_dataset(), _decision(), _full_turn()))
    full_turn = payload["full_turn_observations"]
    assert isinstance(full_turn, list)
    diagnostic = full_turn[0]["failure_diagnostic"]
    assert isinstance(diagnostic, dict)
    diagnostic["extra"] = 1
    with pytest.raises(ValueError, match="unexpected keys"):
        report_from_json(json.dumps(payload))


def test_schema_v3_rejects_missing_diagnostic_field() -> None:
    payload = _payload(_report(_dataset(), _decision(), _full_turn()))
    full_turn = payload["full_turn_observations"]
    assert isinstance(full_turn, list)
    del full_turn[0]["failure_diagnostic"]
    with pytest.raises(ValueError, match="missing required keys"):
        report_from_json(json.dumps(payload))


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda d: d.update(status="bogus"), "unknown failure_diagnostic.status"),
        (
            lambda d: d.update(status="observed", source_category="bogus", exception_type="X"),
            "unknown failure_diagnostic.source_category",
        ),
        (
            lambda d: d.update(
                status="observed", source_category="model_request", exception_type=None
            ),
            "requires exception_type",
        ),
        (
            lambda d: d.update(
                status="observed",
                source_category="model_request",
                exception_type="X",
                request_index=-1,
            ),
            "non-negative",
        ),
        (
            lambda d: d.update(
                status="observed",
                source_category="model_request",
                exception_type="X",
                cause_chain=[1],
            ),
            "cause_chain entries must be strings",
        ),
        (
            lambda d: d.update(source_category="model_request"),
            "not_available must be empty",
        ),
    ],
)
def test_schema_v3_rejects_malformed_diagnostic(
    mutate: Callable[[dict[str, object]], None], match: str
) -> None:
    payload = _payload(_report(_dataset(), _decision(), _full_turn()))
    full_turn = payload["full_turn_observations"]
    assert isinstance(full_turn, list)
    diagnostic = full_turn[0]["failure_diagnostic"]
    assert isinstance(diagnostic, dict)
    mutate(diagnostic)
    with pytest.raises(ValueError, match=match):
        report_from_json(json.dumps(payload))


# ── Schema v2 compatibility path ───────────────────────────────────────────


def _v2_payload(report: EvalReport) -> dict[str, object]:
    payload = _payload(report)
    identity = payload["identity"]
    assert isinstance(identity, dict)
    identity["report_schema_version"] = 2
    full_turn = payload["full_turn_observations"]
    assert isinstance(full_turn, list)
    for observation in full_turn:
        assert isinstance(observation, dict)
        del observation["failure_diagnostic"]
    return payload


def test_schema_v2_compatibility_supplies_not_available_diagnostic() -> None:
    payload = _v2_payload(_report(_dataset(), _decision(), _full_turn()))
    decoded = report_from_json(json.dumps(payload))
    assert decoded.identity.report_schema_version == 2
    assert decoded.full_turn_observations[0].failure_diagnostic == FAILURE_DIAGNOSTIC_NOT_AVAILABLE


def test_schema_v2_reencode_omits_diagnostics() -> None:
    payload = _v2_payload(_report(_dataset(), _decision(), _full_turn()))
    decoded = report_from_json(json.dumps(payload))
    reencoded = json.loads(report_to_json(decoded))
    assert reencoded["identity"]["report_schema_version"] == 2
    assert "failure_diagnostic" not in reencoded["full_turn_observations"][0]


def test_schema_v2_rejects_v3_diagnostic_key() -> None:
    payload = _payload(_report(_dataset(), _decision(), _full_turn()))
    identity = payload["identity"]
    assert isinstance(identity, dict)
    identity["report_schema_version"] = 2
    with pytest.raises(ValueError, match="unexpected keys"):
        report_from_json(json.dumps(payload))


def test_diagnostics_do_not_change_scoring_safety_or_acceptance() -> None:
    dataset = _dataset()
    decision = _decision(error_type="ModelError", error_message="boom", terminal_kind=None)
    plain = _full_turn(success=False, error_type="ModelError", error_message="boom")
    with_diag = dataclasses.replace(plain, failure_diagnostic=_observed_diagnostic())
    without = _report(dataset, decision, plain)
    with_report = _report(dataset, decision, with_diag)
    assert without.sample_scores == with_report.sample_scores
    assert without.safety == with_report.safety
    assert without.quality == with_report.quality
    assert without.latency == with_report.latency
    assert without.run_validity == with_report.run_validity
    assert without.accepted == with_report.accepted


def test_latency_derived_from_frozen_observations() -> None:
    report = _report(_dataset(), _decision(duration_seconds=0.25), _full_turn(duration_seconds=0.5))
    assert report.latency.decision.sample_count == 1
    assert report.latency.decision.p50_seconds == 0.25
    assert report.latency.decision.p95_seconds == 0.25
    assert report.latency.full_turn.sample_count == 1
    assert report.latency.full_turn.p50_seconds == 0.5


def test_latency_required_in_json() -> None:
    payload = _payload(_report(_dataset(), _decision(), _full_turn()))
    del payload["latency"]
    with pytest.raises(ValueError, match="missing required keys"):
        report_from_json(json.dumps(payload))


def test_latency_rejects_bool_sample_count() -> None:
    payload = _payload(_report(_dataset(), _decision(), _full_turn()))
    latency = payload["latency"]
    assert isinstance(latency, dict)
    latency["decision"]["sample_count"] = True
    with pytest.raises(ValueError, match="must be an integer"):
        report_from_json(json.dumps(payload))


def test_latency_rejects_negative_percentile() -> None:
    payload = _payload(_report(_dataset(), _decision(), _full_turn()))
    latency = payload["latency"]
    assert isinstance(latency, dict)
    latency["full_turn"]["p50_seconds"] = -1.0
    with pytest.raises(ValueError, match="non-negative"):
        report_from_json(json.dumps(payload))


def test_latency_rejects_inconsistent_nullability() -> None:
    payload = _payload(_report(_dataset(), _decision(), _full_turn()))
    latency = payload["latency"]
    assert isinstance(latency, dict)
    latency["decision"]["p50_seconds"] = None
    with pytest.raises(ValueError, match="must have percentiles"):
        report_from_json(json.dumps(payload))


def test_latency_rejects_p50_greater_than_p95() -> None:
    payload = _payload(_report(_dataset(), _decision(), _full_turn()))
    latency = payload["latency"]
    assert isinstance(latency, dict)
    latency["decision"]["p50_seconds"] = 2.0
    latency["decision"]["p95_seconds"] = 1.0
    with pytest.raises(ValueError, match="p50 must not exceed p95"):
        report_from_json(json.dumps(payload))


def test_compatible_baseline_reports_latency_deltas() -> None:
    dataset = _dataset()
    baseline = _report(dataset, _decision(duration_seconds=0.1), _full_turn(duration_seconds=0.2))
    current = _report(dataset, _decision(duration_seconds=0.4), _full_turn(duration_seconds=0.9))
    comparison = compare_eval_reports(current, baseline)
    assert comparison.status is BaselineStatus.COMPATIBLE
    assert comparison.decision_p50_delta == pytest.approx(0.3)
    assert comparison.full_turn_p50_delta == pytest.approx(0.7)


def test_incompatible_baseline_still_reports_latency_deltas() -> None:
    current = _report(_dataset(version="2"), _decision(), _full_turn())
    baseline = _report(_dataset(version="1"), _decision(), _full_turn())
    comparison = compare_eval_reports(current, baseline)
    assert comparison.status is BaselineStatus.INCOMPATIBLE
    # Identical durations: deltas are present and zero, never a pass/fail input.
    assert comparison.decision_p50_delta == 0.0
