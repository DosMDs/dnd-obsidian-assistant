"""Contract tests: repository maintainability ratchet.

These tests enforce:
1. Production modules do not exceed the hard line-count limit (700 lines)
   unless explicitly exempted as legacy exceptions.
2. Test modules do not exceed the hard line-count limit (1000 lines)
   unless explicitly exempted as legacy exceptions.
3. New correction-history test filenames (e.g. _c06, _fix2) are prohibited.

The ratchet is monotonic: legacy oversized files may shrink but must not
silently grow beyond their recorded baseline.

All checks are read-only: no Git, no shell, no network.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

# ── Repository root discovery ────────────────────────────────────────────

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent


def _physical_lines(path: Path) -> int:
    """Count physical lines in a Python file."""
    return sum(1 for _ in path.read_bytes().splitlines())


# ── Hard limits ──────────────────────────────────────────────────────────

PRODUCTION_HARD_LIMIT = 700
TEST_HARD_LIMIT = 1000

# ── Source tree roots ────────────────────────────────────────────────────

PRODUCTION_ROOT = REPO_ROOT / "src" / "dnd_assistant"
TEST_ROOT = REPO_ROOT / "tests"

# ── Legacy exception maps ────────────────────────────────────────────────
# These files exceed the hard limit and are pinned at their current size.
# They may shrink but must not grow.

PRODUCTION_LEGACY_EXCEPTIONS: dict[str, int] = {
    "storage/session_recovery.py": 1947,
    "storage/vault_repository.py": 1379,
    "domain/calendar.py": 1295,
    "storage/session_metadata.py": 1138,
    "storage/session_events.py": 1096,
    "storage/world_time.py": 834,
    "storage/types.py": 741,
}

TEST_LEGACY_EXCEPTIONS: dict[str, int] = {
    "unit/test_retrieval_contracts.py": 1477,
    "unit/test_storage_append_fact.py": 1229,
    "unit/test_fts_index.py": 1171,
    "unit/test_session_metadata.py": 1112,
    "unit/test_storage_patch_repository.py": 1103,
    "unit/test_storage_vault_repository.py": 1102,
}

# ── Legacy correction-specific test filename allowlist ───────────────────
# These files use correction-history naming and are permitted only because
# they existed at MNT-01 baseline. New such names are prohibited.

LEGACY_CORRECTION_FILENAMES: set[str] = {
    "test_session_events_c03.py",
    "test_session_events_c03f.py",
    "test_session_recovery_c05.py",
    "test_session_recovery_c05f.py",
}


# ── Helpers ──────────────────────────────────────────────────────────────


def _relative_path(root: Path, full_path: Path) -> str:
    """Return path relative to the given root, using forward slashes."""
    return str(full_path.relative_to(root)).replace("\\", "/")


def _collect_py_files(root: Path) -> list[Path]:
    """Collect all .py files under root, recursively."""
    if not root.is_dir():
        return []
    return sorted(root.rglob("*.py"))


def _is_correction_filename(name: str) -> bool:
    """Check if a filename matches a correction-history pattern.

    Matches patterns like _cNN, _cNNf, _fixN, _followup, _final
    where N is one or more digits.
    """
    stem = Path(name).stem
    # Remove test_ prefix for matching
    core = stem.removeprefix("test_")
    import re

    return bool(re.search(r"_(?:c\d+[a-z]*|fix\d+|followup|final)$", core))


def _line_count_baseline(
    rel_path: str,
    legacy_map: dict[str, int],
    hard_limit: int,
) -> int:
    """Return the maximum allowed line count for a given relative path.

    Legacy files use their pinned baseline; all others use hard_limit.
    """
    return legacy_map.get(rel_path, hard_limit)


# ── Tests ────────────────────────────────────────────────────────────────


class TestProductionModuleSize:
    """Every production module must not exceed its size baseline."""

    PRODUCTION_FILES: ClassVar[list[Path]] = _collect_py_files(PRODUCTION_ROOT)

    @pytest.mark.parametrize(
        "file_path",
        PRODUCTION_FILES,
        ids=lambda p: _relative_path(PRODUCTION_ROOT, p),
    )
    def test_production_module_within_limit(self, file_path: Path) -> None:
        rel = _relative_path(PRODUCTION_ROOT, file_path)
        baseline = _line_count_baseline(rel, PRODUCTION_LEGACY_EXCEPTIONS, PRODUCTION_HARD_LIMIT)
        lines = _physical_lines(file_path)
        assert lines <= baseline, (
            f"{rel} has {lines} lines, exceeds baseline of {baseline}. "
            "Either decompose the module or update the legacy exception "
            "with architectural justification."
        )


class TestCorrectionFilenames:
    """New correction-history test filenames are prohibited.

    Only the legacy allowlist from MNT-01 baseline is permitted.
    """

    TEST_FILES: ClassVar[list[Path]] = _collect_py_files(TEST_ROOT)

    @pytest.mark.parametrize(
        "file_path",
        TEST_FILES,
        ids=lambda p: _relative_path(TEST_ROOT, p),
    )
    def test_no_new_correction_filename(self, file_path: Path) -> None:
        name = file_path.name
        if name in LEGACY_CORRECTION_FILENAMES:
            return  # Legacy exception — permitted
        assert not _is_correction_filename(name), (
            f"{_relative_path(TEST_ROOT, file_path)} uses a correction-history "
            f"filename pattern. Add regression tests to the appropriate topical "
            f"test module instead."
        )


class TestTestModuleSize:
    """Every test module must not exceed its size baseline."""

    TEST_FILES: ClassVar[list[Path]] = _collect_py_files(TEST_ROOT)

    @pytest.mark.parametrize(
        "file_path",
        TEST_FILES,
        ids=lambda p: _relative_path(TEST_ROOT, p),
    )
    def test_test_module_within_limit(self, file_path: Path) -> None:
        rel = _relative_path(TEST_ROOT, file_path)
        baseline = _line_count_baseline(rel, TEST_LEGACY_EXCEPTIONS, TEST_HARD_LIMIT)
        lines = _physical_lines(file_path)
        assert lines <= baseline, (
            f"{rel} has {lines} lines, exceeds baseline of {baseline}. "
            "Either decompose the module or update the legacy exception "
            "with architectural justification."
        )


# ── Helper unit tests (synthetic data, no real files modified) ────────────


class TestLineCountBaseline:
    """Verify _line_count_baseline logic."""

    def test_legacy_file_uses_pinned_baseline(self) -> None:
        legacy = {"big.py": 999}
        assert _line_count_baseline("big.py", legacy, 700) == 999

    def test_normal_file_uses_hard_limit(self) -> None:
        legacy = {"big.py": 999}
        assert _line_count_baseline("small.py", legacy, 700) == 700

    def test_empty_legacy_map_falls_back_to_hard_limit(self) -> None:
        assert _line_count_baseline("any.py", {}, 500) == 500


class TestIsCorrectionFilename:
    """Verify _is_correction_filename pattern matching."""

    def test_plain_name_not_correction(self) -> None:
        assert not _is_correction_filename("test_session.py")

    def test_topical_name_not_correction(self) -> None:
        assert not _is_correction_filename("test_session_recovery.py")

    def test_c03_is_correction(self) -> None:
        assert _is_correction_filename("test_session_events_c03.py")

    def test_c03f_is_correction(self) -> None:
        assert _is_correction_filename("test_session_events_c03f.py")

    def test_c05_is_correction(self) -> None:
        assert _is_correction_filename("test_session_recovery_c05.py")

    def test_c05f_is_correction(self) -> None:
        assert _is_correction_filename("test_session_recovery_c05f.py")

    def test_fix2_is_correction(self) -> None:
        assert _is_correction_filename("test_something_fix2.py")

    def test_followup_is_correction(self) -> None:
        assert _is_correction_filename("test_something_followup.py")

    def test_final_is_correction(self) -> None:
        assert _is_correction_filename("test_something_final.py")

    def test_c10_is_correction(self) -> None:
        assert _is_correction_filename("test_session_recovery_c10.py")

    def test_non_test_file_not_correction(self) -> None:
        assert not _is_correction_filename("helper.py")

    def test_no_digit_after_c_not_correction(self) -> None:
        assert not _is_correction_filename("test_session_events_correction.py")


class TestPhysicalLines:
    """Verify _physical_lines helper."""

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.py"
        f.write_text("")
        assert _physical_lines(f) == 0

    def test_single_line(self, tmp_path: Path) -> None:
        f = tmp_path / "single.py"
        f.write_text("x = 1\n")
        assert _physical_lines(f) == 1

    def test_multiple_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "multi.py"
        f.write_text("a\nb\nc\n")
        assert _physical_lines(f) == 3
