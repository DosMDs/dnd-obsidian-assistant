"""S12-03 Campaign State materialization test helpers.

Test-only helpers.  They deliberately avoid pytest so they can be imported by
both unit and integration test modules.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dnd_assistant.application.campaign_state_identity import (
    CAMPAIGN_STATE_DERIVATION_VERSION,
)
from dnd_assistant.application.campaign_state_source import CampaignStateBuildResult
from dnd_assistant.domain.calendar import CalendarDefinition, CalendarMonth, GameDate
from dnd_assistant.domain.campaign_state import (
    CampaignEntityReference,
    CampaignState,
    CampaignStateInputIdentity,
    CampaignWorldTimeSource,
)
from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import (
    EntityType,
    KnowledgeStatus,
    Sha256Fingerprint,
    Visibility,
)
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.derived_state import ObsidianDerivedStateStore
from dnd_assistant.storage.session_metadata import ObsidianSessionMetadataRepository
from dnd_assistant.storage.types import VaultDocument
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository
from dnd_assistant.storage.world_time import ObsidianWorldTimeRepository
from tests.unit.post_session.helpers import (
    BASE_END,
    BASE_START,
    make_audit_context,
    make_session,
    make_vault,
)

__all__ = [
    "BASE_END",
    "BASE_START",
    "ENTITY_DIRS",
    "Services",
    "close_session",
    "create_entity",
    "make_audit_context",
    "make_build_result",
    "make_calendar",
    "make_entity",
    "make_reference",
    "make_services",
    "make_session",
    "make_state",
    "make_vault",
    "rebuild",
    "setup_entity_dirs",
    "snapshot",
]

ENTITY_DIRS = ("Characters/NPCs", "Locations", "Quests", "Items")


def setup_entity_dirs(root: Path) -> None:
    for relative in ENTITY_DIRS:
        (root / relative).mkdir(parents=True, exist_ok=True)


def make_entity(
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


@dataclass
class Services:
    root: Path
    audit: AuditService
    vault: ObsidianVaultRepository
    metadata: ObsidianSessionMetadataRepository
    world_time: ObsidianWorldTimeRepository
    store: ObsidianDerivedStateStore


def make_services(root: Path) -> Services:
    audit = AuditService(root / "_system" / "audit" / "audit.jsonl")
    return Services(
        root=root,
        audit=audit,
        vault=ObsidianVaultRepository(root, audit),
        metadata=ObsidianSessionMetadataRepository(root, audit),
        world_time=ObsidianWorldTimeRepository(root, audit),
        store=ObsidianDerivedStateStore(root),
    )


def _audit(operation_id: str, when: datetime = BASE_START) -> AuditContext:
    return AuditContext(operation_id=operation_id, real_time=when, source="test")


def create_entity(
    services: Services,
    entity: Entity,
    *,
    body: str = "",
    op_id: str | None = None,
) -> None:
    services.vault.create_entity(
        VaultDocument(entity=entity, body=body),
        audit=_audit(op_id or f"create-{entity.id}"),
    )


def close_session(
    services: Services,
    session_id: str,
    *,
    finish: datetime,
    world_tick_end: int = 200,
    touched: tuple[str, ...] = (),
) -> None:
    services.metadata.create_session(
        make_session(session_id=session_id, status="active"),
        audit=make_audit_context(operation_id=f"{session_id}-start", real_time=BASE_START),
    )
    services.metadata.close_session(
        session_id,
        expected_revision=1,
        world_tick_end=world_tick_end,
        touched_entity_ids=list(touched),
        audit=make_audit_context(operation_id=f"{session_id}-end", real_time=finish),
    )


def make_calendar(calendar_id: str = "forgotten_realms") -> CalendarDefinition:
    return CalendarDefinition(
        calendar_id=calendar_id,
        epoch=GameDate(year=1490, month="Hammer", day=1),
        months=(
            CalendarMonth(name="Hammer", days=30),
            CalendarMonth(name="Alturiak", days=30),
        ),
    )


def make_calendar_with_intercalary() -> CalendarDefinition:
    from dnd_assistant.domain.calendar import IntercalaryDay

    return CalendarDefinition(
        calendar_id="custom",
        epoch=GameDate(year=1, month="Первый Туман", day=1),
        months=(CalendarMonth(name="Первый Туман", days=10),),
        intercalary_days=(IntercalaryDay(name="Середина", after_month="Первый Туман"),),
    )


def rebuild(
    services: Services,
    *,
    recent_session_limit: int = 5,
    calendar_definition: CalendarDefinition | None = None,
):
    from dnd_assistant.application.campaign_state_materialization import (
        rebuild_campaign_state,
    )

    return rebuild_campaign_state(
        vault_repository=services.vault,
        session_repository=services.metadata,
        world_time_repository=services.world_time,
        derived_state_store=services.store,
        recent_session_limit=recent_session_limit,
        calendar_definition=calendar_definition,
    )


def snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result[str(path.relative_to(root).as_posix())] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return result


# ── Controlled-state builders (unit tests) ────────────────────────────────


def make_reference(
    entity_id: str,
    *,
    entity_type: EntityType = EntityType.NPC,
    name: str = "Aria",
    visibility: Visibility = Visibility.PLAYER,
    revision: int = 1,
    source_session_ids: tuple[str, ...] = ("S001",),
) -> CampaignEntityReference:
    return CampaignEntityReference(
        entity_id=entity_id,
        entity_type=entity_type,
        name=name,
        visibility=visibility,
        revision=revision,
        source_session_ids=source_session_ids,
    )


def make_state(
    fingerprint_hex: str,
    *,
    tick: int = 100,
    game_date: GameDate | None = None,
    references: tuple[CampaignEntityReference, ...] = (),
) -> CampaignState:
    return CampaignState(
        input_fingerprint=Sha256Fingerprint(digest=fingerprint_hex),
        current_world_tick=tick,
        current_game_date=game_date,
        recently_touched=references,
    )


def make_build_result(
    fingerprint_hex: str,
    *,
    tick: int = 100,
    game_date: GameDate | None = None,
    references: tuple[CampaignEntityReference, ...] = (),
    limit: int = 5,
) -> CampaignStateBuildResult:
    identity = CampaignStateInputIdentity(
        derivation_version=CAMPAIGN_STATE_DERIVATION_VERSION,
        recent_session_limit=limit,
        world_time=CampaignWorldTimeSource(current_world_tick=tick, revision=1),
    )
    state = make_state(fingerprint_hex, tick=tick, game_date=game_date, references=references)
    return CampaignStateBuildResult(state=state, identity=identity)
