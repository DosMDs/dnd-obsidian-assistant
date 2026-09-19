"""S13-04 CLI presentation for ``dnd bootstrap`` review/approve/reject/apply.

This module owns only CLI presentation and lightweight approval construction for
the bootstrap review/apply workflow:

- Typer option parsing;
- invoking the bootstrap review/approval/apply composition;
- mapping typed results to Russian user-facing text;
- exit-code mapping.

It does not own discovery, binding validation, readiness policy, apply
orchestration or persistence policy, and it never calls a model or mutates the
Vault directly.  Commands are registered onto the existing ``bootstrap`` Typer
group so ``dnd bootstrap`` stays a single surface.
"""

from __future__ import annotations

from pathlib import Path

import typer
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.application.bootstrap_readiness import (
    BootstrapApplyReadiness,
    BootstrapReadinessResult,
)
from dnd_assistant.application.bootstrap_review import (
    BootstrapEvidenceIssue,
    BootstrapReviewBundle,
    BootstrapReviewState,
)
from dnd_assistant.application.changeset_apply import (
    ChangeSetApplyOutcome,
    ChangeSetApplyResult,
)
from dnd_assistant.application.changeset_review import (
    ChangeSetApproval,
    ChangeSetFingerprint,
    ReviewDecision,
    compute_changeset_fingerprint,
)
from dnd_assistant.application.changeset_store import persist_approval
from dnd_assistant.cli.session import _recovery_preflight
from dnd_assistant.composition.bootstrap_review_apply import (
    BootstrapApprovalRun,
    BootstrapReviewRun,
    compose_bootstrap_apply,
    compose_bootstrap_approval,
    compose_bootstrap_context,
    compose_bootstrap_proposal,
    compose_bootstrap_review,
)
from dnd_assistant.domain.changeset import ChangeSet
from dnd_assistant.domain.types import Provenance
from dnd_assistant.errors import (
    ConflictError,
    DndAssistantError,
    StorageError,
    ValidationError,
)

__all__ = ["register_bootstrap_review_apply_commands"]

_VAULT_HELP = "Путь к корню Obsidian Vault."
_CHANGESET_HELP = "Идентификатор bootstrap-предложения ChangeSet."

_REVIEW_STATE_LABELS: dict[BootstrapReviewState, str] = {
    BootstrapReviewState.REVIEWABLE: "доступен для обзора",
    BootstrapReviewState.STALE_SOURCE: "устарел (исходные материалы изменились)",
    BootstrapReviewState.NOT_REVIEWABLE: "недоступен для обзора",
}

_READINESS_LABELS: dict[BootstrapApplyReadiness, str] = {
    BootstrapApplyReadiness.READY: "готово",
    BootstrapApplyReadiness.NOT_APPROVED: "нет привязанного одобрения",
    BootstrapApplyReadiness.MISSING_EVIDENCE: "доказательства маппинга отсутствуют",
    BootstrapApplyReadiness.EVIDENCE_MISMATCH: "доказательства не соответствуют предложению",
    BootstrapApplyReadiness.STALE_SOURCE: "исходные материалы устарели",
    BootstrapApplyReadiness.INCOMPLETE_CANONICAL_COVERAGE: "каноническое покрытие неполно",
    BootstrapApplyReadiness.PROJECTION_INCONSISTENT: (
        "предложение несовместимо с текущим каноническим состоянием"
    ),
    BootstrapApplyReadiness.UNRESOLVED_NOT_ACKNOWLEDGED: (
        "требуется подтверждение нерешённых пунктов"
    ),
    BootstrapApplyReadiness.STRICT_REPOSITORY_NOT_READY: "строгий репозиторий Vault не готов",
    BootstrapApplyReadiness.CHANGESET_PREFLIGHT_FAILED: (
        "предварительная проверка ChangeSet не пройдена"
    ),
    BootstrapApplyReadiness.NOT_APPLICABLE: "повторное применение запрещено",
}

_OUTCOME_LABELS: dict[ChangeSetApplyOutcome, str] = {
    ChangeSetApplyOutcome.APPLIED: "применён",
    ChangeSetApplyOutcome.PARTIAL: "применён частично",
    ChangeSetApplyOutcome.FAILED: "не применён (нет подтверждённых операций)",
}

_MAX_UNRESOLVED_LINES = 20


def _render_error(exc: DndAssistantError) -> str:
    if isinstance(exc, ValidationError):
        return f"Ошибка проверки: {exc}"
    if isinstance(exc, StorageError):
        return f"Ошибка чтения данных Vault: {exc}"
    if isinstance(exc, ConflictError):
        return f"Конфликт: {exc}"
    return f"Ошибка: {exc}"


def _format_indices(indices: tuple[int, ...]) -> str:
    return ", ".join(str(index) for index in indices) if indices else "—"


