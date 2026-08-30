"""D&D Session Assistant — local, offline-first campaign memory for D&D/RPG.

Sub-packages
────────────
cli/          — Typer commands and presentation only.
application/  — Orchestration and use cases.
domain/       — Pure domain models and deterministic business rules.
storage/      — Vault Markdown/YAML persistence, audit, atomic writes.
retrieval/    — Exact/fuzzy/FTS search and entity resolution.
tools/        — ToolRegistry, ToolExecutor and safe tools.
models/       — ModelGateway contracts and provider adapters.
prompts/      — Versioned model prompts.
evals/        — Deterministic model evaluation logic/data.
"""

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
