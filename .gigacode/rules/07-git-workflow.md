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

Для commit message используй Conventional Commits, например:

- feat: implement session domain schema
- fix: correct session id internal type
- test: add session validation coverage
- docs: update development status
- refactor: simplify entity validation
