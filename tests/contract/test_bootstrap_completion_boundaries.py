"""Contract tests: S13-05 bootstrap finalization layer boundaries.

Static AST checks only: no clean-import harness, no Git, no shell, no network.
This focused module is used instead of growing ``test_boundaries.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = REPO_ROOT / "src" / "dnd_assistant"

APPLICATION_MODULE = SRC_ROOT / "application" / "bootstrap_completion.py"
COMPLETION_COMPOSITION = SRC_ROOT / "composition" / "bootstrap_completion.py"
INDEX_COMPOSITION = SRC_ROOT / "composition" / "index_rebuild.py"
WORLD_TIME_COMPOSITION = SRC_ROOT / "composition" / "world_time.py"
FINALIZE_CLI = SRC_ROOT / "cli" / "bootstrap_finalize.py"
TIME_CLI = SRC_ROOT / "cli" / "time.py"
MAIN_CLI = SRC_ROOT / "cli" / "main.py"

FORBIDDEN_APPLICATION = (
    "dnd_assistant.models",
    "dnd_assistant.tools",
    "dnd_assistant.cli",
    "dnd_assistant.retrieval",
    "dnd_assistant.storage",
    "ollama",
    "pydantic_ai",
    "textual",
)

FORBIDDEN_COMPOSITION_PRESENTATION = (
    "dnd_assistant.cli",
    "typer",
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


def test_application_completion_is_pure_policy() -> None:
    assert not _offenders(APPLICATION_MODULE, FORBIDDEN_APPLICATION), APPLICATION_MODULE.name
    modules = _imports(APPLICATION_MODULE)
    assert not (modules & {"pathlib", "os", "shutil", "tempfile"}), APPLICATION_MODULE.name
    assert not _write_offenders(APPLICATION_MODULE), APPLICATION_MODULE.name


def test_application_completion_does_not_construct_models() -> None:
    source = APPLICATION_MODULE.read_text(encoding="utf-8")
    assert "load_model_profiles" not in source
    assert "build_pydantic_ai" not in source
    assert "pydantic_ai_ollama" not in source
    assert "BootstrapRuntime" not in source


def test_composition_modules_do_not_import_presentation() -> None:
    for path in (COMPLETION_COMPOSITION, INDEX_COMPOSITION, WORLD_TIME_COMPOSITION):
        assert not _offenders(path, FORBIDDEN_COMPOSITION_PRESENTATION), path.name


def test_completion_composition_reuses_accepted_runtimes() -> None:
    modules = _imports(COMPLETION_COMPOSITION)
    assert "dnd_assistant.composition.bootstrap" in modules
    assert "dnd_assistant.composition.index_rebuild" in modules
    assert "dnd_assistant.application.bootstrap_completion" in modules
    assert "dnd_assistant.application.campaign_state_materialization" in modules


def test_index_rebuild_routes_main_cli_and_completion() -> None:
    main_modules = _imports(MAIN_CLI)
    assert "dnd_assistant.composition.index_rebuild" in main_modules
    assert "dnd_assistant.retrieval.index" not in main_modules
    assert "dnd_assistant.storage.vault_repository" not in main_modules


def test_finalize_cli_imports_composition_and_is_write_free() -> None:
    modules = _imports(FINALIZE_CLI)
    assert "dnd_assistant.composition.bootstrap_completion" in modules
    assert not any(_is_or_under(m, "textual") for m in modules)
    assert "dnd_assistant.storage.vault_repository" not in modules
    assert not _write_offenders(FINALIZE_CLI)


def test_time_cli_imports_composition_and_is_model_free() -> None:
    modules = _imports(TIME_CLI)
    assert "dnd_assistant.composition.world_time" in modules
    assert not any(_is_or_under(m, "textual") for m in modules)
    assert not any(_is_or_under(m, "dnd_assistant.models") for m in modules)
    assert not _write_offenders(TIME_CLI)


def test_main_cli_registers_time_and_finalize() -> None:
    source = MAIN_CLI.read_text(encoding="utf-8")
    assert "register_bootstrap_finalize_command" in source
    assert "time_app" in source
