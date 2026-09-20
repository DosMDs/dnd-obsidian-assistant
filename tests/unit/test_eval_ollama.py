"""Unit tests: explicit live Ollama eval composition (S14-07).

All offline: HTTP is mocked with respx and model construction is replaced with
a deterministic Pydantic AI ``FunctionModel`` double.  No real Ollama, no
network, no Vault.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import respx
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from dnd_assistant.composition import eval_ollama
from dnd_assistant.composition.eval_ollama import (
    EvalLiveError,
    preflight_ollama,
    run_live_eval,
)
from dnd_assistant.evals.contracts import EvalExpectation, ScenarioExpectationKind
from dnd_assistant.evals.datasets.product_v1 import build_product_v1_dataset
from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole

_BASE_URL = "http://localhost:11434"
_TERMINAL = '{"kind":"respond","message":"ok"}'


def _write_config(
    path: Path,
    *,
    provider: str = "ollama",
    role: str = "agent",
    keep_alive: str | None = None,
    model: str = "test-model",
    name: str = "agent",
) -> Path:
    lines = [
        f"[profiles.{name}]",
        f'provider = "{provider}"',
        f'model = "{model}"',
        f'base_url = "{_BASE_URL}"',
        "temperature = 0.2",
        f'role = "{role}"',
    ]
    if keep_alive is not None:
        lines.append(f'keep_alive = "{keep_alive}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _profile(**overrides: Any) -> ModelProfile:
    base: dict[str, Any] = {
        "provider": "ollama",
        "model": "test-model",
        "base_url": _BASE_URL,
        "temperature": 0.2,
        "role": ModelProfileRole.AGENT,
    }
    base.update(overrides)
    return ModelProfile(**base)


class _CountingDelegate(FunctionModel):
    """Deterministic terminal-only delegate that counts semantic requests."""

    def __init__(self) -> None:
        self.calls = 0

        def _respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            self.calls += 1
            return ModelResponse(parts=[TextPart(_TERMINAL)])

        super().__init__(_respond)


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if any preflight/network path is reached."""

    def _boom(_profile: ModelProfile) -> str:
        raise AssertionError("network preflight must not be reached")

    monkeypatch.setattr(eval_ollama, "preflight_ollama", _boom)


# ── Config/profile validation before network ───────────────────────────────


def test_missing_config_fails_before_network(tmp_path: Path, no_network: None) -> None:
    dataset = build_product_v1_dataset()
    with pytest.raises(Exception, match="not found"):
        run_live_eval(dataset, config_path=tmp_path / "nope.toml", profile_name="agent")


def test_missing_profile_fails_before_network(tmp_path: Path, no_network: None) -> None:
    config = _write_config(tmp_path / "models.toml", name="agent")
    dataset = build_product_v1_dataset()
    with pytest.raises(Exception, match="not found"):
        run_live_eval(dataset, config_path=config, profile_name="absent")


def test_wrong_role_fails_before_network(tmp_path: Path, no_network: None) -> None:
    config = _write_config(tmp_path / "models.toml", role="summarizer")
    dataset = build_product_v1_dataset()
    with pytest.raises(Exception, match="expected 'agent'"):
        run_live_eval(dataset, config_path=config, profile_name="agent")


def test_wrong_provider_fails_before_network(tmp_path: Path, no_network: None) -> None:
    config = _write_config(tmp_path / "models.toml", provider="openai")
    dataset = build_product_v1_dataset()
    with pytest.raises(Exception, match="provider='ollama'"):
        run_live_eval(dataset, config_path=config, profile_name="agent")


def test_keep_alive_non_none_fails_before_network(tmp_path: Path, no_network: None) -> None:
    config = _write_config(tmp_path / "models.toml", keep_alive="5m")
    dataset = build_product_v1_dataset()
    with pytest.raises(Exception, match="keep_alive"):
        run_live_eval(dataset, config_path=config, profile_name="agent")


# ── Preflight ──────────────────────────────────────────────────────────────


def test_preflight_healthy_returns_version() -> None:
    with respx.mock:
        respx.get(f"{_BASE_URL}/api/version").respond(200, json={"version": "0.34.1"})
        respx.get(f"{_BASE_URL}/api/tags").respond(200, json={"models": [{"name": "test-model"}]})
        assert preflight_ollama(_profile()) == "0.34.1"


def test_preflight_unreachable_fails() -> None:
    with respx.mock:
        respx.get(f"{_BASE_URL}/api/version").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        with pytest.raises(EvalLiveError, match="not reachable"):
            preflight_ollama(_profile())


def test_preflight_model_unavailable_fails() -> None:
    with respx.mock:
        respx.get(f"{_BASE_URL}/api/version").respond(200, json={"version": "0.34.1"})
        respx.get(f"{_BASE_URL}/api/tags").respond(200, json={"models": [{"name": "other-model"}]})
        with pytest.raises(EvalLiveError, match="not available"):
            preflight_ollama(_profile())


def test_version_probe_http_error() -> None:
    with respx.mock:
        respx.get(f"{_BASE_URL}/api/version").respond(500)
        with pytest.raises(EvalLiveError, match="HTTP 500"):
            eval_ollama._fetch_ollama_server_version(_BASE_URL)


def test_version_probe_non_json() -> None:
    with respx.mock:
        respx.get(f"{_BASE_URL}/api/version").respond(200, content=b"not json")
        with pytest.raises(EvalLiveError, match="non-JSON"):
            eval_ollama._fetch_ollama_server_version(_BASE_URL)


