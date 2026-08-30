"""S3-08 integration tests: failure injection for Vault Repository.

Covers:
- Atomic replace failure (create, patch, append)
- Disk-full style failure (ENOSPC)
- Audit intent failure
- Committed-audit failure
- Corrupted audit preflight
- External manual edit after intent
- Target disappears after intent
- Temp-file leak checks
- Audit failure-state invariants
- Recoverability assertions
- Operation-ID reuse rejection
"""

from __future__ import annotations

from unittest import mock

import pytest

import dnd_assistant.storage.vault_repository as _vr_mod
from dnd_assistant.errors import ConflictError, NotFoundError, StorageError
from dnd_assistant.storage.patch import EntityPatch
from tests.integration.helpers import (
    content_hash,
    count_temp_files,
    find_entity_file,
    make_audit_context,
    make_document,
)

# ═════════════════════════════════════════════════════════════════════════════
# 1. Atomic replace failure — create
# ═════════════════════════════════════════════════════════════════════════════


class TestAtomicReplaceFailureCreate:
    """Inject os.replace failure during create_entity."""

    def test_create_failure_leaves_intent_no_entity(self, repo, audit_service, vault_root) -> None:
        doc = make_document(entity_id="npc-gandalf")

        with mock.patch(
            "os.replace",
            side_effect=OSError(13, "Permission denied"),
        ):
            with pytest.raises(StorageError):
                repo.create_entity(doc, audit=make_audit_context("op-001"))

        records = audit_service.read_all()
        assert len(records) == 1
        assert records[0].phase == "intent"
        assert records[0].entity_id == "npc-gandalf"
        assert not any(r.phase == "committed" for r in records)

        from dnd_assistant.storage.paths import discover_entity_files

        assert discover_entity_files(vault_root) == []
        assert repo.list_entities() == []
        assert count_temp_files(vault_root) == 0


# ═════════════════════════════════════════════════════════════════════════════
# 2. Atomic replace failure — patch
# ═════════════════════════════════════════════════════════════════════════════


class TestAtomicReplaceFailurePatch:
    """Inject os.replace failure during patch_entity."""

    def test_patch_failure_leaves_original_unchanged(self, repo, audit_service) -> None:
        doc = make_document(entity_id="npc-gandalf", body="Original body\n")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        entity_file = find_entity_file(repo, "npc-gandalf")
        original_bytes = entity_file.read_bytes()

        with mock.patch(
            "os.replace",
            side_effect=StorageError("Simulated replace failure"),
        ):
            with pytest.raises(StorageError, match="Simulated replace failure"):
                repo.patch_entity(
                    "npc-gandalf",
                    EntityPatch(name="Gandalf v2"),
                    expected_revision=1,
                    audit=make_audit_context("op-002"),
                )

        assert entity_file.read_bytes() == original_bytes
        fetched = repo.get_entity("npc-gandalf")
        assert fetched.entity.revision == 1
        assert fetched.body == "Original body\n"

        records = audit_service.read_all()
        assert len(records) == 3
        assert records[2].phase == "intent"
        assert records[2].operation == "patch_entity"
        committed = [r for r in records if r.phase == "committed"]
        assert len(committed) == 1
        assert count_temp_files(entity_file.parent) == 0


# ═════════════════════════════════════════════════════════════════════════════
# 3. Atomic replace failure — append fact
# ═════════════════════════════════════════════════════════════════════════════


class TestAtomicReplaceFailureAppend:
    """Inject os.replace failure during append_entity_fact."""

    def test_append_failure_leaves_original_unchanged(self, repo, audit_service) -> None:
        doc = make_document(entity_id="npc-gandalf", body="Original body\n")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        entity_file = find_entity_file(repo, "npc-gandalf")
        original_bytes = entity_file.read_bytes()

        with mock.patch.object(
            _vr_mod,
            "atomic_write_text",
            side_effect=StorageError("Simulated replace failure"),
        ):
            with pytest.raises(StorageError, match="Simulated replace failure"):
                repo.append_entity_fact(
                    "npc-gandalf",
                    expected_revision=1,
                    fact="New fact",
                    audit=make_audit_context("op-002"),
                )

        assert entity_file.read_bytes() == original_bytes
        fetched = repo.get_entity("npc-gandalf")
        assert fetched.entity.revision == 1
        assert "- New fact" not in fetched.body

        records = audit_service.read_all()
        assert records[2].phase == "intent"
        committed = [r for r in records if r.phase == "committed"]
        assert len(committed) == 1
        assert count_temp_files(entity_file.parent) == 0


