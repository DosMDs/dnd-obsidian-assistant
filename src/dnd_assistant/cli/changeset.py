"""S10-05 CLI ChangeSet review/apply workflow.

This module owns only CLI presentation and runtime composition for the
``dnd changeset`` command group.  It does not own domain validation,
preflight, fingerprint matching, apply orchestration or persistence policy:

- proposal/approval persistence flows through
  ``application.changeset_store`` and the ``ChangeSetStore`` protocol;
- review is built by ``application.changeset_review``;
- apply is delegated to ``application.changeset_apply`` (approval gate, fresh
  preflight, revision checks, ``EntityPatch`` mapping and repository mutations);
- all user-facing text is Russian.

It must never call ``create_entity`` / ``patch_entity`` / ``append_entity_fact``,
construct ``EntityPatch``, manipulate entity Markdown, or write Vault
proposal/approval artifacts directly.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import typer
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.application.changeset_apply import (
    ChangeSetApplyContext,
    ChangeSetApplyOutcome,
    ChangeSetApplyResult,
    apply_changeset,
)
from dnd_assistant.application.changeset_review import (
    ChangeSetApproval,
    ChangeSetFingerprint,
    ChangeSetReview,
    ReviewDecision,
    build_changeset_review,
)
from dnd_assistant.application.changeset_store import (
    ApprovalPersistOutcome,
    ProposalPersistOutcome,
    load_approval,
    load_proposal,
    parse_changeset_document,
    persist_approval,
    persist_proposal,
)
from dnd_assistant.cli.session import _now_utc, _recovery_preflight
from dnd_assistant.domain.changeset import (
    AppendFactOperation,
    CreateEntityOperation,
    UpdateEntityOperation,
)
from dnd_assistant.errors import DndAssistantError, ValidationError
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.changeset_store import ObsidianChangeSetStore
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository

# ── Composition ────────────────────────────────────────────────────────────


def _compose_store(vault_root: Path) -> ObsidianChangeSetStore:
    """Compose the Vault-backed ChangeSet artifact store."""
    return ObsidianChangeSetStore(vault_root)


def _compose_repository(vault_root: Path) -> ObsidianVaultRepository:
    """Compose the read/apply Vault entity repository."""
    audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    audit_service = AuditService(str(audit_log_path))
    return ObsidianVaultRepository(vault_root=str(vault_root), audit_service=audit_service)


# ── Formatting helpers ─────────────────────────────────────────────────────

_UPDATE_FIELD_ORDER: tuple[str, ...] = (
    "name",
    "status",
    "visibility",
    "knowledge_status",
    "created_session",
    "last_seen_session",
    "tags",
)


def _format_value(value: object) -> str:
    """Format a domain scalar for Russian review text."""
    if value is None:
        return "—"
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return ", ".join(str(item) for item in value) if value else "—"
    return str(value)


def _format_indices(indices: tuple[int, ...]) -> str:
    """Format an ordered index tuple, or an em-dash when empty."""
    return ", ".join(str(index) for index in indices) if indices else "—"


def _render_operation(operation: object) -> list[str]:
    """Render one typed change operation as Russian review lines."""
    lines: list[str] = []
    if isinstance(operation, CreateEntityOperation):
        lines.append(f"    Тип: {_format_value(operation.type)}")
        lines.append(f"    Имя: {operation.name}")
        lines.append(f"    Статус: {_format_value(operation.status)}")
        lines.append(f"    Видимость: {_format_value(operation.visibility)}")
        lines.append(f"    Знание: {_format_value(operation.knowledge_status)}")
        lines.append(f"    Сессия создания: {_format_value(operation.created_session)}")
        lines.append(f"    Последняя сессия: {_format_value(operation.last_seen_session)}")
        lines.append(f"    Теги: {_format_value(operation.tags)}")
    elif isinstance(operation, UpdateEntityOperation):
        lines.append(f"    Ожидаемая ревизия: {operation.expected_revision}")
        lines.append("    Предлагаемые значения:")
        update = operation.update
        for field_name in _UPDATE_FIELD_ORDER:
            if field_name in update.model_fields_set:
                lines.append(f"      {field_name}: {_format_value(getattr(update, field_name))}")
    elif isinstance(operation, AppendFactOperation):
        lines.append(f"    Ожидаемая ревизия: {operation.expected_revision}")
        lines.append(f"    Факт: {operation.fact}")
    return lines


def _render_review(review: ChangeSetReview) -> str:
    """Render a ChangeSet review in Russian, without implying approval."""
    provenance = review.provenance
    lines = [
        f"Обзор ChangeSet {review.changeset_id}",
        f"  Отпечаток: {review.fingerprint.algorithm}:{review.fingerprint.digest}",
        f"  Происхождение: {provenance.provenance.value}",
    ]
    if provenance.model_profile is not None:
        lines.append(f"  Профиль модели: {provenance.model_profile}")
    if provenance.prompt_version is not None:
        lines.append(f"  Версия промпта: {provenance.prompt_version}")
    session_ref = review.session_ref if review.session_ref is not None else "—"
    lines.append(f"  Сессия: {session_ref}")
    lines.append(f"  Операций: {len(review.items)}")
    lines.append("")
    lines.append("Операции:")
    for item in review.items:
        lines.append(f"  #{item.operation_index} — {item.kind}")
        lines.append(f"    Сущность: {item.entity_id}")
        lines.extend(_render_operation(item.operation))
    return "\n".join(lines)


def _make_approval(
    changeset_id: str,
    fingerprint: ChangeSetFingerprint,
    decision: ReviewDecision,
    reviewer: str,
    reason: str | None,
) -> ChangeSetApproval:
    """Construct an approval, translating DTO validation to a project error."""
    try:
        return ChangeSetApproval(
            changeset_id=changeset_id,
            fingerprint=fingerprint,
            decision=decision,
            reviewer=reviewer,
            reason=reason,
        )
    except PydanticValidationError as exc:
        raise ValidationError(f"Недопустимое решение о проверке: {exc}") from exc


def _render_decision(
    verb: str,
    approval: ChangeSetApproval,
    outcome: ApprovalPersistOutcome,
) -> None:
    """Render an approve/reject result in Russian."""
    lines = [
        f"ChangeSet {approval.changeset_id} {verb}.",
        f"  Отпечаток: {approval.fingerprint.algorithm}:{approval.fingerprint.digest}",
        f"  Проверяющий: {approval.reviewer}",
    ]
    if approval.reason is not None:
        lines.append(f"  Причина: {approval.reason}")
    if outcome is ApprovalPersistOutcome.ALREADY_PRESENT:
        lines.append("  Решение уже зафиксировано ранее.")
    typer.echo("\n".join(lines))


def _render_apply_result(result: ChangeSetApplyResult) -> str:
    """Render an apply result truthfully as Russian APPLIED/FAILED/PARTIAL."""
    if result.outcome is ChangeSetApplyOutcome.APPLIED:
        return (
            f"ChangeSet {result.changeset_id} применён.\n"
            f"  Применено операций: {len(result.applied_operation_indices)}\n"
            f"  Индексы: {_format_indices(result.applied_operation_indices)}"
        )

    failure = result.failure
    if failure is None:
        return f"ChangeSet {result.changeset_id}: результат {result.outcome.value} без деталей."

    failed_lines = [
        f"  Неудачная операция: #{failure.operation_index}",
        f"  Категория: {failure.category.value}",
        f"  Сообщение: {failure.message}",
        f"  Оставшиеся операции: {_format_indices(result.remaining_operation_indices)}",
    ]

    if result.outcome is ChangeSetApplyOutcome.FAILED:
        return "\n".join(
            [
                f"ChangeSet {result.changeset_id} не применён: ни одна операция не выполнена.",
                *failed_lines,
            ]
        )

    return "\n".join(
        [
            f"Внимание: ChangeSet {result.changeset_id} применён частично.",
            "  Часть изменений уже записана в Vault; автоматический откат не выполнялся.",
            f"  Применённые операции: {_format_indices(result.applied_operation_indices)}",
            *failed_lines,
        ]
    )


# ── ChangeSet Typer subgroup ───────────────────────────────────────────────

changeset_app = typer.Typer(
    name="changeset",
    help="Управление предложениями изменений (ChangeSet).",
)


@changeset_app.command("save")
def _changeset_save(
    file: Path = typer.Argument(  # noqa: B008
        ...,
        help="Путь к JSON-файлу с предложением ChangeSet.",
        exists=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
    ),
    vault: Path = typer.Option(  # noqa: B008
        ...,
        "--vault",
        help="Путь к корню Obsidian Vault.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
    ),
) -> None:
    """Сохранить предложение ChangeSet в Vault."""
    vault_root = vault.resolve(strict=False)

    try:
        _recovery_preflight(vault_root)
        changeset = parse_changeset_document(file.read_text(encoding="utf-8"))
        store = _compose_store(vault_root)
        outcome = persist_proposal(store, changeset)

        if outcome is ProposalPersistOutcome.CREATED:
            typer.echo(
                f"ChangeSet {changeset.changeset_id} сохранён.\n"
                f"  Операций: {len(changeset.operations)}"
            )
        else:
            typer.echo(f"ChangeSet {changeset.changeset_id} уже сохранён с тем же содержимым.")
    except DndAssistantError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@changeset_app.command("review")
def _changeset_review(
    changeset_id: str = typer.Argument(  # noqa: B008
        ...,
        help="Идентификатор предложения ChangeSet.",
    ),
    vault: Path = typer.Option(  # noqa: B008
        ...,
        "--vault",
        help="Путь к корню Obsidian Vault.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
    ),
) -> None:
    """Показать предложение ChangeSet для проверки человеком."""
    vault_root = vault.resolve(strict=False)

    try:
        _recovery_preflight(vault_root)
        store = _compose_store(vault_root)
        repository = _compose_repository(vault_root)
        changeset = load_proposal(store, changeset_id)
        review = build_changeset_review(changeset, repository)
        typer.echo(_render_review(review))
    except DndAssistantError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@changeset_app.command("approve")
def _changeset_approve(
    changeset_id: str = typer.Argument(  # noqa: B008
        ...,
        help="Идентификатор предложения ChangeSet.",
    ),
    vault: Path = typer.Option(  # noqa: B008
        ...,
        "--vault",
        help="Путь к корню Obsidian Vault.",
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
    """Одобрить предложение ChangeSet."""
    vault_root = vault.resolve(strict=False)

    try:
        _recovery_preflight(vault_root)
        store = _compose_store(vault_root)
        repository = _compose_repository(vault_root)
        changeset = load_proposal(store, changeset_id)
        review = build_changeset_review(changeset, repository)
        approval = _make_approval(
            changeset_id=changeset.changeset_id,
            fingerprint=review.fingerprint,
            decision=ReviewDecision.APPROVED,
            reviewer=reviewer,
            reason=reason,
        )
        outcome = persist_approval(store, approval)
        _render_decision("одобрен", approval, outcome)
    except DndAssistantError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@changeset_app.command("reject")
def _changeset_reject(
    changeset_id: str = typer.Argument(  # noqa: B008
        ...,
        help="Идентификатор предложения ChangeSet.",
    ),
    vault: Path = typer.Option(  # noqa: B008
        ...,
        "--vault",
        help="Путь к корню Obsidian Vault.",
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
    """Отклонить предложение ChangeSet."""
    vault_root = vault.resolve(strict=False)

    try:
        _recovery_preflight(vault_root)
        store = _compose_store(vault_root)
        repository = _compose_repository(vault_root)
        changeset = load_proposal(store, changeset_id)
        review = build_changeset_review(changeset, repository)
        approval = _make_approval(
            changeset_id=changeset.changeset_id,
            fingerprint=review.fingerprint,
            decision=ReviewDecision.REJECTED,
            reviewer=reviewer,
            reason=reason,
        )
        outcome = persist_approval(store, approval)
        _render_decision("отклонён", approval, outcome)
    except DndAssistantError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@changeset_app.command("apply")
def _changeset_apply(
    changeset_id: str = typer.Argument(  # noqa: B008
        ...,
        help="Идентификатор предложения ChangeSet.",
    ),
    vault: Path = typer.Option(  # noqa: B008
        ...,
        "--vault",
        help="Путь к корню Obsidian Vault.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
    ),
) -> None:
    """Применить одобренное предложение ChangeSet к Vault."""
    vault_root = vault.resolve(strict=False)

    try:
        _recovery_preflight(vault_root)
        store = _compose_store(vault_root)
        repository = _compose_repository(vault_root)
        changeset = load_proposal(store, changeset_id)
        approval = load_approval(store, changeset_id)

        if not approval.is_approved:
            typer.echo(
                f"Ошибка: ChangeSet {changeset.changeset_id} отклонён и не может быть применён.",
                err=True,
            )
            raise typer.Exit(code=1)

        context = ChangeSetApplyContext(source="cli", real_time=_now_utc())
        result = apply_changeset(changeset, approval, repository, context=context)
        typer.echo(_render_apply_result(result))

        if result.outcome is not ChangeSetApplyOutcome.APPLIED:
            raise typer.Exit(code=1)
    except DndAssistantError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc


__all__ = ["changeset_app"]
