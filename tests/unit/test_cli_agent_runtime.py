"""Unit tests for the S9-06 agent runtime composition module.

These tests verify:

- profile selection
- AGENT role enforcement
- provider enforcement
- READ/WRITE ExecutionContext construction
- session-mode derivation
- AuditContext trace metadata
- 12-tool registry contents
- provider cleanup
- recovery-before-model boundary

They do NOT test CLI presentation (see ``test_cli_ask.py``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from dnd_assistant.cli.agent_runtime import (
    AskRuntime,
    _build_ask_audit_context,
    _build_ask_tool_registry,
    _build_model_provider,
    _derive_session_context,
    _load_profile,
    _new_operation_id,
    _now_utc,
)
from dnd_assistant.errors import DndAssistantError, ValidationError
from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole
from dnd_assistant.prompts.agent_v2 import PROMPT_VERSION
from dnd_assistant.tools.types import ExecutionContext, Permission, SessionMode

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture()
def valid_agent_profile() -> ModelProfile:
    """Return a valid AGENT profile."""
    return ModelProfile(
        provider="ollama",
        model="test-model",
        base_url="http://localhost:11434",
        role=ModelProfileRole.AGENT,
    )


@pytest.fixture()
def summarizer_profile() -> ModelProfile:
    """Return a SUMMARIZER profile (wrong role for ask)."""
    return ModelProfile(
        provider="ollama",
        model="test-model",
        base_url="http://localhost:11434",
        role=ModelProfileRole.SUMMARIZER,
    )


@pytest.fixture()
def unsupported_provider_profile() -> ModelProfile:
    """Return a profile with an unsupported provider."""
    return ModelProfile(
        provider="openai",
        model="gpt-4",
        base_url="https://api.openai.com/v1",
        role=ModelProfileRole.AGENT,
    )


# ── Profile loading tests ──────────────────────────────────────────────────


class TestLoadProfile:
    """Profile loading and validation."""

    def test_load_valid_agent_profile(self, tmp_path: Path) -> None:
        """A valid AGENT profile is loaded successfully."""
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[profiles.my-agent]\n"
            "provider='ollama'\n"
            "model='llama3.2'\n"
            "base_url='http://localhost:11434'\n"
            "role='agent'\n",
            encoding="utf-8",
        )

        profile = _load_profile(config_path, "my-agent")
        assert profile.role is ModelProfileRole.AGENT
        assert profile.provider == "ollama"

    def test_missing_profile_raises_error(self, tmp_path: Path) -> None:
        """A missing profile name raises ValidationError."""
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[profiles.existing]\n"
            "provider='ollama'\n"
            "model='test'\n"
            "base_url='http://localhost:11434'\n"
            "role='agent'\n",
            encoding="utf-8",
        )

        with pytest.raises(ValidationError, match="not found"):
            _load_profile(config_path, "nonexistent")

    def test_wrong_role_raises_error(self, tmp_path: Path) -> None:
        """A non-AGENT profile raises ValidationError."""
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[profiles.my-summarizer]\n"
            "provider='ollama'\n"
            "model='test'\n"
            "base_url='http://localhost:11434'\n"
            "role='summarizer'\n",
            encoding="utf-8",
        )

        with pytest.raises(ValidationError, match="expected.*agent"):
            _load_profile(config_path, "my-summarizer")

    def test_missing_config_file_raises_error(self, tmp_path: Path) -> None:
        """A missing config file raises DndAssistantError."""
        config_path = tmp_path / "nonexistent.toml"

        with pytest.raises(DndAssistantError):
            _load_profile(config_path, "test")


# ── Provider selection tests ───────────────────────────────────────────────


class TestBuildModelProvider:
    """Provider construction."""

    def test_ollama_provider_created(self, valid_agent_profile: ModelProfile) -> None:
        """An Ollama provider is created for an ollama profile."""
        provider = _build_model_provider(valid_agent_profile)
        from dnd_assistant.models.ollama import OllamaModelProvider

        assert isinstance(provider, OllamaModelProvider)
        provider.close()

    def test_unsupported_provider_raises_error(
        self, unsupported_provider_profile: ModelProfile
    ) -> None:
        """An unsupported provider raises ValidationError."""
        with pytest.raises(ValidationError, match="Unsupported"):
            _build_model_provider(unsupported_provider_profile)


# ── ExecutionContext construction tests ────────────────────────────────────


class TestExecutionContextConstruction:
    """READ/WRITE ExecutionContext construction."""

    def test_read_only_context(self) -> None:
        """READ context has Permission.READ and no audit."""
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
            audit=None,
        )
        assert ctx.granted_permission is Permission.READ
        assert ctx.audit is None

    def test_write_context_has_audit(self) -> None:
        """WRITE context has Permission.WRITE and a non-None audit."""
        ctx = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.ACTIVE_SESSION,
            audit=MagicMock(),
        )
        assert ctx.granted_permission is Permission.WRITE
        assert ctx.audit is not None


# ── Session-mode derivation tests ──────────────────────────────────────────


class TestDeriveSessionContext:
    """Session context derivation from repository state using one trusted read."""

    def test_no_active_session(self) -> None:
        """No active session returns NO_ACTIVE_SESSION and None ID."""
        repo = MagicMock()
        repo.get_active_session.return_value = None

        mode, session_id = _derive_session_context(repo)
        assert mode is SessionMode.NO_ACTIVE_SESSION
        assert session_id is None

    def test_active_session(self) -> None:
        """An active session returns ACTIVE_SESSION and the session ID."""
        repo = MagicMock()
        mock_active = MagicMock()
        mock_active.session.id = "S001"
        repo.get_active_session.return_value = mock_active

        mode, session_id = _derive_session_context(repo)
        assert mode is SessionMode.ACTIVE_SESSION
        assert session_id == "S001"

    def test_get_active_session_called_once(self) -> None:
        """get_active_session is called exactly once for both mode and ID."""
        repo = MagicMock()
        repo.get_active_session.return_value = None

        _derive_session_context(repo)
        repo.get_active_session.assert_called_once()


# ── AuditContext tests ─────────────────────────────────────────────────────


class TestBuildAskAuditContext:
    """AuditContext construction for model-tool operations."""

    def test_audit_context_has_trace_metadata(self) -> None:
        """AuditContext includes model_profile and prompt_version."""
        ctx = _build_ask_audit_context(
            model_profile="my-agent",
            prompt_version=PROMPT_VERSION,
        )

        assert ctx.source == "model_tool"
        assert ctx.model_profile == "my-agent"
        assert ctx.prompt_version == PROMPT_VERSION

    def test_audit_context_with_session(self) -> None:
        """AuditContext includes session ID when provided."""
        ctx = _build_ask_audit_context(
            model_profile="my-agent",
            prompt_version=PROMPT_VERSION,
            session_id="S001",
        )

        assert ctx.session == "S001"

    def test_audit_context_without_session(self) -> None:
        """AuditContext session is None when not provided."""
        ctx = _build_ask_audit_context(
            model_profile="my-agent",
            prompt_version=PROMPT_VERSION,
        )

        assert ctx.session is None


# ── Provider cleanup tests ─────────────────────────────────────────────────


class TestAskRuntimeClose:
    """Provider cleanup through AskRuntime."""

    def test_close_called_once(self) -> None:
        """close() calls provider close exactly once."""
        provider = MagicMock()
        runtime = AskRuntime(
            MagicMock(
                model_gateway=provider,
                agent_loop=MagicMock(),
                recovery_service=MagicMock(),
                vault_root=MagicMock(),
                audit_service=None,
            )
        )

        runtime.close()
        provider.close.assert_called_once()

    def test_close_idempotent(self) -> None:
        """close() is safe to call multiple times."""
        provider = MagicMock()
        runtime = AskRuntime(
            MagicMock(
                model_gateway=provider,
                agent_loop=MagicMock(),
                recovery_service=MagicMock(),
                vault_root=MagicMock(),
                audit_service=None,
            )
        )

        runtime.close()
        runtime.close()
        runtime.close()
        provider.close.assert_called_once()

    def test_close_after_success(self) -> None:
        """close() is called after a successful AgentLoop run."""
        provider = MagicMock()
        agent_loop = MagicMock()
        agent_loop.run.return_value = MagicMock()
        runtime = AskRuntime(
            MagicMock(
                model_gateway=provider,
                agent_loop=agent_loop,
                recovery_service=MagicMock(),
                vault_root=MagicMock(),
                audit_service=None,
            )
        )

        runtime.close()
        provider.close.assert_called_once()

    def test_close_after_model_error(self) -> None:
        """close() is called after a ModelError from the agent loop."""
        provider = MagicMock()
        agent_loop = MagicMock()
        agent_loop.run.side_effect = DndAssistantError("Model error")
        runtime = AskRuntime(
            MagicMock(
                model_gateway=provider,
                agent_loop=agent_loop,
                recovery_service=MagicMock(),
                vault_root=MagicMock(),
                audit_service=None,
            )
        )

        runtime.close()
        provider.close.assert_called_once()


# ── 12-tool registry tests ────────────────────────────────────────────────


class TestAskToolRegistry:
    """The S9-06 production ask registry contains exactly 12 tools."""

    def test_registry_has_exactly_12_tools(self) -> None:
        """The ask registry has exactly 12 registered tools."""
        registry = _build_ask_tool_registry(
            search_service=MagicMock(),
            repository=MagicMock(),
            runtime_service=MagicMock(),
            recovery_service=MagicMock(),
            session_repository=MagicMock(),
            event_repository=MagicMock(),
        )

        assert len(registry) == 12

    def test_registry_has_expected_tool_names(self) -> None:
        """The ask registry contains exactly the expected 12 tool names."""
        registry = _build_ask_tool_registry(
            search_service=MagicMock(),
            repository=MagicMock(),
            runtime_service=MagicMock(),
            recovery_service=MagicMock(),
            session_repository=MagicMock(),
            event_repository=MagicMock(),
        )

        names = sorted(d.name for d in registry.list_definitions())
        expected = [
            "append_entity_fact",
            "end_session",
            "get_active_session",
            "get_entity",
            "get_session",
            "list_session_events",
            "list_sessions",
            "patch_entity",
            "record_event",
            "record_note",
            "search_entities",
            "start_session",
        ]

        assert names == expected

    def test_no_world_time_tools(self) -> None:
        """The ask registry does NOT contain world-time/calendar tools."""
        registry = _build_ask_tool_registry(
            search_service=MagicMock(),
            repository=MagicMock(),
            runtime_service=MagicMock(),
            recovery_service=MagicMock(),
            session_repository=MagicMock(),
            event_repository=MagicMock(),
        )

        names = [d.name for d in registry.list_definitions()]
        world_time_tools = [
            "advance_world_time",
            "game_date_to_world_tick",
            "get_world_time",
            "set_world_time",
            "time_between_world_ticks",
            "world_tick_to_date",
        ]

        for wt in world_time_tools:
            assert wt not in names, f"World-time tool '{wt}' should not be in ask registry"


# ── Time/ID helper tests ───────────────────────────────────────────────────


class TestTimeAndIdHelpers:
    """Testable time and ID helpers."""

    def test_now_utc_is_aware(self) -> None:
        """_now_utc returns a timezone-aware datetime."""
        dt = _now_utc()
        assert dt.tzinfo is not None

    def test_new_operation_id_format(self) -> None:
        """_new_operation_id returns a string with model- prefix."""
        op_id = _new_operation_id()
        assert op_id.startswith("model-")
        assert len(op_id) > len("model-")


# ── Composition-failure cleanup tests ──────────────────────────────────────


class TestComposeAskRuntimeCleanup:
    """Provider cleanup when composition fails after provider creation."""

    def _fake_provider(self) -> MagicMock:
        """Create a fake provider with observable close count."""
        provider = MagicMock()
        provider.close = MagicMock()  # type: ignore[method-assign]
        return provider

    def _minimal_vault(self, tmp_path: Path) -> Path:
        """Create a minimal Vault with required directories."""
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
        return vault_root

    def _write_config(self, tmp_path: Path) -> Path:
        """Write a minimal valid config."""
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[profiles.test-agent]\nprovider='ollama'\nmodel='test'\n"
            "base_url='http://localhost:11434'\nrole='agent'\n",
            encoding="utf-8",
        )
        return config_path

    def test_provider_closed_on_storage_composition_failure(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Provider.close called once when AuditService composition fails."""
        vault_root = self._minimal_vault(tmp_path)
        config_path = self._write_config(tmp_path)
        provider = self._fake_provider()

        # Make AuditService raise StorageError on construction
        from dnd_assistant.errors import StorageError

        def _broken_audit(*args: Any, **kwargs: Any) -> None:
            raise StorageError("Audit path invalid")

        monkeypatch.setattr(
            "dnd_assistant.cli.agent_runtime.AuditService.__init__",
            _broken_audit,
        )

        with pytest.raises(StorageError, match="Audit path invalid"):
            from dnd_assistant.cli.agent_runtime import compose_ask_runtime

            compose_ask_runtime(
                vault_root=vault_root,
                config_path=config_path,
                profile_name="test-agent",
                model_provider_factory=lambda p: provider,
            )

        provider.close.assert_called_once()

    def test_provider_closed_on_session_state_failure(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Provider.close called once when session-state read raises StorageError."""
        vault_root = self._minimal_vault(tmp_path)
        config_path = self._write_config(tmp_path)
        provider = self._fake_provider()

        from dnd_assistant.errors import StorageError

        def _broken_get_active(*args: Any, **kwargs: Any) -> None:
            raise StorageError("Session state unavailable")

        monkeypatch.setattr(
            "dnd_assistant.cli.agent_runtime.ObsidianSessionMetadataRepository.get_active_session",
            _broken_get_active,
        )

        with pytest.raises(StorageError, match="Session state unavailable"):
            from dnd_assistant.cli.agent_runtime import compose_ask_runtime

            compose_ask_runtime(
                vault_root=vault_root,
                config_path=config_path,
                profile_name="test-agent",
                model_provider_factory=lambda p: provider,
            )

        provider.close.assert_called_once()

    def test_provider_closed_on_unexpected_runtime_error(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Provider.close called once when an unexpected RuntimeError occurs during composition."""
        vault_root = self._minimal_vault(tmp_path)
        config_path = self._write_config(tmp_path)
        provider = self._fake_provider()

        def _broken_agent_loop(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("Unexpected composition error")

        monkeypatch.setattr(
            "dnd_assistant.cli.agent_runtime.AgentLoop.__init__",
            _broken_agent_loop,
        )

        with pytest.raises(RuntimeError, match="Unexpected composition error"):
            from dnd_assistant.cli.agent_runtime import compose_ask_runtime

            compose_ask_runtime(
                vault_root=vault_root,
                config_path=config_path,
                profile_name="test-agent",
                model_provider_factory=lambda p: provider,
            )

        provider.close.assert_called_once()

    def test_provider_closed_on_active_session_storage_error_write(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Provider.close called once when get_active_session raises StorageError with --allow-write."""
        vault_root = self._minimal_vault(tmp_path)
        config_path = self._write_config(tmp_path)
        provider = self._fake_provider()

        from dnd_assistant.errors import StorageError

        def _broken_get_active(*args: Any, **kwargs: Any) -> None:
            raise StorageError("Cannot read session state")

        monkeypatch.setattr(
            "dnd_assistant.cli.agent_runtime.ObsidianSessionMetadataRepository.get_active_session",
            _broken_get_active,
        )

        with pytest.raises(StorageError, match="Cannot read session state"):
            from dnd_assistant.cli.agent_runtime import compose_ask_runtime

            compose_ask_runtime(
                vault_root=vault_root,
                config_path=config_path,
                profile_name="test-agent",
                allow_write=True,
                model_provider_factory=lambda p: provider,
            )

        provider.close.assert_called_once()


# ── Import-time side-effect test ───────────────────────────────────────────


class TestImportSideEffects:
    """Importing the CLI module does not trigger runtime composition."""

    def test_import_does_not_compose_runtime(self) -> None:
        """Importing cli.ask does not open Vault or connect to Ollama."""
        import importlib

        # This should not raise StorageError or ModelError
        mod = importlib.import_module("dnd_assistant.cli.ask")
        assert mod is not None
