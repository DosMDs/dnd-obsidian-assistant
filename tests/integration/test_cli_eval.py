"""Integration tests: `dnd eval` CLI (S14-06).

All offline: scripted mode needs no Vault, no config and no Ollama.
"""

from __future__ import annotations

import json
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
    assert "Latency первого model request:" in result.output
    assert "Latency полного turn:" in result.output


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
    result = _run(tmp_path, "--runtime", "bogus")
    assert result.exit_code == 2


def test_ollama_requires_config_and_profile(tmp_path: Path) -> None:
    result = _run(tmp_path, "--runtime", "ollama")
    assert result.exit_code == 2
    assert "config" in result.output.lower() or "--config" in result.output


def test_scripted_rejects_live_only_options(tmp_path: Path) -> None:
    result = _run(tmp_path, "--runtime", "scripted", "--profile", "agent")
    assert result.exit_code == 2


def test_ollama_live_preflight_failure_is_exit_1(tmp_path: Path, monkeypatch: Any) -> None:
    from dnd_assistant.composition.eval_ollama import EvalLiveError

    def _fail(*_args: Any, **_kwargs: Any) -> Any:
        raise EvalLiveError("endpoint not reachable")

    monkeypatch.setattr("dnd_assistant.composition.eval_ollama.run_live_eval", _fail)
    config = tmp_path / "models.toml"
    config.write_text(
        "[profiles.agent]\n"
        'provider = "ollama"\n'
        'model = "m"\n'
        'base_url = "http://localhost:11434"\n'
        'role = "agent"\n',
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "eval",
            "run",
            "--runtime",
            "ollama",
            "--config",
            str(config),
            "--profile",
            "agent",
            "--output",
            str(tmp_path / "report.json"),
        ],
    )
    assert result.exit_code == 1
    assert "live" in result.output.lower()


def test_unknown_dataset_is_usage_error(tmp_path: Path) -> None:
    result = _run(tmp_path, "--dataset", "nope")
    assert result.exit_code == 2


def _read_trace(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_scripted_run_with_trace_writes_incremental_jsonl(tmp_path: Path) -> None:
    trace = tmp_path / "run.eval-trace.jsonl"
    result = _run(tmp_path, "--trace", str(trace))
    assert result.exit_code == 0, result.output

    events = [entry["event"] for entry in _read_trace(trace)]
    for required in (
        "trace_started",
        "measurement_started",
        "sample_started",
        "request_started",
        "request_completed",
        "sample_completed",
        "measurement_completed",
        "report_written",
    ):
        assert required in events
    assert events[0] == "trace_started"
    assert events[-1] == "report_written"

    entries = _read_trace(trace)
    started = [e for e in entries if e["event"] == "request_started"]
    completed = [e for e in entries if e["event"] == "request_completed"]
    assert len(started) == len(completed)
    assert {e["request_index"] for e in started} == {e["request_index"] for e in completed}


def test_scripted_run_without_trace_creates_no_trace_file(tmp_path: Path) -> None:
    assert _run(tmp_path).exit_code == 0
    assert list(tmp_path.glob("*.jsonl")) == []


def test_trace_open_failure_aborts_before_any_run(tmp_path: Path, monkeypatch: Any) -> None:
    from dnd_assistant.evals.dataset import EvalDataset

    calls: list[EvalDataset] = []

    def _spy(*_args: Any, **_kwargs: Any) -> Any:
        calls.append(_args[0])
        raise AssertionError("run_eval must not be called when trace open fails")

    monkeypatch.setattr("dnd_assistant.cli.eval.run_eval", _spy)
    missing = tmp_path / "missing" / "trace.jsonl"
    result = _run(tmp_path, "--trace", str(missing))
    assert result.exit_code == 1
    assert "трассировк" in result.output.lower()
    assert calls == []
    assert not (tmp_path / "report.json").exists()


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

    failing = run_dataset(
        dataset,
        model_factory=_factory,
        runtime_mode="scripted",
        runtime_label="scripted-oracle",
        require_oracle_consistency=True,
    )
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
