"""TUI-03 semantic command model, registry and dispatcher (Textual-free).

These tests exercise the production registry/dispatcher directly with a fake
host, providing literal handler-invocation counters without a Textual app.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest

from dnd_assistant.tui.commands import (
    DEFAULT_COMMANDS,
    DEFAULT_REGISTRY,
    CommandContext,
    CommandHost,
    CommandRegistrationError,
    CommandRegistry,
    CommandScope,
    Handler,
    SemanticCommand,
    scopes_overlap,
)
from dnd_assistant.tui.dispatch import (
    CommandAvailability,
    DispatchResult,
    SemanticDispatcher,
)


class FakeHost:
    """Records the host operations a handler may invoke."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def quit_app(self) -> None:
        self.calls.append("quit")

    def open_command_palette(self) -> None:
        self.calls.append("palette")

    def show_help(self) -> None:
        self.calls.append("help")

    def navigate_to(self, view_id: str) -> None:
        self.calls.append(f"navigate:{view_id}")

    def assistant_submit(self) -> None:
        self.calls.append("assistant.submit")

    def assistant_toggle_write(self) -> None:
        self.calls.append("assistant.toggle-write")

    def session_refresh(self) -> None:
        self.calls.append("session.refresh")

    def session_start(self) -> None:
        self.calls.append("session.start")

    def session_note(self) -> None:
        self.calls.append("session.note")

    def session_end(self) -> None:
        self.calls.append("session.end")

    def campaign_state_reload(self) -> None:
        self.calls.append("campaign-state.reload")

    def campaign_state_rebuild(self) -> None:
        self.calls.append("campaign-state.rebuild")


def _noop(host: CommandHost) -> None:
    _ = host


def _command(
    command_id: str = "app.test",
    *,
    title: str = "Тест",
    description: str = "Описание",
    handler: Handler = _noop,
    scope: CommandScope | None = None,
    default_keys: tuple[str, ...] = (),
    palette: bool = True,
    applicable: Callable[[CommandContext], bool] | None = None,
    enabled: Callable[[CommandContext], bool] | None = None,
) -> SemanticCommand:
    return SemanticCommand(
        id=command_id,
        title=title,
        description=description,
        handler=handler,
        scope=scope if scope is not None else CommandScope.global_(),
        default_keys=default_keys,
        palette=palette,
        applicable=applicable,
        enabled=enabled,
    )


def _dispatcher(
    commands: tuple[SemanticCommand, ...],
    context_id: str = "",
    *,
    host: FakeHost | None = None,
) -> SemanticDispatcher:
    registry = CommandRegistry(commands)
    return SemanticDispatcher(registry, host or FakeHost(), lambda: CommandContext(context_id))


def _default_dispatcher(context: CommandContext) -> SemanticDispatcher:
    return SemanticDispatcher(DEFAULT_REGISTRY, FakeHost(), lambda: context)


# ── Stable ID grammar ────────────────────────────────────────────────────────


class TestCommandIdGrammar:
    @pytest.mark.parametrize(
        "command_id",
        [
            "app.quit",
            "app.command-palette",
            "test.scope-here",
            "a.b.c",
            "x1.y2-z3",
        ],
    )
    def test_valid_ids_accepted(self, command_id: str) -> None:
        registry = CommandRegistry((_command(command_id),))
        assert registry.get(command_id) is not None

    @pytest.mark.parametrize(
        "command_id",
        [
            "",
            "app",
            ".app.quit",
            "app.",
            "app..quit",
            "app_quit",
            "App.quit",
            "-app.quit",
            "app-.quit",
            "app.command--palette",
            "app.Command",
            "app.quit!",
            "app.9quit",
        ],
    )
    def test_invalid_ids_rejected(self, command_id: str) -> None:
        with pytest.raises(CommandRegistrationError):
            CommandRegistry((_command(command_id),))


# ── Registry validation ──────────────────────────────────────────────────────