def _readiness_line(readiness: BootstrapReadinessResult) -> str:
    label = _READINESS_LABELS.get(readiness.readiness, readiness.readiness.value)
    if readiness.detail:
        return f"  Готовность к применению: {label} — {readiness.detail}"
    return f"  Готовность к применению: {label}"


def _render_evidence_issues(issues: tuple[BootstrapEvidenceIssue, ...]) -> list[str]:
    if not issues:
        return []
    lines = [f"  Проблемы доказательств: {len(issues)}"]
    for issue in issues[:_MAX_UNRESOLVED_LINES]:
        link = f" (операция #{issue.operation_index})" if issue.operation_index is not None else ""
        ref = f" [{issue.source_ref}]" if issue.source_ref else ""
        lines.append(f"    - {issue.code.value}{link}{ref}: {issue.detail}")
    if len(issues) > _MAX_UNRESOLVED_LINES:
        lines.append(f"    … и ещё {len(issues) - _MAX_UNRESOLVED_LINES}")
    return lines


def _render_unresolved(bundle: BootstrapReviewBundle) -> list[str]:
    unresolved = bundle.unresolved
    lines = [f"  Нерешённых пунктов: {len(unresolved)}"]
    if not unresolved:
        return lines
    counts: dict[str, int] = {}
    for item in unresolved:
        counts[item.reason] = counts.get(item.reason, 0) + 1
    for reason, count in sorted(counts.items()):
        lines.append(f"    {reason}: {count}")
    for item in unresolved[:_MAX_UNRESOLVED_LINES]:
        lines.append(f"    - [{item.reason}] {item.detail}")
    if len(unresolved) > _MAX_UNRESOLVED_LINES:
        lines.append(f"    … и ещё {len(unresolved) - _MAX_UNRESOLVED_LINES}")
    return lines


def _render_sources(bundle: BootstrapReviewBundle) -> list[str]:
    if not bundle.sources:
        return ["  Источники: нет данных доказательств."]
    lines = [f"  Источники (доказательства): {len(bundle.sources)}"]
    previews = 0
    for source in bundle.sources:
        included = "включён" if source.included else "не включён"
        digest = source.content_sha256 or "—"
        lines.append(
            f"    {source.relative_path} [{source.source_class}, {included}, sha256:{digest}]"
        )
        if source.content_text is not None:
            previews += 1
            lines.append("      --- предпросмотр ---")
            for raw_line in source.content_text.splitlines() or [""]:
                lines.append(f"      {raw_line}")
            lines.append("      --- конец предпросмотра ---")
    if previews == 0:
        lines.append("    (содержимое источников не показано)")
    return lines


def _render_review(run: BootstrapReviewRun) -> str:
    bundle = run.bundle
    lines = [
        f"Bootstrap-обзор ChangeSet {bundle.changeset_id}",
        f"  Отпечаток: {bundle.fingerprint.algorithm}:{bundle.fingerprint.digest}",
        f"  Кампания: {bundle.projection.campaign_id}",
        f"  Происхождение: {bundle.provenance.provenance.value}",
        f"  Состояние обзора: {_REVIEW_STATE_LABELS[bundle.review_state]}",
        f"  Отпечаток входа (semantic): sha256:{bundle.projection.input_fingerprint.digest}",
    ]
    label = bundle.evidence_record.model_profile if bundle.evidence_record else None
    if bundle.evidence_record is not None:
        identity = bundle.evidence_record
        lines.append(
            f"  Модель: {identity.model_profile or '—'} "
            f"({identity.model or '—'}, {identity.provider or '—'})"
        )
        lines.append(f"  Версия промпта: {identity.prompt_version}")
    elif label:
        lines.append(f"  Модель: {label}")
    lines.append(
        f"  Каноническое покрытие: "
        f"{'полное' if bundle.coverage.complete else 'неполное'} "
        f"({len(bundle.coverage.issues)} проблем)"
    )
    lines.extend(_render_evidence_issues(bundle.evidence_issues))
    lines.append(_readiness_line(run.readiness))
    lines.append("")
    lines.extend(_render_unresolved(bundle))

    if bundle.changeset_review is not None:
        review = bundle.changeset_review
        lines.append("")
        lines.append(f"Операции: {len(review.items)}")
        for item in review.items:
            lines.append(f"  #{item.operation_index} — {item.kind}, сущность {item.entity_id}")
    else:
        inspection = bundle.proposal_inspection
        lines.append("")
        lines.append("Операции (только просмотр):")
        for index, kind in enumerate(inspection.operation_kinds):
            lines.append(f"  #{index} — {kind}, сущность {inspection.entity_ids[index]}")

    lines.append("")
    lines.extend(_render_sources(bundle))
    lines.append("")
    lines.append("  ВНИМАНИЕ: предложение НЕ применено; канонические данные не изменялись.")
    return "\n".join(lines)


