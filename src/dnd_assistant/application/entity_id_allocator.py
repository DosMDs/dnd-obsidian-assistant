"""S11-05 trusted deterministic candidate EntityId allocation.

New campaign entities proposed from an untrusted ``ExtractedEntityCandidate``
must receive a Python-owned canonical ``EntityId``.  The model never supplies a
stable identity, and identity must not depend on model-selected evidence
references or candidate ordinals.

The allocation material is deliberately bounded to trusted
session/candidate semantics:

    allocator_version
    session_ref
    entity_type.value
    normalize_exact_text(display_name)

It is canonicalized as compact, key-sorted UTF-8 JSON and hashed with SHA-256;
the resulting ``EntityId`` is the bounded opaque value ``ent_<32 lowercase
hex>``.

Properties:

- Python-owned and model-independent;
- filesystem-independent and pure (no I/O, no randomness, no wall clock);
- retry-stable: the same semantic candidate over the same session yields the
  same EntityId across attempts, regardless of the evidence references the
  model happened to select;
- collision-aware: two distinct candidate records that produce the same
  allocation identity are a caller-visible collision, never resolved by adding
  randomness.

This module belongs to the application layer and must not import from:
    storage, models, ollama, pydantic_ai, tools, cli
``hashlib`` and ``json`` are intentional application concerns here (trusted
identity allocation), consistent with the S11-01/S10-03 hashing precedent.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from pydantic import TypeAdapter

from dnd_assistant.domain.types import EntityId, EntityType
from dnd_assistant.errors import ValidationError
from dnd_assistant.retrieval.exact_matching import normalize_exact_text

CANDIDATE_ENTITY_ID_ALLOCATOR_VERSION: Final[str] = "post-session-entity-id-v1"
"""Explicit allocator contract version.

Bump whenever allocation material or serialization semantics change so a
changed identity cannot silently reuse an old EntityId.
"""

_ENTITY_ID_PREFIX: Final[str] = "ent_"
_ENTITY_ID_HEX_CHARS: Final[int] = 32

_ENTITY_ID_ADAPTER: TypeAdapter[EntityId] = TypeAdapter(EntityId)


def candidate_identity_material(
    session_ref: str,
    entity_type: EntityType,
    display_name: str,
) -> dict[str, str]:
    """Return the canonical allocation-material mapping.

    Only trusted session/type/name semantics participate.  Evidence event ids
    and model ``candidate_id`` values are deliberately excluded so that a
    different valid evidence selection cannot change canonical identity.
    """
    return {
        "allocator_version": CANDIDATE_ENTITY_ID_ALLOCATOR_VERSION,
        "session_ref": session_ref,
        "entity_type": entity_type.value,
        "name": normalize_exact_text(display_name),
    }


def canonical_candidate_identity_bytes(
    session_ref: str,
    entity_type: EntityType,
    display_name: str,
) -> bytes:
    """Serialize the allocation material to deterministic UTF-8 bytes.

    Determinism guarantees: sorted keys, compact separators, ``ensure_ascii``
    disabled and ``allow_nan=False``.  Non-serializable input fails closed.
    """
    material = candidate_identity_material(session_ref, entity_type, display_name)
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
            "Candidate identity material is not canonically serializable",
            cause=exc,
        ) from exc
    return text.encode("utf-8")


def allocate_candidate_entity_id(
    session_ref: str,
    entity_type: EntityType,
    display_name: str,
) -> EntityId:
    """Allocate the deterministic canonical ``EntityId`` for a candidate.

    The result is ``ent_`` plus the first 32 lowercase hex characters of the
    SHA-256 digest of the canonical identity material.
    """
    digest = hashlib.sha256(
        canonical_candidate_identity_bytes(session_ref, entity_type, display_name)
    ).hexdigest()
    return _ENTITY_ID_ADAPTER.validate_python(f"{_ENTITY_ID_PREFIX}{digest[:_ENTITY_ID_HEX_CHARS]}")


__all__ = [
    "CANDIDATE_ENTITY_ID_ALLOCATOR_VERSION",
    "allocate_candidate_entity_id",
    "candidate_identity_material",
    "canonical_candidate_identity_bytes",
]
