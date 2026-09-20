"""Live Ollama eval composition: preflight, warm-up, model factory, metadata.

This module is the sole owner of the explicit live Ollama candidate path.  It
reuses the accepted S14-06 surface unchanged:

    product-v1 dataset
    build_fixture() over the real production runtime
    run_dataset() generic collector
    RecordingPydanticModel / ModelCallRecorder
    build_eval_report() (metrics, safety, latency)

Only the model operator differs: instead of the deterministic offline scripted
oracle it wraps the exact production Pydantic AI Ollama model built by
``build_pydantic_ai_ollama_model(profile)``.  It performs no campaign Vault
access, no auto-discovery and no auto-pull.

Live execution is closed (invoked only after explicit CLI opt-in); nothing here
runs at import time.
"""

from __future__ import annotations

import importlib.metadata
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from pydantic_ai.models import Model

from dnd_assistant.composition.agent_model import _close_model, _load_profile
from dnd_assistant.composition.eval_fixture import build_fixture
from dnd_assistant.composition.eval_model import ModelCallRecorder, RecordingPydanticModel
from dnd_assistant.composition.eval_runner import ModelFactory, run_dataset
from dnd_assistant.errors import DndAssistantError
from dnd_assistant.evals.contracts import EvalExpectation
from dnd_assistant.evals.dataset import EvalDataset
from dnd_assistant.evals.report import EvalReport
from dnd_assistant.models.ollama import OllamaModelProvider
from dnd_assistant.models.profiles import ModelProfile
from dnd_assistant.models.pydantic_ai_ollama import build_pydantic_ai_ollama_model
from dnd_assistant.models.transport import build_ollama_http_timeout

LIVE_RUNTIME = "ollama"
LIVE_RUNTIME_LABEL = "ollama-live"

WARMUP_SCENARIO_ID = "EVAL-P1-001"
WARMUP_POLICY = "one-discarded-eval-p1-001"

_PYDANTIC_AI_DISTRIBUTION = "pydantic-ai-slim"


class EvalLiveError(DndAssistantError):
    """Raised when the explicit live Ollama candidate cannot be prepared."""


@dataclass(frozen=True, slots=True)
class LiveOllamaEnvironment:
    """Preflight result for the explicit live Ollama candidate.

    Contains no credential, path or endpoint detail; only non-sensitive
    candidate identity and observed software/runtime versions.
    """

    profile_name: str
    model: str
    role: str
    temperature: str
    keep_alive: str
    server_version: str
    pydantic_ai_version: str


def preflight_ollama(profile: ModelProfile) -> str:
    """Probe the live Ollama endpoint and return its server version.

    Uses the public production ``OllamaModelProvider.health()`` for
    reachability and configured-model availability, then captures the exact
    server version from an explicit ``GET /api/version`` request.  Must be
    called only after the production model has been constructed from
    ``profile``.

    Raises:
        EvalLiveError: The endpoint is unreachable, the configured model is not
            available, or the version response is unusable.
    """
    provider = OllamaModelProvider(profile)
    try:
        health = provider.health()
    finally:
        provider.close()

    if not health.reachable:
        raise EvalLiveError(f"Ollama endpoint not reachable: {health.detail}")
    if not health.model_available:
        raise EvalLiveError(f"Configured model {profile.model!r} not available: {health.detail}")

    return _fetch_ollama_server_version(profile.base_url)


def _fetch_ollama_server_version(base_url: str) -> str:
    """Fetch the server version from ``GET {base_url}/api/version``.

    Raises:
        EvalLiveError: Transport error, HTTP error, non-JSON body, non-object
            body, or missing/empty version field.
    """
    url = f"{base_url.rstrip('/')}/api/version"
    try:
        with httpx.Client(timeout=build_ollama_http_timeout()) as client:
            response = client.get(url)
    except httpx.RequestError as exc:
        raise EvalLiveError(f"Failed to reach Ollama /api/version: {exc}") from exc

    if not response.is_success:
        raise EvalLiveError(f"Ollama /api/version returned HTTP {response.status_code}")

    try:
        data: Any = response.json()
    except ValueError as exc:
        raise EvalLiveError("Ollama /api/version returned a non-JSON body") from exc

    if not isinstance(data, dict):
        raise EvalLiveError(f"Ollama /api/version returned {type(data).__name__}, expected object")

    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        raise EvalLiveError("Ollama /api/version response is missing a usable 'version' field")

    return version.strip()


