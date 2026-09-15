"""Unit tests for S10-02 pure ChangeSet validation / whole-batch preflight.

Exercises :func:`validate_changeset` against in-memory repository doubles and
asserts the Stage-10 trust-boundary invariants it owns:

- I2  validation is side-effect free (zero repository write calls);
- I5  whole-batch preflight resolves every operation before any mutation;
- I6  duplicate/existing creates fail deterministically;
- I10 same-batch dependencies (create X then update/append X) resolve.

The validator is pure; tests assert on the immutable result data, not on
internal state.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from dnd_assistant.application import changeset_validation
from dnd_assistant.application.changeset_validation import (
    ValidationIssue,
    ValidationIssueCode,
    validate_changeset,
)
from dnd_assistant.domain.changeset import (
    AppendFactOperation,
    ChangeSet,
    CreateEntityOperation,
    EntityFieldUpdate,
    ProposalProvenance,
    UpdateEntityOperation,
)
from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import (
    EntityId,
    EntityType,
    KnowledgeStatus,
    Provenance,
    Revision,
    Visibility,
)
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.storage.patch import EntityPatch
from dnd_assistant.storage.types import VaultDocument
from tests.support.repository_doubles import VaultRepositoryWriteStubs

# ── Repository double with a write spy ────────────────────────────────────

_T0 = datetime(2024, 1, 1, tzinfo=UTC)


class SpyVaultRepository(VaultRepositoryWriteStubs):
    """Read-only repository double that counts any attempted mutation."""

    def __init__(self, documents: list[VaultDocument] | None = None) -> None:
        self.write_calls = 0
        self._documents = list(documents) if documents else []

    def get_entity(self, entity_id: EntityId) -> VaultDocument:
        raise AssertionError("validator must not call get_entity")

    def list_entities(self, entity_type: EntityType | None = None) -> list[VaultDocument]:
        return list(self._documents)

    def create_entity(self, document: VaultDocument, *, audit: AuditContext) -> VaultDocument:
        self.write_calls += 1
        raise AssertionError("validator must not write")

    def patch_entity(
        self,
        entity_id: EntityId,
        patch: EntityPatch,
        *,
        expected_revision: Revision,
        audit: AuditContext,
    ) -> VaultDocument:
        self.write_calls += 1
        raise AssertionError("validator must not write")

    def append_entity_fact(
        self,
        entity_id: EntityId,
        *,
        expected_revision: Revision,
        fact: str,
        audit: AuditContext,
    ) -> VaultDocument:
        self.write_calls += 1
        raise AssertionError("validator must not write")


# ── Builders ──────────────────────────────────────────────────────────────


def _document(
    entity_id: str,
    revision: int,
    entity_type: EntityType = EntityType.NPC,
) -> VaultDocument:
    entity = Entity(
        id=entity_id,
        type=entity_type,
        name=f"Entity {entity_id}",
        status="active",
        visibility=Visibility.DM,
        knowledge_status=KnowledgeStatus.CONFIRMED,
        created_at=_T0,
        updated_at=_T0,
        revision=revision,
    )
    return VaultDocument(entity=entity)


def _create(entity_id: str, entity_type: EntityType = EntityType.NPC) -> CreateEntityOperation:
    return CreateEntityOperation(
        entity_id=entity_id,
        type=entity_type,
        name=f"Entity {entity_id}",
        status="active",
        visibility=Visibility.DM,
        knowledge_status=KnowledgeStatus.CONFIRMED,
    )


def _update(entity_id: str, expected_revision: int) -> UpdateEntityOperation:
    return UpdateEntityOperation(
        entity_id=entity_id,
        expected_revision=expected_revision,
        update=EntityFieldUpdate(status="dead"),
    )


def _append(entity_id: str, expected_revision: int) -> AppendFactOperation:
    return AppendFactOperation(
        entity_id=entity_id,
        expected_revision=expected_revision,
        fact="A fact",
    )


def _changeset(*operations: object) -> ChangeSet:
    return ChangeSet(
        changeset_id="cs_test",
        provenance=ProposalProvenance(provenance=Provenance.MANUAL),
        operations=operations,  # type: ignore[arg-type]
    )


# ── Valid semantics ───────────────────────────────────────────────────────


class TestValidSemantics:
    def test_empty_repository_create_is_valid(self) -> None:
        result = validate_changeset(_changeset(_create("npc_a")), SpyVaultRepository())
        assert result.valid is True
        assert result.issues == ()

    def test_update_existing_entity_is_valid(self) -> None:
        repo = SpyVaultRepository([_document("npc_a", 4)])
        result = validate_changeset(_changeset(_update("npc_a", 4)), repo)
        assert result.valid is True

    def test_append_existing_entity_is_valid(self) -> None:
        repo = SpyVaultRepository([_document("npc_a", 2)])
        result = validate_changeset(_changeset(_append("npc_a", 2)), repo)
        assert result.valid is True

    def test_create_then_update_then_append_chain_is_valid(self) -> None:
        changeset = _changeset(
            _create("npc_a"),
            _update("npc_a", 1),
            _append("npc_a", 2),
        )
        result = validate_changeset(changeset, SpyVaultRepository())
        assert result.issues == ()
        assert result.valid is True

    def test_projected_revision_chain_matches_repository_rule(self) -> None:
        repo = SpyVaultRepository([_document("npc_a", 4)])
        changeset = _changeset(_update("npc_a", 4), _append("npc_a", 5))
        result = validate_changeset(changeset, repo)
        assert result.valid is True

    def test_wrong_second_projected_revision_is_invalid(self) -> None:
        repo = SpyVaultRepository([_document("npc_a", 4)])
        changeset = _changeset(_update("npc_a", 4), _append("npc_a", 4))
        result = validate_changeset(changeset, repo)
        assert [issue.code for issue in result.issues] == [ValidationIssueCode.REVISION_CONFLICT]
        assert result.issues[0].operation_index == 1


# ── Create semantics ──────────────────────────────────────────────────────


class TestCreateSemantics:
    def test_create_existing_target_is_reported(self) -> None:
        repo = SpyVaultRepository([_document("npc_a", 7)])
        result = validate_changeset(_changeset(_create("npc_a")), repo)
        assert result.valid is False
        issue = result.issues[0]
        assert issue.code == ValidationIssueCode.CREATE_TARGET_EXISTS
        assert issue.operation_index == 0
        assert issue.entity_id == "npc_a"

    def test_duplicate_create_in_batch_is_reported(self) -> None:
        changeset = _changeset(_create("npc_a"), _create("npc_a"))
        result = validate_changeset(changeset, SpyVaultRepository())
        assert [issue.code for issue in result.issues] == [ValidationIssueCode.DUPLICATE_CREATE]
        assert result.issues[0].operation_index == 1
        assert result.issues[0].entity_id == "npc_a"

    def test_existing_target_then_duplicate_create_reports_both(self) -> None:
        repo = SpyVaultRepository([_document("npc_a", 7)])
        result = validate_changeset(_changeset(_create("npc_a"), _create("npc_a")), repo)
        assert [issue.code for issue in result.issues] == [
            ValidationIssueCode.CREATE_TARGET_EXISTS,
            ValidationIssueCode.DUPLICATE_CREATE,
        ]
        assert [issue.operation_index for issue in result.issues] == [0, 1]
        assert [issue.entity_id for issue in result.issues] == ["npc_a", "npc_a"]

    def test_invalid_create_does_not_project_batch_revision(self) -> None:
        repo = SpyVaultRepository([_document("npc_a", 7)])
        changeset = _changeset(
            _create("npc_a"),
            _create("npc_a"),
            _update("npc_a", 7),
        )
        result = validate_changeset(changeset, repo)
        assert [issue.code for issue in result.issues] == [
            ValidationIssueCode.CREATE_TARGET_EXISTS,
            ValidationIssueCode.DUPLICATE_CREATE,
        ]

    def test_duplicate_create_in_empty_repo_does_not_project_revision(self) -> None:
        changeset = _changeset(
            _create("npc_a"),
            _create("npc_a"),
            _update("npc_a", 1),
        )
        result = validate_changeset(changeset, SpyVaultRepository())
        assert [issue.code for issue in result.issues] == [ValidationIssueCode.DUPLICATE_CREATE]

    def test_distinct_batch_creates_are_valid(self) -> None:
        changeset = _changeset(_create("npc_a"), _create("npc_b"))
        result = validate_changeset(changeset, SpyVaultRepository())
        assert result.valid is True


# ── Target / revision guards ──────────────────────────────────────────────


class TestTargetAndRevisionGuards:
    @pytest.mark.parametrize(
        "operation",
        [_update("npc_missing", 1), _append("npc_missing", 1)],
    )
    def test_missing_target_is_reported(self, operation: object) -> None:
        result = validate_changeset(_changeset(operation), SpyVaultRepository())
        assert [issue.code for issue in result.issues] == [ValidationIssueCode.TARGET_NOT_FOUND]

    @pytest.mark.parametrize(
        "operation",
        [_update("npc_a", 99), _append("npc_a", 99)],
    )
    def test_stale_revision_is_reported(self, operation: object) -> None:
        repo = SpyVaultRepository([_document("npc_a", 4)])
        result = validate_changeset(_changeset(operation), repo)
        issue = result.issues[0]
        assert issue.code == ValidationIssueCode.REVISION_CONFLICT
        assert issue.entity_id == "npc_a"

    def test_failed_operation_does_not_advance_projection(self) -> None:
        repo = SpyVaultRepository([_document("npc_a", 4)])
        changeset = _changeset(_update("npc_a", 99), _update("npc_a", 4))
        result = validate_changeset(changeset, repo)
        assert [issue.code for issue in result.issues] == [ValidationIssueCode.REVISION_CONFLICT]
        assert result.issues[0].operation_index == 0

    def test_missing_create_prerequisite_blocks_followup(self) -> None:
        changeset = _changeset(_update("npc_a", 1), _append("npc_a", 2))
        result = validate_changeset(changeset, SpyVaultRepository())
        assert [issue.code for issue in result.issues] == [
            ValidationIssueCode.TARGET_NOT_FOUND,
            ValidationIssueCode.TARGET_NOT_FOUND,
        ]


# ── Determinism and result contract ───────────────────────────────────────


class TestDeterminismAndResultContract:
    def test_issues_are_ordered_by_operation_index(self) -> None:
        changeset = _changeset(
            _update("npc_missing_1", 1),
            _create("npc_ok"),
            _update("npc_missing_2", 1),
        )
        result = validate_changeset(changeset, SpyVaultRepository())
        assert [issue.operation_index for issue in result.issues] == [0, 2]

    def test_repeated_validation_is_equal(self) -> None:
        changeset = _changeset(_update("npc_missing", 1))
        repo = SpyVaultRepository()
        assert validate_changeset(changeset, repo) == validate_changeset(changeset, repo)

    def test_result_and_issue_are_frozen(self) -> None:
        repo = SpyVaultRepository([_document("npc_a", 1)])
        result = validate_changeset(_changeset(_create("npc_a")), repo)
        assert result.issues
        with pytest.raises(ValidationError):
            result.issues = ()  # type: ignore[misc]
        with pytest.raises(ValidationError):
            result.issues[0].message = "x"  # type: ignore[misc]

    def test_issue_requires_operation_index(self) -> None:
        with pytest.raises(ValidationError):
            ValidationIssue(code=ValidationIssueCode.TARGET_NOT_FOUND, message="x")  # type: ignore[call-arg]

    def test_valid_is_derived_from_issues(self) -> None:
        assert changeset_validation.ChangeSetValidationResult(issues=()).valid is True
        issue = ValidationIssue(
            code=ValidationIssueCode.TARGET_NOT_FOUND,
            operation_index=0,
            message="x",
        )
        assert changeset_validation.ChangeSetValidationResult(issues=(issue,)).valid is False


# ── I2: no side effects ───────────────────────────────────────────────────


class TestNoWrites:
    def test_valid_input_performs_zero_writes(self) -> None:
        repo = SpyVaultRepository([_document("npc_a", 4)])
        validate_changeset(_changeset(_update("npc_a", 4)), repo)
        assert repo.write_calls == 0

    def test_invalid_input_performs_zero_writes(self) -> None:
        repo = SpyVaultRepository([_document("npc_a", 4)])
        changeset = _changeset(_create("npc_a"), _update("npc_missing", 1))
        validate_changeset(changeset, repo)
        assert repo.write_calls == 0

    def test_module_source_has_no_write_method_references(self) -> None:
        tree = ast.parse(inspect.getsource(changeset_validation))
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        write_methods = {"create_entity", "patch_entity", "append_entity_fact"}
        assert attributes.isdisjoint(write_methods), (
            f"validator references write methods: {attributes & write_methods}"
        )
