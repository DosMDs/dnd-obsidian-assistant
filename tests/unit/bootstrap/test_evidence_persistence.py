"""S13-03 bootstrap evidence serialization and persistence tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from dnd_assistant.application.bootstrap_evidence import (
    BOOTSTRAP_EVIDENCE_SCHEMA_VERSION,
    EvidencePersistOutcome,
    EvidenceSource,
    build_bootstrap_evidence,
    deserialize_bootstrap_evidence,
    persist_bootstrap_evidence,
    serialize_bootstrap_evidence,
)
from dnd_assistant.application.bootstrap_input import source_ref
from dnd_assistant.application.bootstrap_mapping import run_bootstrap_mapping
from dnd_assistant.application.vault_discovery import SourceClass
from dnd_assistant.composition.bootstrap import canonical_candidates_from_report
from dnd_assistant.domain.bootstrap_extraction import (
    BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
    BootstrapExtraction,
)
from dnd_assistant.domain.types import EntityType
from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.bootstrap_evidence import ObsidianBootstrapEvidenceStore
from tests.unit.bootstrap.helpers import (
    FakeBootstrapModel,
    canonical_text,
    make_candidate,
    make_report,
    make_source,
)

_CAMP = "camp-1"
_PATH = "Characters/NPCs/varos.md"
_REF = source_ref(_CAMP, _PATH)


def _run():
    report = make_report(
        _CAMP,
        [
            make_source(
                _PATH,
                SourceClass.ENTITY_CANDIDATE,
                canonical_text("npc-1", EntityType.NPC, "Варос"),
            ),
            make_source("Notes/roleplay.md", SourceClass.USER_SOURCE, "история"),
        ],
    )
    extraction = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(make_candidate("c1", "Новый NPC", EntityType.NPC, [_REF]),),
    )
    return run_bootstrap_mapping(
        report, canonical_candidates_from_report(report), FakeBootstrapModel(extraction)
    )


def _record(run):
    return build_bootstrap_evidence(
        run.projection,
        run.result,
        producer_version=run.processor_version,
        prompt_version=run.prompt_version,
        extraction_schema_version=BOOTSTRAP_EVIDENCE_SCHEMA_VERSION,
        model_profile="heavy",
        model="m",
        provider="ollama",
    )


def test_evidence_round_trips_and_records_relative_paths_only() -> None:
    record = _record(_run())
    text = serialize_bootstrap_evidence(record)
    parsed = deserialize_bootstrap_evidence(text)
    assert parsed == record
    for source in record.sources:
        assert not source.relative_path.startswith("/")
        assert "\\" not in source.relative_path


def test_evidence_rejects_absolute_path() -> None:
    with pytest.raises(ValidationError):
        EvidenceSource(
            source_ref=_REF,
            relative_path="/etc/passwd",
            source_class="user_source",
            size_bytes=1,
            included=True,
        )


def _store(tmp_path: Path) -> ObsidianBootstrapEvidenceStore:
    (tmp_path / "_system").mkdir(parents=True, exist_ok=True)
    return ObsidianBootstrapEvidenceStore(tmp_path)


def test_persist_is_exclusive_idempotent_and_conflict_aware(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _record(_run())
    assert persist_bootstrap_evidence(store, record) is EvidencePersistOutcome.CREATED
    assert persist_bootstrap_evidence(store, record) is EvidencePersistOutcome.ALREADY_PRESENT

    other = record.model_copy(update={"changeset_id": "cs_other"})
    assert persist_bootstrap_evidence(store, other) is EvidencePersistOutcome.CREATED
    conflicting = other.model_copy(update={"campaign_id": "different-campaign"})
    with pytest.raises(ConflictError):
        persist_bootstrap_evidence(store, conflicting)


def test_malformed_persisted_evidence_is_storage_error(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create_evidence("cs_x", "not json\n")
    assert store.read_evidence_if_present("cs_x") == "not json\n"
    with pytest.raises(StorageError):
        deserialize_bootstrap_evidence("not json\n")
