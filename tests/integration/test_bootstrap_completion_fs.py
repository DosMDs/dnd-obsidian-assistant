"""S13-05 bootstrap finalization filesystem integration tests.

The accepted S13-03 proposal/evidence persistence is exercised through the real
``BootstrapRuntime.run(persist=True)``.  Only the extraction adapter is replaced
with a deterministic fake extraction model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import dnd_assistant.composition.bootstrap_completion as bc
from dnd_assistant.application.bootstrap_completion import BootstrapCompletionStatus
from dnd_assistant.application.bootstrap_input import source_ref
from dnd_assistant.application.campaign_state_materialization import (
    CampaignStateSourceChangedError,
    CampaignStateStatus,
)
from dnd_assistant.cli.main import app as cli_app
from dnd_assistant.composition.audit_context import build_audit_context
from dnd_assistant.composition.bootstrap import compose_bootstrap_discovery
from dnd_assistant.composition.bootstrap_completion import finalize_bootstrap
from dnd_assistant.composition.world_time import compose_world_time_repository
from dnd_assistant.domain.bootstrap_extraction import (
    BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
    BootstrapExtraction,
)
from dnd_assistant.domain.types import EntityType
from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.changeset_store import ObsidianChangeSetStore
from dnd_assistant.storage.session_metadata import ObsidianSessionMetadataRepository
from tests.unit.bootstrap.helpers import (
    FakeBootstrapModel,
    canonical_text,
    make_candidate,
    make_claim,
    make_reference,
)

_CAMP = "camp-s13-05"
_NPC_PATH = "Characters/NPCs/varos.md"
_NOTE_PATH = "Campaign/Overview.md"
_REF_NEW = source_ref(_CAMP, _NOTE_PATH)
_REF_VAROS = source_ref(_CAMP, _NPC_PATH)
_OVERSIZE = 1_100_000
_runner = CliRunner()


def _write_config(tmp_path: Path) -> Path:
    config = tmp_path / "config.toml"
    config.write_text(
        "[profiles]\n"
        "[profiles.heavy]\n"
        'provider = "ollama"\n'
        'model = "m"\n'
        'base_url = "http://localhost:11434"\n'
        'role = "bootstrap"\n',
        encoding="utf-8",
    )
    return config


def _write_vault(
    root: Path,
    *,
    world_tick: int | None = 0,
    malformed: bool = False,
    oversized: bool = False,
) -> None:
    (root / "_system" / "audit").mkdir(parents=True)
    (root / "_system" / "campaign.yaml").write_text(
        f"schema_version: 1\ncampaign_id: {_CAMP}\n", encoding="utf-8"
    )
    (root / "_system" / "audit" / "audit.jsonl").write_text("", encoding="utf-8")
    (root / "_system" / "raw" / "sessions").mkdir(parents=True)
    (root / "Sessions").mkdir()
    (root / "Characters" / "NPCs").mkdir(parents=True)
    (root / _NPC_PATH).write_text(
        canonical_text("npc-1", EntityType.NPC, "Варос"), encoding="utf-8", newline=""
    )
    (root / "Campaign").mkdir()
    (root / _NOTE_PATH).write_text("# Обзор\nНовый герой.\n", encoding="utf-8")
    if malformed:
        (root / "Characters" / "NPCs" / "old-note.md").write_text(
            "# историческая заметка\n", encoding="utf-8"
        )
    if oversized:
        big = canonical_text("npc-2", EntityType.NPC, "Великан") + ("x" * _OVERSIZE)
        (root / "Characters" / "NPCs" / "giant.md").write_text(big, encoding="utf-8", newline="")
    if world_tick is not None:
        repo = compose_world_time_repository(root)
        repo.initialize_current_world_time(
            world_tick, audit=build_audit_context(source="test", prefix="test-time")
        )


def _proposal_extraction() -> BootstrapExtraction:
    return BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(make_candidate("c1", "Новый Герой", EntityType.NPC, [_REF_NEW]),),
        claims=(
            make_claim(
                "cl1",
                "Варос — союзник партии.",
                [_REF_VAROS],
                references=(make_reference("r1", "Варос", EntityType.NPC, [_REF_VAROS]),),
            ),
        ),
    )


def _patch_adapter(monkeypatch: pytest.MonkeyPatch, fake: FakeBootstrapModel) -> None:
    def factory(*, model: Any) -> FakeBootstrapModel:
        return fake

    monkeypatch.setattr(
        "dnd_assistant.application.pydantic_ai_bootstrap.PydanticAIBootstrapExtractionModel",
        factory,
    )


def _dummy_model_factory(_profile: object) -> Any:
    return object()


def _finalize(
    root: Path,
    config: Path,
    *,
    acknowledge: bool = False,
):
    return finalize_bootstrap(
        vault_root=root,
        config_path=config,
        profile_name="heavy",
        acknowledge_unresolved=acknowledge,
        model_factory=_dummy_model_factory,
    )


def _derived_paths(root: Path) -> list[str]:
    return sorted(
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*")
        if path.is_file()
        and (
            str(path.relative_to(root)).startswith("State")
            or str(path.relative_to(root)).startswith("_system/indexes")
        )
    )


def _proposal_files(root: Path) -> list[Path]:
    return (
        list((root / "_system" / "changesets").glob("*.proposal.json"))
        if (root / "_system" / "changesets").exists()
        else []
    )


# ── Clean paths ───────────────────────────────────────────────────────────


def test_clean_no_changes_reaches_complete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_vault(tmp_path)
    fake = FakeBootstrapModel()
    _patch_adapter(monkeypatch, fake)

    result = _finalize(tmp_path, _write_config(tmp_path))

    assert result.status is BootstrapCompletionStatus.COMPLETE
    assert result.completed
    assert result.campaign_state_status is CampaignStateStatus.CURRENT
    assert result.fts_verified is True
    assert result.final_source_stable is True
    assert result.changeset_id is None
    assert _proposal_files(tmp_path) == []
    assert fake.requests, "the model should have been called for the eligible note"
    assert (tmp_path / "State" / ".campaign-state-manifest.json").is_file()


def test_complete_supports_negative_world_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_vault(tmp_path, world_tick=-42)
    fake = FakeBootstrapModel()
    _patch_adapter(monkeypatch, fake)

    result = _finalize(tmp_path, _write_config(tmp_path))

    assert result.status is BootstrapCompletionStatus.COMPLETE
    assert result.current_world_tick == -42


# ── C1: incomplete canonical coverage is never acknowledgeable ────────────


def test_coverage_incomplete_blocks_even_with_acknowledgement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_vault(tmp_path, oversized=True)
    fake = FakeBootstrapModel()
    _patch_adapter(monkeypatch, fake)

    result = _finalize(tmp_path, _write_config(tmp_path), acknowledge=True)

    assert result.status is BootstrapCompletionStatus.CANONICAL_COVERAGE_INCOMPLETE
    assert result.coverage_complete is False
    assert fake.requests == []
    assert _derived_paths(tmp_path) == []


# ── C2: proposal persistence + source drift ordering ──────────────────────


def _drift_on_second_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    real = compose_bootstrap_discovery
    calls = {"count": 0}

    def wrapper(root: Path):
        calls["count"] += 1
        if calls["count"] == 2:
            (root / "Campaign" / "Overview.md").write_text(
                "# Обзор\nИзменено во время проверки.\n", encoding="utf-8"
            )
        return real(root)

    monkeypatch.setattr(bc, "compose_bootstrap_discovery", wrapper)


def test_persisted_proposal_source_drift_is_not_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_vault(tmp_path)
    fake = FakeBootstrapModel(_proposal_extraction())
    _patch_adapter(monkeypatch, fake)
    _drift_on_second_discovery(monkeypatch)

    result = _finalize(tmp_path, _write_config(tmp_path))

    assert result.status is BootstrapCompletionStatus.SOURCE_CHANGED_DURING_VALIDATION
    assert result.changeset_id is not None
    assert result.status is not BootstrapCompletionStatus.PENDING_CHANGESET
    assert len(_proposal_files(tmp_path)) == 1
    assert _derived_paths(tmp_path) == []


def test_stable_proposal_is_pending_changeset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_vault(tmp_path)
    fake = FakeBootstrapModel(_proposal_extraction())
    _patch_adapter(monkeypatch, fake)

    result = _finalize(tmp_path, _write_config(tmp_path))

    assert result.status is BootstrapCompletionStatus.PENDING_CHANGESET
    assert result.changeset_id is not None
    proposals = _proposal_files(tmp_path)
    assert len(proposals) == 1
    assert (tmp_path / "_system" / "bootstrap" / f"{result.changeset_id}.mapping.json").is_file()
    # The existing S13-04 loader can consume the emitted workflow artifacts.
    from dnd_assistant.application.bootstrap_review import load_bootstrap_bundle
    from dnd_assistant.storage.bootstrap_evidence import ObsidianBootstrapEvidenceStore

    bundle = load_bootstrap_bundle(
        ObsidianChangeSetStore(tmp_path),
        ObsidianBootstrapEvidenceStore(tmp_path),
        result.changeset_id,
    )
    assert bundle.changeset.changeset_id == result.changeset_id
    assert bundle.evidence_present is True
    assert _derived_paths(tmp_path) == []


def test_partial_evidence_persistence_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_vault(tmp_path)
    fake = FakeBootstrapModel(_proposal_extraction())
    _patch_adapter(monkeypatch, fake)

    def boom(_store: Any, _record: Any) -> None:
        raise StorageError("test evidence persistence failure")

    monkeypatch.setattr("dnd_assistant.composition.bootstrap.persist_bootstrap_evidence", boom)

    result = _finalize(tmp_path, _write_config(tmp_path))

    assert result.status is BootstrapCompletionStatus.EVIDENCE_PERSISTENCE_FAILED
    assert len(_proposal_files(tmp_path)) == 1
    assert _derived_paths(tmp_path) == []


def test_partial_persistence_with_drift_prefers_source_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_vault(tmp_path)
    fake = FakeBootstrapModel(_proposal_extraction())
    _patch_adapter(monkeypatch, fake)
    _drift_on_second_discovery(monkeypatch)

    def boom(_store: Any, _record: Any) -> None:
        raise StorageError("test evidence persistence failure")

    monkeypatch.setattr("dnd_assistant.composition.bootstrap.persist_bootstrap_evidence", boom)

    result = _finalize(tmp_path, _write_config(tmp_path))

    assert result.status is BootstrapCompletionStatus.SOURCE_CHANGED_DURING_VALIDATION
    assert any("evidence persistence" in issue.lower() for issue in result.issues)
    assert len(_proposal_files(tmp_path)) == 1
    assert not (tmp_path / "_system" / "bootstrap").exists() or not list(
        (tmp_path / "_system" / "bootstrap").glob("*.json")
    )
    assert _derived_paths(tmp_path) == []


# ── C3: source races vs ordinary derived failures ─────────────────────────


def test_campaign_state_source_race_skips_fts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_vault(tmp_path)
    fake = FakeBootstrapModel()
    _patch_adapter(monkeypatch, fake)

    def race(**_kwargs: Any) -> None:
        raise CampaignStateSourceChangedError("test source race")

    fts_calls: list[Path] = []

    def fake_fts(root: Path):
        fts_calls.append(root)
        raise StorageError("must not run")

    monkeypatch.setattr(bc, "rebuild_campaign_state", race)
    monkeypatch.setattr(bc, "rebuild_fts_index", fake_fts)

    result = _finalize(tmp_path, _write_config(tmp_path))

    assert result.status is BootstrapCompletionStatus.SOURCE_CHANGED_DURING_VALIDATION
    assert fts_calls == []


def test_ordinary_campaign_state_failure_keeps_fts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_vault(tmp_path)
    fake = FakeBootstrapModel()
    _patch_adapter(monkeypatch, fake)

    def fail(**_kwargs: Any) -> None:
        raise StorageError("test campaign state storage failure")

    monkeypatch.setattr(bc, "rebuild_campaign_state", fail)

    result = _finalize(tmp_path, _write_config(tmp_path))

    assert result.status is BootstrapCompletionStatus.CAMPAIGN_STATE_REBUILD_FAILED
    assert result.fts_verified is True
    assert (tmp_path / "_system" / "indexes").exists()


# ── C4: active session vs corrupt session state ───────────────────────────


def test_multiple_active_sessions_is_not_active_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_vault(tmp_path)
    fake = FakeBootstrapModel()
    _patch_adapter(monkeypatch, fake)

    def conflict(self: object) -> None:
        raise ConflictError("Multiple active sessions found (2): s1, s2")

    monkeypatch.setattr(ObsidianSessionMetadataRepository, "get_active_session", conflict)

    result = _finalize(tmp_path, _write_config(tmp_path))

    assert result.status is BootstrapCompletionStatus.RECOVERY_BLOCKED
    assert result.status is not BootstrapCompletionStatus.ACTIVE_SESSION_PRESENT
    assert _derived_paths(tmp_path) == []


# ── Strict canonical validation / prerequisites ───────────────────────────


def test_malformed_canonical_note_blocks_before_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_vault(tmp_path, malformed=True)
    fake = FakeBootstrapModel()
    _patch_adapter(monkeypatch, fake)

    result = _finalize(tmp_path, _write_config(tmp_path))

    assert result.status is BootstrapCompletionStatus.CANONICAL_NOT_READY
    assert fake.requests == []
    assert _derived_paths(tmp_path) == []


def test_missing_world_time_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_vault(tmp_path, world_tick=None)
    fake = FakeBootstrapModel()
    _patch_adapter(monkeypatch, fake)

    result = _finalize(tmp_path, _write_config(tmp_path))

    assert result.status is BootstrapCompletionStatus.WORLD_TIME_UNINITIALIZED
    assert fake.requests == []


def test_uninitialized_vault_is_reported(tmp_path: Path) -> None:
    fake = FakeBootstrapModel()
    result = finalize_bootstrap(
        vault_root=tmp_path,
        config_path=_write_config(tmp_path),
        profile_name="heavy",
        model_factory=_dummy_model_factory,
    )
    assert result.status is BootstrapCompletionStatus.UNINITIALIZED_VAULT
    assert fake.requests == []


# ── Final source stability ────────────────────────────────────────────────


def test_source_drift_after_derived_rebuild_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_vault(tmp_path)
    fake = FakeBootstrapModel()
    _patch_adapter(monkeypatch, fake)

    real = compose_bootstrap_discovery
    calls = {"count": 0}

    def wrapper(root: Path):
        calls["count"] += 1
        # 1 initial, 2 stability recheck, 3 final stability check -> mutate at 3
        if calls["count"] == 3:
            (root / "Campaign" / "Overview.md").write_text(
                "# Обзор\nПозднее изменение.\n", encoding="utf-8"
            )
        return real(root)

    monkeypatch.setattr(bc, "compose_bootstrap_discovery", wrapper)

    result = _finalize(tmp_path, _write_config(tmp_path))

    assert result.status is BootstrapCompletionStatus.SOURCE_CHANGED_DURING_VALIDATION
    assert result.final_source_stable is False
    assert result.fts_verified is True


# ── CLI presentation ──────────────────────────────────────────────────────


def test_finalize_cli_complete_renders_russian(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_vault(tmp_path)
    fake = FakeBootstrapModel()
    _patch_adapter(monkeypatch, fake)

    result = _runner.invoke(
        cli_app,
        [
            "bootstrap",
            "finalize",
            "--vault",
            str(tmp_path),
            "--config",
            str(_write_config(tmp_path)),
            "--profile",
            "heavy",
        ],
    )

    assert result.exit_code == 0
    assert "ЗАВЕРШЕНО" in result.stdout


def test_finalize_cli_pending_changeset_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_vault(tmp_path)
    fake = FakeBootstrapModel(_proposal_extraction())
    _patch_adapter(monkeypatch, fake)

    result = _runner.invoke(
        cli_app,
        [
            "bootstrap",
            "finalize",
            "--vault",
            str(tmp_path),
            "--config",
            str(_write_config(tmp_path)),
            "--profile",
            "heavy",
        ],
    )

    assert result.exit_code != 0
    assert "ОЖИДАЕТ" in result.stdout
    assert "bootstrap review" in result.stdout
