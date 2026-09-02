---
apply: ALWAYS
mode: AGENT
---

# Git workflow

После успешного выполнения текущей задачи и прохождения всех quality gates:

- проверь `git status`;
- проверь `git diff`;
- добавь в индекс только файлы текущей задачи;
- создай один логичный commit;
- сразу отправь commit в `origin` текущей ветки.

Обычные `git commit` и `git push` не требуют отдельного подтверждения пользователя.

Не выполняй push, если тесты, Ruff или другие обязательные проверки не прошли.

Никогда автоматически не используй:

- git push --force
- git push --force-with-lease
- git reset --hard
- destructive rebase
- удаление remote branch
- переписывание опубликованной истории

Если обычный push отклонён, остановись и сообщи причину.

## Pre-finalization audit

Before every task commit, run or follow the `pre-finalization-audit` skill.

The final changed-file inventory must come from Git, not from memory.

A mandatory failed test or Ruff gate means no push.

## Single-task-commit finalization invariant

Для обычной задачи (implementation / correction / maintenance):

```text
все изменения исходников
все тесты
все обновления DEVELOPMENT_STATUS.md
все изменения stage-документации
все ADR / документация, требуемые задачей

ДОЛЖНЫ быть подготовлены ДО intended task commit
```

Затем:

```text
quality gates
→ финальный diff
→ один логичный commit
→ push
→ проверка HEAD == upstream
→ ОСТАНОВКА репозиторных мутаций
```

После task commit **запрещено**:

- редактировать docs для вставки только что созданного SHA;
- делать amend только для добавления self-SHA;
- создавать второй docs-only self-SHA commit;
- создавать второй status-only commit;
- изменять Final Report evidence внутри репозитория.

Полученный commit SHA принадлежит:

```text
Final Report
```

не тому же самому commit.

Репозиторная документация должна использовать:

```text
(reported in Final Report)
```

или опускать текущий task SHA.

Исторические SHA из более ранних commit'ов документируются обычным образом.

Для commit message используй Conventional Commits, например:

- feat: implement session domain schema
- fix: correct session id internal type
- test: add session validation coverage
- docs: update development status
- refactor: simplify entity validation
