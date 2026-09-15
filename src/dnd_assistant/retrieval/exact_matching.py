"""Pure deterministic exact-text and alias helpers shared by retrieval.

This module owns the single canonical project policy for:

- exact-text normalization (strip -> Unicode NFC -> casefold);
- fail-closed extraction of canonical alias strings from raw
  ``extra_frontmatter["aliases"]`` data.

The helpers are pure, read-only and provider-neutral.  They carry no
player-visibility policy, no search tiers and no repository access.  They are
shared by the player-facing retrieval implementation and by internal
deterministic post-session binding so that a single normalization/alias
grammar exists.

This module belongs to the retrieval layer and must not import from:
    storage, application, domain, models, tools, cli, ollama, pydantic_ai
"""

from __future__ import annotations

import unicodedata

__all__ = ["extract_exact_aliases", "normalize_exact_text"]


def normalize_exact_text(text: str) -> str:
    """Normalise text for exact name/alias comparison.

    Applies, in order:

    1. strip surrounding whitespace;
    2. Unicode NFC normalisation;
    3. Unicode ``casefold()``.

    This is a conservative deterministic policy.  It does **not** implement
    transliteration, punctuation stripping, accent stripping, token sorting,
    or word reordering.
    """
    return unicodedata.normalize("NFC", text.strip()).casefold()


def extract_exact_aliases(raw: object) -> tuple[str, ...]:
    """Extract eligible alias strings from a raw ``aliases`` value.

    Fail-closed parsing:

    * ``None`` → no aliases.
    * ``list`` / ``tuple`` → inspect each entry:
      - strict ``str`` entry, printable, non-empty after strip → eligible;
      - non-string, non-printable, empty/whitespace-only → ignored.
    * scalar ``str`` → malformed, no aliases (do NOT iterate characters).
    * ``dict`` / other mapping / any other type → malformed, no aliases.

    Duplicate alias values are collapsed preserving first-occurrence order.
    """
    if raw is None:
        return ()

    if isinstance(raw, (list, tuple)):
        seen: set[str] = set()
        result: list[str] = []
        for entry in raw:
            if not isinstance(entry, str):
                continue
            if not entry.isprintable():
                continue
            stripped = entry.strip()
            if not stripped:
                continue
            if stripped not in seen:
                seen.add(stripped)
                result.append(stripped)
        return tuple(result)

    # Scalar string, dict, or other unexpected type → malformed
    return ()