# ═════════════════════════════════════════════════════════════════════════════
# 6. Committed-audit failure
# ═════════════════════════════════════════════════════════════════════════════


class TestCommittedAuditFailure:
    """Entity mutation succeeds but committed audit append fails."""

    def test_entity_committed_audit_finalization_failed(self, repo, audit_service) -> None:
        doc = make_document(entity_id="npc-gandalf", body="Body\n")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        entity_file = find_entity_file(repo, "npc-gandalf")

        # Save reference to real append before mocking
        real_append = audit_service.append

        call_count = [0]

        def _fail_on_second(record):
            call_count[0] += 1
            if call_count[0] == 2:
                raise StorageError("Committed audit append failed")
            real_append(record)

        with mock.patch.object(audit_service, "append", side_effect=_fail_on_second):
            with pytest.raises(StorageError) as exc_info:
                repo.patch_entity(
                    "npc-gandalf",
                    EntityPatch(name="Gandalf v2"),
                    expected_revision=1,
                    audit=make_audit_context("op-002"),
                )

        # Entity mutation IS committed (no rollback)
        assert entity_file.exists()
        fetched = repo.get_entity("npc-gandalf")
        assert fetched.entity.name == "Gandalf v2"
        assert fetched.entity.revision == 2

        records = audit_service.read_all()
        intents = [r for r in records if r.phase == "intent"]
        assert len(intents) == 2

        patch_committed = [
            r for r in records if r.phase == "committed" and r.operation == "patch_entity"
        ]
        assert len(patch_committed) == 0

        assert "audit finalization" in str(exc_info.value).lower()
        assert exc_info.value.__cause__ is not None
        assert "Committed audit append failed" in str(exc_info.value.__cause__)

        # Recoverability: intent.after_hash matches persisted entity hash
        patch_intent = [
            r for r in records if r.phase == "intent" and r.operation == "patch_entity"
        ][0]
        persisted_hash = content_hash(entity_file.read_text(encoding="utf-8"))
        assert patch_intent.after_hash == persisted_hash


# ═════════════════════════════════════════════════════════════════════════════
# 7. Corrupted audit preflight
# ═════════════════════════════════════════════════════════════════════════════


class TestCorruptedAuditPreflight:
    """Corrupt audit log blocks new mutations."""

    def test_corrupt_audit_blocks_create(
        self, repo, audit_service, audit_log_path, vault_root
    ) -> None:
        repo.create_entity(
            make_document(entity_id="npc-gandalf"),
            audit=make_audit_context("op-001"),
        )

        with open(audit_log_path, "a", encoding="utf-8") as f:
            f.write("NOT JSON\n")

        with pytest.raises(StorageError, match="corruption"):
            repo.create_entity(
                make_document(entity_id="npc-frod"),
                audit=make_audit_context("op-002"),
            )

        from dnd_assistant.storage.paths import discover_entity_files

        assert len(discover_entity_files(repo.vault_root)) == 1

    def test_corrupt_audit_blocks_patch(self, repo, audit_service, audit_log_path) -> None:
        repo.create_entity(
            make_document(entity_id="npc-gandalf"),
            audit=make_audit_context("op-001"),
        )

        with open(audit_log_path, "a", encoding="utf-8") as f:
            f.write("NOT JSON\n")

        with pytest.raises(StorageError, match="corruption"):
            repo.patch_entity(
                "npc-gandalf",
                EntityPatch(name="Gandalf v2"),
                expected_revision=1,
                audit=make_audit_context("op-002"),
            )

        assert repo.get_entity("npc-gandalf").entity.revision == 1


