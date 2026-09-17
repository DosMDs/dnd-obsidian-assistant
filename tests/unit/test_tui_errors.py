"""TUI-05 expected-error presentation unit tests (Textual-free)."""

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
from dnd_assistant.tui.errors import expected_error_category, render_expected_error


class TestExpectedErrorCategory:
    def test_validation_error(self) -> None:
        assert expected_error_category(ValidationError("x")) == "Ошибка проверки"

    def test_not_found_error(self) -> None:
        assert expected_error_category(NotFoundError("x")) == "Не найдено"

    def test_conflict_error(self) -> None:
        assert expected_error_category(ConflictError("x")) == "Конфликт"

    def test_ambiguous_entity_error(self) -> None:
        assert expected_error_category(AmbiguousEntityError("x")) == "Неоднозначная ссылка"

    def test_storage_error(self) -> None:
        assert expected_error_category(StorageError("x")) == "Ошибка хранилища"

    def test_model_error(self) -> None:
        assert expected_error_category(ModelError("x")) == "Ошибка модели"

    def test_lock_error(self) -> None:
        assert expected_error_category(LockError("x")) == "Ошибка блокировки"

    def test_base_error_default_category(self) -> None:
        assert expected_error_category(DndAssistantError("x")) == "Ошибка"

    def test_unknown_subclass_uses_base_category(self) -> None:
        class CustomError(DndAssistantError):
            pass

        assert expected_error_category(CustomError("x")) == "Ошибка"

    def test_category_uses_class_not_message_text(self) -> None:
        # A message that mentions another error class name must not change the
        # category: categorization is class-based, never string parsing.
        exc = ValidationError("ModelError: misleading text")
        assert expected_error_category(exc) == "Ошибка проверки"


class TestRenderExpectedError:
    def test_render_includes_category_and_detail(self) -> None:
        rendered = render_expected_error(ModelError("сбой модели"))
        assert rendered == "Ошибка модели: сбой модели"

    def test_render_appends_hint_on_new_line(self) -> None:
        rendered = render_expected_error(StorageError("нет доступа"), hint="Подсказка")
        assert rendered == "Ошибка хранилища: нет доступа\nПодсказка"

    def test_render_without_hint_is_single_line(self) -> None:
        rendered = render_expected_error(ConflictError("конфликт"))
        assert "\n" not in rendered
