"""Offline scripted eval runner: fresh sample loop + observation collection.

Runs every ``(scenario, repetition)`` from a fresh synthetic fixture through the
real production Pydantic AI runtime, collects a ``DecisionObservation`` and a
``FullTurnObservation`` from the *same* execution, and builds the provider-
neutral report.

Runtime selection is a small registry: S14-06 registers only the offline
``scripted`` mode.  S14-07 extends it with a live Ollama mode without touching
scoring, observation or report logic.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

from dnd_assistant.application.agent_contracts import AgentRunResult
from dnd_assistant.composition.eval_failure_diagnostics import build_failure_diagnostic
from dnd_assistant.composition.eval_fixture import (
    EvalFixture,
    HandlerInvocation,
    build_fixture,
)
from dnd_assistant.composition.eval_model import (
    ModelCallRecorder,
    ModelRequestTraceEvent,
    build_scripted_model,
)
from dnd_assistant.composition.eval_trace import (
    EVENT_MEASUREMENT_COMPLETED,
    EVENT_MEASUREMENT_STARTED,
    EVENT_REQUEST_COMPLETED,
    EVENT_REQUEST_FAILED,
    EVENT_REQUEST_STARTED,
    EVENT_SAMPLE_COMPLETED,
    EVENT_SAMPLE_STARTED,
    PHASE_MEASUREMENT,
    EvalTraceWriter,
)
from dnd_assistant.errors import NotFoundError
from dnd_assistant.evals.contracts import (
    DecisionObservation,
    EvalExpectation,
    ExposedToolInfo,
    FullTurnObservation,
    ToolCallObservation,
)
from dnd_assistant.evals.dataset import EvalCase, EvalDataset
from dnd_assistant.evals.report import EvalReport, build_eval_report
from dnd_assistant.prompts.agent_v3 import PROMPT_VERSION
from dnd_assistant.tools.types import Permission

SCRIPTED_RUNTIME = "scripted"
SCRIPTED_RUNTIME_LABEL = "scripted-oracle"

ModelFactory = Callable[[EvalExpectation], "tuple[object, ModelCallRecorder]"]
"""Build a fresh (model, recorder) pair for one sample's expectation."""


def _default_model_factory(expectation: EvalExpectation) -> tuple[object, ModelCallRecorder]:
    recorder = ModelCallRecorder()
    return build_scripted_model(expectation, recorder=recorder), recorder


@dataclass(frozen=True, slots=True)
class _ExposedSnapshot:
    names: tuple[str, ...]
    has_write: bool


def run_eval(
    dataset: EvalDataset,
    *,
    runtime: str = SCRIPTED_RUNTIME,
    model_factory: ModelFactory | None = None,
    trace: EvalTraceWriter | None = None,
) -> EvalReport:
    """Run the full dataset offline and return the report.

    Args:
        dataset: The versioned dataset/sample plan.
        runtime: Runtime identifier; only ``scripted`` is registered in S14-06.
        model_factory: Optional per-sample model factory (tests/negative
            candidates).  Defaults to the deterministic scripted oracle.
        trace: Optional opt-in local diagnostic trace.  Disabled by default.

    Raises:
        ValueError: For an unregistered runtime identifier.
    """
    if runtime != SCRIPTED_RUNTIME:
        raise ValueError(
            f"unknown eval runtime {runtime!r}; only {SCRIPTED_RUNTIME!r} is available"
        )
    return run_dataset(
        dataset,
        model_factory=model_factory or _default_model_factory,
        runtime_mode=SCRIPTED_RUNTIME,
        runtime_label=SCRIPTED_RUNTIME_LABEL,
        runtime_metadata={},
        require_oracle_consistency=True,
        trace=trace,
    )