def _render_approval_decision(
    changeset_id: str,
    fingerprint: str,
    verb: str,
    reviewer: str,
    reason: str | None,
) -> None:
    lines = [
        f"Bootstrap ChangeSet {changeset_id} {verb}.",
        f"  Отпечаток: {fingerprint}",
        f"  Проверяющий: {reviewer}",
    ]
    if reason is not None:
        lines.append(f"  Причина: {reason}")
    typer.echo("\n".join(lines))


def _make_approval(
    changeset: ChangeSet,
    fingerprint_digest: str,
    decision: ReviewDecision,
    reviewer: str,
    reason: str | None,
) -> ChangeSetApproval:
    try:
        return ChangeSetApproval(
            changeset_id=changeset.changeset_id,
            fingerprint=ChangeSetFingerprint(digest=fingerprint_digest),
            decision=decision,
            reviewer=reviewer,
            reason=reason,
        )
    except PydanticValidationError as exc:
        raise ValidationError(f"Недопустимое решение о проверке: {exc}") from exc


def _render_apply_result(result: ChangeSetApplyResult) -> str:
    if result.outcome is ChangeSetApplyOutcome.APPLIED:
        return (
            f"Bootstrap ChangeSet {result.changeset_id}: применён.\n"
            f"  Применено операций: {len(result.applied_operation_indices)}\n"
            f"  Индексы: {_format_indices(result.applied_operation_indices)}\n"
            "  ВАЖНО: применение ChangeSet НЕ означает завершение bootstrap Stage 13."
        )
    failure = result.failure
    if failure is None:
        return f"Bootstrap ChangeSet {result.changeset_id}: результат без деталей."
    detail = (
        f"  Неудачная операция: #{failure.operation_index}\n"
        f"  Категория: {failure.category.value}\n"
        f"  Сообщение: {failure.message}\n"
        f"  Оставшиеся операции: {_format_indices(result.remaining_operation_indices)}"
    )
    if result.outcome is ChangeSetApplyOutcome.PARTIAL:
        return (
            f"Внимание: Bootstrap ChangeSet {result.changeset_id} применён частично.\n"
            "  Часть изменений уже записана; автоматический откат не выполнялся.\n"
            f"  Применённые операции: {_format_indices(result.applied_operation_indices)}\n"
            f"{detail}"
        )
    return (
        f"Bootstrap ChangeSet {result.changeset_id} не применён: "
        "ни одна операция не подтверждена.\n" + detail
    )


# ── Commands ──────────────────────────────────────────────────────────────


def _bootstrap_review(
    changeset_id: str = typer.Argument(..., help=_CHANGESET_HELP),  # noqa: B008
    vault: Path = typer.Option(  # noqa: B008
        ...,
        "--vault",
        help=_VAULT_HELP,
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
    ),
) -> None:
    """Показать bootstrap-предложение и его доказательства для проверки человеком."""
    vault_root = vault.resolve(strict=False)
    try:
        run = compose_bootstrap_review(vault_root, changeset_id)
        typer.echo(_render_review(run))
        if run.bundle.review_state is BootstrapReviewState.NOT_REVIEWABLE:
            typer.echo(
                "Обзор невозможен: доказательства отсутствуют/не соответствуют предложению.",
                err=True,
            )
            raise typer.Exit(code=1)
    except DndAssistantError as exc:
        typer.echo(_render_error(exc), err=True)
        raise typer.Exit(code=1) from exc


def _bootstrap_approve(
    changeset_id: str = typer.Argument(..., help=_CHANGESET_HELP),  # noqa: B008
    vault: Path = typer.Option(  # noqa: B008
        ...,
        "--vault",
        help=_VAULT_HELP,
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
    ),
    reviewer: str = typer.Option(  # noqa: B008
        ...,
        "--reviewer",
        help="Идентификатор проверяющего (обязательно).",
    ),
    reason: str | None = typer.Option(  # noqa: B008
        None,
        "--reason",
        help="Необязательная причина решения.",
    ),
    acknowledge_unresolved: bool = typer.Option(  # noqa: B008
        False,
        "--acknowledge-unresolved",
        help="Подтвердить нерешённые пункты (обязательно при их наличии).",
    ),
) -> None:
    """Одобрить bootstrap-предложение при прохождении bootstrap-проверок."""
    vault_root = vault.resolve(strict=False)
    try:
        _recovery_preflight(vault_root)
        run: BootstrapApprovalRun = compose_bootstrap_approval(
            vault_root, changeset_id, acknowledge_unresolved=acknowledge_unresolved
        )
        if run.readiness.readiness is not BootstrapApplyReadiness.READY:
            typer.echo(_readiness_line(run.readiness), err=True)
            raise typer.Exit(code=1)

        fingerprint = run.bundle.fingerprint
        approval = _make_approval(
            run.bundle.changeset,
            fingerprint.digest,
            ReviewDecision.APPROVED,
            reviewer,
            reason,
        )
        context = compose_bootstrap_context(vault_root)
        persist_approval(context.changeset_store, approval)
        _render_approval_decision(
            approval.changeset_id,
            f"{approval.fingerprint.algorithm}:{approval.fingerprint.digest}",
            "одобрен",
            approval.reviewer,
            approval.reason,
        )
    except DndAssistantError as exc:
        typer.echo(_render_error(exc), err=True)
        raise typer.Exit(code=1) from exc