class TestRegistryValidation:
    def test_duplicate_ids_rejected(self) -> None:
        with pytest.raises(CommandRegistrationError):
            CommandRegistry((_command("app.a"), _command("app.a", title="Другое")))

    def test_empty_title_rejected(self) -> None:
        with pytest.raises(CommandRegistrationError):
            CommandRegistry((_command(title=""),))

    def test_empty_description_rejected(self) -> None:
        with pytest.raises(CommandRegistrationError):
            CommandRegistry((_command(description=""),))

    def test_missing_handler_rejected(self) -> None:
        with pytest.raises(CommandRegistrationError):
            CommandRegistry((_command(handler=cast(Handler, None)),))

    def test_empty_screen_context_rejected(self) -> None:
        with pytest.raises(CommandRegistrationError):
            CommandRegistry((_command(scope=CommandScope(context_id="")),))

    def test_screen_scope_requires_context(self) -> None:
        with pytest.raises(CommandRegistrationError):
            CommandScope.screen("")

    def test_empty_alias_rejected(self) -> None:
        with pytest.raises(CommandRegistrationError):
            CommandRegistry((_command(default_keys=("",)),))

    def test_duplicate_alias_within_command_rejected(self) -> None:
        with pytest.raises(CommandRegistrationError):
            CommandRegistry((_command(default_keys=("x", "x")),))

    def test_overlapping_global_alias_collision_rejected(self) -> None:
        with pytest.raises(CommandRegistrationError):
            CommandRegistry(
                (_command("app.a", default_keys=("x",)), _command("app.b", default_keys=("x",)))
            )

    def test_global_and_screen_alias_collision_rejected(self) -> None:
        commands = (
            _command("app.a", default_keys=("x",)),
            _command("app.b", scope=CommandScope.screen("shell"), default_keys=("x",)),
        )
        with pytest.raises(CommandRegistrationError):
            CommandRegistry(commands)

    def test_non_overlapping_screen_scopes_may_reuse_alias(self) -> None:
        commands = (
            _command("app.a", scope=CommandScope.screen("one"), default_keys=("x",)),
            _command("app.b", scope=CommandScope.screen("two"), default_keys=("x",)),
        )
        registry = CommandRegistry(commands)
        assert len(registry) == 2

    def test_scopes_overlap_helper(self) -> None:
        global_scope = CommandScope.global_()
        one = CommandScope.screen("one")
        two = CommandScope.screen("two")
        assert scopes_overlap(global_scope, one)
        assert scopes_overlap(one, global_scope)
        assert scopes_overlap(one, one)
        assert not scopes_overlap(one, two)


# ── Lookup and ordering ──────────────────────────────────────────────────────


class TestLookupAndOrder:
    def test_lookup_is_deterministic(self) -> None:
        first = _command("app.a")
        second = _command("app.b")
        registry = CommandRegistry((first, second))
        assert registry.get("app.a") is first
        assert registry.get("app.b") is second
        assert registry.get("app.missing") is None
        assert "app.a" in registry
        assert "app.missing" not in registry

    def test_definition_order_preserved(self) -> None:
        first = _command("app.a")
        second = _command("app.b")
        registry = CommandRegistry((second, first))
        assert registry.commands == (second, first)


# ── Dispatcher ───────────────────────────────────────────────────────────────


class TestDispatcher:
    def test_enabled_dispatch_exactly_once(self) -> None:
        calls: list[str] = []

        def handler(host: CommandHost) -> None:
            _ = host
            calls.append("a")

        dispatcher = _dispatcher((_command("app.a", handler=handler),))
        assert dispatcher.dispatch("app.a") is DispatchResult.EXECUTED
        assert calls == ["a"]

    def test_each_dispatch_invokes_handler_once(self) -> None:
        calls: list[str] = []

        def handler(host: CommandHost) -> None:
            _ = host
            calls.append("a")

        dispatcher = _dispatcher((_command("app.a", handler=handler),))
        dispatcher.dispatch("app.a")
        dispatcher.dispatch("app.a")
        assert calls == ["a", "a"]

    def test_unknown_command_executes_zero_handlers(self) -> None:
        calls: list[str] = []

        def handler(host: CommandHost) -> None:
            _ = host
            calls.append("a")

        dispatcher = _dispatcher((_command("app.a", handler=handler),))
        assert dispatcher.dispatch("app.missing") is DispatchResult.UNKNOWN_COMMAND
        assert calls == []

    def test_disabled_command_executes_zero_handlers(self) -> None:
        calls: list[str] = []

        def handler(host: CommandHost) -> None:
            _ = host
            calls.append("a")

        dispatcher = _dispatcher((_command("app.a", handler=handler, enabled=lambda ctx: False),))
        assert dispatcher.evaluate("app.a") is CommandAvailability.DISABLED
        assert dispatcher.dispatch("app.a") is DispatchResult.DISABLED
        assert calls == []

    def test_inapplicable_scope_executes_zero_handlers(self) -> None:
        calls: list[str] = []

        def handler(host: CommandHost) -> None:
            _ = host
            calls.append("a")

        commands = (_command("app.a", handler=handler, scope=CommandScope.screen("other")),)
        dispatcher = _dispatcher(commands, context_id="shell")
        assert dispatcher.evaluate("app.a") is CommandAvailability.INAPPLICABLE
        assert dispatcher.dispatch("app.a") is DispatchResult.INAPPLICABLE
        assert calls == []

    def test_inapplicable_predicate_executes_zero_handlers(self) -> None:
        calls: list[str] = []

        def handler(host: CommandHost) -> None:
            _ = host
            calls.append("a")

        dispatcher = _dispatcher(
            (_command("app.a", handler=handler, applicable=lambda ctx: False),)
        )
        assert dispatcher.dispatch("app.a") is DispatchResult.INAPPLICABLE
        assert calls == []

    def test_scope_context_change_affects_applicability(self) -> None:
        dispatcher = _dispatcher(
            (_command("app.a", scope=CommandScope.screen("shell")),),
            context_id="shell",
        )
        assert dispatcher.evaluate("app.a") is CommandAvailability.ENABLED

    def test_handler_exception_propagates(self) -> None:
        def handler(host: CommandHost) -> None:
            _ = host
            raise RuntimeError("boom")

        dispatcher = _dispatcher((_command("app.a", handler=handler),))
        with pytest.raises(RuntimeError, match="boom"):
            dispatcher.dispatch("app.a")


