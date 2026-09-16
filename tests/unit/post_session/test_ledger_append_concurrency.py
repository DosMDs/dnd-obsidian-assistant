"""S11-06 multiprocessing ledger-append concurrency evidence.

Runs multiple OS processes appending distinct records concurrently and proves
the final ledger strictly parses to the exact expected logical event count with
no interleaved/malformed records.  This is part of the normal focused suite on
the platform where tests run.
"""

from __future__ import annotations

import multiprocessing
from datetime import UTC, datetime
from pathlib import Path

from dnd_assistant.application.post_session_ledger import (
    load_ledger_events,
    serialize_ledger_event,
)
from dnd_assistant.domain.post_session import AttemptCompleted, ProcessingOutcome
from dnd_assistant.storage.post_session_processing import (
    ObsidianPostSessionProcessingStore,
)
from tests.unit.post_session.helpers import create_completed_session

_ATTEMPT = "att_" + "a" * 32
_REAL_TIME = datetime(2026, 8, 31, 16, 0, 0, tzinfo=UTC)


def _writer(vault_root_str: str, worker: int, count: int) -> None:
    """Module-level spawned-process worker: append ``count`` distinct records."""
    store = ObsidianPostSessionProcessingStore(vault_root_str)
    for index in range(count):
        event = AttemptCompleted(
            event_id="le_" + f"{worker:08x}{index:024x}",
            attempt_id=_ATTEMPT,
            session_ref="S001",
            real_time=_REAL_TIME,
            outcome=ProcessingOutcome.NO_CHANGES,
        )
        store.append_ledger_line("S001", serialize_ledger_event(event) + "\n")


def test_concurrent_process_appends_do_not_interleave(vault_root: Path, audit_service) -> None:
    create_completed_session(vault_root, audit_service)

    workers = 4
    per_worker = 20
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(target=_writer, args=(str(vault_root), worker, per_worker))
        for worker in range(workers)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=120)
        assert process.exitcode == 0, "concurrent writer failed"

    store = ObsidianPostSessionProcessingStore(vault_root)
    text = store.read_ledger_if_present("S001")
    assert text is not None
    assert text.endswith("\n")

    events = load_ledger_events(store, "S001")
    assert len(events) == workers * per_worker
    assert len({event.event_id for event in events}) == workers * per_worker