def _bootstrap_reject(
    changeset_id: str = typer.Argument(..., help=_CHANGESET_HELP),  # noqa: B008
    vault: Path = typer.Option(  # noqa: B008
        ...,
        "--vault",
        help=_VAULT_HELP,
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
    ),
    reviewer: str = typer.Option(  # noqa: B008
        ...,
        "--reviewer",
        help="Идентификатор проверяющего (обязательно).",
    ),
    reason: str | None = typer.Option(  # noqa: B008
        None,
        "--reason",
        help="Необязательная причина решения.",
    ),
) -> None:
    """Отклонить bootstrap-предложение, привязав решение к его содержимому.

    Отклонение не требует готовности к применению: достаточно существующего
    BOOTSTRAP-предложения, точное содержимое которого фиксируется отпечатком.
    """
    vault_root = vault.resolve(strict=False)
    try:
        _recovery_preflight(vault_root)
        changeset = compose_bootstrap_proposal(vault_root, changeset_id)
        if changeset.provenance.provenance is not Provenance.BOOTSTRAP:
            typer.echo(
                "Ошибка: это не bootstrap-предложение; используйте dnd changeset reject.",
                err=True,
            )
            raise typer.Exit(code=1)
        approval = _make_approval(
            changeset,
            _fingerprint_digest(changeset),
            ReviewDecision.REJECTED,
            reviewer,
            reason,
        )
        context = compose_bootstrap_context(vault_root)
        persist_approval(context.changeset_store, approval)
        _render_approval_decision(
            approval.changeset_id,
            f"{approval.fingerprint.algorithm}:{approval.fingerprint.digest}",
            "отклонён",
            approval.reviewer,
            approval.reason,
        )
    except DndAssistantError as exc:
        typer.echo(_render_error(exc), err=True)
        raise typer.Exit(code=1) from exc


def _fingerprint_digest(changeset: ChangeSet) -> str:
    return compute_changeset_fingerprint(changeset).digest


def _bootstrap_apply(
    changeset_id: str = typer.Argument(..., help=_CHANGESET_HELP),  # noqa: B008
    vault: Path = typer.Option(  # noqa: B008
        ...,
        "--vault",
        help=_VAULT_HELP,
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
    ),
    acknowledge_unresolved: bool = typer.Option(  # noqa: B008
        False,
        "--acknowledge-unresolved",
        help="Подтвердить нерешённые пункты (обязательно при их наличии).",
    ),
) -> None:
    """Применить bootstrap-предложение через существующий Stage-10 applier."""
    vault_root = vault.resolve(strict=False)
    try:
        _recovery_preflight(vault_root)
        result = compose_bootstrap_apply(
            vault_root, changeset_id, acknowledge_unresolved=acknowledge_unresolved
        )
        if result.apply_result is None:
            typer.echo(
                _readiness_line(
                    BootstrapReadinessResult(result.readiness, result.detail, result.issues)
                ),
                err=True,
            )
            raise typer.Exit(code=1)

        typer.echo(_render_apply_result(result.apply_result))
        if result.attempt_error is not None:
            typer.echo(
                "Внимание: durable-запись попытки применения не сохранена.\n"
                f"  Причина: {result.attempt_error}\n"
                "  Автоматический откат не выполнялся; повторное применение не запускалось.",
                err=True,
            )
            raise typer.Exit(code=1)
        if result.apply_result.outcome is not ChangeSetApplyOutcome.APPLIED:
            raise typer.Exit(code=1)
    except DndAssistantError as exc:
        typer.echo(_render_error(exc), err=True)
        raise typer.Exit(code=1) from exc


def register_bootstrap_review_apply_commands(app: typer.Typer) -> None:
    """Attach the bootstrap review/approve/reject/apply commands to ``app``."""
    app.command("review")(_bootstrap_review)
    app.command("approve")(_bootstrap_approve)
    app.command("reject")(_bootstrap_reject)
    app.command("apply")(_bootstrap_apply)
