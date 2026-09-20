"""Integration tests: `dnd eval` CLI (S14-06).

All offline: scripted mode needs no Vault, no config and no Ollama.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from dnd_assistant.cli.main import app
from dnd_assistant.evals import report_to_json

runner = CliRunner()


def _run(tmp_path: Path, *extra: str) -> Any:
    return runner.invoke(app, ["eval", "run", "--output", str(tmp_path / "report.json"), *extra])


def test_eval_help_and_subcommand_help() -> None:
    assert runner.invoke(app, ["eval", "--help"]).exit_code == 0
    assert runner.invoke(app, ["eval", "run", "--help"]).exit_code == 0
    assert runner.invoke(app, ["eval", "report", "--help"]).exit_code == 0


def test_scripted_run_writes_report_without_vault(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.exit_code == 0, result.output
    assert (tmp_path / "report.json").is_file()
    assert "Набор данных" in result.output


def test_run_requires_explicit_output(tmp_path: Path) -> None:
    result = runner.invoke(app, ["eval", "run"])
    assert result.exit_code == 2


def test_default_no_overwrite(tmp_path: Path) -> None:
    assert _run(tmp_path).exit_code == 0
    second = _run(tmp_path)
    assert second.exit_code == 1
    assert "Ошибка записи отчёта" in second.output


def test_overwrite_succeeds(tmp_path: Path) -> None:
    assert _run(tmp_path).exit_code == 0
    assert _run(tmp_path, "--overwrite").exit_code == 0


def test_unknown_runtime_is_usage_error(tmp_path: Path) -> None:
    result = _run(tmp_path, "--runtime", "ollama")
    assert result.exit_code == 2


def test_unknown_dataset_is_usage_error(tmp_path: Path) -> None:
    result = _run(tmp_path, "--dataset", "nope")
    assert result.exit_code == 2


def test_missing_output_directory_fails(tmp_path: Path) -> None:
    missing = tmp_path / "missing" / "report.json"
    result = runner.invoke(app, ["eval", "run", "--output", str(missing)])
    assert result.exit_code == 1


def test_report_reads_written_artifact(tmp_path: Path) -> None:
    assert _run(tmp_path).exit_code == 0
    result = runner.invoke(app, ["eval", "report", "--input", str(tmp_path / "report.json")])
    assert result.exit_code == 0
    assert "Системная безопасность: PASS" in result.output


def test_malformed_report_is_operational_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    result = runner.invoke(app, ["eval", "report", "--input", str(bad)])
    assert result.exit_code == 1


def test_report_failure_gate_exit_1(tmp_path: Path) -> None:
    from dnd_assistant.composition.eval_model import (
        ModelCallRecorder,
        build_model_from_responses,
        terminal_response,
        tool_call_response,
    )
    from dnd_assistant.composition.eval_runner import run_dataset
    from dnd_assistant.evals.contracts import (
        EvalExpectation,
        EvalScenario,
        ScenarioExpectationKind,
    )
    from dnd_assistant.evals.dataset import (
        EvalCase,
        EvalDataset,
        EvalExecutionSpec,
        EvalPermission,
        EvalQualityPolicy,
        EvalSamplePlan,
        EvalSessionState,
    )

    case = EvalCase(
        scenario=EvalScenario(
            "EVAL-CLI-001",
            "Ничего не записывай?",
            EvalExpectation(ScenarioExpectationKind.RESPOND_NO_TOOL),
        ),
        execution=EvalExecutionSpec(EvalPermission.WRITE, EvalSessionState.ACTIVE),
    )
    dataset = EvalDataset(
        dataset_id="unit",
        dataset_version="1",
        cases=(case,),
        quality_policy=EvalQualityPolicy(0.0),
        sample_plan=EvalSamplePlan("single", 1),
    )

    def _factory(expectation: EvalExpectation) -> tuple[object, ModelCallRecorder]:
        del expectation
        recorder = ModelCallRecorder()
        responses = [
            tool_call_response("record_note", {"text": "лишнее"}),
            terminal_response("respond"),
        ]
        return build_model_from_responses(responses, recorder=recorder), recorder

    failing = run_dataset(dataset, model_factory=_factory)
    assert not failing.accepted
    path = tmp_path / "failing.json"
    path.write_text(report_to_json(failing), encoding="utf-8")
    result = runner.invoke(app, ["eval", "report", "--input", str(path)])
    assert result.exit_code == 1


def test_baseline_incompatibility_exit_1(tmp_path: Path) -> None:
    assert _run(tmp_path).exit_code == 0
    report_path = tmp_path / "report.json"
    payload = report_path.read_text(encoding="utf-8").replace(
        '"dataset_version": "1"', '"dataset_version": "9"'
    )
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(payload, encoding="utf-8")
    result = runner.invoke(
        app,
        ["eval", "report", "--input", str(report_path), "--baseline", str(baseline_path)],
    )
    assert result.exit_code == 1
