"""Unit tests for S10-04 ChangeSet apply orchestration.

Exercises :func:`apply_changeset` against a deterministic in-memory
``FakeVaultRepository`` and asserts the Stage-10 apply invariants:

- I3  review required (rejected/wrong id/wrong fingerprint -> zero writes);
- I4  stale revision fail-close via fresh preflight;
- I5  whole-batch preflight before the first mutation;
- I6  duplicate/existing create fails;
- I7  mutations only through the repository protocol;
- I8  revision behavior / same-batch chain;
- I9  trusted audit context + proposal provenance;
- I10 cross-operation consistency.

Failure semantics (APPLIED/PARTIAL/FAILED) use repository-injected failures,
never filesystem tricks.
"""

from __future__ import annotations

import ast
import builtins
import inspect
import pathlib
from datetime import UTC, datetime
from typing import Any

import pytest

from dnd_assistant.application import changeset_apply
from dnd_assistant.application.changeset_apply import (
    ApplyFailureCategory,
    ChangeSetApplyContext,
    ChangeSetApplyOutcome,
    apply_changeset,
)
from dnd_assistant.application.changeset_review import (
    ChangeSetApproval,
    ReviewDecision,
    compute_changeset_fingerprint,
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
    EntityType,
    KnowledgeStatus,
    Provenance,
    Visibility,
)
from dnd_assistant.errors import ConflictError, NotFoundError
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.storage.patch import EntityPatch
from dnd_assistant.storage.types import VaultDocument

# ── Deterministic doubles ─────────────────────────────────────────────────

_T0 = datetime(2024, 1, 1, tzinfo=UTC)
_APPLY_TIME = datetime(2024, 6, 1, 12, 30, tzinfo=UTC)

_ALLOWLIST = (
    "name",
    "status",
    "visibility",
    "knowledge_status",
    "created_session",
    "last_seen_session",
    "tags",
)


def _entity(entity_id: str, revision: int = 1) -> Entity:
    return Entity(
        id=entity_id,
        type=EntityType.NPC,
        name=f"Entity {entity_id}",
        status="alive",
        visibility=Visibility.DM,
        knowledge_status=KnowledgeStatus.CONFIRMED,
        created_at=_T0,
        updated_at=_T0,
        revision=revision,
    )


def _document(entity_id: str, revision: int = 1) -> VaultDocument:
    return VaultDocument(entity=_entity(entity_id, revision))


class FakeVaultRepository:
    """Deterministic repository double with a full mutation-call log."""

    def __init__(self, documents: list[VaultDocument] | None = None) -> None:
        self._documents: dict[str, VaultDocument] = {}
        for doc in documents or []:
            self._documents[doc.entity.id] = doc
        self.calls: list[dict[str, Any]] = []
        self.failures: dict[str, Exception] = {}

    def _record(self, **call: Any) -> None:
        self.calls.append(call)

    def _maybe_fail(self, entity_id: str) -> None:
        failure = self.failures.get(entity_id)
        if failure is not None:
            raise failure

    def get_entity(self, entity_id: str) -> VaultDocument:
        doc = self._documents.get(entity_id)
        if doc is None:
            raise NotFoundError(f"Entity not found: {entity_id}")
        return doc

    def list_entities(self, entity_type: EntityType | None = None) -> list[VaultDocument]:
        return list(self._documents.values())

    def create_entity(self, document: VaultDocument, *, audit: AuditContext) -> VaultDocument:
        entity_id = document.entity.id
        self._record(method="create_entity", entity_id=entity_id, document=document, audit=audit)
        self._maybe_fail(entity_id)
        if entity_id in self._documents:
            raise ConflictError(f"Entity with ID {entity_id!r} already exists")
        self._documents[entity_id] = document
        return document

    def patch_entity(
        self,
        entity_id: str,
        patch: EntityPatch,
        *,
        expected_revision: int,
        audit: AuditContext,
    ) -> VaultDocument:
        self._record(
            method="patch_entity",
            entity_id=entity_id,
            patch=patch,
            expected_revision=expected_revision,
            audit=audit,
        )
        self._maybe_fail(entity_id)
        doc = self._documents.get(entity_id)
        if doc is None:
            raise NotFoundError(f"Entity not found: {entity_id}")
        stored = doc.entity
        if stored.revision != expected_revision:
            raise ConflictError(f"Revision mismatch for {entity_id!r}")
        data = stored.model_dump()
        for field_name in patch.model_fields_set:
            value = getattr(patch, field_name)
            if field_name == "tags" and value is not None:
                data[field_name] = list(value)
            else:
                data[field_name] = value
        data["revision"] = stored.revision + 1
        data["updated_at"] = audit.real_time
        new_doc = VaultDocument(
            entity=Entity.model_validate(data),
            extra_frontmatter=doc.extra_frontmatter,
            body=doc.body,
        )
        self._documents[entity_id] = new_doc
        return new_doc

    def append_entity_fact(
        self,
        entity_id: str,
        *,
        expected_revision: int,
        fact: str,
        audit: AuditContext,
    ) -> VaultDocument:
        self._record(
            method="append_entity_fact",
            entity_id=entity_id,
            expected_revision=expected_revision,
            fact=fact,
            audit=audit,
        )
        self._maybe_fail(entity_id)
        doc = self._documents.get(entity_id)
        if doc is None:
            raise NotFoundError(f"Entity not found: {entity_id}")
        stored = doc.entity
        if stored.revision != expected_revision:
            raise ConflictError(f"Revision mismatch for {entity_id!r}")
        data = stored.model_dump()
        data["revision"] = stored.revision + 1
        data["updated_at"] = audit.real_time
        new_doc = VaultDocument(
            entity=Entity.model_validate(data),
            extra_frontmatter=doc.extra_frontmatter,
            body=f"{doc.body}- {fact}\n",
        )
        self._documents[entity_id] = new_doc
        return new_doc


