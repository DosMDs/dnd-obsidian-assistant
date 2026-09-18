"""Contract tests: S13-02 discovery layer boundaries and read-only guarantees.

Static AST checks only: no clean-import harness, no Git, no shell, no network.
This focused module is used instead of growing ``test_boundaries.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = REPO_ROOT / "src" / "dnd_assistant"

STORAGE_MODULE = SRC_ROOT / "storage" / "vault_discovery.py"
APPLICATION_MODULE = SRC_ROOT / "application" / "vault_discovery.py"

FORBIDDEN = (
    "dnd_assistant.application",
    "dnd_assistant.cli",
    "dnd_assistant.models",
    "dnd_assistant.tools",
    "dnd_assistant.retrieval",
    "ollama",
    "pydantic_ai",
    "textual",
)

APPLICATION_FORBIDDEN = FORBIDDEN + ("yaml", "ruamel")
"""Application additionally must not run any YAML parser (structural probe only)."""

_MUTATION_ATTRS = frozenset(
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


def test_storage_discovery_does_not_import_upper_or_provider_layers() -> None:
    assert not _offenders(STORAGE_MODULE, FORBIDDEN)


def test_storage_discovery_does_not_import_application() -> None:
    assert not _offenders(STORAGE_MODULE, ("dnd_assistant.application",))


def test_application_discovery_does_not_import_forbidden_layers() -> None:
    assert not _offenders(APPLICATION_MODULE, APPLICATION_FORBIDDEN)


def test_application_discovery_does_not_parse_campaign_marker() -> None:
    offenders: list[str] = []
    for node in ast.walk(_tree(APPLICATION_MODULE)):
        if isinstance(node, ast.ImportFrom):
            if node.module and _is_or_under(
                node.module, "dnd_assistant.storage.vault_initialization"
            ):
                offenders.append(node.module)
            for alias in node.names:
                if alias.name in ("vault_initialization", "parse_campaign_config"):
                    offenders.append(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if _is_or_under(alias.name, "dnd_assistant.storage.vault_initialization"):
                    offenders.append(alias.name)
    assert not offenders, (
        f"application discovery must not import the storage marker parser: {offenders}"
    )


def test_application_discovery_has_no_filesystem_authority() -> None:
    modules = _imports(APPLICATION_MODULE)
    offenders = [m for m in modules if m in ("os", "pathlib", "shutil", "io")]
    assert not offenders, (
        f"application discovery must hold no filesystem traversal/IO authority: {offenders}"
    )


def test_application_discovery_does_not_import_repository_or_audit() -> None:
    modules = _imports(APPLICATION_MODULE)
    banned = [
        m
        for m in modules
        if _is_or_under(m, "dnd_assistant.storage.audit")
        or _is_or_under(m, "dnd_assistant.storage.vault_repository")
        or _is_or_under(m, "dnd_assistant.domain.entity")
        or _is_or_under(m, "dnd_assistant.storage.markdown")
    ]
    assert not banned, f"application discovery imports non-ownership modules: {banned}"


def test_application_discovery_reuses_campaign_state_layout_ownership() -> None:
    source = APPLICATION_MODULE.read_text(encoding="utf-8")
    assert "ARTIFACT_FILENAMES" in source
    assert "MANIFEST_FILENAME" in source
    # Must not hardcode the physical derived leaf names independently.
    assert "World State.md" not in source
    assert "Recently Touched.md" not in source


def test_discovery_modules_perform_no_filesystem_mutation() -> None:
    for path in (STORAGE_MODULE, APPLICATION_MODULE):
        offenders = _write_offenders(path)
        assert not offenders, f"{path.name} performs filesystem mutation: {offenders}"
