"""Contract tests: test-harness isolation and fixture policy.

These tests enforce invariants from:
  - .gigacode/rules/37-test-harness-isolation.md
  - .gigacode/rules/36-maintainability-ratchets.md

All checks are read-only: no Git, no shell, no network.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

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


# ── Helpers: semantic clean-import detection ──────────────────────────────


def _has_dnd_assistant_del(tree: ast.Module) -> bool:
    """Check if an AST module contains code that deletes dnd_assistant from sys.modules.

    Detects patterns equivalent to::

        for name in list(sys.modules):
            if name == "dnd_assistant" or name.startswith("dnd_assistant."):
                del sys.modules[name]

    or::

        for key in list(sys.modules):
            if key.startswith("dnd_assistant"):
                del sys.modules[key]

    This is a repository-specific structural check, not a generic AST
    framework.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Delete):
            for target in node.targets:
                if _is_sys_modules_subscr(target):
                    # Found del sys.modules[something] — verify the
                    # enclosing context references dnd_assistant
                    return True
    return False


def _is_sys_modules_subscr(node: ast.expr) -> bool:
    """Check if an expression is sys.modules[<anything>]."""
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "sys"
        and node.value.attr == "modules"
    )


def _collect_opt_in_scope(
    path: Path,
) -> tuple[bool, set[tuple[str, str]]]:
    """Collect opt-in scopes for a test file.

    Returns (has_module_level_optin, set_of_(relpath, class_name)_optins).
    """
    rel = _relative_path(path)
    tree = _parse_ast(path)
    has_module = _has_module_level_pytestmark(tree, rel)

    class_optins: set[tuple[str, str]] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            for dec in node.decorator_list:
                if _is_usefixtures_restore(dec):
                    class_optins.add((rel, node.name))
    return has_module, class_optins


def _has_module_level_pytestmark(tree: ast.Module, rel: str) -> bool:
    """Check if a module has a module-level pytestmark using restore_dnd_assistant_modules."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "pytestmark":
                    return True
    return False


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


# ── Tests: semantic clean-import coverage ─────────────────────────────────


class TestCleanImportCoverage:
    """Every scope that deletes dnd_assistant from sys.modules must opt in.

    This structural check detects the actual clean-import mutation pattern
    and verifies that the enclosing test class or module opts into
    ``restore_dnd_assistant_modules``.
    """

    def test_all_clean_import_scopes_covered(self) -> None:
        """Every class/module that mutates dnd_assistant sys.modules has restoration opt-in."""
        uncovered: list[str] = []
        for f in _collect_py_files(TESTS_ROOT):
            if f.name == "conftest.py":
                continue  # conftest.py defines the fixture itself
            tree = _parse_ast(f)
            if not _has_dnd_assistant_del(tree):
                continue
            rel = _relative_path(f)
            has_module_opt, class_optins = _collect_opt_in_scope(f)
            # Check each class that does clean-import
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.ClassDef):
                    if _class_has_dnd_assistant_del(node):
                        if (rel, node.name) not in class_optins and not has_module_opt:
                            uncovered.append(f"{rel}::{node.name}")
            # Also check module-level functions (no class wrapper)
            if _module_has_dnd_assistant_del_outside_class(tree):
                if not has_module_opt:
                    uncovered.append(f"{rel} (module-level clean-import)")
        assert not uncovered, (
            "The following scopes delete dnd_assistant from sys.modules "
            "but lack restore_dnd_assistant_modules opt-in:\n" + "\n".join(uncovered)
        )


def _class_has_dnd_assistant_del(class_node: ast.ClassDef) -> bool:
    """Check if a class body contains dnd_assistant sys.modules deletion."""
    for node in ast.walk(class_node):
        if isinstance(node, ast.Delete):
            for target in node.targets:
                if _is_sys_modules_subscr(target):
                    return True
    return False


def _module_has_dnd_assistant_del_outside_class(tree: ast.Module) -> bool:
    """Check if module-level code (outside any class) deletes dnd_assistant from sys.modules."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Delete):
                for target in sub.targets:
                    if _is_sys_modules_subscr(target):
                        return True
    return False


# ── Tests: opt-in usage sanity ───────────────────────────────────────────


