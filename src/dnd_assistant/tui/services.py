"""Immutable TUI launch context, capability bundle and production adapters (TUI-04).

The TUI reaches trusted behaviour only through narrow capability protocols:
assistant, session and Campaign-State.  Production builders wrap the accepted
shared composition (``dnd_assistant.composition``); tests inject deterministic
fakes at this exact boundary.

This module is a small launch-services bundle, **not** a service locator:
:class:`TuiServices` exposes three named capability fields and no
``get_service``/mapping/registry surface.

The assistant capability composes/run/closes one ``AskRuntime`` per call, so
the trusted session mode/audit identity is refreshed per submission and the
model is closed exactly once even on error.  ``allow_agent_write`` is the
agent/model WRITE ceiling; explicit human session mutations use their own
trusted deterministic paths and are unaffected by it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from dnd_assistant.application.agent_contracts import AgentTextOutcome
from dnd_assistant.application.session_recovery import RecoveryPartition
from dnd_assistant.composition.agent_runtime import compose_ask_runtime
from dnd_assistant.composition.audit_context import build_audit_context
from dnd_assistant.composition.campaign_state import (
    PlayerCampaignStateView,
    compose_campaign_state_capability,
)
from dnd_assistant.composition.session_runtime import (
    compose_recovery_service,
    compose_session_runtime,
)
from dnd_assistant.domain.session import Session
from dnd_assistant.domain.types import EntityId
from dnd_assistant.errors import ValidationError
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.storage.session_events import RawSessionEvent

__all__ = [
    "AssistantCapability",
    "AssistantOutcome",
    "AssistantOutcomeKind",
    "CampaignStateCapabilityProtocol",
    "CampaignStateOutcome",
    "ComposedAssistant",
    "ComposedSession",
    "SessionCapability",
    "SessionOutcome",
    "TuiLaunchContext",
    "TuiServices",
    "build_tui_services",
]


# ── Launch context ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TuiLaunchContext:
    """Immutable per-invocation TUI launch configuration.

    ``allow_agent_write`` is the agent/model WRITE ceiling established at
    launch.  It is not a ban on explicit human session mutations.
    """

    vault_root: Path
    config_path: Path
    profile_name: str
    allow_agent_write: bool = False


# ── Capability protocols ───────────────────────────────────────────────────


class AssistantCapability(Protocol):
    """Bounded single-run assistant capability."""

    def run(self, query: str, *, allow_agent_write: bool) -> AgentTextOutcome: ...


class SessionCapability(Protocol):
    """Deterministic session lifecycle + recovery preflight capability."""

    def recovery_partition(self) -> RecoveryPartition: ...

    def status(self) -> Session | None: ...

    def start(self) -> Session: ...

    def note(self, text: str) -> RawSessionEvent: ...

    def end(self, touched_entity_ids: Sequence[EntityId]) -> Session: ...


class CampaignStateCapabilityProtocol(Protocol):
    """Read-only inspection + explicit derived rebuild capability."""

    def inspect(self) -> PlayerCampaignStateView: ...

    def rebuild(self) -> PlayerCampaignStateView: ...


# ── Presentation-facing result DTOs ────────────────────────────────────────


class AssistantOutcomeKind(StrEnum):
    """Terminal classification surfaced to the assistant view."""

    RESPOND = "respond"
    CLARIFY = "clarify"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AssistantOutcome:
    """Assistant submission result; safe to render directly."""

    kind: AssistantOutcomeKind
    message: str
    hint: str | None = None


@dataclass(frozen=True, slots=True)
class SessionOutcome:
    """Session operation result; safe to render directly.

    ``active_session`` is the resulting trusted session-presence state when the
    operation determines it (status read, start, note, end); ``None`` leaves the
    cached presentation state unchanged.
    """

    ok: bool
    message: str
    hint: str | None = None
    active_session: bool | None = None


@dataclass(frozen=True, slots=True)
class CampaignStateOutcome:
    """Campaign-State operation result.

    ``view`` carries only the PLAYER-safe projection DTO; ``error_message`` is
    a bounded Russian rendering, never raw internal detail/cause.
    """

    ok: bool
    view: PlayerCampaignStateView | None = None
    error_message: str | None = None


# ── Production capability adapters ─────────────────────────────────────────


class ComposedAssistant:
    """Per-submission ``compose_ask_runtime`` → run → close adapter.

    ``close()`` runs exactly once through ``finally`` for success, expected
    ``DndAssistantError`` and unexpected post-composition exceptions.  If
    composition itself fails before returning, existing ``ExitStack`` semantics
    own partial model cleanup and no runtime is closed here.
    """

    def __init__(self, launch: TuiLaunchContext) -> None:
        self._launch = launch

    def run(self, query: str, *, allow_agent_write: bool) -> AgentTextOutcome:
        if allow_agent_write and not self._launch.allow_agent_write:
            raise ValidationError(
                "Agent WRITE was requested without the launch-time --allow-write ceiling"
            )

        runtime = None
        try:
            runtime = compose_ask_runtime(
                vault_root=self._launch.vault_root,
                config_path=self._launch.config_path,
                profile_name=self._launch.profile_name,
                allow_write=allow_agent_write,
            )
            return runtime.agent_runtime.run(
                query,
                execution_context=runtime.execution_context,
            ).outcome
        finally:
            if runtime is not None:
                runtime.close()


class ComposedSession:
    """Deterministic session capability over the shared composition.

    All mutations are stamped with ``source="tui"`` and unique ``tui-*``
    operation IDs.  Recovery inspection uses the trusted partition unchanged.
    """

    def __init__(self, vault_root: Path) -> None:
        self._vault_root = vault_root

    def recovery_partition(self) -> RecoveryPartition:
        return compose_recovery_service(self._vault_root).inspect_runtime_partition()

    def _audit(self, prefix: str) -> AuditContext:
        return build_audit_context(source="tui", prefix=prefix)

    def status(self) -> Session | None:
        return compose_session_runtime(self._vault_root).get_active_session()

    def start(self) -> Session:
        return compose_session_runtime(self._vault_root).start_session(
            audit=self._audit("tui-session-start")
        )

    def note(self, text: str) -> RawSessionEvent:
        return compose_session_runtime(self._vault_root).record_note(
            text,
            audit=self._audit("tui-note"),
        )

    def end(self, touched_entity_ids: Sequence[EntityId]) -> Session:
        return compose_session_runtime(self._vault_root).end_session(
            touched_entity_ids=tuple(touched_entity_ids),
            audit=self._audit("tui-session-end"),
        )


# ── Bounded launch-services bundle ─────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TuiServices:
    """Immutable launch-services bundle: one capability per named field."""

    launch: TuiLaunchContext
    assistant: AssistantCapability
    session: SessionCapability
    campaign_state: CampaignStateCapabilityProtocol


def build_tui_services(launch: TuiLaunchContext) -> TuiServices:
    """Build the production capability bundle for a launch context."""
    return TuiServices(
        launch=launch,
        assistant=ComposedAssistant(launch),
        session=ComposedSession(launch.vault_root),
        campaign_state=compose_campaign_state_capability(launch.vault_root),
    )
