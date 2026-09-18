"""S13-03 trusted deterministic bootstrap EntityId allocation.

New campaign entities proposed from untrusted bootstrap extraction must receive
a Python-owned canonical ``EntityId``.  The model never supplies a stable
identity, and identity must not depend on model-selected evidence references or
candidate ordinals.

The allocation material is deliberately bounded to trusted bootstrap/campaign
semantics:

    allocator_version
    campaign_id
    entity_type.value
    normalize_exact_text(display_name)

It is canonicalized as compact, key-sorted UTF-8 JSON and hashed with SHA-256;
the resulting ``EntityId`` is the bounded opaque value ``ent_<32 lowercase hex>``.

Properties:

- Python-owned and model-independent;
- filesystem-independent and pure (no I/O, no randomness, no wall clock);
- retry-stable: the same semantic candidate over the same campaign yields the
  same EntityId across attempts, regardless of the evidence references the
  model happened to select;
- collision-aware: two distinct candidate records that produce the same
  allocation identity are a caller-visible collision, never resolved by adding
  randomness;
- ``entity_type`` participates in the material, so a cross-type same-name
  allocation is hash-distinct by construction.  The authorization to emit both
  creates is a separate conservative application decision.

This module belongs to the application layer and must not import from:
    storage, models, ollama, pydantic_ai, tools, cli
``hashlib`` and ``json`` are intentional application concerns here (trusted
identity allocation), consistent with the S11-05/S10-03 hashing precedent.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from pydantic import TypeAdapter

from dnd_assistant.domain.types import EntityId, EntityType
from dnd_assistant.errors import ValidationError
from dnd_assistant.retrieval.exact_matching import normalize_exact_text

BOOTSTRAP_ENTITY_ID_ALLOCATOR_VERSION: Final[str] = "bootstrap-entity-id-v1"
"""Explicit allocator contract version.

Bump whenever allocation material or serialization semantics change so a
changed identity cannot silently reuse an old EntityId.
"""

_ENTITY_ID_PREFIX: Final[str] = "ent_"
_ENTITY_ID_HEX_CHARS: Final[int] = 32

_ENTITY_ID_ADAPTER: TypeAdapter[EntityId] = TypeAdapter(EntityId)


def bootstrap_identity_material(
    campaign_id: str,
    entity_type: EntityType,
    display_name: str,
) -> dict[str, str]:
    """Return the canonical bootstrap allocation-material mapping."""
    return {
        "allocator_version": BOOTSTRAP_ENTITY_ID_ALLOCATOR_VERSION,
        "campaign_id": campaign_id,
        "entity_type": entity_type.value,
        "name": normalize_exact_text(display_name),
    }


def canonical_bootstrap_identity_bytes(
    campaign_id: str,
    entity_type: EntityType,
    display_name: str,
) -> bytes:
    """Serialize the allocation material to deterministic UTF-8 bytes.

    Determinism guarantees: sorted keys, compact separators, ``ensure_ascii``
    disabled and ``allow_nan=False``.  Non-serializable input fails closed.
    """
    material = bootstrap_identity_material(campaign_id, entity_type, display_name)
    try:
        text = json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "Bootstrap identity material is not canonically serializable",
            cause=exc,
        ) from exc
    return text.encode("utf-8")


def allocate_bootstrap_entity_id(
    campaign_id: str,
    entity_type: EntityType,
    display_name: str,
) -> EntityId:
    """Allocate the deterministic canonical ``EntityId`` for a candidate.

    The result is ``ent_`` plus the first 32 lowercase hex characters of the
    SHA-256 digest of the canonical bootstrap identity material.
    """
    digest = hashlib.sha256(
        canonical_bootstrap_identity_bytes(campaign_id, entity_type, display_name)
    ).hexdigest()
    return _ENTITY_ID_ADAPTER.validate_python(f"{_ENTITY_ID_PREFIX}{digest[:_ENTITY_ID_HEX_CHARS]}")


__all__ = [
    "BOOTSTRAP_ENTITY_ID_ALLOCATOR_VERSION",
    "allocate_bootstrap_entity_id",
    "bootstrap_identity_material",
    "canonical_bootstrap_identity_bytes",
]
