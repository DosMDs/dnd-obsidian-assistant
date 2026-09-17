"""Contract tests: Textual presentation-boundary guard (TUI-01).

These tests enforce the accepted ADR-0008 dependency direction: Textual is a
presentation-only mechanism, so trusted lower layers must never import it.

They are deliberately static (AST over source files) rather than runtime
clean-import checks: ``tests/contract/test_boundaries.py`` is at its hard
1000-line ceiling and ``tests/contract/test_test_harness_policy.py`` owns an
exact allowlist of clean-import opt-ins. This module therefore introduces no new
clean-import scope and no harness change.

All checks are read-only: no Git, no shell, no network.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = REPO_ROOT / "src" / "dnd_assistant"
PYPROJECT = REPO_ROOT / "pyproject.toml"

# ADR-0008: these layers must never depend on Textual.
TRUSTED_LAYERS: tuple[str, ...] = (
    "domain",
    "storage",
    "tools",
    "models",
    "application",
)

FORBIDDEN_ROOT = "textual"


def _import_roots(path: Path) -> set[str]:
    """Return the set of top-level module roots imported by a Python file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def _trusted_layer_files() -> list[Path]:
    files: list[Path] = []
    for layer in TRUSTED_LAYERS:
        layer_dir = SRC_ROOT / layer
        assert layer_dir.is_dir(), f"expected trusted layer directory: {layer_dir}"
        files.extend(sorted(layer_dir.rglob("*.py")))
    return files


# ── Pinning ──────────────────────────────────────────────────────────────────


def test_textual_is_pinned_exactly() -> None:
    """TUI-01 pins an exact Textual release (dependency qualification result)."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    deps: list[str] = data["project"]["dependencies"]
    textual_deps = [dep for dep in deps if dep.replace(" ", "").startswith("textual==")]
    assert textual_deps, f"no exact textual pin in project dependencies: {deps}"
    assert len(textual_deps) == 1, f"ambiguous textual pins: {textual_deps}"


# ── Trusted-layer boundary ───────────────────────────────────────────────────


def test_trusted_layers_do_not_import_textual() -> None:
    """No domain/storage/tools/models/application module imports Textual."""
    offenders: list[str] = []
    for path in _trusted_layer_files():
        if FORBIDDEN_ROOT in _import_roots(path):
            offenders.append(str(path.relative_to(REPO_ROOT)).replace("\\", "/"))
    assert not offenders, f"trusted layers import textual: {offenders}"


# ── Detector self-tests (the guard must not be vacuous) ──────────────────────


def test_detector_recognizes_textual_import(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("import textual\nfrom textual.widgets import Input\n", encoding="utf-8")
    assert FORBIDDEN_ROOT in _import_roots(sample)


def test_detector_ignores_unrelated_and_relative_imports(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import textwrap\nfrom .textual_helpers import thing\nfrom my_textual import x\n",
        encoding="utf-8",
    )
    assert FORBIDDEN_ROOT not in _import_roots(sample)
