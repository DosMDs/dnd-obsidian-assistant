"""Contract tests: S13-03 bootstrap mapping layer boundaries.

Static AST checks only: no clean-import harness, no Git, no shell, no network.
This focused module is used instead of growing ``test_boundaries.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = REPO_ROOT / "src" / "dnd_assistant"

DOMAIN_MODULE = SRC_ROOT / "domain" / "bootstrap_extraction.py"

STORAGE_TYPES = SRC_ROOT / "storage" / "bootstrap_types.py"
STORAGE_CANONICAL = SRC_ROOT / "storage" / "bootstrap_canonical.py"
STORAGE_EVIDENCE = SRC_ROOT / "storage" / "bootstrap_evidence.py"

PURE_APPLICATION = (
    SRC_ROOT / "application" / "bootstrap_input.py",
    SRC_ROOT / "application" / "bootstrap_canonical.py",
    SRC_ROOT / "application" / "bootstrap_binding.py",
    SRC_ROOT / "application" / "bootstrap_entity_id.py",
    SRC_ROOT / "application" / "bootstrap_changeset.py",
    SRC_ROOT / "application" / "bootstrap_evidence.py",
    SRC_ROOT / "application" / "bootstrap_extraction.py",
    SRC_ROOT / "application" / "bootstrap_mapping.py",
    SRC_ROOT / "application" / "bootstrap_result.py",
)

ADAPTER_MODULE = SRC_ROOT / "application" / "pydantic_ai_bootstrap.py"
COMPOSITION_MODULE = SRC_ROOT / "composition" / "bootstrap.py"
CLI_MODULE = SRC_ROOT / "cli" / "bootstrap.py"

UPPER_LAYERS = (
    "dnd_assistant.application",
    "dnd_assistant.cli",
    "dnd_assistant.models",
    "dnd_assistant.tools",
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


def test_domain_extraction_is_provider_and_persistence_neutral() -> None:
    assert not _offenders(
        DOMAIN_MODULE,
        (
            "dnd_assistant.storage",
            "dnd_assistant.application",
            "dnd_assistant.models",
            "dnd_assistant.tools",
            "dnd_assistant.retrieval",
            "dnd_assistant.cli",
        ),
    )
    targets = _imports(DOMAIN_MODULE)
    persistence = {"pathlib", "os", "hashlib", "shutil", "tempfile"}
    assert not (targets & persistence)


def test_storage_bootstrap_modules_do_not_import_upper_layers() -> None:
    for path in (STORAGE_TYPES, STORAGE_CANONICAL, STORAGE_EVIDENCE):
        assert not _offenders(path, UPPER_LAYERS), path.name


def test_storage_bootstrap_types_does_not_import_markdown_codec() -> None:
    modules = _imports(STORAGE_TYPES)
    assert not any(_is_or_under(m, "dnd_assistant.storage.markdown") for m in modules)
    assert not any(_is_or_under(m, "ruamel") for m in modules)


def test_pure_application_modules_forbid_provider_and_presentation_layers() -> None:
    forbidden = (
        "dnd_assistant.models",
        "dnd_assistant.tools",
        "dnd_assistant.cli",
        "ollama",
        "pydantic_ai",
        "textual",
    )
    for path in PURE_APPLICATION:
        assert not _offenders(path, forbidden), path.name


def test_pure_application_modules_do_not_parse_yaml_or_touch_filesystem() -> None:
    for path in PURE_APPLICATION:
        modules = _imports(path)
        assert not any(_is_or_under(m, "dnd_assistant.storage.markdown") for m in modules), (
            path.name
        )
        assert not (modules & {"pathlib", "os", "shutil", "tempfile"}), path.name
        assert not _write_offenders(path), path.name


def test_binding_does_not_use_player_search_resolver() -> None:
    modules = _imports(SRC_ROOT / "application" / "bootstrap_binding.py")
    banned = [
        m
        for m in modules
        if m
        in (
            "dnd_assistant.retrieval.resolver",
            "dnd_assistant.retrieval.service",
            "dnd_assistant.retrieval.search",
        )
    ]
    assert not banned


def test_adapter_is_provider_isolated_and_has_no_write_authority() -> None:
    modules = _imports(ADAPTER_MODULE)
    assert not any(_is_or_under(m, "dnd_assistant.storage") for m in modules)
    assert not any(_is_or_under(m, "dnd_assistant.retrieval") for m in modules)
    assert not any(_is_or_under(m, "dnd_assistant.tools") for m in modules)
    assert not any(_is_or_under(m, "dnd_assistant.cli") for m in modules)
    assert not _write_offenders(ADAPTER_MODULE)


def test_composition_does_not_import_presentation() -> None:
    assert not _offenders(COMPOSITION_MODULE, ("dnd_assistant.cli", "typer", "textual"))


def test_cli_bootstrap_imports_composition_and_application() -> None:
    modules = _imports(CLI_MODULE)
    assert "dnd_assistant.composition.bootstrap" in modules


def test_cli_bootstrap_does_not_import_textual_or_storage_mutation() -> None:
    modules = _imports(CLI_MODULE)
    assert not any(_is_or_under(m, "textual") for m in modules)
    assert "dnd_assistant.storage.vault_repository" not in modules
    assert not _write_offenders(CLI_MODULE)