# ── Palette eligibility ──────────────────────────────────────────────────────


class TestPaletteEligibility:
    def _titles(self, dispatcher: SemanticDispatcher, context_id: str) -> list[str]:
        context = CommandContext(context_id)
        return [command.title for command in dispatcher.palette_commands(context)]

    def test_palette_false_omitted(self) -> None:
        dispatcher = _dispatcher((_command("app.a", title="Скрытая", palette=False),))
        assert self._titles(dispatcher, "") == []

    def test_disabled_omitted(self) -> None:
        dispatcher = _dispatcher(
            (_command("app.a", title="Выключенная", enabled=lambda ctx: False),)
        )
        assert self._titles(dispatcher, "") == []

    def test_inapplicable_omitted(self) -> None:
        commands = (_command("app.a", title="Другая", scope=CommandScope.screen("other")),)
        dispatcher = _dispatcher(commands, context_id="shell")
        assert self._titles(dispatcher, "shell") == []

    def test_enabled_applicable_included(self) -> None:
        dispatcher = _dispatcher((_command("app.a", title="Доступная"),))
        assert self._titles(dispatcher, "") == ["Доступная"]


# ── Production inventory ─────────────────────────────────────────────────────


class TestDefaultInventory:
    EXPECTED_IDS = {
        "app.quit",
        "app.command-palette",
        "app.help",
        "view.assistant",
        "view.session",
        "assistant.submit",
        "assistant.toggle-write",
        "session.refresh",
        "session.start",
        "session.note",
        "session.end",
        "campaign-state.reload",
        "campaign-state.rebuild",
    }

    def test_ids_titles_and_keys(self) -> None:
        inventory = {command.id: command for command in DEFAULT_COMMANDS}
        assert set(inventory) == self.EXPECTED_IDS
        assert inventory["app.quit"].default_keys == ("ctrl+q",)
        assert inventory["app.command-palette"].default_keys == ("ctrl+p",)
        assert inventory["app.command-palette"].palette is False
        assert inventory["app.help"].default_keys == ("?", "f1")
        assert inventory["view.assistant"].default_keys == ("f2", "escape")
        assert inventory["view.session"].default_keys == ("f3",)
        assert inventory["assistant.submit"].default_keys == ("ctrl+enter", "f5")
        assert "view.campaign-state" not in inventory
        assert DEFAULT_REGISTRY.get("app.help") is inventory["app.help"]

    def test_view_commands_are_scoped(self) -> None:
        inventory = {command.id: command for command in DEFAULT_COMMANDS}
        assert inventory["view.assistant"].scope.context_id is None
        assert inventory["view.session"].scope.context_id == "assistant"
        assert inventory["assistant.submit"].scope.context_id == "assistant"
        assert inventory["assistant.toggle-write"].scope.context_id == "assistant"
        assert inventory["session.start"].scope.context_id == "session"
        assert inventory["session.note"].scope.context_id == "session"
        assert inventory["session.end"].scope.context_id == "session"
        assert inventory["campaign-state.reload"].scope.context_id == "assistant"
        assert inventory["campaign-state.rebuild"].scope.context_id == "assistant"

    def test_handlers_invoke_host_operations(self) -> None:
        host = FakeHost()
        for command in DEFAULT_COMMANDS:
            command.handler(host)
        assert host.calls == [
            "quit",
            "palette",
            "help",
            "navigate:assistant",
            "navigate:session",
            "assistant.submit",
            "assistant.toggle-write",
            "session.refresh",
            "session.start",
            "session.note",
            "session.end",
            "campaign-state.reload",
            "campaign-state.rebuild",
        ]


