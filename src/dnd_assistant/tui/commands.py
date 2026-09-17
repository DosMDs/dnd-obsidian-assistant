r"""Semantic command model and registry (TUI-03).

This module is deliberately **Textual-free**. Physical keys are replaceable
aliases for stable semantic command IDs; the registry is the single authority
that feeds bindings, the command palette, footer hints and future context
actions.

Presentation vs authorization
-----------------------------

``SemanticCommand.applicable`` and ``SemanticCommand.enabled`` are
**presentation predicates only**. They decide whether an action is currently
worth offering in the UI. They are never an authorization boundary: a future
write-capable TUI action must still flow through the trusted path
(``ToolExecutor`` / ChangeSet review/revision checks / audit /
``VaultRepository``) regardless of these predicates.

Stable command ID grammar
-------------------------

::

    segment := [a-z][a-z0-9]*(?:-[a-z0-9]+)*
    id      := segment(?:\.segment)+

Rejected examples include ``-app.quit``, ``app-.quit``, ``app..quit``,
``app.command--palette``, ``App.quit`` and ``app_quit``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = [
    "CommandContext",
    "CommandHost",
    "CommandRegistrationError",
    "CommandRegistry",
    "CommandScope",
    "DEFAULT_COMMANDS",
    "DEFAULT_REGISTRY",
    "Handler",
    "SemanticCommand",
    "default_commands",
    "scopes_overlap",
]

# ── Stable command-ID grammar ────────────────────────────────────────────────

_ID_SEGMENT = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*"
_ID_RE = re.compile(rf"^{_ID_SEGMENT}(?:\.{_ID_SEGMENT})+$")


class CommandRegistrationError(ValueError):
    """Raised when a semantic command registry is invalid (fail fast)."""


# ── Scope and context ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CommandScope:
    """Structural presentation scope of a command.

    ``context_id is None`` means the command is global. A non-``None`` value
    names the screen/context in which the command is applicable. This is a
    presentation concern, never authorization.
    """

    context_id: str | None = None

    @classmethod
    def global_(cls) -> CommandScope:
        """Return the global scope."""
        return cls(None)

    @classmethod
    def screen(cls, context_id: str) -> CommandScope:
        """Return a screen/context scope for a non-empty context id."""
        if not isinstance(context_id, str) or not context_id:
            raise CommandRegistrationError("screen scope requires a non-empty context id")
        return cls(context_id)


@dataclass(frozen=True, slots=True)
class CommandContext:
    """Read-only presentation context passed to predicates.

    ``context_id`` is the active screen/pane context id (empty string when a
    screen declares none).  The remaining fields are **cached presentation
    state** used only to decide whether an action is currently worth offering:

    - ``busy_owner`` is the current exclusive in-flight owner (or ``None``);
    - ``has_active_session`` mirrors the last trusted session read;
    - ``write_intent_available`` is whether the launch-time agent-WRITE ceiling
      permits the assistant mode toggle.

    None of these fields is authorization.
    """

    context_id: str = ""
    busy_owner: str | None = None
    has_active_session: bool = False
    write_intent_available: bool = False


def scopes_overlap(left: CommandScope, right: CommandScope) -> bool:
    """Return whether two scopes can be simultaneously active.

    A global scope overlaps every other scope. Two screen scopes overlap only
    when they name the same context.
    """
    if left.context_id is None or right.context_id is None:
        return True
    return left.context_id == right.context_id


# ── Command metadata ─────────────────────────────────────────────────────────


@runtime_checkable
class CommandHost(Protocol):
    """Host operations a semantic command handler may invoke.

    The host is the presentation app. Handlers receive it explicitly so the
    semantic model stays framework-free and unit-testable with a fake host.
    Each domain-facing host method is a thin dispatch delegation; capability
    work lives in the capability view/presenter objects.
    """

    def quit_app(self) -> None:
        """Request application shutdown."""

    def open_command_palette(self) -> None:
        """Open the command palette."""

    def show_help(self) -> None:
        """Show the key/help panel."""

    def navigate_to(self, view_id: str) -> None:
        """Switch the primary view by stable view id."""

    def assistant_submit(self) -> None:
        """Submit the current assistant query."""

    def assistant_toggle_write(self) -> None:
        """Toggle the per-request assistant WRITE intent."""

    def session_refresh(self) -> None:
        """Refresh the session status display."""

    def session_start(self) -> None:
        """Start a session."""

    def session_note(self) -> None:
        """Record the note text from the session view."""

    def session_end(self) -> None:
        """End the active session."""

    def campaign_state_reload(self) -> None:
        """Re-inspect the Campaign-State display."""

    def campaign_state_rebuild(self) -> None:
        """Explicitly rebuild (ensure-current) the derived Campaign-State."""


Handler = Callable[[CommandHost], None]


@dataclass(frozen=True, slots=True)
class SemanticCommand:
    """One stable semantic command.

    Fields are presentation metadata plus a handler. There is intentionally no
    authorization/policy field.
    """

    id: str
    title: str
    description: str
    handler: Handler
    scope: CommandScope = field(default_factory=CommandScope.global_)
    default_keys: tuple[str, ...] = ()
    palette: bool = True
    applicable: Callable[[CommandContext], bool] | None = None
    enabled: Callable[[CommandContext], bool] | None = None


# ── Registry validation ──────────────────────────────────────────────────────


def _validate_command(command: SemanticCommand) -> None:
    if not isinstance(command.id, str) or not _ID_RE.match(command.id):
        raise CommandRegistrationError(
            f"invalid semantic command id: {command.id!r} "
            "(expected segment(?:.segment)+ with segments [a-z][a-z0-9]*(?:-[a-z0-9]+)*)"
        )
    if not command.title:
        raise CommandRegistrationError(f"command {command.id!r} has an empty title")
    if not command.description:
        raise CommandRegistrationError(f"command {command.id!r} has an empty description")
    if not callable(command.handler):
        raise CommandRegistrationError(f"command {command.id!r} has no callable handler")
    if command.scope.context_id is not None and not command.scope.context_id:
        raise CommandRegistrationError(f"command {command.id!r} has an empty screen context id")

    seen_aliases: set[str] = set()
    for alias in command.default_keys:
        if not isinstance(alias, str) or not alias:
            raise CommandRegistrationError(f"command {command.id!r} has an empty key alias")
        if alias in seen_aliases:
            raise CommandRegistrationError(f"command {command.id!r} repeats key alias {alias!r}")
        seen_aliases.add(alias)


def _validate_registry(commands: tuple[SemanticCommand, ...]) -> None:
    seen_ids: set[str] = set()
    alias_owners: dict[str, list[SemanticCommand]] = {}

    for command in commands:
        _validate_command(command)
        if command.id in seen_ids:
            raise CommandRegistrationError(f"duplicate semantic command id: {command.id!r}")
        seen_ids.add(command.id)

        for alias in command.default_keys:
            for other in alias_owners.get(alias, ()):
                if scopes_overlap(command.scope, other.scope):
                    raise CommandRegistrationError(
                        f"key alias {alias!r} is shared by overlapping commands "
                        f"{other.id!r} and {command.id!r}"
                    )
            alias_owners.setdefault(alias, []).append(command)


class CommandRegistry:
    """Validated, ordered, immutable semantic command registry."""

    def __init__(self, commands: Iterable[SemanticCommand]) -> None:
        ordered = tuple(commands)
        _validate_registry(ordered)
        self._commands = ordered
        self._by_id = {command.id: command for command in ordered}

    @property
    def commands(self) -> tuple[SemanticCommand, ...]:
        """Commands in deterministic definition order."""
        return self._commands

    def get(self, command_id: str) -> SemanticCommand | None:
        """Look up a command by stable id, or ``None`` when unknown."""
        return self._by_id.get(command_id)

    def __contains__(self, command_id: object) -> bool:
        return command_id in self._by_id

    def __len__(self) -> int:
        return len(self._commands)


# ── Production command inventory ─────────────────────────────────────────────


def _quit(host: CommandHost) -> None:
    host.quit_app()


def _open_palette(host: CommandHost) -> None:
    host.open_command_palette()


def _help(host: CommandHost) -> None:
    host.show_help()


def _view_assistant(host: CommandHost) -> None:
    host.navigate_to("assistant")


def _view_session(host: CommandHost) -> None:
    host.navigate_to("session")


def _view_campaign_state(host: CommandHost) -> None:
    host.navigate_to("campaign-state")


def _assistant_submit(host: CommandHost) -> None:
    host.assistant_submit()


def _assistant_toggle_write(host: CommandHost) -> None:
    host.assistant_toggle_write()


def _session_refresh(host: CommandHost) -> None:
    host.session_refresh()


def _session_start(host: CommandHost) -> None:
    host.session_start()


def _session_note(host: CommandHost) -> None:
    host.session_note()


def _session_end(host: CommandHost) -> None:
    host.session_end()


def _campaign_state_reload(host: CommandHost) -> None:
    host.campaign_state_reload()


def _campaign_state_rebuild(host: CommandHost) -> None:
    host.campaign_state_rebuild()


def _idle(context: CommandContext) -> bool:
    """Presentation predicate: no exclusive operation in flight."""
    return context.busy_owner is None


def _has_active_session(context: CommandContext) -> bool:
    return context.has_active_session


def _no_active_session(context: CommandContext) -> bool:
    return not context.has_active_session


def default_commands() -> tuple[SemanticCommand, ...]:
    """Return the production TUI command inventory (TUI-03 shell + TUI-04)."""
    return (
        SemanticCommand(
            id="app.quit",
            title="Выход",
            description="Закрыть приложение",
            handler=_quit,
            default_keys=("ctrl+q",),
            enabled=_idle,
        ),
        SemanticCommand(
            id="app.command-palette",
            title="Палитра команд",
            description="Открыть палитру команд",
            handler=_open_palette,
            default_keys=("ctrl+p",),
            palette=False,
        ),
        SemanticCommand(
            id="app.help",
            title="Справка",
            description="Показать справку и сочетания клавиш",
            handler=_help,
            default_keys=("?", "f1"),
        ),
        SemanticCommand(
            id="view.assistant",
            title="Ассистент",
            description="Переключиться на вкладку ассистента",
            handler=_view_assistant,
            default_keys=("f2",),
        ),
        SemanticCommand(
            id="view.session",
            title="Сессия",
            description="Переключиться на вкладку сессии",
            handler=_view_session,
            default_keys=("f3",),
        ),
        SemanticCommand(
            id="view.campaign-state",
            title="Состояние кампании",
            description="Переключиться на вкладку состояния кампании",
            handler=_view_campaign_state,
            default_keys=("f4",),
        ),
        SemanticCommand(
            id="assistant.submit",
            title="Отправить запрос",
            description="Отправить текущий запрос ассистенту",
            handler=_assistant_submit,
            scope=CommandScope.screen("assistant"),
            default_keys=("f5",),
            enabled=_idle,
        ),
        SemanticCommand(
            id="assistant.toggle-write",
            title="Режим записи ассистента",
            description="Переключить разрешение записи для следующего запроса",
            handler=_assistant_toggle_write,
            scope=CommandScope.screen("assistant"),
            applicable=lambda context: context.write_intent_available,
            enabled=_idle,
        ),
        SemanticCommand(
            id="session.refresh",
            title="Обновить статус сессии",
            description="Прочитать текущий статус сессии",
            handler=_session_refresh,
            scope=CommandScope.screen("session"),
        ),
        SemanticCommand(
            id="session.start",
            title="Начать сессию",
            description="Начать новую игровую сессию",
            handler=_session_start,
            scope=CommandScope.screen("session"),
            applicable=_no_active_session,
            enabled=_idle,
        ),
        SemanticCommand(
            id="session.note",
            title="Добавить заметку",
            description="Добавить заметку в активную сессию",
            handler=_session_note,
            scope=CommandScope.screen("session"),
            applicable=_has_active_session,
            enabled=_idle,
        ),
        SemanticCommand(
            id="session.end",
            title="Завершить сессию",
            description="Завершить активную сессию",
            handler=_session_end,
            scope=CommandScope.screen("session"),
            applicable=_has_active_session,
            enabled=_idle,
        ),
        SemanticCommand(
            id="campaign-state.reload",
            title="Обновить отображение",
            description="Повторно проверить состояние кампании",
            handler=_campaign_state_reload,
            scope=CommandScope.screen("campaign-state"),
            enabled=_idle,
        ),
        SemanticCommand(
            id="campaign-state.rebuild",
            title="Перестроить состояние",
            description="Перестроить производное состояние кампании",
            handler=_campaign_state_rebuild,
            scope=CommandScope.screen("campaign-state"),
            enabled=_idle,
        ),
    )


DEFAULT_COMMANDS: tuple[SemanticCommand, ...] = default_commands()
DEFAULT_REGISTRY = CommandRegistry(DEFAULT_COMMANDS)
