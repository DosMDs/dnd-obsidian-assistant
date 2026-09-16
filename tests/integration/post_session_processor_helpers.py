"""S11-06 processor integration test helpers (test-only, no pytest import).

Builds real-Vault processor dependencies with deterministic fake extraction and
rendering models and a fixed clock.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from dnd_assistant.application.post_session_context import PreparedPostSessionInput
from dnd_assistant.application.post_session_processor import PostSessionProcessorDeps
from dnd_assistant.domain.post_session_extraction import PostSessionExtraction
from dnd_assistant.domain.types import EntityType
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.changeset_store import ObsidianChangeSetStore
from dnd_assistant.storage.post_session_artifacts import ObsidianPostSessionArtifactStore
from dnd_assistant.storage.post_session_processing import PostSessionProcessingStore
from tests.integration.test_post_session_context import _services
from tests.unit.post_session.extraction_helpers import (
    FakePostSessionExtractionModel,
    make_claim,
    make_extraction,
    make_mention,
)
from tests.unit.post_session.helpers import BASE_END
from tests.unit.post_session.rendering_helpers import (
    FakePostSessionRenderingModel,
    make_render_output,
)

ATTEMPT_A = "att_" + "a" * 32
ATTEMPT_B = "att_" + "b" * 32
ATTEMPT_C = "att_" + "c" * 32


def fixed_clock() -> datetime:
    """Deterministic ledger real-time source."""
    return BASE_END


def append_extraction(prepared: PreparedPostSessionInput) -> PostSessionExtraction:
    """Extraction that yields one append_fact proposal for npc-aria."""
    event_ids = tuple(event.event_id for event in prepared.identity.raw_events)
    return make_extraction(
        claims=(
            make_claim(
                text="Aria gained a new scar.",
                evidence_event_ids=(event_ids[0],),
                entity_mentions=(
                    make_mention(
                        text="Aria",
                        candidate_entity_id="npc-aria",
                        entity_type=EntityType.NPC,
                        evidence_event_ids=(event_ids[0],),
                    ),
                ),
            ),
        )
    )


def build_deps(
    root: Path,
    audit: AuditService,
    *,
    extraction: PostSessionExtraction | None = None,
    extraction_error: Exception | None = None,
    render_error: Exception | None = None,
    processing_store: PostSessionProcessingStore | None = None,
) -> PostSessionProcessorDeps:
    """Assemble real processor dependencies for session ``S001``."""
    metadata_repo, event_repo, vault, store = _services(root, audit)
    return PostSessionProcessorDeps(
        metadata_repo=metadata_repo,
        event_repo=event_repo,
        vault_repo=vault,
        processing_store=processing_store if processing_store is not None else store,
        artifact_store=ObsidianPostSessionArtifactStore(root),
        changeset_store=ObsidianChangeSetStore(root),
        extraction_model=FakePostSessionExtractionModel(extraction, error=extraction_error),
        rendering_model=FakePostSessionRenderingModel(make_render_output(), error=render_error),
    )
