"""S3-08 integration tests: happy-path repository cycle, revision chain,
audit hash chain, body/newline/extra-frontmatter preservation, multi-type,
human filename rename, and Vault validity.

Uses a real temporary Vault with real AuditService and
ObsidianVaultRepository — no mocks, no network, no Ollama.
"""

from __future__ import annotations

import pytest

from dnd_assistant.domain.types import EntityType
from dnd_assistant.errors import NotFoundError
from dnd_assistant.storage.patch import EntityPatch
from tests.integration.helpers import (
    assert_vault_valid,
    content_hash,
    find_entity_file,
    make_audit_context,
    make_document,
)

# ═════════════════════════════════════════════════════════════════════════════
# 1. Happy-path integration cycle
# ═════════════════════════════════════════════════════════════════════════════


class TestHappyPathCycle:
    """Canonical Stage-3 integration cycle: create -> get -> patch -> get
    -> append fact -> get -> list -> audit read-back -> validate final Vault.
    """

    def test_full_cycle(self, repo, audit_service) -> None:
        doc = make_document(
            entity_id="npc-gandalf",
            name="Gandalf",
            body=(
                "## Notes\nMet [[Captain Veyra]].\n**Important:** do not trust the gatekeeper.\n"
            ),
        )
        created = repo.create_entity(doc, audit=make_audit_context("op-001"))
        assert created.entity.id == "npc-gandalf"
        assert created.entity.revision == 1
        assert created.entity.name == "Gandalf"
        entity_file = find_entity_file(repo, "npc-gandalf")

        # Get
        fetched = repo.get_entity("npc-gandalf")
        assert fetched.entity.id == "npc-gandalf"
        assert fetched.entity.revision == 1
        assert fetched.body == doc.body

        # Patch
        patched = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Gandalf the White"),
            expected_revision=1,
            audit=make_audit_context("op-002"),
        )
        assert patched.entity.revision == 2
        assert patched.entity.name == "Gandalf the White"

        # Get after patch
        fetched2 = repo.get_entity("npc-gandalf")
        assert fetched2.entity.revision == 2
        assert fetched2.entity.name == "Gandalf the White"

        # Append fact
        appended = repo.append_entity_fact(
            "npc-gandalf",
            expected_revision=2,
            fact="Is a Maia",
            audit=make_audit_context("op-003"),
        )
        assert appended.entity.revision == 3
        assert "- Is a Maia" in appended.body
        assert doc.body in appended.body

        # Get after append
        fetched3 = repo.get_entity("npc-gandalf")
        assert fetched3.entity.revision == 3
        assert "- Is a Maia" in fetched3.body

        # List
        all_entities = repo.list_entities()
        assert len(all_entities) == 1
        assert all_entities[0].entity.id == "npc-gandalf"

        # Audit read-back
        records = audit_service.read_all()
        assert len(records) == 6

        expected_ops = [
            "create_entity",
            "create_entity",
            "patch_entity",
            "patch_entity",
            "append_entity_fact",
            "append_entity_fact",
        ]
        expected_phases = [
            "intent",
            "committed",
            "intent",
            "committed",
            "intent",
            "committed",
        ]
        for i, (op, phase) in enumerate(zip(expected_ops, expected_phases, strict=True)):
            assert records[i].operation == op
            assert records[i].phase == phase
            assert records[i].entity_id == "npc-gandalf"

        # Stable EntityId unchanged
        assert fetched.entity.id == "npc-gandalf"

        # Same entity file remains after patch/append
        assert find_entity_file(repo, "npc-gandalf") == entity_file

        # Final Vault validity
        assert_vault_valid(repo)

    def test_empty_vault_list(self, repo) -> None:
        assert repo.list_entities() == []

    def test_empty_vault_get_not_found(self, repo) -> None:
        with pytest.raises(NotFoundError):
            repo.get_entity("npc-nonexistent")


# ═════════════════════════════════════════════════════════════════════════════
# 2. Revision chain integration invariant
# ═════════════════════════════════════════════════════════════════════════════


