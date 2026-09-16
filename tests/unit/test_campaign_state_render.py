"""S12-03 Campaign State deterministic rendering / manifest format tests.

Covers byte determinism, LF-only newline policy, generic (non-Gregorian) game
date rendering, player-only visibility in the human-readable ``State/*.md``
artifacts, Markdown metacharacter escaping, and manifest build/serialize/parse.
Pure: no filesystem I/O.
"""

from __future__ import annotations

import pytest

from dnd_assistant.application.campaign_state_render import (
    ARTIFACT_ORDER,
    CAMPAIGN_STATE_RENDER_VERSION,
    LOGICAL_ARTIFACT_PATHS,
    CampaignStateManifestError,
    CampaignStateManifestOutdatedError,
    artifact_content_hash,
    build_manifest,
    escape_inline,
    parse_manifest,
    render_campaign_state_artifacts,
    render_game_date,
    serialize_manifest,
)
from dnd_assistant.domain.calendar import GameDate
from dnd_assistant.domain.campaign_state import CampaignStateArtifact
from dnd_assistant.domain.types import Visibility
from tests.unit.campaign_state.helpers import make_reference, make_state

_FP = "a" * 64


def _artifacts(state):
    return render_campaign_state_artifacts(state)


def _joined(state) -> str:
    texts = _artifacts(state)
    return "\n".join(texts[artifact] for artifact in ARTIFACT_ORDER)


# ── World State ───────────────────────────────────────────────────────────


class TestWorldState:
    def test_contains_tick_and_fingerprint(self) -> None:
        text = _artifacts(make_state(_FP, tick=150))[CampaignStateArtifact.WORLD_STATE]
        assert "- Current world tick: 150" in text
        assert f"- Generation fingerprint: {_FP}" in text

    def test_game_date_omitted_when_absent(self) -> None:
        text = _artifacts(make_state(_FP))[CampaignStateArtifact.WORLD_STATE]
        assert "Current game date" not in text

    def test_regular_generic_date_rendered(self) -> None:
        date = GameDate(year=1492, month="Первый Туман", day=4, hour=7, minute=9)
        text = _artifacts(make_state(_FP, game_date=date))[CampaignStateArtifact.WORLD_STATE]
        assert "Current game date: year=1492, month=Первый Туман, day=4, hour=7, minute=9" in text

    def test_intercalary_date_rendered(self) -> None:
        date = GameDate(year=1492, intercalary_day="Midwinter", hour=12, minute=30)
        text = _artifacts(make_state(_FP, game_date=date))[CampaignStateArtifact.WORLD_STATE]
        assert "Current game date: year=1492, intercalary_day=Midwinter, hour=12, minute=30" in text

    def test_no_gregorian_assumptions(self) -> None:
        date = GameDate(year=3, month="Флора", day=2)
        assert render_game_date(date) == "year=3, month=Флора, day=2, hour=0, minute=0"


# ── Recently Touched ──────────────────────────────────────────────────────


class TestRecentlyTouched:
    def test_empty_state_line(self) -> None:
        text = _artifacts(make_state(_FP))[CampaignStateArtifact.RECENTLY_TOUCHED]
        assert "_No player-visible entities were touched in the selected sessions._" in text

    def test_player_reference_rendered(self) -> None:
        ref = make_reference("npc-aria", name="Aria", source_session_ids=("S001", "S002"))
        text = _artifacts(make_state(_FP, references=(ref,)))[
            CampaignStateArtifact.RECENTLY_TOUCHED
        ]
        assert "**Aria**" in text
        assert "(npc-aria, npc, visibility: player, revision: 1)" in text
        assert "— sessions: S001, S002" in text

    def test_dm_system_absent_from_rendered_bytes(self) -> None:
        refs = (
            make_reference("npc-player", name="Aria", visibility=Visibility.PLAYER),
            make_reference("npc-dm", name="Тайный Лорд", visibility=Visibility.DM),
            make_reference("npc-sys", name="Система", visibility=Visibility.SYSTEM),
        )
        text = _artifacts(make_state(_FP, references=refs))[CampaignStateArtifact.RECENTLY_TOUCHED]
        assert "Aria" in text
        for leaked in ("npc-dm", "Тайный Лорд", "npc-sys", "Система"):
            assert leaked not in text

    def test_cyrillic_preserved(self) -> None:
        ref = make_reference("npc-varos", name="Магистр Варос")
        text = _artifacts(make_state(_FP, references=(ref,)))[
            CampaignStateArtifact.RECENTLY_TOUCHED
        ]
        assert "Магистр Варос" in text

    def test_markdown_metacharacters_escaped(self) -> None:
        ref = make_reference("npc`tick", name="*bold* _under_ [link]")
        text = _artifacts(make_state(_FP, references=(ref,)))[
            CampaignStateArtifact.RECENTLY_TOUCHED
        ]
        assert r"\*bold\*" in text
        assert r"\_under\_" in text
        assert r"\[link\]" in text
        assert "*bold*" not in text
        assert "npc`tick" not in text
        assert "npc\\`tick" in text

    def test_entity_id_inline_context_metacharacters(self) -> None:
        raw_id = "`*[]\\"
        ref = make_reference(raw_id, name="Магистр Варос")
        text = _artifacts(make_state(_FP, references=(ref,)))[
            CampaignStateArtifact.RECENTLY_TOUCHED
        ]
        ref_lines = [line for line in text.splitlines() if line.startswith("- **")]
        assert len(ref_lines) == 1
        line = ref_lines[0]
        # Fixed list structure: bold name, then the metadata group and provenance.
        assert line.startswith("- **Магистр Варос** (")
        assert line.endswith("— sessions: S001")
        # The id is ordinary escaped inline text; the raw metacharacter run must
        # not survive unescaped (which is what a backtick code span would fail
        # to guarantee).
        assert escape_inline(raw_id) in line
        assert raw_id not in line

    def test_cyrillic_entity_id_preserved(self) -> None:
        ref = make_reference("npc-варос", name="Магистр")
        text = _artifacts(make_state(_FP, references=(ref,)))[
            CampaignStateArtifact.RECENTLY_TOUCHED
        ]
        assert "npc-варос" in text

    def test_no_unsupported_semantics(self) -> None:
        text = _joined(make_state(_FP))
        for forbidden in ("Active Quest", "Current Location", "Important NPC", "deadline"):
            assert forbidden not in text


