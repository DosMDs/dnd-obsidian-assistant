"""S12-04 Campaign State consumer integration tests.

Runs the real lazy-rebuild provider against a real temporary Vault, real
repositories and the real derived-state store: rebuild/repair/current
lifecycle, graceful vs fail-closed behavior, canonical read-only safety, and a
deterministic fake-model end-to-end proof that the first USER payload carries
only player-safe campaign memory.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from dnd_assistant.application.agent_context import AgentContextBuilder
from dnd_assistant.application.campaign_state_consumer import (
    FAST_AGENT_RECENT_SESSION_LIMIT,
    RebuildPlayerCampaignStateProvider,
)
from dnd_assistant.application.pydantic_ai_fast_agent import PydanticAIFastAgent
from dnd_assistant.application.pydantic_ai_run_deps import DndAgentRunPreparer
from dnd_assistant.application.pydantic_ai_tool_bridge import PydanticAIToolBridge
from dnd_assistant.domain.campaign_state import CampaignStateArtifact
from dnd_assistant.domain.types import Visibility
from dnd_assistant.errors import StorageError
from dnd_assistant.tools.catalog import build_tool_registry_schema
from dnd_assistant.tools.types import ExecutionContext, Permission, SessionMode
from tests.support.context_builder_doubles import NullSearchService, NullSessionEventRepository
from tests.support.pydantic_ai_runtime import HandlerCounters, make_tool_registry
from tests.unit.campaign_state.helpers import (
    BASE_START,
    Services,
    close_session,
    create_entity,
    make_audit_context,
    make_entity,
    make_services,
    make_vault,
    setup_entity_dirs,
    snapshot,
)

_DM_NAME = "Тайный Лорд"
_SYS_NAME = "Система"


def _initialized(tmp_path: Path, *, tick: int = 150) -> Services:
    root = make_vault(tmp_path)
    setup_entity_dirs(root)
    services = make_services(root)
    services.world_time.initialize_current_world_time(
        tick, audit=make_audit_context(operation_id="wt-init", real_time=BASE_START)
    )
    return services


def _provider(services: Services) -> RebuildPlayerCampaignStateProvider:
    return RebuildPlayerCampaignStateProvider(
        vault_repository=services.vault,
        session_repository=services.metadata,
        world_time_repository=services.world_time,
        derived_state_store=services.store,
        recent_session_limit=FAST_AGENT_RECENT_SESSION_LIMIT,
    )


def _seed_mixed(services: Services) -> None:
    create_entity(services, make_entity("npc-player", name="Aria"))
    create_entity(services, make_entity("npc-dm", name=_DM_NAME, visibility=Visibility.DM))
    create_entity(services, make_entity("npc-sys", name=_SYS_NAME, visibility=Visibility.SYSTEM))
    close_session(
        services,
        "S001",
        finish=BASE_START.replace(hour=15),
        touched=("npc-player", "npc-dm", "npc-sys"),
    )


class TestLifecycle:
    def test_missing_generation_rebuilt_then_projected(self, tmp_path: Path) -> None:
        services = _initialized(tmp_path)
        _seed_mixed(services)
        provider = _provider(services)

        first = provider.get_player_campaign_state()
        assert first is not None
        assert [r.entity_id for r in first.recently_touched] == ["npc-player"]
        assert services.store.read_manifest_text() is not None

        second = provider.get_player_campaign_state()
        assert second == first

    def test_stale_generation_repaired(self, tmp_path: Path) -> None:
        services = _initialized(tmp_path)
        _seed_mixed(services)
        provider = _provider(services)
        provider.get_player_campaign_state()

        create_entity(services, make_entity("npc-new", name="Брен"))
        close_session(
            services,
            "S002",
            finish=BASE_START.replace(hour=16),
            touched=("npc-new",),
        )

        repaired = provider.get_player_campaign_state()
        assert repaired is not None
        assert {r.entity_id for r in repaired.recently_touched} == {"npc-player", "npc-new"}
        touched_bytes = services.store.read_artifact_bytes(CampaignStateArtifact.RECENTLY_TOUCHED)
        assert touched_bytes is not None
        assert "Брен" in touched_bytes.decode("utf-8")

    def test_world_time_unavailable_is_graceful(self, tmp_path: Path) -> None:
        root = make_vault(tmp_path)
        setup_entity_dirs(root)
        provider = _provider(make_services(root))
        assert provider.get_player_campaign_state() is None

    def test_unsafe_state_symlink_fails_closed(self, tmp_path: Path) -> None:
        services = _initialized(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        state_dir = services.root / "State"
        try:
            os.symlink(outside, state_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("host cannot create symlinks")

        with pytest.raises(StorageError):
            _provider(services).get_player_campaign_state()


class TestCanonicalReadOnly:
    def test_lazy_rebuild_only_adds_derived_state_files(self, tmp_path: Path) -> None:
        services = _initialized(tmp_path)
        _seed_mixed(services)

        before = snapshot(services.root)
        collection = _provider(services).get_player_campaign_state()
        assert collection is not None
        after = snapshot(services.root)

        assert set(after) >= set(before)
        assert not set(before) - set(after)
        added = set(after) - set(before)
        assert added, "lazy rebuild should materialize managed State files"
        assert all(path.startswith("State/") for path in added), sorted(added)

    def test_no_canonical_audit_append(self, tmp_path: Path) -> None:
        services = _initialized(tmp_path)
        _seed_mixed(services)
        audit_path = services.root / "_system" / "audit" / "audit.jsonl"
        before = audit_path.read_bytes()

        _provider(services).get_player_campaign_state()

        assert audit_path.read_bytes() == before


class TestEndToEndUserPayload:
    def _build_agent(self, services: Services) -> tuple[PydanticAIFastAgent, list[Any]]:
        captured: list[list[ModelMessage]] = []

        def _respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            captured.append(list(messages))
            return ModelResponse(parts=[TextPart(content='{"kind":"respond","message":"ok"}')])

        context_builder = AgentContextBuilder(
            search_service=NullSearchService(),
            vault_repository=services.vault,
            session_repository=services.metadata,
            event_repository=NullSessionEventRepository(),
            world_time_repository=services.world_time,
            campaign_state_provider=_provider(services),
        )
        registry = make_tool_registry(HandlerCounters())
        catalog = build_tool_registry_schema(registry)
        bridge = PydanticAIToolBridge(registry=registry)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=catalog,
            tool_bridge=bridge,
        )
        agent = PydanticAIFastAgent(run_preparer=preparer, model=FunctionModel(_respond))
        return agent, captured

    def test_first_user_payload_is_player_safe(self, tmp_path: Path) -> None:
        services = _initialized(tmp_path)
        _seed_mixed(services)
        agent, captured = self._build_agent(services)

        decision = agent.decide(
            "Кто такая Ария?",
            execution_context=ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=None,
            ),
        )

        assert decision.prompt_version == "agent-v3"
        assert captured, "model must have been called once"

        user_content: str | None = None
        for message in captured[0]:
            if isinstance(message, ModelRequest):
                for part in message.parts:
                    if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                        user_content = part.content
        assert user_content is not None

        parsed = json.loads(user_content)
        assert parsed["campaign_memory"] == {
            "recently_touched": [{"entity_id": "npc-player", "entity_type": "npc", "name": "Aria"}],
            "total_recently_touched": 1,
            "truncated": False,
        }
        for leaked in (_DM_NAME, "npc-dm", _SYS_NAME, "npc-sys"):
            assert leaked not in user_content


class TestReadOnlyToolExposure:
    def test_default_read_context_exposes_no_write_tools(self) -> None:
        from unittest.mock import MagicMock

        from dnd_assistant.application.agent_tool_selection import select_agent_tools
        from dnd_assistant.cli.agent_runtime import _build_ask_tool_registry

        registry = _build_ask_tool_registry(
            search_service=MagicMock(),
            repository=MagicMock(),
            runtime_service=MagicMock(),
            recovery_service=MagicMock(),
            session_repository=MagicMock(),
            event_repository=MagicMock(),
        )
        catalog = build_tool_registry_schema(registry)
        context = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
            audit=None,
        )
        selected = select_agent_tools(catalog, context=context)
        assert selected
        assert all(tool.permission is Permission.READ for tool in selected)
