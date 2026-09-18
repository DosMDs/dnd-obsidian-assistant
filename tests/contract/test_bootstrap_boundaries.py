"""Contract tests: S13-01 bootstrap layer boundaries and no-scan guarantees.

Static AST checks only: no clean-import harness, no Git, no shell, no network.
This focused module is used instead of growing ``test_boundaries.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = REPO_ROOT / "src" / "dnd_assistant"

STORAGE_MODULE = SRC_ROOT / "storage" / "vault_initialization.py"
ATOMIC_MODULE = SRC_ROOT / "storage" / "atomic.py"
APPLICATION_MODULE = SRC_ROOT / "application" / "vault_initialization.py"
COMPOSITION_MODULE = SRC_ROOT / "composition" / "vault_initialization.py"
CLI_MODULE = SRC_ROOT / "cli" / "init.py"

FORBIDDEN_FOR_STORAGE = (
    "dnd_assistant.application",
    "dnd_assistant.cli",
    "dnd_assistant.models",
    "dnd_assistant.tools",
    "dnd_assistant.retrieval",
    "ollama",
    "pydantic_ai",
)

FORBIDDEN_FOR_APPLICATION = (
    "dnd_assistant.cli",
    "dnd_assistant.models",
    "dnd_assistant.tools",
    "ollama",
    "pydantic_ai",
)

FORBIDDEN_FOR_COMPOSITION = ("dnd_assistant.cli", "typer", "textual")

NO_SCAN_IMPORTS = (
    "dnd_assistant.storage.markdown",
    "dnd_assistant.storage.vault_repository",
    "dnd_assistant.retrieval",
)


def _imports(path: Path) -> tuple[set[str], dict[str, set[str]]]:
    """Return (imported modules, {module: imported names}) for a source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    names: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            modules.add(node.module)
            names.setdefault(node.module, set()).update(a.name for a in node.names)
    return modules, names


def _is_or_under(module: str, package: str) -> bool:
    return module == package or module.startswith(f"{package}.")


def _offenders(path: Path, forbidden: tuple[str, ...]) -> list[str]:
    modules, _ = _imports(path)
    return [m for m in modules if any(_is_or_under(m, f) for f in forbidden)]


def test_storage_initializer_does_not_import_upper_layers() -> None:
    assert not _offenders(STORAGE_MODULE, FORBIDDEN_FOR_STORAGE)


def test_storage_initializer_is_provider_neutral() -> None:
    assert not _offenders(STORAGE_MODULE, ("ollama", "pydantic_ai"))


def test_application_initialization_does_not_import_upper_layers() -> None:
    assert not _offenders(APPLICATION_MODULE, FORBIDDEN_FOR_APPLICATION)


def test_application_initialization_does_not_depend_on_concrete_audit_service() -> None:
    _, names = _imports(APPLICATION_MODULE)
    audit_names = names.get("dnd_assistant.storage.audit", set())
    assert "AuditService" not in audit_names, (
        f"application must not depend on the concrete AuditService; imported {sorted(audit_names)}"
    )


def test_composition_does_not_import_presentation() -> None:
    assert not _offenders(COMPOSITION_MODULE, FORBIDDEN_FOR_COMPOSITION)


def test_no_scan_imports_in_bootstrap_layers() -> None:
    for path in (STORAGE_MODULE, APPLICATION_MODULE):
        offenders = _offenders(path, NO_SCAN_IMPORTS)
        assert not offenders, f"{path.name} imports note-scanning modules: {offenders}"


def test_cli_init_imports_composition_and_application() -> None:
    modules, _ = _imports(CLI_MODULE)
    assert "dnd_assistant.composition.vault_initialization" in modules
    assert "dnd_assistant.application.vault_initialization" in modules


def test_cli_init_does_not_import_storage_or_presentation_internals() -> None:
    modules, _ = _imports(CLI_MODULE)
    storage_internal = [m for m in modules if _is_or_under(m, "dnd_assistant.storage")]
    assert not storage_internal, f"cli/init.py imports storage internals: {storage_internal}"


_FILESYSTEM_CALL_ATTRS = frozenset(
    {
        "mkdir",
        "makedirs",
        "rmdir",
        "unlink",
        "rename",
        "replace",
        "touch",
        "write_text",
        "write_bytes",
        "remove",
        "rmtree",
    }
)


def test_cli_init_performs_no_filesystem_mutation() -> None:
    tree = ast.parse(CLI_MODULE.read_text(encoding="utf-8"), filename=str(CLI_MODULE))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in _FILESYSTEM_CALL_ATTRS:
                offenders.append(func.attr)
            if isinstance(func, ast.Name) and func.id == "open":
                offenders.append("open")
    assert not offenders, f"cli/init.py performs filesystem mutation: {offenders}"


def test_atomic_module_exposes_exclusive_primitive() -> None:
    source = ATOMIC_MODULE.read_text(encoding="utf-8")
    assert "def exclusive_atomic_write_text(" in source
    assert "_exclusive_link(" in source
    # The forbidden fallbacks must not exist anywhere in the primitive.
    assert 'mode="x"' not in source
