"""Markdown/YAML document codec for Obsidian entity documents.

Converts between:

    Obsidian entity Markdown text
        ↕
    VaultDocument

This module is a pure text codec.  It does NOT perform filesystem access,
path validation, atomic writes, or audit logging.

Parse contract
--------------

Input: ``str`` containing a complete Markdown document with YAML frontmatter.

Required format::

    ---
    <YAML mapping>
    ---
    <Markdown body>

- Frontmatter must begin at the first line of the document.
- The closing delimiter is a standalone ``---`` delimiter line.
- A ``---`` sequence inside the Markdown body must not be confused with
  frontmatter.
- Indented or scalar-content YAML is not terminated merely because its
  text contains ``---``; only the actual standalone frontmatter delimiter
  line terminates frontmatter.

Serialization contract
----------------------

Output is valid UTF-8-compatible Unicode text with LF line endings for
newly generated frontmatter delimiters and YAML output.

Canonical Entity fields are serialised before extra frontmatter fields.

``VaultDocument.body`` is preserved character-for-character through
``parse → serialize``, except that serialization owns the newly generated
frontmatter and its delimiter newline.

YAML preservation policy
------------------------

Guaranteed:

- unknown/non-core frontmatter keys survive parse/serialize semantically;
- their values remain equivalent YAML data;
- key/value information is not silently dropped.

NOT guaranteed:

- YAML comments;
- anchors/aliases presentation;
- scalar quote style;
- flow/block formatting;
- exact whitespace;
- exact original key formatting;
- original frontmatter newline style;
- byte-identical frontmatter output.
"""

from __future__ import annotations

import io

import ruamel.yaml
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.domain.entity import Entity
from dnd_assistant.errors import ValidationError
from dnd_assistant.storage.types import VaultDocument

# ── Constants ───────────────────────────────────────────────────────────────

FM_DELIMITER = "---"
"""Frontmatter delimiter line."""

# ── YAML instance factory ───────────────────────────────────────────────────


def _make_yaml() -> ruamel.yaml.YAML:
    """Create a fresh YAML serializer instance.

    Each call returns an independent instance so that a failed
    serialization does not corrupt a shared module-level instance.
    """
    yaml = ruamel.yaml.YAML(typ="safe")
    yaml.default_flow_style = False
    yaml.allow_unicode = True
    yaml.indent(mapping=2, sequence=2, offset=0)
    yaml.sort_base_mapping_type_on_output = False
    return yaml


# ── Canonical Entity field names ────────────────────────────────────────────

_ENTITY_FIELD_ORDER: tuple[str, ...] = tuple(Entity.model_fields.keys())
"""Ordered canonical field names, matching the Entity Pydantic model declaration order."""

_ENTITY_FIELD_NAMES: frozenset[str] = frozenset(_ENTITY_FIELD_ORDER)
"""Set of canonical field names defined by the Entity Pydantic model (for membership checks)."""


# ── Frontmatter boundary helpers ────────────────────────────────────────────


def _find_frontmatter(text: str) -> tuple[int, int, int] | None:
    """Locate frontmatter boundaries in ``text``.

    Args:
        text: The full Markdown document text.

    Returns:
        A tuple ``(opener_end, closer_start, closer_end)`` where:
        - ``opener_end`` is the index of the newline after the opening
          ``---`` line;
        - ``closer_start`` is the index of the ``---`` that closes the
          frontmatter;
        - ``closer_end`` is the index of the newline after the closing
          ``---`` line.

        Returns ``None`` if the frontmatter is missing or malformed
        (no opening delimiter at line 1, or no closing delimiter found).
    """
    # The opening delimiter must be exactly "---" at position 0, followed
    # immediately by "\n" or "\r\n".  No leading whitespace, no extra
    # hyphens, no trailing text on the delimiter line.
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return None

    # Skip the opening --- line
    if text.startswith("---\r\n"):
        opener_end = 5  # len("---\r\n")
    else:
        opener_end = 4  # len("---\n")

    # Search for the closing --- delimiter line
    # It must be a standalone line: start-of-line, "---", then optionally
    # whitespace, then end-of-line.
    search_start = opener_end
    while True:
        closer_start = text.find("\n" + FM_DELIMITER, search_start - 1)
        if closer_start == -1:
            return None

        # closer_start points to the \n before ---; move past it
        closer_start += 1

        # Check that this --- is a standalone delimiter line
        line_end = text.find("\n", closer_start + len(FM_DELIMITER))
        if line_end == -1:
            line_end = len(text)

        rest_of_line = text[closer_start + len(FM_DELIMITER) : line_end]
        if rest_of_line.strip() == "":
            # This is a standalone delimiter line
            closer_end = line_end + 1 if line_end < len(text) else line_end
            return (opener_end, closer_start, closer_end)

        # False alarm: --- was part of content; keep searching
        search_start = line_end + 1


