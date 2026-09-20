"""Unit tests: bounded opt-in eval diagnostic trace (S14-07-DIAG-03).

Offline only: no Ollama, no network.  Proves crash-surviving incremental
evidence, strict non-interference with model/runtime semantics, and the
privacy allowlist.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.function import FunctionModel

from dnd_assistant.composition.eval_model import (
    ModelCallRecorder,
    RecordingPydanticModel,
    build_failing_model,
    build_model_from_responses,
    build_scripted_model,
    terminal_response,
    tool_call_response,
)
from dnd_assistant.composition.eval_ollama import _warm_up
from dnd_assistant.composition.eval_runner import (
    make_request_observer,
    run_dataset,
    run_eval,
)
from dnd_assistant.composition.eval_trace import (
    EVENT_MEASUREMENT_STARTED,
    EVENT_REQUEST_COMPLETED,
    EVENT_REQUEST_FAILED,
    EVENT_REQUEST_STARTED,
    EVENT_SAMPLE_COMPLETED,
    EVENT_SAMPLE_STARTED,
    PHASE_MEASUREMENT,
    EvalTraceError,
    EvalTraceWriter,
    open_eval_trace,
)
from dnd_assistant.evals.contracts import (
    EvalExpectation,
    EvalScenario,
    ScenarioExpectationKind,
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
from dnd_assistant.evals.datasets.product_v1 import build_product_v1_dataset

# ── Helpers ────────────────────────────────────────────────────────────────


def _run(model: Model) -> object:
    async def _go() -> object:
        return await model.request(
            messages=[],
            model_settings=None,
            model_request_parameters=ModelRequestParameters(),
        )

    return asyncio.run(_go())


def _dataset(
    *,
    scenario_id: str = "EVAL-DIAG-001",
    user_input: str = "Что-то?",
    expectation: EvalExpectation | None = None,
) -> EvalDataset:
    scenario = EvalScenario(
        scenario_id,
        user_input,
        expectation or EvalExpectation(ScenarioExpectationKind.RESPOND_NO_TOOL),
    )
    case = EvalCase(
        scenario=scenario,
        execution=EvalExecutionSpec(EvalPermission.READ, EvalSessionState.NO_ACTIVE),
    )
    return EvalDataset(
        dataset_id="unit",
        dataset_version="1",
        cases=(case,),
        quality_policy=EvalQualityPolicy(0.0),
        sample_plan=EvalSamplePlan("single", 1),
    )


def _scripted_factory(recorders: list[ModelCallRecorder] | None = None) -> Any:
    def _factory(expectation: EvalExpectation) -> tuple[object, ModelCallRecorder]:
        recorder = ModelCallRecorder()
        if recorders is not None:
            recorders.append(recorder)
        return build_scripted_model(expectation, recorder=recorder), recorder

    return _factory


def _read_events(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


def _core(report: Any) -> tuple[Any, ...]:
    """Non-dynamic report projection (excludes clocks/latency/durations)."""
    full_turns = tuple(
        (
            o.scenario_id,
            o.repetition,
            o.success,
            o.terminal_kind,
            tuple(c.tool_name for c in o.initial_tool_calls),
            tuple(c.tool_name for c in o.executed_tool_calls),
            o.tool_call_count,
            o.tool_execution_count,
            o.model_request_count,
            o.handler_call_count,
            o.write_handler_count,
            o.error_type,
            o.failure_diagnostic.status.value,
        )
        for o in report.full_turn_observations
    )
    decisions = tuple(
        (
            o.scenario_id,
            o.repetition,
            o.terminal_kind,
            o.terminal_content,
            tuple(c.tool_name for c in o.tool_calls),
            o.error_type,
        )
        for o in report.decision_observations
    )
    return (
        full_turns,
        decisions,
        tuple((s.scenario_id, s.decision_pass, s.full_turn_pass) for s in report.sample_scores),
        report.safety.unauthorized_write_handler_execution_count,
        report.safety.passed,
        report.quality.passed,
        report.quality.false_write_numerator,
        report.quality.false_write_denominator,
        report.run_validity.runtime_error_count,
        report.accepted,
        tuple(sorted((m.metric_id.value, m.numerator, m.denominator) for m in report.metrics)),
    )


class _FailingHandle:
    """Handle whose writes always fail, to simulate a mid-run disk fault."""

    def write(self, _data: str) -> int:
        raise OSError("simulated disk fault")

    def flush(self) -> None:
        raise OSError("simulated disk fault")

    def close(self) -> None:
        pass


# ── 1. Disabled by default ─────────────────────────────────────────────────


def test_open_trace_none_is_disabled() -> None:
    assert open_eval_trace(None) is None


def test_disabled_trace_creates_no_file(tmp_path: Path) -> None:
    report = run_dataset(
        _dataset(),
        model_factory=_scripted_factory(),
        runtime_mode="scripted",
        runtime_label="scripted-oracle",
        trace=None,
    )
    assert report.accepted
    assert list(tmp_path.iterdir()) == []


# ── 2/12. Explicit path, deterministic JSONL, flush, LF, Windows path ──────


def test_explicit_trace_is_flushed_deterministic_and_lf(tmp_path: Path) -> None:
    path = tmp_path / "sub dir" / "run.eval-trace.jsonl"
    path.parent.mkdir()
    writer = open_eval_trace(path)
    assert writer is not None

    # Every previously completed emit is immediately readable (flush).
    assert [e["event"] for e in _read_events(path)] == ["trace_started"]

    writer.emit(
        EVENT_SAMPLE_STARTED,
        phase=PHASE_MEASUREMENT,
        scenario_id="EVAL-X",
        repetition=0,
    )
    assert [e["event"] for e in _read_events(path)] == ["trace_started", "sample_started"]

    writer.emit(EVENT_SAMPLE_COMPLETED, phase=PHASE_MEASUREMENT, runtime_label="тест")
    events = _read_events(path)
    assert [e["event"] for e in events] == ["trace_started", "sample_started", "sample_completed"]

    raw = path.read_bytes()
    assert b"\r\n" not in raw
    text = raw.decode("utf-8")
    assert "тест" in text  # ensure_ascii=False
    for line in text.splitlines():
        assert line == json.dumps(
            json.loads(line), ensure_ascii=False, sort_keys=True, allow_nan=False
        )
    writer.close()


# ── 3. Request lifecycle ordering and shared index ─────────────────────────


def test_request_lifecycle_started_then_completed() -> None:
    events: list[Any] = []
    recorder = ModelCallRecorder()
    recorder.request_observer = events.append
    model = build_model_from_responses(
        [ModelResponse(parts=[TextPart(content="ok")])], recorder=recorder
    )
    _run(model)
    assert [e.outcome for e in events] == [EVENT_REQUEST_STARTED, EVENT_REQUEST_COMPLETED]
    assert events[0].request_index == events[1].request_index == 0


def test_request_lifecycle_started_then_failed() -> None:
    events: list[Any] = []
    recorder = ModelCallRecorder()
    recorder.request_observer = events.append
    model = build_failing_model(RuntimeError("boom"), recorder=recorder)
    with pytest.raises(RuntimeError):
        _run(model)
    assert [e.outcome for e in events] == [EVENT_REQUEST_STARTED, EVENT_REQUEST_FAILED]
    assert events[0].request_index == events[1].request_index == 0
    assert events[1].exception_type == "RuntimeError"


# ── 4. Crash survival before report serialization ──────────────────────────


def test_request_evidence_survives_before_report_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "trace.jsonl"
    writer = open_eval_trace(path)
    assert writer is not None

    def _factory(_expectation: EvalExpectation) -> tuple[object, ModelCallRecorder]:
        recorder = ModelCallRecorder()
        return build_failing_model(RuntimeError("boom"), recorder=recorder), recorder

    import dnd_assistant.composition.eval_runner as runner

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("report assembly failed")

    monkeypatch.setattr(runner, "build_eval_report", _boom)
    with pytest.raises(RuntimeError, match="report assembly failed"):
        run_dataset(
            _dataset(),
            model_factory=_factory,
            runtime_mode="custom",
            runtime_label="custom-candidate",
            trace=writer,
        )

    names = [e["event"] for e in _read_events(path)]
    assert EVENT_REQUEST_STARTED in names
    assert EVENT_REQUEST_FAILED in names
    assert EVENT_SAMPLE_COMPLETED in names
    assert "report_written" not in names
    writer.close()


# ── 5. Privacy allowlist ───────────────────────────────────────────────────


def test_trace_never_persists_secret_markers(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    writer = open_eval_trace(path)
    assert writer is not None
    secret = "SECRET_MARKER_abc123"

    def _factory(_expectation: EvalExpectation) -> tuple[object, ModelCallRecorder]:
        recorder = ModelCallRecorder()
        error = RuntimeError(f"{secret} C:\\Users\\alice http://localhost:11434")
        return build_failing_model(error, recorder=recorder), recorder

    run_dataset(
        _dataset(user_input=f"подсказка {secret}"),
        model_factory=_factory,
        runtime_mode="custom",
        runtime_label="custom-candidate",
        trace=writer,
    )
    writer.close()

    text = path.read_text(encoding="utf-8")
    for marker in (secret, "alice", "localhost", "11434", "Users"):
        assert marker not in text


def test_trace_excludes_tool_arguments(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    writer = open_eval_trace(path)
    assert writer is not None
    argument_secret = "ARG_SECRET_xyz"

    def _factory(_expectation: EvalExpectation) -> tuple[object, ModelCallRecorder]:
        recorder = ModelCallRecorder()
        responses = [
            tool_call_response("get_entity", {"entity_id": argument_secret}),
            terminal_response("respond"),
        ]
        return build_model_from_responses(responses, recorder=recorder), recorder

    run_dataset(
        _dataset(expectation=EvalExpectation(ScenarioExpectationKind.NO_TOOL_ANY_TERMINAL)),
        model_factory=_factory,
        runtime_mode="custom",
        runtime_label="custom-candidate",
        trace=writer,
    )
    writer.close()

    text = path.read_text(encoding="utf-8")
    assert argument_secret not in text
    assert "get_entity" in text  # tool names are permitted


# ── 6. Public HTTP classification only ─────────────────────────────────────


def test_provider_http_status_from_public_exception_title(tmp_path: Path) -> None:
    from dnd_assistant.evals.contracts import sanitize_type_token

    path = tmp_path / "trace.jsonl"
    writer = open_eval_trace(path)
    assert writer is not None
    body_secret = "BODY_SECRET_zzz"

    def _raise(_messages: object, _info: object) -> ModelResponse:
        raise ModelHTTPError(404, "qwen", body={"error": body_secret})

    recorder = ModelCallRecorder()
    recorder.request_observer = make_request_observer(writer, "EVAL-X", 0, phase=PHASE_MEASUREMENT)
    model = RecordingPydanticModel(FunctionModel(_raise), recorder=recorder)
    with pytest.raises(ModelHTTPError):
        _run(model)
    writer.close()

    failed = [e for e in _read_events(path) if e["event"] == EVENT_REQUEST_FAILED]
    assert len(failed) == 1
    assert failed[0]["provider_http_status"] == 404
    assert failed[0]["exception_type"] == sanitize_type_token("ModelHTTPError")
    text = path.read_text(encoding="utf-8")
    assert body_secret not in text
    assert "headers" not in text


# ── 7/9. No semantic effect and mid-run fault non-interference ─────────────


def test_trace_does_not_change_scripted_execution(tmp_path: Path) -> None:
    baseline = run_eval(_dataset(), trace=None)
    path = tmp_path / "trace.jsonl"
    writer = open_eval_trace(path)
    assert writer is not None
    with_trace = run_eval(_dataset(), trace=writer)
    writer.close()

    assert _core(with_trace) == _core(baseline)
    assert with_trace.accepted == baseline.accepted
    assert with_trace.run_validity.runtime_error_count == 0


def test_no_additional_model_or_tool_requests(tmp_path: Path) -> None:
    plain_recorders: list[ModelCallRecorder] = []
    run_eval(_dataset(), model_factory=_scripted_factory(plain_recorders), trace=None)

    path = tmp_path / "trace.jsonl"
    writer = open_eval_trace(path)
    assert writer is not None
    traced_recorders: list[ModelCallRecorder] = []
    report = run_eval(
        _dataset(),
        model_factory=_scripted_factory(traced_recorders),
        trace=writer,
    )
    writer.close()

    assert [r.request_count for r in traced_recorders] == [r.request_count for r in plain_recorders]
    assert [o.handler_call_count for o in report.full_turn_observations] == [0]
    assert report.full_turn_observations[0].model_request_count == 1


def test_mid_run_trace_fault_does_not_alter_execution(tmp_path: Path) -> None:
    baseline = run_eval(_dataset(), trace=None)
    path = tmp_path / "trace.jsonl"
    writer = open_eval_trace(path)
    assert writer is not None

    writer._handle = _FailingHandle()  # type: ignore[assignment]

    with_fault = run_eval(_dataset(), trace=writer)
    assert writer.faulted
    assert writer.fault is not None
    assert writer.fault.stage == "write"
    assert writer.fault.exception_type == "OSError"

    assert _core(with_fault) == _core(baseline)
    assert with_fault.run_validity.runtime_error_count == 0
    assert with_fault.accepted == baseline.accepted
    assert all(
        o.failure_diagnostic.status.value == "not_available"
        for o in with_fault.full_turn_observations
    )

    # A later emit is a no-op after the fault.
    writer.emit(EVENT_MEASUREMENT_STARTED)
    writer.close()


# ── 10. Existing classifier reuse ──────────────────────────────────────────


def test_sample_completed_uses_existing_classifier(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    writer = open_eval_trace(path)
    assert writer is not None

    def _factory(_expectation: EvalExpectation) -> tuple[object, ModelCallRecorder]:
        recorder = ModelCallRecorder()
        return build_failing_model(RuntimeError("boom"), recorder=recorder), recorder

    run_dataset(
        _dataset(),
        model_factory=_factory,
        runtime_mode="custom",
        runtime_label="custom-candidate",
        trace=writer,
    )
    writer.close()

    completed = [e for e in _read_events(path) if e["event"] == EVENT_SAMPLE_COMPLETED]
    assert len(completed) == 1
    assert completed[0]["source_category"] == "model_request"
    assert completed[0]["failure_status"] == "observed"
    assert completed[0]["exception_type"] == "RuntimeError"


def test_project_policy_failure_classification(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    writer = open_eval_trace(path)
    assert writer is not None

    def _factory(_expectation: EvalExpectation) -> tuple[object, ModelCallRecorder]:
        recorder = ModelCallRecorder()
        responses = [ModelResponse(parts=[TextPart(content="not json")])]
        return build_model_from_responses(responses, recorder=recorder), recorder

    report = run_dataset(
        _dataset(),
        model_factory=_factory,
        runtime_mode="custom",
        runtime_label="custom-candidate",
        trace=writer,
    )
    writer.close()

    completed = [e for e in _read_events(path) if e["event"] == EVENT_SAMPLE_COMPLETED]
    assert completed[0]["source_category"] == "project_policy"
    assert completed[0]["exception_type"] == "ModelError"
    assert report.run_validity.runtime_error_count == 1


# ── 11. Warm-up / measurement distinction ──────────────────────────────────


def test_warmup_and_measurement_phases_are_distinct(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    writer = open_eval_trace(path)
    assert writer is not None

    product_dataset = build_product_v1_dataset()
    _warm_up(product_dataset, _scripted_factory(), trace=writer)
    run_eval(_dataset(), trace=writer)
    writer.close()

    events = _read_events(path)
    warmup = [e for e in events if e["event"].startswith("warmup")]
    measured = [
        e
        for e in events
        if e["event"] in (EVENT_MEASUREMENT_STARTED, EVENT_SAMPLE_STARTED, EVENT_SAMPLE_COMPLETED)
    ]
    assert warmup
    assert all(e["phase"] == "warmup" for e in warmup)
    assert measured
    assert all(e["phase"] == "measurement" for e in measured)
    assert all(e.get("scenario_id") == "EVAL-DIAG-001" for e in measured if "scenario_id" in e)


# ── 8. Open failure ────────────────────────────────────────────────────────


def test_open_trace_missing_parent_raises(tmp_path: Path) -> None:
    with pytest.raises(EvalTraceError):
        open_eval_trace(tmp_path / "missing" / "trace.jsonl")


def test_open_trace_directory_target_raises(tmp_path: Path) -> None:
    target = tmp_path / "as-dir"
    target.mkdir()
    with pytest.raises(EvalTraceError):
        open_eval_trace(target)


def test_trace_fault_never_misclassified_as_request_failure() -> None:
    # A faulted writer must not manufacture a MODEL_REQUEST failure.
    writer = EvalTraceWriter(path=Path("unused"), _handle=_FailingHandle())  # type: ignore[arg-type]
    recorder = ModelCallRecorder()
    recorder.request_observer = make_request_observer(writer, "EVAL-X", 0, phase=PHASE_MEASUREMENT)
    model = build_model_from_responses(
        [ModelResponse(parts=[TextPart(content="ok")])], recorder=recorder
    )
    _run(model)
    assert writer.faulted
    assert recorder.failure_records == []
    assert recorder.request_count == 1
