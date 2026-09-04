"""Unit tests for the ``dnd ask`` CLI command presentation layer.

These tests verify:

- Typer command registration (via CliRunner for --help and option-only tests)
- respond rendering
- clarify rendering
- exit codes
- project-error rendering
- option propagation
- ``--allow-write`` propagation
- unexpected exception not broad-caught
- recovery error rendering

Typer 0.27.1 regression
───────────────────────
Typer 0.27.1 has a confirmed regression where ``CliRunner`` does not handle
positional arguments in named subcommands — the positional value is treated
as an unexpected extra argument.  Tests that require positional argument
parsing invoke ``_ask_command`` directly.  Option-only tests (``--help``,
option validation) use ``CliRunner`` with the real ``dnd`` app.

They do NOT test runtime composition (see ``test_cli_agent_runtime.py``).
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from dnd_assistant.application.agent_loop import (
    AgentOutcomeKind,
    AgentRunResult,
    AgentTextOutcome,
)
from dnd_assistant.cli.ask import _ask_command
from dnd_assistant.cli.main import app
from dnd_assistant.errors import DndAssistantError, StorageError

# ── Runner for help-text tests ─────────────────────────────────────────────


@pytest.fixture()
def runner() -> CliRunner:
    """Return a Typer CLI test runner."""
    return CliRunner()


# ── Fake runtime factory ───────────────────────────────────────────────────


def _make_fake_ask_runtime(
    outcome_message: str = "Ответ ассистента.",
    outcome_kind: str = "respond",
    close_called: list[bool] | None = None,
) -> MagicMock:
    """Build a fake ``AskRuntime`` that returns a deterministic outcome.

    Args:
        outcome_message: The message the fake agent returns.
        outcome_kind: ``"respond"`` or ``"clarify"``.
        close_called: Optional list to track ``close()`` calls.

    Returns:
        A configured ``MagicMock`` simulating ``AskRuntime``.
    """
    track = close_called if close_called is not None else []

    outcome = AgentTextOutcome(
        kind=AgentOutcomeKind(outcome_kind),
        message=outcome_message,
    )

    run_result = MagicMock(spec=AgentRunResult)
    run_result.outcome = outcome

    runtime = MagicMock()
    runtime.agent_loop.run.return_value = run_result
    runtime.execution_context = MagicMock()

    def _close() -> None:
        track.append(True)

    runtime.close = _close  # type: ignore[method-assign]

    return runtime


# ── Helper: invoke ask command function directly ───────────────────────────


def _invoke_ask_direct(
    query: str,
    vault_root: Path,
    config_path: Path,
    profile: str = "test-agent",
    allow_write: bool = False,
) -> Any:
    """Invoke the ``_ask_command`` function directly with keyword arguments.

    This bypasses Typer's CLI runner to work around a Typer 0.27.1
    regression with positional arguments in named subcommands.

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


# ── Tests ──────────────────────────────────────────────────────────────────


class TestAskCommandRegistration:
    """Verify the ask command is properly registered in the real dnd app."""

    def test_ask_command_exists(self, runner: CliRunner) -> None:
        """The ``ask`` subcommand is registered in the real app."""
        result = runner.invoke(app, ["ask", "--help"])
        assert result.exit_code == 0
        assert "ask" in result.stdout

    def test_ask_has_positional_query(self, runner: CliRunner) -> None:
        """The ``ask`` help shows the QUERY positional argument."""
        result = runner.invoke(app, ["ask", "--help"])
        assert result.exit_code == 0
        assert "QUERY" in result.stdout or "{query}" in result.stdout

    def test_ask_has_vault_option(self, runner: CliRunner) -> None:
        """The ``ask`` help shows the --vault option."""
        result = runner.invoke(app, ["ask", "--help"])
        assert result.exit_code == 0
        assert "--vault" in result.stdout

    def test_ask_has_config_option(self, runner: CliRunner) -> None:
        """The ``ask`` help shows the --config option."""
        result = runner.invoke(app, ["ask", "--help"])
        assert result.exit_code == 0
        assert "--config" in result.stdout

    def test_ask_has_profile_option(self, runner: CliRunner) -> None:
        """The ``ask`` help shows the --profile option."""
        result = runner.invoke(app, ["ask", "--help"])
        assert result.exit_code == 0
        assert "--profile" in result.stdout

    def test_ask_has_allow_write_option(self, runner: CliRunner) -> None:
        """The ``ask`` help shows the --allow-write option."""
        result = runner.invoke(app, ["ask", "--help"])
        assert result.exit_code == 0
        assert "--allow-write" in result.stdout


