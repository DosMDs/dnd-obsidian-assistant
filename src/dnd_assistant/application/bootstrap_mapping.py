"""S13-03 deterministic bootstrap mapping orchestration.

Composes the trusted S13-02 discovery report, the filesystem-free canonical
recognition of ``ENTITY_CANDIDATE`` sources, bounded batch model extraction,
semantic validation, deterministic merge and ChangeSet production into one
typed result.

Orchestration is pure application policy: discovery, the canonical parse helper
and the model adapter are injected.  This module performs no filesystem I/O and
no persistence.

This module belongs to the application layer and must not import from:
    storage at runtime (only the pure recognition value types), models, ollama,
    pydantic_ai, tools, cli, or the player SearchService/EntityResolver.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final

from dnd_assistant.application.bootstrap_canonical import (
    CanonicalCoverage,
    CanonicalStateSnapshot,
    assess_canonical_coverage,
    build_canonical_snapshot,
)
from dnd_assistant.application.bootstrap_changeset import (
    BOOTSTRAP_MAPPING_VERSION,
    produce_bootstrap_changeset,
)
from dnd_assistant.application.bootstrap_extraction import (
    BootstrapExtractionModel,
    build_bootstrap_extraction_request,
    merge_bootstrap_extractions,
    run_bootstrap_extraction,
)
from dnd_assistant.application.bootstrap_input import (
    BootstrapInputProjection,
    prepare_bootstrap_input,
)
from dnd_assistant.application.bootstrap_result import (
    BootstrapMappingOutcome,
    BootstrapMappingResult,
    BootstrapUnresolved,
    BootstrapUnresolvedReason,
)
from dnd_assistant.application.vault_discovery import VaultDiscoveryReport
from dnd_assistant.domain.bootstrap_extraction import (
    BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
)
from dnd_assistant.prompts.bootstrap_extraction_v1 import (
    BOOTSTRAP_EXTRACTION_PROMPT_ID,
)
from dnd_assistant.storage.bootstrap_types import CanonicalCandidate

BOOTSTRAP_PROCESSOR_VERSION: Final[str] = BOOTSTRAP_MAPPING_VERSION
"""Trusted producer/prompt contract version for a bootstrap mapping run."""


@dataclass(frozen=True, slots=True)
class BootstrapModelIdentity:
    """Non-deterministic execution identity of the bootstrap model."""

    profile: str | None = None
    model: str | None = None
    provider: str | None = None


@dataclass(frozen=True, slots=True)
class BootstrapMappingRun:
    """Complete in-memory result of one bootstrap mapping run."""

    projection: BootstrapInputProjection
    snapshot: CanonicalStateSnapshot
    coverage: CanonicalCoverage
    result: BootstrapMappingResult
    model_identity: BootstrapModelIdentity
    processor_version: str
    prompt_version: str
    extraction_schema_version: int


def _run_level_unresolved(
    projection: BootstrapInputProjection,
    snapshot: CanonicalStateSnapshot,
) -> list[BootstrapUnresolved]:
    diagnostics: list[BootstrapUnresolved] = []

    for conflict in snapshot.conflicts:
        diagnostics.append(
            BootstrapUnresolved(
                reason=BootstrapUnresolvedReason.CANONICAL_STATE_CONFLICT,
                detail=(
                    f"Canonical identity conflict ({conflict.reason.value}) at "
                    f"{conflict.relative_path!r}; participates only in duplicate prevention"
                ),
                entity_ids=(conflict.entity_id,),
            )
        )

    for issue in snapshot.issues:
        diagnostics.append(
            BootstrapUnresolved(
                reason=BootstrapUnresolvedReason.NON_CANONICAL_SOURCE,
                detail=(
                    f"Non-canonical historical note ({issue.outcome.value}) at "
                    f"{issue.relative_path!r} remains source evidence only"
                ),
            )
        )

    for source in projection.sources:
        if source.included:
            continue
        skip = source.skip_reason.value if source.skip_reason else "not_included"
        diagnostics.append(
            BootstrapUnresolved(
                reason=BootstrapUnresolvedReason.SOURCE_SKIPPED,
                detail=f"Eligible source {source.relative_path!r} was not sent to the model: {skip}",
                source_refs=(source.source_ref,),
            )
        )

    return diagnostics


def _sort_unresolved(items: Sequence[BootstrapUnresolved]) -> tuple[BootstrapUnresolved, ...]:
    return tuple(
        sorted(
            items,
            key=lambda item: (
                item.reason.value,
                item.candidate_id or "",
                item.claim_id or "",
                item.detail,
            ),
        )
    )


def _coverage_unresolved(coverage: CanonicalCoverage) -> list[BootstrapUnresolved]:
    return [
        BootstrapUnresolved(
            reason=BootstrapUnresolvedReason.CANONICAL_COVERAGE_INCOMPLETE,
            detail=(
                f"Canonical identity coverage incomplete at {issue.relative_path!r}: {issue.detail}"
            ),
        )
        for issue in coverage.issues
    ]


def run_bootstrap_mapping(
    report: VaultDiscoveryReport,
    canonical_candidates: Sequence[CanonicalCandidate],
    model: BootstrapExtractionModel,
    *,
    processor_version: str = BOOTSTRAP_PROCESSOR_VERSION,
    prompt_version: str = BOOTSTRAP_EXTRACTION_PROMPT_ID,
    extraction_schema_version: int = BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
    model_identity: BootstrapModelIdentity | None = None,
) -> BootstrapMappingRun:
    """Run the deterministic bootstrap mapping pipeline.

    If canonical identity coverage is incomplete, no model call is made and a
    typed ``NO_CHANGES`` result is returned with explicit coverage diagnostics:
    the canonical state could not be fully established, so no mutation may be
    authorized.  Otherwise a model/batch failure fails closed (no proposal).
    The result is in-memory only; persistence is a separate service.

    Raises:
        BootstrapExtractionError: Model/framework/semantic validation failure.
        BootstrapChangeError: Produced proposal failed preflight.
    """
    identity = model_identity or BootstrapModelIdentity()
    projection = prepare_bootstrap_input(report)
    snapshot = build_canonical_snapshot(canonical_candidates)
    coverage = assess_canonical_coverage(report)

    if not coverage.complete:
        diagnostics = _sort_unresolved(
            [*_coverage_unresolved(coverage), *_run_level_unresolved(projection, snapshot)]
        )
        result = BootstrapMappingResult(
            outcome=BootstrapMappingOutcome.NO_CHANGES,
            unresolved=diagnostics,
        )
        return BootstrapMappingRun(
            projection=projection,
            snapshot=snapshot,
            coverage=coverage,
            result=result,
            model_identity=identity,
            processor_version=processor_version,
            prompt_version=prompt_version,
            extraction_schema_version=extraction_schema_version,
        )

    validated = [
        run_bootstrap_extraction(
            model,
            build_bootstrap_extraction_request(
                projection,
                batch,
                processor_version=processor_version,
                prompt_version=prompt_version,
                extraction_schema_version=extraction_schema_version,
            ),
        )
        for batch in projection.batches
    ]
    merged = merge_bootstrap_extractions([item.extraction for item in validated])

    result = produce_bootstrap_changeset(
        snapshot,
        merged,
        campaign_id=projection.campaign_id,
        input_fingerprint=projection.input_fingerprint,
        model_profile=identity.profile,
        prompt_version=prompt_version,
        processor_version=processor_version,
        extraction_schema_version=extraction_schema_version,
    )

    combined = _sort_unresolved([*result.unresolved, *_run_level_unresolved(projection, snapshot)])
    result = replace(result, unresolved=combined)

    return BootstrapMappingRun(
        projection=projection,
        snapshot=snapshot,
        coverage=coverage,
        result=result,
        model_identity=identity,
        processor_version=processor_version,
        prompt_version=prompt_version,
        extraction_schema_version=extraction_schema_version,
    )


__all__ = [
    "BOOTSTRAP_PROCESSOR_VERSION",
    "BootstrapMappingRun",
    "BootstrapModelIdentity",
    "run_bootstrap_mapping",
]
