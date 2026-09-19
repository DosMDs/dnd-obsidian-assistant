"""S13-05 CLI presentation for ``dnd bootstrap finalize``.

This module owns only CLI presentation: Typer option parsing, invoking the
bootstrap finalization composition and mapping the typed completion result to
Russian user-facing text and exit codes.

It owns no discovery, mapping, validation, rebuild or session policy, calls no
model directly and performs no mutation.
"""

from __future__ import annotations

from pathlib import Path

import typer

from dnd_assistant.application.bootstrap_completion import (
    BootstrapCompletionResult,
    BootstrapCompletionStatus,
)
from dnd_assistant.composition.bootstrap_completion import finalize_bootstrap
from dnd_assistant.errors import DndAssistantError

__all__ = ["register_bootstrap_finalize_command"]

_VAULT_HELP = "Путь к корню Obsidian Vault."
_MAX_ISSUE_LINES = 20

_STATUS_LABELS: dict[BootstrapCompletionStatus, str] = {
    BootstrapCompletionStatus.COMPLETE: "ЗАВЕРШЕНО",
    BootstrapCompletionStatus.COMPLETE_WITH_ACKNOWLEDGED_UNRESOLVED: (
        "ЗАВЕРШЕНО С ПОДТВЕРЖДЁННЫМИ НЕРЕШЁННЫМИ ПУНКТАМИ"
    ),
    BootstrapCompletionStatus.UNINITIALIZED_VAULT: "VAULT НЕ ИНИЦИАЛИЗИРОВАН",
    BootstrapCompletionStatus.RECOVERY_BLOCKED: "ТРЕБУЕТСЯ ВОССТАНОВЛЕНИЕ",
    BootstrapCompletionStatus.CANONICAL_NOT_READY: "КАНОНИЧЕСКОЕ СОСТОЯНИЕ НЕ ГОТОВО",
    BootstrapCompletionStatus.CANONICAL_COVERAGE_INCOMPLETE: "КАНОНИЧЕСКОЕ ПОКРЫТИЕ НЕПОЛНО",
    BootstrapCompletionStatus.WORLD_TIME_UNINITIALIZED: "МИРОВОЕ ВРЕМЯ НЕ ИНИЦИАЛИЗИРОВАНО",
    BootstrapCompletionStatus.WORLD_TIME_INVALID: "МИРОВОЕ ВРЕМЯ ПОВРЕЖДЕНО",
    BootstrapCompletionStatus.ACTIVE_SESSION_PRESENT: "ЕСТЬ АКТИВНАЯ СЕССИЯ",
    BootstrapCompletionStatus.MAPPING_FAILED: "МАППИНГ НЕ ВЫПОЛНЕН",
    BootstrapCompletionStatus.PROPOSAL_PERSISTENCE_FAILED: "ОШИБКА СОХРАНЕНИЯ ПРЕДЛОЖЕНИЯ",
    BootstrapCompletionStatus.EVIDENCE_PERSISTENCE_FAILED: "ОШИБКА СОХРАНЕНИЯ ДОКАЗАТЕЛЬСТВ",
    BootstrapCompletionStatus.PENDING_CHANGESET: "ОЖИДАЕТ ПРИМЕНЕНИЯ ПРЕДЛОЖЕНИЯ",
    BootstrapCompletionStatus.UNRESOLVED_NOT_ACKNOWLEDGED: "НЕРЕШЁННЫЕ ПУНКТЫ НЕ ПОДТВЕРЖДЕНЫ",
    BootstrapCompletionStatus.SOURCE_CHANGED_DURING_VALIDATION: (
        "ИСХОДНЫЕ МАТЕРИАЛЫ ИЗМЕНИЛИСЬ ВО ВРЕМЯ ПРОВЕРКИ"
    ),
    BootstrapCompletionStatus.CAMPAIGN_STATE_REBUILD_FAILED: "СБОРКА CAMPAIGN STATE НЕ УДАЛАСЬ",
    BootstrapCompletionStatus.FTS_REBUILD_FAILED: "СБОРКА FTS НЕ УДАЛАСЬ",
    BootstrapCompletionStatus.DERIVED_VERIFICATION_FAILED: "ПРОВЕРКА ПРОИЗВОДНЫХ ДАННЫХ НЕ ПРОЙДЕНА",
}


def _status_label(status: BootstrapCompletionStatus) -> str:
    return _STATUS_LABELS.get(status, status.value)


def _fmt(value: object, *, default: str = "—") -> str:
    if value is None:
        return default
    if isinstance(value, bool):
        return "да" if value else "нет"
    return str(value)


