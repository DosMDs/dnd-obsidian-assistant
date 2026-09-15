"""S11-05 shared exact-matching helper and retrieval delegation regression."""

from __future__ import annotations

from dnd_assistant.retrieval import search as search_module
from dnd_assistant.retrieval.exact_matching import (
    extract_exact_aliases,
    normalize_exact_text,
)
from tests.unit.post_session.changeset_helpers import make_document


def test_normalize_exact_text_applies_strip_nfc_casefold() -> None:
    assert normalize_exact_text("  ARIA  ") == "aria"
    # NFD "A" + combining diaeresis normalizes to NFC "Ä" then casefolds.
    assert normalize_exact_text("A\u0308rger") == "\u00e4rger"


def test_extract_exact_aliases_fail_closed_grammar() -> None:
    assert extract_exact_aliases(None) == ()
    assert extract_exact_aliases("scalar") == ()
    assert extract_exact_aliases({"a": "b"}) == ()
    assert extract_exact_aliases(["Aria", "  Aria  ", "", "  ", 5, "\n"]) == ("Aria",)
    assert extract_exact_aliases(("One", "Two")) == ("One", "Two")


def test_search_normalize_text_delegates_to_shared_helper() -> None:
    for value in ("Aria", "  ARIA  ", "A\u0308rger", "Mixed Case Name"):
        assert search_module._normalize_text(value) == normalize_exact_text(value)


def test_search_extract_aliases_delegates_to_shared_helper() -> None:
    document = make_document(
        "npc-aria", name="Aria", aliases=["Лорд Ария", "Лорд Ария", "  Lord Aria  "]
    )
    assert search_module._extract_aliases(document) == list(
        extract_exact_aliases(document.extra_frontmatter.get("aliases"))
    )
    assert search_module._extract_aliases(document) == ["Лорд Ария", "Lord Aria"]


def test_search_extract_aliases_malformed_document_returns_empty() -> None:
    document = make_document("npc-aria", name="Aria")
    assert search_module._extract_aliases(document) == []
