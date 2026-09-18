"""S13-03 CLI presentation for ``dnd bootstrap map``.

This module owns only CLI presentation and runtime composition for the
``dnd bootstrap`` command group:

- Typer option parsing;
- invoking the bootstrap discovery/mapping runtime;
- mapping the typed ``BootstrapRuntimeResult`` to Russian user-facing text;
- exit-code mapping.

It does NOT own discovery, canonical recognition, mapping, binding, ChangeSet
construction, persistence policy or model prompts, and it NEVER approves,
reviews or applies a proposal.  Review/apply is the next Stage-13 step (S13-04).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import typer

from dnd_assistant.application.bootstrap_mapping import BootstrapMappingRun
from dnd_assistant.application.bootstrap_result import (
    BootstrapMappingOutcome,
    BootstrapUnresolvedReason,
)
from dnd_assistant.application.vault_discovery import SourceClass
from dnd_assistant.cli.session import _recovery_preflight
from dnd_assistant.composition.bootstrap import (
    BootstrapRuntime,
    BootstrapRuntimeResult,
    compose_bootstrap_discovery,
    compose_bootstrap_runtime,
)
from dnd_assistant.errors import ConflictError, DndAssistantError, StorageError, ValidationError

__all__ = ["bootstrap_app"]

_MAX_UNRESOLVED_LINES: Final[int] = 20

_SOURCE_CLASS_LABELS: dict[SourceClass, str] = {
    SourceClass.ENTITY_CANDIDATE: "кандидаты сущностей",
    SourceClass.SESSION_SOURCE: "сессии",
    SourceClass.USER_SOURCE: "пользовательские заметки",
    SourceClass.APPLICATION_CONFIG: "конфигурация приложения",
    SourceClass.APPLICATION_RAW: "сырые данные приложения",
    SourceClass.APPLICATION_CONTROL: "рабочие данные приложения",
    SourceClass.DERIVED: "производные данные",
    SourceClass.UNSUPPORTED: "неподдерживаемые",
}

_UNRESOLVED_LABELS: dict[BootstrapUnresolvedReason, str] = {
    BootstrapUnresolvedReason.NO_CANONICAL_TARGET: "нет канонической цели",
    BootstrapUnresolvedReason.UNRESOLVED_REFERENCE: "нерешённая ссылка",
    BootstrapUnresolvedReason.UNSUPPORTED_CLAIM_KIND: "неподдерживаемый тип утверждения",
    BootstrapUnresolvedReason.UNSUPPORTED_MULTI_TARGET: "несколько целей",
    BootstrapUnresolvedReason.AMBIGUOUS_EXACT_MATCH: "неоднозначное точное совпадение",
    BootstrapUnresolvedReason.DUPLICATE_EXISTING_ENTITY: "дубликат существующей сущности",
    BootstrapUnresolvedReason.ENTITY_ID_COLLISION: "коллизия идентификатора",
    BootstrapUnresolvedReason.CANONICAL_STATE_CONFLICT: "конфликт канонического состояния",
    BootstrapUnresolvedReason.CANDIDATE_NAME_CONFLICT: "конфликт имён кандидатов",
    BootstrapUnresolvedReason.CONFLICTING_SOURCE_CLAIMS: "противоречивые источники",
    BootstrapUnresolvedReason.SYSTEM_ENTITY_EXCLUDED: "SYSTEM-сущность исключена",
    BootstrapUnresolvedReason.STALE_CANONICAL_ENTITY: "устаревшая каноническая сущность",
    BootstrapUnresolvedReason.DUPLICATE_FACT: "дубликат факта",
    BootstrapUnresolvedReason.SOURCE_SKIPPED: "источник пропущен",
    BootstrapUnresolvedReason.NON_CANONICAL_SOURCE: "неканонический исторический файл",
    BootstrapUnresolvedReason.CANONICAL_COVERAGE_INCOMPLETE: "каноническое состояние неполно",
}

_INCLUDED_CLASSES: Final[tuple[SourceClass, ...]] = (
    SourceClass.ENTITY_CANDIDATE,
    SourceClass.SESSION_SOURCE,
    SourceClass.USER_SOURCE,
)


def _render_dnd_error(exc: DndAssistantError) -> str:
    if isinstance(exc, ValidationError):
        return f"Ошибка конфигурации или профиля: {exc}"
    if isinstance(exc, StorageError):
        return f"Ошибка чтения данных Vault: {exc}"
    if isinstance(exc, ConflictError):
        return f"Конфликт: {exc}"
    return f"Ошибка: {exc}"


def _render_source_summary(run: BootstrapMappingRun) -> list[str]:
    counts: dict[SourceClass, int] = {}
    included = 0
    skipped = 0
    for source in run.projection.sources:
        counts[source.source_class] = counts.get(source.source_class, 0) + 1
        if source.included:
            included += 1
        else:
            skipped += 1

    lines = [
        f"  Отпечаток входа (semantic): sha256:{run.projection.input_fingerprint.digest}",
        f"  Пакетов модели: {len(run.projection.batches)}",
        f"  Источников включено: {included}",
        f"  Источников пропущено: {skipped}",
    ]
    for source_class in _INCLUDED_CLASSES:
        count = counts.get(source_class, 0)
        if count:
            lines.append(f"    {_SOURCE_CLASS_LABELS[source_class]}: {count}")
    conflicts = len(run.snapshot.conflicts)
    non_canonical = len(run.snapshot.issues)
    if conflicts or non_canonical:
        lines.append(
            f"  Канонические конфликты: {conflicts}; неканонические исторические файлы: "
            f"{non_canonical}"
        )
    return lines


def _unresolved_counts(run: BootstrapMappingRun) -> dict[BootstrapUnresolvedReason, int]:
    counts: dict[BootstrapUnresolvedReason, int] = {}
    for item in run.result.unresolved:
        counts[item.reason] = counts.get(item.reason, 0) + 1
    return counts


def _render_unresolved(run: BootstrapMappingRun) -> list[str]:
    unresolved = run.result.unresolved
    lines = [f"  Нерешённых пунктов: {len(unresolved)}"]
    if not unresolved:
        return lines

    lines.append("  Сводка по причинам:")
    for reason, count in sorted(_unresolved_counts(run).items(), key=lambda item: item[0].value):
        lines.append(f"    {_UNRESOLVED_LABELS.get(reason, reason.value)}: {count}")

    lines.append("  Примеры:")
    for item in unresolved[:_MAX_UNRESOLVED_LINES]:
        lines.append(
            f"    - [{_UNRESOLVED_LABELS.get(item.reason, item.reason.value)}] {item.detail}"
        )
    if len(unresolved) > _MAX_UNRESOLVED_LINES:
        lines.append(f"    … и ещё {len(unresolved) - _MAX_UNRESOLVED_LINES}")
    return lines


def _render_result(result: BootstrapRuntimeResult, *, persisted: bool) -> str:
    run = result.run
    identity = run.model_identity
    lines = [
        "Bootstrap существующей кампании (маппинг).",
        f"  Vault: {run.projection.campaign_id}",
        f"  Профиль модели: {identity.profile or '—'} "
        f"({identity.model or '—'}, {identity.provider or '—'})",
        f"  Версия промпта: {run.prompt_version}",
        *_render_source_summary(run),
        "",
    ]

    if run.result.outcome is BootstrapMappingOutcome.PROPOSAL and run.result.changeset is not None:
        fingerprint = run.result.changeset_fingerprint
        digest = f"{fingerprint.algorithm}:{fingerprint.digest}" if fingerprint else "—"
        lines.extend(
            [
                "  ChangeSet (предложение): " + run.result.changeset.changeset_id,
                f"  Отпечаток предложения: {digest}",
            ]
        )
        if not persisted:
            lines.extend(
                [
                    "  Режим проверки (--dry-run): предложение НЕ сохранено.",
                    "  Ничего не одобрено и не применено.",
                ]
            )
        else:
            if result.evidence_error is not None:
                lines.extend(
                    [
                        "  ВНИМАНИЕ: предложение сохранено, но доказательства маппинга "
                        "НЕ сохранены (частичное сохранение workflow).",
                        f"    Причина: {result.evidence_error}",
                        "    Автоматический откат не выполнялся.",
                    ]
                )
            else:
                lines.append("  Доказательства маппинга сохранены (workflow/control).")
            lines.extend(
                [
                    "  ВНИМАНИЕ: это ТОЛЬКО предложение; оно НЕ одобрено и НЕ применено.",
                    "  Канонические данные кампании не изменялись.",
                    "  Следующий шаг Stage 13 — bootstrap-обзор и применение (S13-04).",
                ]
            )
    else:
        lines.extend(["  ChangeSet не создан."])
        if not run.result.unresolved:
            lines.append("  Допустимых новых сущностей/фактов не найдено; нерешённых пунктов нет.")
        else:
            lines.append(
                "  Найдены нерешённые/неподдерживаемые/конфликтующие материалы; "
                "кампания НЕ считается полностью импортированной."
            )
        lines.append("  Канонические данные кампании не изменялись.")

    lines.append("")
    lines.extend(_render_unresolved(run))
    return "\n".join(lines)


# ── Typer subgroup ─────────────────────────────────────────────────────────

bootstrap_app = typer.Typer(
    name="bootstrap",
    help="Bootstrap существующей кампании из уже созданного Vault (маппинг/предложения).",
)


@bootstrap_app.callback()
def _bootstrap_callback() -> None:
    """Bootstrap существующей кампании: маппинг в предложения ChangeSet."""


@bootstrap_app.command("map")
def _bootstrap_map(
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
        help="Имя профиля модели (должен иметь роль BOOTSTRAP).",
    ),
    dry_run: bool = typer.Option(  # noqa: B008
        False,
        "--dry-run",
        help="Только показать результат маппинга; ничего не сохранять.",
    ),
) -> None:
    """Сопоставить существующий Vault с каноническими структурами и создать предложение.

    Команда только СОЗДАЁТ предложение ChangeSet; обзор и применение выполняются
    bootstrap-процедурой Stage 13 (S13-04).  Канонические данные не изменяются.
    """
    vault_root = vault.resolve(strict=False)
    if not vault_root.is_dir():
        typer.echo(
            f"Ошибка: корень Vault должен быть существующей директорией: {vault_root}",
            err=True,
        )
        raise typer.Exit(code=1)

    runtime: BootstrapRuntime | None = None
    try:
        report = compose_bootstrap_discovery(vault_root)
        if not dry_run:
            _recovery_preflight(vault_root)

        runtime = compose_bootstrap_runtime(
            vault_root=vault_root,
            config_path=config,
            profile_name=profile,
        )
        result = runtime.run(report, persist=not dry_run)

        typer.echo(_render_result(result, persisted=not dry_run))
        if result.partial_persistence:
            raise typer.Exit(code=1)
    except DndAssistantError as exc:
        typer.echo(_render_dnd_error(exc), err=True)
        raise typer.Exit(code=1) from exc
    finally:
        if runtime is not None:
            runtime.close()