@pytest.mark.parametrize("payload", [{}, {"version": ""}, {"version": "   "}])
def test_version_probe_missing_or_empty(payload: dict[str, str]) -> None:
    with respx.mock:
        respx.get(f"{_BASE_URL}/api/version").respond(200, json=payload)
        with pytest.raises(EvalLiveError, match="usable 'version' field"):
            eval_ollama._fetch_ollama_server_version(_BASE_URL)


# ── Orchestration: warm-up + measured-once evidence ────────────────────────


def _run_with_delegate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, _CountingDelegate]:
    config = _write_config(tmp_path / "models.toml")
    delegate = _CountingDelegate()
    monkeypatch.setattr(eval_ollama, "build_pydantic_ai_ollama_model", lambda _profile: delegate)
    monkeypatch.setattr(eval_ollama, "preflight_ollama", lambda _profile: "0.34.1")
    report = run_live_eval(build_product_v1_dataset(), config_path=config, profile_name="agent")
    return report, delegate


def test_warmup_once_and_measured_set_executes_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, delegate = _run_with_delegate(tmp_path, monkeypatch)

    # 1 discarded warm-up (EVAL-P1-001) + exactly 13 measured samples, no retry.
    assert delegate.calls == 14
    assert report.sample_contract.expected_sample_count == 13
    assert report.sample_contract.observed_decision_count == 13
    assert report.sample_contract.observed_full_turn_count == 13
    assert report.sample_contract.complete
    assert report.run_validity.runtime_error_count == 0

    # Every measured sample keeps its own literal recorder count.
    assert all(o.model_request_count == 1 for o in report.full_turn_observations)
    keys = [(o.scenario_id, o.repetition) for o in report.full_turn_observations]
    assert len(keys) == 13
    assert len(set(keys)) == 13


def test_warmup_is_excluded_from_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, _delegate = _run_with_delegate(tmp_path, monkeypatch)
    # The warm-up runs EVAL-P1-001 but it appears exactly once in the measured
    # observations (its measured sample), never as an extra observation.
    warmup_keys = [
        (o.scenario_id, o.repetition)
        for o in report.full_turn_observations
        if o.scenario_id == "EVAL-P1-001"
    ]
    assert warmup_keys == [("EVAL-P1-001", 0)]


def test_live_candidate_does_not_require_oracle_consistency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, _delegate = _run_with_delegate(tmp_path, monkeypatch)
    assert report.run_validity.oracle_consistency_required is False
    assert report.runtime.mode == "ollama"
    assert report.runtime.label == "ollama-live"


def test_latency_uses_same_frozen_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, _delegate = _run_with_delegate(tmp_path, monkeypatch)
    assert report.latency.decision.sample_count == 13
    assert report.latency.full_turn.sample_count == 13
    assert report.latency.decision.p50_seconds is not None
    assert report.latency.full_turn.p95_seconds is not None


def test_production_factory_invoked_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_config(tmp_path / "models.toml")
    delegate = _CountingDelegate()
    calls: list[object] = []

    def _factory(profile: ModelProfile) -> Any:
        calls.append(profile)
        return delegate

    monkeypatch.setattr(eval_ollama, "build_pydantic_ai_ollama_model", _factory)
    monkeypatch.setattr(eval_ollama, "preflight_ollama", lambda _profile: "0.34.1")
    run_live_eval(build_product_v1_dataset(), config_path=config, profile_name="agent")
    assert len(calls) == 1


def test_warmup_failure_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_config(tmp_path / "models.toml")

    def _boom(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise RuntimeError("warmup exploded")

    monkeypatch.setattr(
        eval_ollama, "build_pydantic_ai_ollama_model", lambda _profile: FunctionModel(_boom)
    )
    monkeypatch.setattr(eval_ollama, "preflight_ollama", lambda _profile: "0.34.1")
    with pytest.raises(EvalLiveError, match="warm-up failed"):
        run_live_eval(build_product_v1_dataset(), config_path=config, profile_name="agent")


# ── Runtime metadata privacy and identity ──────────────────────────────────


def _metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    report, _delegate = _run_with_delegate(tmp_path, monkeypatch)
    return dict(report.runtime.metadata)


def test_runtime_metadata_selected_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    metadata = _metadata(tmp_path, monkeypatch)
    assert set(metadata) == {
        "provider",
        "profile_name",
        "model",
        "role",
        "temperature",
        "keep_alive",
        "pydantic_ai_version",
        "ollama_server_version",
        "python_version",
        "platform_system",
        "platform_machine",
        "warmup_policy",
        "measured_sample_plan",
    }
    assert metadata["provider"] == "ollama"
    assert metadata["profile_name"] == "agent"
    assert metadata["model"] == "test-model"
    assert metadata["role"] == "agent"
    assert metadata["keep_alive"] == "none"
    assert metadata["ollama_server_version"] == "0.34.1"
    assert metadata["warmup_policy"] == "one-discarded-eval-p1-001"
    assert metadata["measured_sample_plan"] == "single-pass-v1"


def test_runtime_metadata_has_no_private_path_or_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata = _metadata(tmp_path, monkeypatch)
    blob = json.dumps(metadata, ensure_ascii=False)
    assert str(tmp_path) not in blob
    assert "models.toml" not in blob
    assert _BASE_URL not in blob
    assert "endpoint" not in blob
    assert "localhost" not in blob


def test_live_model_factory_wraps_same_delegate() -> None:
    delegate = _CountingDelegate()
    factory = eval_ollama._build_live_model_factory(delegate)
    expectation = EvalExpectation(ScenarioExpectationKind.RESPOND_NO_TOOL)
    first, first_recorder = factory(expectation)
    second, second_recorder = factory(expectation)
    assert first is not second
    assert first_recorder is not second_recorder
    assert cast(Any, first).wrapped is delegate
    assert cast(Any, second).wrapped is delegate
