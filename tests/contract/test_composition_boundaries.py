"""Contract tests: shared composition dependency-direction guard (TUI-02).

These tests enforce the accepted TUI-02 boundary:

    cli / future tui
            |
    composition
            |
    application / storage / retrieval / tools / models

Forbidden reverse direction:

    domain      -> composition
    application -> composition
    storage     -> composition
    retrieval   -> composition
    tools       -> composition
    models      -> composition

Forbidden forward direction:

    composition -> cli
    composition -> typer
    composition -> textual

Checks are deliberately static (AST over source files) and read-only: no Git,
no shell, no network, no clean-import harness allowlist change.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = REPO_ROOT / "src" / "dnd_assistant"
COMPOSITION_ROOT = SRC_ROOT / "composition"

COMPOSITION_PACKAGE = "dnd_assistant.composition"
CLI_PACKAGE = "dnd_assistant.cli"

# Every trusted lower layer that must never import composition.
TRUSTED_LAYERS: tuple[str, ...] = (
    "domain",
    "storage",
    "tools",
    "models",
    "application",
    "retrieval",
)

FORBIDDEN_COMPOSITION_ROOTS = ("typer", "textual")


def _module_import_targets(path: Path) -> set[str]:
    """Return every absolute module name imported at any nesting depth."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            targets.add(node.module)
    return targets


def _composition_files() -> list[Path]:
    files = sorted(COMPOSITION_ROOT.rglob("*.py"))
    assert files, f"expected composition package files under {COMPOSITION_ROOT}"
    return files


def _trusted_layer_files() -> list[Path]:
    files: list[Path] = []
    for layer in TRUSTED_LAYERS:
        layer_dir = SRC_ROOT / layer
        assert layer_dir.is_dir(), f"expected trusted layer directory: {layer_dir}"
        files.extend(sorted(layer_dir.rglob("*.py")))
    return files


def _is_or_under(module: str, package: str) -> bool:
    return module == package or module.startswith(f"{package}.")


# ── Composition must not depend on presentation ──────────────────────────────


def test_composition_does_not_import_cli_typer_or_textual() -> None:
    offenders: list[str] = []
    for path in _composition_files():
        for target in _module_import_targets(path):
            root = target.split(".")[0]
            if root in FORBIDDEN_COMPOSITION_ROOTS or _is_or_under(target, CLI_PACKAGE):
                offenders.append(f"{path.relative_to(REPO_ROOT)} imports {target}")
    assert not offenders, f"composition imports forbidden presentation: {offenders}"


def test_composition_init_has_no_eager_internal_imports() -> None:
    init = COMPOSITION_ROOT / "__init__.py"
    assert init.is_file(), f"missing composition package marker: {init}"
    targets = _module_import_targets(init)
    internal = sorted(t for t in targets if t.startswith("dnd_assistant"))
    assert not internal, f"composition/__init__.py eagerly imports: {internal}"


# ── Trusted lower layers must not depend on composition ──────────────────────


def test_trusted_layers_do_not_import_composition() -> None:
    offenders: list[str] = []
    for path in _trusted_layer_files():
        for target in _module_import_targets(path):
            if _is_or_under(target, COMPOSITION_PACKAGE):
                offenders.append(f"{path.relative_to(REPO_ROOT)} imports {target}")
    assert not offenders, f"trusted layers import composition: {offenders}"


# ── CLI is the intended consumer of the shared boundary ──────────────────────


def test_cli_agent_runtime_reexports_composition() -> None:
    """The CLI compatibility module must delegate to the real composition owner."""
    shim = SRC_ROOT / "cli" / "agent_runtime.py"
    assert shim.is_file(), f"missing CLI re-export module: {shim}"
    targets = _module_import_targets(shim)
    assert any(_is_or_under(t, COMPOSITION_PACKAGE) for t in targets), (
        f"cli/agent_runtime.py does not import composition: {sorted(targets)}"
    )


# ── Detector self-tests (the guard must not be vacuous) ──────────────────────


def test_detector_recognizes_forbidden_imports(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import typer\n"
        "from textual.widgets import Input\n"
        "from dnd_assistant.cli.session import thing\n",
        encoding="utf-8",
    )
    targets = _module_import_targets(sample)
    roots = {t.split(".")[0] for t in targets}
    assert {"typer", "textual"} <= roots
    assert any(_is_or_under(t, CLI_PACKAGE) for t in targets)


def test_detector_recognizes_composition_import(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def f():\n"
        "    from dnd_assistant.composition.agent_runtime import compose_ask_runtime\n"
        "    return compose_ask_runtime\n",
        encoding="utf-8",
    )
    targets = _module_import_targets(sample)
    assert any(_is_or_under(t, COMPOSITION_PACKAGE) for t in targets)


def test_detector_ignores_unrelated_and_relative_imports(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import textwrap\nfrom .composition_helpers import thing\nfrom my_composition import x\n",
        encoding="utf-8",
    )
    targets = _module_import_targets(sample)
    assert not any(_is_or_under(t, COMPOSITION_PACKAGE) for t in targets)
    assert not any(t.split(".")[0] in FORBIDDEN_COMPOSITION_ROOTS for t in targets)