# ── Builders ──────────────────────────────────────────────────────────────


def _create(entity_id: str) -> CreateEntityOperation:
    return CreateEntityOperation(
        entity_id=entity_id,
        type=EntityType.NPC,
        name=f"Entity {entity_id}",
        status="alive",
        visibility=Visibility.DM,
        knowledge_status=KnowledgeStatus.CONFIRMED,
    )


def _update(entity_id: str, expected_revision: int, **fields: Any) -> UpdateEntityOperation:
    return UpdateEntityOperation(
        entity_id=entity_id,
        expected_revision=expected_revision,
        update=EntityFieldUpdate(**fields),
    )


def _append(entity_id: str, expected_revision: int, fact: str = "A fact") -> AppendFactOperation:
    return AppendFactOperation(
        entity_id=entity_id,
        expected_revision=expected_revision,
        fact=fact,
    )


def _changeset(
    *operations: object,
    changeset_id: str = "cs_test",
    session_ref: str | None = None,
    model_profile: str | None = None,
    prompt_version: str | None = None,
) -> ChangeSet:
    return ChangeSet(
        changeset_id=changeset_id,
        provenance=ProposalProvenance(
            provenance=Provenance.MANUAL,
            model_profile=model_profile,
            prompt_version=prompt_version,
        ),
        session_ref=session_ref,
        operations=operations,  # type: ignore[arg-type]
    )


def _approval(
    changeset: ChangeSet,
    *,
    decision: ReviewDecision = ReviewDecision.APPROVED,
    changeset_id: str | None = None,
    fingerprint: object | None = None,
) -> ChangeSetApproval:
    return ChangeSetApproval(
        changeset_id=changeset_id or changeset.changeset_id,
        fingerprint=fingerprint or compute_changeset_fingerprint(changeset),  # type: ignore[arg-type]
        decision=decision,
        reviewer="reviewer-1",
    )


def _context(source: str = "changeset_apply") -> ChangeSetApplyContext:
    return ChangeSetApplyContext(source=source, real_time=_APPLY_TIME)


# ── I3 — approval gate ────────────────────────────────────────────────────


class TestApprovalGate:
    def test_rejected_decision_produces_zero_writes(self) -> None:
        changeset = _changeset(_create("npc_a"))
        repo = FakeVaultRepository()
        with pytest.raises(changeset_apply.ValidationError):
            apply_changeset(
                changeset,
                _approval(changeset, decision=ReviewDecision.REJECTED),
                repo,
                context=_context(),
            )
        assert repo.calls == []

    def test_wrong_changeset_id_produces_zero_writes(self) -> None:
        changeset = _changeset(_create("npc_a"))
        repo = FakeVaultRepository()
        with pytest.raises(changeset_apply.ValidationError):
            apply_changeset(
                changeset, _approval(changeset, changeset_id="cs_other"), repo, context=_context()
            )
        assert repo.calls == []

    def test_wrong_fingerprint_produces_zero_writes(self) -> None:
        changeset = _changeset(_create("npc_a"))
        other = _changeset(_create("npc_b"))
        repo = FakeVaultRepository()
        with pytest.raises(changeset_apply.ValidationError):
            apply_changeset(
                changeset,
                _approval(changeset, fingerprint=compute_changeset_fingerprint(other)),
                repo,
                context=_context(),
            )
        assert repo.calls == []

    def test_approval_is_a_required_parameter(self) -> None:
        signature = inspect.signature(apply_changeset)
        approval = signature.parameters["approval"]
        assert approval.default is inspect.Parameter.empty