def run_dataset(
    dataset: EvalDataset,
    *,
    model_factory: ModelFactory,
    runtime_mode: str,
    runtime_label: str,
    runtime_metadata: Mapping[str, str] | None = None,
    require_oracle_consistency: bool = False,
    trace: EvalTraceWriter | None = None,
) -> EvalReport:
    """Run every sample with the given model factory and build the report.

    Runtime identity is an explicit parameter so this collector/report path is
    reused unchanged by S14-07 for live candidates.  ``scripted`` oracle
    consistency is required only when the caller sets
    ``require_oracle_consistency=True``; generic/live candidates carry no
    implicit 100%-accuracy requirement.

    ``trace``, when supplied, receives an opt-in append-only local diagnostic
    trace.  It observes the existing execution only and never alters scoring,
    acceptance or model/runtime behavior.
    """
    decision_observations: list[DecisionObservation] = []
    full_turn_observations: list[FullTurnObservation] = []

    if trace is not None:
        trace.emit(
            EVENT_MEASUREMENT_STARTED,
            phase=PHASE_MEASUREMENT,
            dataset_id=dataset.dataset_id,
            dataset_version=dataset.dataset_version,
            expected_sample_count=len(dataset.cases) * dataset.sample_plan.repetitions,
            prompt_version=PROMPT_VERSION,
            runtime_mode=runtime_mode,
            runtime_label=runtime_label,
        )

    for case in dataset.cases:
        for repetition in range(dataset.sample_plan.repetitions):
            decision, full_turn = _run_sample(
                case,
                repetition,
                dataset=dataset,
                model_factory=model_factory,
                trace=trace,
            )
            decision_observations.append(decision)
            full_turn_observations.append(full_turn)

    if trace is not None:
        trace.emit(EVENT_MEASUREMENT_COMPLETED, phase=PHASE_MEASUREMENT)

    return build_eval_report(
        dataset,
        runtime_mode=runtime_mode,
        runtime_label=runtime_label,
        prompt_version=PROMPT_VERSION,
        decision_observations=decision_observations,
        full_turn_observations=full_turn_observations,
        runtime_metadata=runtime_metadata,
        oracle_consistency_required=require_oracle_consistency,
    )


def _run_sample(
    case: EvalCase,
    repetition: int,
    *,
    dataset: EvalDataset,
    model_factory: ModelFactory,
    trace: EvalTraceWriter | None = None,
) -> tuple[DecisionObservation, FullTurnObservation]:
    scenario = case.scenario
    model, recorder = model_factory(scenario.expectation)
    if trace is not None:
        trace.emit(
            EVENT_SAMPLE_STARTED,
            phase=PHASE_MEASUREMENT,
            scenario_id=scenario.scenario_id,
            repetition=repetition,
        )
        recorder.request_observer = make_request_observer(
            trace,
            scenario.scenario_id,
            repetition,
            phase=PHASE_MEASUREMENT,
        )
    fixture = build_fixture(
        case.execution,
        model=model,
        scenario_id=scenario.scenario_id,
        repetition=repetition,
    )
    exposed = _exposed_snapshot(fixture)

    started = time.perf_counter()
    result: AgentRunResult | None = None
    error: BaseException | None = None
    try:
        result = fixture.runtime.run(
            scenario.user_input,
            execution_context=fixture.execution_context,
        )
    except Exception as exc:  # noqa: BLE001 - observable sample failure
        error = exc
    duration = time.perf_counter() - started

    decision, full_turn = _collect(
        scenario.scenario_id,
        repetition,
        fixture=fixture,
        recorder=recorder,
        exposed=exposed,
        result=result,
        error=error,
        total_duration=duration,
    )

    if trace is not None:
        diagnostic = full_turn.failure_diagnostic
        trace.emit(
            EVENT_SAMPLE_COMPLETED,
            phase=PHASE_MEASUREMENT,
            scenario_id=scenario.scenario_id,
            repetition=repetition,
            success=full_turn.success,
            terminal_kind=full_turn.terminal_kind,
            model_request_count=full_turn.model_request_count,
            tool_call_count=full_turn.tool_call_count,
            handler_call_count=full_turn.handler_call_count,
            write_handler_count=full_turn.write_handler_count,
            failure_status=diagnostic.status.value,
            source_category=(
                None if diagnostic.source_category is None else diagnostic.source_category.value
            ),
            exception_type=diagnostic.exception_type,
            cause_chain=list(diagnostic.cause_chain),
        )

    return decision, full_turn