# ── Determinism / newline policy ──────────────────────────────────────────


class TestDeterminism:
    def test_deterministic_bytes(self) -> None:
        refs = (make_reference("npc-aria"),)
        first = render_campaign_state_artifacts(make_state(_FP, references=refs))
        second = render_campaign_state_artifacts(make_state(_FP, references=refs))
        assert first == second

    def test_lf_only_and_single_trailing_newline(self) -> None:
        texts = _artifacts(make_state(_FP, references=(make_reference("npc-aria"),)))
        for text in texts.values():
            assert "\r" not in text
            assert text.endswith("\n")
            assert not text.endswith("\n\n")

    def test_exact_artifact_set(self) -> None:
        assert set(_artifacts(make_state(_FP))) == set(ARTIFACT_ORDER)
        assert set(LOGICAL_ARTIFACT_PATHS) == set(ARTIFACT_ORDER)


# ── Escaping ──────────────────────────────────────────────────────────────


class TestEscapeInline:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("plain", "plain"),
            ("Магистр", "Магистр"),
            ("*x*", r"\*x\*"),
            ("a_b", r"a\_b"),
            ("[x]", r"\[x\]"),
            ("`x`", r"\`x\`"),
            ("a\rb", r"a\rb"),
            ("a\nb", r"a\nb"),
        ],
    )
    def test_escape_rules(self, raw: str, expected: str) -> None:
        assert escape_inline(raw) == expected


# ── Manifest ──────────────────────────────────────────────────────────────


class TestManifest:
    def test_build_manifest_inventory_and_hashes(self) -> None:
        state = make_state(_FP)
        texts = _artifacts(state)
        manifest = build_manifest(state, texts)
        assert manifest.render_version == CAMPAIGN_STATE_RENDER_VERSION
        assert manifest.input_fingerprint == state.input_fingerprint
        assert {a.relative_path for a in manifest.artifacts} == {
            LOGICAL_ARTIFACT_PATHS[artifact] for artifact in ARTIFACT_ORDER
        }
        for artifact in manifest.artifacts:
            artifact_id = next(
                a for a in ARTIFACT_ORDER if LOGICAL_ARTIFACT_PATHS[a] == artifact.relative_path
            )
            assert artifact.content_hash == artifact_content_hash(texts[artifact_id])

    def test_serialize_parse_roundtrip(self) -> None:
        manifest = build_manifest(make_state(_FP), _artifacts(make_state(_FP)))
        text = serialize_manifest(manifest)
        assert text.endswith("\n") and "\r" not in text
        assert parse_manifest(text) == manifest

    def test_parse_malformed_raises(self) -> None:
        with pytest.raises(CampaignStateManifestError):
            parse_manifest("{not json")

    def test_parse_non_object_raises(self) -> None:
        with pytest.raises(CampaignStateManifestError):
            parse_manifest("[]")

    def test_parse_outdated_schema_raises(self) -> None:
        manifest = build_manifest(make_state(_FP), _artifacts(make_state(_FP)))
        text = serialize_manifest(manifest).replace('"schema_version":2', '"schema_version":1', 1)
        with pytest.raises(CampaignStateManifestOutdatedError):
            parse_manifest(text)

    def test_build_manifest_missing_artifact_raises(self) -> None:
        state = make_state(_FP)
        texts = _artifacts(state)
        texts.pop(CampaignStateArtifact.WORLD_STATE)
        with pytest.raises(CampaignStateManifestError):
            build_manifest(state, texts)
