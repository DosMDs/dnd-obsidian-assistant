"""TUI capability adapters and bounded services bundle (TUI-04).

Proves per-submission runtime close exactly once and the agent-WRITE ceiling
without any real Ollama/model.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from dnd_assistant.application.agent_contracts import AgentOutcomeKind, AgentTextOutcome
from dnd_assistant.application.session_recovery import RecoveryPartition
from dnd_assistant.composition.campaign_state import CampaignStateStatus, PlayerCampaignStateView
from dnd_assistant.domain.session import Session
from dnd_assistant.domain.types import EntityId
from dnd_assistant.errors import DndAssistantError, ValidationError
from dnd_assistant.storage.session_events import RawSessionEvent
from dnd_assistant.tui import services as services_module
from dnd_assistant.tui.services import (
    ComposedAssistant,
    ComposedSession,
    TuiLaunchContext,
    TuiServices,
    build_tui_services,
)


def _launch(*, allow_agent_write: bool = True) -> TuiLaunchContext:
    return TuiLaunchContext(
        vault_root=Path("vault"),
        config_path=Path("config.toml"),
        profile_name="test-agent",
        allow_agent_write=allow_agent_write,
    )


class _FakeAgentRuntime:
    def __init__(self, *, outcome: Any = None, error: Exception | None = None) -> None:
        self._outcome = outcome
        self._error = error
        self.run_calls = 0

    def run(self, query: str, *, execution_context: object) -> Any:
        self.run_calls += 1
        if self._error is not None:
            raise self._error
        return type("_Result", (), {"outcome": self._outcome})()


class _FakeAskRuntime:
    def __init__(self, agent_runtime: _FakeAgentRuntime) -> None:
        self.agent_runtime = agent_runtime
        self.execution_context = object()
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def _patch_compose(
    monkeypatch: pytest.MonkeyPatch,
    *,
    outcome: Any = None,
    run_error: Exception | None = None,
    compose_error: Exception | None = None,
) -> dict[str, Any]:
    holder: dict[str, Any] = {"calls": 0, "runtime": None}

    def fake_compose(**kwargs: Any) -> _FakeAskRuntime:
        holder["calls"] += 1
        if compose_error is not None:
            raise compose_error
        runtime = _FakeAskRuntime(_FakeAgentRuntime(outcome=outcome, error=run_error))
        holder["runtime"] = runtime
        return runtime

    monkeypatch.setattr(services_module, "compose_ask_runtime", fake_compose)
    return holder


_OK = AgentTextOutcome(kind=AgentOutcomeKind.RESPOND, message="Ответ")


class TestComposedAssistantLifetime:
    def test_success_closes_exactly_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        holder = _patch_compose(monkeypatch, outcome=_OK)
        assistant = ComposedAssistant(_launch())
        result = assistant.run("q", allow_agent_write=False)
        assert result.kind is AgentOutcomeKind.RESPOND
        assert holder["calls"] == 1
        assert holder["runtime"].close_calls == 1

    def test_expected_error_closes_exactly_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        holder = _patch_compose(monkeypatch, run_error=DndAssistantError("boom"))
        assistant = ComposedAssistant(_launch())
        with pytest.raises(DndAssistantError):
            assistant.run("q", allow_agent_write=False)
        assert holder["calls"] == 1
        assert holder["runtime"].close_calls == 1

    def test_unexpected_error_closes_exactly_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        holder = _patch_compose(monkeypatch, run_error=RuntimeError("unexpected"))
        assistant = ComposedAssistant(_launch())
        with pytest.raises(RuntimeError):
            assistant.run("q", allow_agent_write=False)
        assert holder["calls"] == 1
        assert holder["runtime"].close_calls == 1

    def test_composition_failure_propagates_without_close(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        holder = _patch_compose(monkeypatch, compose_error=DndAssistantError("compose"))
        assistant = ComposedAssistant(_launch())
        with pytest.raises(DndAssistantError):
            assistant.run("q", allow_agent_write=False)
        assert holder["calls"] == 1
        assert holder["runtime"] is None


class TestAgentWriteCeiling:
    def test_write_requested_without_ceiling_rejected_before_compose(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        holder = _patch_compose(monkeypatch, outcome=_OK)
        assistant = ComposedAssistant(_launch(allow_agent_write=False))
        with pytest.raises(ValidationError):
            assistant.run("q", allow_agent_write=True)
        assert holder["calls"] == 0

    def test_read_submission_allowed_without_ceiling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        holder = _patch_compose(monkeypatch, outcome=_OK)
        assistant = ComposedAssistant(_launch(allow_agent_write=False))
        assistant.run("q", allow_agent_write=False)
        assert holder["calls"] == 1

    def test_write_submission_allowed_with_ceiling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        holder = _patch_compose(monkeypatch, outcome=_OK)
        assistant = ComposedAssistant(_launch(allow_agent_write=True))
        assistant.run("q", allow_agent_write=True)
        assert holder["calls"] == 1


class _NoopSession:
    def recovery_partition(self) -> RecoveryPartition:
        raise AssertionError

    def status(self) -> Session | None:
        raise AssertionError

    def start(self) -> Session:
        raise AssertionError

    def note(self, text: str) -> RawSessionEvent:
        raise AssertionError

    def end(self, touched_entity_ids: Sequence[EntityId]) -> Session:
        raise AssertionError


class _NoopCampaign:
    def inspect(self) -> PlayerCampaignStateView:
        return PlayerCampaignStateView(status=CampaignStateStatus.MISSING)

    def rebuild(self) -> PlayerCampaignStateView:
        return PlayerCampaignStateView(status=CampaignStateStatus.CURRENT, recently_touched=())


class TestBoundedServices:
    def test_fields_are_named_capabilities_only(self) -> None:
        names = {field.name for field in dataclasses.fields(TuiServices)}
        assert names == {"launch", "assistant", "session", "campaign_state"}

    def test_no_service_locator_surface(self) -> None:
        for name in ("get_service", "get", "getitem", "__getitem__", "registry"):
            assert not hasattr(TuiServices, name)

    def test_build_returns_capability_adapters(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        (vault / "_system" / "audit").mkdir(parents=True)
        launch = TuiLaunchContext(
            vault_root=vault,
            config_path=Path("config.toml"),
            profile_name="test-agent",
            allow_agent_write=True,
        )
        services = build_tui_services(launch)
        assert isinstance(services.launch, TuiLaunchContext)
        assert isinstance(services.assistant, ComposedAssistant)
        assert isinstance(services.session, ComposedSession)
        assert services.launch.allow_agent_write is True

    def test_dto_bundle_constructed_from_named_fields(self) -> None:
        services = TuiServices(
            launch=_launch(),
            assistant=ComposedAssistant(_launch()),
            session=_NoopSession(),
            campaign_state=_NoopCampaign(),
        )
        assert services.campaign_state.inspect().status is CampaignStateStatus.MISSING