# ── I4 / I5 / I6 — fresh preflight ────────────────────────────────────────


class TestFreshPreflight:
    def test_stale_revision_detected_by_fresh_preflight(self) -> None:
        changeset = _changeset(_update("npc_a", 1, status="dead"))
        repo = FakeVaultRepository([_document("npc_a", revision=1)])
        approval = _approval(changeset)

        # Simulate another writer advancing the Vault after review.
        repo._documents["npc_a"] = _document("npc_a", revision=2)

        with pytest.raises(changeset_apply.ValidationError):
            apply_changeset(changeset, approval, repo, context=_context())
        assert repo.calls == []

    def test_later_invalid_operation_causes_whole_batch_zero_writes(self) -> None:
        changeset = _changeset(
            _update("npc_a", 1, status="dead"),
            _update("npc_missing", 1, status="dead"),
        )
        repo = FakeVaultRepository([_document("npc_a", revision=1)])
        with pytest.raises(changeset_apply.ValidationError):
            apply_changeset(changeset, _approval(changeset), repo, context=_context())
        assert repo.calls == []

    def test_existing_create_target_produces_zero_writes(self) -> None:
        changeset = _changeset(_create("npc_a"))
        repo = FakeVaultRepository([_document("npc_a", revision=1)])
        with pytest.raises(changeset_apply.ValidationError):
            apply_changeset(changeset, _approval(changeset), repo, context=_context())
        assert repo.calls == []

    def test_duplicate_create_produces_zero_writes(self) -> None:
        changeset = _changeset(_create("npc_a"), _create("npc_a"))
        repo = FakeVaultRepository()
        with pytest.raises(changeset_apply.ValidationError):
            apply_changeset(changeset, _approval(changeset), repo, context=_context())
        assert repo.calls == []


# ── Create / update / append mapping ──────────────────────────────────────


class TestCreateMapping:
    def test_create_uses_trusted_revision_and_timestamps(self) -> None:
        changeset = _changeset(_create("npc_a"))
        repo = FakeVaultRepository()
        result = apply_changeset(changeset, _approval(changeset), repo, context=_context())

        assert result.outcome is ChangeSetApplyOutcome.APPLIED
        assert [call["method"] for call in repo.calls] == ["create_entity"]
        document = repo.calls[0]["document"]
        entity = document.entity
        assert entity.id == "npc_a"
        assert entity.revision == 1
        assert entity.created_at == _APPLY_TIME
        assert entity.updated_at == _APPLY_TIME
        assert document.body == ""
        assert document.extra_frontmatter == {}

    def test_create_does_not_accept_path_authority(self) -> None:
        changeset = _changeset(_create("npc_a"))
        repo = FakeVaultRepository()
        apply_changeset(changeset, _approval(changeset), repo, context=_context())
        assert not hasattr(repo.calls[0]["document"], "path")


