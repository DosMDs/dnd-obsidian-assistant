"""Live DeepSeek eval composition: candidate validation, warm-up, model factory.

This module is the sole owner of the explicit live DeepSeek product-v1 candidate
path (RM-05).  It reuses the accepted provider-neutral eval surface unchanged:

    product-v1 dataset
    build_fixture() over the real production runtime
    run_dataset() generic collector
    RecordingPydanticModel / ModelCallRecorder
    build_eval_report() (metrics, safety, latency)

Only the model operator differs: instead of the deterministic offline scripted
oracle it wraps the exact production Pydantic AI DeepSeek model selected by the
shared production dispatch ``_build_agent_model(profile)``.  It performs no
campaign Vault access, no auto-discovery and no extra request.

The measured candidate is the canonical DeepSeek AGENT identity only
(``deepseek`` / ``deepseek-flash`` / thinking enabled / reasoning effort high /
canonical base URL).  Identity validation fails closed before model construction,
credential resolution or any network access.

Live execution is closed (invoked only after explicit CLI opt-in); nothing here
runs at import time.
"""

from __future__ import annotations

import importlib.metadata
import platform
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings

from dnd_assistant.composition.agent_model import (
    _build_agent_model,
    _close_model,
    _load_profile,
)
from dnd_assistant.composition.eval_fixture import build_fixture
from dnd_assistant.composition.eval_model import (
    ModelCallRecorder,
    RecordingPydanticModel,
)
from dnd_assistant.composition.eval_runner import (
    ModelFactory,
    make_request_observer,
    run_dataset,
)
from dnd_assistant.composition.eval_trace import (
    EVENT_WARMUP_COMPLETED,
    EVENT_WARMUP_FAILED,
    EVENT_WARMUP_STARTED,
    PHASE_WARMUP,
    EvalTraceWriter,
)
from dnd_assistant.errors import DndAssistantError
from dnd_assistant.evals.contracts import EvalExpectation, sanitize_type_token
from dnd_assistant.evals.dataset import EvalDataset
from dnd_assistant.evals.report import EvalReport
from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole, ReasoningEffort

LIVE_RUNTIME = "deepseek"
LIVE_RUNTIME_LABEL = "deepseek-live"

WARMUP_SCENARIO_ID = "EVAL-P1-001"
WARMUP_POLICY = "one-discarded-eval-p1-001"

_CANONICAL_MODEL = "deepseek-flash"
_CANONICAL_BASE_URL = "https://api.deepseek.com"
_DOCUMENTED_ROUTE = "DeepSeek-V4.1-Flash"
_PYDANTIC_AI_DISTRIBUTION = "pydantic-ai-slim"

RESPONSE_MODEL_NOT_REPORTED = "not-reported"
RESPONSE_MODEL_MULTIPLE = "multiple"


class EvalDeepSeekError(DndAssistantError):
    """Raised when the explicit live DeepSeek candidate cannot be prepared."""


def _validate_deepseek_candidate(profile: ModelProfile) -> None:
    """Fail closed on any profile that is not the canonical RM-05 identity.

    Runs before model construction, credential resolution and network access.
    The exact reasoning-effort pin (``high``) is owned here because the
    production DeepSeek factory accepts the whole ``low|high|max`` vocabulary.
    """
    problems: list[str] = []
    if profile.provider != "deepseek":
        problems.append(f"provider={profile.provider!r}")
    if profile.role is not ModelProfileRole.AGENT:
        problems.append(f"role={profile.role.value!r}")
    if profile.model != _CANONICAL_MODEL:
        problems.append(f"model={profile.model!r}")
    if profile.thinking is not True:
        problems.append(f"thinking={profile.thinking!r}")
    if profile.reasoning_effort is not ReasoningEffort.HIGH:
        problems.append(f"reasoning_effort={profile.reasoning_effort!r}")
    if profile.base_url.rstrip("/") != _CANONICAL_BASE_URL:
        problems.append(f"base_url={profile.base_url!r}")

    if problems:
        raise EvalDeepSeekError(
            "DeepSeek eval candidate is not the canonical RM-05 identity: " + ", ".join(problems)
        )