class TestAskRespond:
    """Direct respond outcome rendering."""

    @patch("dnd_assistant.cli.ask.compose_ask_runtime")
    @patch("dnd_assistant.cli.ask._recovery_preflight")
    def test_respond_renders_message(
        self,
        mock_preflight: MagicMock,
        mock_compose: MagicMock,
        tmp_path: Path,
    ) -> None:
        """A RESPOND outcome prints the message to stdout."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir(parents=True)
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[profiles.test-agent]\nprovider='ollama'\nmodel='test'\n"
            "base_url='http://localhost:11434'\nrole='agent'\n",
            encoding="utf-8",
        )

        runtime = _make_fake_ask_runtime(
            outcome_message="Варос — опытный следопыт.",
            outcome_kind="respond",
        )
        mock_compose.return_value = runtime

        result = _invoke_ask_direct("Кто такой Варос?", vault_root, config_path)

        assert result.exit_code == 0
        assert "Варос — опытный следопыт." in result.stdout
        mock_preflight.assert_called_once()

    @patch("dnd_assistant.cli.ask.compose_ask_runtime")
    @patch("dnd_assistant.cli.ask._recovery_preflight")
    def test_respond_exit_code_0(
        self,
        mock_preflight: MagicMock,
        mock_compose: MagicMock,
        tmp_path: Path,
    ) -> None:
        """A RESPOND outcome exits with code 0."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir(parents=True)
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[profiles.test-agent]\nprovider='ollama'\nmodel='test'\n"
            "base_url='http://localhost:11434'\nrole='agent'\n",
            encoding="utf-8",
        )

        runtime = _make_fake_ask_runtime(
            outcome_message="Ответ.",
            outcome_kind="respond",
        )
        mock_compose.return_value = runtime

        result = _invoke_ask_direct("Тест", vault_root, config_path)
        assert result.exit_code == 0


class TestAskClarify:
    """Direct clarify outcome rendering."""

    @patch("dnd_assistant.cli.ask.compose_ask_runtime")
    @patch("dnd_assistant.cli.ask._recovery_preflight")
    def test_clarify_renders_message(
        self,
        mock_preflight: MagicMock,
        mock_compose: MagicMock,
        tmp_path: Path,
    ) -> None:
        """A CLARIFY outcome prints the clarification message to stdout."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir(parents=True)
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[profiles.test-agent]\nprovider='ollama'\nmodel='test'\n"
            "base_url='http://localhost:11434'\nrole='agent'\n",
            encoding="utf-8",
        )

        runtime = _make_fake_ask_runtime(
            outcome_message="Какого именно Вароса вы имеете в виду?",
            outcome_kind="clarify",
        )
        mock_compose.return_value = runtime

        result = _invoke_ask_direct("Обнови Вароса", vault_root, config_path)

        assert result.exit_code == 0
        assert "Какого именно Вароса вы имеете в виду?" in result.stdout

    @patch("dnd_assistant.cli.ask.compose_ask_runtime")
    @patch("dnd_assistant.cli.ask._recovery_preflight")
    def test_clarify_exit_code_0(
        self,
        mock_preflight: MagicMock,
        mock_compose: MagicMock,
        tmp_path: Path,
    ) -> None:
        """A CLARIFY outcome exits with code 0."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir(parents=True)
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[profiles.test-agent]\nprovider='ollama'\nmodel='test'\n"
            "base_url='http://localhost:11434'\nrole='agent'\n",
            encoding="utf-8",
        )

        runtime = _make_fake_ask_runtime(
            outcome_message="Уточните запрос.",
            outcome_kind="clarify",
        )
        mock_compose.return_value = runtime

        result = _invoke_ask_direct("Тест", vault_root, config_path)
        assert result.exit_code == 0


