"""Contract tests: test-harness isolation and fixture policy.

These tests enforce invariants from:
  - .gigacode/rules/37-test-harness-isolation.md
  - .gigacode/rules/36-maintainability-ratchets.md

All checks are read-only: no Git, no shell, no network.
"""

from __future__ import annotations

import ast
from pathlib import Path

# ── Repository root discovery ────────────────────────────────────────────

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
TESTS_ROOT = REPO_ROOT / "tests"


# ── Helpers ──────────────────────────────────────────────────────────────


def _relative_path(full_path: Path) -> str:
    """Return path relative to tests root, using forward slashes."""
    return str(full_path.relative_to(TESTS_ROOT)).replace("\\", "/")


def _collect_py_files(root: Path) -> list[Path]:
    """Collect all .py files under root, recursively."""
    if not root.is_dir():
        return []
    return sorted(root.rglob("*.py"))


def _read_source(path: Path) -> str:
    """Read a Python source file as text."""
    return path.read_text(encoding="utf-8")


def _parse_ast(path: Path) -> ast.Module:
    """Parse a Python file into an AST."""
    return ast.parse(_read_source(path), filename=str(path))


def _find_function_def(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    """Find a top-level function definition by name."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _find_class_def(tree: ast.Module, name: str) -> ast.ClassDef | None:
    """Find a top-level class definition by name."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def _has_autouse_decorator(func_node: ast.FunctionDef) -> bool:
    """Check if a function definition has an @pytest.fixture(autouse=True) decorator."""
    for dec in func_node.decorator_list:
        if isinstance(dec, ast.Call):
            func = dec.func
            # pytest.fixture(autouse=True)
            if isinstance(func, ast.Attribute) and func.attr == "fixture":
                for kw in dec.keywords:
                    if (
                        kw.arg == "autouse"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value is True
                    ):
                        return True
            # @pytest.fixture with autouse via ast.Name
            if isinstance(func, ast.Name) and func.id == "fixture":
                for kw in dec.keywords:
                    if (
                        kw.arg == "autouse"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value is True
                    ):
                        return True
    return False


def _is_fixture_decorator(func_node: ast.FunctionDef) -> bool:
    """Check if a function definition has a @pytest.fixture decorator."""
    for dec in func_node.decorator_list:
        if isinstance(dec, ast.Attribute) and dec.attr == "fixture":
            return True
        if isinstance(dec, ast.Name) and dec.id == "fixture":
            return True
        if isinstance(dec, ast.Call):
            func = dec.func
            if isinstance(func, ast.Attribute) and func.attr == "fixture":
                return True
            if isinstance(func, ast.Name) and func.id == "fixture":
                return True
    return False


# ── Tests: restoration fixture uniqueness ────────────────────────────────


class TestRestorationFixtureUniqueness:
    """The restoration fixture implementation must be defined only in conftest.py.

    No other test module should define a function named
    ``restore_dnd_assistant_modules``.
    """

    EXCLUDED = {"conftest.py"}

    def _collect_candidate_files(self) -> list[Path]:
        """Collect test .py files excluding conftest.py at any level."""
        result = []
        for f in _collect_py_files(TESTS_ROOT):
            if f.name == "conftest.py":
                continue
            result.append(f)
        return result

    def test_no_duplicate_definition(self) -> None:
        """No test file outside conftest.py defines restore_dnd_assistant_modules."""
        violations = []
        for f in self._collect_candidate_files():
            tree = _parse_ast(f)
            func = _find_function_def(tree, "restore_dnd_assistant_modules")
            if func is not None:
                violations.append(_relative_path(f))
        assert not violations, (
            f"restore_dnd_assistant_modules is duplicated in: {violations}. "
            "The fixture must only be defined in tests/conftest.py."
        )


# ── Tests: opt-in usage sanity ───────────────────────────────────────────


class TestRestorationOptInUsage:
    """Verify current clean-import tests explicitly opt in to the fixture.

    This test documents the current accepted opt-in modules/classes from
    S7-C12. It fails if a module that uses the fixture is removed from the
    list (indicating a regression) or if a new module uses the fixture
    without being added here (indicating undocumented scope change).
    """

    # Modules that use restore_dnd_assistant_modules via module-level pytestmark
    MODULE_LEVEL_OPTIIN: set[str] = {
        "contract/test_boundaries.py",
    }

    # (module_path, class_name) tuples that use it via @pytest.mark.usefixtures
    CLASS_LEVEL_OPTIIN: set[tuple[str, str]] = {
        ("unit/test_calendar_contracts.py", "TestImportBoundaries"),
        ("unit/test_calendar_conversion.py", "TestImportBoundaries"),
        ("unit/test_cli_session.py", "TestCliSessionBoundaries"),
        ("unit/test_calendar_conversion.py", "TestBoundaries"),
        ("unit/test_retrieval_contracts.py", "TestBoundaries"),
        ("unit/test_storage_paths.py", "TestPathsImportBoundaries"),
        ("unit/test_storage_types.py", "TestStorageTypesImportBoundaries"),
        ("unit/test_storage_markdown.py", "TestMarkdownImportBoundaries"),
        ("unit/test_storage_atomic.py", "TestAtomicImportBoundaries"),
        ("unit/test_session_storage_paths.py", "TestSessionPathsImportBoundaries"),
    }

    def test_known_module_level_optins(self) -> None:
        """All module-level opt-in files are accounted for."""
        actual: set[str] = set()
        for f in _collect_py_files(TESTS_ROOT):
            src = _read_source(f)
            if "restore_dnd_assistant_modules" in src:
                # Check if it's module-level pytestmark
                tree = _parse_ast(f)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name) and target.id == "pytestmark":
                                actual.add(_relative_path(f))
        # Every actual module-level opt-in must be in the known set
        for p in actual:
            assert p in self.MODULE_LEVEL_OPTIIN, (
                f"{p} uses module-level restore_dnd_assistant_modules but is not "
                "in MODULE_LEVEL_OPTIIN. Add it or verify it's intentional."
            )

    def test_known_class_level_optins(self) -> None:
        """All class-level opt-in usages are accounted for."""
        actual: set[tuple[str, str]] = set()
        for f in _collect_py_files(TESTS_ROOT):
            tree = _parse_ast(f)
            rel = _relative_path(f)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.ClassDef):
                    for dec in node.decorator_list:
                        if self._is_usefixtures_restore(dec):
                            actual.add((rel, node.name))
        for entry in actual:
            assert entry in self.CLASS_LEVEL_OPTIIN, (
                f"{entry[0]}::{entry[1]} uses restore_dnd_assistant_modules "
                "but is not in CLASS_LEVEL_OPTIIN. Add it or verify it's intentional."
            )

    @staticmethod
    def _is_usefixtures_restore(dec: ast.expr) -> bool:
        """Check if a decorator is @pytest.mark.usefixtures('restore_dnd_assistant_modules')."""
        if not isinstance(dec, ast.Call):
            return False
        func = dec.func
        if not (isinstance(func, ast.Attribute) and func.attr == "usefixtures"):
            return False
        for arg in dec.args:
            if isinstance(arg, ast.Constant) and arg.value == "restore_dnd_assistant_modules":
                return True
        return False


# ── Tests: root conftest restoration fixture ─────────────────────────────


class TestRootRestorationFixture:
    """Verify the root conftest restoration fixture policy."""

    CONFTEST_PATH = TESTS_ROOT / "conftest.py"

    def test_restore_fixture_exists(self) -> None:
        """restore_dnd_assistant_modules must exist as a fixture."""
        tree = _parse_ast(self.CONFTEST_PATH)
        func = _find_function_def(tree, "restore_dnd_assistant_modules")
        assert func is not None, (
            "restore_dnd_assistant_modules fixture not found in tests/conftest.py"
        )
        assert _is_fixture_decorator(func), (
            "restore_dnd_assistant_modules must be a @pytest.fixture"
        )

    def test_restore_fixture_not_autouse(self) -> None:
        """restore_dnd_assistant_modules must NOT be declared with autouse=True."""
        tree = _parse_ast(self.CONFTEST_PATH)
        func = _find_function_def(tree, "restore_dnd_assistant_modules")
        assert func is not None
        assert not _has_autouse_decorator(func), (
            "restore_dnd_assistant_modules must not use autouse=True. "
            "It must remain opt-in via explicit usefixtures."
        )
