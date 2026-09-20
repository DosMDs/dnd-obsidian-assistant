"""Unit tests: bounded eval failure diagnostics (S14-07-DIAG-02).

Covers the recorder-side structured evidence, the final project-error cause
chain, sanitization/privacy, bounded cause chains and runner integration.
No Ollama, no network.
"""

from __future__ import annotations

import asyncio
import json

from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel

from dnd_assistant.composition.eval_failure_diagnostics import (
    bounded_cause_chain,
    build_failure_diagnostic,
)
from dnd_assistant.composition.eval_model import (
    ModelCallFailure,
    ModelCallRecorder,
    RecordingPydanticModel,
    build_failing_model,
)
from dnd_assistant.composition.eval_runner import run_dataset
from dnd_assistant.errors import ModelError, ValidationError
from dnd_assistant.evals.contracts import (
    MAX_CAUSE_CHAIN_LENGTH,
    EvalExpectation,
    EvalScenario,
    FailureDiagnosticStatus,
    FailureSourceCategory,
    ScenarioExpectationKind,
    is_canonical_type_token,
    sanitize_type_token,
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


def _request(model: Model) -> object:
    async def _go() -> object:
        return await model.request(
            messages=[],
            model_settings=None,
            model_request_parameters=ModelRequestParameters(),
        )

    return asyncio.run(_go())


def _recorder_with(
    *,
    request_count: int = 0,
    failures: list[ModelCallFailure] | None = None,
) -> ModelCallRecorder:
    recorder = ModelCallRecorder(request_count=request_count)
    if failures:
        recorder.failure_records.extend(failures)
    return recorder


# ── Recorder-side structured evidence ──────────────────────────────────────


def test_recorder_records_failure_request_index_and_type() -> None:
    recorder = ModelCallRecorder()
    state = {"count": 0}

    def _respond(_messages: object, _info: AgentInfo) -> ModelResponse:
        state["count"] += 1
        if state["count"] == 1:
            return ModelResponse(parts=[TextPart(content="first")])
        raise RuntimeError("second request failed")

    model = RecordingPydanticModel(FunctionModel(_respond), recorder=recorder)
    _request(model)
    try:
        _request(model)
    except RuntimeError:
        pass

    assert recorder.request_count == 2
    assert len(recorder.failure_records) == 1
    record = recorder.failure_records[0]
    assert record.request_index == 1
    assert record.exception_type == "RuntimeError"


def test_recorder_success_has_no_failure_records() -> None:
    recorder = ModelCallRecorder()
    model = build_failing_model(RuntimeError("nope"), recorder=recorder)
    try:
        _request(model)
    except RuntimeError:
        pass
    assert recorder.failures == ["RuntimeError: nope"]
    assert len(recorder.failure_records) == 1
    assert recorder.failure_records[0].request_index == 0

    ok_recorder = ModelCallRecorder()
    ok_model = RecordingPydanticModel(
        FunctionModel(lambda _m, _i: ModelResponse(parts=[TextPart(content="ok")])),
        recorder=ok_recorder,
    )
    _request(ok_model)
    assert ok_recorder.failure_records == []


# ── Cause-chain bounding ───────────────────────────────────────────────────


def test_bounded_cause_chain_is_limited_and_deterministic() -> None:
    root = RuntimeError("root")
    current: BaseException = root
    for index in range(MAX_CAUSE_CHAIN_LENGTH + 2):
        wrapper = RuntimeError(f"level-{index}")
        wrapper.__cause__ = current
        current = wrapper
    chain = bounded_cause_chain(current)
    assert len(chain) == MAX_CAUSE_CHAIN_LENGTH
    assert chain == bounded_cause_chain(current)


# ── Sanitization / privacy ─────────────────────────────────────────────────


def test_sanitize_type_token_redacts_unsafe_text() -> None:
    assert sanitize_type_token("UnexpectedModelBehavior") == "UnexpectedModelBehavior"
    assert sanitize_type_token("Good_Name1") == "Good_Name1"
    assert sanitize_type_token("C:\\Users\\alice") == "<redacted>"
    assert sanitize_type_token("http://localhost:11434") == "<redacted>"
    assert sanitize_type_token("has space") == "<redacted>"
    assert sanitize_type_token("x" * 65) == "<redacted>"


def test_diagnostic_never_persists_raw_message_or_path() -> None:
    secret = "C:\\Users\\alice\\.config\\models.toml http://localhost:11434 SECRET_TOKEN"
    error = ModelError(
        "Pydantic AI model request failed",
        cause=UnexpectedModelBehavior("framework detail", body=secret),
    )
    recorder = _recorder_with(request_count=2)
    diagnostic = build_failure_diagnostic(error, recorder)
    blob = json.dumps(
        {
            "exception_type": diagnostic.exception_type,
            "cause_chain": list(diagnostic.cause_chain),
            "source_category": (
                None if diagnostic.source_category is None else diagnostic.source_category.value
            ),
        }
    )
    for forbidden in ("alice", "models.toml", "localhost", "SECRET_TOKEN", "framework detail"):
        assert forbidden not in blob
    assert diagnostic.exception_type == "UnexpectedModelBehavior"


def test_redaction_token_is_canonical() -> None:
    assert is_canonical_type_token("<redacted>")
    assert sanitize_type_token("bad/path") == "<redacted>"


def test_composition_output_is_canonical() -> None:
    recorder = _recorder_with(
        request_count=1,
        failures=[
            ModelCallFailure(
                request_index=0,
                exception_type="C:\\Users\\alice",
                cause_chain=("bad path", "GoodName"),
            )
        ],
    )
    diagnostic = build_failure_diagnostic(RuntimeError("boom"), recorder)
    assert diagnostic.exception_type is not None
    assert is_canonical_type_token(diagnostic.exception_type)
    assert all(is_canonical_type_token(entry) for entry in diagnostic.cause_chain)
    assert len(diagnostic.cause_chain) <= MAX_CAUSE_CHAIN_LENGTH


def test_unsafe_dynamic_exception_name_is_redacted() -> None:
    unsafe_class = type("C:\\Users\\alice", (Exception,), {})
    recorder = ModelCallRecorder(request_count=1)
    recorder.failure_records.append(
        ModelCallFailure(request_index=0, exception_type="C:\\Users\\alice", cause_chain=())
    )
    diagnostic = build_failure_diagnostic(unsafe_class("x"), recorder)
    assert diagnostic.exception_type == "<redacted>"


# ── Category classification ────────────────────────────────────────────────


def test_model_request_failure_category_and_index() -> None:
    recorder = _recorder_with(
        request_count=2,
        failures=[
            ModelCallFailure(
                request_index=1,
                exception_type="ModelHTTPError",
                cause_chain=("ReadTimeout",),
            )
        ],
    )
    diagnostic = build_failure_diagnostic(RuntimeError("wrapped"), recorder)
    assert diagnostic.status is FailureDiagnosticStatus.OBSERVED
    assert diagnostic.source_category is FailureSourceCategory.MODEL_REQUEST
    assert diagnostic.exception_type == "ModelHTTPError"
    assert diagnostic.cause_chain == ("ReadTimeout",)
    assert diagnostic.request_index == 1


def test_framework_failure_survives_only_through_project_cause_chain() -> None:
    recorder = _recorder_with(request_count=2)
    error = ModelError(
        "Pydantic AI model request failed",
        cause=UnexpectedModelBehavior("Exceeded maximum output retries (0)"),
    )
    diagnostic = build_failure_diagnostic(error, recorder)
    assert diagnostic.status is FailureDiagnosticStatus.OBSERVED
    assert diagnostic.source_category is FailureSourceCategory.FRAMEWORK_PROCESSING
    assert diagnostic.exception_type == "UnexpectedModelBehavior"
    assert diagnostic.request_index == 1


def test_project_policy_failure_category() -> None:
    recorder = _recorder_with(request_count=2)
    diagnostic = build_failure_diagnostic(ModelError("second batch rejected"), recorder)
    assert diagnostic.source_category is FailureSourceCategory.PROJECT_POLICY
    assert diagnostic.exception_type == "ModelError"


def test_project_validation_failure_category() -> None:
    recorder = _recorder_with(request_count=1)
    diagnostic = build_failure_diagnostic(ValidationError("bad binding"), recorder)
    assert diagnostic.source_category is FailureSourceCategory.PROJECT_POLICY
    assert diagnostic.exception_type == "ValidationError"


def test_unexpected_runtime_failure_category() -> None:
    recorder = _recorder_with(request_count=1)
    diagnostic = build_failure_diagnostic(ValueError("boom"), recorder)
    assert diagnostic.source_category is FailureSourceCategory.RUNTIME_OTHER
    assert diagnostic.exception_type == "ValueError"


def test_success_yields_explicit_not_available() -> None:
    diagnostic = build_failure_diagnostic(None, _recorder_with(request_count=1))
    assert diagnostic.status is FailureDiagnosticStatus.NOT_AVAILABLE
    assert diagnostic.source_category is None
    assert diagnostic.exception_type is None
    assert diagnostic.cause_chain == ()
    assert diagnostic.request_index is None


# ── Runner integration ─────────────────────────────────────────────────────


def _single_case_dataset() -> EvalDataset:
    scenario = EvalScenario(
        scenario_id="EVAL-DIAG-001",
        user_input="Что-то?",
        expectation=EvalExpectation(ScenarioExpectationKind.RESPOND_NO_TOOL),
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


def test_runner_records_observed_diagnostic_on_model_request_failure() -> None:
    def _factory(_expectation: EvalExpectation) -> tuple[object, ModelCallRecorder]:
        recorder = ModelCallRecorder()
        return build_failing_model(RuntimeError("boom"), recorder=recorder), recorder

    report = run_dataset(
        _single_case_dataset(),
        model_factory=_factory,
        runtime_mode="custom",
        runtime_label="custom-candidate",
        require_oracle_consistency=False,
    )
    diagnostic = report.full_turn_observations[0].failure_diagnostic
    assert diagnostic.status is FailureDiagnosticStatus.OBSERVED
    assert diagnostic.source_category is FailureSourceCategory.MODEL_REQUEST
    assert diagnostic.exception_type == "RuntimeError"
    assert diagnostic.request_index == 0
    # Diagnostics do not alter acceptance semantics.
    assert report.run_validity.runtime_error_count == 1
    assert not report.accepted
