"""S11-07 CLI orchestration for the post-session processor.

This module owns only CLI presentation for the ``session process`` and
``session outputs`` commands:

- Typer option/argument parsing and selector presentation;
- invoking the focused POST_SESSION runtime (``cli/post_session_runtime.py``);
- mapping the typed ``PostSessionProcessorResult`` to Russian user-facing text;
- exit-code mapping;
- read-only rendering of the ``session outputs`` query.

It does NOT own eligibility, prepared-input assembly, ledger folding, attempt
claiming, entity resolution, ChangeSet construction, artifact/proposal
persistence policy, failure categorization, terminal-integrity rules, model
prompts or dependency composition.

Review/approval/apply remain exclusively ``dnd changeset ...``.  This command
never approves or applies a produced proposal.
"""

from __future__ import annotations

from pathlib import Path

import typer

from dnd_assistant.application.post_session_attempt_state import AttemptState
from dnd_assistant.application.post_session_outputs import (
    PostSessionAttemptOutput,
    PostSessionOutputsError,
    build_post_session_outputs,
)
from dnd_assistant.application.post_session_processor_support import (
    PostSessionFailureRecordingError,
    PostSessionProcessorResult,
    PostSessionProcessorStatus,
)
from dnd_assistant.cli.post_session_runtime import (
    compose_metadata_repository,
    compose_post_session_runtime,
    new_attempt_id,
    select_latest_completed_session,
)
from dnd_assistant.cli.session import _recovery_preflight
from dnd_assistant.domain.post_session import (
    FailureCategory,
    ProcessingOutcome,
    ProcessingPhase,
)
from dnd_assistant.errors import (
    ConflictError,
    DndAssistantError,
    NotFoundError,
    StorageError,
    ValidationError,
)
from dnd_assistant.storage.changeset_store import ObsidianChangeSetStore
from dnd_assistant.storage.post_session_artifacts import ObsidianPostSessionArtifactStore
from dnd_assistant.storage.post_session_processing import ObsidianPostSessionProcessingStore
from dnd_assistant.storage.session_metadata import ObsidianSessionMetadataRepository

# ── Local bounded error ────────────────────────────────────────────────────