class TestAskErrorRendering:
    """Project error rendering."""

    @patch("dnd_assistant.cli.ask.compose_ask_runtime")
    @patch("dnd_assistant.cli.ask._recovery_preflight")
    def test_dnd_error_renders_to_stderr(
        self,
        mock_preflight: MagicMock,
        mock_compose: MagicMock,
        tmp_path: Path,
    ) -> None:
        """A ``DndAssistantError`` is rendered to stderr with exit code 1."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir(parents=True)
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[profiles.test-agent]\nprovider='ollama'\nmodel='test'\n"
            "base_url='http://localhost:11434'\nrole='agent'\n",
            encoding="utf-8",
        )

        def _raise_error(**kwargs: Any) -> MagicMock:
            raise DndAssistantError("Тестовая ошибка")

        mock_compose.side_effect = _raise_error

        result = _invoke_ask_direct("Тест", vault_root, config_path)

        assert result.exit_code == 1
        assert "Тестовая ошибка" in result.stderr

    @patch("dnd_assistant.cli.ask.compose_ask_runtime")
    @patch("dnd_assistant.cli.ask._recovery_preflight")
    def test_dnd_error_exit_code_1(
        self,
        mock_preflight: MagicMock,
        mock_compose: MagicMock,
        tmp_path: Path,
    ) -> None:
        """A ``DndAssistantError`` exits with code 1."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir(parents=True)
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[profiles.test-agent]\nprovider='ollama'\nmodel='test'\n"
            "base_url='http://localhost:11434'\nrole='agent'\n",
            encoding="utf-8",
        )

        def _raise_error(**kwargs: Any) -> MagicMock:
            raise DndAssistantError("Ошибка")

        mock_compose.side_effect = _raise_error

        result = _invoke_ask_direct("Тест", vault_root, config_path)
        assert result.exit_code == 1


class TestAskRecoveryErrors:
    """Recovery error rendering through the CLI error boundary."""

    @patch("dnd_assistant.cli.ask.compose_ask_runtime")
    @patch("dnd_assistant.cli.ask._recovery_preflight")
    def test_recovery_storage_error_renders_to_stderr(
        self,
        mock_preflight: MagicMock,
        mock_compose: MagicMock,
        tmp_path: Path,
    ) -> None:
        """A StorageError from recovery preflight renders to stderr with exit 1."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir(parents=True)
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[profiles.test-agent]\nprovider='ollama'\nmodel='test'\n"
            "base_url='http://localhost:11434'\nrole='agent'\n",
            encoding="utf-8",
        )

        mock_preflight.side_effect = StorageError("Recovery inspection failed")

        result = _invoke_ask_direct("Тест", vault_root, config_path)

        assert result.exit_code == 1
        assert "Ошибка:" in result.stderr
        assert "Recovery inspection failed" in result.stderr


class TestAskAllowWrite:
    """``--allow-write`` option propagation."""

    @patch("dnd_assistant.cli.ask.compose_ask_runtime")
    @patch("dnd_assistant.cli.ask._recovery_preflight")
    def test_allow_write_propagated(
        self,
        mock_preflight: MagicMock,
        mock_compose: MagicMock,
        tmp_path: Path,
    ) -> None:
        """``--allow-write`` is passed to ``compose_ask_runtime``."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir(parents=True)
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[profiles.test-agent]\nprovider='ollama'\nmodel='test'\n"
            "base_url='http://localhost:11434'\nrole='agent'\n",
            encoding="utf-8",
        )

        runtime = _make_fake_ask_runtime(
            outcome_message="Ответ.",
            outcome_kind="respond",
        )
        mock_compose.return_value = runtime

        _invoke_ask_direct("Тест", vault_root, config_path, allow_write=True)

        call_kwargs = mock_compose.call_args.kwargs
        assert call_kwargs.get("allow_write") is True

    @patch("dnd_assistant.cli.ask.compose_ask_runtime")
    @patch("dnd_assistant.cli.ask._recovery_preflight")
    def test_default_read_only(
        self,
        mock_preflight: MagicMock,
        mock_compose: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Without ``--allow-write``, ``allow_write`` is ``False``."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir(parents=True)
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[profiles.test-agent]\nprovider='ollama'\nmodel='test'\n"
            "base_url='http://localhost:11434'\nrole='agent'\n",
            encoding="utf-8",
        )

        runtime = _make_fake_ask_runtime(
            outcome_message="Ответ.",
            outcome_kind="respond",
        )
        mock_compose.return_value = runtime

        _invoke_ask_direct("Тест", vault_root, config_path, allow_write=False)

        call_kwargs = mock_compose.call_args.kwargs
        assert call_kwargs.get("allow_write") is False


