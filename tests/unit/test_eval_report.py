"""Unit tests: eval report DTO, serialization, safety/quality and comparison."""

from __future__ import annotations

import dataclasses
import json

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
    DecisionObservation,
    EvalExpectation,
    EvalScenario,
    ExposedToolInfo,
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
    dataset: EvalDataset, decision: DecisionObservation, full_turn: FullTurnObservation
) -> EvalReport:
    return build_eval_report(
        dataset,
        runtime_mode="scripted",
        runtime_label="scripted-oracle",
        prompt_version="agent-v3",
        decision_observations=[decision],
        full_turn_observations=[full_turn],
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
    assert report.runtime_error_count == 1
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
