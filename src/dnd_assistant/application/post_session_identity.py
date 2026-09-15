"""S11-01 trusted processing identity: attempt ids and prepared-input fingerprint.

Owns two distinct identities (architecture correction C2):

- ``new_attempt_id`` — trusted Python generation of one execution-attempt
  identity.  It is deliberately opaque, random and never derived from the
  prepared input, so multiple attempts may share one ``input_fingerprint``.
- ``compute_input_fingerprint`` — canonical serialization and SHA-256 of the
  full prepared-input identity (C1).

Canonical serialization rules are intentionally project-consistent with the
Stage-10 ChangeSet contract but implemented independently here: post-session
processing must not couple to ChangeSet review policy merely to reuse a few
lines of serialization.

This module belongs to the application layer and must not import from:
    storage, models, ollama, pydantic_ai, tools, cli, retrieval
``hashlib``, ``json`` and ``uuid`` are intentional application concerns here:
canonical hashing and trusted identity generation are owned by S11-01.
"""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from dnd_assistant.domain.post_session import (
    PreparedInputIdentity,
    Sha256Fingerprint,
)
from dnd_assistant.errors import ValidationError

# ── Version constants ─────────────────────────────────────────────────────

POST_SESSION_PROCESSOR_VERSION = "2"
"""Deterministic processor/assembler version included in the fingerprint.

This is an explicit contract constant, never an implicit package version.
Bump it whenever prepared-input assembly semantics change so that a changed
input cannot silently reuse an old fingerprint.

Version history:
    1 — S11-01 foundational prepared-input identity.
    2 — S11-02 deterministic context assembler: entity ``type`` projection,
        prepared-input schema v2, centralized Stage-11 context bounds and
        eligibility-revision binding.
"""

POST_SESSION_PROMPT_VERSION = "1"
"""Prompt-material contract version included in the fingerprint.

Bump it whenever the prepared prompt material changes.
"""

# ── Attempt identity ──────────────────────────────────────────────────────


def new_attempt_id() -> str:
    """Generate a trusted, opaque processing-attempt identifier.

    The value is random (``uuid4``), never derived from the input fingerprint,
    and satisfies the domain ``PostSessionAttemptId`` contract: lowercase
    ``att_`` prefix plus 32 hex characters, safe as a path component and
    inside a future ``changeset_id``.
    """
    return f"att_{uuid4().hex}"


# ── Canonical prepared-input fingerprint ──────────────────────────────────


def canonical_prepared_input_bytes(identity: PreparedInputIdentity) -> bytes:
    """Serialize a ``PreparedInputIdentity`` to deterministic UTF-8 bytes.

    Determinism guarantees:

    - tuple component order is preserved (explicit canonical ordering);
    - JSON object keys are sorted, so dict insertion order is irrelevant;
    - compact separators make the result independent of pretty-printing;
    - enums are normalized through ``mode="json"``;
    - Unicode is preserved and encoded as UTF-8 with no normalization;
    - ``allow_nan=False`` forbids NaN/Infinity;
    - ``exclude_unset=False`` keeps every declared field.
    """
    payload = identity.model_dump(mode="json", exclude_unset=False)
    try:
        text = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "Prepared-input identity is not canonically serializable",
            cause=exc,
        ) from exc
    return text.encode("utf-8")


def compute_input_fingerprint(identity: PreparedInputIdentity) -> Sha256Fingerprint:
    """Compute the lowercase-hex SHA-256 fingerprint of the prepared input."""
    digest = hashlib.sha256(canonical_prepared_input_bytes(identity)).hexdigest()
    return Sha256Fingerprint(digest=digest)


__all__ = [
    "POST_SESSION_PROCESSOR_VERSION",
    "POST_SESSION_PROMPT_VERSION",
    "canonical_prepared_input_bytes",
    "compute_input_fingerprint",
    "new_attempt_id",
]
