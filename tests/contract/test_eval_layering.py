"""Contract tests: eval composition/CLI layering and artifact safety (S14-06).

Static (AST / source text) and read-only: no Git, no shell, no network.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = REPO_ROOT / "src" / "dnd_assistant"
EVALS_ROOT = SRC_ROOT / "evals"
COMPOSITION_ROOT = SRC_ROOT / "composition"

_FILESYSTEM_OR_NETWORK_MODULES = frozenset(
    {"pathlib", "tempfile", "sqlite3", "socket", "urllib", "requests", "httpx", "os"}
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            targets.add(node.module)
    return targets


def test_eval_composition_never_imports_cli() -> None:
    offenders: list[str] = []
    for path in sorted(COMPOSITION_ROOT.glob("eval_*.py")):
        for target in _imports(path):
            if target == "dnd_assistant.cli" or target.startswith("dnd_assistant.cli."):
                offenders.append(f"{path.name} imports {target}")
    assert not offenders, offenders


def test_evals_package_has_no_filesystem_or_network_stdlib() -> None:
    offenders: list[str] = []
    for path in sorted(EVALS_ROOT.rglob("*.py")):
        for target in _imports(path):
            root = target.split(".")[0]
            if root in _FILESYSTEM_OR_NETWORK_MODULES:
                offenders.append(f"{path.name} imports {target}")
    assert not offenders, offenders


def test_cli_eval_contains_no_scoring_logic() -> None:
    source = (SRC_ROOT / "cli" / "eval.py").read_text(encoding="utf-8")
    for forbidden in ("summarize_metrics", "score_decision", "score_full_turn", "score_tool_name"):
        assert forbidden not in source, f"cli/eval.py must not reference {forbidden}"


def test_no_system_evals_artifact_path_in_source() -> None:
    offenders: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "_system/evals" in text or "_system\\evals" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, offenders


def test_evals_dataset_module_is_import_safe_without_side_effects() -> None:
    # The dataset module must not open files, start processes or touch the
    # environment at import time.
    path = EVALS_ROOT / "dataset.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "exec", "eval", "compile"}, node.func.id
