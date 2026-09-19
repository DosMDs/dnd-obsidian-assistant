"""Contract tests: S13-04 bootstrap review/apply layer boundaries.

Static AST checks only: no clean-import harness, no Git, no shell, no network.
This focused module is used instead of growing ``test_boundaries.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = REPO_ROOT / "src" / "dnd_assistant"

APPLICATION_MODULES = (
    SRC_ROOT / "application" / "bootstrap_review.py",
    SRC_ROOT / "application" / "bootstrap_readiness.py",
    SRC_ROOT / "application" / "bootstrap_apply.py",
)
COMPOSITION_MODULE = SRC_ROOT / "composition" / "bootstrap_review_apply.py"
CLI_MODULE = SRC_ROOT / "cli" / "bootstrap_review.py"
GENERIC_CLI_MODULE = SRC_ROOT / "cli" / "changeset.py"

FORBIDDEN_APPLICATION = (
    "dnd_assistant.models",
    "dnd_assistant.tools",
    "dnd_assistant.cli",
    "dnd_assistant.retrieval",
    "ollama",
    "pydantic_ai",
    "textual",
)

_MUTATION_ATTRS = frozenset(
    {
        "mkdir",
        "makedirs",
        "rmdir",
        "unlink",
        "rename",
        "touch",
        "write_text",
        "write_bytes",
        "remove",
        "rmtree",
        "chmod",
        "link",
        "symlink",
        "truncate",
    }
)
_WRITE_MODE_TOKENS = ("w", "a", "x", "+")


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            modules.add(node.module)
    return modules


def _is_or_under(module: str, package: str) -> bool:
    return module == package or module.startswith(f"{package}.")


def _offenders(path: Path, forbidden: tuple[str, ...]) -> list[str]:
    return [m for m in _imports(path) if any(_is_or_under(m, f) for f in forbidden)]


def _write_offenders(path: Path) -> list[str]:
    offenders: list[str] = []
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name: str | None = None
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        if name in _MUTATION_ATTRS:
            offenders.append(name)
        if name in ("open", "fdopen"):
            modes: list[str] = [
                arg.value
                for arg in node.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            ]
            modes += [
                kw.value.value
                for kw in node.keywords
                if kw.arg == "mode"
                and isinstance(kw.value, ast.Constant)
                and isinstance(kw.value.value, str)
            ]
            for mode in modes:
                if any(token in mode for token in _WRITE_MODE_TOKENS):
                    offenders.append(f"open(mode={mode!r})")
    return offenders


def test_application_modules_forbid_provider_presentation_and_filesystem() -> None:
    for path in APPLICATION_MODULES:
        assert not _offenders(path, FORBIDDEN_APPLICATION), path.name
        modules = _imports(path)
        assert not (modules & {"pathlib", "os", "shutil", "tempfile"}), path.name
        assert not _write_offenders(path), path.name


def test_application_modules_do_not_construct_models_or_profiles() -> None:
    for path in APPLICATION_MODULES:
        source = path.read_text(encoding="utf-8")
        assert "load_model_profiles" not in source
        assert "build_pydantic_ai" not in source
        assert "pydantic_ai_ollama" not in source


def test_composition_does_not_import_presentation() -> None:
    assert not _offenders(COMPOSITION_MODULE, ("dnd_assistant.cli", "typer", "textual"))


def test_cli_module_imports_composition_and_is_write_free() -> None:
    modules = _imports(CLI_MODULE)
    assert "dnd_assistant.composition.bootstrap_review_apply" in modules
    assert not any(_is_or_under(m, "textual") for m in modules)
    assert "dnd_assistant.storage.vault_repository" not in modules
    assert not _write_offenders(CLI_MODULE)


def test_generic_apply_has_bootstrap_guard() -> None:
    source = GENERIC_CLI_MODULE.read_text(encoding="utf-8")
    assert "Provenance.BOOTSTRAP" in source
    assert "bootstrap apply" in source
    assert "dnd bootstrap" in source
