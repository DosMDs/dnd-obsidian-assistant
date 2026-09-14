"""Stage-10 ChangeSet and change-operation domain schemas.

Defines the immutable, strict proposal contracts through which a later
post-session proposal producer can describe campaign changes without ever
gaining filesystem, path or persistence authority.

This module owns **proposal data only**. Validation/preflight (S10-02),
review DTO / approval / fingerprint binding (S10-03) and apply orchestration
(S10-04) are application-layer concerns and deliberately do not appear here.

This module belongs to the domain layer and must not import from:
    storage, application, models, tools, retrieval, cli, pathlib, os, hashlib

No filesystem paths, hashes/fingerprints, review lifecycle state or storage
DTOs appear in these schemas.  A proposal exposes only semantic operation
kinds and a semantic allowlist of updatable entity fields; ``extra="forbid"``
rejects any smuggled field (invariant I1).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from dnd_assistant.domain.entity import NameStr, SessionRef, StatusStr, TagStr
from dnd_assistant.domain.types import (
    EntityId,
    EntityType,
    KnowledgeStatus,
    Provenance,
    Revision,
    Visibility,
)

# ── Field-level validators ────────────────────────────────────────────────


def _validate_changeset_id(value: str) -> str:
    """Validate an opaque ChangeSet identifier.

    Mirrors the ``EntityId`` validation policy but is a distinct concept:
    a ChangeSet ID identifies a proposal, not a campaign entity.

    Requirements: strict string, non-empty, no leading/trailing whitespace,
    printable Unicode.  It carries no path or filename meaning.
    """
    if not isinstance(value, str):
        raise ValueError("ChangeSetId must be a string")
    if not value:
        raise ValueError("ChangeSetId must not be empty")
    if value.strip() != value:
        raise ValueError("ChangeSetId must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError("ChangeSetId must not contain non-printable characters")
    return value


def _validate_optional_metadata(value: str | None) -> str | None:
    """Validate an optional printable provenance metadata string.

    When present: strict string, non-empty, no surrounding whitespace,
    printable Unicode.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("value must be a string or None")
    if not value:
        raise ValueError("value must not be empty")
    if value.strip() != value:
        raise ValueError("value must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError("value must not contain non-printable characters")
    return value


def _validate_fact(value: str) -> str:
    """Validate a single appended fact line.

    Semantically matches the accepted repository fact contract: strict
    string, non-empty, no leading/trailing whitespace, printable Unicode
    with no embedded newline/control characters.  The domain owns this
    validation and does not import storage validators.
    """
    if not isinstance(value, str):
        raise ValueError("fact must be a string")
    if not value:
        raise ValueError("fact must not be empty")
    if value.strip() != value:
        raise ValueError("fact must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError("fact must not contain non-printable characters")
    return value


# ── Annotated value types ─────────────────────────────────────────────────


ChangeSetId = Annotated[
    str,
    BeforeValidator(_validate_changeset_id),
    Field(description="Opaque stable proposal identifier, independent of path/name"),
]
"""An opaque, validated ChangeSet identifier.

A ``ChangeSetId`` is conceptually distinct from an ``EntityId``: it names a
proposal batch, not a campaign entity.  It is deliberately independent of
any filesystem path, filename or display name and encodes no filesystem
meaning.
"""

OptionalProvenanceStr = Annotated[
    str | None,
    BeforeValidator(_validate_optional_metadata),
    Field(default=None, description="Optional printable provenance metadata string"),
]

FactStr = Annotated[
    str,
    BeforeValidator(_validate_fact),
    Field(description="Validated single fact line (non-empty, printable, no newlines)"),
]

# ── ProposalProvenance ────────────────────────────────────────────────────


class ProposalProvenance(BaseModel):
    """Origin semantics for an untrusted proposal.

    Describes **how the proposal entered the system**, not which actor later
    performs the write (repository audit owns that distinction).  Session
    origin lives canonically on :class:`ChangeSet`; it is intentionally not
    duplicated here.
    """

    provenance: Provenance
    """Origin mechanism (manual/session/bootstrap/import/model_inference)."""

    model_profile: OptionalProvenanceStr = None
    """Optional model profile name used to produce the proposal."""

    prompt_version: OptionalProvenanceStr = None
    """Optional prompt/version identifier for reproducibility."""

    model_config = {
        "extra": "forbid",
        "frozen": True,
    }


# ── EntityFieldUpdate ─────────────────────────────────────────────────────


class EntityFieldUpdate(BaseModel):
    """Explicit semantic allowlist of entity fields a proposal may update.

    This is **not** an automatic mirror of ``storage.patch.EntityPatch`` and
    is not under a permanent parity contract.  Storage-only capability must
    not automatically expand ChangeSet authority.  Immutable entity fields
    (``id``, ``type``, ``revision``, timestamps, ``body``) and path/filename
    concepts are not representable here.

    At least one field must be explicitly supplied.  Omitted fields remain
    unset; explicit ``None`` is accepted only for the nullable session
    fields (``created_session``, ``last_seen_session``) and means "clear".
    ``tags`` uses replacement semantics only.
    """

    name: NameStr | None = None
    status: StatusStr | None = None
    visibility: Visibility | None = None
    knowledge_status: KnowledgeStatus | None = None
    created_session: SessionRef = None
    last_seen_session: SessionRef = None
    tags: tuple[TagStr, ...] | None = None
    """Full replacement tag set; no add/remove mini-language."""

    model_config = {
        "extra": "forbid",
        "frozen": True,
    }

    @model_serializer(mode="wrap")
    def _serialize_explicit_fields(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> object:
        """Serialize only explicitly supplied fields.

        Omitted fields must stay omitted so that ``model_dump`` /
        ``model_validate`` round-trips preserve the "unset" versus "explicit
        None" distinction required by the update contract.
        """
        data = handler(self)
        if info.exclude_unset or not isinstance(data, dict):
            return data
        return {name: value for name, value in data.items() if name in self.model_fields_set}

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> EntityFieldUpdate:
        """Reject an update with no explicitly supplied field."""
        if not self.model_fields_set:
            raise ValueError("EntityFieldUpdate must include at least one editable field")
        return self

    @model_validator(mode="after")
    def _reject_explicit_none_for_non_nullable(self) -> EntityFieldUpdate:
        """Reject explicit ``None`` for non-nullable fields.

        Non-nullable fields: name, status, visibility, knowledge_status, tags.
        Nullable fields: created_session, last_seen_session.
        """
        non_nullable = ("name", "status", "visibility", "knowledge_status", "tags")
        for field_name in non_nullable:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"Field {field_name!r} is non-nullable and cannot be set to None")
        return self


# ── Operations ────────────────────────────────────────────────────────────


class CreateEntityOperation(BaseModel):
    """Propose creation of a new campaign entity.

    Carries the canonical create payload but **not** application-only fields
    (``revision``, ``created_at``, ``updated_at``, ``body``) and no path or
    filename.  The ``entity_id`` is supplied explicitly by the trusted
    proposal author; identity is never taken from raw model text.
    """

    kind: Literal["create_entity"] = "create_entity"
    entity_id: EntityId
    type: EntityType
    name: NameStr
    status: StatusStr
    visibility: Visibility
    knowledge_status: KnowledgeStatus
    created_session: SessionRef = None
    last_seen_session: SessionRef = None
    tags: tuple[TagStr, ...] = ()

    model_config = {
        "extra": "forbid",
        "frozen": True,
    }


class UpdateEntityOperation(BaseModel):
    """Propose a revision-guarded partial update of an existing entity."""

    kind: Literal["update_entity"] = "update_entity"
    entity_id: EntityId
    expected_revision: Revision
    """Mandatory optimistic-concurrency precondition; no implicit default."""

    update: EntityFieldUpdate

    model_config = {
        "extra": "forbid",
        "frozen": True,
    }


class AppendFactOperation(BaseModel):
    """Propose appending one validated fact line to an existing entity."""

    kind: Literal["append_fact"] = "append_fact"
    entity_id: EntityId
    expected_revision: Revision
    """Mandatory optimistic-concurrency precondition; no implicit default."""

    fact: FactStr

    model_config = {
        "extra": "forbid",
        "frozen": True,
    }


ChangeOperation = Annotated[
    CreateEntityOperation | UpdateEntityOperation | AppendFactOperation,
    Field(discriminator="kind"),
]
"""Constrained, discriminated union of the accepted Stage-10 operation kinds.

Unknown ``kind`` values fail validation; there is no generic fallback.
"""


# ── ChangeSet ─────────────────────────────────────────────────────────────


class ChangeSet(BaseModel):
    """Immutable aggregate of ordered semantic change operations.

    A ``ChangeSet`` describes a proposal, not a persisted or reviewed
    artifact: it contains no approval/review state, no apply result, no
    fingerprint/hash and no filesystem paths.  Operation order is the apply
    order.
    """

    schema_version: Literal[1] = 1

    changeset_id: ChangeSetId

    provenance: ProposalProvenance

    session_ref: SessionRef = None
    """Optional canonical origin session reference for the whole proposal."""

    operations: tuple[ChangeOperation, ...] = Field(min_length=1)
    """Ordered non-empty tuple of change operations (order = apply order)."""

    model_config = {
        "extra": "forbid",
        "frozen": True,
    }
