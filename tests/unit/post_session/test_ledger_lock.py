"""S11-06 portable interprocess ledger-lock behavior tests (deterministic)."""

from __future__ import annotations

import errno
import os
import sys

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


def test_lock_contention_classifier_uses_errno_values() -> None:
    assert pse._is_lock_contention(OSError(errno.EACCES, "Permission denied"))
    assert pse._is_lock_contention(OSError(errno.EDEADLK, "deadlock"))
    assert not pse._is_lock_contention(OSError(errno.EBADF, "Bad file descriptor"))
    assert not pse._is_lock_contention(OSError(errno.EINVAL, "Invalid argument"))


def test_lock_contention_classifier_recognizes_winerror_values() -> None:
    class _WinOSError(OSError):
        def __init__(self, winerror: int) -> None:
            super().__init__()
            self.winerror = winerror

    assert pse._is_lock_contention(_WinOSError(33))
    assert not pse._is_lock_contention(_WinOSError(5))


def test_non_contention_acquisition_error_terminates_as_storage_error(
    vault_root, audit_service, monkeypatch
) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    calls = {"count": 0}

    def permanent(fd: int) -> None:
        calls["count"] += 1
        raise OSError(errno.EBADF, "Bad file descriptor")

    monkeypatch.setattr(pse, "_acquire_exclusive", permanent)

    with pytest.raises(StorageError):
        store.append_ledger_line("S001", serialize_ledger_event(_event()) + "\n")

    # A permanent acquisition error is not retried.
    assert calls["count"] == 1


def test_unlock_failure_on_successful_operation_becomes_storage_error(
    vault_root, audit_service, monkeypatch
) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)

    def failing_release(fd: int) -> None:
        raise OSError(errno.EIO, "unlock failed")

    monkeypatch.setattr(pse, "_release_exclusive", failing_release)

    with pytest.raises(StorageError) as exc:
        store.append_ledger_line("S001", serialize_ledger_event(_event()) + "\n")
    assert isinstance(exc.value.__cause__, OSError)
    assert exc.value.__cause__.errno == errno.EIO


def test_body_failure_is_not_replaced_by_unlock_failure(
    vault_root, audit_service, monkeypatch
) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)

    def failing_write(fd: int, data: bytes) -> int:
        raise OSError(errno.ENOSPC, "disk full")

    def failing_release(fd: int) -> None:
        raise OSError(errno.EIO, "unlock failed")

    monkeypatch.setattr(pse.os, "write", failing_write)
    monkeypatch.setattr(pse, "_release_exclusive", failing_release)

    with pytest.raises(StorageError) as exc:
        store.append_ledger_line("S001", serialize_ledger_event(_event()) + "\n")

    # Primary write failure is preserved, not replaced by the unlock failure.
    assert "append" in str(exc.value).lower()
    assert isinstance(exc.value.__cause__, OSError)
    assert exc.value.__cause__.errno == errno.ENOSPC


def test_descriptor_is_closed_when_unlock_fails(vault_root, audit_service, monkeypatch) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    closed: list[int] = []
    real_close = pse.os.close

    def recording_close(fd: int) -> None:
        closed.append(fd)
        real_close(fd)

    def failing_release(fd: int) -> None:
        raise OSError(errno.EIO, "unlock failed")

    monkeypatch.setattr(pse.os, "close", recording_close)
    monkeypatch.setattr(pse, "_release_exclusive", failing_release)

    with pytest.raises(StorageError):
        store.append_ledger_line("S001", serialize_ledger_event(_event()) + "\n")

    # Both the ledger descriptor and the lock descriptor are closed in finally.
    assert closed


@pytest.mark.skipif(sys.platform != "win32", reason="direct msvcrt behavior")
def test_real_msvcrt_contention_is_classified(monkeypatch, tmp_path) -> None:
    lock = tmp_path / "ledger.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
    holder = os.open(lock, flags, 0o666)
    contender = os.open(lock, flags, 0o666)
    try:
        pse.msvcrt.locking(holder, pse.msvcrt.LK_NBLCK, 1)
        with pytest.raises(OSError) as exc:
            pse.msvcrt.locking(contender, pse.msvcrt.LK_NBLCK, 1)
        assert pse._is_lock_contention(exc.value)
    finally:
        pse.msvcrt.locking(holder, pse.msvcrt.LK_UNLCK, 1)
        os.close(holder)
        os.close(contender)


@pytest.mark.skipif(sys.platform != "win32", reason="direct msvcrt behavior")
def test_contention_error_is_retried_until_success(monkeypatch, tmp_path) -> None:
    calls = {"count": 0}
    real_locking = pse.msvcrt.locking

    def flaky(fd: int, mode: int, nbytes: int) -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError(errno.EACCES, "Permission denied")
        real_locking(fd, mode, nbytes)

    monkeypatch.setattr(pse.msvcrt, "locking", flaky)

    lock = tmp_path / "ledger.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
    fd = os.open(lock, flags, 0o666)
    try:
        pse._acquire_exclusive(fd)
        assert calls["count"] == 2
    finally:
        os.close(fd)


@pytest.mark.skipif(sys.platform != "win32", reason="direct msvcrt behavior")
def test_permanent_msvcrt_error_is_not_retried(monkeypatch, tmp_path) -> None:
    calls = {"count": 0}

    def permanent(fd: int, mode: int, nbytes: int) -> None:
        calls["count"] += 1
        raise OSError(errno.EBADF, "Bad file descriptor")

    monkeypatch.setattr(pse.msvcrt, "locking", permanent)

    lock = tmp_path / "ledger.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
    fd = os.open(lock, flags, 0o666)
    try:
        with pytest.raises(OSError):
            pse._acquire_exclusive(fd)
        assert calls["count"] == 1
    finally:
        os.close(fd)


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