class TestRevisionChain:
    """Verify revision sequence through disk round-trips."""

    def test_revision_chain(self, repo) -> None:
        doc = make_document(entity_id="npc-gandalf")
        created = repo.create_entity(doc, audit=make_audit_context("op-001"))
        assert created.entity.revision == 1
        assert repo.get_entity("npc-gandalf").entity.revision == 1

        # Patch: 1 -> 2
        patched = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Gandalf v2"),
            expected_revision=1,
            audit=make_audit_context("op-002"),
        )
        assert patched.entity.revision == 2
        assert repo.get_entity("npc-gandalf").entity.revision == 2

        # Append fact: 2 -> 3
        appended = repo.append_entity_fact(
            "npc-gandalf",
            expected_revision=2,
            fact="New fact",
            audit=make_audit_context("op-003"),
        )
        assert appended.entity.revision == 3
        assert repo.get_entity("npc-gandalf").entity.revision == 3

        # Patch: 3 -> 4
        patched2 = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Gandalf v4"),
            expected_revision=3,
            audit=make_audit_context("op-004"),
        )
        assert patched2.entity.revision == 4
        assert repo.get_entity("npc-gandalf").entity.revision == 4


# ═════════════════════════════════════════════════════════════════════════════
# 3. Audit hash-chain integration invariant
# ═════════════════════════════════════════════════════════════════════════════


class TestAuditHashChain:
    """Verify audit hash chain through real persistence."""

    def test_hash_chain(self, repo, audit_service) -> None:
        doc = make_document(entity_id="npc-gandalf", body="Initial body\n")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        entity_file = find_entity_file(repo, "npc-gandalf")
        create_text = entity_file.read_text(encoding="utf-8")
        create_hash = content_hash(create_text)

        records = audit_service.read_all()
        create_intent = records[0]
        create_committed = records[1]
        assert create_intent.phase == "intent"
        assert create_committed.phase == "committed"
        assert create_intent.before_hash is None
        assert create_intent.after_hash == create_hash
        assert create_committed.after_hash == create_hash

        # Patch
        repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Gandalf v2"),
            expected_revision=1,
            audit=make_audit_context("op-002"),
        )
        patch_text = entity_file.read_text(encoding="utf-8")
        patch_hash = content_hash(patch_text)

        records2 = audit_service.read_all()
        patch_intent = records2[2]
        patch_committed = records2[3]
        assert patch_intent.before_hash == create_hash
        assert patch_intent.after_hash == patch_hash
        assert patch_committed.after_hash == patch_hash

        # Append fact
        repo.append_entity_fact(
            "npc-gandalf",
            expected_revision=2,
            fact="Another fact",
            audit=make_audit_context("op-003"),
        )
        append_text = entity_file.read_text(encoding="utf-8")
        append_hash = content_hash(append_text)

        records3 = audit_service.read_all()
        append_intent = records3[4]
        append_committed = records3[5]
        assert append_intent.before_hash == patch_hash
        assert append_intent.after_hash == append_hash
        assert append_committed.after_hash == append_hash

        # Final persisted hash matches committed after_hash
        assert append_hash == content_hash(entity_file.read_text(encoding="utf-8"))


# ═════════════════════════════════════════════════════════════════════════════
# 4. User Markdown body preservation
# ═════════════════════════════════════════════════════════════════════════════


class TestUserMarkdownPreservation:
    """Verify user-authored Markdown body survives patch and append."""

    BODY = (
        "## Notes\n"
        "\n"
        "Met [[Captain Veyra]].\n"
        "\n"
        "**Important:** do not trust the gatekeeper.\n"
        "\n"
        "- Reason one\n"
        "- Reason two\n"
    )

    def test_body_survives_patch(self, repo) -> None:
        doc = make_document(entity_id="npc-gandalf", body=self.BODY)
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        patched = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Gandalf the White"),
            expected_revision=1,
            audit=make_audit_context("op-002"),
        )
        assert patched.body == self.BODY
        assert repo.get_entity("npc-gandalf").body == self.BODY

    def test_body_survives_append(self, repo) -> None:
        doc = make_document(entity_id="npc-gandalf", body=self.BODY)
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        appended = repo.append_entity_fact(
            "npc-gandalf",
            expected_revision=1,
            fact="New discovered fact",
            audit=make_audit_context("op-002"),
        )
        assert appended.body.startswith(self.BODY)
        assert "- New discovered fact" in appended.body
        assert repo.get_entity("npc-gandalf").body.startswith(self.BODY)

    def test_body_survives_patch_then_append(self, repo) -> None:
        doc = make_document(entity_id="npc-gandalf", body=self.BODY)
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        patched = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Gandalf the White"),
            expected_revision=1,
            audit=make_audit_context("op-002"),
        )
        assert patched.body == self.BODY

        appended = repo.append_entity_fact(
            "npc-gandalf",
            expected_revision=2,
            fact="Even more info",
            audit=make_audit_context("op-003"),
        )
        assert appended.body.startswith(self.BODY)
        assert "- Even more info" in appended.body


