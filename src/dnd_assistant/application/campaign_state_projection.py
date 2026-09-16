"""S12-04 explicit player-safe Campaign State projection.

Produces a deterministic, player-safe view of the trusted internal
``CampaignState``.  The internal S12-02 projection is deliberately
**all-visibility**; this module is the single reusable boundary that admits
only ``Visibility.PLAYER`` references and copies only the minimum
player-facing fields (stable id, entity type, display name).

The projection is pure, model-free and side-effect-free: it never mutates the
input ``CampaignState`` and never performs I/O.  It also defines the narrow
``PlayerCampaignStateProvider`` capability consumed by
``AgentContextBuilder`` so the context builder never receives repositories,
materialization services or a derived-state store.

This module belongs to the application layer and must not import from:
    storage, models, ollama, pydantic_ai, tools, cli, retrieval, pathlib, os,
    hashlib, json
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from dnd_assistant.domain.campaign_state import CampaignState
from dnd_assistant.domain.types import EntityId, EntityType, Visibility

# ── Player-safe projection DTOs ───────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PlayerCampaignEntityReference:
    """One player-visible recently-touched entity reference.

    Carries only the player-safe minimum: the exact stable id, the entity type
    and the display name.  Internal visibility, revision, provenance session
    ids and the projection fingerprint are intentionally absent.
    """

    entity_id: EntityId
    entity_type: EntityType
    name: str


@dataclass(frozen=True, slots=True)
class PlayerCampaignState:
    """Complete player-safe Campaign State projection.

    ``recently_touched`` contains only ``Visibility.PLAYER`` references in
    deterministic canonical order (``entity_id`` ascending).  It is not
    bounded here: bounding/compactness is an explicit Fast-Agent consumer
    policy (see ``agent_context``).
    """

    recently_touched: tuple[PlayerCampaignEntityReference, ...]


# ── Provider capability ────────────────────────────────────────────────────


@runtime_checkable
class PlayerCampaignStateProvider(Protocol):
    """Trusted capability returning the current player-safe Campaign State.

    Implementations compose the S12-03 rebuild/read service, trusted
    repositories, a derived-state store and the player projection.  Consumers
    only see ``PlayerCampaignState | None``: ``None`` means Campaign State is
    unavailable for this turn (graceful omission).
    """

    def get_player_campaign_state(self) -> PlayerCampaignState | None:
        """Return the player-safe Campaign State, or ``None`` when unavailable."""
        ...


# ── Projection ─────────────────────────────────────────────────────────────


def project_player_campaign_state(state: CampaignState) -> PlayerCampaignState:
    """Project a trusted internal ``CampaignState`` to its player-safe view.

    Deterministic and pure.  Only PLAYER references are admitted; the result is
    sorted by ``entity_id`` ascending so caller-independent ordering never
    leaks into the consumer.  The internal ``CampaignState`` is never mutated
    and no internal reference object is exposed.
    """
    player_refs = [ref for ref in state.recently_touched if ref.visibility is Visibility.PLAYER]
    player_refs.sort(key=lambda ref: ref.entity_id)
    return PlayerCampaignState(
        recently_touched=tuple(
            PlayerCampaignEntityReference(
                entity_id=ref.entity_id,
                entity_type=ref.entity_type,
                name=ref.name,
            )
            for ref in player_refs
        ),
    )


__all__ = [
    "PlayerCampaignEntityReference",
    "PlayerCampaignState",
    "PlayerCampaignStateProvider",
    "project_player_campaign_state",
]
