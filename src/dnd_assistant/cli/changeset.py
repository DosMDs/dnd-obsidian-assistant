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
    ApplyCommitState,
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
from dnd_assistant.application.changeset_status import (
    AuditOperationState,
    ChangeSetStatus,
    assert_changeset_applicable,
    build_changeset_status,
    load_apply_attempts,
    record_apply_attempt,
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
    ChangeSet,
    CreateEntityOperation,
    UpdateEntityOperation,
)
from dnd_assistant.errors import (
    ConflictError,
    DndAssistantError,
    NotFoundError,
    StorageError,
    ValidationError,
)
from dnd_assistant.storage.audit import AuditRecord, AuditService
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


def _read_audit_records(vault_root: Path) -> list[AuditRecord]:
    """Read validated audit records through the storage service.

    The CLI never parses the audit JSONL itself: ``AuditService.read_all``
    returns validated ``AuditRecord`` values, and the application status service
    owns the correlation rules.
    """
    audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    return AuditService(str(audit_log_path)).read_all()


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


_COMMIT_STATE_LABELS: dict[ApplyCommitState, str] = {
    ApplyCommitState.COMMITTED: "зафиксировано",
    ApplyCommitState.NOT_WRITTEN: "не записано",
    ApplyCommitState.UNCONFIRMED: "не подтверждено (возможна частичная запись)",
    ApplyCommitState.NOT_ATTEMPTED: "не выполнялось",
}


def _format_commit_state(state: ApplyCommitState | None) -> str:
    """Format a failing-operation commit state for Russian output."""
    if state is None:
        return "—"
    return _COMMIT_STATE_LABELS[state]


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
        f"  Состояние записи: {_format_commit_state(result.failing_operation_commit_state)}",
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


def _render_attempt_record_failure(
    result: ChangeSetApplyResult, error: object, vault_root: Path
) -> str:
    """Render a durable apply-attempt persistence failure without claiming rollback."""
    lines = [
        "Внимание: результат применения получен, но durable-запись попытки не сохранена.",
        f"  Причина: {error}",
        "  Автоматический откат не выполнялся; повторное применение не запускалось.",
        "  Фактическое состояние можно восстановить из журнала аудита:",
        f"    dnd changeset status {result.changeset_id} --vault {vault_root}",
    ]
    if result.outcome is ChangeSetApplyOutcome.APPLIED:
        lines.append("  Все операции могли быть успешно записаны в Vault.")
    elif result.outcome is ChangeSetApplyOutcome.PARTIAL:
        lines.append("  Уже применённые операции остаются применёнными.")
    elif result.failing_operation_commit_state is ApplyCommitState.UNCONFIRMED:
        lines.append("  Неудачная операция может быть частично записана (не подтверждено).")
    return "\n".join(lines)


_OUTCOME_LABELS: dict[ChangeSetApplyOutcome, str] = {
    ChangeSetApplyOutcome.APPLIED: "применён",
    ChangeSetApplyOutcome.PARTIAL: "применён частично",
    ChangeSetApplyOutcome.FAILED: "не применён (нет подтверждённых операций)",
}

_AUDIT_STATE_LABELS: dict[AuditOperationState, str] = {
    AuditOperationState.NOT_ATTEMPTED: "не выполнялось",
    AuditOperationState.UNCONFIRMED: "не подтверждено (intent без committed)",
    AuditOperationState.COMMITTED: "зафиксировано (intent + committed)",
}

_DECISION_LABELS: dict[ReviewDecision, str] = {
    ReviewDecision.APPROVED: "одобрено",
    ReviewDecision.REJECTED: "отклонено",
}