# ── Parse ───────────────────────────────────────────────────────────────────


def parse(text: str) -> VaultDocument:
    """Parse an Obsidian Markdown document with YAML frontmatter.

    Args:
        text: The complete Markdown document text.

    Returns:
        A ``VaultDocument`` with the parsed entity, extra frontmatter,
        and Markdown body.

    Raises:
        ValidationError: The document is malformed, has invalid YAML,
            missing required fields, or invalid field values.
    """
    if not isinstance(text, str):
        raise ValidationError("Input must be a string")

    boundaries = _find_frontmatter(text)
    if boundaries is None:
        raise ValidationError(
            "Document must start with '---' frontmatter opener and have a closing '---' delimiter"
        )

    opener_end, closer_start, closer_end = boundaries

    # Extract YAML content (between opener and closer)
    yaml_text = text[opener_end:closer_start]

    # Extract Markdown body (after closing delimiter)
    body = text[closer_end:]

    # Parse YAML
    try:
        raw: object = _make_yaml().load(yaml_text)
    except Exception as exc:
        raise ValidationError(
            "Failed to parse YAML frontmatter",
            cause=exc,
        ) from exc

    if not isinstance(raw, dict):
        raise ValidationError(
            f"YAML frontmatter root must be a mapping (key/value pairs), got {type(raw).__name__}"
        )

    # Check for non-string keys
    for key in raw:
        if not isinstance(key, str):
            raise ValidationError(
                f"YAML frontmatter keys must be strings, got {type(key).__name__}"
            )

    raw_mapping: dict[str, object] = dict(raw)

    # Separate canonical Entity fields from extra frontmatter
    entity_data: dict[str, object] = {}
    extra_frontmatter: dict[str, object] = {}

    for key, value in raw_mapping.items():
        if key in _ENTITY_FIELD_NAMES:
            entity_data[key] = value
        else:
            extra_frontmatter[key] = value

    # Validate Entity
    try:
        entity = Entity.model_validate(entity_data)
    except PydanticValidationError as exc:
        raise ValidationError(
            "Entity validation failed for frontmatter fields",
            cause=exc,
        ) from exc

    return VaultDocument(
        entity=entity,
        extra_frontmatter=extra_frontmatter,
        body=body,
    )


# ── Serialize ───────────────────────────────────────────────────────────────


def serialize(document: VaultDocument) -> str:
    """Serialize a ``VaultDocument`` back to Obsidian Markdown text.

    Args:
        document: The document to serialize.

    Returns:
        A complete Markdown document string with YAML frontmatter.

    Raises:
        ValidationError: Extra frontmatter keys collide with canonical
            Entity field names.
    """
    # Detect canonical/extra key collisions
    extra_keys = set(document.extra_frontmatter)
    collision = extra_keys & _ENTITY_FIELD_NAMES
    if collision:
        raise ValidationError(
            f"Extra frontmatter keys collide with canonical Entity fields: {sorted(collision)}"
        )

    # Serialize Entity to YAML-compatible primitives
    entity_dict = document.entity.model_dump(mode="json")

    # Build combined frontmatter: canonical fields first (in declaration
    # order), then extras
    frontmatter: dict[str, object] = {}
    for key in _ENTITY_FIELD_ORDER:
        if key in entity_dict:
            value = entity_dict[key]
            # Omit None values and empty default lists for cleaner output
            if value is not None and not (key == "tags" and value == []):
                frontmatter[key] = value

    # Add extra frontmatter (already validated not to collide)
    for key, value in document.extra_frontmatter.items():
        if not isinstance(key, str):
            raise ValidationError(
                f"Extra frontmatter keys must be strings, got {type(key).__name__}"
            )
        frontmatter[key] = value

    # Serialize to YAML string
    buf = io.StringIO()
    try:
        _make_yaml().dump(frontmatter, buf)
    except Exception as exc:
        raise ValidationError(
            "Failed to serialize frontmatter to YAML",
            cause=exc,
        ) from exc
    yaml_output = buf.getvalue()

    # Build final document
    parts: list[str] = [FM_DELIMITER, "\n", yaml_output, FM_DELIMITER, "\n"]
    parts.append(document.body)

    return "".join(parts)
