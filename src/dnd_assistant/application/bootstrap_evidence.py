"""S13-03 immutable bootstrap mapping evidence policy.

Owns the *meaning* of the persisted bootstrap mapping evidence bytes and the
workflow invariants around them; the storage layer owns *safe placement* behind
the ``BootstrapEvidenceStore`` protocol.

The evidence artifact is non-canonical workflow/control data.  It preserves the
source-evidence linkage needed for a meaningful human review of the produced
proposal without contaminating the core Stage-10 ``ChangeSet`` schema with
filesystem paths or arbitrary evidence fields.

Invariants:

- a persisted evidence record round-trips through canonical JSON;
- evidence identity is immutable: an existing artifact with the same
  ``changeset_id`` and identical content is idempotent, differing content is a
  ``ConflictError``, and malformed persisted content is a ``StorageError``;
- the record is bound to the exact proposal id and fingerprint.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, cli, tools, or a concrete ``BootstrapEvidenceStore``
    implementation (only the protocol is referenced under ``TYPE_CHECKING``).
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from dnd_assistant.domain.changeset import ChangeSetId
from dnd_assistant.domain.types import RelativeArtifactPath, Sha256Fingerprint
from dnd_assistant.errors import ConflictError, StorageError

if TYPE_CHECKING:
    from dnd_assistant.application.bootstrap_input import BootstrapInputProjection
    from dnd_assistant.application.bootstrap_result import BootstrapMappingResult
    from dnd_assistant.storage.bootstrap_evidence import BootstrapEvidenceStore

BOOTSTRAP_EVIDENCE_SCHEMA_VERSION: int = 1
"""Explicit bootstrap evidence artifact schema version."""

_SOURCE_REF_PATTERN = r"^src_[0-9a-f]{32}$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"


# ── Record schema ─────────────────────────────────────────────────────────


class EvidenceSource(BaseModel):
    """Evidence descriptor for one eligible bootstrap source."""

    source_ref: str = Field(pattern=_SOURCE_REF_PATTERN)
    relative_path: RelativeArtifactPath
    source_class: str
    size_bytes: int = Field(ge=0)
    content_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    included: bool
    skip_reason: str | None = None

    model_config = {"frozen": True, "extra": "forbid"}


class EvidenceOperation(BaseModel):
    """Evidence linkage for one emitted ChangeSet operation."""

    operation_index: int = Field(ge=0)
    operation_kind: str
    candidate_ids: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()

    model_config = {"frozen": True, "extra": "forbid"}


class EvidenceUnresolved(BaseModel):
    """One unresolved/clarification diagnostic preserved for review."""

    reason: str
    detail: str
    candidate_id: str | None = None
    claim_id: str | None = None
    entity_ids: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()

    model_config = {"frozen": True, "extra": "forbid"}


class BootstrapEvidenceRecord(BaseModel):
    """Immutable bootstrap mapping evidence bound to one proposal."""

    schema_version: Literal[1] = 1

    producer_version: str
    campaign_id: str
    changeset_id: ChangeSetId
    proposal_fingerprint: Sha256Fingerprint
    input_fingerprint: Sha256Fingerprint

    model_profile: str | None = None
    model: str | None = None
    provider: str | None = None

    prompt_version: str
    extraction_schema_version: int = Field(ge=0)

    sources: tuple[EvidenceSource, ...] = ()
    operations: tuple[EvidenceOperation, ...] = ()
    unresolved: tuple[EvidenceUnresolved, ...] = ()

    model_config = {"frozen": True, "extra": "forbid"}


# ── Persistence outcomes ──────────────────────────────────────────────────


class EvidencePersistOutcome(StrEnum):
    """Result of persisting a bootstrap evidence artifact."""

    CREATED = "created"
    ALREADY_PRESENT = "already_present"


# ── Serialization ─────────────────────────────────────────────────────────


def serialize_bootstrap_evidence(record: BootstrapEvidenceRecord) -> str:
    """Serialize a evidence record to deterministic JSON text plus one newline."""
    payload = record.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def deserialize_bootstrap_evidence(text: str) -> BootstrapEvidenceRecord:
    """Parse persisted bootstrap evidence text.

    Raises:
        StorageError: The persisted text is malformed JSON, not an object, or
            fails ``BootstrapEvidenceRecord`` validation.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StorageError("Persisted bootstrap evidence is malformed JSON", cause=exc) from exc
    if not isinstance(data, dict):
        raise StorageError("Persisted bootstrap evidence is not a JSON object")
    try:
        return BootstrapEvidenceRecord.model_validate(data)
    except Exception as exc:
        raise StorageError("Persisted bootstrap evidence is invalid", cause=exc) from exc