class TestUpdateMapping:
    def test_allowlist_only_and_expected_revision_unchanged(self) -> None:
        changeset = _changeset(_update("npc_a", 3, status="dead", tags=("hero", "fallen")))
        repo = FakeVaultRepository([_document("npc_a", revision=3)])
        result = apply_changeset(changeset, _approval(changeset), repo, context=_context())

        assert result.outcome is ChangeSetApplyOutcome.APPLIED
        call = repo.calls[0]
        assert call["method"] == "patch_entity"
        assert call["expected_revision"] == 3
        patch: EntityPatch = call["patch"]
        assert set(patch.model_fields_set) <= set(_ALLOWLIST)
        assert patch.status == "dead"
        assert patch.tags == ["hero", "fallen"]

    def test_omitted_fields_remain_omitted(self) -> None:
        changeset = _changeset(_update("npc_a", 1, status="dead"))
        repo = FakeVaultRepository([_document("npc_a", revision=1)])
        apply_changeset(changeset, _approval(changeset), repo, context=_context())

        patch: EntityPatch = repo.calls[0]["patch"]
        assert patch.model_fields_set == {"status"}

    def test_explicit_none_session_field_is_explicit_clear(self) -> None:
        changeset = _changeset(_update("npc_a", 1, created_session=None))
        repo = FakeVaultRepository([_document("npc_a", revision=1)])
        apply_changeset(changeset, _approval(changeset), repo, context=_context())

        patch: EntityPatch = repo.calls[0]["patch"]
        assert "created_session" in patch.model_fields_set
        assert patch.created_session is None

    def test_tags_replacement_semantics(self) -> None:
        changeset = _changeset(_update("npc_a", 1, tags=("only",)))
        repo = FakeVaultRepository([_document("npc_a", revision=1)])
        apply_changeset(changeset, _approval(changeset), repo, context=_context())
        persisted = repo._documents["npc_a"].entity
        assert persisted.tags == ["only"]


class TestAppendMapping:
    def test_append_uses_repository_method_without_body_edits(self) -> None:
        changeset = _changeset(_append("npc_a", 1, fact="Slain at the gate"))
        repo = FakeVaultRepository([_document("npc_a", revision=1)])
        result = apply_changeset(changeset, _approval(changeset), repo, context=_context())

        assert result.outcome is ChangeSetApplyOutcome.APPLIED
        call = repo.calls[0]
        assert call["method"] == "append_entity_fact"
        assert call["fact"] == "Slain at the gate"
        assert call["expected_revision"] == 1
        assert repo._documents["npc_a"].body == "- Slain at the gate\n"


# ── I8 / I10 — same-batch chain ───────────────────────────────────────────


class TestSameBatchChain:
    def test_create_append_update_in_exact_order(self) -> None:
        changeset = _changeset(
            _create("npc_x"),
            _append("npc_x", 1),
            _update("npc_x", 2, status="dead"),
        )
        repo = FakeVaultRepository()
        result = apply_changeset(changeset, _approval(changeset), repo, context=_context())

        assert result.outcome is ChangeSetApplyOutcome.APPLIED
        assert result.applied_operation_indices == (0, 1, 2)
        assert result.remaining_operation_indices == ()
        assert result.failure is None
        assert [call["method"] for call in repo.calls] == [
            "create_entity",
            "append_entity_fact",
            "patch_entity",
        ]
        assert repo.calls[2]["expected_revision"] == 2
        assert repo._documents["npc_x"].entity.revision == 3


# ── I9 — audit context ────────────────────────────────────────────────────


class TestAuditContext:
    def test_per_operation_audit_is_trusted_and_derived(self) -> None:
        changeset = _changeset(
            _create("npc_a"),
            _append("npc_a", 1),
            changeset_id="cs_audit",
            session_ref="S007",
            model_profile="llama3",
            prompt_version="v2",
        )
        repo = FakeVaultRepository()
        apply_changeset(
            changeset, _approval(changeset), repo, context=_context(source="changeset_apply")
        )

        for index, call in enumerate(repo.calls):
            audit: AuditContext = call["audit"]
            assert audit.operation_id == f"cs_audit:{index}"
            assert audit.source == "changeset_apply"
            assert audit.real_time == _APPLY_TIME
            assert audit.session == "S007"
            assert audit.model_profile == "llama3"
            assert audit.prompt_version == "v2"

    def test_proposal_text_cannot_become_audit_source(self) -> None:
        changeset = _changeset(
            _create("npc_a"),
            model_profile="model_text_not_source",
        )
        repo = FakeVaultRepository()
        apply_changeset(changeset, _approval(changeset), repo, context=_context(source="trusted"))
        audit: AuditContext = repo.calls[0]["audit"]
        assert audit.source == "trusted"


# ── Failure semantics ─────────────────────────────────────────────────────


