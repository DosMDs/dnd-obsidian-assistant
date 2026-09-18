"""S13-03 bootstrap input preparation and fingerprint tests."""

from __future__ import annotations

import re

from dnd_assistant.application.bootstrap_input import (
    MAX_BOOTSTRAP_CONTEXT_CHARS,
    BootstrapSourceSkipReason,
    prepare_bootstrap_input,
    source_ref,
)
from dnd_assistant.application.vault_discovery import (
    ContentReadStatus,
    SourceClass,
)
from tests.unit.bootstrap.helpers import make_report, make_source

_SRC_RE = re.compile(r"^src_[0-9a-f]{32}$")


def _report(*sources):
    return make_report("camp-1", sources)


def test_fingerprint_is_deterministic_for_same_input() -> None:
    sources = (
        make_source("Notes/a.md", SourceClass.USER_SOURCE, "hello"),
        make_source("Characters/NPCs/b.md", SourceClass.ENTITY_CANDIDATE, "world"),
    )
    first = prepare_bootstrap_input(_report(*sources))
    second = prepare_bootstrap_input(_report(*reversed(sources)))
    assert first.input_fingerprint == second.input_fingerprint
    assert [b.batch_id for b in first.batches] == ["batch_0"]


def test_fingerprint_changes_with_content_and_path() -> None:
    base = prepare_bootstrap_input(
        _report(make_source("Notes/a.md", SourceClass.USER_SOURCE, "hello"))
    )
    changed = prepare_bootstrap_input(
        _report(make_source("Notes/a.md", SourceClass.USER_SOURCE, "hello!"))
    )
    moved = prepare_bootstrap_input(
        _report(make_source("Notes/b.md", SourceClass.USER_SOURCE, "hello"))
    )
    changed_class = prepare_bootstrap_input(
        _report(make_source("Sessions/a.md", SourceClass.SESSION_SOURCE, "hello"))
    )
    assert base.input_fingerprint != changed.input_fingerprint
    assert base.input_fingerprint != moved.input_fingerprint
    assert base.input_fingerprint != changed_class.input_fingerprint


def test_fingerprint_ignores_application_owned_artifacts() -> None:
    base = _report(
        make_source("Notes/a.md", SourceClass.USER_SOURCE, "hello"),
        make_source("Characters/NPCs/n.md", SourceClass.ENTITY_CANDIDATE, "npc"),
    )
    polluted = _report(
        make_source("Notes/a.md", SourceClass.USER_SOURCE, "hello"),
        make_source("Characters/NPCs/n.md", SourceClass.ENTITY_CANDIDATE, "npc"),
        make_source("_system/bootstrap/cs_x.mapping.json", SourceClass.APPLICATION_CONTROL, "{}"),
        make_source("_system/changesets/cs_x.proposal.json", SourceClass.APPLICATION_CONTROL, "{}"),
        make_source("_system/raw/sessions/S1/events.jsonl", SourceClass.APPLICATION_RAW, "[]"),
        make_source("State/World State.md", SourceClass.DERIVED, "derived"),
        make_source("assets/pic.png", SourceClass.UNSUPPORTED, None),
    )
    assert (
        prepare_bootstrap_input(base).input_fingerprint
        == prepare_bootstrap_input(polluted).input_fingerprint
    )
    # Ineligible artifacts never appear as sources or in batch text.
    projection = prepare_bootstrap_input(polluted)
    assert all("_system/" not in source.relative_path for source in projection.sources)
    assert all("_system/" not in batch.request_text for batch in projection.batches)


def test_rerun_after_workflow_artifacts_is_fingerprint_stable() -> None:
    report = _report(make_source("Notes/a.md", SourceClass.USER_SOURCE, "hello"))
    first = prepare_bootstrap_input(report).input_fingerprint
    # Simulate rediscovery after persisting workflow artifacts.
    rediscovered = _report(
        make_source("Notes/a.md", SourceClass.USER_SOURCE, "hello"),
        make_source(
            "_system/bootstrap/cs_bootstrap_abc.mapping.json", SourceClass.APPLICATION_CONTROL, "{}"
        ),
        make_source(
            "_system/changesets/cs_bootstrap_abc.proposal.json",
            SourceClass.APPLICATION_CONTROL,
            "{}",
        ),
    )
    assert prepare_bootstrap_input(rediscovered).input_fingerprint == first


def test_source_ref_is_at_least_128_bits() -> None:
    ref = source_ref("camp-1", "Notes/a.md")
    assert _SRC_RE.match(ref)
    assert len(ref) == len("src_") + 32
    assert source_ref("camp-1", "Notes/a.md") == ref
    assert source_ref("camp-2", "Notes/a.md") != ref


def test_oversize_source_is_skipped_not_split() -> None:
    big = "x" * (MAX_BOOTSTRAP_CONTEXT_CHARS + 1)
    projection = prepare_bootstrap_input(
        _report(make_source("Notes/big.md", SourceClass.USER_SOURCE, big))
    )
    assert projection.batches == ()
    assert projection.sources[0].skip_reason is BootstrapSourceSkipReason.TOO_LARGE
    assert projection.sources[0].included is False


def test_unreadable_source_is_recorded_without_batch_text() -> None:
    projection = prepare_bootstrap_input(
        _report(
            make_source(
                "Notes/bad.md",
                SourceClass.USER_SOURCE,
                None,
                content_status=ContentReadStatus.FAILED,
            )
        )
    )
    assert projection.batches == ()
    assert projection.sources[0].skip_reason is BootstrapSourceSkipReason.FAILED
    assert projection.expected_source_refs == frozenset()


def test_cyrillic_paths_and_content_are_stable() -> None:
    source = make_source("Кампания/Обзор.md", SourceClass.USER_SOURCE, "Варос и Серый Брод")
    first = prepare_bootstrap_input(_report(source))
    second = prepare_bootstrap_input(_report(source))
    assert first.input_fingerprint == second.input_fingerprint
    assert "Варос" in first.batches[0].request_text
