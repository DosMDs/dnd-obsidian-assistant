"""S12-03 deterministic Campaign State rendering and manifest format.

Turns a validated in-memory ``CampaignState`` into the exact, human-readable
derived artifacts persisted under ``State/`` and into the canonical
machine-readable ``DerivedStateManifest``.

Determinism contract:

- pure, model-free, wall-clock-free and filesystem-free;
- UTF-8 output, ``\\n`` only (no CR/OS newline variation), exactly one
  trailing newline per artifact;
- ordering follows the already-canonicalized ``CampaignState`` structures;
- user-controlled printable strings are inline-escaped so they cannot alter
  the structural Markdown template.

Visibility contract: the human-readable MVP ``State/*.md`` files are
player-facing Vault material.  ``Recently Touched.md`` renders
``Visibility.PLAYER`` references only; DM/SYSTEM references never appear in
rendered artifact bytes.  The S12-02 source collection remains
all-visibility internally; S12-04 owns the reusable player-safe consumer
projection.

Format identity is separate from source identity: ``CAMPAIGN_STATE_RENDER_VERSION``
identifies the renderer/artifact format and is persisted as
``DerivedStateManifest.render_version``.  The source-snapshot fingerprint lives
in ``input_fingerprint`` and is never overloaded with presentation versioning.

This module belongs to the application layer and must not import from:
    storage, models, ollama, pydantic_ai, tools, cli, retrieval, pathlib, os
``hashlib`` and ``json`` are intentional application format concerns here.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.domain.calendar import GameDate
from dnd_assistant.domain.campaign_state import (
    CampaignEntityReference,
    CampaignState,
    CampaignStateArtifact,
    DerivedStateArtifact,
    DerivedStateManifest,
)
from dnd_assistant.domain.types import Sha256Fingerprint, Visibility
from dnd_assistant.errors import ValidationError

# ── Format identity ───────────────────────────────────────────────────────

CAMPAIGN_STATE_RENDER_VERSION: Final[str] = "3"
"""Artifact/renderer format version persisted as ``manifest.render_version``.

Bump whenever rendered artifact bytes or the managed artifact set can change
without a change to the canonical source-snapshot identity.  This is distinct
from ``CAMPAIGN_STATE_DERIVATION_VERSION`` (source identity).

