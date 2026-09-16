"""S12-02 Campaign State source collection integration tests.

Exercises a real temporary Vault with the real metadata/Vault/world-time
repositories: completed sessions + canonical entities + world time -> a
deterministic ``CampaignState`` + source-snapshot fingerprint, then proves
selection, fingerprint sensitivity, byte-for-byte read-only behaviour and
DM/SYSTEM internal admission.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from pathlib import Path

from dnd_assistant.application.campaign_state_source import build_campaign_state
from dnd_assistant.domain.calendar import CalendarDefinition, CalendarMonth, GameDate
from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityType, KnowledgeStatus, Visibility
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_metadata import ObsidianSessionMetadataRepository
from dnd_assistant.storage.types import VaultDocument
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository
from dnd_assistant.storage.world_time import ObsidianWorldTimeRepository
from tests.unit.post_session.helpers import (
    BASE_START,
    make_audit_context,
    make_session,
    make_vault,
)

_ENTITY_DIRS = ("Characters/NPCs", "Locations", "Quests", "Items")


# ── Setup helpers ─────────────────────────────────────────────────────────


def _setup_vault(root: Path) -> None:
    for relative in _ENTITY_DIRS:
        (root / relative).mkdir(parents=True, exist_ok=True)


def _entity(
    entity_id: str,
    *,
    name: str = "Aria",
    entity_type: EntityType = EntityType.NPC,
    visibility: Visibility = Visibility.PLAYER,
    revision: int = 1,
) -> Entity:
    return Entity(
        id=entity_id,
        type=entity_type,
        name=name,
        status="alive",
        visibility=visibility,
        knowledge_status=KnowledgeStatus.CONFIRMED,
        created_at=BASE_START,
        updated_at=BASE_START,
        revision=revision,
    )


def _audit(op_id: str, when: datetime = BASE_START) -> AuditContext:
    return AuditContext(operation_id=op_id, real_time=when, source="test")


def _create_entity(
    vault: ObsidianVaultRepository,
    entity: Entity,
    *,
    body: str = "",
    op_id: str,
) -> None:
    vault.create_entity(VaultDocument(entity=entity, body=body), audit=_audit(op_id))


def _services(
    root: Path,
) -> tuple[
    AuditService,
    ObsidianVaultRepository,
    ObsidianSessionMetadataRepository,
    ObsidianWorldTimeRepository,
]:
    audit = AuditService(root / "_system" / "audit" / "audit.jsonl")
    return (
        audit,
        ObsidianVaultRepository(root, audit),
        ObsidianSessionMetadataRepository(root, audit),
        ObsidianWorldTimeRepository(root, audit),
    )


def _close(
    metadata_repo: ObsidianSessionMetadataRepository,
    session_id: str,
    *,
    finish: datetime,
    world_tick_end: int = 200,
    touched: tuple[str, ...] = (),
) -> None:
    metadata_repo.create_session(
        make_session(session_id=session_id, status="active"),
        audit=make_audit_context(operation_id=f"{session_id}-start", real_time=BASE_START),
    )
    metadata_repo.close_session(
        session_id,
        expected_revision=1,
        world_tick_end=world_tick_end,
        touched_entity_ids=list(touched),
        audit=make_audit_context(operation_id=f"{session_id}-end", real_time=finish),
    )


def _calendar() -> CalendarDefinition:
    return CalendarDefinition(
        calendar_id="forgotten_realms",
        epoch=GameDate(year=1490, month="Hammer", day=1),
        months=(
            CalendarMonth(name="Hammer", days=30),
            CalendarMonth(name="Alturiak", days=30),
        ),
    )


def _snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result[str(path.relative_to(root).as_posix())] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return result


# ── Tests ─────────────────────────────────────────────────────────────────


def test_completed_sessions_assemble_deterministic_state(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    _setup_vault(root)
    audit, vault, metadata_repo, world_time = _services(root)
    world_time.initialize_current_world_time(150, audit=_audit("wt-init"))

    _create_entity(vault, _entity("npc-aria"), body="A ranger.", op_id="c-aria")
    _create_entity(vault, _entity("npc-other"), body="Unrelated.", op_id="c-other")
    _close(metadata_repo, "S001", finish=BASE_START + timedelta(hours=1), touched=("npc-aria",))
    _close(metadata_repo, "S002", finish=BASE_START + timedelta(hours=2), touched=("npc-aria",))

    def _build():
        return build_campaign_state(
            vault_repository=ObsidianVaultRepository(root, audit),
            session_repository=ObsidianSessionMetadataRepository(root, audit),
            world_time_repository=ObsidianWorldTimeRepository(root, audit),
            recent_session_limit=1,
        )

    result = _build()
    assert tuple(s.session_id for s in result.identity.sessions) == ("S002",)
    assert result.state.current_world_tick == 150
    assert tuple(r.entity_id for r in result.state.recently_touched) == ("npc-aria",)
    assert result.state.recently_touched[0].source_session_ids == ("S002",)

    fresh = _build()
    assert fresh.identity == result.identity
    assert fresh.state.input_fingerprint == result.state.input_fingerprint


def test_selection_limit_is_bound_into_identity(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    _setup_vault(root)
    audit, vault, metadata_repo, world_time = _services(root)
    world_time.initialize_current_world_time(150, audit=_audit("wt-init"))
    _create_entity(vault, _entity("npc-aria"), op_id="c-aria")
    _close(metadata_repo, "S001", finish=BASE_START + timedelta(hours=1), touched=("npc-aria",))

    one = build_campaign_state(
        vault_repository=ObsidianVaultRepository(root, audit),
        session_repository=ObsidianSessionMetadataRepository(root, audit),
        world_time_repository=ObsidianWorldTimeRepository(root, audit),
        recent_session_limit=1,
    )
    two = build_campaign_state(
        vault_repository=ObsidianVaultRepository(root, audit),
        session_repository=ObsidianSessionMetadataRepository(root, audit),
        world_time_repository=ObsidianWorldTimeRepository(root, audit),
        recent_session_limit=2,
    )
    assert one.identity.sessions == two.identity.sessions
    assert one.state.input_fingerprint != two.state.input_fingerprint


def test_selected_entity_mutation_changes_fingerprint(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    _setup_vault(root)
    audit, vault, metadata_repo, world_time = _services(root)
    world_time.initialize_current_world_time(150, audit=_audit("wt-init"))
    _create_entity(vault, _entity("npc-aria"), op_id="c-aria")
    _close(metadata_repo, "S001", finish=BASE_START + timedelta(hours=1), touched=("npc-aria",))

    def _build():
        return build_campaign_state(
            vault_repository=ObsidianVaultRepository(root, audit),
            session_repository=ObsidianSessionMetadataRepository(root, audit),
            world_time_repository=ObsidianWorldTimeRepository(root, audit),
            recent_session_limit=5,
        )

    before = _build()
    ObsidianVaultRepository(root, audit).append_entity_fact(
        "npc-aria",
        expected_revision=1,
        fact="Aria gained a scar.",
        audit=_audit("mutate-aria", when=BASE_START + timedelta(hours=3)),
    )
    after = _build()
    assert after.state.input_fingerprint != before.state.input_fingerprint


def test_all_visibilities_admitted_internally(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    _setup_vault(root)
    audit, vault, metadata_repo, world_time = _services(root)
    world_time.initialize_current_world_time(150, audit=_audit("wt-init"))
    _create_entity(vault, _entity("npc-dm", visibility=Visibility.DM), op_id="c-dm")
    _create_entity(vault, _entity("npc-sys", visibility=Visibility.SYSTEM), op_id="c-sys")
    _close(
        metadata_repo,
        "S001",
        finish=BASE_START + timedelta(hours=1),
        touched=("npc-dm", "npc-sys"),
    )
    result = build_campaign_state(
        vault_repository=ObsidianVaultRepository(root, audit),
        session_repository=ObsidianSessionMetadataRepository(root, audit),
        world_time_repository=ObsidianWorldTimeRepository(root, audit),
        recent_session_limit=5,
    )
    assert {r.visibility for r in result.state.recently_touched} == {
        Visibility.DM,
        Visibility.SYSTEM,
    }


def test_unicode_entity_name_preserved(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    _setup_vault(root)
    audit, vault, metadata_repo, world_time = _services(root)
    world_time.initialize_current_world_time(150, audit=_audit("wt-init"))
    _create_entity(vault, _entity("npc-varos", name="Магистр Варос"), op_id="c-varos")
    _close(metadata_repo, "S001", finish=BASE_START + timedelta(hours=1), touched=("npc-varos",))
    result = build_campaign_state(
        vault_repository=ObsidianVaultRepository(root, audit),
        session_repository=ObsidianSessionMetadataRepository(root, audit),
        world_time_repository=ObsidianWorldTimeRepository(root, audit),
        recent_session_limit=5,
    )
    assert result.state.recently_touched[0].name == "Магистр Варос"


def test_supplied_calendar_derives_game_date(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    _setup_vault(root)
    audit, vault, metadata_repo, world_time = _services(root)
    world_time.initialize_current_world_time(0, audit=_audit("wt-init"))
    result = build_campaign_state(
        vault_repository=ObsidianVaultRepository(root, audit),
        session_repository=ObsidianSessionMetadataRepository(root, audit),
        world_time_repository=ObsidianWorldTimeRepository(root, audit),
        recent_session_limit=5,
        calendar_definition=_calendar(),
    )
    assert result.identity.calendar_definition_fingerprint is not None
    assert result.state.current_game_date == GameDate(year=1490, month="Hammer", day=1)


def test_build_leaves_vault_bytes_unchanged(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    _setup_vault(root)
    audit, vault, metadata_repo, world_time = _services(root)
    world_time.initialize_current_world_time(150, audit=_audit("wt-init"))
    _create_entity(vault, _entity("npc-aria"), op_id="c-aria")
    _close(metadata_repo, "S001", finish=BASE_START + timedelta(hours=1), touched=("npc-aria",))

    before = _snapshot(root)
    audit_before = audit.read_all()
    build_campaign_state(
        vault_repository=ObsidianVaultRepository(root, audit),
        session_repository=ObsidianSessionMetadataRepository(root, audit),
        world_time_repository=ObsidianWorldTimeRepository(root, audit),
        recent_session_limit=5,
    )
    assert _snapshot(root) == before
    assert audit.read_all() == audit_before