class TestBusyPredicates:
    def _dispatcher_for(self, *command_ids: str, context: CommandContext) -> SemanticDispatcher:
        registry = CommandRegistry(
            tuple(command for command in DEFAULT_COMMANDS if command.id in command_ids)
        )
        return SemanticDispatcher(registry, FakeHost(), lambda: context)

    def test_exclusive_commands_cannot_execute_while_busy(self) -> None:
        session_context = CommandContext(
            context_id="session",
            busy_owner="assistant",
            has_active_session=True,
        )
        session_dispatcher = self._dispatcher_for(
            "session.start",
            "session.note",
            "session.end",
            context=session_context,
        )
        for command_id in ("session.note", "session.end"):
            assert session_dispatcher.evaluate(command_id) is CommandAvailability.DISABLED
            assert session_dispatcher.dispatch(command_id) is DispatchResult.DISABLED
        # session.start is inapplicable while a session is active; either way it
        # must not execute while the gate is held.
        assert session_dispatcher.dispatch("session.start") is not DispatchResult.EXECUTED

        for command_id, context_id in (
            ("assistant.submit", "assistant"),
            ("campaign-state.rebuild", "assistant"),
        ):
            context = CommandContext(context_id=context_id, busy_owner="assistant")
            dispatcher = self._dispatcher_for(command_id, context=context)
            assert dispatcher.evaluate(command_id) is CommandAvailability.DISABLED
            assert dispatcher.dispatch(command_id) is DispatchResult.DISABLED

    def test_session_status_refresh_available_while_busy(self) -> None:
        context = CommandContext(context_id="session", busy_owner="assistant")
        dispatcher = self._dispatcher_for("session.refresh", context=context)
        assert dispatcher.evaluate("session.refresh") is CommandAvailability.ENABLED

    def test_campaign_state_reload_disabled_while_busy(self) -> None:
        context = CommandContext(context_id="assistant", busy_owner="assistant")
        dispatcher = self._dispatcher_for("campaign-state.reload", context=context)
        assert dispatcher.evaluate("campaign-state.reload") is CommandAvailability.DISABLED
        assert dispatcher.dispatch("campaign-state.reload") is DispatchResult.DISABLED

    def test_campaign_state_commands_not_offered_from_session_context(self) -> None:
        """Sidebar commands belong to the main workspace, not the session screen."""
        context = CommandContext(context_id="session")
        dispatcher = self._dispatcher_for(
            "campaign-state.reload",
            "campaign-state.rebuild",
            "view.session",
            "assistant.submit",
            context=context,
        )
        for command_id in (
            "campaign-state.reload",
            "campaign-state.rebuild",
            "view.session",
            "assistant.submit",
        ):
            assert dispatcher.evaluate(command_id) is CommandAvailability.INAPPLICABLE
            assert dispatcher.dispatch(command_id) is DispatchResult.INAPPLICABLE

    def test_view_commands_are_idempotent_by_context(self) -> None:
        """`view.assistant` is offered from the session context; `view.session` is not."""
        session_dispatcher = _default_dispatcher(CommandContext(context_id="session"))
        assert session_dispatcher.evaluate("view.assistant") is CommandAvailability.ENABLED
        assert session_dispatcher.evaluate("view.session") is CommandAvailability.INAPPLICABLE
        assistant_dispatcher = _default_dispatcher(CommandContext(context_id="assistant"))
        assert assistant_dispatcher.evaluate("view.assistant") is CommandAvailability.ENABLED
        assert assistant_dispatcher.evaluate("view.session") is CommandAvailability.ENABLED

    def test_session_mutation_in_flight_blocks_assistant(self) -> None:
        context = CommandContext(context_id="assistant", busy_owner="session")
        dispatcher = self._dispatcher_for("assistant.submit", context=context)
        assert dispatcher.evaluate("assistant.submit") is CommandAvailability.DISABLED

    def test_write_toggle_inapplicable_without_ceiling(self) -> None:
        context = CommandContext(context_id="assistant", write_intent_available=False)
        dispatcher = self._dispatcher_for("assistant.toggle-write", context=context)
        assert dispatcher.evaluate("assistant.toggle-write") is (CommandAvailability.INAPPLICABLE)

    def test_write_toggle_applicable_with_ceiling(self) -> None:
        context = CommandContext(context_id="assistant", write_intent_available=True)
        dispatcher = self._dispatcher_for("assistant.toggle-write", context=context)
        assert dispatcher.evaluate("assistant.toggle-write") is CommandAvailability.ENABLED

    def test_session_applicability_tracks_active_session(self) -> None:
        no_session = self._dispatcher_for(
            "session.start", "session.note", context=CommandContext(context_id="session")
        )
        assert no_session.evaluate("session.start") is CommandAvailability.ENABLED
        assert no_session.evaluate("session.note") is CommandAvailability.INAPPLICABLE

        active = self._dispatcher_for(
            "session.start",
            "session.note",
            context=CommandContext(context_id="session", has_active_session=True),
        )
        assert active.evaluate("session.start") is CommandAvailability.INAPPLICABLE
        assert active.evaluate("session.note") is CommandAvailability.ENABLED