# ═════════════════════════════════════════════════════════════════════════════
# 5. Newline integration matrix
# ═════════════════════════════════════════════════════════════════════════════


class TestNewlineIntegration:
    """Exercise persistence of various newline styles through real mutations."""

    @pytest.mark.parametrize(
        "body",
        [
            "line1\nline2\n",
            "line1\r\nline2\r\n",
            "line1\nline2\r\nline3\n",
            "no trailing newline",
            "CRLF only\r\nno trailing",
            "Unicode: \u041f\u0440\u0438\u0432\u0435\u0442\n\u041c\u0438\u0440\n",
        ],
        ids=["LF", "CRLF", "mixed", "no_trailing", "CRLF_no_trailing", "unicode"],
    )
    def test_newline_preserved_through_create_get(self, repo, body) -> None:
        doc = make_document(entity_id="npc-test", body=body)
        created = repo.create_entity(doc, audit=make_audit_context("op-001"))
        assert created.body == body
        assert repo.get_entity("npc-test").body == body

    @pytest.mark.parametrize(
        "body",
        [
            "line1\nline2\n",
            "line1\r\nline2\r\n",
            "no trailing newline",
            "Unicode: \u041f\u0440\u0438\u0432\u0435\u0442\n\u041c\u0438\u0440\n",
        ],
        ids=["LF", "CRLF", "no_trailing", "unicode"],
    )
    def test_newline_preserved_through_patch(self, repo, body) -> None:
        doc = make_document(entity_id="npc-test", body=body)
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        patched = repo.patch_entity(
            "npc-test",
            EntityPatch(name="New Name"),
            expected_revision=1,
            audit=make_audit_context("op-002"),
        )
        assert patched.body == body

    @pytest.mark.parametrize(
        "body",
        [
            "line1\nline2\n",
            "line1\r\nline2\r\n",
            "no trailing newline",
        ],
        ids=["LF", "CRLF", "no_trailing"],
    )
    def test_newline_preserved_through_append(self, repo, body) -> None:
        doc = make_document(entity_id="npc-test", body=body)
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        appended = repo.append_entity_fact(
            "npc-test",
            expected_revision=1,
            fact="A fact",
            audit=make_audit_context("op-002"),
        )
        assert appended.body.startswith(body)
        assert "- A fact" in appended.body


# ═════════════════════════════════════════════════════════════════════════════
# 6. Extra-frontmatter preservation
# ═════════════════════════════════════════════════════════════════════════════


class TestExtraFrontmatterPreservation:
    """Verify non-core YAML frontmatter survives mutations."""

    EXTRA = {
        "aliases": ["Mithrandir", "Ol\u00f3rin"],
        "faction": "Istari",
        "custom_nested": {"order": 2, "title": "Grey"},
        "unicode_value": "\u042d\u043b\u044c\u0444\u0438\u0439\u0441\u043a\u0438\u0439",
    }

    def test_extra_survives_create_get(self, repo) -> None:
        doc = make_document(entity_id="npc-gandalf", extra=self.EXTRA)
        created = repo.create_entity(doc, audit=make_audit_context("op-001"))
        assert created.extra_frontmatter == self.EXTRA
        assert repo.get_entity("npc-gandalf").extra_frontmatter == self.EXTRA

    def test_extra_survives_patch(self, repo) -> None:
        doc = make_document(entity_id="npc-gandalf", extra=self.EXTRA)
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        patched = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Gandalf the White"),
            expected_revision=1,
            audit=make_audit_context("op-002"),
        )
        assert patched.extra_frontmatter == self.EXTRA
        assert repo.get_entity("npc-gandalf").extra_frontmatter == self.EXTRA

    def test_extra_survives_append(self, repo) -> None:
        doc = make_document(entity_id="npc-gandalf", extra=self.EXTRA)
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        appended = repo.append_entity_fact(
            "npc-gandalf",
            expected_revision=1,
            fact="New fact",
            audit=make_audit_context("op-002"),
        )
        assert appended.extra_frontmatter == self.EXTRA
        assert repo.get_entity("npc-gandalf").extra_frontmatter == self.EXTRA


# ═════════════════════════════════════════════════════════════════════════════
# 7. Multi-type integration
# ═════════════════════════════════════════════════════════════════════════════