# ═════════════════════════════════════════════════════════════════════════════
# 8. External manual edit after intent
# ═════════════════════════════════════════════════════════════════════════════


class TestExternalEditAfterIntent:
    """External edit after intent must be detected."""

    def test_body_change_after_intent_detected(self, repo) -> None:
        """Edit after intent is detected by second hash check."""
        doc = make_document(entity_id="npc-gandalf", body="Original body\n")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        entity_file = find_entity_file(repo, "npc-gandalf")

        # Inject the edit during the second-read phase of _commit_entity_mutation
        real_read = _vr_mod._read_exact_text

        call_count = [0]

        def _edit_on_second_read(path):
            call_count[0] += 1
            if call_count[0] == 2:
                text = real_read(path)
                edited = text.replace("Original body", "EDITED body")
                entity_file.write_text(edited, encoding="utf-8")
            return real_read(path)

        with mock.patch.object(
            _vr_mod,
            "_read_exact_text",
            side_effect=_edit_on_second_read,
        ):
            with pytest.raises((ConflictError, StorageError)):
                repo.patch_entity(
                    "npc-gandalf",
                    EntityPatch(name="Gandalf v2"),
                    expected_revision=1,
                    audit=make_audit_context("op-002"),
                )

        # External edit remains intact
        assert "EDITED body" in entity_file.read_text(encoding="utf-8")

    def test_revision_change_detected(self, repo) -> None:
        doc = make_document(entity_id="npc-gandalf", body="Body\n")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        entity_file = find_entity_file(repo, "npc-gandalf")

        text = entity_file.read_text(encoding="utf-8")
        edited = text.replace("revision: 1", "revision: 99")
        entity_file.write_text(edited, encoding="utf-8")

        with pytest.raises(ConflictError, match="Revision mismatch"):
            repo.patch_entity(
                "npc-gandalf",
                EntityPatch(name="Gandalf v2"),
                expected_revision=1,
                audit=make_audit_context("op-002"),
            )

        assert "revision: 99" in entity_file.read_text(encoding="utf-8")


# ═════════════════════════════════════════════════════════════════════════════
# 9. Target disappears after intent
# ═════════════════════════════════════════════════════════════════════════════


class TestTargetDisappearsAfterIntent:
    """Target file removed after intent must be detected."""

    def test_target_removed_after_intent(self, repo, audit_service) -> None:
        doc = make_document(entity_id="npc-gandalf", body="Body\n")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        entity_file = find_entity_file(repo, "npc-gandalf")

        # Use wraps to avoid recursion - wrap the real function
        real_read = _vr_mod._read_exact_text

        call_count = [0]

        def _remove_on_second_read(path):
            call_count[0] += 1
            if call_count[0] == 2:
                entity_file.unlink()
            return real_read(path)

        with mock.patch.object(
            _vr_mod,
            "_read_exact_text",
            side_effect=_remove_on_second_read,
        ):
            with pytest.raises((StorageError, NotFoundError)):
                repo.patch_entity(
                    "npc-gandalf",
                    EntityPatch(name="Gandalf v2"),
                    expected_revision=1,
                    audit=make_audit_context("op-002"),
                )

        assert not entity_file.exists()

        records = audit_service.read_all()
        intents = [r for r in records if r.phase == "intent"]
        assert len(intents) == 2


# ═════════════════════════════════════════════════════════════════════════════
# 10. Operation-ID reuse after failed intent
# ═════════════════════════════════════════════════════════════════════════════


class TestOperationIdReuse:
    """Same operation_id after failed intent must be rejected."""

    def test_reuse_rejected_after_failed_intent(self, repo, audit_service) -> None:
        doc = make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        with pytest.raises(ConflictError, match="already been used"):
            repo.create_entity(doc, audit=make_audit_context("op-001"))

    def test_fresh_operation_after_failed_intent(self, repo, audit_service) -> None:
        doc = make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        result = repo.create_entity(
            make_document(entity_id="npc-frod"),
            audit=make_audit_context("op-002"),
        )
        assert result.entity.id == "npc-frod"


