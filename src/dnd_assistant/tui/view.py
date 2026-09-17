"""Shared capability-view base for worker hosting and the in-flight gate (TUI-04).

Worker callables perform synchronous trusted capability work and return plain
result DTOs.  They never touch Textual UI: all widget/reactive updates happen
on the Textual event loop inside ``on_worker_state_changed``.

Expected ``DndAssistantError`` is converted inside the worker wrapper (view
specific) into an error result DTO.  Any unexpected exception escapes the
worker and is re-raised here on the event loop, so it stays observable and
test-failing instead of being silently swallowed.

``exit_on_error=False`` is used so an unexpected worker exception does not
terminate the app mid-way; the exception is not discarded -- it is re-raised
from the state handler.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from textual.widget import Widget
from textual.worker import Worker, WorkerState

from dnd_assistant.tui.dispatch import DispatchResult
from dnd_assistant.tui.inflight import InFlightGate
from dnd_assistant.tui.services import TuiLaunchContext

__all__ = ["CapabilityView", "TuiHost"]


@runtime_checkable
class TuiHost(Protocol):
    """Narrow host surface a capability view needs from the app.

    This is a view-facing adapter protocol, not a service locator: it exposes
    only exclusivity, command-state refresh, notification, semantic dispatch
    and immutable launch context.
    """

    def acquire_exclusive(self, owner: str) -> bool:
        """Attempt to claim the exclusive in-flight gate."""
        ...

    def release_exclusive(self, owner: str) -> None:
        """Release the exclusive in-flight gate."""
        ...

    def refresh_command_state(self) -> None:
        """Re-evaluate presentation predicates (e.g. busy/context)."""
        ...

    def set_active_session(self, active: bool) -> None:
        """Cache the last trusted session-presence read for command predicates."""
        ...

    def notify_user(self, message: str, *, severity: str = "warning") -> None:
        """Show a short Russian notice to the user."""
        ...

    def run_semantic_command(self, command_id: str) -> DispatchResult:
        """Dispatch a stable semantic command through the single dispatcher."""
        ...

    @property
    def launch_context(self) -> TuiLaunchContext:
        """The immutable launch context."""
        ...


class CapabilityView(Widget):
    """Base widget that hosts one exclusive synchronous capability operation.

    Subclasses set ``WORKER_OWNER`` to the capability in-flight owner constant
    and implement :meth:`_handle_result` for the event-loop UI update.
    """

    WORKER_OWNER: str = ""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._host: TuiHost | None = None
        self._gate: InFlightGate | None = None
        self._busy = False

    def configure(self, *, host: TuiHost, gate: InFlightGate) -> None:
        """Wire the host and shared in-flight gate (called by the app)."""
        self._host = host
        self._gate = gate
        self.on_configured()

    def on_configured(self) -> None:
        """Hook for capability-specific initialisation after wiring."""

    @property
    def host(self) -> TuiHost:
        """The wired host (programming error if accessed before configure)."""
        if self._host is None:
            raise RuntimeError("capability view used before configure()")
        return self._host

    @property
    def busy(self) -> bool:
        """Whether this view currently owns an exclusive operation."""
        return self._busy

    def _start_exclusive(
        self,
        *,
        name: str,
        work: Callable[[], object],
    ) -> bool:
        """Acquire the shared gate and start exactly one thread worker.

        Returns ``False`` (without starting work) when another exclusive
        operation is already in flight.
        """
        if self._gate is None or self._host is None:
            raise RuntimeError("capability view used before configure()")
        owner = self.WORKER_OWNER
        if not self._gate.acquire(owner):
            self.host.notify_user("Дождитесь завершения текущей операции.")
            return False
        self._busy = True
        self.host.refresh_command_state()
        self.run_worker(
            work,
            name=name,
            group=owner,
            thread=True,
            exit_on_error=False,
        )
        return True

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Apply worker completion on the event loop; never inside the thread."""
        worker = event.worker
        if worker.group != self.WORKER_OWNER:
            return
        if event.state not in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            return

        self._busy = False
        if self._gate is not None:
            self._gate.release(worker.group)
        if self._host is not None:
            self.host.refresh_command_state()

        if event.state is WorkerState.SUCCESS:
            self._handle_result(worker.result)
        elif event.state is WorkerState.ERROR:
            error = worker.error
            # Expected DndAssistantError is converted to a result DTO inside
            # the worker wrapper; anything reaching here is unexpected and must
            # stay observable rather than being silently ignored.
            if error is not None:
                raise error
        # CANCELLED: TUI-04 exposes no user cancellation affordance.

    def _handle_result(self, result: object) -> None:
        """Apply a successful worker result on the event loop."""
        raise NotImplementedError