def build_runtime_metadata(
    dataset: EvalDataset,
    profile: ModelProfile,
    *,
    profile_name: str,
    server_version: str,
) -> dict[str, str]:
    """Build the non-sensitive runtime identity recorded in the frozen report.

    Deliberately contains no config path, home/user identity, hostname,
    credentials, raw endpoint URL or environment dump.
    """
    return {
        "provider": profile.provider,
        "profile_name": profile_name,
        "model": profile.model,
        "role": profile.role.value,
        "temperature": "none" if profile.temperature is None else repr(profile.temperature),
        "keep_alive": "none" if profile.keep_alive is None else "set",
        "pydantic_ai_version": _installed_pydantic_ai_version(),
        "ollama_server_version": server_version,
        "python_version": platform.python_version(),
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "warmup_policy": WARMUP_POLICY,
        "measured_sample_plan": dataset.sample_plan.plan_id,
    }


def _installed_pydantic_ai_version() -> str:
    """Return the installed Pydantic AI distribution version, if resolvable."""
    try:
        return importlib.metadata.version(_PYDANTIC_AI_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _build_live_model_factory(delegate: Model) -> ModelFactory:
    """Build a per-sample factory around one shared production delegate.

    A fresh ``RecordingPydanticModel`` + ``ModelCallRecorder`` is created per
    sample so each measured sample keeps its own literal request evidence,
    while the underlying production model identity and settings do not drift.
    """

    def factory(_expectation: EvalExpectation) -> tuple[object, ModelCallRecorder]:
        recorder = ModelCallRecorder()
        return RecordingPydanticModel(delegate, recorder=recorder), recorder

    return factory


def _warm_up(dataset: EvalDataset, model_factory: ModelFactory) -> None:
    """Run one discarded warm-up turn (never part of measured observations).

    Raises:
        EvalLiveError: The dataset has no warm-up scenario, or the warm-up turn
            failed.
    """
    case = next(
        (case for case in dataset.cases if case.scenario.scenario_id == WARMUP_SCENARIO_ID),
        None,
    )
    if case is None:
        raise EvalLiveError(f"warm-up scenario {WARMUP_SCENARIO_ID!r} not present in dataset")

    model, _recorder = model_factory(case.scenario.expectation)
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
        raise EvalLiveError(f"live warm-up failed: {type(exc).__name__}: {exc}") from exc


def run_live_eval(
    dataset: EvalDataset,
    *,
    config_path: Path,
    profile_name: str,
) -> EvalReport:
    """Run one explicit live Ollama measured pass over ``dataset``.

    Ordering: load/validate the AGENT profile, construct the exact production
    Pydantic AI Ollama model (before any network request), preflight the
    endpoint+version, run one discarded warm-up, then execute the measured
    dataset exactly once with the shared delegate.

    Raises:
        DndAssistantError: Config/profile loading, model construction,
            preflight or warm-up failure.
    """
    profile = _load_profile(config_path, profile_name)

    # Construct the exact production candidate BEFORE any HTTP request so that
    # wrong provider / wrong role / non-None keep_alive fail before network.
    delegate = build_pydantic_ai_ollama_model(profile)
    try:
        server_version = preflight_ollama(profile)
        metadata = build_runtime_metadata(
            dataset,
            profile,
            profile_name=profile_name,
            server_version=server_version,
        )
        model_factory = _build_live_model_factory(delegate)
        _warm_up(dataset, model_factory)
        return run_dataset(
            dataset,
            model_factory=model_factory,
            runtime_mode=LIVE_RUNTIME,
            runtime_label=LIVE_RUNTIME_LABEL,
            runtime_metadata=metadata,
            require_oracle_consistency=False,
        )
    finally:
        _close_model(delegate)
