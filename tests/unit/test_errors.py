import pytest

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


@pytest.mark.parametrize(
    "error_type",
    [
        ValidationError,
        NotFoundError,
        ConflictError,
        AmbiguousEntityError,
        StorageError,
        ModelError,
        LockError,
    ],
)
def test_application_errors_inherit_from_base(
    error_type: type[DndAssistantError],
) -> None:
    error = error_type("test")

    assert isinstance(error, DndAssistantError)
    assert str(error) == "test"
