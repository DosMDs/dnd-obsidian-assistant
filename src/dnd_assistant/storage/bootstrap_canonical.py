"""S13-03 filesystem-free canonical candidate parse helper.

Recognizes a *genuinely canonical* entity document from an already-read
``ENTITY_CANDIDATE`` source produced by the S13-02 discovery report.  It
performs **no filesystem I/O**: it takes a Vault-relative logical path plus the
exact UTF-8 text S13-02 already read, and reuses the existing canonical
Markdown codec and ``EntityDirectory`` ownership.

It deliberately does not rescan managed entity directories and does not import
the path-discovery or repository modules.  S13-02 remains the single trusted
traversal/read boundary.

A historical malformed note is reported as ``MALFORMED`` with no identity
(identity is never guessed from partially parsed YAML).  A parseable note that
is non-canonical (e.g. directory/type mismatch) reports reliable identity so
the application can conservatively block duplicate creation even though the
document is not bindable.

The pure recognition result types live in ``storage.bootstrap_types`` so the
application layer can consume them without importing this YAML-backed module.

This module belongs to the storage layer and must not import from:
    application, models, tools, retrieval, cli, ollama, pydantic_ai
"""

from __future__ import annotations

from dnd_assistant.errors import ValidationError
from dnd_assistant.storage.bootstrap_types import (
    CanonicalCandidate,
    CanonicalCandidateOutcome,
    expected_entity_type,
)
from dnd_assistant.storage.markdown import parse


def parse_canonical_candidate(relative_path: str, text: str) -> CanonicalCandidate:
    """Recognize a canonical entity from an already-read source candidate.

    Pure and filesystem-free.  A parse failure yields ``MALFORMED`` with no
    identity; a parseable but directory/type-inconsistent document yields
    ``TYPE_DIRECTORY_MISMATCH`` with its reliable parsed identity retained.
    """
    expected = expected_entity_type(relative_path)
    if expected is None:
        return CanonicalCandidate(
            relative_path=relative_path,
            expected_type=None,
            outcome=CanonicalCandidateOutcome.NOT_IN_ENTITY_DIRECTORY,
        )

    try:
        document = parse(text)
    except ValidationError:
        return CanonicalCandidate(
            relative_path=relative_path,
            expected_type=expected,
            outcome=CanonicalCandidateOutcome.MALFORMED,
        )

    entity = document.entity
    outcome = (
        CanonicalCandidateOutcome.CANONICAL
        if entity.type is expected
        else CanonicalCandidateOutcome.TYPE_DIRECTORY_MISMATCH
    )
    return CanonicalCandidate(
        relative_path=relative_path,
        expected_type=expected,
        outcome=outcome,
        document=document,
        entity_id=entity.id,
        entity_type=entity.type,
        display_name=entity.name,
        revision=entity.revision,
    )


__all__ = [
    "CanonicalCandidate",
    "CanonicalCandidateOutcome",
    "expected_entity_type",
    "parse_canonical_candidate",
]
