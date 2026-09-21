"""Unit tests: atomic eval artifact writing and output-target preflight.

Offline: no Vault, no model, no network.  The preflight must never create,
truncate or replace the final target and must always clean its probe file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dnd_assistant.composition.eval_artifacts import (
    EvalArtifactError,
    preflight_report_target,
    read_report_text,
    write_report_atomic,
)


def test_preflight_missing_parent_raises(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "report.json"
    with pytest.raises(EvalArtifactError, match="does not exist"):
        preflight_report_target(target, overwrite=False)


def test_preflight_target_directory_raises(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    target.mkdir()
    with pytest.raises(EvalArtifactError, match="is a directory"):
        preflight_report_target(target, overwrite=True)


def test_preflight_existing_target_without_overwrite_raises(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    target.write_text("{}", encoding="utf-8")
    with pytest.raises(EvalArtifactError, match="already exists"):
        preflight_report_target(target, overwrite=False)


def test_preflight_existing_target_with_overwrite_passes(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    target.write_text("{}", encoding="utf-8")
    preflight_report_target(target, overwrite=True)
    assert target.read_text(encoding="utf-8") == "{}"


def test_preflight_valid_does_not_create_target(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    preflight_report_target(target, overwrite=False)
    assert not target.exists()


def test_preflight_leaves_no_probe_residue(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    before = sorted(p.name for p in tmp_path.iterdir())
    preflight_report_target(target, overwrite=False)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after == []


def test_preflight_failure_leaves_no_probe_residue(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    target.write_text("{}", encoding="utf-8")
    before = sorted(p.name for p in tmp_path.iterdir())
    with pytest.raises(EvalArtifactError):
        preflight_report_target(target, overwrite=False)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after == ["report.json"]


def test_write_report_atomic_writes(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    write_report_atomic(target, "hello", overwrite=False)
    assert read_report_text(target) == "hello"


def test_write_report_atomic_refuses_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    write_report_atomic(target, "hello", overwrite=False)
    with pytest.raises(EvalArtifactError, match="already exists"):
        write_report_atomic(target, "world", overwrite=False)
    assert read_report_text(target) == "hello"


def test_write_report_atomic_missing_parent_raises(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "report.json"
    with pytest.raises(EvalArtifactError, match="does not exist"):
        write_report_atomic(target, "hello", overwrite=False)


def test_read_report_text_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(EvalArtifactError, match="not found"):
        read_report_text(tmp_path / "absent.json")
