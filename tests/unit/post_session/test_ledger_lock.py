"""S11-06 portable interprocess ledger-lock behavior tests (deterministic)."""

from __future__ import annotations

import pytest

from dnd_assistant.application.post_session_ledger import serialize_ledger_event
from dnd_assistant.domain.post_session import AttemptStarted, Sha256Fingerprint
from dnd_assistant.errors import StorageError
from dnd_assistant.storage import post_session_processing as pse
from dnd_assistant.storage.post_session_processing import (
    ObsidianPostSessionProcessingStore,
)
from tests.unit.post_session.helpers import BASE_END, create_completed_session

_ATT = "att_" + "a" * 32
_FP = Sha256Fingerprint(digest="c" * 64)


def _event(event_id: str = "le_" + "a" * 32) -> AttemptStarted:
    return AttemptStarted(
        event_id=event_id,
        attempt_id=_ATT,
        session_ref="S001",
        real_time=BASE_END,
        input_fingerprint=_FP,
        processor_version="2",
        prompt_version="v1",
    )


class _LockSpy:
    def __init__(self) -> None:
        self.events: list[str] = []

    def acquire(self, fd: int) -> None:
        self.events.append("acquire")

    def release(self, fd: int) -> None:
        self.events.append("release")


def _install_spy(monkeypatch) -> _LockSpy:
    spy = _LockSpy()
    monkeypatch.setattr(pse, "_acquire_exclusive", spy.acquire)
    monkeypatch.setattr(pse, "_release_exclusive", spy.release)
    return spy


def test_append_acquires_and_releases_lock(vault_root, audit_service, monkeypatch) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    spy = _install_spy(monkeypatch)

    store.append_ledger_line("S001", serialize_ledger_event(_event()) + "\n")

    assert spy.events == ["acquire", "release"]


def test_read_uses_the_interprocess_lock(vault_root, audit_service, monkeypatch) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    store.append_ledger_line("S001", serialize_ledger_event(_event()) + "\n")

    spy = _install_spy(monkeypatch)
    text = store.read_ledger_if_present("S001")
    assert text is not None
    assert spy.events == ["acquire", "release"]


def test_lock_file_is_synchronization_only(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    store.append_ledger_line("S001", serialize_ledger_event(_event()) + "\n")

    lock = vault_root / "_system" / "raw" / "sessions" / "S001" / "processing" / "ledger.lock"
    assert lock.exists()
    # No audit record was written by the lock or the ledger.
    assert not any(record.operation == "attempt_started" for record in audit_service.read_all())


def test_short_write_fails_closed_without_remainder(vault_root, audit_service, monkeypatch) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    spy = _install_spy(monkeypatch)

    real_write = pse.os.write
    calls = {"count": 0}

    def partial_write(fd: int, data: bytes) -> int:
        calls["count"] += 1
        return real_write(fd, data[: max(1, len(data) - 1)])

    monkeypatch.setattr(pse.os, "write", partial_write)

    with pytest.raises(StorageError):
        store.append_ledger_line("S001", serialize_ledger_event(_event()) + "\n")

    # Exactly one write attempt; no remainder retry; lock released in finally.
    assert calls["count"] == 1
    assert spy.events == ["acquire", "release"]


def test_lock_released_after_os_write_failure(vault_root, audit_service, monkeypatch) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    spy = _install_spy(monkeypatch)

    def failing_write(fd: int, data: bytes) -> int:
        raise OSError("disk full")

    monkeypatch.setattr(pse.os, "write", failing_write)

    with pytest.raises(StorageError):
        store.append_ledger_line("S001", serialize_ledger_event(_event()) + "\n")

    assert spy.events == ["acquire", "release"]


def test_symlinked_lock_path_rejected(vault_root, audit_service, monkeypatch) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    store.append_ledger_line("S001", serialize_ledger_event(_event()) + "\n")

    processing = vault_root / "_system" / "raw" / "sessions" / "S001" / "processing"
    lock = processing / "ledger.lock"
    lock.unlink()
    target = processing / "target.lock"
    target.write_text("", encoding="utf-8")
    try:
        import os as _os

        _os.symlink(target, lock)
    except (OSError, NotImplementedError):
        pytest.skip("host cannot create symlinks")

    with pytest.raises(StorageError):
        store.read_ledger_if_present("S001")
