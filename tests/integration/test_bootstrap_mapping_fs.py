"""S13-03 bootstrap mapping + persistence filesystem integration tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from dnd_assistant.application.bootstrap_canonical import CanonicalCoverageReason
from dnd_assistant.application.bootstrap_changeset import BootstrapUnresolvedReason
from dnd_assistant.application.bootstrap_evidence import (
    BOOTSTRAP_EVIDENCE_SCHEMA_VERSION,
    build_bootstrap_evidence,
    persist_bootstrap_evidence,
)
from dnd_assistant.application.bootstrap_input import prepare_bootstrap_input, source_ref
from dnd_assistant.application.bootstrap_mapping import run_bootstrap_mapping
from dnd_assistant.application.bootstrap_result import BootstrapMappingOutcome
from dnd_assistant.application.changeset_store import persist_proposal
from dnd_assistant.application.vault_discovery import (
    VaultDiscoveryService,
)
from dnd_assistant.composition.bootstrap import canonical_candidates_from_report
from dnd_assistant.domain.bootstrap_extraction import (
    BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
    BootstrapExtraction,
)
from dnd_assistant.domain.types import EntityType
from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.bootstrap_evidence import ObsidianBootstrapEvidenceStore
from dnd_assistant.storage.changeset_store import ObsidianChangeSetStore
from dnd_assistant.storage.vault_discovery import ObsidianVaultSourceReader
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository
from tests.unit.bootstrap.helpers import (
    FakeBootstrapModel,
    canonical_text,
    make_candidate,
)

_CAMP = "camp-test"
_NPC_PATH = "Characters/NPCs/varos.md"
_MALFORMED_PATH = "Characters/NPCs/old-note.md"
_NOTE_PATH = "Campaign/Overview.md"


def _write_vault(root: Path) -> None:
    (root / "_system" / "audit").mkdir(parents=True)
    (root / "_system" / "campaign.yaml").write_text(
        f"schema_version: 1\ncampaign_id: {_CAMP}\n", encoding="utf-8"
    )
    (root / "_system" / "audit" / "audit.jsonl").write_text("", encoding="utf-8")
    (root / "Characters" / "NPCs").mkdir(parents=True)
    (root / _NPC_PATH).write_text(
        canonical_text("npc-1", EntityType.NPC, "Варос"), encoding="utf-8", newline=""
    )
    (root / _MALFORMED_PATH).write_text("# just a historical note\n", encoding="utf-8")
    (root / "Campaign").mkdir()
    (root / _NOTE_PATH).write_text("# Обзор\nПартия в Сером Броде.\n", encoding="utf-8")


def _tree_snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    snapshot: dict[str, tuple[int, int, str]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            stat = path.stat()
            snapshot[str(path.relative_to(root)).replace("\\", "/")] = (
                stat.st_size,
                stat.st_mtime_ns,
                hashlib.sha256(data).hexdigest(),
            )
    return snapshot


def _report(root: Path):
    reader = ObsidianVaultSourceReader(root)
    return VaultDiscoveryService(reader).run()


def _extraction():
    ref = source_ref(_CAMP, _NOTE_PATH)
    return BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(make_candidate("c1", "Новый NPC", EntityType.NPC, [ref]),),
    )


def test_mapping_persists_only_workflow_artifacts(tmp_path: Path) -> None:
    _write_vault(tmp_path)
    before = _tree_snapshot(tmp_path)
    audit_before = (tmp_path / "_system" / "audit" / "audit.jsonl").read_bytes()

    report = _report(tmp_path)
    candidates = canonical_candidates_from_report(report)
    run = run_bootstrap_mapping(
        report, candidates, FakeBootstrapModel(_extraction()), model_identity=None
    )
    # The malformed historical note is never treated as canonical.
    assert all(view.relative_path != _MALFORMED_PATH for view in run.snapshot.bindable)
    assert any(issue.relative_path == _MALFORMED_PATH for issue in run.snapshot.issues)
    assert run.result.changeset is not None

    store = ObsidianChangeSetStore(tmp_path)
    persist_proposal(store, run.result.changeset)
    record = build_bootstrap_evidence(
        run.projection,
        run.result,
        producer_version=run.processor_version,
        prompt_version=run.prompt_version,
        extraction_schema_version=run.extraction_schema_version,
    )
    persist_bootstrap_evidence(ObsidianBootstrapEvidenceStore(tmp_path), record)

    after = _tree_snapshot(tmp_path)
    changed = {path for path, value in after.items() if before.get(path) != value}
    # Only workflow/control artifacts may be added/changed.
    allowed_prefixes = ("_system/changesets/", "_system/bootstrap/")
    assert changed, "expected workflow artifacts to be created"
    assert all(path.startswith(allowed_prefixes) for path in changed), changed
    assert (tmp_path / "_system" / "audit" / "audit.jsonl").read_bytes() == audit_before
    # Canonical entity content unchanged (hash + mtime).
    assert before[_NPC_PATH] == after[_NPC_PATH]


def test_rediscovery_fingerprint_is_unchanged_after_persistence(tmp_path: Path) -> None:
    _write_vault(tmp_path)
    first = prepare_bootstrap_input(_report(tmp_path)).input_fingerprint

    run = run_bootstrap_mapping(
        _report(tmp_path),
        canonical_candidates_from_report(_report(tmp_path)),
        FakeBootstrapModel(_extraction()),
    )
    assert run.result.changeset is not None
    persist_proposal(ObsidianChangeSetStore(tmp_path), run.result.changeset)
    persist_bootstrap_evidence(
        ObsidianBootstrapEvidenceStore(tmp_path),
        build_bootstrap_evidence(
            run.projection,
            run.result,
            producer_version=run.processor_version,
            prompt_version=run.prompt_version,
            extraction_schema_version=run.extraction_schema_version,
        ),
    )

    second = prepare_bootstrap_input(_report(tmp_path)).input_fingerprint
    assert second == first


def test_same_id_different_content_fails_closed(tmp_path: Path) -> None:
    _write_vault(tmp_path)
    report = _report(tmp_path)
    run = run_bootstrap_mapping(
        report, canonical_candidates_from_report(report), FakeBootstrapModel(_extraction())
    )
    assert run.result.changeset is not None
    store = ObsidianChangeSetStore(tmp_path)
    persist_proposal(store, run.result.changeset)

    from dnd_assistant.application.changeset_review import compute_changeset_fingerprint

    changed = run.result.changeset.model_copy(
        update={
            "operations": (
                run.result.changeset.operations[0].model_copy(update={"name": "Другое имя"}),
            )
        }
    )
    assert compute_changeset_fingerprint(changed) != compute_changeset_fingerprint(
        run.result.changeset
    )
    with pytest.raises(ConflictError):
        persist_proposal(store, changed)


def test_normal_repository_strictness_is_unchanged(tmp_path: Path) -> None:
    _write_vault(tmp_path)
    repository = ObsidianVaultRepository(
        vault_root=str(tmp_path),
        audit_service=AuditService(str(tmp_path / "_system" / "audit" / "audit.jsonl")),
    )
    # The malformed historical note makes the strict repository fail closed.
    with pytest.raises(StorageError):
        repository.list_entities()


def test_runtime_evidence_uses_extraction_schema_version(tmp_path: Path, monkeypatch) -> None:
    from dnd_assistant.application.bootstrap_evidence import deserialize_bootstrap_evidence
    from dnd_assistant.composition.bootstrap import BootstrapModelIdentity, BootstrapRuntime

    _write_vault(tmp_path)
    fake = FakeBootstrapModel(_extraction())

    class _Adapter:
        def __init__(self, *, model: object) -> None:
            pass

        def extract(self, request):  # type: ignore[no-untyped-def]
            return fake.extract(request)

    monkeypatch.setattr(
        "dnd_assistant.application.pydantic_ai_bootstrap.PydanticAIBootstrapExtractionModel",
        _Adapter,
    )
    dummy_model: Any = object()
    runtime = BootstrapRuntime(
        model=dummy_model,
        model_identity=BootstrapModelIdentity(profile="heavy"),
        vault_root=tmp_path,
        profile_name="heavy",
        changeset_store=ObsidianChangeSetStore(tmp_path),
        evidence_store=ObsidianBootstrapEvidenceStore(tmp_path),
    )
    try:
        result = runtime.run(_report(tmp_path), persist=True)
    finally:
        runtime.close()

    assert result.run.extraction_schema_version == BOOTSTRAP_EXTRACTION_SCHEMA_VERSION
    assert result.evidence_record is not None
    assert result.evidence_record.extraction_schema_version == BOOTSTRAP_EXTRACTION_SCHEMA_VERSION
    assert result.evidence_record.schema_version == BOOTSTRAP_EVIDENCE_SCHEMA_VERSION
    assert result.run.result.changeset is not None
    stored = ObsidianBootstrapEvidenceStore(tmp_path).read_evidence_if_present(
        result.run.result.changeset.changeset_id
    )
    assert stored is not None
    assert (
        deserialize_bootstrap_evidence(stored).extraction_schema_version
        == BOOTSTRAP_EXTRACTION_SCHEMA_VERSION
    )


def _excluded_pairs(root: Path) -> set[tuple[str, bool]]:
    return {(entry.relative_path, entry.is_directory) for entry in _report(root).excluded}


def test_excluded_subtree_in_managed_namespace_blocks_coverage(tmp_path: Path) -> None:
    _write_vault(tmp_path)
    (tmp_path / "Characters" / "NPCs" / ".archive").mkdir()
    (tmp_path / "Characters" / "NPCs" / ".archive" / "hidden.md").write_text(
        canonical_text("npc-2", EntityType.NPC, "Скрытый"), encoding="utf-8"
    )

    report = _report(tmp_path)
    paths = {entry.relative_path for entry in report.entries}
    assert "Characters/NPCs/.archive" not in paths
    assert "Characters/NPCs/.archive/hidden.md" not in paths
    assert ("Characters/NPCs/.archive", True) in {
        (entry.relative_path, entry.is_directory) for entry in report.excluded
    }

    model = FakeBootstrapModel(_extraction())
    run = run_bootstrap_mapping(report, canonical_candidates_from_report(report), model)
    assert run.coverage.complete is False
    assert any(
        issue.reason is CanonicalCoverageReason.EXCLUDED_CANONICAL_PATH
        and issue.relative_path == "Characters/NPCs/.archive"
        for issue in run.coverage.issues
    )
    assert run.result.outcome is BootstrapMappingOutcome.NO_CHANGES
    assert run.result.changeset is None
    assert model.requests == []
    assert any(
        item.reason is BootstrapUnresolvedReason.CANONICAL_COVERAGE_INCOMPLETE
        for item in run.result.unresolved
    )


def test_excluded_markdown_file_in_managed_namespace_blocks_coverage(tmp_path: Path) -> None:
    _write_vault(tmp_path)
    (tmp_path / "Characters" / "NPCs" / "~legacy.md").write_text("# legacy\n", encoding="utf-8")

    report = _report(tmp_path)
    assert "Characters/NPCs/~legacy.md" not in {entry.relative_path for entry in report.entries}
    assert ("Characters/NPCs/~legacy.md", False) in {
        (entry.relative_path, entry.is_directory) for entry in report.excluded
    }

    model = FakeBootstrapModel(_extraction())
    run = run_bootstrap_mapping(report, canonical_candidates_from_report(report), model)
    assert run.coverage.complete is False
    assert any(
        issue.reason is CanonicalCoverageReason.EXCLUDED_CANONICAL_PATH
        and issue.relative_path == "Characters/NPCs/~legacy.md"
        for issue in run.coverage.issues
    )
    assert run.result.changeset is None
    assert model.requests == []
    assert any(
        item.reason is BootstrapUnresolvedReason.CANONICAL_COVERAGE_INCOMPLETE
        for item in run.result.unresolved
    )


def test_root_infrastructure_exclusions_do_not_block_coverage(tmp_path: Path) -> None:
    _write_vault(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")

    report = _report(tmp_path)
    assert {entry.relative_path for entry in report.entries}.isdisjoint({".git", ".obsidian"})
    assert _excluded_pairs(tmp_path) >= {(".git", True), (".obsidian", True)}

    run = run_bootstrap_mapping(
        report, canonical_candidates_from_report(report), FakeBootstrapModel()
    )
    assert run.coverage.complete is True


def test_os_metadata_exclusion_does_not_block_coverage(tmp_path: Path) -> None:
    _write_vault(tmp_path)
    (tmp_path / "Characters" / "NPCs" / ".DS_Store").write_text("x", encoding="utf-8")

    report = _report(tmp_path)
    assert "Characters/NPCs/.DS_Store" not in {entry.relative_path for entry in report.entries}
    assert ("Characters/NPCs/.DS_Store", False) in {
        (entry.relative_path, entry.is_directory) for entry in report.excluded
    }

    run = run_bootstrap_mapping(
        report, canonical_candidates_from_report(report), FakeBootstrapModel()
    )
    assert run.coverage.complete is True
    assert all(issue.relative_path != "Characters/NPCs/.DS_Store" for issue in run.coverage.issues)
