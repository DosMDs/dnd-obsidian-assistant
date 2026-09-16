"""S11-08 immutable artifact-store hardening tests (real filesystem).

Closes gaps left by S11-06: read-back mismatch orphan semantics, best-effort
cleanup on write/fsync failure, deterministic concurrent same-slot persistence,
and symlinked processing/attempts/attempt-directory topology.
"""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

import pytest

from dnd_assistant.domain.post_session import PersistedArtifactKind
from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage import post_session_artifacts as pa
from dnd_assistant.storage.post_session_artifacts import (
    ArtifactWriteResult,
    ObsidianPostSessionArtifactStore,
)
from tests.unit.post_session.helpers import create_completed_session

_ATT = "att_" + "a" * 32
_SUMMARY = PersistedArtifactKind.SUMMARY


def _can_symlink() -> bool:
    tmp = tempfile.mkdtemp()
    try:
        target = os.path.join(tmp, "target")
        Path(target).write_text("", encoding="utf-8")
        os.symlink(target, os.path.join(tmp, "link"))
        return True
    except (OSError, NotImplementedError):
        return False
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


requires_symlink = pytest.mark.skipif(not _can_symlink(), reason="host cannot create symlinks")


@pytest.fixture
def store(vault_root: Path, audit_service) -> ObsidianPostSessionArtifactStore:
    create_completed_session(vault_root, audit_service)
    return ObsidianPostSessionArtifactStore(vault_root)


def test_readback_mismatch_fails_closed_and_leaves_orphan(
    vault_root: Path, store: ObsidianPostSessionArtifactStore, monkeypatch
) -> None:
    store.claim_attempt("S001", _ATT)
    relative = store.expected_relative_path("S001", _ATT, _SUMMARY)

    monkeypatch.setattr(pa, "_read_exact_text", lambda path: "tampered\n")
    with pytest.raises(StorageError):
        store.persist_artifact("S001", _ATT, _SUMMARY, "body\n")

    # The implementation does not delete on read-back mismatch: the artifact
    # remains as orphan workflow evidence.  File existence must never imply
    # completion (the ledger has no artifact_persisted event).
    path = vault_root / relative
    assert path.exists()
    assert path.read_bytes() == b"body\n"


def test_write_failure_cleans_up_partial_file(
    vault_root: Path, store: ObsidianPostSessionArtifactStore, monkeypatch
) -> None:
    store.claim_attempt("S001", _ATT)
    relative = store.expected_relative_path("S001", _ATT, _SUMMARY)

    def failing_fsync(fd: int) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(pa.os, "fsync", failing_fsync)
    with pytest.raises(StorageError):
        store.persist_artifact("S001", _ATT, _SUMMARY, "body\n")

    assert not (vault_root / relative).exists()


def test_identical_bytes_concurrently_are_idempotent(
    vault_root: Path, store: ObsidianPostSessionArtifactStore
) -> None:
    store.claim_attempt("S001", _ATT)
    barrier = threading.Barrier(2)
    results: list[ArtifactWriteResult] = []
    errors: list[BaseException] = []

    def worker() -> None:
        barrier.wait()
        try:
            results.append(store.persist_artifact("S001", _ATT, _SUMMARY, "body\n"))
        except BaseException as exc:  # noqa: BLE001 - captured for assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    created = sorted(result.created for result in results)
    assert created == [False, True]
    assert store.read_artifact_if_present("S001", _ATT, _SUMMARY) == "body\n"


def test_conflicting_bytes_concurrently_fail_closed(
    vault_root: Path, store: ObsidianPostSessionArtifactStore
) -> None:
    store.claim_attempt("S001", _ATT)
    barrier = threading.Barrier(2)
    results: list[ArtifactWriteResult] = []
    errors: list[BaseException] = []
    bodies = ("first\n", "second\n")

    def worker(body: str) -> None:
        barrier.wait()
        try:
            results.append(store.persist_artifact("S001", _ATT, _SUMMARY, body))
        except BaseException as exc:  # noqa: BLE001 - captured for assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(body,)) for body in bodies]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(1 for result in results if result.created) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], ConflictError)
    final = store.read_artifact_if_present("S001", _ATT, _SUMMARY)
    assert final in bodies


@requires_symlink
def test_symlinked_processing_directory_rejected(
    vault_root: Path, store: ObsidianPostSessionArtifactStore
) -> None:
    raw = vault_root / "_system" / "raw" / "sessions" / "S001"
    target = raw / "processing_target"
    target.mkdir()
    os.symlink(target, raw / "processing")
    with pytest.raises(StorageError):
        store.claim_attempt("S001", _ATT)


@requires_symlink
def test_symlinked_attempts_directory_rejected(
    vault_root: Path, store: ObsidianPostSessionArtifactStore
) -> None:
    processing = vault_root / "_system" / "raw" / "sessions" / "S001" / "processing"
    processing.mkdir()
    target = processing / "attempts_target"
    target.mkdir()
    os.symlink(target, processing / "attempts")
    with pytest.raises(StorageError):
        store.claim_attempt("S001", _ATT)


@requires_symlink
def test_symlinked_attempt_directory_rejected(
    vault_root: Path, store: ObsidianPostSessionArtifactStore
) -> None:
    processing = vault_root / "_system" / "raw" / "sessions" / "S001" / "processing"
    attempts = processing / "attempts"
    attempts.mkdir(parents=True)
    target = attempts / "target"
    target.mkdir()
    os.symlink(target, attempts / _ATT)
    with pytest.raises(StorageError):
        store.claim_attempt("S001", _ATT)