def persist_bootstrap_evidence(
    store: BootstrapEvidenceStore,
    record: BootstrapEvidenceRecord,
) -> EvidencePersistOutcome:
    """Persist evidence with immutable, idempotent policy.

    Semantics:

    - absent                  -> exclusive create; ``CREATED``
    - identical content       -> no write; ``ALREADY_PRESENT``
    - same id, different body -> ``ConflictError``
    - present but malformed   -> ``StorageError``
    """
    serialized = serialize_bootstrap_evidence(record)
    existing = store.read_evidence_if_present(record.changeset_id)
    if existing is None:
        store.create_evidence(record.changeset_id, serialized)
        return EvidencePersistOutcome.CREATED
    existing_record = deserialize_bootstrap_evidence(existing)
    if existing_record.changeset_id != record.changeset_id:
        raise ConflictError(
            f"Persisted bootstrap evidence id {existing_record.changeset_id!r} does not match "
            f"key {record.changeset_id!r}"
        )
    if serialize_bootstrap_evidence(existing_record) == serialized:
        return EvidencePersistOutcome.ALREADY_PRESENT
    raise ConflictError(
        f"Bootstrap evidence for {record.changeset_id!r} already exists with different content"
    )


def build_bootstrap_evidence(
    projection: BootstrapInputProjection,
    result: BootstrapMappingResult,
    *,
    producer_version: str,
    prompt_version: str,
    extraction_schema_version: int,
    model_profile: str | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> BootstrapEvidenceRecord:
    """Build the immutable evidence record for a produced proposal.

    Raises:
        ValueError: ``result`` is not a proposal with a fingerprint.
    """
    if result.changeset is None or result.changeset_fingerprint is None:
        raise ValueError("Bootstrap evidence requires a produced proposal")

    sources = tuple(
        EvidenceSource(
            source_ref=source.source_ref,
            relative_path=source.relative_path,
            source_class=source.source_class.value,
            size_bytes=source.size_bytes,
            content_sha256=source.content_sha256,
            included=source.included,
            skip_reason=source.skip_reason.value if source.skip_reason else None,
        )
        for source in projection.sources
    )
    operations = tuple(
        EvidenceOperation(
            operation_index=item.operation_index,
            operation_kind=item.operation_kind,
            candidate_ids=item.candidate_ids,
            claim_ids=item.claim_ids,
            source_refs=item.source_refs,
        )
        for item in result.operation_provenance
    )
    unresolved = tuple(
        EvidenceUnresolved(
            reason=item.reason.value,
            detail=item.detail,
            candidate_id=item.candidate_id,
            claim_id=item.claim_id,
            entity_ids=item.entity_ids,
            source_refs=item.source_refs,
        )
        for item in result.unresolved
    )
    return BootstrapEvidenceRecord(
        producer_version=producer_version,
        campaign_id=projection.campaign_id,
        changeset_id=result.changeset.changeset_id,
        proposal_fingerprint=Sha256Fingerprint(digest=result.changeset_fingerprint.digest),
        input_fingerprint=projection.input_fingerprint,
        model_profile=model_profile,
        model=model,
        provider=provider,
        prompt_version=prompt_version,
        extraction_schema_version=extraction_schema_version,
        sources=sources,
        operations=operations,
        unresolved=unresolved,
    )


def evidence_content_fingerprint(record: BootstrapEvidenceRecord) -> str:
    """Return the SHA-256 hex of the canonical serialized evidence text."""
    return hashlib.sha256(serialize_bootstrap_evidence(record).encode("utf-8")).hexdigest()


__all__ = [
    "BOOTSTRAP_EVIDENCE_SCHEMA_VERSION",
    "BootstrapEvidenceRecord",
    "EvidenceOperation",
    "EvidencePersistOutcome",
    "EvidenceSource",
    "EvidenceUnresolved",
    "build_bootstrap_evidence",
    "deserialize_bootstrap_evidence",
    "evidence_content_fingerprint",
    "persist_bootstrap_evidence",
    "serialize_bootstrap_evidence",
]
