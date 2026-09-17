"""TUI-03 production shell headless integration tests (Textual 8.2.8).

Uses the production app, registry, dispatcher, binding adapter and palette
adapter. Test-only screens/registries isolate focus and scope conditions; no
production campaign screens or capabilities are introduced.

Textual's ``App.run_test()`` is driven synchronously via ``asyncio.run``,
matching the repository idiom; no async pytest plugin is used.
"""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Coroutine
from typing import Any, ClassVar

import pytest
from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Static, TextArea

from dnd_assistant.tui.app import DEFAULT_BINDINGS, DndTuiApp
from dnd_assistant.tui.bindings import CommandBindingError, build_bindings, semantic_action
from dnd_assistant.tui.commands import (
    DEFAULT_REGISTRY,
    CommandHost,
    CommandRegistry,
    CommandScope,
    SemanticCommand,
)
from dnd_assistant.tui.dispatch import CommandAvailability, DispatchResult
from dnd_assistant.tui.screens import ShellScreen

_CYRILLIC = "Привет"


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


def _noop(host: CommandHost) -> None:
    _ = host


def _help_handler(host: CommandHost) -> None:
    host.show_help()


def _quit_handler(host: CommandHost) -> None:
    host.quit_app()


def _palette_handler(host: CommandHost) -> None:
    host.open_command_palette()


# ── Test-only registry / screens (no fake campaign semantics) ──────────────────

_TEST_COMMANDS: tuple[SemanticCommand, ...] = (
    SemanticCommand(
        id="app.quit",
        title="Выход",
        description="Закрыть приложение",
        handler=_quit_handler,
        default_keys=("ctrl+q",),
    ),
    SemanticCommand(
        id="app.command-palette",
        title="Палитра команд",
        description="Открыть палитру команд",
        handler=_palette_handler,
        default_keys=("ctrl+p",),
        palette=False,
    ),
    SemanticCommand(
        id="test.alpha",
        title="Тестальфа",
        description="Альфа-команда",
        handler=_help_handler,
        default_keys=("z",),
    ),
    SemanticCommand(
        id="test.disabled",
        title="Тестдисейбл",
        description="Выключенная команда",
        handler=_quit_handler,
        enabled=lambda ctx: False,
    ),
    SemanticCommand(
        id="test.hidden",
        title="Тестскрыт",
        description="Скрытая команда",
        handler=_quit_handler,
        palette=False,
    ),
    SemanticCommand(
        id="test.here",
        title="Тестздесь",
        description="Команда текущего контекста",
        handler=_quit_handler,
        scope=CommandScope.screen("testscreen"),
        default_keys=("x",),
    ),
    SemanticCommand(
        id="test.elsewhere",
        title="Тестдругой",
        description="Команда другого контекста",
        handler=_quit_handler,
        scope=CommandScope.screen("other"),
        default_keys=("x",),
    ),
    SemanticCommand(
        id="test.missing",
        title="Тестнет",
        description="Недоступная команда",
        handler=_quit_handler,
        applicable=lambda ctx: False,
    ),
)
TEST_REGISTRY = CommandRegistry(_TEST_COMMANDS)


class _TestScreen(Screen[None]):
    CONTEXT_ID: ClassVar[str] = "testscreen"

    def compose(self):
        yield Static("test", id="test-body")
        yield Footer()


class _TestApp(DndTuiApp):
    SEMANTIC_REGISTRY: ClassVar[CommandRegistry] = TEST_REGISTRY
    BINDINGS: ClassVar[list[BindingType]] = list(build_bindings(TEST_REGISTRY))
    DEFAULT_SCREEN: ClassVar[type[Screen[None]]] = _TestScreen

    def __init__(self) -> None:
        super().__init__(registry=TEST_REGISTRY)
        self.recorded: list[str] = []

    def quit_app(self) -> None:
        self.recorded.append("quit")

    def open_command_palette(self) -> None:
        self.recorded.append("palette")
        super().open_command_palette()

    def show_help(self) -> None:
        self.recorded.append("help")


class _FocusScreen(Screen[None]):
    CONTEXT_ID: ClassVar[str] = "focus"

    def compose(self):
        yield Input(id="focus-input")
        yield TextArea(id="focus-area")
        yield Footer()


