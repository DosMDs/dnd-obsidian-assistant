"""Contract tests: provider-neutral eval package boundary (S14-02).

``dnd_assistant.evals`` must be a deterministic, provider-neutral package.
Its source may import the Python standard library and its own
``dnd_assistant.evals`` modules only.  It must not import any other
``dnd_assistant`` layer (including ``domain``), any concrete provider/framework,
any HTTP client, and must not read environment/config at import time.

It must also never classify WRITE by tool-name prefix.

Checks are static (AST and source text over ``src/dnd_assistant/evals``) and
read-only: no Git, no shell, no network, no clean-import harness changes.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = REPO_ROOT / "src" / "dnd_assistant"
EVALS_ROOT = SRC_ROOT / "evals"

ALLOWED_DND_PACKAGE = "dnd_assistant.evals"

FORBIDDEN_IMPORT_ROOTS = (
    "ollama",
    "pydantic_ai",
    "textual",
    "typer",
    "httpx",
    "respx",
)

_ENV_ATTRIBUTES = frozenset({"environ", "getenv", "putenv"})


def _evals_files() -> list[Path]:
    files = sorted(EVALS_ROOT.rglob("*.py"))
    assert files, f"expected eval package files under {EVALS_ROOT}"
    return files


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _module_import_targets(tree: ast.Module) -> set[str]:
    """Return every absolute module name imported at any nesting depth."""
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            targets.add(node.module)
    return targets


def _is_or_under(module: str, package: str) -> bool:
    return module == package or module.startswith(f"{package}.")


def _env_access_offenders(tree: ast.Module) -> list[str]:
    offenders: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and node.attr in _ENV_ATTRIBUTES
        ):
            offenders.append(f"os.{node.attr}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "load_dotenv":
                offenders.append("load_dotenv")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "load_dotenv"
        ):
            offenders.append("load_dotenv")
    return offenders


def _write_prefix_offenders(tree: ast.Module) -> list[str]:
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                node.func.attr == "startswith"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "write_"
            ):
                offenders.append("startswith('write_')")
        elif isinstance(node, ast.Constant) and node.value == "write_":
            offenders.append("literal 'write_'")
    return offenders


# ── Import boundary ────────────────────────────────────────────────────────


def test_evals_does_not_import_foreign_packages() -> None:
    offenders: list[str] = []
    for path in _evals_files():
        for target in _module_import_targets(_parse(path)):
            root = target.split(".")[0]
            if root in FORBIDDEN_IMPORT_ROOTS:
                offenders.append(f"{path.relative_to(REPO_ROOT)} imports {target}")
    assert not offenders, f"evals imports forbidden provider/framework packages: {offenders}"


def test_evals_does_not_import_other_dnd_assistant_layers() -> None:
    offenders: list[str] = []
    for path in _evals_files():
        for target in _module_import_targets(_parse(path)):
            if not _is_or_under(target, "dnd_assistant"):
                continue
            if not _is_or_under(target, ALLOWED_DND_PACKAGE):
                offenders.append(f"{path.relative_to(REPO_ROOT)} imports {target}")
    assert not offenders, f"evals imports other dnd_assistant layers: {offenders}"


def test_evals_does_not_read_environment() -> None:
    offenders: list[str] = []
    for path in _evals_files():
        found = _env_access_offenders(_parse(path))
        if found:
            offenders.append(f"{path.relative_to(REPO_ROOT)}: {sorted(found)}")
    assert not offenders, f"evals reads environment/config at import time: {offenders}"


# ── WRITE classification boundary ──────────────────────────────────────────


def test_evals_never_infers_write_from_name_prefix() -> None:
    offenders: list[str] = []
    for path in _evals_files():
        found = _write_prefix_offenders(_parse(path))
        if found:
            offenders.append(f"{path.relative_to(REPO_ROOT)}: {sorted(found)}")
    assert not offenders, f"evals infers WRITE from tool-name prefix: {offenders}"


# ── Detector self-tests (the guard must not be vacuous) ─────────────────────


def test_detector_recognizes_forbidden_imports(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import httpx\n"
        "from ollama import Client\n"
        "from dnd_assistant.tools.registry import ToolRegistry\n",
        encoding="utf-8",
    )
    targets = _module_import_targets(_parse(sample))
    roots = {t.split(".")[0] for t in targets}
    assert {"httpx", "ollama"} <= roots
    assert any(t.startswith("dnd_assistant.") for t in targets)


def test_detector_ignores_relative_and_own_imports(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from .contracts import Thing\nfrom dnd_assistant.evals.scoring import score_decision\n",
        encoding="utf-8",
    )
    targets = _module_import_targets(_parse(sample))
    allowed = {t for t in targets if t.startswith("dnd_assistant")}
    assert all(_is_or_under(t, ALLOWED_DND_PACKAGE) for t in allowed)


def test_detector_recognizes_env_and_write_prefix(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import os\nx = os.environ.get('A')\ny = name.startswith('write_')\n",
        encoding="utf-8",
    )
    tree = _parse(sample)
    assert _env_access_offenders(tree)
    assert _write_prefix_offenders(tree)