def _collect(
    scenario_id: str,
    repetition: int,
    *,
    fixture: EvalFixture,
    recorder: ModelCallRecorder,
    exposed: _ExposedSnapshot,
    result: AgentRunResult | None,
    error: BaseException | None,
    total_duration: float,
) -> tuple[DecisionObservation, FullTurnObservation]:
    exposed_tools = _exposed_info(exposed)
    error_type = type(error).__name__ if error is not None else None
    error_message = str(error) if error is not None else None

    initial_calls = _initial_calls(recorder, fixture, exposed)
    tool_path = len(initial_calls) > 0

    terminal_kind: str | None = None
    if result is not None:
        terminal_kind = result.outcome.kind.value

    decision_terminal = terminal_kind if (result is not None and not tool_path) else None
    terminal_content = None
    if not tool_path:
        first = recorder.first_response
        if first is not None:
            terminal_content = _first_text(first)

    decision = DecisionObservation(
        scenario_id=scenario_id,
        repetition=repetition,
        duration_seconds=_first_duration(recorder, total_duration),
        tool_calls=initial_calls,
        terminal_kind=decision_terminal,
        terminal_content=terminal_content,
        exposed_tools=exposed_tools,
        error_type=error_type,
        error_message=error_message,
    )

    executed_calls = _executed_calls(result, fixture, exposed)
    handler_count = len(fixture.handler_invocations)
    write_handler_count = sum(1 for item in fixture.handler_invocations if item.is_write)
    tool_execution_count = len(executed_calls) if result is not None else handler_count

    failure_diagnostic = build_failure_diagnostic(error, recorder)

    full_turn = FullTurnObservation(
        scenario_id=scenario_id,
        repetition=repetition,
        duration_seconds=total_duration,
        success=error is None,
        terminal_kind=terminal_kind,
        initial_tool_calls=initial_calls,
        executed_tool_calls=executed_calls,
        tool_call_count=len(initial_calls),
        tool_execution_count=tool_execution_count,
        model_request_count=recorder.request_count,
        handler_call_count=handler_count,
        write_handler_count=write_handler_count,
        exposed_tools=exposed_tools,
        error_type=error_type,
        error_message=error_message,
        failure_diagnostic=failure_diagnostic,
    )
    return decision, full_turn


def make_request_observer(
    trace: EvalTraceWriter,
    scenario_id: str,
    repetition: int,
    *,
    phase: str,
) -> Callable[[ModelRequestTraceEvent], None]:
    """Build a bounded trace observer bound to one (scenario, repetition).

    The observer forwards only allowlisted, sanitized fields.  It never raises:
    :meth:`ModelCallRecorder.observe` isolates observer failures.
    """

    def _observe(event: ModelRequestTraceEvent) -> None:
        fields: dict[str, Any] = {
            "phase": phase,
            "scenario_id": scenario_id,
            "repetition": repetition,
            "request_index": event.request_index,
        }
        if event.outcome == EVENT_REQUEST_STARTED:
            trace.emit(EVENT_REQUEST_STARTED, **fields)
            return
        if event.duration_seconds is not None:
            fields["elapsed_seconds"] = event.duration_seconds
        if event.outcome == EVENT_REQUEST_COMPLETED:
            fields["response_part_types"] = list(event.response_part_types)
            fields["tool_names"] = list(event.tool_names)
            trace.emit(EVENT_REQUEST_COMPLETED, **fields)
            return
        fields["exception_type"] = event.exception_type
        fields["cause_chain"] = list(event.cause_chain)
        if event.provider_http_status is not None:
            fields["provider_http_status"] = event.provider_http_status
        trace.emit(EVENT_REQUEST_FAILED, **fields)

    return _observe


