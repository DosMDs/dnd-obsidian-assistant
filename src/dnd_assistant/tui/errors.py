"""Expected-error presentation for the TUI (TUI-05).

Presentation-only and Textual-free. This module maps the stable trusted
``DndAssistantError`` classes to bounded Russian user-facing text.  It never
parses exception message strings to infer domain semantics; the exception class
already carries the category.

Scope is deliberately narrow:

- only expected ``DndAssistantError`` subclasses become recoverable user-facing
  results;
- unexpected programming exceptions are never caught here and stay observable
  and test-failing in the worker/state path.

No error framework, no duplicate domain-error hierarchy.
"""

from __future__ import annotations

from dnd_assistant.errors import (
    AmbiguousEntityError,
    ConflictError,
    DndAssistantError,
    LockError,
    ModelError,
    NotFoundError,
    StorageError,
    ValidationError,
)

__all__ = ["expected_error_category", "render_expected_error"]

_DEFAULT_CATEGORY = "Ошибка"

_EXPECTED_CATEGORIES: tuple[tuple[type[DndAssistantError], str], ...] = (
    (ValidationError, "Ошибка проверки"),
    (NotFoundError, "Не найдено"),
    (ConflictError, "Конфликт"),
    (AmbiguousEntityError, "Неоднозначная ссылка"),
    (StorageError, "Ошибка хранилища"),
    (ModelError, "Ошибка модели"),
    (LockError, "Ошибка блокировки"),
)


def expected_error_category(exc: DndAssistantError) -> str:
    """Return the Russian category label for an expected error class."""
    for error_type, label in _EXPECTED_CATEGORIES:
        if isinstance(exc, error_type):
            return label
    return _DEFAULT_CATEGORY


def render_expected_error(exc: DndAssistantError, *, hint: str | None = None) -> str:
    """Render one expected error with its category and an optional hint.

    The optional ``hint`` is a presentation-supplied, already-safe note (for
    example the non-blocking externally-owned ChangeSet hint); it is never raw
    internal exception detail.
    """
    message = f"{expected_error_category(exc)}: {exc}"
    if hint:
        return f"{message}\n{hint}"
    return message