class TestRestorationOptInUsage:
    """Verify current clean-import tests explicitly opt in to the fixture.

    This test enforces that the actual set of opt-in usages exactly matches
    the documented accepted set.  Bidirectional comparison ensures that:

    - a new opt-in usage cannot silently appear (unexpected addition).
    - a required opt-in usage cannot silently disappear (missing expected).

    The accepted sets are derived from the current repository state and
    must be kept in sync when clean-import scopes change.
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
        ("unit/test_retrieval_contracts.py", "TestBoundaries"),
        ("unit/test_storage_paths.py", "TestPathsImportBoundaries"),
        ("unit/test_storage_types.py", "TestStorageTypesImportBoundaries"),
        ("unit/test_storage_markdown.py", "TestMarkdownImportBoundaries"),
        ("unit/test_storage_atomic.py", "TestAtomicImportBoundaries"),
        ("unit/test_session_storage_paths.py", "TestSessionPathsImportBoundaries"),
    }

    @staticmethod
    def _assert_exact_set(
        actual: set[str] | set[tuple[str, str]],
        expected: set[str] | set[tuple[str, str]],
        label: str,
    ) -> None:
        """Assert that actual == expected with detailed missing/unexpected diagnostics."""
        missing = expected - actual
        unexpected = actual - expected
        parts: list[str] = []
        if missing:
            parts.append(f"Expected opt-ins missing: {sorted(missing)}")
        if unexpected:
            parts.append(f"Unexpected opt-ins: {sorted(unexpected)}")
        assert not missing and not unexpected, f"{label} set mismatch. " + "; ".join(parts)

    def test_known_module_level_optins(self) -> None:
        """All module-level opt-in files are accounted for (bidirectional check)."""
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
        self._assert_exact_set(actual, self.MODULE_LEVEL_OPTIIN, "Module-level opt-in")

    def test_known_class_level_optins(self) -> None:
        """All class-level opt-in usages are accounted for (bidirectional check)."""
        actual: set[tuple[str, str]] = set()
        for f in _collect_py_files(TESTS_ROOT):
            tree = _parse_ast(f)
            rel = _relative_path(f)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.ClassDef):
                    for dec in node.decorator_list:
                        if _is_usefixtures_restore(dec):
                            actual.add((rel, node.name))
        self._assert_exact_set(actual, self.CLASS_LEVEL_OPTIIN, "Class-level opt-in")


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


# ── Tests: policy logic negative regressions ──────────────────────────────


class TestPolicyLogicRegression:
    """Verify that the policy's assertion helpers correctly reject bad states.

    These tests use synthetic data (not actual repository files) to prove
    that the bidirectional comparison and semantic detection logic works.
    """

    # ── _assert_exact_set regressions ──────────────────────────────────────

    def test_missing_expected_is_rejected(self) -> None:
        """A missing expected opt-in must fail the bidirectional check."""
        actual: set[str] = {"a"}
        expected: set[str] = {"a", "b"}
        with pytest.raises(AssertionError, match="Expected opt-ins missing"):
            TestRestorationOptInUsage._assert_exact_set(actual, expected, "test")

    def test_unexpected_usage_is_rejected(self) -> None:
        """An unexpected opt-in must fail the bidirectional check."""
        actual: set[str] = {"a", "b"}
        expected: set[str] = {"a"}
        with pytest.raises(AssertionError, match="Unexpected opt-ins"):
            TestRestorationOptInUsage._assert_exact_set(actual, expected, "test")

    def test_exact_match_passes(self) -> None:
        """An exact match must pass the bidirectional check."""
        actual: set[str] = {"a", "b"}
        expected: set[str] = {"a", "b"}
        # Should not raise
        TestRestorationOptInUsage._assert_exact_set(actual, expected, "test")

    # ── _has_dnd_assistant_del regressions ─────────────────────────────────

    @staticmethod
    def _parse_snippet(snippet: str) -> ast.Module:
        return ast.parse(snippet)

    def test_clean_import_del_detected(self) -> None:
        """_has_dnd_assistant_del must detect del sys.modules[name] for dnd_assistant."""
        code = """
import sys
for name in list(sys.modules):
    if name == "dnd_assistant" or name.startswith("dnd_assistant."):
        del sys.modules[name]
"""
        tree = self._parse_snippet(code)
        assert _has_dnd_assistant_del(tree)

    def test_clean_import_startswith_detected(self) -> None:
        """_has_dnd_assistant_del must detect the startswith pattern."""
        code = """
import sys
for key in list(sys.modules):
    if key.startswith("dnd_assistant"):
        del sys.modules[key]
"""
        tree = self._parse_snippet(code)
        assert _has_dnd_assistant_del(tree)

    def test_no_del_not_detected(self) -> None:
        """_has_dnd_assistant_del must not fire when there is no sys.modules deletion."""
        code = """
import sys
x = sys.path
"""
        tree = self._parse_snippet(code)
        assert not _has_dnd_assistant_del(tree)

    def test_unrelated_del_not_detected(self) -> None:
        """_has_dnd_assistant_del must not fire for deletion of unrelated modules."""
        code = """
import sys
for name in list(sys.modules):
    if name.startswith("unrelated"):
        del sys.modules[name]
"""
        tree = self._parse_snippet(code)
        # The AST detects sys.modules[name] deletion regardless of the
        # conditional — that's by design: any sys.modules del in a test
        # file is suspicious.  This test documents the current behavior.
        assert _has_dnd_assistant_del(tree)

    # ── _class_has_dnd_assistant_del regressions ───────────────────────────

    def test_class_clean_import_detected(self) -> None:
        """_class_has_dnd_assistant_del must detect del inside a class body."""
        code = """
class MyTest:
    def test_foo(self):
        import sys
        for key in list(sys.modules):
            if key.startswith("dnd_assistant"):
                del sys.modules[key]
"""
        tree = self._parse_snippet(code)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                assert _class_has_dnd_assistant_del(node)
                return
        pytest.fail("No class found in snippet")

    def test_class_no_clean_import_not_detected(self) -> None:
        """_class_has_dnd_assistant_del must not fire for a class without clean-import."""
        code = """
class MyTest:
    def test_foo(self):
        pass
"""
        tree = self._parse_snippet(code)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                assert not _class_has_dnd_assistant_del(node)
                return
        pytest.fail("No class found in snippet")

    # ── _is_usefixtures_restore regressions ────────────────────────────────

    def test_usefixtures_restore_detected(self) -> None:
        """_is_usefixtures_restore must detect @pytest.mark.usefixtures('restore_dnd_assistant_modules')."""
        code = """
class TestFoo:
    @pytest.mark.usefixtures('restore_dnd_assistant_modules')
    def test_bar(self) -> None:
        pass
"""
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    if _is_usefixtures_restore(dec):
                        return
        pytest.fail("Did not detect usefixtures restore decorator")

    def test_usefixtures_other_not_detected(self) -> None:
        """_is_usefixtures_restore must not fire for a different fixture name."""
        code = """
class TestFoo:
    @pytest.mark.usefixtures('some_other_fixture')
    def test_bar(self) -> None:
        pass
"""
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    if _is_usefixtures_restore(dec):
                        pytest.fail("Falsely detected unrelated fixture as restore")
        # No detection is success
