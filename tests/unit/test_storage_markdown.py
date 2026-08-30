"""Tests for the Markdown/YAML document codec (S3-01).

Covers:
- Canonical parse (minimal, all fields, each EntityType)
- Extra frontmatter (scalars, lists, nested, booleans, null, round trip)
- Body preservation (empty, headings, blank lines, trailing newlines, CRLF, --- in body, code fences, Unicode)
- Invalid documents (missing opener/closer, malformed YAML, wrong root type, invalid values, missing fields, non-string keys)
- Serialization (collision rejection, deterministic field order)
- Round-trip guarantees
- Import smoke tests
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest

from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityId, EntityType, Revision
from dnd_assistant.errors import ValidationError
from dnd_assistant.storage import VaultDocument, parse, serialize
from dnd_assistant.storage.markdown import _find_frontmatter

# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_entity(
    *,
    id_str: str = "gandalf",
    entity_type: EntityType = EntityType.NPC,
    name: str = "Gandalf",
    status: str = "alive",
    visibility: str = "player",
    knowledge_status: str = "confirmed",
    revision: int = 1,
    tags: list[str] | None = None,
) -> Entity:
    return Entity(
        id=cast(EntityId, id_str),
        type=entity_type,
        name=name,
        status=status,
        visibility=visibility,
        knowledge_status=knowledge_status,
        created_at=datetime(2026, 8, 30, 10, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 30, 10, 0, 0, tzinfo=UTC),
        revision=cast(Revision, revision),
        tags=tags or [],
    )


def _minimal_frontmatter(**overrides: str) -> str:
    """Build a minimal YAML frontmatter string with overridable values."""
    defaults: dict[str, str] = {
        "id": "gandalf",
        "type": "npc",
        "name": "Gandalf",
        "status": "alive",
        "visibility": "player",
        "knowledge_status": "confirmed",
        "created_at": "2026-08-30T10:00:00Z",
        "updated_at": "2026-08-30T10:00:00Z",
        "revision": "1",
    }
    # Apply overrides
    defaults.update(overrides)
    lines = [f"{k}: {v}" for k, v in defaults.items()]
    return "\n".join(lines)


def _minimal_document(body: str = "", **overrides: str) -> str:
    """Build a complete minimal Markdown document."""
    fm = _minimal_frontmatter(**overrides)
    return f"---\n{fm}\n---\n{body}"


# ── _find_frontmatter tests ─────────────────────────────────────────────────


class TestFindFrontmatter:
    def test_simple_frontmatter(self) -> None:
        text = "---\nkey: value\n---\nBody"
        result = _find_frontmatter(text)
        assert result is not None
        opener_end, closer_start, closer_end = result
        assert text[opener_end:closer_start] == "key: value\n"
        assert text[closer_end:] == "Body"

    def test_no_opener(self) -> None:
        assert _find_frontmatter("no frontmatter") is None

    def test_no_closer(self) -> None:
        assert _find_frontmatter("---\nkey: value\n") is None

    def test_only_opener(self) -> None:
        assert _find_frontmatter("---") is None

    def test_delimiter_in_body_not_confused(self) -> None:
        text = "---\nkey: value\n---\nSome --- text"
        result = _find_frontmatter(text)
        assert result is not None
        _, _, closer_end = result
        assert text[closer_end:] == "Some --- text"

    def test_crlf_delimiters(self) -> None:
        text = "---\r\nkey: value\r\n---\r\nBody"
        result = _find_frontmatter(text)
        assert result is not None
        opener_end, closer_start, closer_end = result
        assert text[opener_end:closer_start] == "key: value\r\n"
        assert text[closer_end:] == "Body"

    def test_closer_with_trailing_whitespace(self) -> None:
        text = "---\nkey: value\n---  \nBody"
        result = _find_frontmatter(text)
        assert result is not None
        _, closer_start, closer_end = result
        assert text[closer_start:closer_end].startswith("---")
        assert text[closer_end:] == "Body"

    # ── Negative opener tests (S3-01 correction 1) ─────────────────────

    def test_four_hyphens_rejected(self) -> None:
        """``----`` must not be accepted as an opener."""
        assert _find_frontmatter("----\nkey: value\n---\nbody") is None

    def test_opener_with_trailing_text_rejected(self) -> None:
        """``--- text`` must not be accepted as an opener."""
        assert _find_frontmatter("--- text\nkey: value\n---\nbody") is None

    def test_opener_with_leading_space_rejected(self) -> None:
        """`` ---`` (leading space) must not be accepted."""
        assert _find_frontmatter(" ---\nkey: value\n---\nbody") is None

    def test_opener_with_leading_tab_rejected(self) -> None:
        """``\\t---`` (leading tab) must not be accepted."""
        assert _find_frontmatter("\t---\nkey: value\n---\nbody") is None


# ── Canonical parse tests ───────────────────────────────────────────────────


class TestParseCanonical:
    def test_minimal_entity(self) -> None:
        doc = parse(_minimal_document())
        assert doc.entity.id == cast(EntityId, "gandalf")
        assert doc.entity.type == EntityType.NPC
        assert doc.entity.name == "Gandalf"
        assert doc.entity.status == "alive"
        assert doc.entity.visibility.value == "player"
        assert doc.entity.knowledge_status.value == "confirmed"
        assert doc.entity.revision == 1
        assert doc.entity.schema_version == 1
        assert doc.extra_frontmatter == {}
        assert doc.body == ""

    def test_all_entity_types(self) -> None:
        for entity_type in EntityType:
            doc = parse(_minimal_document(type=entity_type.value))
            assert doc.entity.type == entity_type

    def test_entity_with_tags(self) -> None:
        text = "---\n" + _minimal_frontmatter(tags="[wizard, istari]") + "\n---\n"
        doc = parse(text)
        assert doc.entity.tags == ["wizard", "istari"]

    def test_entity_with_session_refs(self) -> None:
        text = (
            "---\n"
            + _minimal_frontmatter(created_session="S001", last_seen_session="S005")
            + "\n---\n"
        )
        doc = parse(text)
        assert doc.entity.created_session == "S001"
        assert doc.entity.last_seen_session == "S005"

    def test_entity_with_empty_body(self) -> None:
        doc = parse(_minimal_document(body=""))
        assert doc.body == ""

    def test_parse_importable(self) -> None:
        from dnd_assistant.storage import parse  # noqa: F401


# ── Extra frontmatter tests ─────────────────────────────────────────────────


class TestParseExtraFrontmatter:
    def test_scalar_extra(self) -> None:
        text = "---\n" + _minimal_frontmatter() + "\nfaction: The Fellowship\n---\n"
        doc = parse(text)
        assert doc.extra_frontmatter["faction"] == "The Fellowship"

    def test_list_extra(self) -> None:
        text = "---\n" + _minimal_frontmatter() + "\nallies:\n- Frodo\n- Aragorn\n---\n"
        doc = parse(text)
        assert doc.extra_frontmatter["allies"] == ["Frodo", "Aragorn"]

    def test_nested_mapping_extra(self) -> None:
        text = "---\n" + _minimal_frontmatter() + "\nstats:\n  str: 10\n  dex: 14\n---\n"
        doc = parse(text)
        assert doc.extra_frontmatter["stats"] == {"str": 10, "dex": 14}

    def test_boolean_extra(self) -> None:
        text = "---\n" + _minimal_frontmatter() + "\nis_immortal: true\n---\n"
        doc = parse(text)
        assert doc.extra_frontmatter["is_immortal"] is True

    def test_number_extra(self) -> None:
        text = "---\n" + _minimal_frontmatter() + "\nage: 2000\n---\n"
        doc = parse(text)
        assert doc.extra_frontmatter["age"] == 2000

    def test_null_extra(self) -> None:
        text = "---\n" + _minimal_frontmatter() + "\nsecret: null\n---\n"
        doc = parse(text)
        assert doc.extra_frontmatter["secret"] is None

    def test_multiple_unknown_keys(self) -> None:
        text = (
            "---\n"
            + _minimal_frontmatter()
            + "\nfaction: The Fellowship\n"
            + "race: Maia\n"
            + "home: Valinor\n"
            + "---\n"
        )
        doc = parse(text)
        assert doc.extra_frontmatter["faction"] == "The Fellowship"
        assert doc.extra_frontmatter["race"] == "Maia"
        assert doc.extra_frontmatter["home"] == "Valinor"

    def test_extra_semantic_round_trip(self) -> None:
        """Extra frontmatter survives parse/serialize semantically."""
        text = (
            "---\n"
            + _minimal_frontmatter()
            + "\nfaction: The Fellowship\n"
            + "allies:\n  - Frodo\n  - Aragorn\n"
            + "age: 2000\n"
            + "---\nBody text"
        )
        doc = parse(text)
        serialized = serialize(doc)
        reparsed = parse(serialized)
        assert reparsed.extra_frontmatter == doc.extra_frontmatter


# ── Body preservation tests ─────────────────────────────────────────────────


class TestBodyPreservation:
    def test_empty_body(self) -> None:
        doc = parse(_minimal_document(body=""))
        assert doc.body == ""

    def test_heading_body(self) -> None:
        doc = parse(_minimal_document(body="## Description\nA wizard.\n"))
        assert doc.body == "## Description\nA wizard.\n"

    def test_blank_line_after_frontmatter(self) -> None:
        doc = parse(_minimal_document(body="\n## Description\n"))
        assert doc.body == "\n## Description\n"

    def test_multiple_blank_lines(self) -> None:
        doc = parse(_minimal_document(body="\n\n\nBody\n"))
        assert doc.body == "\n\n\nBody\n"

    def test_trailing_newline(self) -> None:
        doc = parse(_minimal_document(body="Body\n"))
        assert doc.body == "Body\n"

    def test_no_trailing_newline(self) -> None:
        doc = parse(_minimal_document(body="Body"))
        assert doc.body == "Body"

    def test_crlf_source_frontmatter(self) -> None:
        """CRLF in frontmatter delimiters is parsed correctly."""
        text = "---\r\n" + _minimal_frontmatter() + "\r\n---\r\nBody text"
        doc = parse(text)
        assert doc.body == "Body text"
        assert doc.entity.id == cast(EntityId, "gandalf")

    def test_horizontal_rule_in_body(self) -> None:
        doc = parse(_minimal_document(body="## Section\n\n---\n\nMore text\n"))
        assert doc.body == "## Section\n\n---\n\nMore text\n"

    def test_code_fence_with_delimiter(self) -> None:
        body = "```\n---\nstill code\n```\n"
        doc = parse(_minimal_document(body=body))
        assert doc.body == body

    def test_wikilinks(self) -> None:
        body = "See [[Aragorn]] and [[Frodo]]\n"
        doc = parse(_minimal_document(body=body))
        assert doc.body == body

    def test_unicode_body(self) -> None:
        body = "## Описание\nВолшебник из Средиземья.\n"
        doc = parse(_minimal_document(body=body))
        assert doc.body == body

    def test_body_preserved_through_round_trip(self) -> None:
        body = "## Notes\n- Met in Bree.\n- Friendly.\n"
        text = _minimal_document(body=body)
        doc = parse(text)
        serialized = serialize(doc)
        reparsed = parse(serialized)
        assert reparsed.body == doc.body

    def test_body_with_only_newlines(self) -> None:
        doc = parse(_minimal_document(body="\n\n\n"))
        assert doc.body == "\n\n\n"


# ── Invalid document tests ─────────────────────────────────────────────────


class TestParseInvalid:
    def test_not_a_string(self) -> None:
        with pytest.raises(ValidationError, match="Input must be a string"):
            parse(123)  # type: ignore[arg-type]

    def test_missing_opener(self) -> None:
        with pytest.raises(ValidationError, match="must start with"):
            parse("key: value\n---\nbody")

    def test_missing_closer(self) -> None:
        with pytest.raises(ValidationError, match="must start with"):
            parse("---\nkey: value\nbody")

    def test_malformed_yaml(self) -> None:
        with pytest.raises(ValidationError, match="Failed to parse YAML"):
            parse("---\nkey: [invalid\n---\nbody")

    def test_yaml_sequence_root(self) -> None:
        with pytest.raises(ValidationError, match="root must be a mapping"):
            parse("---\n- one\n- two\n---\nbody")

    def test_yaml_scalar_root(self) -> None:
        with pytest.raises(ValidationError, match="root must be a mapping"):
            parse("---\njust a string\n---\nbody")

    def test_missing_required_field(self) -> None:
        text = "---\nname: Gandalf\nstatus: alive\n---\n"
        with pytest.raises(ValidationError, match="Entity validation failed"):
            parse(text)

    def test_invalid_entity_type(self) -> None:
        text = "---\n" + _minimal_frontmatter(type="invalid") + "\n---\n"
        with pytest.raises(ValidationError, match="Entity validation failed"):
            parse(text)

    def test_invalid_revision(self) -> None:
        text = "---\n" + _minimal_frontmatter(revision="zero") + "\n---\n"
        with pytest.raises(ValidationError, match="Entity validation failed"):
            parse(text)

    def test_invalid_datetime(self) -> None:
        text = "---\n" + _minimal_frontmatter(created_at="not-a-date") + "\n---\n"
        with pytest.raises(ValidationError, match="Entity validation failed"):
            parse(text)

    def test_non_string_key(self) -> None:
        text = "---\n" + _minimal_frontmatter() + "\n42: numeric-key\n---\n"
        with pytest.raises(ValidationError, match="keys must be strings"):
            parse(text)

    def test_empty_document(self) -> None:
        with pytest.raises(ValidationError, match="must start with"):
            parse("")

    def test_only_frontmatter_opener(self) -> None:
        with pytest.raises(ValidationError, match="must start with"):
            parse("---")

    def test_empty_frontmatter(self) -> None:
        with pytest.raises(ValidationError, match="root must be a mapping"):
            parse("---\n---\nbody")


# ── Serialization tests ─────────────────────────────────────────────────────


class TestSerialize:
    def test_round_trip_minimal(self) -> None:
        text = _minimal_document()
        doc = parse(text)
        serialized = serialize(doc)
        reparsed = parse(serialized)
        assert reparsed.entity == doc.entity
        assert reparsed.extra_frontmatter == doc.extra_frontmatter
        assert reparsed.body == doc.body

    def test_round_trip_with_body(self) -> None:
        text = _minimal_document(body="## Notes\nSome content.\n")
        doc = parse(text)
        serialized = serialize(doc)
        reparsed = parse(serialized)
        assert reparsed.entity == doc.entity
        assert reparsed.body == doc.body

    def test_round_trip_with_extras(self) -> None:
        text = (
            "---\n"
            + _minimal_frontmatter()
            + "\nfaction: The Fellowship\n"
            + "allies:\n  - Frodo\n  - Aragorn\n"
            + "---\nBody\n"
        )
        doc = parse(text)
        serialized = serialize(doc)
        reparsed = parse(serialized)
        assert reparsed.entity == doc.entity
        assert reparsed.extra_frontmatter == doc.extra_frontmatter
        assert reparsed.body == doc.body

    def test_round_trip_with_all_fields(self) -> None:
        entity = _make_entity(
            id_str="aragorn",
            name="Aragorn",
            status="alive",
            tags=["ranger", "king"],
        )
        doc = VaultDocument(
            entity=entity,
            extra_frontmatter={"faction": "The Fellowship"},
            body="## Description\nHeir of Isildur.\n",
        )
        serialized = serialize(doc)
        reparsed = parse(serialized)
        assert reparsed.entity == doc.entity
        assert reparsed.extra_frontmatter == doc.extra_frontmatter
        assert reparsed.body == doc.body

    def test_collision_rejected(self) -> None:
        """Extra frontmatter keys colliding with canonical fields are rejected."""
        entity = _make_entity()
        doc = VaultDocument(
            entity=entity,
            extra_frontmatter={"revision": 999},
        )
        with pytest.raises(ValidationError, match="collide"):
            serialize(doc)

    def test_collision_multiple_keys_rejected(self) -> None:
        entity = _make_entity()
        doc = VaultDocument(
            entity=entity,
            extra_frontmatter={"revision": 999, "name": "ShouldNotWork"},
        )
        with pytest.raises(ValidationError, match="collide"):
            serialize(doc)

    def test_canonical_fields_in_declaration_order(self) -> None:
        """Canonical Entity fields appear in Entity.model_fields declaration order."""
        from dnd_assistant.domain.entity import Entity as _Entity

        entity = _make_entity()
        doc = VaultDocument(
            entity=entity,
            extra_frontmatter={"faction": "The Fellowship"},
            body="Body\n",
        )
        output = serialize(doc)
        # Find the frontmatter section
        fm_start = output.index("---\n") + 4
        fm_end = output.index("\n---\n", fm_start)
        fm_section = output[fm_start:fm_end]
        fm_lines = fm_section.split("\n")

        # Collect keys in order of appearance (skip empty/blank lines)
        seen_keys: list[str] = []
        for line in fm_lines:
            stripped = line.strip()
            if stripped and ":" in stripped:
                key = stripped.split(":")[0].strip()
                seen_keys.append(key)

        # The canonical keys (non-None, non-empty-tags) must appear in
        # Entity.model_fields order, before any extra keys.
        expected_order = list(_Entity.model_fields.keys())
        # Filter out keys that would be omitted (None values, empty tags)
        expected_present = [
            k
            for k in expected_order
            if getattr(entity, k) is not None and not (k == "tags" and getattr(entity, k) == [])
        ]

        # Verify canonical keys appear in declaration order
        canonical_seen = [k for k in seen_keys if k in expected_present]
        assert canonical_seen == expected_present, (
            f"Canonical fields out of order: expected {expected_present}, got {canonical_seen}"
        )

        # Verify extra key appears after all canonical keys
        assert "faction" in seen_keys
        faction_idx = seen_keys.index("faction")
        last_canonical_idx = max(seen_keys.index(k) for k in canonical_seen)
        assert faction_idx > last_canonical_idx, (
            "Extra field 'faction' appeared before canonical fields"
        )

    def test_output_starts_and_ends_with_delimiters(self) -> None:
        entity = _make_entity()
        doc = VaultDocument(entity=entity, body="Body\n")
        output = serialize(doc)
        assert output.startswith("---\n")
        # Should have --- before body
        assert "\n---\n" in output

    def test_serialize_importable(self) -> None:
        from dnd_assistant.storage import serialize  # noqa: F401

    # ── Serialize-side non-string key validation (S3-01 correction 3) ──

    def test_serialize_rejects_non_string_extra_key(self) -> None:
        """Serialization must reject non-string extra frontmatter keys."""
        entity = _make_entity()
        # Construct VaultDocument with an int key via type-ignore
        extra: dict[str, object] = {"valid": "ok"}
        extra[cast(str, 42)] = "numeric-key"  # type: ignore[assignment]
        doc = VaultDocument(entity=entity, extra_frontmatter=extra)  # type: ignore[arg-type]
        with pytest.raises(ValidationError, match="keys must be strings"):
            serialize(doc)

    # ── YAML serialization error wrapping (S3-01 correction 4) ─────────

    def test_serialize_wraps_yaml_failure(self) -> None:
        """YAML serialization failures must raise ValidationError with __cause__."""
        entity = _make_entity()

        # ruamel.yaml safe dumper cannot serialize arbitrary objects
        class Unserializable:
            pass

        doc = VaultDocument(
            entity=entity,
            extra_frontmatter={"bad_value": Unserializable()},
        )
        with pytest.raises(ValidationError) as exc_info:
            serialize(doc)
        assert exc_info.value.__cause__ is not None, (
            "ValidationError must preserve original exception as __cause__"
        )


# ── Round-trip integration tests ────────────────────────────────────────────


class TestRoundTrip:
    """Verify the parse(serialize(parse(source))) invariant."""

    @pytest.mark.parametrize(
        ("source", "description"),
        [
            (_minimal_document(), "minimal"),
            (_minimal_document(body="\n"), "body with single newline"),
            (_minimal_document(body="Body text"), "body no trailing newline"),
            (_minimal_document(body="Body text\n"), "body with trailing newline"),
            (
                _minimal_document(body="## Heading\n\nParagraph.\n\n---\n\nMore.\n"),
                "body with horizontal rule",
            ),
            (
                _minimal_document(body="```yaml\n---\nkey: inside code\n```\n"),
                "body with code fence containing ---",
            ),
            (
                "---\n" + _minimal_frontmatter() + "\nextra: value\n---\nBody\n",
                "with extra frontmatter",
            ),
            (
                "---\n" + _minimal_frontmatter(tags="[tag1, tag2]") + "\n---\nBody\n",
                "with tags",
            ),
            (
                _minimal_document(body="## Описание\nРусский текст.\n"),
                "Unicode body",
            ),
        ],
    )
    def test_round_trip_preserves_semantics(self, source: str, description: str) -> None:
        parsed = parse(source)
        serialized = serialize(parsed)
        reparsed = parse(serialized)
        assert reparsed.entity == parsed.entity, f"Entity mismatch: {description}"
        assert reparsed.extra_frontmatter == parsed.extra_frontmatter, (
            f"Extra frontmatter mismatch: {description}"
        )
        assert reparsed.body == parsed.body, f"Body mismatch: {description}"


# ── Import / boundary tests ────────────────────────────────────────────────


def test_markdown_module_importable() -> None:
    from dnd_assistant.storage import markdown  # noqa: F401


def test_markdown_reexported() -> None:
    from dnd_assistant.storage import parse, serialize  # noqa: F401


def test_markdown_does_not_import_models() -> None:
    """Verify storage/markdown does not trigger model imports."""
    import sys

    for key in list(sys.modules):
        if key.startswith("dnd_assistant"):
            del sys.modules[key]

    import dnd_assistant.storage.markdown  # noqa: F401

    mod_names = {m for m in sys.modules if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"storage/markdown imported model modules: {mod_names}"


def test_markdown_does_not_import_retrieval() -> None:
    import sys

    for key in list(sys.modules):
        if key.startswith("dnd_assistant"):
            del sys.modules[key]

    import dnd_assistant.storage.markdown  # noqa: F401

    mod_names = {m for m in sys.modules if m.startswith("dnd_assistant.retrieval")}
    assert not mod_names, f"storage/markdown imported retrieval modules: {mod_names}"


def test_markdown_does_not_import_tools() -> None:
    import sys

    for key in list(sys.modules):
        if key.startswith("dnd_assistant"):
            del sys.modules[key]

    import dnd_assistant.storage.markdown  # noqa: F401

    mod_names = {m for m in sys.modules if m.startswith("dnd_assistant.tools")}
    assert not mod_names, f"storage/markdown imported tool modules: {mod_names}"
