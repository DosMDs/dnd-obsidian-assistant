"""S11-06 immutable artifact store + atomic attempt-claim tests (real FS)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from dnd_assistant.application.post_session_persistence import (
    EMPTY_RECAP_ARTIFACT_TEXT,
    artifact_content_hash,
)
from dnd_assistant.domain.post_session import PersistedArtifactKind
from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.post_session_artifacts import (
    ObsidianPostSessionArtifactStore,
)
from tests.unit.post_session.helpers import create_completed_session

_ATT = "att_" + "a" * 32
_ATT2 = "att_" + "b" * 32


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


def test_claim_is_atomic_and_idempotent(store: ObsidianPostSessionArtifactStore) -> None:
    assert store.claim_attempt("S001", _ATT) is True
    assert store.claim_attempt("S001", _ATT) is False
    # Distinct attempt ids claim independently.
    assert store.claim_attempt("S001", _ATT2) is True


def test_persist_requires_a_claimed_attempt(store: ObsidianPostSessionArtifactStore) -> None:
    with pytest.raises(StorageError):
        store.persist_artifact("S001", _ATT, PersistedArtifactKind.SUMMARY, "body\n")


def test_immutable_artifact_roundtrip(store: ObsidianPostSessionArtifactStore) -> None:
    store.claim_attempt("S001", _ATT)
    first = store.persist_artifact("S001", _ATT, PersistedArtifactKind.SUMMARY, "body\n")
    assert first.created is True
    assert first.relative_path == (
        f"_system/raw/sessions/S001/processing/attempts/{_ATT}/summary.md"
    )
    assert store.read_artifact_if_present("S001", _ATT, PersistedArtifactKind.SUMMARY) == "body\n"

    again = store.persist_artifact("S001", _ATT, PersistedArtifactKind.SUMMARY, "body\n")
    assert again.created is False

    with pytest.raises(ConflictError):
        store.persist_artifact("S001", _ATT, PersistedArtifactKind.SUMMARY, "different\n")


def test_absent_artifact_reads_none(store: ObsidianPostSessionArtifactStore) -> None:
    store.claim_attempt("S001", _ATT)
    assert store.read_artifact_if_present("S001", _ATT, PersistedArtifactKind.RECAP) is None
    assert store.artifact_exists("S001", _ATT, PersistedArtifactKind.RECAP) is False


def test_empty_recap_placeholder_persists_and_verifies(
    store: ObsidianPostSessionArtifactStore,
) -> None:
    store.claim_attempt("S001", _ATT)
    result = store.persist_artifact(
        "S001", _ATT, PersistedArtifactKind.RECAP, EMPTY_RECAP_ARTIFACT_TEXT
    )
    assert result.created is True
    text = store.read_artifact_if_present("S001", _ATT, PersistedArtifactKind.RECAP)
    assert text == EMPTY_RECAP_ARTIFACT_TEXT
    assert (
        artifact_content_hash(text or "").digest
        == artifact_content_hash(EMPTY_RECAP_ARTIFACT_TEXT).digest
    )


def test_trailing_newline_is_preserved_exactly(store: ObsidianPostSessionArtifactStore) -> None:
    bodies = ("no newline", "with newline\n", "two\n\n")
    for index, body in enumerate(bodies):
        attempt = f"att_{index:032x}"
        store.claim_attempt("S001", attempt)
        store.persist_artifact("S001", attempt, PersistedArtifactKind.SUMMARY, body)
        assert (
            store.read_artifact_if_present("S001", attempt, PersistedArtifactKind.SUMMARY) == body
        )


def test_workflow_slot_maps_to_json_path(store: ObsidianPostSessionArtifactStore) -> None:
    store.claim_attempt("S001", _ATT)
    path = store.expected_relative_path("S001", _ATT, PersistedArtifactKind.WORKFLOW)
    assert path.endswith("/workflow.json")


def test_bad_attempt_id_rejected(store: ObsidianPostSessionArtifactStore) -> None:
    for bad in ("", "att_short", "../evil", "att_" + "Z" * 32, "attempt_" + "a" * 32):
        with pytest.raises(StorageError):
            store.claim_attempt("S001", bad)


def test_session_path_escape_rejected(store: ObsidianPostSessionArtifactStore) -> None:
    with pytest.raises(StorageError):
        store.claim_attempt("../evil", _ATT)


@requires_symlink
def test_symlinked_artifact_leaf_rejected(
    vault_root: Path, audit_service, store: ObsidianPostSessionArtifactStore
) -> None:
    store.claim_attempt("S001", _ATT)
    attempt_dir = (
        vault_root / "_system" / "raw" / "sessions" / "S001" / "processing" / "attempts" / _ATT
    )
    target = attempt_dir / "target.md"
    target.write_text("x\n", encoding="utf-8")
    os.symlink(target, attempt_dir / "summary.md")
    with pytest.raises(StorageError):
        store.persist_artifact("S001", _ATT, PersistedArtifactKind.SUMMARY, "x\n")
