"""Unit tests for S10-01 ChangeSet and change-operation domain schemas.

Covers ``ChangeSetId``, ``ProposalProvenance``, ``EntityFieldUpdate``, the
three accepted operations, the discriminated ``ChangeOperation`` union and the
immutable ``ChangeSet`` aggregate.

These tests are behavior-driven: they exercise the schemas directly and assert
the Stage-10 trust-boundary invariants (I1 no arbitrary path authority, I9
provenance round-trip) rather than inspecting source text.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from dnd_assistant.domain.changeset import (
    AppendFactOperation,
    ChangeOperation,
    ChangeSet,
    ChangeSetId,
    CreateEntityOperation,
    EntityFieldUpdate,
    ProposalProvenance,
    UpdateEntityOperation,
)
from dnd_assistant.domain.types import (
    EntityType,
    KnowledgeStatus,
    Provenance,
    Visibility,
)

# ── Shared fixtures / helpers ─────────────────────────────────────────────

_changeset_id_adapter: TypeAdapter[str] = TypeAdapter(ChangeSetId)
_change_operation_adapter: TypeAdapter[Any] = TypeAdapter(ChangeOperation)

STAGE_10_UPDATE_ALLOWLIST = frozenset(
    {
        "name",
        "status",
        "visibility",
        "knowledge_status",
        "created_session",
        "last_seen_session",
        "tags",
    }
)

FORBIDDEN_SEMANTIC_FIELDS = frozenset(
    {
        "path",
        "target_path",
        "file",
        "filename",
        "filesystem_path",
        "vault_path",
    }
)


def _create_payload() -> dict[str, Any]:
    return {
        "kind": "create_entity",
        "entity_id": "npc_01J",
        "type": "npc",
        "name": "Варос",
        "status": "alive",
        "visibility": "dm",
        "knowledge_status": "confirmed",
        "created_session": "S014",
        "last_seen_session": "S014",
        "tags": ("mentor",),
    }


def _update_payload() -> dict[str, Any]:
    return {
        "kind": "update_entity",
        "entity_id": "npc_01J",
        "expected_revision": 2,
        "update": {"status": "dead"},
    }


def _append_payload() -> dict[str, Any]:
    return {
        "kind": "append_fact",
        "entity_id": "npc_01J",
        "expected_revision": 3,
        "fact": "Убит у ворот",
    }


def _valid_changeset() -> ChangeSet:
    return ChangeSet(
        changeset_id="cs_01J",
        provenance=ProposalProvenance(
            provenance=Provenance.MODEL_INFERENCE,
            model_profile="post_session",
            prompt_version="v3",
        ),
        session_ref="S014",
        operations=(
            CreateEntityOperation.model_validate(_create_payload()),
            UpdateEntityOperation.model_validate(_update_payload()),
            AppendFactOperation.model_validate(_append_payload()),
        ),
    )


# ── ChangeSetId ───────────────────────────────────────────────────────────


class TestChangeSetId:
    @pytest.mark.parametrize(
        "valid_id",
        [
            "cs_01JXYZ",
            "a",
            "changeset-01",
            "proposal.with.dots",
            "набор_01",
        ],
    )
    def test_accepts_valid_ids(self, valid_id: str) -> None:
        assert _changeset_id_adapter.validate_python(valid_id) == valid_id

    @pytest.mark.parametrize(
        "invalid_id",
        [
            "",
            " ",
            "   ",
            "\t",
            "\n",
            " leading",
            "trailing ",
            " both ",
            "tab\tinside",
            "new\nline",
        ],
    )
    def test_rejects_empty_or_whitespace(self, invalid_id: str) -> None:
        with pytest.raises(ValidationError):
            _changeset_id_adapter.validate_python(invalid_id)

    def test_rejects_non_printable(self) -> None:
        with pytest.raises(ValidationError):
            _changeset_id_adapter.validate_python("cs\x00")

    def test_accepts_unicode_printable(self) -> None:
        assert _changeset_id_adapter.validate_python("набор-01") == "набор-01"

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValidationError):
            _changeset_id_adapter.validate_python(123)

    def test_distinct_type_from_entity_id(self) -> None:
        from dnd_assistant.domain.types import EntityId

        assert ChangeSetId is not EntityId


# ── Frozen / strict behavior ──────────────────────────────────────────────


FROZEN_MODELS: tuple[tuple[str, BaseModel], ...] = (
    (
        "ProposalProvenance",
        ProposalProvenance(provenance=Provenance.MANUAL),
    ),
    (
        "EntityFieldUpdate",
        EntityFieldUpdate(name="Gandalf"),
    ),
    (
        "CreateEntityOperation",
        CreateEntityOperation.model_validate(_create_payload()),
    ),
    (
        "UpdateEntityOperation",
        UpdateEntityOperation.model_validate(_update_payload()),
    ),
    (
        "AppendFactOperation",
        AppendFactOperation.model_validate(_append_payload()),
    ),
    ("ChangeSet", _valid_changeset()),
)


class TestStrictImmutable:
    @pytest.mark.parametrize(
        ("name", "instance"), FROZEN_MODELS, ids=lambda v: v if isinstance(v, str) else ""
    )
    def test_rejects_mutation(self, name: str, instance: BaseModel) -> None:
        field_name = next(iter(type(instance).model_fields))
        with pytest.raises(ValidationError):
            setattr(instance, field_name, "changed")

    @pytest.mark.parametrize(
        ("name", "instance"), FROZEN_MODELS, ids=lambda v: v if isinstance(v, str) else ""
    )
    def test_rejects_unknown_extra_field(self, name: str, instance: BaseModel) -> None:
        payload = instance.model_dump()
        payload["path"] = "/tmp/vault/npc.md"
        with pytest.raises(ValidationError):
            type(instance).model_validate(payload)


# ── ProposalProvenance ────────────────────────────────────────────────────


class TestProposalProvenance:
    def test_minimal_construction(self) -> None:
        provenance = ProposalProvenance(provenance=Provenance.MANUAL)
        assert provenance.provenance is Provenance.MANUAL
        assert provenance.model_profile is None
        assert provenance.prompt_version is None

    def test_optional_metadata_accepted(self) -> None:
        provenance = ProposalProvenance(
            provenance=Provenance.MODEL_INFERENCE,
            model_profile="post_session",
            prompt_version="v3",
        )
        assert provenance.model_profile == "post_session"
        assert provenance.prompt_version == "v3"

    def test_rejects_blank_metadata(self) -> None:
        with pytest.raises(ValidationError):
            ProposalProvenance(provenance=Provenance.MANUAL, model_profile="  ")

    def test_does_not_contain_session(self) -> None:
        assert "session_ref" not in ProposalProvenance.model_fields
        assert "session" not in ProposalProvenance.model_fields

    def test_rejects_unknown_extra_field(self) -> None:
        with pytest.raises(ValidationError):
            ProposalProvenance.model_validate(
                {"provenance": "manual", "path": "/tmp/proposal.json"}
            )


# ── EntityFieldUpdate ─────────────────────────────────────────────────────


class TestEntityFieldUpdateAllowlist:
    def test_exact_stage_10_allowlist(self) -> None:
        assert frozenset(EntityFieldUpdate.model_fields) == STAGE_10_UPDATE_ALLOWLIST

    @pytest.mark.parametrize(
        "forbidden",
        [
            "id",
            "type",
            "revision",
            "created_at",
            "updated_at",
            "body",
            "filename",
            "path",
            "extra_frontmatter",
        ],
    )
    def test_forbidden_field_absent(self, forbidden: str) -> None:
        assert forbidden not in EntityFieldUpdate.model_fields

    @pytest.mark.parametrize(
        "forbidden",
        ["id", "type", "revision", "created_at", "updated_at", "body", "path", "filename"],
    )
    def test_forbidden_field_rejected_on_construction(self, forbidden: str) -> None:
        with pytest.raises(ValidationError):
            EntityFieldUpdate.model_validate({forbidden: "value", "name": "ok"})


class TestEntityFieldUpdateBehavior:
    def test_empty_update_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EntityFieldUpdate()

    def test_single_field_update_accepted(self) -> None:
        update = EntityFieldUpdate(status="dead")
        assert update.status == "dead"

    def test_multi_field_update_accepted(self) -> None:
        update = EntityFieldUpdate(
            name="Gandalf the White",
            status="alive",
            visibility=Visibility.DM,
            knowledge_status=KnowledgeStatus.CONFIRMED,
            tags=("wizard", "istari"),
        )
        assert update.tags == ("wizard", "istari")

    def test_explicit_none_accepted_for_nullable_session_fields(self) -> None:
        created = EntityFieldUpdate(created_session=None)
        last_seen = EntityFieldUpdate(last_seen_session=None)
        assert created.created_session is None
        assert last_seen.last_seen_session is None
        assert "created_session" in created.model_fields_set
        assert "last_seen_session" in last_seen.model_fields_set

    @pytest.mark.parametrize(
        "field_name",
        ["name", "status", "visibility", "knowledge_status", "tags"],
    )
    def test_explicit_none_rejected_for_non_nullable(self, field_name: str) -> None:
        with pytest.raises(ValidationError):
            EntityFieldUpdate.model_validate({field_name: None})

    def test_unset_differs_from_explicit_none(self) -> None:
        explicit_none = EntityFieldUpdate(last_seen_session=None)
        unset = EntityFieldUpdate(name="Gandalf")
        assert "last_seen_session" in explicit_none.model_fields_set
        assert "last_seen_session" not in unset.model_fields_set
        assert explicit_none.model_dump() == {"last_seen_session": None}
        assert unset.model_dump() == {"name": "Gandalf"}

    def test_tags_replacement_semantics(self) -> None:
        update = EntityFieldUpdate(tags=("a", "b"))
        assert update.tags == ("a", "b")
        assert isinstance(update.tags, tuple)

    def test_rejects_invalid_field_value(self) -> None:
        with pytest.raises(ValidationError):
            EntityFieldUpdate(name="  padded  ")


# ── Operations ────────────────────────────────────────────────────────────


class TestCreateEntityOperation:
    def test_valid_create(self) -> None:
        operation = CreateEntityOperation.model_validate(_create_payload())
        assert operation.kind == "create_entity"
        assert operation.entity_id == "npc_01J"
        assert operation.type is EntityType.NPC
        assert operation.tags == ("mentor",)

    def test_defaults_are_domain_stable(self) -> None:
        payload = dict(_create_payload())
        payload.pop("tags")
        payload.pop("created_session")
        payload.pop("last_seen_session")
        operation = CreateEntityOperation.model_validate(payload)
        assert operation.tags == ()
        assert operation.created_session is None
        assert operation.last_seen_session is None

    @pytest.mark.parametrize(
        "forbidden",
        ["revision", "created_at", "updated_at", "body", "path", "filename"],
    )
    def test_forbidden_field_rejected(self, forbidden: str) -> None:
        payload = _create_payload()
        payload[forbidden] = "value"
        with pytest.raises(ValidationError):
            CreateEntityOperation.model_validate(payload)

    def test_requires_explicit_entity_id(self) -> None:
        payload = _create_payload()
        payload.pop("entity_id")
        with pytest.raises(ValidationError):
            CreateEntityOperation.model_validate(payload)


class TestUpdateEntityOperation:
    def test_valid_update(self) -> None:
        operation = UpdateEntityOperation.model_validate(_update_payload())
        assert operation.kind == "update_entity"
        assert operation.expected_revision == 2
        assert operation.update.status == "dead"

    def test_missing_expected_revision_rejected(self) -> None:
        payload = _update_payload()
        payload.pop("expected_revision")
        with pytest.raises(ValidationError):
            UpdateEntityOperation.model_validate(payload)

    @pytest.mark.parametrize("invalid_revision", [0, -1, "1", 1.0, True])
    def test_invalid_revision_rejected(self, invalid_revision: object) -> None:
        payload = _update_payload()
        payload["expected_revision"] = invalid_revision
        with pytest.raises(ValidationError):
            UpdateEntityOperation.model_validate(payload)

    def test_empty_update_payload_rejected(self) -> None:
        payload = _update_payload()
        payload["update"] = {}
        with pytest.raises(ValidationError):
            UpdateEntityOperation.model_validate(payload)

    @pytest.mark.parametrize("forbidden", ["path", "target_path", "file", "filename"])
    def test_path_extras_rejected(self, forbidden: str) -> None:
        payload = _update_payload()
        payload[forbidden] = "/tmp/npc.md"
        with pytest.raises(ValidationError):
            UpdateEntityOperation.model_validate(payload)


class TestAppendFactOperation:
    def test_valid_append(self) -> None:
        operation = AppendFactOperation.model_validate(_append_payload())
        assert operation.kind == "append_fact"
        assert operation.expected_revision == 3
        assert operation.fact == "Убит у ворот"

    def test_missing_expected_revision_rejected(self) -> None:
        payload = _append_payload()
        payload.pop("expected_revision")
        with pytest.raises(ValidationError):
            AppendFactOperation.model_validate(payload)

    @pytest.mark.parametrize(
        "invalid_fact",
        ["", " ", " leading", "trailing ", "line\nbreak", "tab\there", "ctrl\x00", 123, None],
    )
    def test_invalid_fact_rejected(self, invalid_fact: object) -> None:
        payload = _append_payload()
        payload["fact"] = invalid_fact
        with pytest.raises(ValidationError):
            AppendFactOperation.model_validate(payload)

    @pytest.mark.parametrize("forbidden", ["path", "file", "filename"])
    def test_path_extras_rejected(self, forbidden: str) -> None:
        payload = _append_payload()
        payload[forbidden] = "/tmp/npc.md"
        with pytest.raises(ValidationError):
            AppendFactOperation.model_validate(payload)


# ── ChangeOperation discriminated union ───────────────────────────────────


class TestChangeOperationUnion:
    @pytest.mark.parametrize(
        ("payload", "expected_type"),
        [
            (_create_payload(), CreateEntityOperation),
            (_update_payload(), UpdateEntityOperation),
            (_append_payload(), AppendFactOperation),
        ],
    )
    def test_accepts_each_operation_kind(
        self, payload: dict[str, Any], expected_type: type
    ) -> None:
        parsed = _change_operation_adapter.validate_python(payload)
        assert isinstance(parsed, expected_type)

    def test_unknown_kind_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _change_operation_adapter.validate_python({"kind": "delete_entity", "entity_id": "x"})

    def test_missing_kind_rejected(self) -> None:
        payload = _create_payload()
        payload.pop("kind")
        with pytest.raises(ValidationError):
            _change_operation_adapter.validate_python(payload)

    def test_no_generic_fallback_accepts_arbitrary_dict(self) -> None:
        with pytest.raises(ValidationError):
            _change_operation_adapter.validate_python({"foo": "bar"})


# ── ChangeSet ─────────────────────────────────────────────────────────────


class TestChangeSet:
    def test_required_fields(self) -> None:
        changeset = _valid_changeset()
        assert changeset.schema_version == 1
        assert changeset.changeset_id == "cs_01J"
        assert changeset.session_ref == "S014"
        assert changeset.provenance.provenance is Provenance.MODEL_INFERENCE

    def test_heterogeneous_ordered_operations(self) -> None:
        changeset = _valid_changeset()
        assert [operation.kind for operation in changeset.operations] == [
            "create_entity",
            "update_entity",
            "append_fact",
        ]

    def test_operation_order_preserved(self) -> None:
        first = CreateEntityOperation.model_validate(_create_payload())
        second = AppendFactOperation.model_validate(_append_payload())
        changeset = ChangeSet(
            changeset_id="cs_order",
            provenance=ProposalProvenance(provenance=Provenance.MANUAL),
            operations=(first, second),
        )
        assert changeset.operations[0] is first
        assert changeset.operations[1] is second

    def test_empty_operations_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChangeSet(
                changeset_id="cs_empty",
                provenance=ProposalProvenance(provenance=Provenance.MANUAL),
                operations=(),
            )

    def test_unknown_operation_kind_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChangeSet.model_validate(
                {
                    "changeset_id": "cs_bad",
                    "provenance": {"provenance": "manual"},
                    "operations": [{"kind": "delete_entity", "entity_id": "x"}],
                }
            )

    @pytest.mark.parametrize("schema_version", [0, 2, "1"])
    def test_only_schema_version_1_accepted(self, schema_version: object) -> None:
        with pytest.raises(ValidationError):
            ChangeSet.model_validate(
                {
                    "schema_version": schema_version,
                    "changeset_id": "cs_v",
                    "provenance": {"provenance": "manual"},
                    "operations": [_create_payload()],
                }
            )

    def test_session_ref_defaults_to_none(self) -> None:
        changeset = ChangeSet(
            changeset_id="cs_no_session",
            provenance=ProposalProvenance(provenance=Provenance.MANUAL),
            operations=(CreateEntityOperation.model_validate(_create_payload()),),
        )
        assert changeset.session_ref is None

    @pytest.mark.parametrize(
        "forbidden",
        [
            "approved",
            "reviewed",
            "rejected",
            "applied",
            "fingerprint",
            "hash",
            "created_at",
            "path",
            "file",
        ],
    )
    def test_no_review_apply_or_path_fields(self, forbidden: str) -> None:
        assert forbidden not in ChangeSet.model_fields

    def test_path_extra_rejected(self) -> None:
        payload = _valid_changeset().model_dump()
        payload["path"] = "/tmp/vault"
        with pytest.raises(ValidationError):
            ChangeSet.model_validate(payload)


# ── I9 — provenance survives round-trip ───────────────────────────────────


class TestChangeSetRoundTrip:
    def test_python_round_trip_preserves_provenance(self) -> None:
        original = _valid_changeset()
        reparsed = ChangeSet.model_validate(original.model_dump())
        assert reparsed == original
        assert reparsed.provenance == original.provenance
        assert reparsed.session_ref == original.session_ref
        assert reparsed.changeset_id == original.changeset_id

    def test_json_round_trip_preserves_provenance(self) -> None:
        original = _valid_changeset()
        reparsed = ChangeSet.model_validate(original.model_dump(mode="json"))
        assert reparsed.provenance.provenance is Provenance.MODEL_INFERENCE
        assert reparsed.provenance.model_profile == "post_session"
        assert reparsed.provenance.prompt_version == "v3"
        assert reparsed.session_ref == "S014"

    def test_round_trip_preserves_operation_kinds_and_order(self) -> None:
        original = _valid_changeset()
        reparsed = ChangeSet.model_validate(original.model_dump())
        assert [operation.kind for operation in reparsed.operations] == [
            "create_entity",
            "update_entity",
            "append_fact",
        ]

    def test_round_trip_preserves_unset_vs_explicit_none(self) -> None:
        original = UpdateEntityOperation(
            entity_id="npc_01J",
            expected_revision=4,
            update=EntityFieldUpdate(created_session=None),
        ).model_dump()
        reparsed = UpdateEntityOperation.model_validate(original)
        assert reparsed.update.model_fields_set == {"created_session"}
        assert reparsed.update.created_session is None


# ── I1 — no arbitrary path authority ──────────────────────────────────────


I1_MODELS: tuple[type[BaseModel], ...] = (
    ChangeSet,
    ProposalProvenance,
    EntityFieldUpdate,
    CreateEntityOperation,
    UpdateEntityOperation,
    AppendFactOperation,
)


class TestNoFilesystemAuthority:
    @pytest.mark.parametrize("model", I1_MODELS, ids=lambda m: m.__name__)
    def test_no_forbidden_semantic_field_names(self, model: type[BaseModel]) -> None:
        exposed = set(model.model_fields)
        assert not (exposed & FORBIDDEN_SEMANTIC_FIELDS)

    @pytest.mark.parametrize("model", I1_MODELS, ids=lambda m: m.__name__)
    def test_no_path_attribute(self, model: type[BaseModel]) -> None:
        assert not hasattr(model, "path")

    def test_smuggled_path_rejected_on_every_model(self) -> None:
        payloads: list[tuple[type[BaseModel], dict[str, Any]]] = [
            (
                ChangeSet,
                {
                    "changeset_id": "cs_path",
                    "provenance": {"provenance": "manual"},
                    "operations": [_create_payload()],
                },
            ),
            (ProposalProvenance, {"provenance": "manual"}),
            (EntityFieldUpdate, {"name": "ok"}),
            (
                CreateEntityOperation,
                CreateEntityOperation.model_validate(_create_payload()).model_dump(),
            ),
            (
                UpdateEntityOperation,
                UpdateEntityOperation.model_validate(_update_payload()).model_dump(),
            ),
            (
                AppendFactOperation,
                AppendFactOperation.model_validate(_append_payload()).model_dump(),
            ),
        ]
        for model, payload in payloads:
            smuggled = dict(payload)
            smuggled["path"] = "/tmp/vault/npc.md"
            with pytest.raises(ValidationError):
                model.model_validate(smuggled)
