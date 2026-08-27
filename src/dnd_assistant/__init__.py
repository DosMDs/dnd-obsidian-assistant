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

__all__: list[str] = [
    "AmbiguousEntityError",
    "ConflictError",
    "DndAssistantError",
    "LockError",
    "ModelError",
    "NotFoundError",
    "StorageError",
    "ValidationError",
]


def main() -> None:
    print("Hello from dnd-assistant!")
