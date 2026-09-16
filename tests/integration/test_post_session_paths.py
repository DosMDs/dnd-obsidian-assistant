"""S11-08 path/Unicode adversarial hardening for the post-session workflow.

Covers a Vault root containing spaces + Unicode, an allowed-Unicode session id,
traversal-like session-id rejection and a symlinked ``processing/`` directory at
the processor boundary.  Symlink-gated tests skip only where the host genuinely
cannot create symlinks.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from dnd_assistant.application.post_session_processor import (
    PostSessionProcessorStatus,
    run_post_session_processing,
)
from dnd_assistant.errors import StorageError
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.session_metadata import ObsidianSessionMetadataRepository
from dnd_assistant.storage.session_paths import resolve_session_storage_paths
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository
from tests.integration.post_session_processor_helpers import (
    ATTEMPT_A,
    append_extraction,
    build_deps,
    fixed_clock,
)
from tests.integration.test_post_session_context import (
    _build,
    _build_vault,
    _create_entity,
    _entity,
    _setup_vault,
)
from tests.unit.post_session.helpers import (
    BASE_END,
    BASE_START,
    make_audit_context,
    make_session,
)


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


def _unicode_vault(tmp_path: Path):
    """Create a Vault whose root contains spaces and Unicode plus one entity."""
    root = tmp_path / "vault space ünïcode"
    root.mkdir()
    (root / "Sessions").mkdir()
    (root / "_system" / "raw" / "sessions").mkdir(parents=True)
    (root / "_system" / "audit").mkdir(parents=True)
    _setup_vault(root)
    audit = AuditService(root / "_system" / "audit" / "audit.jsonl")
    vault = ObsidianVaultRepository(root, audit)
    _create_entity(
        vault,
        _entity("npc-aria", name="Aria"),
        body="Aria is a ranger.",
        op_id="create-aria",
    )
    metadata_repo = ObsidianSessionMetadataRepository(root, audit)
    from dnd_assistant.storage.session_events import ObsidianSessionEventRepository

    event_repo = ObsidianSessionEventRepository(root, audit)
    metadata_repo.create_session(
        make_session(status="active"),
        audit=make_audit_context(operation_id="s-start", real_time=BASE_START),
    )
    event_repo.append_event(
        "S001",
        event_type="note",
        real_time=BASE_START,
        world_tick=150,
        extra_fields={"text": "The party met Aria."},
        audit=make_audit_context(operation_id="evt-1", real_time=BASE_START),
    )
    metadata_repo.close_session(
        "S001",
        expected_revision=1,
        world_tick_end=200,
        touched_entity_ids=["npc-aria"],
        audit=make_audit_context(operation_id="s-end", real_time=BASE_END),
    )
    return root, audit


def test_unicode_and_spaces_vault_root_end_to_end(tmp_path: Path) -> None:
    root, audit = _unicode_vault(tmp_path)
    prepared = _build(root, audit)
    deps = build_deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.COMPLETED
    assert result.summary_path is not None
    assert (root / result.summary_path).is_file()


def test_allowed_unicode_session_id_resolves(tmp_path: Path) -> None:
    root, audit = _unicode_vault(tmp_path)
    paths = resolve_session_storage_paths(root, "S001-Ä")
    assert paths.raw_dir.name == "S001-Ä"
    assert paths.raw_dir.is_relative_to(root)


@pytest.mark.parametrize("bad", ("../evil", "S001/../evil", "a\\b", ".."))
def test_traversal_like_session_id_rejected(tmp_path: Path, bad: str) -> None:
    root, _audit = _unicode_vault(tmp_path)
    with pytest.raises(StorageError):
        resolve_session_storage_paths(root, bad)


@requires_symlink
def test_symlinked_processing_directory_fails_closed(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)

    raw = root / "_system" / "raw" / "sessions" / "S001"
    target = raw / "processing_target"
    target.mkdir()
    os.symlink(target, raw / "processing")

    deps = build_deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.reason == "ledger_unreadable"
    assert len(getattr(deps.extraction_model, "requests", [])) == 0
    assert not (target / "ledger.jsonl").exists()
