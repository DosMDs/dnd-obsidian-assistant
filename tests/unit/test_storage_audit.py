"""Tests for AuditRecord schema and AuditService (S3-04)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import pytest
from pydantic import ValidationError

from dnd_assistant.errors import StorageError
from dnd_assistant.storage.audit import AuditRecord, AuditService

# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_log_path(tmp_path: Path, name: str = "audit.jsonl") -> Path:
    """Create a valid audit-log path under ``tmp_path``."""
    parent = tmp_path / "vault"
    parent.mkdir()
    return parent / name


def _valid_record(**overrides: object) -> AuditRecord:
    """Build a minimally valid AuditRecord with optional overrides."""
    kwargs: dict[str, object] = {
        "operation_id": "op-001",
        "real_time": datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC),
        "operation": "create",
        "source": "model_tool",
    }
    kwargs.update(overrides)
    return AuditRecord(**kwargs)  # type: ignore[arg-type]


def _can_symlink() -> bool:
    """Check whether the OS/environment supports symlinks."""
    import tempfile

    tmp = tempfile.mkdtemp()
    try:
        link = os.path.join(tmp, "link")
        target = os.path.join(tmp, "target")
        Path(target).write_text("", encoding="utf-8")
        os.symlink(target, link)
        return True
    except (OSError, NotImplementedError):
        return False
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


# ═════════════════════════════════════════════════════════════════════════════
# AuditRecord schema
# ═════════════════════════════════════════════════════════════════════════════


class TestAuditRecordMinimal:
    """Minimal valid AuditRecord construction."""

    def test_minimal_valid(self) -> None:
        record = _valid_record()
        assert record.operation_id == "op-001"
        assert record.operation == "create"
        assert record.source == "model_tool"
        assert record.schema_version == 1
        assert record.session is None
        assert record.entity_id is None
        assert record.before_hash is None
        assert record.after_hash is None
        assert record.model_profile is None
        assert record.prompt_version is None

    def test_schema_version_default(self) -> None:
        record = _valid_record()
        assert record.schema_version == 1

    def test_schema_version_fixed(self) -> None:
        with pytest.raises(ValidationError):
            _valid_record(schema_version=2)

    def test_timezone_aware_accepted(self) -> None:
        dt = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)
        record = _valid_record(real_time=dt)
        assert record.real_time == dt

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _valid_record(real_time=datetime(2026, 8, 30, 12, 0, 0))


class TestAuditRecordFull:
    """Full AuditRecord with all optional fields."""

    def test_full_record(self) -> None:
        record = _valid_record(
            session="S007",
            entity_id="npc-001",
            before_hash="abc123",
            after_hash="def456",
            model_profile="llama3",
            prompt_version="v2.1",
        )
        assert record.session == "S007"
        assert record.entity_id == "npc-001"
        assert record.before_hash == "abc123"
        assert record.after_hash == "def456"
        assert record.model_profile == "llama3"
        assert record.prompt_version == "v2.1"

    def test_entity_id_validated(self) -> None:
        with pytest.raises(ValidationError):
            _valid_record(entity_id="")

    def test_entity_id_printable_unicode(self) -> None:
        record = _valid_record(entity_id="персонаж-001")
        assert record.entity_id == "персонаж-001"


class TestAuditRecordValidation:
    """Validation of required and optional string fields."""

    # Required fields

    def test_empty_operation_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _valid_record(operation_id="")

    def test_whitespace_operation_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _valid_record(operation_id="  op-001  ")

    def test_non_printable_operation_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _valid_record(operation_id="op\x00id")

    def test_empty_operation_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _valid_record(operation="")

    def test_whitespace_operation_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _valid_record(operation="  create  ")

    def test_non_printable_operation_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _valid_record(operation="create\x01")

    def test_empty_source_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _valid_record(source="")

    def test_whitespace_source_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _valid_record(source="  model_tool  ")

    def test_non_printable_source_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _valid_record(source="model\x08tool")

    # Optional fields

    def test_optional_session_validated_when_present(self) -> None:
        with pytest.raises(ValidationError):
            _valid_record(session="")

    def test_optional_session_whitespace_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _valid_record(session="  S007  ")

    def test_optional_session_none_accepted(self) -> None:
        record = _valid_record(session=None)
        assert record.session is None

    def test_optional_before_hash_validated_when_present(self) -> None:
        with pytest.raises(ValidationError):
            _valid_record(before_hash="")

    def test_optional_after_hash_validated_when_present(self) -> None:
        with pytest.raises(ValidationError):
            _valid_record(after_hash="")

    def test_optional_hash_none_accepted(self) -> None:
        record = _valid_record(before_hash=None, after_hash=None)
        assert record.before_hash is None
        assert record.after_hash is None

    def test_optional_model_profile_validated_when_present(self) -> None:
        with pytest.raises(ValidationError):
            _valid_record(model_profile="")

    def test_optional_prompt_version_validated_when_present(self) -> None:
        with pytest.raises(ValidationError):
            _valid_record(prompt_version="")

    def test_optional_metadata_none_accepted(self) -> None:
        record = _valid_record(model_profile=None, prompt_version=None)
        assert record.model_profile is None
        assert record.prompt_version is None

    def test_unicode_allowed(self) -> None:
        record = _valid_record(
            operation_id="оп-001",
            operation="создать",
            source="инструмент",
            session="Сессия-007",
        )
        assert record.operation_id == "оп-001"
        assert record.operation == "создать"
        assert record.source == "инструмент"
        assert record.session == "Сессия-007"

    def test_unknown_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AuditRecord(
                operation_id="op-001",
                real_time=datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC),
                operation="create",
                source="model_tool",
                unknown_field="should fail",
            )

    def test_source_not_restricted_to_provenance(self) -> None:
        record = _valid_record(source="manual_cli")
        assert record.source == "manual_cli"
        record2 = _valid_record(source="bootstrap_script")
        assert record2.source == "bootstrap_script"

    def test_frozen_immutable(self) -> None:
        record = _valid_record()
        with pytest.raises(ValidationError):
            record.operation_id = "changed"


# ═════════════════════════════════════════════════════════════════════════════
# AuditService — path validation
# ═════════════════════════════════════════════════════════════════════════════


class TestAuditServicePathValidation:
    """AuditService path precondition checks."""

    def test_absolute_path_accepted(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        service = AuditService(log_path)
        assert service.log_path == log_path

    def test_relative_path_rejected(self) -> None:
        with pytest.raises(StorageError, match="must be absolute"):
            AuditService("relative/audit.jsonl")

    def test_missing_parent_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "nonexistent" / "audit.jsonl"
        with pytest.raises(StorageError, match="parent directory does not exist"):
            AuditService(path)

    def test_parent_regular_file_rejected(self, tmp_path: Path) -> None:
        parent = tmp_path / "not_a_dir.txt"
        parent.write_text("", encoding="utf-8")
        path = parent / "audit.jsonl"
        with pytest.raises(StorageError, match="parent is not a directory"):
            AuditService(path)

    def test_audit_path_directory_rejected(self, tmp_path: Path) -> None:
        parent = tmp_path / "vault"
        parent.mkdir()
        with pytest.raises(StorageError, match="existing directory"):
            AuditService(parent)

    def test_symlink_rejected(self, tmp_path: Path) -> None:
        if not _can_symlink():
            pytest.skip("OS does not support symlinks")
        parent = tmp_path / "vault"
        parent.mkdir()
        real = parent / "real.jsonl"
        link = parent / "link.jsonl"
        os.symlink(str(real), str(link))
        with pytest.raises(StorageError, match="symlink"):
            AuditService(link)

    def test_dangling_symlink_rejected(self, tmp_path: Path) -> None:
        if not _can_symlink():
            pytest.skip("OS does not support symlinks")
        parent = tmp_path / "vault"
        parent.mkdir()
        link = parent / "dangling.jsonl"
        os.symlink(str(parent / "nonexistent.jsonl"), str(link))
        with pytest.raises(StorageError, match="symlink"):
            AuditService(link)

    def test_log_path_property(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        service = AuditService(log_path)
        assert service.log_path == log_path


# ═════════════════════════════════════════════════════════════════════════════
# AuditService — append
# ═════════════════════════════════════════════════════════════════════════════


class TestAuditServiceAppend:
    """Append operations."""

    def test_missing_file_created_on_first_append(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        assert not log_path.exists()
        service = AuditService(log_path)
        service.append(_valid_record())
        assert log_path.exists()
        assert log_path.stat().st_size > 0

    def test_record_written_as_one_json_line(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        service = AuditService(log_path)
        record = _valid_record(operation_id="op-001")
        service.append(record)
        lines = log_path.read_text(encoding="utf-8").splitlines(keepends=True)
        assert len(lines) == 1
        data = json.loads(lines[0].strip())
        assert data["operation_id"] == "op-001"

    def test_exactly_one_newline_per_record(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        service = AuditService(log_path)
        service.append(_valid_record(operation_id="op-001"))
        raw = log_path.read_bytes()
        assert raw.endswith(b"\n")
        assert raw.count(b"\n") == 1

    def test_unicode_round_trip(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        service = AuditService(log_path)
        record = _valid_record(
            operation_id="оп-001",
            session="Сессия-007",
            source="инструмент",
        )
        service.append(record)
        lines = log_path.read_text(encoding="utf-8")
        assert "оп-001" in lines
        assert "Сессия-007" in lines
        assert "инструмент" in lines

    def test_multiple_appends_preserve_order(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        service = AuditService(log_path)
        service.append(_valid_record(operation_id="op-001"))
        service.append(_valid_record(operation_id="op-002"))
        service.append(_valid_record(operation_id="op-003"))
        records = service.read_all()
        assert [r.operation_id for r in records] == ["op-001", "op-002", "op-003"]

    def test_existing_bytes_remain_exact_prefix(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        service = AuditService(log_path)
        service.append(_valid_record(operation_id="op-001"))
        first_bytes = log_path.read_bytes()
        service.append(_valid_record(operation_id="op-002"))
        full_bytes = log_path.read_bytes()
        assert full_bytes[: len(first_bytes)] == first_bytes

    def test_append_does_not_truncate(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        log_path.write_text(
            json.dumps(
                _valid_record(operation_id="op-001").model_dump(mode="json"),
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        original_size = log_path.stat().st_size
        service = AuditService(log_path)
        service.append(_valid_record(operation_id="op-002"))
        assert log_path.stat().st_size > original_size

    def test_fsync_called(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        service = AuditService(log_path)
        original_fsync = os.fsync
        fsync_called = False

        def _monkey_fsync(fd: int) -> None:
            nonlocal fsync_called
            fsync_called = True
            original_fsync(fd)

        with mock.patch("os.fsync", side_effect=_monkey_fsync):
            service.append(_valid_record())
        assert fsync_called

    def test_file_closed_after_append(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        service = AuditService(log_path)
        service.append(_valid_record())
        assert log_path.read_text(encoding="utf-8")


# ═════════════════════════════════════════════════════════════════════════════
# AuditService — read_all
# ═════════════════════════════════════════════════════════════════════════════


class TestAuditServiceReadAll:
    """Read-back behaviour."""

    def test_missing_file_returns_empty_list(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        assert not log_path.exists()
        service = AuditService(log_path)
        assert service.read_all() == []

    def test_one_valid_record(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        service = AuditService(log_path)
        record = _valid_record(operation_id="op-001")
        service.append(record)
        records = service.read_all()
        assert len(records) == 1
        assert records[0].operation_id == "op-001"

    def test_multiple_records_preserve_order(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        service = AuditService(log_path)
        service.append(_valid_record(operation_id="op-001"))
        service.append(_valid_record(operation_id="op-002"))
        service.append(_valid_record(operation_id="op-003"))
        records = service.read_all()
        assert len(records) == 3
        assert [r.operation_id for r in records] == ["op-001", "op-002", "op-003"]

    def test_malformed_json_raises_storage_error(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        log_path.write_text('{"valid": true}\nnot json\n', encoding="utf-8")
        service = AuditService(log_path)
        with pytest.raises(StorageError) as exc:
            service.read_all()
        error_msg = str(exc.value)
        # The first line is valid JSON but fails AuditRecord validation
        # (missing required fields).  The error should reference line 1.
        assert "corruption" in error_msg.lower()
        assert "line 1" in error_msg

    def test_schema_invalid_record_raises_storage_error(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        log_path.write_text(
            '{"operation_id": "op-001", "real_time": "invalid", "operation": "x", "source": "y"}\n',
            encoding="utf-8",
        )
        service = AuditService(log_path)
        with pytest.raises(StorageError) as exc:
            service.read_all()
        assert "line 1" in str(exc.value)

    def test_blank_line_raises_storage_error(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        log_path.write_text(
            '{"operation_id":"op-001","real_time":"2026-08-30T12:00:00+00:00","operation":"x","source":"y"}\n\n',
            encoding="utf-8",
        )
        service = AuditService(log_path)
        with pytest.raises(StorageError) as exc:
            service.read_all()
        assert "blank line" in str(exc.value).lower()

    def test_unknown_fields_in_persisted_record_raises_error(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        log_path.write_text(
            '{"operation_id":"op-001","real_time":"2026-08-30T12:00:00+00:00",'
            '"operation":"x","source":"y","unknown_field":"bad"}\n',
            encoding="utf-8",
        )
        service = AuditService(log_path)
        with pytest.raises(StorageError) as exc:
            service.read_all()
        assert "line 1" in str(exc.value)

    def test_no_silent_skip_of_bad_record(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        log_path.write_text(
            '{"operation_id":"op-001","real_time":"2026-08-30T12:00:00+00:00","operation":"x","source":"y"}\n'
            "not json\n",
            encoding="utf-8",
        )
        service = AuditService(log_path)
        with pytest.raises(StorageError):
            service.read_all()


# ═════════════════════════════════════════════════════════════════════════════
# AuditService — failure injection
# ═════════════════════════════════════════════════════════════════════════════


class TestAuditServiceFailureInjection:
    """Filesystem failure behaviour."""

    def test_open_write_failure_raises_storage_error(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        service = AuditService(log_path)

        def _broken_open(*args: object, **kwargs: object) -> object:
            raise OSError(13, "Permission denied")

        with mock.patch("builtins.open", _broken_open):
            with pytest.raises(StorageError) as exc:
                service.append(_valid_record())
        assert exc.value.__cause__ is not None
        assert isinstance(exc.value.__cause__, OSError)

    def test_fsync_failure_raises_storage_error(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        service = AuditService(log_path)

        def _broken_fsync(fd: int) -> None:
            raise OSError(5, "Input/output error")

        with mock.patch("os.fsync", side_effect=_broken_fsync):
            with pytest.raises(StorageError) as exc:
                service.append(_valid_record())
        assert exc.value.__cause__ is not None
        assert isinstance(exc.value.__cause__, OSError)

    def test_fsync_failure_does_not_rewrite_history(self, tmp_path: Path) -> None:
        log_path = _make_log_path(tmp_path)
        service = AuditService(log_path)
        service.append(_valid_record(operation_id="op-001"))
        original_bytes = log_path.read_bytes()

        def _broken_fsync(fd: int) -> None:
            raise OSError(5, "Input/output error")

        with mock.patch("os.fsync", side_effect=_broken_fsync):
            with pytest.raises(StorageError):
                service.append(_valid_record(operation_id="op-002"))

        # The original record must still be intact (append may have written
        # bytes but we do NOT truncate/rollback).
        assert log_path.read_bytes()[: len(original_bytes)] == original_bytes


# ═════════════════════════════════════════════════════════════════════════════
# Boundary tests — audit.py must not import prohibited modules
# ═════════════════════════════════════════════════════════════════════════════


class TestAuditBoundaries:
    """Audit module must not depend on entity, model, retrieval, or tools."""

    def test_audit_module_importable(self) -> None:
        import dnd_assistant.storage.audit  # noqa: F401

    def test_audit_re_exported(self) -> None:
        from dnd_assistant.storage import AuditRecord, AuditService  # noqa: F401

    def test_no_entity_import(self) -> None:
        import dnd_assistant.storage.audit as mod

        source = str(mod.__file__)
        with open(source, encoding="utf-8") as f:
            content = f.read()
        assert "from dnd_assistant.domain.entity import" not in content
        assert "from dnd_assistant.domain import entity" not in content

    def test_no_models_import(self) -> None:
        import dnd_assistant.storage.audit as mod

        source = str(mod.__file__)
        with open(source, encoding="utf-8") as f:
            content = f.read()
        assert "from dnd_assistant.models" not in content

    def test_no_retrieval_import(self) -> None:
        import dnd_assistant.storage.audit as mod

        source = str(mod.__file__)
        with open(source, encoding="utf-8") as f:
            content = f.read()
        assert "from dnd_assistant.retrieval" not in content

    def test_no_tools_import(self) -> None:
        import dnd_assistant.storage.audit as mod

        source = str(mod.__file__)
        with open(source, encoding="utf-8") as f:
            content = f.read()
        assert "from dnd_assistant.tools" not in content

    def test_no_storage_markdown_import(self) -> None:
        import dnd_assistant.storage.audit as mod

        source = str(mod.__file__)
        with open(source, encoding="utf-8") as f:
            content = f.read()
        assert "from dnd_assistant.storage.markdown" not in content

    def test_no_atomic_write_text_usage(self) -> None:
        import dnd_assistant.storage.audit as mod

        source = str(mod.__file__)
        with open(source, encoding="utf-8") as f:
            content = f.read()
        # The docstring mentions atomic_write_text as something the
        # module must NOT use.  Check that the actual code does not
        # import or reference it outside docstrings/comments.
        assert "from dnd_assistant.storage.atomic" not in content
        assert "atomic_write_text(" not in content