Render ``"3"`` (S12-05): the internal all-visibility generation fingerprint is
no longer written into the PLAYER-facing ``State/World State.md`` bytes.  That
digest was a function of DM/SYSTEM evidence, so hidden-only canonical changes
could alter a PLAYER-facing artifact.  Source identity remains in the manifest
(``input_fingerprint``) and freshness/integrity remain enforced by deterministic
re-render comparison; no player-facing replacement fingerprint is introduced.
A generation persisted with render version ``"2"`` is classified ``OUTDATED``.
"""

_MANIFEST_SCHEMA_VERSION: Final[int] = 2

# ── Trusted logical artifact layout ───────────────────────────────────────
#
# These logical paths are inventory/validation identifiers only.  They carry
# no filesystem authority: physical destinations are mapped from the typed
# ``CampaignStateArtifact`` allowlist by the storage layer.

LOGICAL_ARTIFACT_PATHS: Final[dict[CampaignStateArtifact, str]] = {
    CampaignStateArtifact.WORLD_STATE: "State/World State.md",
    CampaignStateArtifact.RECENTLY_TOUCHED: "State/Recently Touched.md",
}
"""Trusted logical path of every managed artifact, in deterministic order."""

ARTIFACT_ORDER: Final[tuple[CampaignStateArtifact, ...]] = (
    CampaignStateArtifact.WORLD_STATE,
    CampaignStateArtifact.RECENTLY_TOUCHED,
)
"""Trusted managed artifact set in deterministic order."""

_DERIVED_BANNER = "_Derived campaign memory. Not canonical; regenerated from canonical evidence._"

# ── Errors ────────────────────────────────────────────────────────────────


class CampaignStateManifestError(ValidationError):
    """Raised when persisted manifest text is malformed or schema-invalid."""


class CampaignStateManifestOutdatedError(CampaignStateManifestError):
    """Raised when a manifest has a recognized but unsupported schema version."""


# ── Deterministic inline escaping ─────────────────────────────────────────


_MARKDOWN_METACHARACTERS: Final[frozenset[str]] = frozenset(
    {
        "\\",
        "`",
        "*",
        "_",
        "[",
        "]",
        "(",
        ")",
        "{",
        "}",
        "#",
        "|",
        "<",
        ">",
        "~",
        "!",
    }
)


def escape_inline(value: str) -> str:
    """Escape one user-controlled value for safe inline Markdown embedding.

    A single deterministic rule is applied to every user-controlled value
    (entity names, stable IDs, session IDs, calendar names): backslash-escape
    Markdown structural metacharacters and CR/LF so a value can never alter
    the surrounding template.  Validators already reject non-printable
    characters; CR/LF handling is a defensive belt.
    """
    parts: list[str] = []
    for char in value:
        if char == "\r":
            parts.append("\\r")
        elif char == "\n":
            parts.append("\\n")
        elif char in _MARKDOWN_METACHARACTERS:
            parts.append("\\" + char)
        else:
            parts.append(char)
    return "".join(parts)


# ── Generic calendar rendering ────────────────────────────────────────────


def render_game_date(date: GameDate) -> str:
    """Render a ``GameDate`` in its generic domain shape.

    No Gregorian assumptions: a regular date renders its named month and
    numbered day, an intercalary date renders its named intercalary day.
    Time-of-day (hour, minute) is always included.
    """
    if date.intercalary_day is not None:
        return (
            f"year={date.year}, "
            f"intercalary_day={escape_inline(date.intercalary_day)}, "
            f"hour={date.hour}, minute={date.minute}"
        )
    assert date.month is not None and date.day is not None
    return (
        f"year={date.year}, "
        f"month={escape_inline(date.month)}, "
        f"day={date.day}, "
        f"hour={date.hour}, minute={date.minute}"
    )


# ── Artifact rendering ────────────────────────────────────────────────────


def _render_world_state(state: CampaignState) -> str:
    lines = [
        "# World State",
        "",
        _DERIVED_BANNER,
        "",
        f"- Current world tick: {state.current_world_tick}",
    ]
    if state.current_game_date is not None:
        lines.append(f"- Current game date: {render_game_date(state.current_game_date)}")
    return "\n".join(lines) + "\n"


def _render_recently_touched(state: CampaignState) -> str:
    lines = [
        "# Recently Touched",
        "",
        _DERIVED_BANNER,
        "",
        'Entities referenced in the selected completed sessions. "Recently touched"',
        "does not mean current, active, or important. Only player-visible entities",
        "are listed.",
        "",
    ]
    player_refs = tuple(
        ref for ref in state.recently_touched if ref.visibility is Visibility.PLAYER
    )
    if not player_refs:
        lines.append("_No player-visible entities were touched in the selected sessions._")
        return "\n".join(lines) + "\n"

    for ref in player_refs:
        lines.append(_render_reference(ref))
    return "\n".join(lines) + "\n"


def _render_reference(ref: CampaignEntityReference) -> str:
    """Render one reference as a single fixed-structure list line.

    The entity id is rendered as ordinary escaped inline text, never inside a
    Markdown code span: backslash escaping is not interpreted inside CommonMark
    code spans, so a generally printable ``EntityId`` containing a backtick
    would break the span.  The existing deterministic ``escape_inline`` rule is
    valid in the inline-text context used here.
    """
    sessions = ", ".join(escape_inline(session_id) for session_id in ref.source_session_ids)
    return (
        f"- **{escape_inline(ref.name)}** "
        f"({escape_inline(ref.entity_id)}, {ref.entity_type.value}, "
        f"visibility: {ref.visibility.value}, revision: {ref.revision}) "
        f"— sessions: {sessions}"
    )


def render_campaign_state_artifacts(
    state: CampaignState,
) -> dict[CampaignStateArtifact, str]:
    """Render every managed artifact as exact deterministic text.

    The returned mapping always covers the exact trusted artifact set.
    """
    return {
        CampaignStateArtifact.WORLD_STATE: _render_world_state(state),
        CampaignStateArtifact.RECENTLY_TOUCHED: _render_recently_touched(state),
    }


# ── Hashing ───────────────────────────────────────────────────────────────


def artifact_content_hash(text: str) -> Sha256Fingerprint:
    """SHA-256 of the exact UTF-8 bytes of one rendered artifact."""
    return _bytes_hash(text.encode("utf-8"))


def artifact_bytes_hash(data: bytes) -> Sha256Fingerprint:
    """SHA-256 of exact stored artifact bytes."""
    return _bytes_hash(data)


def _bytes_hash(data: bytes) -> Sha256Fingerprint:
    return Sha256Fingerprint(digest=hashlib.sha256(data).hexdigest())


# ── Manifest build / serialize / parse ────────────────────────────────────


def build_manifest(
    state: CampaignState,
    artifacts: dict[CampaignStateArtifact, str],
) -> DerivedStateManifest:
    """Build the canonical manifest for a rendered generation.

    ``artifacts`` must cover the exact trusted artifact set; the manifest
    inventory is a function of it, keyed by trusted logical paths.
    """
    missing = set(LOGICAL_ARTIFACT_PATHS) - set(artifacts)
    if missing:
        raise CampaignStateManifestError(
            f"rendered artifact set is missing: {sorted(m.value for m in missing)}"
        )
    entries = tuple(
        DerivedStateArtifact(
            relative_path=LOGICAL_ARTIFACT_PATHS[artifact],
            content_hash=artifact_content_hash(artifacts[artifact]),
        )
        for artifact in ARTIFACT_ORDER
    )
    return DerivedStateManifest(
        render_version=CAMPAIGN_STATE_RENDER_VERSION,
        input_fingerprint=state.input_fingerprint,
        artifacts=entries,
    )


def serialize_manifest(manifest: DerivedStateManifest) -> str:
    """Serialize a manifest to canonical compact JSON ending in one ``\\n``."""
    payload = manifest.model_dump(mode="json")
    text = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return text + "\n"


def parse_manifest(text: str) -> DerivedStateManifest:
    """Parse and validate persisted manifest text.

    Raises:
        CampaignStateManifestOutdatedError: A recognized but unsupported
            ``schema_version``.
        CampaignStateManifestError: Malformed JSON or an invalid schema.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise CampaignStateManifestError("manifest is not valid JSON", cause=exc) from exc

    if not isinstance(data, dict):
        raise CampaignStateManifestError("manifest JSON must be an object")

    version = data.get("schema_version")
    if version != _MANIFEST_SCHEMA_VERSION:
        raise CampaignStateManifestOutdatedError(
            f"unsupported manifest schema_version: {version!r}"
        )

    try:
        return DerivedStateManifest.model_validate(data)
    except PydanticValidationError as exc:
        raise CampaignStateManifestError("manifest schema is invalid", cause=exc) from exc


__all__ = [
    "ARTIFACT_ORDER",
    "CAMPAIGN_STATE_RENDER_VERSION",
    "LOGICAL_ARTIFACT_PATHS",
    "CampaignStateManifestError",
    "CampaignStateManifestOutdatedError",
    "artifact_bytes_hash",
    "artifact_content_hash",
    "build_manifest",
    "escape_inline",
    "parse_manifest",
    "render_campaign_state_artifacts",
    "render_game_date",
    "serialize_manifest",
]