class _FocusApp(DndTuiApp):
    SEMANTIC_REGISTRY: ClassVar[CommandRegistry] = DEFAULT_REGISTRY
    BINDINGS: ClassVar[list[BindingType]] = list(build_bindings(DEFAULT_REGISTRY))
    DEFAULT_SCREEN: ClassVar[type[Screen[None]]] = _FocusScreen

    def __init__(self) -> None:
        super().__init__()
        self.help_calls = 0

    def show_help(self) -> None:
        self.help_calls += 1


# ── Production shell lifecycle / discoverability ─────────────────────────────


class TestProductionShell:
    def test_mount_widgets_and_clean_shutdown(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp()
            async with app.run_test(size=(80, 24)):
                assert app.is_running
                assert isinstance(app.screen, ShellScreen)
                assert app.query_one(Header) is not None
                assert app.query_one(Footer) is not None
                assert app.query_one("#shell-body", Static) is not None
            assert not app.is_running
            assert list(app.workers) == []

        _run(scenario())

    def test_footer_metadata_derives_from_registry(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp()
            async with app.run_test(size=(80, 24)):
                palette_command = DEFAULT_REGISTRY.get("app.command-palette")
                assert palette_command is not None
                active = app.active_bindings
                assert active["ctrl+p"].binding.description == palette_command.title
                assert active["question_mark"].binding.description == "Справка"
                ids = {binding.binding.id for binding in active.values()}
                assert {"app.quit", "app.command-palette", "app.help"} <= ids

        _run(scenario())

    def test_no_priority_printable_binding_in_production(self) -> None:
        for binding in DEFAULT_BINDINGS:
            assert isinstance(binding, Binding)
            assert binding.priority is False

        async def scenario() -> None:
            app = DndTuiApp()
            async with app.run_test(size=(80, 24)):
                for active in app.active_bindings.values():
                    key = active.binding.key
                    if active.binding.priority and len(key) == 1:
                        pytest.fail(f"priority printable single-key binding: {key!r}")

        _run(scenario())


# ── Binding → semantic ID → dispatcher → handler ─────────────────────────────


class TestBindingDispatch:
    def test_hotkey_dispatches_exactly_once_per_press(self) -> None:
        async def scenario() -> None:
            app = _TestApp()
            async with app.run_test(size=(80, 24)) as pilot:
                app.set_focus(None)
                await pilot.pause()
                await pilot.press("z")
                await pilot.pause()
                assert app.recorded == ["help"]
                await pilot.press("z")
                await pilot.pause()
                assert app.recorded == ["help", "help"]

        _run(scenario())

    def test_context_scoped_hotkey_dispatches_in_matching_context(self) -> None:
        async def scenario() -> None:
            app = _TestApp()
            async with app.run_test(size=(80, 24)) as pilot:
                app.set_focus(None)
                await pilot.pause()
                await pilot.press("x")
                await pilot.pause()
                assert app.recorded == ["quit"]

        _run(scenario())

    def test_unknown_disabled_inapplicable_execute_zero_handlers(self) -> None:
        async def scenario() -> None:
            app = _TestApp()
            async with app.run_test(size=(80, 24)):
                assert app.run_semantic_command("no.such.command") is (
                    DispatchResult.UNKNOWN_COMMAND
                )
                assert app.run_semantic_command("test.disabled") is DispatchResult.DISABLED
                assert app.run_semantic_command("test.elsewhere") is (DispatchResult.INAPPLICABLE)
                assert app.run_semantic_command("test.missing") is DispatchResult.INAPPLICABLE
                assert app.recorded == []
                assert app._dispatcher.evaluate("test.disabled") is (CommandAvailability.DISABLED)

        _run(scenario())


# ── Palette ──────────────────────────────────────────────────────────────────


class TestPaletteAccess:
    def test_ctrl_p_opens_palette_exactly_once(self) -> None:
        async def scenario() -> None:
            app = _TestApp()
            async with app.run_test(size=(80, 24)) as pilot:
                app.set_focus(None)
                await pilot.pause()
                await pilot.press("ctrl+p")
                await pilot.pause()
                assert app.recorded == ["palette"]
                assert type(app.screen).__name__ == "CommandPalette"

        _run(scenario())

    def test_palette_metadata_and_exclusions(self) -> None:
        async def scenario() -> None:
            app = _TestApp()
            async with app.run_test(size=(80, 24)):
                shell_screen = app.screen
                titles = {command.title for command in app.get_system_commands(shell_screen)}
                assert "Тестальфа" in titles
                assert "Тестздесь" in titles
                assert "Тестдисейбл" not in titles
                assert "Тестскрыт" not in titles
                assert "Тестдругой" not in titles
                assert "Тестнет" not in titles

        _run(scenario())

    def test_palette_selection_reaches_same_dispatcher_once(self) -> None:
        async def scenario() -> None:
            app = _TestApp()
            async with app.run_test(size=(80, 24)) as pilot:
                app.set_focus(None)
                await pilot.pause()
                app.open_command_palette()
                await pilot.pause()
                assert app.recorded == ["palette"]
                assert type(app.screen).__name__ == "CommandPalette"
                await pilot.press(*"альфа")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert app.recorded == ["palette", "help"]
                assert type(app.screen).__name__ != "CommandPalette"

        _run(scenario())


# ── Binding adapter ──────────────────────────────────────────────────────────


class TestBindingAdapter:
    def test_semantic_action_string(self) -> None:
        assert semantic_action("app.quit") == "semantic_dispatch('app.quit')"

    def test_all_generated_bindings_non_priority(self) -> None:
        for binding in build_bindings(DEFAULT_REGISTRY):
            assert binding.priority is False

    def test_effective_alias_collision_rejected(self) -> None:
        registry = CommandRegistry(
            (
                SemanticCommand(
                    id="test.a",
                    title="А",
                    description="А",
                    handler=_noop,
                    default_keys=("?",),
                ),
                SemanticCommand(
                    id="test.b",
                    title="Б",
                    description="Б",
                    handler=_noop,
                    default_keys=("question_mark",),
                ),
            )
        )
        with pytest.raises(CommandBindingError):
            build_bindings(registry)

    def test_non_overlapping_contexts_may_reuse_effective_key(self) -> None:
        registry = CommandRegistry(
            (
                SemanticCommand(
                    id="test.a",
                    title="А",
                    description="А",
                    handler=_noop,
                    scope=CommandScope.screen("one"),
                    default_keys=("question_mark",),
                ),
                SemanticCommand(
                    id="test.b",
                    title="Б",
                    description="Б",
                    handler=_noop,
                    scope=CommandScope.screen("two"),
                    default_keys=("?",),
                ),
            )
        )
        bindings = build_bindings(registry)
        assert {binding.id for binding in bindings} == {"test.a", "test.b"}


# ── Focus safety ─────────────────────────────────────────────────────────────


class TestFocusSafety:
    def test_focused_input_consumes_printable_global_key(self) -> None:
        async def scenario() -> None:
            app = _FocusApp()
            async with app.run_test(size=(80, 24)) as pilot:
                field = app.query_one("#focus-input", Input)
                field.focus()
                await pilot.pause()
                await pilot.press("?")
                await pilot.pause()
                assert app.help_calls == 0, "focused input leaked key into global binding"
                assert "?" in field.value

                app.set_focus(None)
                await pilot.pause()
                await pilot.press("?")
                await pilot.pause()
                assert app.help_calls == 1

        _run(scenario())

    def test_focused_text_area_consumes_printable_global_key_and_cyrillic(self) -> None:
        async def scenario() -> None:
            app = _FocusApp()
            async with app.run_test(size=(80, 24)) as pilot:
                area = app.query_one("#focus-area", TextArea)
                area.focus()
                await pilot.pause()
                await pilot.press(*_CYRILLIC, "?")
                await pilot.pause()
                assert app.help_calls == 0, "focused text area leaked key into global binding"
                assert area.text == f"{_CYRILLIC}?"

                app.set_focus(None)
                await pilot.pause()
                await pilot.press("?")
                await pilot.pause()
                assert app.help_calls == 1

        _run(scenario())


# ── Scope ────────────────────────────────────────────────────────────────────


class TestContextScope:
    def test_here_scope_applicable_elsewhere_not(self) -> None:
        async def scenario() -> None:
            app = _TestApp()
            async with app.run_test(size=(80, 24)):
                assert app._dispatcher.evaluate("test.here") is CommandAvailability.ENABLED
                assert app._dispatcher.evaluate("test.elsewhere") is (
                    CommandAvailability.INAPPLICABLE
                )

        _run(scenario())