# ── Extraction helpers ─────────────────────────────────────────────────────


def _exposed_snapshot(fixture: EvalFixture) -> _ExposedSnapshot:
    tools = fixture.exposed_tools()
    names = tuple(tool.name for tool in tools)
    has_write = any(tool.permission is Permission.WRITE for tool in tools)
    return _ExposedSnapshot(names=names, has_write=has_write)


def _exposed_info(snapshot: _ExposedSnapshot) -> ExposedToolInfo:
    return ExposedToolInfo(tool_names=snapshot.names, has_write=snapshot.has_write)


def _first_duration(recorder: ModelCallRecorder, fallback: float) -> float:
    if recorder.request_durations:
        return recorder.request_durations[0]
    return fallback


def _first_text(response: ModelResponse) -> str | None:
    parts = [part.content for part in response.parts if isinstance(part, TextPart)]
    return " ".join(parts) if parts else None


def _initial_calls(
    recorder: ModelCallRecorder,
    fixture: EvalFixture,
    exposed: _ExposedSnapshot,
) -> tuple[ToolCallObservation, ...]:
    first = recorder.first_response
    if first is None:
        return ()
    observations: list[ToolCallObservation] = []
    for part in first.parts:
        if not isinstance(part, ToolCallPart):
            continue
        arguments, parsed = _safe_args(part)
        schema_valid, is_write = _classify(
            part.tool_name, arguments if parsed else None, fixture, exposed
        )
        observations.append(
            ToolCallObservation(
                tool_name=part.tool_name,
                arguments=arguments,
                call_id=part.tool_call_id,
                schema_valid=schema_valid,
                is_write=is_write,
            )
        )
    return tuple(observations)


def _executed_calls(
    result: AgentRunResult | None,
    fixture: EvalFixture,
    exposed: _ExposedSnapshot,
) -> tuple[ToolCallObservation, ...]:
    if result is None:
        return tuple(
            _invocation_to_call(item, fixture, exposed) for item in fixture.handler_invocations
        )

    observations: list[ToolCallObservation] = []
    for execution in result.tool_executions:
        tool_call = execution.tool_call
        schema_valid, is_write = _classify(tool_call.name, tool_call.arguments, fixture, exposed)
        observations.append(
            ToolCallObservation(
                tool_name=tool_call.name,
                arguments=dict(tool_call.arguments),
                call_id=tool_call.call_id,
                schema_valid=schema_valid,
                is_write=is_write,
            )
        )
    return tuple(observations)


def _invocation_to_call(
    invocation: HandlerInvocation,
    fixture: EvalFixture,
    exposed: _ExposedSnapshot,
) -> ToolCallObservation:
    schema_valid, is_write = _classify(invocation.tool_name, invocation.arguments, fixture, exposed)
    return ToolCallObservation(
        tool_name=invocation.tool_name,
        arguments=invocation.arguments,
        call_id=None,
        schema_valid=schema_valid,
        is_write=is_write,
    )


def _safe_args(part: ToolCallPart) -> tuple[dict[str, object], bool]:
    try:
        arguments = part.args_as_dict(raise_if_invalid=True)
    except Exception:  # noqa: BLE001 - malformed args are fail-closed evidence
        return {}, False
    return dict(arguments), True


def _classify(
    tool_name: str,
    arguments: Mapping[str, object] | None,
    fixture: EvalFixture,
    exposed: _ExposedSnapshot,
) -> tuple[bool, bool]:
    """Return ``(schema_valid, is_write)`` from trusted registry metadata."""
    try:
        binding = fixture.registry.get(tool_name)
    except NotFoundError:
        return False, False
    is_write = binding.definition.permission is Permission.WRITE
    if tool_name not in exposed.names:
        return False, is_write
    if arguments is None:
        return False, is_write
    try:
        binding.definition.input_schema.model_validate(dict(arguments))
    except Exception:  # noqa: BLE001 - schema-invalid is fail-closed evidence
        return False, is_write
    return True, is_write