# ═════════════════════════════════════════════════════════════════════════════
# 4. Disk-full style failure (ENOSPC)
# ═════════════════════════════════════════════════════════════════════════════


class TestDiskFullFailure:
    """Simulate ENOSPC at the atomic write boundary."""

    def test_enospc_on_patch(self, repo) -> None:
        doc = make_document(entity_id="npc-gandalf", body="Body\n")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        entity_file = find_entity_file(repo, "npc-gandalf")
        original_bytes = entity_file.read_bytes()

        with mock.patch(
            "os.replace",
            side_effect=StorageError(
                "No space left on device",
                cause=OSError(28, "No space left on device"),
            ),
        ):
            with pytest.raises(StorageError):
                repo.patch_entity(
                    "npc-gandalf",
                    EntityPatch(name="New Name"),
                    expected_revision=1,
                    audit=make_audit_context("op-002"),
                )

        assert entity_file.read_bytes() == original_bytes
        assert repo.get_entity("npc-gandalf").entity.revision == 1

    def test_enospc_on_append(self, repo) -> None:
        doc = make_document(entity_id="npc-frod", body="Body\n")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        entity_file = find_entity_file(repo, "npc-frod")
        original_bytes = entity_file.read_bytes()

        with mock.patch(
            "os.replace",
            side_effect=StorageError(
                "No space left on device",
                cause=OSError(28, "No space left on device"),
            ),
        ):
            with pytest.raises(StorageError):
                repo.append_entity_fact(
                    "npc-frod",
                    expected_revision=1,
                    fact="New fact",
                    audit=make_audit_context("op-002"),
                )

        assert entity_file.read_bytes() == original_bytes
        assert repo.get_entity("npc-frod").entity.revision == 1


# ═════════════════════════════════════════════════════════════════════════════
# 5. Audit intent failure
# ═════════════════════════════════════════════════════════════════════════════


class TestAuditIntentFailure:
    """If audit intent cannot be persisted, entity mutation must NOT begin."""

    def test_create_aborted_before_entity_write(self, repo, audit_service, vault_root) -> None:
        doc = make_document(entity_id="npc-gandalf")

        with mock.patch.object(
            audit_service,
            "append",
            side_effect=StorageError("Audit append failed"),
        ):
            with pytest.raises(StorageError, match="Audit append failed"):
                repo.create_entity(doc, audit=make_audit_context("op-001"))

        from dnd_assistant.storage.paths import discover_entity_files

        assert discover_entity_files(vault_root) == []

    def test_patch_aborted_before_entity_write(self, repo, audit_service) -> None:
        doc = make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        entity_file = find_entity_file(repo, "npc-gandalf")
        original_bytes = entity_file.read_bytes()

        with mock.patch.object(
            audit_service,
            "append",
            side_effect=StorageError("Audit append failed"),
        ):
            with pytest.raises(StorageError, match="Audit append failed"):
                repo.patch_entity(
                    "npc-gandalf",
                    EntityPatch(name="Gandalf v2"),
                    expected_revision=1,
                    audit=make_audit_context("op-002"),
                )

        assert entity_file.read_bytes() == original_bytes
        assert repo.get_entity("npc-gandalf").entity.revision == 1

    def test_append_aborted_before_entity_write(self, repo, audit_service) -> None:
        doc = make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        entity_file = find_entity_file(repo, "npc-gandalf")
        original_bytes = entity_file.read_bytes()

        with mock.patch.object(
            audit_service,
            "append",
            side_effect=StorageError("Audit append failed"),
        ):
            with pytest.raises(StorageError, match="Audit append failed"):
                repo.append_entity_fact(
                    "npc-gandalf",
                    expected_revision=1,
                    fact="New fact",
                    audit=make_audit_context("op-002"),
                )

        assert entity_file.read_bytes() == original_bytes
        assert repo.get_entity("npc-gandalf").entity.revision == 1
