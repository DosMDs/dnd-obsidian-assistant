"""S13-03 bootstrap mapping orchestration tests."""

from __future__ import annotations

import builtins

import pytest

from dnd_assistant.application.bootstrap_changeset import BootstrapUnresolvedReason
from dnd_assistant.application.bootstrap_extraction import (
    BootstrapExtractionError,
    BootstrapExtractionFailureReason,
)
from dnd_assistant.application.bootstrap_input import MAX_BOOTSTRAP_CONTEXT_CHARS, source_ref
from dnd_assistant.application.bootstrap_mapping import (
    BootstrapModelIdentity,
    run_bootstrap_mapping,
)
from dnd_assistant.application.vault_discovery import SourceClass
from dnd_assistant.composition.bootstrap import canonical_candidates_from_report
from dnd_assistant.domain.bootstrap_extraction import (
    BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
    BootstrapExtraction,
)
from dnd_assistant.domain.types import EntityType
from tests.unit.bootstrap.helpers import (
    FakeBootstrapModel,
    canonical_text,
    make_candidate,
    make_report,
    make_source,
)

_CAMP = "camp-1"
_REF = source_ref(_CAMP, "Characters/NPCs/varos.md")


def _report():
    return make_report(
        _CAMP,
        [
            make_source(
                "Characters/NPCs/varos.md",
                SourceClass.ENTITY_CANDIDATE,
                canonical_text("npc-1", EntityType.NPC, "Варос"),
            ),
            make_source("Characters/NPCs/old.md", SourceClass.ENTITY_CANDIDATE, "loose note"),
            make_source(
                "Notes/huge.md",
                SourceClass.USER_SOURCE,
                "x" * (MAX_BOOTSTRAP_CONTEXT_CHARS + 1),
            ),
        ],
    )


def _extraction():
    return BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(make_candidate("c1", "Новый NPC", EntityType.NPC, [_REF]),),
    )


def test_mapping_does_not_read_the_filesystem_after_report(monkeypatch) -> None:
    read_calls: list[object] = []

    def guard(*args, **kwargs):  # type: ignore[no-untyped-def]
        read_calls.append(args)
        raise AssertionError("S13-03 must not read the filesystem after receiving the report")

    monkeypatch.setattr(builtins, "open", guard)
    report = _report()
    candidates = canonical_candidates_from_report(report)
    run = run_bootstrap_mapping(report, candidates, FakeBootstrapModel(_extraction()))
    assert read_calls == []
    assert run.result.changeset is not None
    assert run.model_identity == BootstrapModelIdentity()


def test_run_level_unresolved_reports_skips_conflicts_and_non_canonical() -> None:
    report = _report()
    candidates = canonical_candidates_from_report(report)
    run = run_bootstrap_mapping(report, candidates, FakeBootstrapModel(_extraction()))
    reasons = {item.reason for item in run.result.unresolved}
    assert BootstrapUnresolvedReason.SOURCE_SKIPPED in reasons
    assert BootstrapUnresolvedReason.NON_CANONICAL_SOURCE in reasons


def test_model_failure_fails_closed() -> None:
    report = _report()
    error = BootstrapExtractionError(
        BootstrapExtractionFailureReason.MODEL_TIMEOUT,
        "timeout",
    )
    with pytest.raises(BootstrapExtractionError):
        run_bootstrap_mapping(
            report,
            canonical_candidates_from_report(report),
            FakeBootstrapModel(error=error),
        )


def test_default_run_is_no_changes_without_proposal() -> None:
    report = _report()
    run = run_bootstrap_mapping(
        report,
        canonical_candidates_from_report(report),
        FakeBootstrapModel(),
    )
    assert run.result.changeset is None
    assert run.result.outcome.value == "no_changes"
