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
    def test_ids_titles_and_keys(self) -> None:
        inventory = {command.id: command for command in DEFAULT_COMMANDS}
        assert set(inventory) == {"app.quit", "app.command-palette", "app.help"}
        assert inventory["app.quit"].default_keys == ("ctrl+q",)
        assert inventory["app.command-palette"].default_keys == ("ctrl+p",)
        assert inventory["app.command-palette"].palette is False
        assert inventory["app.help"].default_keys == ("?", "f1")
        assert DEFAULT_REGISTRY.get("app.help") is inventory["app.help"]

    def test_handlers_invoke_host_operations(self) -> None:
        host = FakeHost()
        for command in DEFAULT_COMMANDS:
            command.handler(host)
        assert host.calls == ["quit", "palette", "help"]