def _render_status(
    changeset: ChangeSet,
    approval: ChangeSetApproval | None,
    status: ChangeSetStatus,
) -> str:
    """Render a truthful, read-only ChangeSet workflow status in Russian."""
    lines = [
        f"Статус ChangeSet {status.changeset_id}",
        "  Предложение: найдено",
        f"  Операций: {len(changeset.operations)}",
        f"  Отпечаток: {status.fingerprint.algorithm}:{status.fingerprint.digest}",
    ]

    if approval is None:
        lines.append("  Решение о проверке: отсутствует")
    else:
        lines.append(f"  Решение: {_DECISION_LABELS[approval.decision]}")
        lines.append(f"  Проверяющий: {approval.reviewer}")
        if approval.reason is not None:
            lines.append(f"  Причина: {approval.reason}")
        if not approval.is_approved:
            lines.append("  Привязка одобрения: решение не является одобрением")
        elif approval.matches_approved_changeset(changeset):
            lines.append("  Привязка одобрения: подтверждена")
        else:
            lines.append("  Привязка одобрения: НЕ подтверждена (идентификатор/отпечаток)")

    lines.append("")
    lines.append(f"Записей о применении: {status.attempt_count}")
    latest = status.latest_attempt
    if latest is None:
        lines.append("  Последняя попытка: отсутствует")
    else:
        lines.append(f"  Последний результат: {_OUTCOME_LABELS[latest.outcome]}")
        lines.append(f"  Источник: {latest.source}")
        lines.append(f"  Время: {latest.real_time.isoformat()}")
        lines.append(f"  Применённые операции: {_format_indices(latest.applied_operation_indices)}")
        lines.append(
            f"  Оставшиеся операции: {_format_indices(latest.remaining_operation_indices)}"
        )
        if latest.failure is not None:
            lines.append(f"  Неудачная операция: #{latest.failure.operation_index}")
            lines.append(f"  Категория: {latest.failure.category.value}")
            lines.append(f"  Сообщение: {latest.failure.message}")
            lines.append(
                f"  Состояние записи: {_format_commit_state(latest.failing_operation_commit_state)}"
            )
        if latest.outcome is not ChangeSetApplyOutcome.APPLIED:
            lines.append("  Автоматический откат не выполнялся.")

    lines.append("")
    lines.append("Аудит операций:")
    for index, state in enumerate(status.audit_states):
        lines.append(f"  #{index}: {_AUDIT_STATE_LABELS[state]}")
    if not status.audit_evidence_present:
        lines.append("  (записей аудита по этому ChangeSet не найдено)")

    lines.append("")
    if status.can_apply:
        lines.append("Повторное применение: разрешено")
    else:
        lines.append(f"Повторное применение: запрещено — {status.block_reason}")
        lines.append("Требуется ручная проверка; автоматическое возобновление не выполняется.")
    return "\n".join(lines)


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

        # S10-06 pre-apply gate: durable attempt history + correlated audit
        # evidence decide whether another apply may start.  The gate logic lives
        # in application.changeset_status; the CLI only invokes it.
        attempts = load_apply_attempts(store, changeset_id)
        audit_records = _read_audit_records(vault_root)
        assert_changeset_applicable(changeset, attempts, audit_records)

        context = ChangeSetApplyContext(source="cli", real_time=_now_utc())
        result = apply_changeset(changeset, approval, repository, context=context)
        typer.echo(_render_apply_result(result))

        # Persist the durable attempt record after a structured result.  A
        # record-persistence failure never triggers rollback or a mutation
        # retry: the apply result is already printed truthfully.
        try:
            record_apply_attempt(
                store,
                changeset,
                result,
                source=context.source,
                real_time=context.real_time,
            )
        except (StorageError, ConflictError) as exc:
            typer.echo(_render_attempt_record_failure(result, exc, vault_root), err=True)
            raise typer.Exit(code=1) from exc

        if result.outcome is not ChangeSetApplyOutcome.APPLIED:
            raise typer.Exit(code=1)
    except DndAssistantError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@changeset_app.command("status")
def _changeset_status(
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
    """Показать durable-состояние workflow ChangeSet (только чтение).

    Намеренно НЕ запускает глобальный recovery preflight: команда должна
    оставаться доступной для диагностики незавершённого состояния ChangeSet
    даже тогда, когда recovery preflight блокирует изменяющие команды.
    """
    vault_root = vault.resolve(strict=False)

    try:
        store = _compose_store(vault_root)
        changeset = load_proposal(store, changeset_id)
        try:
            approval: ChangeSetApproval | None = load_approval(store, changeset_id)
        except NotFoundError:
            approval = None
        attempts = load_apply_attempts(store, changeset_id)
        audit_records = _read_audit_records(vault_root)
        status = build_changeset_status(changeset, attempts, audit_records)
        typer.echo(_render_status(changeset, approval, status))
    except DndAssistantError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc


__all__ = ["changeset_app"]
