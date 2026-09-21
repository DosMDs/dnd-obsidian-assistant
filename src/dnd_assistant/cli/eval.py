"""`dnd eval` — scriptable product eval runner (offline scripted mode).

Presentation only: dataset/runtime selection, human-readable Russian summary and
exit semantics.  All scoring, completeness, safety and report logic lives in
``dnd_assistant.evals`` / ``dnd_assistant.composition``.

S14-06 registers only the offline ``scripted`` runtime.  S14-07 extends the same
registry with a live Ollama runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import typer

from dnd_assistant.composition import eval_deepseek, eval_ollama
from dnd_assistant.composition.eval_artifacts import (
    EvalArtifactError,
    preflight_report_target,
    read_report_text,
    write_report_atomic,
)
from dnd_assistant.composition.eval_runner import SCRIPTED_RUNTIME, run_eval
from dnd_assistant.composition.eval_trace import (
    EVENT_REPORT_WRITTEN,
    TRACE_FAULT_MESSAGE,
    EvalTraceError,
    EvalTraceWriter,
    open_eval_trace,
)
from dnd_assistant.errors import DndAssistantError
from dnd_assistant.evals import (
    EvalReport,
    LatencySummary,
    compare_eval_reports,
    report_from_json,
    report_to_json,
)
from dnd_assistant.evals.dataset import EvalDataset
from dnd_assistant.evals.datasets.product_v1 import build_product_v1_dataset

eval_app = typer.Typer(
    name="eval",
    help="Запуск и просмотр детерминированных eval-отчётов продукта.",
)


_DATASETS: dict[str, Callable[[], EvalDataset]] = {
    "product-v1": build_product_v1_dataset,
}


def _resolve_dataset(alias: str) -> EvalDataset:
    builder = _DATASETS.get(alias)
    if builder is None:
        known = ", ".join(sorted(_DATASETS))
        raise typer.BadParameter(f"Неизвестный набор данных: {alias!r}. Доступны: {known}")
    return builder()


def _resolve_runtime(runtime: str) -> str:
    if runtime not in (SCRIPTED_RUNTIME, eval_ollama.LIVE_RUNTIME, eval_deepseek.LIVE_RUNTIME):
        raise typer.BadParameter(
            f"Неизвестный режим выполнения: {runtime!r}. "
            f"Доступны: {SCRIPTED_RUNTIME!r}, {eval_ollama.LIVE_RUNTIME!r}, "
            f"{eval_deepseek.LIVE_RUNTIME!r}"
        )
    return runtime


def _echo_latency_layer(summary: LatencySummary) -> None:
    for label, value in (("p50", summary.p50_seconds), ("p95", summary.p95_seconds)):
        rendered = "нет данных" if value is None else f"{value:.4f} с"
        typer.echo(f"  {label}: {rendered}, N={summary.sample_count}")


def _echo_summary(report: EvalReport) -> None:
    identity = report.identity
    contract = report.sample_contract
    quality = report.quality
    safety = report.safety

    typer.echo(f"Набор данных: {identity.dataset_id} v{identity.dataset_version}")
    typer.echo(f"Режим выполнения: {report.runtime.label}")
    typer.echo(
        "Выборки: "
        f"ожидается {contract.expected_sample_count}, "
        f"decision {contract.observed_decision_count}, "
        f"full-turn {contract.observed_full_turn_count}, "
        f"полнота: {'да' if contract.complete else 'нет'}"
    )
    for metric in report.metrics:
        value = "n/a" if metric.value is None else f"{metric.value:.4f}"
        typer.echo(f"  {metric.metric_id.value}: {value} ({metric.numerator}/{metric.denominator})")
    typer.echo(
        "Ложные WRITE-вызовы: "
        f"{quality.false_write_numerator}/{quality.false_write_denominator} "
        f"порог={quality.max_false_write_tool_call_rate}"
    )
    typer.echo(
        "Несанкционированные WRITE handler executions: "
        f"{safety.unauthorized_write_handler_execution_count}"
    )
    typer.echo(f"Системная безопасность: {'PASS' if safety.passed else 'FAIL'}")
    typer.echo(f"Качество: {'PASS' if quality.passed else 'FAIL'}")
    typer.echo("Latency первого model request:")
    _echo_latency_layer(report.latency.decision)
    typer.echo("Latency полного turn:")
    _echo_latency_layer(report.latency.full_turn)
    if report.run_validity.oracle_consistency_required:
        typer.echo(
            f"Согласованность scripted-oracle: {'PASS' if report.run_validity.oracle_consistent else 'FAIL'}"
        )
    if report.run_validity.runtime_error_count:
        typer.echo(f"Ошибки выполнения: {report.run_validity.runtime_error_count}")


@eval_app.command("run")
def _eval_run(
    runtime: str = typer.Option(
        SCRIPTED_RUNTIME,
        "--runtime",
        help="Режим выполнения: 'scripted' (офлайн), 'ollama' или 'deepseek' (явный live).",
    ),
    dataset: str = typer.Option(
        "product-v1",
        "--dataset",
        help="Имя набора данных (например, product-v1).",
    ),
    config: Path | None = typer.Option(  # noqa: B008
        None,
        "--config",
        help="Путь к machine-local TOML конфигурации (для live-режимов ollama/deepseek).",
        resolve_path=True,
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Имя AGENT-профиля модели (для live-режимов ollama/deepseek).",
    ),
    output: Path = typer.Option(  # noqa: B008
        ...,
        "--output",
        help="Путь к JSON-файлу отчёта (вне Vault).",
        resolve_path=True,
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Перезаписать существующий файл отчёта.",
    ),
    trace: Path | None = typer.Option(  # noqa: B008
        None,
        "--trace",
        help="Необязательный путь к локальному диагностическому trace (JSONL).",
        resolve_path=True,
    ),
) -> None:
    """Запустить eval и записать отчёт."""
    resolved_runtime = _resolve_runtime(runtime)
    resolved_dataset = _resolve_dataset(dataset)

    # Preflight the output target BEFORE any trace open, runtime selection,
    # credential resolution or model request.  A consumed live measurement must
    # never be lost to a foreseeable output-target failure.
    try:
        preflight_report_target(output, overwrite=overwrite)
    except EvalArtifactError as exc:
        typer.echo(f"Ошибка записи отчёта: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    # Open/validate the diagnostic trace BEFORE any warm-up or model request.
    try:
        trace_writer = open_eval_trace(trace)
    except EvalTraceError as exc:
        typer.echo(f"Ошибка диагностической трассировки: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        try:
            report = _run_selected_runtime(
                resolved_runtime,
                resolved_dataset,
                config=config,
                profile=profile,
                trace=trace_writer,
            )
        except DndAssistantError as exc:
            typer.echo(f"Ошибка live-выполнения: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        _echo_summary(report)

        try:
            write_report_atomic(output, report_to_json(report), overwrite=overwrite)
        except EvalArtifactError as exc:
            typer.echo(f"Ошибка записи отчёта: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        typer.echo(f"Отчёт записан: {output}")

        if trace_writer is not None:
            # Never invalidates or deletes an already-written frozen report.
            trace_writer.emit(EVENT_REPORT_WRITTEN)
            if trace_writer.faulted:
                typer.echo(TRACE_FAULT_MESSAGE, err=True)

        if not report.accepted:
            typer.echo("Оценка не принята: проверьте safety/quality/полноту.", err=True)
            raise typer.Exit(code=1)
    finally:
        if trace_writer is not None:
            trace_writer.close()


def _run_selected_runtime(
    runtime: str,
    dataset: EvalDataset,
    *,
    config: Path | None,
    profile: str | None,
    trace: EvalTraceWriter | None = None,
) -> EvalReport:
    """Dispatch scripted vs explicit live runtime; validate option presence."""
    if runtime == eval_ollama.LIVE_RUNTIME:
        if config is None or profile is None:
            raise typer.BadParameter("Для --runtime ollama требуются --config и --profile.")
        return eval_ollama.run_live_eval(
            dataset,
            config_path=config,
            profile_name=profile,
            trace=trace,
        )

    if runtime == eval_deepseek.LIVE_RUNTIME:
        if config is None or profile is None:
            raise typer.BadParameter("Для --runtime deepseek требуются --config и --profile.")
        return eval_deepseek.run_live_eval(
            dataset,
            config_path=config,
            profile_name=profile,
            trace=trace,
        )

    if config is not None or profile is not None:
        raise typer.BadParameter(
            "Опции --config/--profile допустимы только для live-режимов (ollama, deepseek)."
        )
    return run_eval(dataset, runtime=runtime, trace=trace)


@eval_app.command("report")
def _eval_report(
    input: Path = typer.Option(  # noqa: B008
        ...,
        "--input",
        help="Путь к JSON-файлу отчёта.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
    ),
    baseline: Path | None = typer.Option(  # noqa: B008
        None,
        "--baseline",
        help="Необязательный базовый отчёт для сравнения.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
    ),
) -> None:
    """Прочитать и показать сохранённый eval-отчёт."""
    try:
        report = report_from_json(read_report_text(input))
    except (EvalArtifactError, ValueError) as exc:
        typer.echo(f"Ошибка чтения отчёта: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    _echo_summary(report)

    if baseline is not None:
        try:
            baseline_report = report_from_json(read_report_text(baseline))
        except (EvalArtifactError, ValueError) as exc:
            typer.echo(f"Ошибка чтения базового отчёта: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        comparison = compare_eval_reports(report, baseline_report)
        if comparison.status.value != "compatible":
            typer.echo("Базовый отчёт несовместим:", err=True)
            for reason in comparison.incompatible_reasons:
                typer.echo(f"  {reason}", err=True)
            raise typer.Exit(code=1)
        typer.echo("Сравнение с базой (совместимо):")
        for delta in comparison.metric_deltas:
            typer.echo(
                f"  {delta.metric_id.value}: {delta.baseline_value} -> {delta.current_value}"
            )

    if not report.accepted:
        typer.echo("Отчёт не принят: safety/quality/полнота не пройдены.", err=True)
        raise typer.Exit(code=1)