class TestFailureSemantics:
    def test_write_failure_at_op0_is_failed(self) -> None:
        changeset = _changeset(
            _update("npc_a", 1, status="dead"),
            _update("npc_b", 1, status="dead"),
        )
        repo = FakeVaultRepository([_document("npc_a"), _document("npc_b")])
        repo.failures["npc_a"] = ConflictError("revision changed")

        result = apply_changeset(changeset, _approval(changeset), repo, context=_context())

        assert result.outcome is ChangeSetApplyOutcome.FAILED
        assert result.applied_operation_indices == ()
        assert result.remaining_operation_indices == (1,)
        assert result.failure is not None
        assert result.failure.operation_index == 0
        assert result.failure.category is ApplyFailureCategory.CONFLICT
        assert result.failure.message == "revision changed"
        assert [call["method"] for call in repo.calls] == ["patch_entity"]

    def test_write_failure_after_success_is_partial_and_stops(self) -> None:
        changeset = _changeset(
            _update("npc_a", 1, status="dead"),
            _update("npc_b", 1, status="dead"),
            _update("npc_c", 1, status="dead"),
        )
        repo = FakeVaultRepository([_document("npc_a"), _document("npc_b"), _document("npc_c")])
        repo.failures["npc_b"] = ConflictError("revision changed")

        result = apply_changeset(changeset, _approval(changeset), repo, context=_context())

        assert result.outcome is ChangeSetApplyOutcome.PARTIAL
        assert result.applied_operation_indices == (0,)
        assert result.remaining_operation_indices == (2,)
        assert result.failure is not None
        assert result.failure.operation_index == 1
        assert result.failure.category is ApplyFailureCategory.CONFLICT
        # op0 wrote, op1 attempted and failed, op2 never attempted.
        assert [call["method"] for call in repo.calls] == ["patch_entity", "patch_entity"]
        assert repo.calls[1]["entity_id"] == "npc_b"
        assert "npc_c" not in repo._documents or repo._documents["npc_c"].entity.status == "alive"

    def test_full_success_reports_applied(self) -> None:
        changeset = _changeset(_update("npc_a", 1, status="dead"))
        repo = FakeVaultRepository([_document("npc_a")])
        result = apply_changeset(changeset, _approval(changeset), repo, context=_context())

        assert result.outcome is ChangeSetApplyOutcome.APPLIED
        assert result.succeeded is True
        assert result.applied_operation_indices == (0,)
        assert result.remaining_operation_indices == ()
        assert result.failure is None

    def test_unexpected_exception_propagates_unchanged(self) -> None:
        changeset = _changeset(_update("npc_a", 1, status="dead"))
        repo = FakeVaultRepository([_document("npc_a")])
        repo.failures["npc_a"] = RuntimeError("programmer error")

        with pytest.raises(RuntimeError, match="programmer error"):
            apply_changeset(changeset, _approval(changeset), repo, context=_context())


# ── I7 — no direct filesystem mutation ────────────────────────────────────


def _module_tree() -> ast.Module:
    return ast.parse(inspect.getsource(changeset_apply))


def test_module_imports_no_filesystem_or_upper_layers() -> None:
    targets: set[str] = set()
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            targets.add(node.module)

    forbidden_roots = {"pathlib", "os", "shutil", "tempfile", "subprocess", "ollama", "pydantic_ai"}
    forbidden_prefixes = (
        "dnd_assistant.models",
        "dnd_assistant.tools",
        "dnd_assistant.cli",
        "dnd_assistant.retrieval",
    )
    offending = sorted(
        target
        for target in targets
        if target.split(".")[0] in forbidden_roots or target.startswith(forbidden_prefixes)
    )
    assert not offending, f"changeset_apply imported forbidden modules: {offending}"


def test_module_calls_only_repository_mutation_methods() -> None:
    repo_methods = {
        node.func.attr
        for node in ast.walk(_module_tree())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "repository"
    }
    assert repo_methods <= {"create_entity", "patch_entity", "append_entity_fact"}


def test_module_has_no_direct_filesystem_calls() -> None:
    tree = _module_tree()
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    forbidden_attributes = {
        "write_text",
        "write_bytes",
        "mkdir",
        "unlink",
        "rmdir",
        "rename",
        "replace",
        "chmod",
    }
    assert called_attributes.isdisjoint(forbidden_attributes)
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "open" not in called_names


def test_apply_performs_no_filesystem_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("apply_changeset must not touch the filesystem")

    monkeypatch.setattr(builtins, "open", _forbidden)
    monkeypatch.setattr(pathlib.Path, "write_text", _forbidden)

    changeset = _changeset(_create("npc_a"), _append("npc_a", 1))
    repo = FakeVaultRepository()
    result = apply_changeset(changeset, _approval(changeset), repo, context=_context())
    assert result.outcome is ChangeSetApplyOutcome.APPLIED