def render_completion(result: BootstrapCompletionResult, *, vault: str) -> str:
    """Render a typed completion result as Russian CLI text.

    ``vault`` is the already-resolved CLI Vault path, used only to render
    executable follow-up commands; it is never added to application DTOs.
    """
    fingerprint = result.completion_fingerprint
    digest = f"sha256:{fingerprint.digest}" if fingerprint is not None else "—"
    lines = [
        "Финализация bootstrap существующей кампании.",
        f"  Кампания: {_fmt(result.campaign_id)}",
        f"  Отпечаток входа (semantic): {digest}",
        f"  Итог маппинга: {_fmt(result.mapping_outcome.value if result.mapping_outcome else None)}",
        f"  Предложение ChangeSet: {_fmt(result.changeset_id)}",
        f"  Каноническое покрытие полное: {_fmt(result.coverage_complete)}",
        f"  Нерешённых пунктов: {result.unresolved_count}"
        f" (подтверждено: {_fmt(result.unresolved_acknowledged)})",
        f"  Канонических сущностей: {_fmt(result.canonical_documents)}",
        f"  Текущий мировой такт: {_fmt(result.current_world_tick)}",
        f"  Активная сессия: {_fmt(result.active_session_id)}",
        f"  Campaign State: {_fmt(result.campaign_state_status.value if result.campaign_state_status else None)}",
        f"  FTS проверен: {_fmt(result.fts_verified)}",
        f"  Итоговая стабильность источников: {_fmt(result.final_source_stable)}",
        f"  Итоговый статус: {_status_label(result.status)}",
    ]
    if result.detail:
        lines.append(f"  Пояснение: {result.detail}")

    if result.status is BootstrapCompletionStatus.PENDING_CHANGESET:
        lines.extend(
            [
                "",
                "Bootstrap НЕ завершён. Просмотрите и примените созданное предложение:",
                f"  dnd bootstrap review {_fmt(result.changeset_id)} --vault {vault}",
                f"  dnd bootstrap approve {_fmt(result.changeset_id)} --vault {vault} "
                "--reviewer <id> [--acknowledge-unresolved]",
                f"  dnd bootstrap apply {_fmt(result.changeset_id)} --vault {vault} "
                "[--acknowledge-unresolved]",
            ]
        )
    elif result.status is BootstrapCompletionStatus.COMPLETE:
        lines.extend(
            [
                "",
                "Поддерживаемый bootstrap-workflow чисто закрыт; производные данные актуальны; "
                "предпосылки запуска сессии выполнены.",
            ]
        )
    elif result.status is BootstrapCompletionStatus.COMPLETE_WITH_ACKNOWLEDGED_UNRESOLVED:
        lines.extend(
            [
                "",
                "Операционная готовность достигнута; импорт явно принял нерешённые диагностики.",
                "Это НЕ утверждение о полноте исторического знания кампании.",
            ]
        )

    if result.issues:
        lines.append("")
        lines.append("  Наблюдённые проблемы:")
        for issue in result.issues[:_MAX_ISSUE_LINES]:
            lines.append(f"    - {issue}")
        if len(result.issues) > _MAX_ISSUE_LINES:
            lines.append(f"    … и ещё {len(result.issues) - _MAX_ISSUE_LINES}")
    return "\n".join(lines)


def _bootstrap_finalize(
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
        help="Имя профиля модели (должен иметь роль BOOTSTRAP).",
    ),
    acknowledge_unresolved: bool = typer.Option(  # noqa: B008
        False,
        "--acknowledge-unresolved",
        help="Подтвердить нерешённые пункты (не влияет на неполное каноническое покрытие).",
    ),
) -> None:
    """Проверить полноту bootstrap, пересобрать производные данные и подтвердить готовность."""
    vault_root = vault.resolve(strict=False)
    if not vault_root.is_dir():
        typer.echo(
            f"Ошибка: корень Vault должен быть существующей директорией: {vault_root}",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        result = finalize_bootstrap(
            vault_root=vault_root,
            config_path=config,
            profile_name=profile,
            acknowledge_unresolved=acknowledge_unresolved,
        )
    except DndAssistantError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(render_completion(result, vault=str(vault_root)))
    if not result.completed:
        raise typer.Exit(code=1)


def register_bootstrap_finalize_command(app: typer.Typer) -> None:
    """Attach the ``finalize`` command to the bootstrap Typer group."""
    app.command("finalize")(_bootstrap_finalize)
