"""Unit tests: explicit live DeepSeek eval composition (RM-05 Phase A).

All offline: model construction is replaced with a deterministic Pydantic AI
``FunctionModel`` double and no credential/network path is reached.  The tests
prove candidate-identity fail-closed behavior, warm-up/measured ownership,
``response_model`` capture and metadata privacy.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from dnd_assistant.composition import eval_deepseek, eval_ollama
from dnd_assistant.composition.eval_deepseek import EvalDeepSeekError, run_live_eval
from dnd_assistant.errors import CredentialError
from dnd_assistant.evals.datasets.product_v1 import build_product_v1_dataset
from dnd_assistant.models.profiles import ModelProfile

_TERMINAL = '{"kind":"respond","message":"ok"}'

_CANONICAL_LINES = [
    'provider = "deepseek"',
    'model = "deepseek-flash"',
    'base_url = "https://api.deepseek.com"',
    'role = "agent"',
    "thinking = true",
    'reasoning_effort = "high"',
]


def _write_config(
    path: Path,
    *,
    lines: Sequence[str] = tuple(_CANONICAL_LINES),
    name: str = "agent-deepseek",
) -> Path:
    text = f"[profiles.{name}]\n" + "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


class _Delegate(FunctionModel):
    """Deterministic terminal-only delegate that counts requests.

    Each response carries the configured ``model_name`` (the public
    provider-reported model id), cycling through the supplied names.  The value
    is applied in ``request`` because ``FunctionModel`` overwrites
    ``response.model_name`` with its own framework name.
    """

    def __init__(self, names: Sequence[str | None] = ("deepseek-flash",)) -> None:
        self.calls = 0
        self._names = list(names) or [None]
        self._name_index = 0

        def _respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            self.calls += 1
            return ModelResponse(parts=[TextPart(_TERMINAL)])

        super().__init__(_respond)

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: Any,
        model_request_parameters: Any,
    ) -> ModelResponse:
        response = await super().request(messages, model_settings, model_request_parameters)
        name = self._names[min(self._name_index, len(self._names) - 1)]
        self._name_index += 1
        response.model_name = name
        return response


@pytest.fixture
def no_build(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if the candidate identity check does not fail first."""

    def _boom(_profile: ModelProfile) -> Any:
        raise AssertionError("model construction must not be reached")

    monkeypatch.setattr(eval_deepseek, "_build_agent_model", _boom)


def _run_with_delegate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    delegate: _Delegate | None = None,
) -> tuple[Any, _Delegate]:
    config = _write_config(tmp_path / "models.toml")
    resolved = delegate if delegate is not None else _Delegate()
    monkeypatch.setattr(eval_deepseek, "_build_agent_model", lambda _profile: resolved)
    report = run_live_eval(
        build_product_v1_dataset(),
        config_path=config,
        profile_name="agent-deepseek",
        qualification_date="2026-09-21",
    )
    return report, resolved


# ── Candidate identity fails before model construction ─────────────────────


def test_canonical_profile_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report, _delegate = _run_with_delegate(tmp_path, monkeypatch)
    metadata = dict(report.runtime.metadata)
    assert metadata["provider"] == "deepseek"
    assert metadata["model"] == "deepseek-flash"
    assert metadata["thinking"] == "true"
    assert metadata["reasoning_effort"] == "high"


def test_wrong_provider_fails_before_build(tmp_path: Path, no_build: None) -> None:
    config = _write_config(
        tmp_path / "models.toml",
        lines=[
            'provider = "ollama"',
            'model = "deepseek-flash"',
            'base_url = "http://localhost:11434"',
            'role = "agent"',
        ],
    )
    with pytest.raises(EvalDeepSeekError, match="provider="):
        run_live_eval(build_product_v1_dataset(), config_path=config, profile_name="agent-deepseek")


@pytest.mark.parametrize(
    "override",
    [
        'model = "deepseek-reasoner"',
        "thinking = false",
        'reasoning_effort = "low"',
        'base_url = "https://example.com"',
    ],
)
def test_wrong_candidate_identity_fails_before_build(
    tmp_path: Path, no_build: None, override: str
) -> None:
    key = override.split("=", 1)[0].strip()
    lines = [line for line in _CANONICAL_LINES if not line.strip().startswith(f"{key} =")]
    # thinking=false must not carry reasoning_effort (RM-01 contract).
    if override == "thinking = false":
        lines = [line for line in lines if not line.strip().startswith("reasoning_effort")]
    lines.append(override)
    config = _write_config(tmp_path / "models.toml", lines=lines)
    with pytest.raises(EvalDeepSeekError):
        run_live_eval(build_product_v1_dataset(), config_path=config, profile_name="agent-deepseek")