class TestMultiTypeIntegration:
    """Verify all four MVP entity types work correctly."""

    def test_all_types_create_and_list(self, repo) -> None:
        npc = make_document(entity_id="npc-gandalf", entity_type=EntityType.NPC, name="Gandalf")
        loc = make_document(
            entity_id="loc-shire", entity_type=EntityType.LOCATION, name="The Shire"
        )
        quest = make_document(
            entity_id="qst-ring", entity_type=EntityType.QUEST, name="Destroy Ring"
        )
        item = make_document(entity_id="itm-ring", entity_type=EntityType.ITEM, name="One Ring")

        npc_c = repo.create_entity(npc, audit=make_audit_context("op-001"))
        loc_c = repo.create_entity(loc, audit=make_audit_context("op-002"))
        quest_c = repo.create_entity(quest, audit=make_audit_context("op-003"))
        item_c = repo.create_entity(item, audit=make_audit_context("op-004"))

        assert npc_c.entity.type == EntityType.NPC
        assert loc_c.entity.type == EntityType.LOCATION
        assert quest_c.entity.type == EntityType.QUEST
        assert item_c.entity.type == EntityType.ITEM

        # List all
        all_entities = repo.list_entities()
        assert len(all_entities) == 4

        # Type-filtered listing
        npcs = repo.list_entities(entity_type=EntityType.NPC)
        assert len(npcs) == 1
        assert npcs[0].entity.id == "npc-gandalf"

        locations = repo.list_entities(entity_type=EntityType.LOCATION)
        assert len(locations) == 1

        quests = repo.list_entities(entity_type=EntityType.QUEST)
        assert len(quests) == 1

        items = repo.list_entities(entity_type=EntityType.ITEM)
        assert len(items) == 1

        # IDs globally unique
        assert_vault_valid(repo)

    def test_mutation_stays_in_correct_directory(self, repo, vault_root) -> None:
        from dnd_assistant.storage.paths import entity_directory

        npc = make_document(entity_id="npc-test", entity_type=EntityType.NPC)
        repo.create_entity(npc, audit=make_audit_context("op-001"))

        loc = make_document(entity_id="loc-test", entity_type=EntityType.LOCATION)
        repo.create_entity(loc, audit=make_audit_context("op-002"))

        # Find NPC file - must be in Characters/NPCs
        npc_file = find_entity_file(repo, "npc-test")
        npc_dir = entity_directory(vault_root, EntityType.NPC)
        assert npc_file.parent == npc_dir or npc_dir in npc_file.parents

        # Find Location file - must be in Locations
        loc_file = find_entity_file(repo, "loc-test")
        loc_dir = entity_directory(vault_root, EntityType.LOCATION)
        assert loc_file.parent == loc_dir or loc_dir in loc_file.parents


# ═════════════════════════════════════════════════════════════════════════════
# 8. Human filename rename integration
# ═════════════════════════════════════════════════════════════════════════════


class TestHumanFilenameRename:
    """Repository identity must survive Obsidian-side filename rename."""

    def test_rename_survives_get_patch_append(self, repo, vault_root) -> None:
        doc = make_document(entity_id="npc-gandalf", name="Gandalf")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        # Identify generated file
        entity_file = find_entity_file(repo, "npc-gandalf")
        assert entity_file.name.startswith("entity-")

        # Rename manually to a human filename
        from dnd_assistant.storage.paths import entity_directory

        npc_dir = entity_directory(vault_root, EntityType.NPC)
        human_path = npc_dir / "Gandalf.md"
        entity_file.rename(human_path)

        # Get by EntityId still works
        fetched = repo.get_entity("npc-gandalf")
        assert fetched.entity.id == "npc-gandalf"
        assert fetched.entity.name == "Gandalf"

        # Patch still works
        patched = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Gandalf the White"),
            expected_revision=1,
            audit=make_audit_context("op-002"),
        )
        assert patched.entity.name == "Gandalf the White"
        assert patched.entity.revision == 2

        # Append fact still works
        appended = repo.append_entity_fact(
            "npc-gandalf",
            expected_revision=2,
            fact="Is a Maia",
            audit=make_audit_context("op-003"),
        )
        assert "- Is a Maia" in appended.body
        assert appended.entity.revision == 3

        # Get again
        fetched2 = repo.get_entity("npc-gandalf")
        assert fetched2.entity.revision == 3

        # No duplicate/generated file appeared
        from dnd_assistant.storage.paths import discover_entity_files

        candidates = discover_entity_files(vault_root)
        md_files = [c.path for c in candidates]
        assert human_path in md_files
        # Only one file for this entity
        assert sum(1 for p in md_files if "Gandalf" in p.name) == 1
