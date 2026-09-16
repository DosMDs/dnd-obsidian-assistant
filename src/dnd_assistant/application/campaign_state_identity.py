"""S12-01 Campaign State source-snapshot identity and canonical fingerprint.

Owns deterministic canonical serialization and SHA-256 fingerprinting for the
Stage-12 Campaign State projection:

- ``canonical_campaign_state_input_bytes`` / ``compute_input_fingerprint`` —
  the exact canonical bytes and source-snapshot identity of a
  ``CampaignStateInputIdentity``;
- ``canonical_calendar_definition_bytes`` /
  ``compute_calendar_definition_fingerprint`` — the exact supplied
  ``CalendarDefinition`` identity, so two definitions sharing a ``calendar_id``
  but differing in structure cannot produce the same fingerprint.

Canonical serialization rules are project-consistent with the Stage-10/11
fingerprint contracts but implemented independently: Campaign State identity
must not couple to ChangeSet review or post-session processing policy merely to
reuse a few lines of serialization.

This module belongs to the application layer and must not import from:
    storage, models, ollama, pydantic_ai, tools, cli, retrieval, pathlib, os
``hashlib`` and ``json`` are intentional application concerns here.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from dnd_assistant.domain.calendar import CalendarDefinition
from dnd_assistant.domain.campaign_state import CampaignStateInputIdentity
from dnd_assistant.domain.types import Sha256Fingerprint
from dnd_assistant.errors import ValidationError

# ── Version constant ──────────────────────────────────────────────────────

CAMPAIGN_STATE_DERIVATION_VERSION: Final[str] = "1"
"""Deterministic derivation/serialization contract version.

Bump whenever the projection's selection or serialization semantics change so
that a changed input cannot silently reuse an old fingerprint.
"""

# ── Canonical serialization ───────────────────────────────────────────────


def _canonical_json_bytes(payload: object, *, label: str) -> bytes:
    """Serialize a JSON-compatible payload to deterministic UTF-8 bytes.

    Determinism guarantees:

    - tuple/list component order is preserved (canonical ordering is the
      caller's/DTO's responsibility);
    - JSON object keys are sorted, so mapping insertion order is irrelevant;
    - compact separators make the result independent of pretty-printing;
    - Unicode is preserved and encoded as UTF-8 with no normalization;
    - ``allow_nan=False`` forbids NaN/Infinity.
    """
    try:
        text = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} is not canonically serializable", cause=exc) from exc
    return text.encode("utf-8")


def canonical_campaign_state_input_bytes(identity: CampaignStateInputIdentity) -> bytes:
    """Serialize a ``CampaignStateInputIdentity`` to deterministic UTF-8 bytes.

    The serialized content is exactly the source-snapshot identity: derivation
    version, world-time source, session sources, entity references and the
    supplied calendar-definition fingerprint.  It contains no wall-clock time,
    attempt id, model metadata or filesystem data.
    """
    payload = identity.model_dump(mode="json", exclude_unset=False)
    return _canonical_json_bytes(payload, label="Campaign State input identity")


def compute_input_fingerprint(identity: CampaignStateInputIdentity) -> Sha256Fingerprint:
    """Compute the lowercase-hex SHA-256 fingerprint of the Campaign State input."""
    digest = hashlib.sha256(canonical_campaign_state_input_bytes(identity)).hexdigest()
    return Sha256Fingerprint(digest=digest)


def canonical_calendar_definition_bytes(definition: CalendarDefinition) -> bytes:
    """Serialize a complete ``CalendarDefinition`` to deterministic UTF-8 bytes.

    The full validated definition is serialized (months, intercalary days,
    holidays, epoch, hours/minutes), so definition identity never reduces to
    ``calendar_id`` alone.
    """
    payload = definition.model_dump(mode="json", exclude_unset=False)
    return _canonical_json_bytes(payload, label="CalendarDefinition")


def compute_calendar_definition_fingerprint(
    definition: CalendarDefinition,
) -> Sha256Fingerprint:
    """Compute the SHA-256 identity of a complete supplied ``CalendarDefinition``."""
    digest = hashlib.sha256(canonical_calendar_definition_bytes(definition)).hexdigest()
    return Sha256Fingerprint(digest=digest)


__all__ = [
    "CAMPAIGN_STATE_DERIVATION_VERSION",
    "canonical_calendar_definition_bytes",
    "canonical_campaign_state_input_bytes",
    "compute_calendar_definition_fingerprint",
    "compute_input_fingerprint",
]
