"""S13-03 ``dnd bootstrap map`` CLI presentation tests."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from dnd_assistant.application.bootstrap_changeset import BootstrapUnresolved
from dnd_assistant.application.bootstrap_input import source_ref
from dnd_assistant.application.bootstrap_mapping import run_bootstrap_mapping
from dnd_assistant.application.vault_discovery import SourceClass
from dnd_assistant.cli.bootstrap import bootstrap_app
from dnd_assistant.composition.bootstrap import (
    BootstrapRuntimeResult,
    canonical_candidates_from_report,
)
from dnd_assistant.domain.bootstrap_extraction import (
    BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
    BootstrapExtraction,
)
from dnd_assistant.domain.types import EntityType
from tests.unit.bootstrap.helpers import (
    FakeBootstrapModel,
    make_candidate,
    make_report,
    make_source,
)

runner = CliRunner()


class _StubRuntime:
    def __init__(self, result: BootstrapRuntimeResult) -> None:
        self._result = result
        self.closed = False
        self.persist_calls: list[bool] = []

    def run(self, report, *, persist: bool = True) -> BootstrapRuntimeResult:
        self.persist_calls.append(persist)
        return self._result

    def close(self) -> None:
        self.closed = True


def _base_run():
    report = _base_run_report()
    extraction = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(
            make_candidate("c1", "Варос", EntityType.NPC, [source_ref("camp-1", "Notes/a.md")]),
        ),
    )
    return run_bootstrap_mapping(
        report, canonical_candidates_from_report(report), FakeBootstrapModel(extraction)
    )


def _no_change_run():
    report = _base_run_report()
    return run_bootstrap_mapping(
        report, canonical_candidates_from_report(report), FakeBootstrapModel()
    )


def _invoke(monkeypatch, result: BootstrapRuntimeResult, args: list[str]):
    runtime = _StubRuntime(result)
    report = _base_run_report()
    monkeypatch.setattr(
        "dnd_assistant.cli.bootstrap.compose_bootstrap_discovery", lambda root: report
    )
    monkeypatch.setattr(
        "dnd_assistant.cli.bootstrap.compose_bootstrap_runtime", lambda **kw: runtime
    )
    monkeypatch.setattr("dnd_assistant.cli.bootstrap._recovery_preflight", lambda root: None)
    invocation = runner.invoke(bootstrap_app, args)
    return invocation, runtime


def _base_run_report():
    return make_report("camp-1", [make_source("Notes/a.md", SourceClass.USER_SOURCE, "варос")])


def _args(tmp_path: Path, *extra: str) -> list[str]:
    config = tmp_path / "config.toml"
    config.write_text(
        "[profiles]\n"
        "[profiles.heavy]\n"
        'provider = "ollama"\n'
        'model = "m"\n'
        'base_url = "http://localhost:11434"\n'
        'role = "bootstrap"\n',
        encoding="utf-8",
    )
    return ["map", "--vault", str(tmp_path), "--config", str(config), "--profile", "heavy", *extra]


def test_proposal_is_not_advertised_as_reviewable_or_applied(tmp_path: Path, monkeypatch) -> None:
    result = BootstrapRuntimeResult(run=_base_run())
    invocation, runtime = _invoke(monkeypatch, result, _args(tmp_path))
    assert invocation.exit_code == 0, invocation.output
    assert "НЕ одобрено" in invocation.output
    assert "НЕ применено" in invocation.output
    assert "S13-04" in invocation.output
    assert "changeset review" not in invocation.output
    assert runtime.closed is True


def test_no_changes_without_unresolved_is_explicit(tmp_path: Path, monkeypatch) -> None:
    result = BootstrapRuntimeResult(run=_no_change_run())
    invocation, _ = _invoke(monkeypatch, result, _args(tmp_path))
    assert invocation.exit_code == 0
    assert "Нерешённых пунктов: 0" in invocation.output


def test_no_changes_with_unresolved_does_not_claim_full_import(tmp_path: Path, monkeypatch) -> None:
    from dataclasses import replace

    from dnd_assistant.application.bootstrap_changeset import (
        BootstrapMappingOutcome,
        BootstrapUnresolvedReason,
    )

    run = _base_run()
    unresolved = (
        BootstrapUnresolved(reason=BootstrapUnresolvedReason.SOURCE_SKIPPED, detail="skip"),
    )
    result = BootstrapRuntimeResult(
        run=replace(
            run,
            result=replace(
                run.result,
                outcome=BootstrapMappingOutcome.NO_CHANGES,
                changeset=None,
                changeset_fingerprint=None,
                unresolved=unresolved,
            ),
        )
    )
    invocation, _ = _invoke(monkeypatch, result, _args(tmp_path))
    assert "НЕ считается полностью импортированной" in invocation.output


def test_dry_run_persists_nothing(tmp_path: Path, monkeypatch) -> None:
    result = BootstrapRuntimeResult(run=_base_run())
    invocation, runtime = _invoke(monkeypatch, result, _args(tmp_path, "--dry-run"))
    assert invocation.exit_code == 0
    assert "НЕ сохранено" in invocation.output
    assert runtime.persist_calls == [False]