class SessionNotFoundError(DndAssistantError):
    """Bounded, trusted session-not-found error for selector/outputs paths."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"Сессия {session_id} не найдена.")
        self.session_id = session_id


# ── Labels ─────────────────────────────────────────────────────────────────


_OUTCOME_LABELS: dict[ProcessingOutcome, str] = {
    ProcessingOutcome.PRODUCED: "предложение изменений",
    ProcessingOutcome.NO_CHANGES: "без изменений",
}

_STATE_LABELS: dict[AttemptState, str] = {
    AttemptState.NOT_STARTED: "не начата",
    AttemptState.STARTED: "начата (прервана)",
    AttemptState.COMPLETED: "завершена",
    AttemptState.FAILED: "ошибка",
    AttemptState.SUPERSEDED: "заменена",
}

_PHASE_LABELS: dict[ProcessingPhase, str] = {
    ProcessingPhase.ELIGIBILITY: "проверка допустимости",
    ProcessingPhase.INPUT_ASSEMBLY: "сборка входных данных",
    ProcessingPhase.EXTRACTION: "извлечение",
    ProcessingPhase.VALIDATION: "проверка и сборка ChangeSet",
    ProcessingPhase.RENDERING: "рендеринг",
    ProcessingPhase.PERSISTENCE: "сохранение",
}

_CATEGORY_LABELS: dict[FailureCategory, str] = {
    FailureCategory.MODEL_UNAVAILABLE: "модель недоступна",
    FailureCategory.MODEL_TIMEOUT: "таймаут модели",
    FailureCategory.INVALID_OUTPUT: "некорректный структурированный ответ",
    FailureCategory.FINGERPRINT_MISMATCH: "несовпадение отпечатка входа",
    FailureCategory.STORAGE_ERROR: "ошибка хранилища",
    FailureCategory.ARTIFACT_CONFLICT: "конфликт артефакта",
    FailureCategory.PROPOSAL_CONFLICT: "конфликт предложения",
    FailureCategory.INTERNAL_ERROR: "внутренняя ошибка",
}


# ── Rendering helpers ──────────────────────────────────────────────────────


def _render_dnd_error(exc: DndAssistantError) -> str:
    """Render a project error with a bounded, type-distinguishing prefix."""
    if isinstance(exc, NotFoundError):
        return f"Ошибка: не найдено: {exc}"
    if isinstance(exc, ValidationError):
        return f"Ошибка конфигурации или профиля: {exc}"
    if isinstance(exc, StorageError):
        return f"Ошибка чтения данных: {exc}"
    if isinstance(exc, ConflictError):
        return f"Конфликт: {exc}"
    return f"Ошибка: {exc}"


def _exit_code_for(result: PostSessionProcessorResult) -> int:
    """Stable exit-code policy for a typed processor result."""
    if result.status in (
        PostSessionProcessorStatus.COMPLETED,
        PostSessionProcessorStatus.ALREADY_TERMINAL,
    ):
        return 0
    return 1


def _render_terminal_common(result: PostSessionProcessorResult) -> list[str]:
    """Render the shared terminal-result block from the processor result."""
    return [
        f"  Попытка: {result.attempt_id}",
        f"  Итог: {_OUTCOME_LABELS.get(result.outcome, '—') if result.outcome else '—'}",
        f"  Сводка (Summary): {result.summary_path or '—'}",
        f"  Пересказ (Recap): {result.recap_path or '—'}",
        f"  Рабочие доказательства (workflow): {result.workflow_path or '—'}",
        f"  Recap пуст (детерминированно): {'да' if result.recap_was_empty else 'нет'}",
        f"  Нерешённых ссылок: {result.unresolved_count}",
    ]


def _render_proposal(result: PostSessionProcessorResult, vault_root: Path) -> list[str]:
    """Render the produced-proposal block without implying approval/apply."""
    fingerprint = result.changeset_fingerprint
    digest = f"{fingerprint.algorithm}:{fingerprint.digest}" if fingerprint else "—"
    return [
        f"  ChangeSet (предложение): {result.changeset_id}",
        f"  Отпечаток: {digest}",
        "  ВНИМАНИЕ: это ТОЛЬКО предложение; оно НЕ одобрено и НЕ применено.",
        f"  Для проверки человеком: dnd changeset review {result.changeset_id} --vault {vault_root}",
    ]


def _render_no_changes() -> list[str]:
    """Render the explicit no-proposal block."""
    return [
        "  ChangeSet не создан: допустимых изменений кампании не найдено.",
        "  Сущности кампании не изменялись.",
        "  Сводка/Пересказ/доказательства сохранены (см. пути выше).",
    ]


def _render_outcome_block(result: PostSessionProcessorResult, vault_root: Path) -> list[str]:
    if result.outcome is ProcessingOutcome.PRODUCED and result.changeset_id:
        return _render_proposal(result, vault_root)
    return _render_no_changes()


def _render_process_result(result: PostSessionProcessorResult, vault_root: Path) -> str:
    """Render any typed processor result truthfully in Russian."""
    if result.status is PostSessionProcessorStatus.COMPLETED:
        lines = [
            f"Обработка сессии {result.session_id} завершена.",
            *_render_terminal_common(result),
            *_render_outcome_block(result, vault_root),
        ]
        return "\n".join(lines)

    if result.status is PostSessionProcessorStatus.ALREADY_TERMINAL:
        lines = [
            f"Попытка {result.attempt_id} уже завершена (идемпотентный повтор).",
            "  Модель не вызывалась; новые артефакты не создавались.",
            *_render_terminal_common(result),
            *_render_outcome_block(result, vault_root),
        ]
        return "\n".join(lines)

    if result.status is PostSessionProcessorStatus.INTERRUPTED:
        return "\n".join(
            [
                f"Попытка {result.attempt_id} не была завершена "
                f"(прервано: {result.reason or '—'}).",
                "  Автоматическое продолжение и повторный запуск той же попытки не выполнялись.",
                "  Откат не выполнялся.",
                "  Для новой обработки используйте новый вызов: будет создана новая попытка.",
            ]
        )

    if result.status is PostSessionProcessorStatus.INELIGIBLE:
        return "\n".join(
            [
                f"Сессия {result.session_id} не подходит для обработки: {result.reason or '—'}.",
                "  Модельная обработка не запускалась.",
            ]
        )

    # FAILED
    return "\n".join(
        [
            f"Обработка сессии {result.session_id} завершилась ошибкой.",
            f"  Попытка: {result.attempt_id}",
            f"  Фаза: {_PHASE_LABELS.get(result.phase, '—') if result.phase else '—'}",
            f"  Категория: "
            f"{_CATEGORY_LABELS.get(result.failure_category, '—') if result.failure_category else '—'}",
            f"  Терминальная ошибка сохранена: {'да' if result.failure_recorded else 'нет'}",
            f"  Причина: {result.reason or '—'}",
        ]
    )


def _render_recording_uncertainty(
    session_id: str | None,
    attempt_id: str | None,
    exc: PostSessionFailureRecordingError,
) -> str:
    """Render an unrecordable post-start failure without exposing internals."""
    phase = _PHASE_LABELS.get(exc.phase, exc.phase.value) if exc.phase else "—"
    return "\n".join(
        [
            f"Обработка сессии {session_id or '—'} завершилась ошибкой, и "
            "терминальный статус не удалось надёжно сохранить "
            f"(фаза: {phase}).",
            f"  Попытка: {attempt_id or '—'}",
            "  Durable-состояние попытки неопределённо.",
            "  Автоматический повтор не выполнялся; выполните новую обработку.",
        ]
    )


def _render_outputs(session_id: str, attempts: tuple[PostSessionAttemptOutput, ...]) -> str:
    """Render the read-only attempt-output view."""
    lines = [
        f"Результаты обработки сессии {session_id}:",
        f"  Попыток: {len(attempts)}",
    ]
    for attempt in attempts:
        lines.append(f"  Попытка {attempt.attempt_id}:")
        lines.append(f"    Состояние: {_STATE_LABELS.get(attempt.state, attempt.state.value)}")
        if attempt.verified:
            lines.append("    Проверка терминальных доказательств: подтверждена")
            lines.append(
                f"    Итог: {_OUTCOME_LABELS.get(attempt.outcome, '—') if attempt.outcome else '—'}"
            )
            lines.append(f"    Сводка (Summary): {attempt.summary_path or '—'}")
            lines.append(f"    Пересказ (Recap): {attempt.recap_path or '—'}")
            lines.append(f"    Рабочие доказательства (workflow): {attempt.workflow_path or '—'}")
            if attempt.changeset_id:
                lines.append(f"    ChangeSet (предложение): {attempt.changeset_id}")
        else:
            if attempt.state is AttemptState.FAILED:
                lines.append(
                    f"    Фаза: "
                    f"{_PHASE_LABELS.get(attempt.failure_phase, '—') if attempt.failure_phase else '—'}"
                )
                lines.append(
                    f"    Категория: "
                    f"{_CATEGORY_LABELS.get(attempt.failure_category, '—') if attempt.failure_category else '—'}"
                )
            if attempt.summary_path or attempt.recap_path or attempt.workflow_path:
                lines.append(f"    Сводка (Summary): {attempt.summary_path or '—'}")
                lines.append(f"    Пересказ (Recap): {attempt.recap_path or '—'}")
                lines.append(
                    f"    Рабочие доказательства (workflow): {attempt.workflow_path or '—'}"
                )
    return "\n".join(lines)


def _render_outputs_integrity_failure(exc: PostSessionOutputsError) -> str:
    """Render a bounded terminal-integrity failure (no artifact bodies)."""
    return "\n".join(
        [
            f"Ошибка: терминальное состояние попытки {exc.attempt_id} "
            f"не подтверждено ({exc.reason.value}).",
            "  Результаты обработки недостоверны; тела артефактов не выводятся.",
        ]
    )


# ── Selector resolution ────────────────────────────────────────────────────


def _resolve_session_id(
    metadata_repo: ObsidianSessionMetadataRepository,
    session_id: str | None,
    latest: bool,
) -> str:
    """Resolve the explicit id or the deterministic ``--latest`` id.

    Raises:
        SessionNotFoundError: The explicit session does not exist.
        LatestSelectionError: No completed session or malformed finish metadata.
    """
    if latest:
        return select_latest_completed_session(metadata_repo.list_session_metadata())

    assert session_id is not None
    try:
        metadata_repo.get_session_metadata(session_id)
    except NotFoundError as exc:
        raise SessionNotFoundError(session_id) from exc
    return session_id


# ── Commands ───────────────────────────────────────────────────────────────


def _session_process(
    session_id: str | None = typer.Argument(  # noqa: B008
        None,
        help="Идентификатор сессии. Взаимоисключающе с --latest.",
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
    config: Path = typer.Option(  # noqa: B008
        ...,
        "--config",
        help="Путь к machine-local TOML файлу конфигурации модели.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
    ),
    profile: str = typer.Option(  # noqa: B008
        ...,
        "--profile",
        help="Имя профиля модели (должен иметь роль POST_SESSION).",
    ),
    latest: bool = typer.Option(  # noqa: B008
        False,
        "--latest",
        help="Выбрать последнюю завершённую сессию. Взаимоисключающе с SESSION_ID.",
    ),
) -> None:
    """Обработать завершённую сессию пост-сессионным процессором.

    Требуется ровно одно из: позиционный SESSION_ID или --latest.
    Команда только СОЗДАЁТ предложение ChangeSet; проверка и применение
    выполняются отдельно через `dnd changeset ...`.
    """
    if (session_id is not None) == latest:
        typer.echo(
            "Ошибка: укажите ровно одно из: SESSION_ID или --latest.",
            err=True,
        )
        raise typer.Exit(code=1)

    vault_root = vault.resolve(strict=False)

    runtime = None
    resolved_id: str | None = None
    attempt_id: str | None = None

    try:
        metadata_repo = compose_metadata_repository(vault_root)
        resolved_id = _resolve_session_id(metadata_repo, session_id, latest)

        _recovery_preflight(vault_root)

        runtime = compose_post_session_runtime(
            vault_root=vault_root,
            config_path=config,
            profile_name=profile,
        )

        attempt_id = new_attempt_id()
        result = runtime.run(resolved_id, attempt_id)

        typer.echo(_render_process_result(result, vault_root))
        if _exit_code_for(result) != 0:
            raise typer.Exit(code=1)
    except PostSessionFailureRecordingError as exc:
        typer.echo(
            _render_recording_uncertainty(resolved_id, attempt_id, exc),
            err=True,
        )
        raise typer.Exit(code=1) from exc
    except DndAssistantError as exc:
        typer.echo(_render_dnd_error(exc), err=True)
        raise typer.Exit(code=1) from exc
    finally:
        if runtime is not None:
            runtime.close()


def _session_outputs(
    session_id: str = typer.Argument(  # noqa: B008
        ...,
        help="Идентификатор сессии.",
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
    """Показать результаты обработки сессии (только чтение).

    Основано на durable processing-ledger.  Для структурно завершённых попыток
    терминальные доказательства проверяются повторно; при несоответствии
    команда завершается с ошибкой и не выдаёт тела артефактов.
    """
    vault_root = vault.resolve(strict=False)

    try:
        metadata_repo = compose_metadata_repository(vault_root)
        try:
            metadata_repo.get_session_metadata(session_id)
        except NotFoundError as exc:
            raise SessionNotFoundError(session_id) from exc

        processing_store = ObsidianPostSessionProcessingStore(vault_root)
        artifact_store = ObsidianPostSessionArtifactStore(vault_root)
        changeset_store = ObsidianChangeSetStore(vault_root)

        attempts = build_post_session_outputs(
            processing_store,
            artifact_store,
            changeset_store,
            session_id,
        )

        if not attempts:
            typer.echo(f"Попыток обработки нет для сессии {session_id}.")
            return

        typer.echo(_render_outputs(session_id, attempts))
    except PostSessionOutputsError as exc:
        typer.echo(_render_outputs_integrity_failure(exc), err=True)
        raise typer.Exit(code=1) from exc
    except DndAssistantError as exc:
        typer.echo(_render_dnd_error(exc), err=True)
        raise typer.Exit(code=1) from exc


# ── Registration ───────────────────────────────────────────────────────────


def register_session_process_commands(app: typer.Typer) -> None:
    """Attach ``process`` and ``outputs`` to the existing session Typer group.

    Kept as an explicit registration function so ``cli/session.py`` never needs
    to import this module (avoiding a circular CLI import).
    """
    app.command("process")(_session_process)
    app.command("outputs")(_session_outputs)


__all__ = ["register_session_process_commands"]
