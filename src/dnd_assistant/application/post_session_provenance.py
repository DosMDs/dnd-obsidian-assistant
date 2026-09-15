"""S11-05 shared prepared/accepted extraction provenance binding.

A single provider-neutral policy proves that an accepted S11-03 extraction
still belongs to an accepted S11-02 prepared input.  It is shared by S11-04
(rendering) and S11-05 (ChangeSet production) so that the two consumers cannot
drift into subtly different rules.

The helper reports a bounded, ordered tuple of mismatch labels; each caller
maps a non-empty tuple onto its own typed failure.  It performs no I/O, no
model call and no repository read.

This module belongs to the application layer and must not import from:
    storage, models, ollama, pydantic_ai, tools, cli, retrieval
"""

from __future__ import annotations

from dnd_assistant.application.post_session_context import PreparedPostSessionInput
from dnd_assistant.application.post_session_extraction import (
    AcceptedPostSessionExtraction,
)
from dnd_assistant.domain.post_session_extraction import (
    POST_SESSION_EXTRACTION_SCHEMA_VERSION,
)

__all__ = ["extraction_binding_mismatches"]


def extraction_binding_mismatches(
    prepared: PreparedPostSessionInput,
    accepted: AcceptedPostSessionExtraction,
) -> tuple[str, ...]:
    """Return the ordered mismatch labels, or ``()`` when fully bound.

    Verifies session identity, input fingerprint, processor version,
    extraction prompt version and both extraction schema-version declarations.
    """
    provenance = accepted.provenance
    identity = prepared.identity

    mismatches: list[str] = []
    if provenance.session_ref != identity.session.id:
        mismatches.append("session_ref")
    if provenance.input_fingerprint != prepared.fingerprint:
        mismatches.append("input_fingerprint")
    if provenance.processor_version != identity.processor_version:
        mismatches.append("processor_version")
    if provenance.prompt_version != identity.prompt_version:
        mismatches.append("prompt_version")
    if provenance.extraction_schema_version != POST_SESSION_EXTRACTION_SCHEMA_VERSION:
        mismatches.append("extraction_schema_version")
    if accepted.validated.extraction.schema_version != POST_SESSION_EXTRACTION_SCHEMA_VERSION:
        mismatches.append("extraction.schema_version")

    return tuple(mismatches)