@dataclass(slots=True)
class _ResponseModelCapture:
    """Deterministic capture of public provider response model identifiers.

    ``ModelResponse.model_name`` is mapped by Pydantic AI from the provider
    response.  It is the *provider-reported* model id (which may be an API alias),
    never a claim about an exact underlying release.  Identifiers are recorded
    as-is; if they differ across the run the fact is reported as ``multiple``
    rather than normalized.
    """

    metadata: dict[str, str]
    models: set[str] = field(default_factory=set)

    def record(self, model_name: object) -> None:
        if isinstance(model_name, str) and model_name.strip():
            self.models.add(model_name.strip())
        if not self.models:
            self.metadata["response_model"] = RESPONSE_MODEL_NOT_REPORTED
        elif len(self.models) == 1:
            self.metadata["response_model"] = next(iter(self.models))
        else:
            self.metadata["response_model"] = RESPONSE_MODEL_MULTIPLE


class _ResponseModelRecordingModel(RecordingPydanticModel):
    """Recording model that also captures the public provider response model id.

    Uses only the public ``ModelResponse.model_name`` attribute and adds zero
    requests.  Recording semantics (counts, durations, failures) are unchanged.
    """

    def __init__(
        self,
        delegate: Model,
        *,
        recorder: ModelCallRecorder,
        capture: _ResponseModelCapture,
    ) -> None:
        super().__init__(delegate, recorder=recorder)
        self._capture = capture

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        response = await super().request(messages, model_settings, model_request_parameters)
        self._capture.record(getattr(response, "model_name", None))
        return response


