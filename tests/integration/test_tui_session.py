"""TUI-04 session integration: real trusted write path.

Uses the production ``DndTuiApp`` and the production ``build_tui_services``
against a deterministic temporary Vault.  No Ollama, no network, no personal
Vault.  Proves the TUI session lifecycle reaches the real trusted services and
records ``source="tui"`` audit provenance.
"""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Coroutine, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from textual.widgets import Input, Static

from dnd_assistant.application.agent_contracts import AgentTextOutcome
from dnd_assistant.application.session_recovery import RecoveryPartition
from dnd_assistant.composition.campaign_state import PlayerCampaignStateView
from dnd_assistant.domain.session import Session
from dnd_assistant.domain.types import EntityId
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_events import ObsidianSessionEventRepository, RawSessionEvent
from dnd_assistant.storage.session_metadata import ObsidianSessionMetadataRepository
from dnd_assistant.storage.world_time import ObsidianWorldTimeRepository
from dnd_assistant.tui.app import DndTuiApp
from dnd_assistant.tui.services import TuiLaunchContext, TuiServices, build_tui_services
from dnd_assistant.tui.session import SessionView


def _run(coro: Coroutine[Any, Any, None]) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        asyncio.run(coro)
    unresolved = [
        str(item.message)
        for item in caught
        if "was destroyed but it is pending" in str(item.message)
        or "was never awaited" in str(item.message)
    ]
    assert not unresolved, f"unresolved async lifecycle diagnostics: {unresolved}"


async def _drain(pilot: Any, predicate: Any) -> None:
    for _ in range(200):
        if predicate():
            return
        await pilot.pause()
    raise AssertionError("condition not reached within pilot iterations")


def _create_vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    for relative in (
        "Sessions",
        "_system",
        "_system/raw",
        "_system/raw/sessions",
        "_system/audit",
        "_system/indexes",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    audit = AuditService(str(root / "_system" / "audit" / "audit.jsonl"))
    world_time = ObsidianWorldTimeRepository(root, audit)
    world_time.initialize_current_world_time(
        13800,
        audit=AuditContext(
            operation_id="test-wt-init",
            real_time=datetime.now(UTC),
            source="test",
        ),
    )
    return root


def _launch(vault: Path, *, allow_agent_write: bool = False) -> TuiLaunchContext:
    return TuiLaunchContext(
        vault_root=vault,
        config_path=vault.parent / "config.toml",
        profile_name="test-agent",
        allow_agent_write=allow_agent_write,
    )


def _output(app: DndTuiApp, widget_id: str) -> str:
    return str(app.screen.query_one(f"#{widget_id}", Static).content)


def _session_wired(app: DndTuiApp) -> bool:
    view = app._first(SessionView)
    return view is not None and view.is_configured


async def _switch(app: DndTuiApp, pilot: Any, view_id: str) -> None:
    app.run_semantic_command(f"view.{view_id}")
    for _ in range(300):
        if app._current_context().context_id == view_id and _session_wired(app):
            return
        await pilot.pause()
    raise AssertionError(f"view {view_id!r} did not settle")


class TestRealSessionWritePath:
    def test_full_lifecycle(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path)
        app = DndTuiApp(build_tui_services(_launch(vault)))
        audit_log = vault / "_system" / "audit" / "audit.jsonl"

        async def scenario() -> None:
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await _switch(app, pilot, "session")

                assert app.run_semantic_command("session.start").name == "EXECUTED"
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert "S001" in _output(app, "session-output")

                app.screen.query_one("#session-note-input", Input).value = "Варос найден"
                assert app.run_semantic_command("session.note").name == "EXECUTED"
                await _drain(pilot, lambda: not app._gate.is_busy)

                app.screen.query_one("#session-touched", Input).value = "npc-varos, item-001"
                assert app.run_semantic_command("session.end").name == "EXECUTED"
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert "завершена" in _output(app, "session-output")

        _run(scenario())

        audit = AuditService(str(audit_log))
        records = audit.read_all()
        tui_records = [record for record in records if record.source == "tui"]
        assert tui_records, "expected TUI-sourced audit records"
        assert {record.operation_id.split("-")[0] for record in tui_records} == {"tui"}
        assert any(record.operation_id.startswith("tui-session-start-") for record in tui_records)
        assert any(record.operation_id.startswith("tui-note-") for record in tui_records)
        assert any(record.operation_id.startswith("tui-session-end-") for record in tui_records)
        assert all(record.source != "cli" for record in tui_records)

        session_repo = ObsidianSessionMetadataRepository(vault, audit)
        metadata = session_repo.get_session_metadata("S001")
        assert metadata.session.status == "completed"
        assert metadata.extra_fields.get("touched_entities") == ["npc-varos", "item-001"]

        event_repo = ObsidianSessionEventRepository(vault, audit)
        notes = [event for event in event_repo.list_events("S001") if event.type == "note"]
        assert notes
        assert notes[-1].extra_fields.get("text") == "Варос найден"

    def test_status_when_no_active_session(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path)
        app = DndTuiApp(build_tui_services(_launch(vault)))

        async def scenario() -> None:
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await _switch(app, pilot, "session")
                await _drain(
                    pilot,
                    lambda: "Активной сессии нет" in _output(app, "session-status"),
                )

        _run(scenario())


class _FakeAssistant:
    def run(self, query: str, *, allow_agent_write: bool) -> AgentTextOutcome:
        raise AssertionError("assistant must not run")


class _BlockingSession:
    def __init__(self, issue: object) -> None:
        self._issue = issue
        self.start_calls = 0

    def recovery_partition(self) -> RecoveryPartition:
        return RecoveryPartition(blocking=(self._issue,), externally_owned=())  # type: ignore[arg-type]

    def status(self) -> Session | None:
        return None

    def start(self) -> Session:
        self.start_calls += 1
        raise AssertionError("blocked mutation must not execute")

    def note(self, text: str) -> RawSessionEvent:
        raise AssertionError("blocked mutation must not execute")

    def end(self, touched_entity_ids: Sequence[EntityId]) -> Session:
        raise AssertionError("blocked mutation must not execute")


class _FakeCampaign:
    def inspect(self) -> PlayerCampaignStateView:
        from dnd_assistant.composition.campaign_state import CampaignStateStatus

        return PlayerCampaignStateView(status=CampaignStateStatus.MISSING)

    def rebuild(self) -> PlayerCampaignStateView:
        raise AssertionError("not used")


class TestRecoveryBlocksMutation:
    def test_blocking_recovery_prevents_session_start(self) -> None:
        from dnd_assistant.storage.session_recovery import RecoveryIssue

        issue = RecoveryIssue("unresolved_audit_intent", operation_id="op-1")
        session = _BlockingSession(issue)
        services = TuiServices(
            launch=TuiLaunchContext(
                vault_root=Path("vault"),
                config_path=Path("config.toml"),
                profile_name="test-agent",
            ),
            assistant=_FakeAssistant(),
            session=session,
            campaign_state=_FakeCampaign(),
        )
        app = DndTuiApp(services)

        async def scenario() -> None:
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await _switch(app, pilot, "session")
                assert app.run_semantic_command("session.start").name == "EXECUTED"
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert session.start_calls == 0
                assert "повреждённое" in _output(app, "session-output")

        _run(scenario())
