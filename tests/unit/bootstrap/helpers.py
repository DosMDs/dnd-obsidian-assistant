"""Shared helpers for S13-03 bootstrap tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from dnd_assistant.application.bootstrap_extraction import BootstrapExtractionRequest
from dnd_assistant.application.vault_discovery import (
    ContentReadStatus,
    DiscoveredSource,
    FrontmatterStatus,
    SourceClass,
    VaultDiscoveryReport,
)
from dnd_assistant.domain.bootstrap_extraction import (
    BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
    BootstrapClaim,
    BootstrapClaimKind,
    BootstrapEntityCandidate,
    BootstrapEntityReference,
    BootstrapExtraction,
)
from dnd_assistant.domain.types import EntityType
from dnd_assistant.storage.vault_discovery import DiscoveryIssue

__all__ = [
    "FakeBootstrapModel",
    "canonical_text",
    "make_claim",
    "make_candidate",
    "make_reference",
    "make_report",
    "make_source",
]


def make_source(
    relative_path: str,
    source_class: SourceClass,
    text: str | None,
    *,
    content_status: ContentReadStatus | None = None,
    frontmatter_status: FrontmatterStatus = FrontmatterStatus.ABSENT,
    size_bytes: int | None = None,
) -> DiscoveredSource:
    """Build one DiscoveredSource, defaulting to a successful read."""
    if content_status is None:
        content_status = ContentReadStatus.READ if text is not None else ContentReadStatus.SKIPPED
    if size_bytes is None:
        size_bytes = len(text.encode()) if text is not None else 0
    return DiscoveredSource(
        relative_path=relative_path,
        source_class=source_class,
        extension=Path(relative_path).suffix.casefold(),
        size_bytes=size_bytes,
        content_status=content_status,
        frontmatter_status=frontmatter_status,
        content_text=text if content_status is ContentReadStatus.READ else None,
    )


def make_report(
    campaign_id: str,
    sources: Sequence[DiscoveredSource],
    issues: Sequence[DiscoveryIssue] = (),
) -> VaultDiscoveryReport:
    return VaultDiscoveryReport(
        campaign_id=campaign_id,
        entries=tuple(sources),
        issues=tuple(issues),
    )


def canonical_text(
    entity_id: str,
    entity_type: EntityType | str,
    name: str,
    *,
    revision: int = 1,
    visibility: str = "dm",
    knowledge_status: str = "confirmed",
    status: str = "alive",
    aliases: Sequence[str] | None = None,
    body: str = "body\n",
) -> str:
    """Build canonical entity Markdown text for the existing codec."""
    type_value = entity_type.value if isinstance(entity_type, EntityType) else entity_type
    lines = [
        "---",
        "schema_version: 1",
        f"id: {entity_id}",
        f"type: {type_value}",
        f"name: {name}",
        f"status: {status}",
        f"visibility: {visibility}",
        f"knowledge_status: {knowledge_status}",
        "created_at: 2026-01-01T00:00:00+00:00",
        "updated_at: 2026-01-01T00:00:00+00:00",
        f"revision: {revision}",
    ]
    if aliases:
        lines.append("aliases:")
        lines.extend(f"  - {alias}" for alias in aliases)
    lines.append("---")
    return "\n".join(lines) + "\n" + body


def make_candidate(
    candidate_id: str,
    display_name: str,
    entity_type: EntityType,
    source_refs: Sequence[str],
    *,
    summary: str | None = None,
) -> BootstrapEntityCandidate:
    return BootstrapEntityCandidate(
        candidate_id=candidate_id,
        display_name=display_name,
        entity_type=entity_type,
        source_refs=tuple(source_refs),
        summary=summary,
    )


def make_reference(
    reference_id: str,
    text: str,
    entity_type: EntityType,
    source_refs: Sequence[str],
) -> BootstrapEntityReference:
    return BootstrapEntityReference(
        reference_id=reference_id,
        text=text,
        entity_type=entity_type,
        source_refs=tuple(source_refs),
    )


def make_claim(
    claim_id: str,
    text: str,
    source_refs: Sequence[str],
    *,
    kind: BootstrapClaimKind = BootstrapClaimKind.FACT,
    references: Sequence[BootstrapEntityReference] = (),
    conflict_group: str | None = None,
) -> BootstrapClaim:
    return BootstrapClaim(
        claim_id=claim_id,
        kind=kind,
        text=text,
        source_refs=tuple(source_refs),
        references=tuple(references),
        conflict_group=conflict_group,
    )


def empty_extraction() -> BootstrapExtraction:
    return BootstrapExtraction(schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION)


class FakeBootstrapModel:
    """Deterministic in-memory BootstrapExtractionModel for tests."""

    def __init__(
        self,
        extraction: BootstrapExtraction | None = None,
        *,
        by_batch: Mapping[str, BootstrapExtraction] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._extraction = extraction if extraction is not None else empty_extraction()
        self._by_batch = dict(by_batch) if by_batch else None
        self._error = error
        self.requests: list[BootstrapExtractionRequest] = []

    def extract(self, request: BootstrapExtractionRequest) -> BootstrapExtraction:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        if self._by_batch is not None:
            return self._by_batch[request.batch_id]
        return self._extraction
