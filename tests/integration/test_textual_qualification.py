"""TUI-01: Textual 8.2.8 dependency qualification spike (headless).

This module qualifies the exact pinned Textual release against the repository's
trusted architecture. It is a deliberate, self-contained *qualification spike*:
the app below is throwaway-capable and contains no production TUI architecture
(no screens, no navigation, no command registry, no assistant/session/Vault
integration, no write path).

Evidence classes:

- The headless lifecycle, input/focus/Unicode/resize, palette, binding and
  worker results asserted here are ``LOCAL_VERIFIED`` on the development host.
- The dependency/platform metadata backing these tests is ``EXTERNALLY_VERIFIED``
  and is recorded in the TUI track document, not asserted here.

Strategy: Textual's ``App.run_test()`` is an async context manager. The
repository already drives coroutines synchronously (see
``test_pydantic_ai_eval_live_harness.py``) via ``asyncio.run``; this module uses
the same mechanism and therefore requires no async pytest plugin.
"""

from __future__ import annotations

import asyncio
import threading
import time
import warnings
from collections.abc import Coroutine, Iterable
from typing import Any

from textual.app import App, ComposeResult, SystemCommand
from textual.screen import Screen
from textual.widgets import Input, Static, TextArea
from textual.worker import Worker, WorkerCancelled, WorkerFailed, WorkerState, get_current_worker

_CYRILLIC = "Привет"
_WORKER_RETURN = "done"
_WAIT_TIMEOUT = 10.0


class _QualificationApp(App[None]):
    """Minimal qualification app. Never a production TUI shell."""

    BINDINGS = [("b", "spike", "Спайк")]

    def __init__(self) -> None:
        super().__init__()
        self.spike_calls = 0

    def compose(self) -> ComposeResult:
        yield Static("qualification", id="qual-status")
        yield Input(placeholder="запрос", id="qual-input")
        yield TextArea(id="qual-textarea")

    def action_spike(self) -> None:
        """Synthetic semantic effect shared by the binding and the palette."""
        self.spike_calls += 1

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        yield SystemCommand("Спайк команда", "Квалификационная команда", self.action_spike)


def _run(coro: Coroutine[Any, Any, None]) -> None:
    """Drive a Textual coroutine synchronously without an async pytest plugin.

    Python warnings that indicate an unresolved async lifecycle are treated as
    failures. Worker/task/thread termination state is the primary clean-shutdown
    evidence; this warning capture is supplementary.
    """
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


# ── Blocking fakes (thread workers). No UI access, no production side effects. ──


def _blocking_success(
    started: threading.Event, release: threading.Event, calls: list[object]
) -> str:
    calls.append(object())
    started.set()
    release.wait(_WAIT_TIMEOUT)
    return _WORKER_RETURN


def _blocking_error(started: threading.Event, release: threading.Event) -> str:
    started.set()
    release.wait(_WAIT_TIMEOUT)
    raise ValueError("qualification-boom")


def _blocking_cancel(started: threading.Event, exited: threading.Event) -> str:
    started.set()
    worker = get_current_worker()
    while not worker.is_cancelled:
        time.sleep(0.002)
    exited.set()
    return "cancelled"


# ── Minimal application lifecycle ────────────────────────────────────────────


class TestLifecycle:
    def test_construct_mount_start_shutdown(self) -> None:
        async def scenario() -> None:
            app = _QualificationApp()
            async with app.run_test(size=(60, 20)) as pilot:
                assert app.is_running
                assert app.query_one("#qual-status", Static) is not None
                assert app.query_one("#qual-input", Input) is not None
                assert app.query_one("#qual-textarea", TextArea) is not None
                await pilot.pause()
            assert not app.is_running
            # Additional evidence: no worker/thread remains after shutdown.
            assert list(app.workers) == []

        _run(scenario())


# ── Input / focus / Unicode / resize ─────────────────────────────────────────


class TestInputFocusUnicodeResize:
    def test_cyrillic_input_round_trip(self) -> None:
        async def scenario() -> None:
            app = _QualificationApp()
            async with app.run_test(size=(60, 20)) as pilot:
                field = app.query_one("#qual-input", Input)
                field.focus()
                await pilot.pause()
                await pilot.press(*_CYRILLIC)
                await pilot.pause()
                assert field.value == _CYRILLIC

        _run(scenario())

    def test_textarea_cyrillic_multiline(self) -> None:
        async def scenario() -> None:
            app = _QualificationApp()
            async with app.run_test(size=(60, 20)) as pilot:
                area = app.query_one("#qual-textarea", TextArea)
                area.focus()
                await pilot.pause()
                await pilot.press("С", "т", "р", "о", "к", "а", "enter", "Д", "в", "а")
                await pilot.pause()
                assert area.text == "Строка\nДва"

        _run(scenario())

    def test_focused_input_does_not_leak_single_key_binding(self) -> None:
        async def scenario() -> None:
            app = _QualificationApp()
            async with app.run_test(size=(60, 20)) as pilot:
                field = app.query_one("#qual-input", Input)
                field.focus()
                await pilot.pause()
                before = app.spike_calls
                await pilot.press("b")
                await pilot.pause()
                assert app.spike_calls == before, "focused input leaked key into global binding"
                assert "b" in field.value

                app.set_focus(None)
                await pilot.pause()
                await pilot.press("b")
                await pilot.pause()
                assert app.spike_calls == before + 1, "unfocused binding did not fire once"

        _run(scenario())

    def test_deterministic_resize(self) -> None:
        async def scenario() -> None:
            app = _QualificationApp()
            async with app.run_test(size=(40, 12)) as pilot:
                assert (app.size.width, app.size.height) == (40, 12)
                await pilot.resize_terminal(80, 30)
                await pilot.pause()
                assert (app.size.width, app.size.height) == (80, 30)

        _run(scenario())


