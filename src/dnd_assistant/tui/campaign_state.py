"""Campaign-State capability view (TUI-04).

Presentation only.  Receives only the player-safe
``PlayerCampaignStateView`` DTO: exact trusted status plus PLAYER-projected
recently-touched references.  Internal ``CampaignState``, manifest,
fingerprint, provenance, cause and raw detail are structurally absent.

Status labels are fixed Russian renderings of the trusted status enum; no raw
inspection detail is forwarded.  Inspection is a gated read; rebuild is the
explicit exclusive derived-maintenance operation.
"""

from __future__ import annotations

from typing import cast

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Static
from textual.worker import Worker, WorkerState

from dnd_assistant.composition.campaign_state import (
    CampaignStateStatus,
    PlayerCampaignStateView,
)
from dnd_assistant.errors import DndAssistantError
from dnd_assistant.tui.inflight import EXCLUSIVE_CAMPAIGN_STATE
from dnd_assistant.tui.services import (
    CampaignStateCapabilityProtocol,
    CampaignStateOutcome,
)
from dnd_assistant.tui.view import CapabilityView

__all__ = ["CampaignStateView", "render_campaign_state_view", "STATUS_LABELS"]

_READ_GROUP = "campaign-state-read"

STATUS_LABELS: dict[CampaignStateStatus, str] = {
    CampaignStateStatus.MISSING: "не создано",
    CampaignStateStatus.OUTDATED: "устаревший формат",
    CampaignStateStatus.CORRUPT: "повреждено",
    CampaignStateStatus.UNVERIFIABLE: "невозможно проверить",
    CampaignStateStatus.STALE: "требует обновления",
    CampaignStateStatus.CURRENT: "актуально",
}


def render_campaign_state_view(view: PlayerCampaignStateView) -> str:
    """Render a PLAYER-safe Campaign-State view; never internal state."""
    status = view.status
    lines = [f"Состояние: {STATUS_LABELS[status]}"]
    refs = view.recently_touched
    if refs is None:
        lines.append("Данные о недавно затронутых сущностях недоступны.")
        return "\n".join(lines)
    lines.append("Недавно затронутые:")
    if not refs:
        lines.append("  (нет)")
        return "\n".join(lines)
    for ref in refs:
        lines.append(f"  — {ref.name} ({ref.entity_type.value})")
    return "\n".join(lines)


class CampaignStateView(CapabilityView):
    """Player-facing Campaign-State view."""

    WORKER_OWNER = EXCLUSIVE_CAMPAIGN_STATE

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._capability: CampaignStateCapabilityProtocol | None = None

    # ── Composition / wiring ────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Static("Состояние кампании", id="campaign-state-title")
        yield Static("", id="campaign-state-body")
        yield Static("", id="campaign-state-error")
        with Horizontal(id="campaign-state-actions"):
            yield Button("Обновить", id="campaign-state-reload")
            yield Button("Перестроить", id="campaign-state-rebuild")

    def set_capabilities(self, *, campaign_state: CampaignStateCapabilityProtocol) -> None:
        self._capability = campaign_state

    # ── Event → semantic dispatch convergence ───────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "campaign-state-reload":
            self.host.run_semantic_command("campaign-state.reload")
        elif event.button.id == "campaign-state-rebuild":
            self.host.run_semantic_command("campaign-state.rebuild")

    # ── Command entry points ────────────────────────────────────────────────

    def reload(self) -> None:
        """Read-only inspection (not gated)."""
        if self._capability is None:
            return
        self.run_worker(
            self._run_inspect,
            name="campaign-state.inspect",
            group=_READ_GROUP,
            thread=True,
            exit_on_error=False,
        )

    def rebuild(self) -> None:
        """Explicit exclusive derived rebuild."""
        self._start_exclusive(name="campaign-state.rebuild", work=self._run_rebuild)

    # ── Workers (synchronous trusted work; no UI access) ────────────────────

    def _run_inspect(self) -> CampaignStateOutcome:
        assert self._capability is not None
        try:
            view = self._capability.inspect()
        except DndAssistantError as exc:
            return CampaignStateOutcome(ok=False, error_message=f"Ошибка: {exc}")
        return CampaignStateOutcome(ok=True, view=view)

    def _run_rebuild(self) -> CampaignStateOutcome:
        assert self._capability is not None
        try:
            view = self._capability.rebuild()
        except DndAssistantError as exc:
            return CampaignStateOutcome(ok=False, error_message=f"Ошибка: {exc}")
        return CampaignStateOutcome(ok=True, view=view)

    # ── Event-loop UI update ────────────────────────────────────────────────

    def _handle_result(self, result: object) -> None:
        self._apply(cast(CampaignStateOutcome, result))

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        super().on_worker_state_changed(event)
        worker = event.worker
        if worker.group != _READ_GROUP:
            return
        if event.state not in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            return
        if event.state is WorkerState.SUCCESS:
            self._apply(cast(CampaignStateOutcome, worker.result))
        elif event.state is WorkerState.ERROR and worker.error is not None:
            raise worker.error

    def _apply(self, outcome: CampaignStateOutcome) -> None:
        error_widget = self.query_one("#campaign-state-error", Static)
        if outcome.ok and outcome.view is not None:
            self.query_one("#campaign-state-body", Static).update(
                render_campaign_state_view(outcome.view)
            )
            error_widget.update("")
        else:
            error_widget.update(outcome.error_message or "Ошибка.")
