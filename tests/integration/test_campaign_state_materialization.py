"""S12-03 Campaign State materialization integration tests.

Exercises a real temporary Vault with the real repositories, the real
derived-state store and the real materialization service: publication,
``ALREADY_CURRENT``, staleness, repair, deterministic rebuild, calendar
handling, player-only State bytes, manifest-last ordering and canonical
read-only safety.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from dnd_assistant.application.campaign_state_source import build_campaign_state
from dnd_assistant.domain.campaign_state import CampaignStateArtifact
from dnd_assistant.domain.types import Visibility
from dnd_assistant.storage.derived_state import ARTIFACT_FILENAMES, MANIFEST_FILENAME
from tests.unit.campaign_state.helpers import (
    BASE_START,
    Services,
    close_session,
    create_entity,
    make_audit_context,
    make_calendar,
    make_calendar_with_intercalary,
    make_entity,
    make_services,
    make_vault,
    rebuild,
    setup_entity_dirs,
    snapshot,
)

_WORLD = CampaignStateArtifact.WORLD_STATE
_TOUCHED = CampaignStateArtifact.RECENTLY_TOUCHED


def _services(tmp_path: Path, *, tick: int = 150) -> Services:
    root = make_vault(tmp_path)
    setup_entity_dirs(root)
    services = make_services(root)
    services.world_time.initialize_current_world_time(
        tick,
        audit=make_audit_context(operation_id="wt-init", real_time=BASE_START),
    )
    return services


def _text(services: Services, artifact: CampaignStateArtifact) -> str:
    data = services.store.read_artifact_bytes(artifact)
    assert data is not None
    return data.decode("utf-8")


# ── Publication / idempotency ─────────────────────────────────────────────


class TestPublication:
    def test_first_publication_then_already_current(self, tmp_path: Path) -> None:
        services = _services(tmp_path)
        create_entity(services, make_entity("npc-aria"))
        close_session(
            services, "S001", finish=BASE_START + timedelta(hours=1), touched=("npc-aria",)
        )

        from dnd_assistant.application.campaign_state_materialization import (
            CampaignStateRebuildStatus,
        )

        first = rebuild(services)
        assert first.status is CampaignStateRebuildStatus.PUBLISHED
        assert (services.store.state_dir / MANIFEST_FILENAME).exists()

        second = rebuild(services)
        assert second.status is CampaignStateRebuildStatus.ALREADY_CURRENT

    def test_manifest_written_last(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import dnd_assistant.storage.derived_state as ds

        services = _services(tmp_path)
        create_entity(services, make_entity("npc-aria"))
        close_session(
            services, "S001", finish=BASE_START + timedelta(hours=1), touched=("npc-aria",)
        )

        calls: list[str] = []
        original = ds.atomic_write_text

        def recording(target, content, *, validator):
            calls.append(Path(target).name)
            return original(target, content, validator=validator)

        monkeypatch.setattr(ds, "atomic_write_text", recording)
        rebuild(services)

        assert calls[-1] == MANIFEST_FILENAME
        assert calls[:-1] == [ARTIFACT_FILENAMES[a] for a in (_WORLD, _TOUCHED)]


# ── Visibility ────────────────────────────────────────────────────────────


class TestVisibility:
    def test_dm_system_absent_from_persisted_bytes(self, tmp_path: Path) -> None:
        services = _services(tmp_path)
        create_entity(services, make_entity("npc-player", name="Aria"))
        create_entity(services, make_entity("npc-dm", name="Тайный Лорд", visibility=Visibility.DM))
        create_entity(
            services, make_entity("npc-sys", name="Система", visibility=Visibility.SYSTEM)
        )
        close_session(
            services,
            "S001",
            finish=BASE_START + timedelta(hours=1),
            touched=("npc-player", "npc-dm", "npc-sys"),
        )

        result = rebuild(services)
        # Internal projection remains all-visibility.
        assert {r.visibility for r in result.state.recently_touched} == {
            Visibility.PLAYER,
            Visibility.DM,
            Visibility.SYSTEM,
        }

        touched_text = _text(services, _TOUCHED)
        assert "Aria" in touched_text
        for leaked in ("npc-dm", "Тайный Лорд", "npc-sys", "Система"):
            assert leaked not in touched_text

    def test_internal_source_collection_still_all_visibility(self, tmp_path: Path) -> None:
        services = _services(tmp_path)
        create_entity(services, make_entity("npc-dm", visibility=Visibility.DM))
        close_session(services, "S001", finish=BASE_START + timedelta(hours=1), touched=("npc-dm",))
        build = build_campaign_state(
            vault_repository=services.vault,
            session_repository=services.metadata,
            world_time_repository=services.world_time,
            recent_session_limit=5,
        )
        assert build.state.recently_touched[0].visibility is Visibility.DM


# ── Deterministic rebuild ─────────────────────────────────────────────────


class TestDeterministicRebuild:
    def test_repeated_rebuild_byte_identical(self, tmp_path: Path) -> None:
        services = _services(tmp_path)
        create_entity(services, make_entity("npc-aria"))
        close_session(
            services, "S001", finish=BASE_START + timedelta(hours=1), touched=("npc-aria",)
        )
        rebuild(services)
        first = _text(services, _WORLD), _text(services, _TOUCHED)
        rebuild(services)
        assert (_text(services, _WORLD), _text(services, _TOUCHED)) == first

    def test_delete_all_managed_files_deterministic_rebuild(self, tmp_path: Path) -> None:
        import shutil

        services = _services(tmp_path)
        create_entity(services, make_entity("npc-aria"))
        close_session(
            services, "S001", finish=BASE_START + timedelta(hours=1), touched=("npc-aria",)
        )
        rebuild(services)
        before = _text(services, _WORLD), _text(services, _TOUCHED)

        shutil.rmtree(services.store.state_dir)
        rebuild(services)
        assert (_text(services, _WORLD), _text(services, _TOUCHED)) == before


# ── Freshness / staleness / repair ────────────────────────────────────────


class TestFreshness:
    def _seed(self, tmp_path: Path) -> Services:
        services = _services(tmp_path)
        create_entity(services, make_entity("npc-aria"))
        create_entity(services, make_entity("npc-other", name="Other"))
        close_session(
            services, "S001", finish=BASE_START + timedelta(hours=1), touched=("npc-aria",)
        )
        rebuild(services)
        return services

    def test_world_tick_change_is_stale_then_repaired(self, tmp_path: Path) -> None:
        from dnd_assistant.application.campaign_state_materialization import (
            CampaignStateStatus,
            inspect_campaign_state,
        )

        services = self._seed(tmp_path)
        services.world_time.set_current_world_time(
            999,
            expected_revision=1,
            audit=make_audit_context(operation_id="wt-set", real_time=BASE_START),
        )
        inspection = inspect_campaign_state(
            vault_repository=services.vault,
            session_repository=services.metadata,
            world_time_repository=services.world_time,
            derived_state_store=services.store,
            recent_session_limit=5,
        )
        assert inspection.status is CampaignStateStatus.STALE

        rebuild(services)
        assert "999" in _text(services, _WORLD)

    def test_selected_entity_revision_change_is_stale(self, tmp_path: Path) -> None:
        from dnd_assistant.application.campaign_state_materialization import (
            CampaignStateStatus,
            inspect_campaign_state,
        )

        services = self._seed(tmp_path)
        services.vault.append_entity_fact(
            "npc-aria",
            expected_revision=1,
            fact="Aria gained a scar.",
            audit=make_audit_context(operation_id="mutate-aria", real_time=BASE_START),
        )
        assert (
            inspect_campaign_state(
                vault_repository=services.vault,
                session_repository=services.metadata,
                world_time_repository=services.world_time,
                derived_state_store=services.store,
                recent_session_limit=5,
            ).status
            is CampaignStateStatus.STALE
        )

    def test_unrelated_entity_change_remains_current(self, tmp_path: Path) -> None:
        from dnd_assistant.application.campaign_state_materialization import (
            CampaignStateStatus,
            inspect_campaign_state,
        )

        services = self._seed(tmp_path)
        services.vault.append_entity_fact(
            "npc-other",
            expected_revision=1,
            fact="Unrelated fact.",
            audit=make_audit_context(operation_id="mutate-other", real_time=BASE_START),
        )
        assert (
            inspect_campaign_state(
                vault_repository=services.vault,
                session_repository=services.metadata,
                world_time_repository=services.world_time,
                derived_state_store=services.store,
                recent_session_limit=5,
            ).status
            is CampaignStateStatus.CURRENT
        )

    def test_new_completed_session_changes_selection(self, tmp_path: Path) -> None:
        from dnd_assistant.application.campaign_state_materialization import (
            CampaignStateStatus,
            inspect_campaign_state,
        )

        services = self._seed(tmp_path)
        close_session(
            services,
            "S002",
            finish=BASE_START + timedelta(hours=5),
            touched=("npc-aria",),
        )
        assert (
            inspect_campaign_state(
                vault_repository=services.vault,
                session_repository=services.metadata,
                world_time_repository=services.world_time,
                derived_state_store=services.store,
                recent_session_limit=5,
            ).status
            is CampaignStateStatus.STALE
        )


# ── Repair / crash / mixed generation ─────────────────────────────────────


class TestRepairAndPartial:
    def test_tampered_artifact_is_corrupt_then_repaired(self, tmp_path: Path) -> None:
        from dnd_assistant.application.campaign_state_materialization import (
            CampaignStateStatus,
            inspect_campaign_state,
        )

        services = _services(tmp_path)
        create_entity(services, make_entity("npc-aria"))
        close_session(
            services, "S001", finish=BASE_START + timedelta(hours=1), touched=("npc-aria",)
        )
        rebuild(services)
        original = _text(services, _WORLD)

        (services.store.state_dir / ARTIFACT_FILENAMES[_WORLD]).write_text(
            "# tampered\n", encoding="utf-8"
        )
        assert (
            inspect_campaign_state(
                vault_repository=services.vault,
                session_repository=services.metadata,
                world_time_repository=services.world_time,
                derived_state_store=services.store,
                recent_session_limit=5,
            ).status
            is CampaignStateStatus.CORRUPT
        )
        rebuild(services)
        assert _text(services, _WORLD) == original

    def test_artifacts_without_manifest_never_current(self, tmp_path: Path) -> None:
        from dnd_assistant.application.campaign_state_materialization import (
            CampaignStateStatus,
            inspect_campaign_state,
        )

        services = _services(tmp_path)
        services.store.state_dir.mkdir()
        (services.store.state_dir / ARTIFACT_FILENAMES[_WORLD]).write_text(
            "# a\n", encoding="utf-8"
        )
        assert (
            inspect_campaign_state(
                vault_repository=services.vault,
                session_repository=services.metadata,
                world_time_repository=services.world_time,
                derived_state_store=services.store,
                recent_session_limit=5,
            ).status
            is CampaignStateStatus.CORRUPT
        )

    def test_mixed_generation_never_current(self, tmp_path: Path) -> None:
        from dnd_assistant.application.campaign_state_materialization import (
            CampaignStateStatus,
            inspect_campaign_state,
        )

        services = _services(tmp_path)
        create_entity(services, make_entity("npc-aria"))
        close_session(
            services, "S001", finish=BASE_START + timedelta(hours=1), touched=("npc-aria",)
        )
        rebuild(services)
        old_artifact = _text(services, _WORLD)

        services.world_time.set_current_world_time(
            500,
            expected_revision=1,
            audit=make_audit_context(operation_id="wt-set", real_time=BASE_START),
        )
        rebuild(services)
        # Simulate an interrupted publication: old artifact bytes + new manifest.
        (services.store.state_dir / ARTIFACT_FILENAMES[_WORLD]).write_text(
            old_artifact, encoding="utf-8"
        )
        assert (
            inspect_campaign_state(
                vault_repository=services.vault,
                session_repository=services.metadata,
                world_time_repository=services.world_time,
                derived_state_store=services.store,
                recent_session_limit=5,
            ).status
            is CampaignStateStatus.CORRUPT
        )


# ── Unrelated State preservation ──────────────────────────────────────────


class TestUnrelatedStatePreservation:
    def test_unrelated_state_note_survives_rebuild(self, tmp_path: Path) -> None:
        from dnd_assistant.application.campaign_state_materialization import (
            CampaignStateStatus,
            inspect_campaign_state,
        )

        services = _services(tmp_path)
        create_entity(services, make_entity("npc-aria"))
        close_session(
            services, "S001", finish=BASE_START + timedelta(hours=1), touched=("npc-aria",)
        )

        services.store.state_dir.mkdir()
        note = services.store.state_dir / "My Notes.md"
        note.write_text("player notes", encoding="utf-8")

        rebuild(services)
        assert note.read_text(encoding="utf-8") == "player notes"

        # Canonical source change forces a real re-publication of generation B.
        services.world_time.set_current_world_time(
            999,
            expected_revision=1,
            audit=make_audit_context(operation_id="wt-set", real_time=BASE_START),
        )
        rebuild(services)
        assert note.read_text(encoding="utf-8") == "player notes"

        assert (
            inspect_campaign_state(
                vault_repository=services.vault,
                session_repository=services.metadata,
                world_time_repository=services.world_time,
                derived_state_store=services.store,
                recent_session_limit=5,
            ).status
            is CampaignStateStatus.CURRENT
        )


# ── Calendar ──────────────────────────────────────────────────────────────


class TestCalendar:
    def _seed(self, tmp_path: Path) -> Services:
        services = _services(tmp_path, tick=0)
        return services

    def test_absent_calendar_is_current(self, tmp_path: Path) -> None:
        from dnd_assistant.application.campaign_state_materialization import (
            CampaignStateStatus,
            inspect_campaign_state,
        )

        services = self._seed(tmp_path)
        rebuild(services)
        assert (
            inspect_campaign_state(
                vault_repository=services.vault,
                session_repository=services.metadata,
                world_time_repository=services.world_time,
                derived_state_store=services.store,
                recent_session_limit=5,
            ).status
            is CampaignStateStatus.CURRENT
        )

    def test_supplied_calendar_round_trip_and_mismatch(self, tmp_path: Path) -> None:
        from dnd_assistant.application.campaign_state_materialization import (
            CampaignStateStatus,
            inspect_campaign_state,
        )

        services = self._seed(tmp_path)
        calendar = make_calendar()

        # A generation built without a calendar is stale when verified with one.
        rebuild(services)
        assert (
            inspect_campaign_state(
                vault_repository=services.vault,
                session_repository=services.metadata,
                world_time_repository=services.world_time,
                derived_state_store=services.store,
                recent_session_limit=5,
                calendar_definition=calendar,
            ).status
            is CampaignStateStatus.STALE
        )

        rebuild(services, calendar_definition=calendar)
        assert "Current game date" in _text(services, _WORLD)
        assert (
            inspect_campaign_state(
                vault_repository=services.vault,
                session_repository=services.metadata,
                world_time_repository=services.world_time,
                derived_state_store=services.store,
                recent_session_limit=5,
                calendar_definition=calendar,
            ).status
            is CampaignStateStatus.CURRENT
        )

        # Same calendar_id but different structure -> stale.
        different = make_calendar_with_intercalary()
        assert (
            inspect_campaign_state(
                vault_repository=services.vault,
                session_repository=services.metadata,
                world_time_repository=services.world_time,
                derived_state_store=services.store,
                recent_session_limit=5,
                calendar_definition=different,
            ).status
            is CampaignStateStatus.STALE
        )

    def test_intercalary_game_date_rendered(self, tmp_path: Path) -> None:
        services = _services(tmp_path, tick=14400)
        rebuild(services, calendar_definition=make_calendar_with_intercalary())
        assert "intercalary_day=Середина" in _text(services, _WORLD)


# ── Canonical read-only safety ────────────────────────────────────────────


class TestCanonicalSafety:
    def test_rebuild_changes_no_canonical_bytes_or_audit(self, tmp_path: Path) -> None:
        services = _services(tmp_path)
        create_entity(services, make_entity("npc-aria"))
        close_session(
            services, "S001", finish=BASE_START + timedelta(hours=1), touched=("npc-aria",)
        )

        before = snapshot(services.root)
        audit_before = services.audit.read_all()
        rebuild(services)
        after = snapshot(services.root)
        audit_after = services.audit.read_all()

        assert audit_after == audit_before
        for key, value in before.items():
            if key.startswith("State/"):
                continue
            assert after[key] == value
        new_keys = {k for k in after if k not in before}
        assert all(k.startswith("State/") for k in new_keys)
        assert json.loads(
            (services.store.state_dir / MANIFEST_FILENAME).read_text(encoding="utf-8")
        )

    def test_read_current_returns_typed_state(self, tmp_path: Path) -> None:
        from dnd_assistant.application.campaign_state_materialization import (
            read_current_campaign_state,
        )

        services = _services(tmp_path)
        create_entity(services, make_entity("npc-aria"))
        close_session(
            services, "S001", finish=BASE_START + timedelta(hours=1), touched=("npc-aria",)
        )
        rebuild(services)
        result = read_current_campaign_state(
            vault_repository=services.vault,
            session_repository=services.metadata,
            world_time_repository=services.world_time,
            derived_state_store=services.store,
            recent_session_limit=5,
        )
        assert tuple(r.entity_id for r in result.state.recently_touched) == ("npc-aria",)
