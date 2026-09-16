"""S11-08 CLI hardening source-level guards.

The CLI must not introduce a broad ``except Exception`` and must not own
processing/model/storage policy.  These are structural, read-only checks.
"""

from __future__ import annotations

import ast
from pathlib import Path

_CLI_PATH = (
    Path(__file__).resolve().parents[3] / "src" / "dnd_assistant" / "cli" / "post_session.py"
)


def _handler_exception_types(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is not None:
            names.append(ast.unparse(node.type))
    return names


def test_cli_catches_only_typed_errors() -> None:
    tree = ast.parse(_CLI_PATH.read_text(encoding="utf-8"))
    handlers = _handler_exception_types(tree)
    assert handlers, "expected explicit typed handlers"
    assert all(handler != "Exception" and "BaseException" not in handler for handler in handlers)


def test_cli_does_not_import_model_or_storage_policy() -> None:
    source = _CLI_PATH.read_text(encoding="utf-8")
    # CLI presentation must not construct concrete models or call apply.
    assert "apply_changeset" not in source
    assert "build_pydantic_ai_post_session_model" not in source