# ── Bindings and command palette ─────────────────────────────────────────────


class TestBindingsAndPalette:
    def test_ordinary_binding_invokes_action_exactly_once(self) -> None:
        async def scenario() -> None:
            app = _QualificationApp()
            async with app.run_test(size=(60, 20)) as pilot:
                app.set_focus(None)
                await pilot.pause()
                before = app.spike_calls
                await pilot.press("b")
                await pilot.pause()
                assert app.spike_calls == before + 1

        _run(scenario())

    def test_command_palette_reaches_same_semantic_effect(self) -> None:
        async def scenario() -> None:
            app = _QualificationApp()
            async with app.run_test(size=(60, 20)) as pilot:
                before = app.spike_calls
                await pilot.press("ctrl+p")
                await pilot.pause()
                assert type(app.screen).__name__ == "CommandPalette"
                exposed = {command.title for command in app.get_system_commands(app.screen)}
                assert "Спайк команда" in exposed
                await pilot.press("с", "п", "а", "й", "к")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert app.spike_calls == before + 1
                assert type(app.screen).__name__ == "Screen"

        _run(scenario())


# ── Worker / synchronous-runtime hosting ─────────────────────────────────────


class TestWorkers:
    def test_thread_worker_completes_and_loop_stays_responsive(self) -> None:
        async def scenario() -> None:
            app = _QualificationApp()
            async with app.run_test(size=(60, 20)) as pilot:
                started = threading.Event()
                release = threading.Event()
                calls: list[object] = []
                worker: Worker[str] = app.run_worker(
                    lambda: _blocking_success(started, release, calls), thread=True
                )
                assert await asyncio.to_thread(started.wait, _WAIT_TIMEOUT)
                assert worker.state is WorkerState.RUNNING

                # Responsiveness: the event loop processes input while blocked.
                app.set_focus(None)
                await pilot.pause()
                before = app.spike_calls
                await pilot.press("b")
                await pilot.pause()
                assert app.spike_calls == before + 1
                assert worker.state is WorkerState.RUNNING

                release.set()
                result = await worker.wait()
                assert result == _WORKER_RETURN
                assert worker.state is WorkerState.SUCCESS
                assert len(calls) == 1, "callable must run exactly once (no implicit retry)"

        _run(scenario())

    def test_thread_worker_error_is_recoverable(self) -> None:
        async def scenario() -> None:
            app = _QualificationApp()
            async with app.run_test(size=(60, 20)) as pilot:
                started = threading.Event()
                release = threading.Event()
                worker: Worker[str] = app.run_worker(
                    lambda: _blocking_error(started, release),
                    thread=True,
                    exit_on_error=False,
                )
                assert await asyncio.to_thread(started.wait, _WAIT_TIMEOUT)
                release.set()

                raised: BaseException | None = None
                try:
                    await worker.wait()
                except WorkerFailed as exc:
                    raised = exc

                assert isinstance(raised, WorkerFailed)
                assert worker.state is WorkerState.ERROR
                assert isinstance(worker.error, ValueError)

                # Recovery: the app and its ordinary bindings still work.
                app.set_focus(None)
                await pilot.pause()
                before = app.spike_calls
                await pilot.press("b")
                await pilot.pause()
                assert app.spike_calls == before + 1

        _run(scenario())

    def test_thread_worker_cancellation_cooperative_exit_no_retry(self) -> None:
        async def scenario() -> None:
            app = _QualificationApp()
            async with app.run_test(size=(60, 20)) as pilot:
                started = threading.Event()
                exited = threading.Event()
                worker: Worker[str] = app.run_worker(
                    lambda: _blocking_cancel(started, exited),
                    thread=True,
                    exit_on_error=False,
                )
                assert await asyncio.to_thread(started.wait, _WAIT_TIMEOUT)
                worker.cancel()

                raised: BaseException | None = None
                try:
                    await worker.wait()
                except WorkerCancelled as exc:
                    raised = exc

                assert isinstance(raised, WorkerCancelled)
                assert worker.state is WorkerState.CANCELLED
                # A CANCELLED thread may still be running; prove cooperative exit.
                assert await asyncio.to_thread(exited.wait, _WAIT_TIMEOUT), (
                    "cancelled qualification thread did not terminate"
                )
                await pilot.pause()

        _run(scenario())
