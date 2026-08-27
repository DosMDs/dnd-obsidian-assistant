"""Domain and application error hierarchy for D&D Session Assistant."""


class DndAssistantError(Exception):
    """Base error for all D&D Session Assistant exceptions."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self._message = message
        if cause is not None:
            self.__cause__ = cause

    def __str__(self) -> str:
        return self._message


class ValidationError(DndAssistantError):
    """Raised when input data fails validation."""


class NotFoundError(DndAssistantError):
    """Raised when a requested entity or resource is not found."""


class ConflictError(DndAssistantError):
    """Raised when an operation conflicts with the current state."""


class AmbiguousEntityError(DndAssistantError):
    """Raised when an entity reference cannot be uniquely resolved."""


class StorageError(DndAssistantError):
    """Raised when a storage operation fails."""


class ModelError(DndAssistantError):
    """Raised when a model/LLM interaction fails."""


class LockError(DndAssistantError):
    """Raised when a lock cannot be acquired or released."""
