"""Mocked end-to-end integration tests for ``dnd ask``.

These tests use a real temporary Vault, real Python layers (repositories,
services, tool registry, executor, agent loop), and a fake ``ModelGateway``.

No live Ollama, no network, no GPU, no model download.

Parser-backed E2E
─────────────────
The real ``dnd_assistant.cli.main:app`` has an ``@app.callback()`` registered,
which causes ``typer.main.get_command()`` to produce a ``TyperGroup``.  In
this configuration, ``typer.testing.CliRunner`` correctly handles positional
arguments in named subcommands.  All E2E integration scenarios use
``CliRunner.invoke(app, ...)`` with ``unittest.mock.patch`` on
``_build_model_provider`` to inject a fake ``ModelGateway``.

Direct-call tests
─────────────────
A minimal Typer app *without* a callback reproduces the Typer 0.27.1
regression where ``CliRunner`` rejects positional args as unexpected extra
arguments.  The ``_invoke_ask_direct`` helper remains for narrow presentation-
layer tests that do not need parser verification.
"""

from __future__ import annotations

import json
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

from typer.testing import CliRunner

from dnd_assistant.cli.ask import _ask_command
from dnd_assistant.cli.main import app as dnd_app
from dnd_assistant.errors import DndAssistantError
from dnd_assistant.models.profiles import ModelProfile
from dnd_assistant.models.types import ChatMessage, ChatRequest, MessageRole, ToolAwareResponse
from dnd_assistant.prompts.agent_v2 import PROMPT_VERSION
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_events import ObsidianSessionEventRepository
from dnd_assistant.tools.catalog import ToolPublicDefinition

# ── Fake ModelGateway ──────────────────────────────────────────────────────


class FakeModelGateway:
    """Deterministic fake ``ModelGateway`` for testing.

    Returns pre-configured responses in sequence.  Tracks calls for
    verification.
    """

    def __init__(self) -> None:
        self.responses: list[ToolAwareResponse] = []
        self.call_count = 0
        self.last_request: ChatRequest | None = None
        self.last_tools: list[ToolPublicDefinition] | None = None

    def add_response(self, response: ToolAwareResponse) -> None:
        """Add a response to the sequence."""
        self.responses.append(response)

    def chat_with_tools(
        self,
        request: ChatRequest,
        tools: list[ToolPublicDefinition],
    ) -> ToolAwareResponse:
        """Return the next pre-configured response."""
        self.call_count += 1
        self.last_request = request
        self.last_tools = tools

        if self.call_count > len(self.responses):
            raise DndAssistantError("FakeModelGateway: no more responses configured")

        return self.responses[self.call_count - 1]

    def close(self) -> None:
        """Fake close — no-op."""
        pass


# ── Response builders ──────────────────────────────────────────────────────


