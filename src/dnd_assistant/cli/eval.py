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

from dnd_assistant.composition.eval_artifacts import (
    EvalArtifactError,
    read_report_text,
    write_report_atomic,
)
from dnd_assistant.composition.eval_runner import SCRIPTED_RUNTIME, run_eval
from dnd_assistant.evals import (
    EvalReport,
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
    if runtime != SCRIPTED_RUNTIME:
        raise typer.BadParameter(
            f"Неизвестный режим выполнения: {runtime!r}. Доступен: {SCRIPTED_RUNTIME!r}"
        )
    return runtime


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
        help="Режим выполнения. S14-06 поддерживает только 'scripted'.",
    ),
    dataset: str = typer.Option(
        "product-v1",
        "--dataset",
        help="Имя набора данных (например, product-v1).",
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
) -> None:
    """Запустить офлайн eval и записать отчёт."""
    resolved_runtime = _resolve_runtime(runtime)
    resolved_dataset = _resolve_dataset(dataset)

    report = run_eval(resolved_dataset, runtime=resolved_runtime)

    _echo_summary(report)

    try:
        write_report_atomic(output, report_to_json(report), overwrite=overwrite)
    except EvalArtifactError as exc:
        typer.echo(f"Ошибка записи отчёта: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Отчёт записан: {output}")

    if not report.accepted:
        typer.echo("Оценка не принята: проверьте safety/quality/полноту.", err=True)
        raise typer.Exit(code=1)


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