def test_missing_credential_fails_closed_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = _write_config(tmp_path / "models.toml")
    with pytest.raises(CredentialError, match="DEEPSEEK_API_KEY"):
        run_live_eval(build_product_v1_dataset(), config_path=config, profile_name="agent-deepseek")


# ── Warm-up / measured-dataset ownership ───────────────────────────────────


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

    assert all(o.model_request_count == 1 for o in report.full_turn_observations)
    keys = [(o.scenario_id, o.repetition) for o in report.full_turn_observations]
    assert len(keys) == 13
    assert len(set(keys)) == 13


def test_warmup_is_excluded_from_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, _delegate = _run_with_delegate(tmp_path, monkeypatch)
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
    assert report.runtime.mode == "deepseek"
    assert report.runtime.label == "deepseek-live"


def test_latency_uses_same_frozen_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, _delegate = _run_with_delegate(tmp_path, monkeypatch)
    assert report.latency.decision.sample_count == 13
    assert report.latency.full_turn.sample_count == 13


def test_production_dispatch_invoked_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_config(tmp_path / "models.toml")
    delegate = _Delegate()
    calls: list[ModelProfile] = []

    def _dispatch(profile: ModelProfile) -> Any:
        calls.append(profile)
        return delegate

    monkeypatch.setattr(eval_deepseek, "_build_agent_model", _dispatch)
    run_live_eval(
        build_product_v1_dataset(),
        config_path=config,
        profile_name="agent-deepseek",
        qualification_date="2026-09-21",
    )
    assert len(calls) == 1


def test_warmup_failure_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_config(tmp_path / "models.toml")

    def _boom(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise RuntimeError("warmup exploded")

    monkeypatch.setattr(eval_deepseek, "_build_agent_model", lambda _profile: FunctionModel(_boom))
    with pytest.raises(EvalDeepSeekError, match="warm-up failed"):
        run_live_eval(build_product_v1_dataset(), config_path=config, profile_name="agent-deepseek")


def test_warmup_constants_bound_to_ollama_policy() -> None:
    assert eval_deepseek.WARMUP_SCENARIO_ID == eval_ollama.WARMUP_SCENARIO_ID
    assert eval_deepseek.WARMUP_POLICY == eval_ollama.WARMUP_POLICY


# ── response_model capture ─────────────────────────────────────────────────


def test_response_model_single(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report, _delegate = _run_with_delegate(
        tmp_path, monkeypatch, delegate=_Delegate(names=("deepseek-chat",))
    )
    assert dict(report.runtime.metadata)["response_model"] == "deepseek-chat"


def test_response_model_multiple(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report, _delegate = _run_with_delegate(
        tmp_path, monkeypatch, delegate=_Delegate(names=("model-a", "model-b"))
    )
    assert dict(report.runtime.metadata)["response_model"] == "multiple"


def test_response_model_not_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report, _delegate = _run_with_delegate(tmp_path, monkeypatch, delegate=_Delegate(names=(None,)))
    assert dict(report.runtime.metadata)["response_model"] == "not-reported"


# ── Runtime metadata privacy and identity ──────────────────────────────────


def test_runtime_metadata_selected_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report, _delegate = _run_with_delegate(tmp_path, monkeypatch)
    metadata = dict(report.runtime.metadata)
    assert set(metadata) == {
        "provider",
        "profile_name",
        "model",
        "role",
        "thinking",
        "reasoning_effort",
        "temperature",
        "pydantic_ai_version",
        "python_version",
        "platform_system",
        "platform_machine",
        "warmup_policy",
        "measured_sample_plan",
        "documented_route",
        "qualification_date",
        "response_model",
    }
    assert metadata["profile_name"] == "agent-deepseek"
    assert metadata["role"] == "agent"
    assert metadata["temperature"] == "none"
    assert metadata["warmup_policy"] == "one-discarded-eval-p1-001"
    assert metadata["measured_sample_plan"] == "single-pass-v1"
    assert metadata["documented_route"] == "DeepSeek-V4.1-Flash"
    assert metadata["qualification_date"] == "2026-09-21"


def test_runtime_metadata_has_no_private_or_secret_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, _delegate = _run_with_delegate(tmp_path, monkeypatch)
    blob = json.dumps(dict(report.runtime.metadata), ensure_ascii=False)
    assert str(tmp_path) not in blob
    assert "models.toml" not in blob
    assert "api.deepseek.com" not in blob
    assert "endpoint" not in blob
    assert "localhost" not in blob
    assert "api_key" not in blob.lower()
    assert "authorization" not in blob.lower()
    assert "reasoning_content" not in blob