def _respond(message: str) -> ToolAwareResponse:
    """Build a terminal RESPOND response."""
    content = json.dumps(
        {"kind": "respond", "message": message},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return ToolAwareResponse(
        message=ChatMessage(role=MessageRole.ASSISTANT, content=content),
    )


def _clarify(message: str) -> ToolAwareResponse:
    """Build a terminal CLARIFY response."""
    content = json.dumps(
        {"kind": "clarify", "message": message},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return ToolAwareResponse(
        message=ChatMessage(role=MessageRole.ASSISTANT, content=content),
    )


def _tool_call_response(tool_name: str, arguments: dict[str, Any]) -> ToolAwareResponse:
    """Build a response with a tool call."""
    from dnd_assistant.models.types import ToolCall

    return ToolAwareResponse(
        message=ChatMessage(
            role=MessageRole.ASSISTANT,
            content=None,
            tool_calls=(
                ToolCall(
                    name=tool_name,
                    arguments=arguments,
                    call_id="call_001",
                ),
            ),
        ),
    )


# ── Vault fixture builder ─────────────────────────────────────────────────


def _build_minimal_vault(tmp_path: Path) -> Path:
    """Build a minimal Vault with required directories and world time.

    Creates:
    - Characters/NPCs/
    - Locations/
    - Quests/
    - Items/
    - Sessions/
    - _system/audit/
    - _system/raw/sessions/
    - _system/world_time.json
    - _system/indexes/

    Returns:
        The Vault root path.
    """
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    (vault_root / "Characters" / "NPCs").mkdir(parents=True)
    (vault_root / "Locations").mkdir()
    (vault_root / "Quests").mkdir()
    (vault_root / "Items").mkdir()
    (vault_root / "Sessions").mkdir()
    (vault_root / "_system" / "audit").mkdir(parents=True)
    (vault_root / "_system" / "raw" / "sessions").mkdir(parents=True)
    (vault_root / "_system" / "indexes").mkdir(parents=True)

    from dnd_assistant.retrieval.index import SqliteFtsIndex
    from dnd_assistant.storage.world_time import ObsidianWorldTimeRepository

    audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    audit_service = AuditService(str(audit_log_path))
    world_time_repo = ObsidianWorldTimeRepository(vault_root, audit_service)
    world_time_repo.initialize_current_world_time(
        1000,
        audit=AuditContext(
            operation_id="init-world-time",
            real_time=datetime.now(UTC),
            source="test",
        ),
    )

    # Initialize FTS index (required by VaultSearchService.verify_freshness)
    fts_index = SqliteFtsIndex(vault_root=str(vault_root))
    fts_index.rebuild([])

    return vault_root


def _start_test_session(vault_root: Path) -> str:
    """Start a test session and return its session ID."""
    from dnd_assistant.application.session_runtime import SessionRuntimeService
    from dnd_assistant.storage.session_events import ObsidianSessionEventRepository
    from dnd_assistant.storage.session_metadata import (
        ObsidianSessionMetadataRepository,
    )
    from dnd_assistant.storage.world_time import ObsidianWorldTimeRepository

    audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    audit_service = AuditService(str(audit_log_path))
    session_repo = ObsidianSessionMetadataRepository(vault_root, audit_service)
    world_time_repo = ObsidianWorldTimeRepository(vault_root, audit_service)
    event_repo = ObsidianSessionEventRepository(vault_root, audit_service)

    runtime = SessionRuntimeService(session_repo, world_time_repo, event_repo)

    session = runtime.start_session(
        audit=AuditContext(
            operation_id="test-start-session",
            real_time=datetime.now(UTC),
            source="test",
        ),
    )
    return session.id


def _write_test_config(tmp_path: Path, profile_name: str = "test-agent") -> Path:
    """Write a minimal TOML config file."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"[profiles.{profile_name}]\n"
        "provider='ollama'\n"
        "model='test-model'\n"
        "base_url='http://localhost:11434'\n"
        "role='agent'\n",
        encoding="utf-8",
    )
    return config_path


def _fake_provider_factory(fake_gateway: FakeModelGateway) -> Any:
    """Return a factory function that returns the given fake gateway."""

    def factory(profile: ModelProfile) -> FakeModelGateway:
        return fake_gateway

    return factory


def _invoke_ask_direct(
    query: str,
    vault_root: Path,
    config_path: Path,
    profile: str = "test-agent",
    allow_write: bool = False,
) -> Any:
    """Invoke the ``_ask_command`` function directly with keyword arguments.

    Returns a result-like object with ``exit_code``, ``stdout``, and
    ``stderr`` attributes.
    """
    stdout_capture = StringIO()
    stderr_capture = StringIO()

    exit_code = 0
    exception = None

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            _ask_command(
                query=query,
                vault=vault_root,
                config=config_path,
                profile=profile,
                allow_write=allow_write,
            )
    except SystemExit as e:
        exit_code = e.code if e.code is not None else 0
    except BaseException as e:
        exception = e
        exit_code = 1

    class _Result:
        pass

    result = _Result()
    result.exit_code = exit_code
    result.stdout = stdout_capture.getvalue()
    result.stderr = stderr_capture.getvalue()
    result.exception = exception
    return result


# ── Integration tests ──────────────────────────────────────────────────────


class TestAskDirectRespond:
    """Direct respond path (zero tools)."""

    def test_direct_respond(self, tmp_path: Path) -> None:
        """A direct respond returns exit 0 with the message on stdout."""
        vault_root = _build_minimal_vault(tmp_path)
        config_path = _write_test_config(tmp_path)
        fake_gateway = FakeModelGateway()
        fake_gateway.add_response(_respond("Варос — опытный следопыт."))

        with patch(
            "dnd_assistant.cli.agent_runtime._build_model_provider",
            side_effect=_fake_provider_factory(fake_gateway),
        ):
            result = _invoke_ask_direct("Кто такой Варос?", vault_root, config_path)

        assert result.exit_code == 0
        assert "Варос — опытный следопыт." in result.stdout


class TestAskDirectClarify:
    """Direct clarify path (zero tools)."""

    def test_direct_clarify(self, tmp_path: Path) -> None:
        """A direct clarify returns exit 0 with the clarification on stdout."""
        vault_root = _build_minimal_vault(tmp_path)
        config_path = _write_test_config(tmp_path)
        fake_gateway = FakeModelGateway()
        fake_gateway.add_response(_clarify("Какого именно Вароса вы имеете в виду?"))

        with patch(
            "dnd_assistant.cli.agent_runtime._build_model_provider",
            side_effect=_fake_provider_factory(fake_gateway),
        ):
            result = _invoke_ask_direct("Обнови Вароса", vault_root, config_path)

        assert result.exit_code == 0
        assert "Какого именно Вароса вы имеете в виду?" in result.stdout


class TestAskReadTool:
    """Real READ tool execution through the mocked path."""

    def test_read_tool_then_respond(self, tmp_path: Path) -> None:
        """A READ tool (get_active_session) executes and final respond is printed."""
        vault_root = _build_minimal_vault(tmp_path)
        _start_test_session(vault_root)
        config_path = _write_test_config(tmp_path)
        fake_gateway = FakeModelGateway()

        fake_gateway.add_response(_tool_call_response("get_active_session", {}))
        fake_gateway.add_response(_respond("Сессия активна."))

        with patch(
            "dnd_assistant.cli.agent_runtime._build_model_provider",
            side_effect=_fake_provider_factory(fake_gateway),
        ):
            result = _invoke_ask_direct("Какая сессия активна?", vault_root, config_path)

        assert result.exit_code == 0
        assert "Сессия активна." in result.stdout
        assert fake_gateway.call_count == 2


class TestAskReadOnlyBlocksWrite:
    """READ-only mode blocks WRITE tools."""

    def test_read_only_blocks_write_tool(self, tmp_path: Path) -> None:
        """Without --allow-write, a WRITE tool call raises ModelError -> exit 1."""
        vault_root = _build_minimal_vault(tmp_path)
        _start_test_session(vault_root)
        config_path = _write_test_config(tmp_path)
        fake_gateway = FakeModelGateway()

        fake_gateway.add_response(_tool_call_response("record_note", {"text": "Test note"}))

        with patch(
            "dnd_assistant.cli.agent_runtime._build_model_provider",
            side_effect=_fake_provider_factory(fake_gateway),
        ):
            result = _invoke_ask_direct("Запиши заметку", vault_root, config_path)

        assert result.exit_code == 1
        assert "Ошибка" in result.stderr


class TestAskWriteTool:
    """Explicit WRITE tool execution through --allow-write."""

    def test_write_tool_with_allow_write(self, tmp_path: Path) -> None:
        """With --allow-write, a WRITE tool executes and audit is persisted."""
        vault_root = _build_minimal_vault(tmp_path)
        session_id = _start_test_session(vault_root)
        config_path = _write_test_config(tmp_path)
        fake_gateway = FakeModelGateway()

        fake_gateway.add_response(
            _tool_call_response("record_note", {"text": "Варос упомянул древний артефакт."})
        )
        fake_gateway.add_response(_respond("Заметка сохранена."))

        with patch(
            "dnd_assistant.cli.agent_runtime._build_model_provider",
            side_effect=_fake_provider_factory(fake_gateway),
        ):
            result = _invoke_ask_direct(
                "Запиши: Варос упомянул древний артефакт.",
                vault_root,
                config_path,
                allow_write=True,
            )

        assert result.exit_code == 0
        assert "Заметка сохранена." in result.stdout

        # Verify audit evidence
        audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        assert audit_log_path.exists()
        audit_text = audit_log_path.read_text(encoding="utf-8")

        assert "model_tool" in audit_text
        assert "test-agent" in audit_text
        assert PROMPT_VERSION in audit_text

        # Verify the note was actually persisted
        audit_service = AuditService(str(audit_log_path))
        event_repo = ObsidianSessionEventRepository(vault_root, audit_service)
        events = event_repo.list_events(session_id)
        assert len(events) >= 1
        note_events = [e for e in events if e.type == "note"]
        assert len(note_events) >= 1
        assert note_events[-1].extra_fields.get("text") == "Варос упомянул древний артефакт."


class TestAskProfileConfigFailures:
    """Profile/config failure scenarios."""

    def test_missing_config_file(self, tmp_path: Path) -> None:
        """A missing config file exits with code 1."""
        vault_root = _build_minimal_vault(tmp_path)
        config_path = tmp_path / "nonexistent.toml"

        result = _invoke_ask_direct("Тест", vault_root, config_path)

        assert result.exit_code == 1
        assert "Ошибка" in result.stderr

    def test_wrong_role_profile(self, tmp_path: Path) -> None:
        """A non-AGENT profile exits with code 1."""
        vault_root = _build_minimal_vault(tmp_path)
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[profiles.test-agent]\n"
            "provider='ollama'\n"
            "model='test'\n"
            "base_url='http://localhost:11434'\n"
            "role='summarizer'\n",
            encoding="utf-8",
        )

        result = _invoke_ask_direct("Тест", vault_root, config_path)

        assert result.exit_code == 1
        assert "Ошибка" in result.stderr


# ── Actual CLI runner tests (option-only, no positional args) ──────────────


class TestAskCliRunnerIntegration:
    """Integration tests using the real Typer CliRunner for option paths.

    These tests verify that the real ``dnd`` app correctly routes option
    validation through Typer's parser.  The real app has an
    ``@app.callback()`` registered, so ``CliRunner`` handles positional
    arguments correctly (unlike a minimal Typer app without a callback).
    """

    def test_ask_help_via_cli_runner(self, tmp_path: Path) -> None:
        """``dnd ask --help`` works through the real CLI runner."""
        runner = CliRunner()
        result = runner.invoke(dnd_app, ["ask", "--help"])
        assert result.exit_code == 0
        assert "QUERY" in result.stdout or "{query}" in result.stdout
        assert "--vault" in result.stdout
        assert "--config" in result.stdout
        assert "--profile" in result.stdout
        assert "--allow-write" in result.stdout

    def test_missing_vault_option_via_cli_runner(self, tmp_path: Path) -> None:
        """Missing --vault is caught by Typer parser, exit 2."""
        config_path = _write_test_config(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            dnd_app,
            [
                "ask",
                "test query",
                "--config",
                str(config_path),
                "--profile",
                "test-agent",
            ],
        )
        assert result.exit_code == 2
        assert "Missing option" in result.stderr

    def test_missing_config_option_via_cli_runner(self, tmp_path: Path) -> None:
        """Missing --config is caught by Typer parser, exit 2."""
        vault_root = _build_minimal_vault(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            dnd_app,
            [
                "ask",
                "test query",
                "--vault",
                str(vault_root),
                "--profile",
                "test-agent",
            ],
        )
        assert result.exit_code == 2
        assert "Missing option" in result.stderr

    def test_missing_profile_option_via_cli_runner(self, tmp_path: Path) -> None:
        """Missing --profile is caught by Typer parser, exit 2."""
        vault_root = _build_minimal_vault(tmp_path)
        config_path = _write_test_config(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            dnd_app,
            [
                "ask",
                "test query",
                "--vault",
                str(vault_root),
                "--config",
                str(config_path),
            ],
        )
        assert result.exit_code == 2
        assert "Missing option" in result.stderr


# ── Parser-backed mocked E2E tests ─────────────────────────────────────────


class TestAskCliRunnerParserBacked:
    """Parser-backed mocked E2E integration tests.

    These tests use ``CliRunner.invoke(dnd_app, ...)`` with
    ``unittest.mock.patch`` on ``_build_model_provider`` to inject a fake
    ``ModelGateway``.  Every scenario exercises the real Typer/Click parser:
    positional QUERY, ``--vault``, ``--config``, ``--profile``, and
    ``--allow-write`` are all parsed by the generated command, then routed
    through the real ``_ask_command``, ``compose_ask_runtime``, repositories,
    services, ``ToolRegistry``, ``ToolExecutor``, and ``AgentLoop``.
    """

    def test_respond_through_real_parser(self, tmp_path: Path) -> None:
        """RESPOND outcome: exit 0, correct stdout, 1 fake model call."""
        vault_root = _build_minimal_vault(tmp_path)
        config_path = _write_test_config(tmp_path)
        fake_gateway = FakeModelGateway()
        fake_gateway.add_response(_respond("Ответ через реальный парсер."))

        runner = CliRunner()
        with patch(
            "dnd_assistant.cli.agent_runtime._build_model_provider",
            side_effect=_fake_provider_factory(fake_gateway),
        ):
            result = runner.invoke(
                dnd_app,
                [
                    "ask",
                    "Кто такой Варос?",
                    "--vault",
                    str(vault_root),
                    "--config",
                    str(config_path),
                    "--profile",
                    "test-agent",
                ],
            )

        assert result.exit_code == 0
        assert "Ответ через реальный парсер." in result.stdout
        assert fake_gateway.call_count == 1

    def test_clarify_through_real_parser(self, tmp_path: Path) -> None:
        """CLARIFY outcome: exit 0, correct stdout, 1 fake model call."""
        vault_root = _build_minimal_vault(tmp_path)
        config_path = _write_test_config(tmp_path)
        fake_gateway = FakeModelGateway()
        fake_gateway.add_response(_clarify("Какого именно Вароса?"))

        runner = CliRunner()
        with patch(
            "dnd_assistant.cli.agent_runtime._build_model_provider",
            side_effect=_fake_provider_factory(fake_gateway),
        ):
            result = runner.invoke(
                dnd_app,
                [
                    "ask",
                    "Обнови Вароса",
                    "--vault",
                    str(vault_root),
                    "--config",
                    str(config_path),
                    "--profile",
                    "test-agent",
                ],
            )

        assert result.exit_code == 0
        assert "Какого именно Вароса?" in result.stdout
        assert fake_gateway.call_count == 1

    def test_read_tool_through_real_parser(self, tmp_path: Path) -> None:
        """READ tool executes, final respond printed, 2 fake model calls."""
        vault_root = _build_minimal_vault(tmp_path)
        _start_test_session(vault_root)
        config_path = _write_test_config(tmp_path)
        fake_gateway = FakeModelGateway()

        fake_gateway.add_response(_tool_call_response("get_active_session", {}))
        fake_gateway.add_response(_respond("Сессия активна."))

        runner = CliRunner()
        with patch(
            "dnd_assistant.cli.agent_runtime._build_model_provider",
            side_effect=_fake_provider_factory(fake_gateway),
        ):
            result = runner.invoke(
                dnd_app,
                [
                    "ask",
                    "Какая сессия активна?",
                    "--vault",
                    str(vault_root),
                    "--config",
                    str(config_path),
                    "--profile",
                    "test-agent",
                ],
            )

        assert result.exit_code == 0
        assert "Сессия активна." in result.stdout
        assert fake_gateway.call_count == 2

    def test_read_only_blocks_write_through_real_parser(self, tmp_path: Path) -> None:
        """Without --allow-write, WRITE tool raises error -> exit 1."""
        vault_root = _build_minimal_vault(tmp_path)
        _start_test_session(vault_root)
        config_path = _write_test_config(tmp_path)
        fake_gateway = FakeModelGateway()

        fake_gateway.add_response(_tool_call_response("record_note", {"text": "Test note"}))

        runner = CliRunner()
        with patch(
            "dnd_assistant.cli.agent_runtime._build_model_provider",
            side_effect=_fake_provider_factory(fake_gateway),
        ):
            result = runner.invoke(
                dnd_app,
                [
                    "ask",
                    "Запиши заметку",
                    "--vault",
                    str(vault_root),
                    "--config",
                    str(config_path),
                    "--profile",
                    "test-agent",
                ],
            )

        assert result.exit_code == 1
        assert "Ошибка" in result.stderr
        # Zero mutations
        audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        audit_text = audit_log_path.read_text(encoding="utf-8")
        assert "model_tool" not in audit_text

    def test_write_tool_through_real_parser(self, tmp_path: Path) -> None:
        """With --allow-write, WRITE tool executes, audit persisted."""
        vault_root = _build_minimal_vault(tmp_path)
        session_id = _start_test_session(vault_root)
        config_path = _write_test_config(tmp_path)
        fake_gateway = FakeModelGateway()

        fake_gateway.add_response(
            _tool_call_response("record_note", {"text": "Варос упомянул древний артефакт."})
        )
        fake_gateway.add_response(_respond("Заметка сохранена."))

        runner = CliRunner()
        with patch(
            "dnd_assistant.cli.agent_runtime._build_model_provider",
            side_effect=_fake_provider_factory(fake_gateway),
        ):
            result = runner.invoke(
                dnd_app,
                [
                    "ask",
                    "Запиши: Варос упомянул древний артефакт.",
                    "--vault",
                    str(vault_root),
                    "--config",
                    str(config_path),
                    "--profile",
                    "test-agent",
                    "--allow-write",
                ],
            )

        assert result.exit_code == 0
        assert "Заметка сохранена." in result.stdout
        assert fake_gateway.call_count == 2

        # Semantic audit evidence
        audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        assert audit_log_path.exists()

        audit_service = AuditService(str(audit_log_path))
        records = audit_service.read_all()
        tool_records = [r for r in records if r.source == "model_tool"]
        assert len(tool_records) >= 1

        last_tool = tool_records[-1]
        assert last_tool.source == "model_tool"
        assert last_tool.model_profile == "test-agent"
        assert last_tool.prompt_version == PROMPT_VERSION
        assert last_tool.session == session_id

        # Verify the note was persisted exactly once
        event_repo = ObsidianSessionEventRepository(vault_root, audit_service)
        events = event_repo.list_events(session_id)
        note_events = [e for e in events if e.type == "note"]
        assert len(note_events) >= 1
        assert note_events[-1].extra_fields.get("text") == "Варос упомянул древний артефакт."


class TestAskCliRunnerProfileFailures:
    """Profile/config failure scenarios through the real parser."""

    def test_missing_config_file_through_parser(self, tmp_path: Path) -> None:
        """A nonexistent --config path is rejected by Typer parser, exit 2."""
        vault_root = _build_minimal_vault(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            dnd_app,
            [
                "ask",
                "Тест",
                "--vault",
                str(vault_root),
                "--config",
                str(tmp_path / "nonexistent.toml"),
                "--profile",
                "test-agent",
            ],
        )

        assert result.exit_code == 2

    def test_wrong_role_profile_through_parser(self, tmp_path: Path) -> None:
        """A non-AGENT profile exits with code 1 and Ошибка on stderr."""
        vault_root = _build_minimal_vault(tmp_path)
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[profiles.test-agent]\n"
            "provider='ollama'\n"
            "model='test'\n"
            "base_url='http://localhost:11434'\n"
            "role='summarizer'\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(
            dnd_app,
            [
                "ask",
                "Тест",
                "--vault",
                str(vault_root),
                "--config",
                str(config_path),
                "--profile",
                "test-agent",
            ],
        )

        assert result.exit_code == 1
        assert "Ошибка" in result.stderr

    def test_missing_profile_name_through_parser(self, tmp_path: Path) -> None:
        """A nonexistent profile name exits with code 1 and Ошибка on stderr."""
        vault_root = _build_minimal_vault(tmp_path)
        config_path = _write_test_config(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            dnd_app,
            [
                "ask",
                "Тест",
                "--vault",
                str(vault_root),
                "--config",
                str(config_path),
                "--profile",
                "nonexistent",
            ],
        )

        assert result.exit_code == 1
        assert "Ошибка" in result.stderr

    def test_unsupported_provider_through_parser(self, tmp_path: Path) -> None:
        """An unsupported provider exits with code 1."""
        vault_root = _build_minimal_vault(tmp_path)
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[profiles.test-agent]\n"
            "provider='openai'\n"
            "model='gpt-4'\n"
            "base_url='https://api.openai.com/v1'\n"
            "role='agent'\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(
            dnd_app,
            [
                "ask",
                "Тест",
                "--vault",
                str(vault_root),
                "--config",
                str(config_path),
                "--profile",
                "test-agent",
            ],
        )

        assert result.exit_code == 1
        assert "Ошибка" in result.stderr


class TestAskCliRunnerProviderCleanup:
    """Provider cleanup regressions through the real parser."""

    def test_composition_storage_error_close_once(self, tmp_path: Path) -> None:
        """StorageError during composition -> provider close called once."""
        vault_root = _build_minimal_vault(tmp_path)
        config_path = _write_test_config(tmp_path)

        from dnd_assistant.errors import StorageError

        def _broken_audit_init(self_arg, *args, **kwargs):
            raise StorageError("Audit path invalid")

        runner = CliRunner()
        with patch(
            "dnd_assistant.cli.agent_runtime.AuditService.__init__",
            _broken_audit_init,
        ):
            result = runner.invoke(
                dnd_app,
                [
                    "ask",
                    "Тест",
                    "--vault",
                    str(vault_root),
                    "--config",
                    str(config_path),
                    "--profile",
                    "test-agent",
                ],
            )

        assert result.exit_code == 1
        assert "Ошибка" in result.stderr
