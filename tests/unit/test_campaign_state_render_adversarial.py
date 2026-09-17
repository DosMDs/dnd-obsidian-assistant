"""S12-05 Unicode and Markdown adversarial hardening for Campaign State render.

Proves exact deterministic UTF-8 serialization with no implicit Unicode
normalization, that distinct canonical strings stay distinct, that Markdown
metacharacters mixed with Unicode cannot gain attacker-controlled structure, and
that actually non-printable values are rejected at the canonical domain boundary
(not taught to the renderer).

Pure: no filesystem I/O, no model.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.application.agent_context import (
    MAX_AGENT_CAMPAIGN_MEMORY_TEXT_BYTES,
    _read_campaign_memory,
)
from dnd_assistant.application.campaign_state_projection import (
    PlayerCampaignEntityReference,
    PlayerCampaignState,
)
from dnd_assistant.application.campaign_state_render import (
    escape_inline,
    render_campaign_state_artifacts,
)
from dnd_assistant.domain.campaign_state import (
    CampaignEntityReference,
    CampaignStateArtifact,
)
from dnd_assistant.domain.types import EntityType
from tests.unit.campaign_state.helpers import make_reference, make_state

_FP = "a" * 64
_TOUCHED = CampaignStateArtifact.RECENTLY_TOUCHED


def _render(name: str, entity_id: str = "npc-x", *, sessions: tuple[str, ...] = ("S001",)) -> str:
    ref = make_reference(entity_id, name=name, source_session_ids=sessions)
    return render_campaign_state_artifacts(make_state(_FP, references=(ref,)))[_TOUCHED]


class _FakeProvider:
    def __init__(self, refs: tuple[PlayerCampaignEntityReference, ...]) -> None:
        self._state = PlayerCampaignState(recently_touched=refs)

    def get_player_campaign_state(self) -> PlayerCampaignState | None:
        return self._state


# ── Unicode corpus ─────────────────────────────────────────────────────────

_VALID_UNICODE = (
    ("cyrillic", "Магистр Варос"),
    ("emoji", "Дракон 😀🐉"),
    ("leading-combining", "\u0301Мария"),
    ("inner-combining", "e\u0301clair"),
    ("mixed-scripts", "Ārīa Тайна 日本"),
)


class TestUnicodeCorpus:
    @pytest.mark.parametrize(("label", "name"), _VALID_UNICODE)
    def test_valid_value_roundtrips_exact(self, label: str, name: str) -> None:
        text = _render(name)
        assert name in text

    def test_combining_mark_is_valid(self) -> None:
        # U+0301 (Mn) is printable per the canonical validators: accepted.
        assert "\u0301".isprintable()
        assert "\u0301Мария" in _render("\u0301Мария")

    def test_same_input_identical_bytes(self) -> None:
        name = "Дракон 😀 e\u0301"
        assert _render(name) == _render(name)

    def test_no_implicit_normalization_nfc_vs_nfd(self) -> None:
        nfc = "caf\u00e9"  # é precomposed
        nfd = "cafe\u0301"  # e + combining acute
        assert nfc != nfd
        nfc_text = _render(nfc)
        nfd_text = _render(nfd)
        assert nfc_text != nfd_text
        assert nfc in nfc_text
        assert nfd in nfd_text
        assert len(nfc.encode("utf-8")) != len(nfd.encode("utf-8"))

    def test_distinct_canonical_strings_stay_distinct(self) -> None:
        a = _render("Aria")
        b = _render("Ariа")  # final char is Cyrillic 'а'
        assert "Aria" in a
        assert "Ariа" in b
        assert a != b

    def test_long_multibyte_name_exact(self) -> None:
        name = "Ж" * 500
        text = _render(name)
        assert name in text
        assert text.encode("utf-8").count(name.encode("utf-8")) == 1

    def test_cyrillic_entity_id_exact(self) -> None:
        text = _render("Aria", entity_id="npc-варос")
        assert "npc-варос" in text


# ── Domain boundary rejection (renderer is not taught invalid values) ──────


class TestDomainBoundaryRejection:
    @pytest.mark.parametrize("bad", ["bad\nname", "nul\x00name", "zero\u200bwidth", "tab\tname"])
    def test_non_printable_name_rejected_by_domain(self, bad: str) -> None:
        with pytest.raises(PydanticValidationError):
            CampaignEntityReference(
                entity_id="npc-x",
                entity_type=EntityType.NPC,
                name=bad,
                visibility=make_reference("npc-x").visibility,
                revision=1,
                source_session_ids=("S001",),
            )

    @pytest.mark.parametrize("bad", ["bad\nid", "nul\x00id", "zero\u200bwidth"])
    def test_non_printable_entity_id_rejected_by_domain(self, bad: str) -> None:
        with pytest.raises(PydanticValidationError):
            CampaignEntityReference(
                entity_id=bad,
                entity_type=EntityType.NPC,
                name="Aria",
                visibility=make_reference("npc-x").visibility,
                revision=1,
                source_session_ids=("S001",),
            )

    def test_zero_width_space_is_non_printable(self) -> None:
        assert not "\u200b".isprintable()
        with pytest.raises(PydanticValidationError):
            CampaignEntityReference(
                entity_id="npc-x",
                entity_type=EntityType.NPC,
                name="a\u200bb",
                visibility=make_reference("npc-x").visibility,
                revision=1,
                source_session_ids=("S001",),
            )


# ── Markdown structure hardening ───────────────────────────────────────────

_MD_ATTACKS = (
    "# Heading",
    "## Subheading",
    "- list item",
    "1. ordered item",
    "[link](http://x)",
    "![img](http://x)",
    "*emphasis*",
    "`code`",
    "<html>",
    "| a | b |",
    "> quote",
    "~~strike~~",
    "\\escape",
    "\u0301# mixed Тайна [x](y) 😀",
)


class TestMarkdownStructure:
    @pytest.mark.parametrize("attack", _MD_ATTACKS)
    def test_name_cannot_create_structure(self, attack: str) -> None:
        text = _render(attack, entity_id="npc-a")
        lines = text.splitlines()

        headings = [line for line in lines if line.startswith("#")]
        assert headings == ["# Recently Touched"]

        list_lines = [line for line in lines if line.startswith("- ")]
        assert len(list_lines) == 1
        assert list_lines[0].startswith("- **")

        # No attacker-controlled quote/table block structure.
        assert not any(line.startswith("> ") for line in lines)
        assert not any(line.startswith("|") for line in lines)

    @pytest.mark.parametrize("attack", _MD_ATTACKS)
    def test_entity_id_cannot_create_structure(self, attack: str) -> None:
        text = _render("Aria", entity_id=attack)
        lines = text.splitlines()
        assert [line for line in lines if line.startswith("#")] == ["# Recently Touched"]
        list_lines = [line for line in lines if line.startswith("- ")]
        assert len(list_lines) == 1

    def test_escaped_forms_present_for_structural_metacharacters(self) -> None:
        text = _render("# Head *em* [x](y) <html> `c`")
        assert r"\# Head" in text
        assert r"\*em\*" in text
        assert r"\[x\]\(y\)" in text
        assert r"\<html\>" in text
        assert r"\`c\`" in text

    def test_escape_inline_is_idempotent_for_plain_text(self) -> None:
        assert escape_inline("Магистр Варос 😀") == "Магистр Варос 😀"


# ── Fast-Agent byte budget with non-BMP ────────────────────────────────────


class TestFastAgentUnicodeBudget:
    def _memory(self, *names: str):
        refs = tuple(
            PlayerCampaignEntityReference(
                entity_id=f"npc-{index}", entity_type=EntityType.NPC, name=name
            )
            for index, name in enumerate(names)
        )
        memory = _read_campaign_memory(_FakeProvider(refs))
        assert memory is not None
        return memory

    def test_budget_counts_emoji_utf8_bytes(self) -> None:
        emoji = "😀"  # 4 UTF-8 bytes
        assert len(emoji.encode("utf-8")) == 4
        # Two entries whose ids add 4 bytes each would exceed the 2048 budget for
        # the second entry; the first fits.
        memory = self._memory(emoji * 500, emoji * 500)
        assert len(memory.recently_touched) == 1
        assert memory.total_recently_touched == 2
        assert memory.truncated is True
        assert memory.recently_touched[0].name == emoji * 500

    def test_non_bmp_name_never_partially_included(self) -> None:
        emoji = "😀"
        huge = emoji * ((MAX_AGENT_CAMPAIGN_MEMORY_TEXT_BYTES // 4) + 1)
        memory = self._memory(huge)
        assert memory.recently_touched == ()
        assert memory.total_recently_touched == 1
        assert memory.truncated is True