def _installed_pydantic_ai_version() -> str:
    """Return the installed Pydantic AI distribution version, if resolvable."""
    try:
        return importlib.metadata.version(_PYDANTIC_AI_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def build_runtime_metadata(
    dataset: EvalDataset,
    profile: ModelProfile,
    *,
    profile_name: str,
    qualification_date: str,
) -> dict[str, str]:
    """Build the non-sensitive runtime identity recorded in the frozen report.

    Deliberately contains no config path, home/user identity, hostname,
    credentials, raw endpoint URL, environment dump, prompt or reasoning.

    ``response_model`` starts at ``not-reported`` and is updated by the capture
    seam as the provider reports model ids during the run.
    """
    return {
        "provider": profile.provider,
        "profile_name": profile_name,
        "model": profile.model,
        "role": profile.role.value,
        "thinking": "true" if profile.thinking else "false",
        "reasoning_effort": (
            "none" if profile.reasoning_effort is None else profile.reasoning_effort.value
        ),
        "temperature": "none" if profile.temperature is None else repr(profile.temperature),
        "pydantic_ai_version": _installed_pydantic_ai_version(),
        "python_version": platform.python_version(),
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "warmup_policy": WARMUP_POLICY,
        "measured_sample_plan": dataset.sample_plan.plan_id,
        "documented_route": _DOCUMENTED_ROUTE,
        "qualification_date": qualification_date,
        "response_model": RESPONSE_MODEL_NOT_REPORTED,
    }


def _build_live_model_factory(
    delegate: Model,
    capture: _ResponseModelCapture,
) -> ModelFactory:
    """Build a per-sample factory around one shared production delegate.

    A fresh ``RecordingPydanticModel`` + ``ModelCallRecorder`` is created per
    sample so each measured sample keeps its own literal request evidence,
    while the underlying production model identity and settings do not drift.
    """

    def factory(_expectation: EvalExpectation) -> tuple[object, ModelCallRecorder]:
        recorder = ModelCallRecorder()
        return (
            _ResponseModelRecordingModel(delegate, recorder=recorder, capture=capture),
            recorder,
        )

    return factory


def _warm_up(
    dataset: EvalDataset,
    model_factory: ModelFactory,
    *,
    trace: EvalTraceWriter | None = None,
) -> None:
    """Run one discarded warm-up turn (never part of measured observations).

    When ``trace`` is supplied, warm-up lifecycle events are emitted with
    ``phase=warmup`` so they can never be confused with measured samples.

    Raises:
        EvalDeepSeekError: The dataset has no warm-up scenario, or the warm-up
            turn failed.
    """
    case = next(
        (case for case in dataset.cases if case.scenario.scenario_id == WARMUP_SCENARIO_ID),
        None,
    )
    if case is None:
        raise EvalDeepSeekError(f"warm-up scenario {WARMUP_SCENARIO_ID!r} not present in dataset")

    if trace is not None:
        trace.emit(
            EVENT_WARMUP_STARTED,
            phase=PHASE_WARMUP,
            scenario_id=WARMUP_SCENARIO_ID,
            repetition=0,
        )

    model, recorder = model_factory(case.scenario.expectation)
    if trace is not None:
        recorder.request_observer = make_request_observer(
            trace,
            WARMUP_SCENARIO_ID,
            0,
            phase=PHASE_WARMUP,
        )
    fixture = build_fixture(
        case.execution,
        model=model,
        scenario_id=WARMUP_SCENARIO_ID,
        repetition=0,
    )
    try:
        fixture.runtime.run(
            case.scenario.user_input,
            execution_context=fixture.execution_context,
        )
    except Exception as exc:  # noqa: BLE001 - warm-up must succeed fail-closed
        if trace is not None:
            trace.emit(
                EVENT_WARMUP_FAILED,
                phase=PHASE_WARMUP,
                scenario_id=WARMUP_SCENARIO_ID,
                repetition=0,
                exception_type=sanitize_type_token(type(exc).__name__),
            )
        raise EvalDeepSeekError(f"live warm-up failed: {type(exc).__name__}: {exc}") from exc

    if trace is not None:
        trace.emit(
            EVENT_WARMUP_COMPLETED,
            phase=PHASE_WARMUP,
            scenario_id=WARMUP_SCENARIO_ID,
            repetition=0,
        )


def run_live_eval(
    dataset: EvalDataset,
    *,
    config_path: Path,
    profile_name: str,
    trace: EvalTraceWriter | None = None,
    qualification_date: str | None = None,
) -> EvalReport:
    """Run one explicit live DeepSeek measured pass over ``dataset``.

    Ordering: load the AGENT profile, validate the exact RM-05 candidate
    identity (before credential/network), construct the exact production
    Pydantic AI DeepSeek model through ``_build_agent_model``, run one discarded
    warm-up, then execute the measured dataset exactly once with the shared
    delegate.

    ``trace``, when supplied, is an opt-in local diagnostic side channel.  It
    observes the one existing execution only and never issues an extra model
    request, warm-up, retry or sample.

    Raises:
        DndAssistantError: Candidate-identity, config/profile loading, model
            construction, credential or warm-up failure.
    """
    profile = _load_profile(config_path, profile_name)
    _validate_deepseek_candidate(profile)

    # Construct the exact production candidate BEFORE any HTTP request so that
    # wrong provider/model/thinking/effort/base URL fail before network.
    delegate = _build_agent_model(profile)
    try:
        metadata = build_runtime_metadata(
            dataset,
            profile,
            profile_name=profile_name,
            qualification_date=qualification_date or date.today().isoformat(),
        )
        capture = _ResponseModelCapture(metadata=metadata)
        model_factory = _build_live_model_factory(delegate, capture)
        _warm_up(dataset, model_factory, trace=trace)
        return run_dataset(
            dataset,
            model_factory=model_factory,
            runtime_mode=LIVE_RUNTIME,
            runtime_label=LIVE_RUNTIME_LABEL,
            runtime_metadata=metadata,
            require_oracle_consistency=False,
            trace=trace,
        )
    finally:
        _close_model(delegate)


__all__ = [
    "LIVE_RUNTIME",
    "LIVE_RUNTIME_LABEL",
    "RESPONSE_MODEL_MULTIPLE",
    "RESPONSE_MODEL_NOT_REPORTED",
    "WARMUP_POLICY",
    "WARMUP_SCENARIO_ID",
    "EvalDeepSeekError",
    "build_runtime_metadata",
    "run_live_eval",
]
