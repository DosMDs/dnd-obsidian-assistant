"""S13-03 trusted bootstrap model-input preparation and fingerprinting.

Consumes the trusted, already-read S13-02 ``VaultDiscoveryReport`` (no second
filesystem traversal) and produces a deterministic, bounded, fingerprinted
model-input projection:

- only ``ENTITY_CANDIDATE``, ``SESSION_SOURCE`` and ``USER_SOURCE`` sources may
  affect bootstrap mapping;
- application-owned configuration/raw/control, derived and unsupported entries
  are excluded entirely from the semantic fingerprint, so persisting bootstrap
  workflow artifacts (``_system/changesets/**``, ``_system/bootstrap/**``) does
  not invalidate an otherwise unchanged campaign source set;
- every eligible source receives a stable, >=128-bit ``src_`` reference and a
  whole-document SHA-256 content fingerprint (when content was read);
- deterministic ordering and greedy batching bound the model-visible text.

This module belongs to the application layer and must not import from:
    storage, models, ollama, pydantic_ai, tools, cli, retrieval.
``hashlib``/``json`` are intentional trusted-fingerprint concerns.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from dnd_assistant.application.vault_discovery import (
    ContentReadStatus,
    DiscoveredSource,
    SourceClass,
    VaultDiscoveryReport,
)
from dnd_assistant.domain.types import Sha256Fingerprint
from dnd_assistant.errors import ValidationError

# ── Policy contract ───────────────────────────────────────────────────────

BOOTSTRAP_INPUT_POLICY_VERSION: Final[str] = "bootstrap-input-v1"
"""Explicit semantic input-policy version bound into the fingerprint."""

BOOTSTRAP_ELIGIBLE_SOURCE_CLASSES: Final[tuple[SourceClass, ...]] = (
    SourceClass.ENTITY_CANDIDATE,
    SourceClass.SESSION_SOURCE,
    SourceClass.USER_SOURCE,
)
"""Only these S13-02 classes can affect bootstrap mapping."""

MAX_BOOTSTRAP_CONTEXT_CHARS: Final[int] = 200_000
"""Maximum model-visible characters per batch (Python-owned)."""

MAX_BOOTSTRAP_BATCHES: Final[int] = 16
"""Maximum number of deterministic model-input batches."""

_SOURCE_REF_HEX_CHARS: Final[int] = 32
"""128 bits of SHA-256 material for an opaque source reference."""

_CLASS_ORDER: Final[dict[SourceClass, int]] = {
    source_class: index for index, source_class in enumerate(BOOTSTRAP_ELIGIBLE_SOURCE_CLASSES)
}


# ── Result types ──────────────────────────────────────────────────────────


class BootstrapSourceSkipReason(StrEnum):
    """Why an eligible source is not present in any model batch."""

    NOT_READ = "not_read"
    FAILED = "failed"
    SKIPPED_BUDGET = "skipped_budget"
    TOO_LARGE = "too_large"
    BATCH_LIMIT = "batch_limit"


@dataclass(frozen=True, slots=True)
class BootstrapSourceProjection:
    """Deterministic descriptor for one eligible bootstrap source."""

    source_ref: str
    relative_path: str
    source_class: SourceClass
    size_bytes: int
    content_sha256: str | None
    included: bool
    skip_reason: BootstrapSourceSkipReason | None


@dataclass(frozen=True, slots=True)
class BootstrapBatch:
    """One deterministic, bounded model-input batch."""

    batch_id: str
    request_text: str
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BootstrapInputProjection:
    """Complete trusted model-input projection for a bootstrap run."""

    campaign_id: str
    input_fingerprint: Sha256Fingerprint
    batches: tuple[BootstrapBatch, ...]
    sources: tuple[BootstrapSourceProjection, ...]

    @property
    def expected_source_refs(self) -> frozenset[str]:
        """All source references the model may cite across all batches."""
        return frozenset(source.source_ref for source in self.sources if source.included)


# ── Pure helpers ──────────────────────────────────────────────────────────


def source_ref(campaign_id: str, relative_path: str) -> str:
    """Derive the stable >=128-bit opaque source reference for a path."""
    digest = hashlib.sha256(f"{campaign_id}\x00{relative_path}".encode()).hexdigest()
    return f"src_{digest[:_SOURCE_REF_HEX_CHARS]}"


def _content_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _skip_reason_for(status: ContentReadStatus) -> BootstrapSourceSkipReason:
    if status is ContentReadStatus.FAILED:
        return BootstrapSourceSkipReason.FAILED
    if status is ContentReadStatus.SKIPPED:
        return BootstrapSourceSkipReason.SKIPPED_BUDGET
    return BootstrapSourceSkipReason.NOT_READ


def _order_key(entry: DiscoveredSource) -> tuple[int, str, str]:
    return (
        _CLASS_ORDER.get(entry.source_class, len(_CLASS_ORDER)),
        entry.relative_path.casefold(),
        entry.relative_path,
    )


def _render_block(campaign_id: str, entry: DiscoveredSource) -> tuple[str, str]:
    """Render one source exactly as the model will see it, plus its ref.

    The rendered block includes the ``SOURCE`` marker, class/path metadata,
    content and ``END SOURCE`` marker.  Batch bounding is enforced against the
    exact joined representation so wrapper overhead cannot bypass the limit.
    """
    ref = source_ref(campaign_id, entry.relative_path)
    block = (
        f"SOURCE id={ref} class={entry.source_class.value} path={entry.relative_path}\n"
        f"{entry.content_text or ''}\n"
        f"END SOURCE id={ref}"
    )
    return block, ref


def _fingerprint(
    campaign_id: str,
    sources: tuple[BootstrapSourceProjection, ...],
) -> Sha256Fingerprint:
    material = {
        "policy_version": BOOTSTRAP_INPUT_POLICY_VERSION,
        "campaign_id": campaign_id,
        "sources": [
            {
                "path": source.relative_path,
                "class": source.source_class.value,
                "size": source.size_bytes,
                "content_sha256": source.content_sha256,
                "included": source.included,
                "skip_reason": source.skip_reason.value if source.skip_reason else None,
            }
            for source in sources
        ],
    }
    try:
        text = json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "Bootstrap input fingerprint material is not canonically serializable",
            cause=exc,
        ) from exc
    return Sha256Fingerprint(digest=hashlib.sha256(text.encode("utf-8")).hexdigest())


# ── Public entry point ────────────────────────────────────────────────────


def prepare_bootstrap_input(report: VaultDiscoveryReport) -> BootstrapInputProjection:
    """Prepare the bounded, fingerprinted model-input projection.

    Only eligible S13-02 classes participate.  ``APPLICATION_CONFIG``,
    ``APPLICATION_RAW``, ``APPLICATION_CONTROL``, ``DERIVED`` and
    ``UNSUPPORTED`` entries are ignored entirely, so writing bootstrap workflow
    artifacts never changes the semantic input fingerprint.
    """
    eligible = [
        entry for entry in report.entries if entry.source_class in BOOTSTRAP_ELIGIBLE_SOURCE_CLASSES
    ]
    eligible.sort(key=_order_key)

    projections: list[BootstrapSourceProjection] = []
    batches: list[BootstrapBatch] = []
    pending_blocks: list[str] = []
    pending_refs: list[str] = []
    pending_chars = 0

    def flush() -> None:
        nonlocal pending_blocks, pending_refs, pending_chars
        if not pending_blocks:
            return
        text = "\n".join(pending_blocks)
        batches.append(
            BootstrapBatch(
                batch_id=f"batch_{len(batches)}",
                request_text=text,
                source_refs=tuple(pending_refs),
            )
        )
        pending_blocks = []
        pending_refs = []
        pending_chars = 0

    def skip(
        entry: DiscoveredSource,
        ref: str,
        reason: BootstrapSourceSkipReason,
    ) -> None:
        projections.append(
            BootstrapSourceProjection(
                source_ref=ref,
                relative_path=entry.relative_path,
                source_class=entry.source_class,
                size_bytes=entry.size_bytes,
                content_sha256=(
                    _content_fingerprint(entry.content_text)
                    if entry.content_text is not None
                    else None
                ),
                included=False,
                skip_reason=reason,
            )
        )

    for entry in eligible:
        ref = source_ref(report.campaign_id, entry.relative_path)

        if entry.content_status is not ContentReadStatus.READ or entry.content_text is None:
            projections.append(
                BootstrapSourceProjection(
                    source_ref=ref,
                    relative_path=entry.relative_path,
                    source_class=entry.source_class,
                    size_bytes=entry.size_bytes,
                    content_sha256=None,
                    included=False,
                    skip_reason=_skip_reason_for(entry.content_status),
                )
            )
            continue

        block, ref = _render_block(report.campaign_id, entry)
        block_chars = len(block)

        # A single fully rendered source that cannot fit must be skipped whole;
        # it is never truncated or split.
        if block_chars > MAX_BOOTSTRAP_CONTEXT_CHARS:
            skip(entry, ref, BootstrapSourceSkipReason.TOO_LARGE)
            continue

        if len(batches) >= MAX_BOOTSTRAP_BATCHES:
            skip(entry, ref, BootstrapSourceSkipReason.BATCH_LIMIT)
            continue

        separator = 1 if pending_blocks else 0
        projected_chars = pending_chars + separator + block_chars
        if pending_blocks and projected_chars > MAX_BOOTSTRAP_CONTEXT_CHARS:
            flush()
            if len(batches) >= MAX_BOOTSTRAP_BATCHES:
                skip(entry, ref, BootstrapSourceSkipReason.BATCH_LIMIT)
                continue
            projected_chars = block_chars

        pending_blocks.append(block)
        pending_refs.append(ref)
        pending_chars = projected_chars
        projections.append(
            BootstrapSourceProjection(
                source_ref=ref,
                relative_path=entry.relative_path,
                source_class=entry.source_class,
                size_bytes=entry.size_bytes,
                content_sha256=_content_fingerprint(entry.content_text),
                included=True,
                skip_reason=None,
            )
        )

        if pending_chars >= MAX_BOOTSTRAP_CONTEXT_CHARS:
            flush()

    flush()

    sources = tuple(
        sorted(
            projections,
            key=lambda source: (
                _CLASS_ORDER.get(source.source_class, len(_CLASS_ORDER)),
                source.relative_path.casefold(),
                source.relative_path,
            ),
        )
    )
    return BootstrapInputProjection(
        campaign_id=report.campaign_id,
        input_fingerprint=_fingerprint(report.campaign_id, sources),
        batches=tuple(batches),
        sources=sources,
    )


__all__ = [
    "BOOTSTRAP_ELIGIBLE_SOURCE_CLASSES",
    "BOOTSTRAP_INPUT_POLICY_VERSION",
    "MAX_BOOTSTRAP_BATCHES",
    "MAX_BOOTSTRAP_CONTEXT_CHARS",
    "BootstrapBatch",
    "BootstrapInputProjection",
    "BootstrapSourceProjection",
    "BootstrapSourceSkipReason",
    "prepare_bootstrap_input",
    "source_ref",
]
