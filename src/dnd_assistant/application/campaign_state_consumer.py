"""S12-04 Fast-Agent Campaign State consumer (lazy ensure-current provider).

Concrete ``PlayerCampaignStateProvider`` used by the production ``dnd ask``
composition.  It composes the accepted S12-03 materialization service, the
trusted repositories and a derived-state store into a single capability:

```text
rebuild_campaign_state            (lazy ensure-current; PUBLISHED | ALREADY_CURRENT)
  -> trusted typed CampaignState
  -> project_player_campaign_state (player-safe, minimal)
  -> PlayerCampaignState
```

Lazy materialization is trusted, non-canonical derived-cache maintenance.  A
READ-only ``dnd ask`` may create/repair managed ``State/*`` files, but no
canonical entity/session/world-time data and no canonical audit record is
written, and model/tool WRITE authorization is unaffected.

Failure policy (deliberately narrow):

```text
CampaignStateSourceReason.WORLD_TIME_UNAVAILABLE   -> None (graceful omission)
CampaignStateSourceChangedError                    -> None (pre-publication race)
any other CampaignStateSourceError                 -> propagate (fail closed)
StorageError                                       -> propagate (fail closed)
```

Only expected unavailability is normalized to ``None``.  Corrupt/malformed
canonical evidence, an invalid selection limit/calendar and unsafe derived
topology are never silently hidden from the caller.  There is no retry loop.

This module belongs to the application layer and must not import concrete
storage implementations at runtime (storage protocols are referenced only
under ``TYPE_CHECKING``).  It imports no provider/model/framework module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dnd_assistant.application.campaign_state_materialization import (
    CampaignStateSourceChangedError,
    rebuild_campaign_state,
)
from dnd_assistant.application.campaign_state_projection import (
    PlayerCampaignState,
    project_player_campaign_state,
)
from dnd_assistant.application.campaign_state_source import (
    CampaignStateSourceError,
    CampaignStateSourceReason,
)

if TYPE_CHECKING:
    from dnd_assistant.domain.calendar import CalendarDefinition
    from dnd_assistant.storage.derived_state import DerivedStateStore
    from dnd_assistant.storage.types import (
        SessionMetadataRepository,
        VaultRepository,
        WorldTimeRepository,
    )

# ── Production Fast-Agent policy ──────────────────────────────────────────
#
# S12-02 deliberately exposes no hidden default for ``recent_session_limit``:
# the selection limit is a semantic derivation input bound into the source
# fingerprint.  S12-04 owns exactly one explicit production policy value for
# the Fast-Agent consumer.  This is a policy constant, not a magic literal:
# composition passes it explicitly and tests assert it is bound into the
# rebuild request.

FAST_AGENT_RECENT_SESSION_LIMIT: Final[int] = 5
"""Recent-session selection limit owned by the Fast-Agent composition."""

_GRACEFUL_SOURCE_REASONS: Final[frozenset[CampaignStateSourceReason]] = frozenset(
    {CampaignStateSourceReason.WORLD_TIME_UNAVAILABLE}
)
"""Source-collection reasons that degrade to unavailable memory.

Every other ``CampaignStateSourceReason`` is an unclassifiable/invalid source
condition and must propagate rather than silently disappear.
"""


# ── Provider ───────────────────────────────────────────────────────────────


class RebuildPlayerCampaignStateProvider:
    """Lazy ensure-current player-safe Campaign State provider.

    Args:
        vault_repository: Trusted all-visibility entity read boundary.
        session_repository: Completed-session metadata read boundary.
        world_time_repository: Canonical current-world-time read boundary.
        derived_state_store: Trusted derived-state persistence boundary.
        recent_session_limit: Explicit, application-owned selection limit.
        calendar_definition: Optional calendar definition.  S12-04 production
            uses ``None`` (no canonical definition source exists), so no
            ``GameDate`` is ever fabricated.

    The model/runtime never receives this object or its dependencies.
    """

    def __init__(
        self,
        *,
        vault_repository: VaultRepository,
        session_repository: SessionMetadataRepository,
        world_time_repository: WorldTimeRepository,
        derived_state_store: DerivedStateStore,
        recent_session_limit: int,
        calendar_definition: CalendarDefinition | None = None,
    ) -> None:
        self._vault_repository = vault_repository
        self._session_repository = session_repository
        self._world_time_repository = world_time_repository
        self._derived_state_store = derived_state_store
        self._recent_session_limit = recent_session_limit
        self._calendar_definition = calendar_definition

    def get_player_campaign_state(self) -> PlayerCampaignState | None:
        """Return the player-safe Campaign State, or ``None`` when unavailable.

        Lazily rebuilds/repairs the materialized generation, then projects the
        verified typed state.  Returns ``None`` only for expected unavailability
        (no canonical world time) or a pre-publication source race; other
        bounded source failures and all storage failures propagate.
        """
        try:
            result = rebuild_campaign_state(
                vault_repository=self._vault_repository,
                session_repository=self._session_repository,
                world_time_repository=self._world_time_repository,
                derived_state_store=self._derived_state_store,
                recent_session_limit=self._recent_session_limit,
                calendar_definition=self._calendar_definition,
            )
        except CampaignStateSourceChangedError:
            return None
        except CampaignStateSourceError as exc:
            if exc.reason in _GRACEFUL_SOURCE_REASONS:
                return None
            raise
        return project_player_campaign_state(result.state)


__all__ = [
    "FAST_AGENT_RECENT_SESSION_LIMIT",
    "RebuildPlayerCampaignStateProvider",
]