class TestAskClose:
    """Provider cleanup."""

    @patch("dnd_assistant.cli.ask.compose_ask_runtime")
    @patch("dnd_assistant.cli.ask._recovery_preflight")
    def test_close_called_on_success(
        self,
        mock_preflight: MagicMock,
        mock_compose: MagicMock,
        tmp_path: Path,
    ) -> None:
        """``close()`` is called after a successful respond."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir(parents=True)
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[profiles.test-agent]\nprovider='ollama'\nmodel='test'\n"
            "base_url='http://localhost:11434'\nrole='agent'\n",
            encoding="utf-8",
        )

        close_track: list[bool] = []
        runtime = _make_fake_ask_runtime(
            outcome_message="Ответ.",
            outcome_kind="respond",
            close_called=close_track,
        )
        mock_compose.return_value = runtime

        _invoke_ask_direct("Тест", vault_root, config_path)

        assert len(close_track) == 1

    @patch("dnd_assistant.cli.ask.compose_ask_runtime")
    @patch("dnd_assistant.cli.ask._recovery_preflight")
    def test_close_called_on_error(
        self,
        mock_preflight: MagicMock,
        mock_compose: MagicMock,
        tmp_path: Path,
    ) -> None:
        """``close()`` is called even when a ``DndAssistantError`` occurs."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir(parents=True)
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[profiles.test-agent]\nprovider='ollama'\nmodel='test'\n"
            "base_url='http://localhost:11434'\nrole='agent'\n",
            encoding="utf-8",
        )

        close_track: list[bool] = []
        runtime = _make_fake_ask_runtime(
            outcome_message="Ошибка.",
            outcome_kind="respond",
            close_called=close_track,
        )
        runtime.agent_loop.run.side_effect = DndAssistantError("Ошибка")
        mock_compose.return_value = runtime

        _invoke_ask_direct("Тест", vault_root, config_path)

        assert len(close_track) == 1


class TestAskUnexpectedException:
    """Unexpected exceptions must NOT be broad-caught."""

    @patch("dnd_assistant.cli.ask.compose_ask_runtime")
    @patch("dnd_assistant.cli.ask._recovery_preflight")
    def test_unexpected_exception_not_broad_caught(
        self,
        mock_preflight: MagicMock,
        mock_compose: MagicMock,
        tmp_path: Path,
    ) -> None:
        """A non-DndAssistantError exception propagates."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir(parents=True)
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[profiles.test-agent]\nprovider='ollama'\nmodel='test'\n"
            "base_url='http://localhost:11434'\nrole='agent'\n",
            encoding="utf-8",
        )

        def _raise_runtime(**kwargs: Any) -> MagicMock:
            raise RuntimeError("Неожиданная ошибка")

        mock_compose.side_effect = _raise_runtime

        result = _invoke_ask_direct("Тест", vault_root, config_path)

        # RuntimeError is not a DndAssistantError — should NOT be caught
        assert "Ошибка:" not in (result.stderr or "")
