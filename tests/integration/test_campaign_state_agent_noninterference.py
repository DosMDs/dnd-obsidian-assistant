"""S12-05 Fast-Agent hidden-data noninterference and lazy consumer recovery.

Proves that two real Fast-Agent preparations whose PLAYER-visible evidence is
identical while DM/SYSTEM Campaign State evidence differs produce the **same
first actual Pydantic AI USER payload** (equality, not just sentinel absence),
and that the lazy provider fails closed / repairs correctly after interrupted
or corrupt derived publication.

No Ollama, no network: the Pydantic AI model is a deterministic ``FunctionModel``.
"""

from __future__ import annotations

import json
from pathlib import Path

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
from dnd_assistant.application.campaign_state_materialization import (
    CampaignStateStatus,
)
from dnd_assistant.application.campaign_state_render import (
    CAMPAIGN_STATE_RENDER_VERSION,
)
from dnd_assistant.application.campaign_state_source import CampaignStateSourceError
from dnd_assistant.application.pydantic_ai_fast_agent import PydanticAIFastAgent
from dnd_assistant.application.pydantic_ai_run_deps import DndAgentRunPreparer
from dnd_assistant.application.pydantic_ai_tool_bridge import PydanticAIToolBridge
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
    rebuild,
    setup_entity_dirs,
)

_TICK = 150
_DM_NAME = "Тайный Лорд"
_SYS_NAME = "Система"


def _initialized(tmp_path: Path, *, tick: int = _TICK) -> Services:
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


def _seed(services: Services, hidden: tuple[tuple[str, str, Visibility], ...]) -> None:
    create_entity(services, make_entity("npc-player", name="Aria"))
    for entity_id, name, visibility in hidden:
        create_entity(services, make_entity(entity_id, name=name, visibility=visibility))
    touched = ("npc-player",) + tuple(entity_id for entity_id, _n, _v in hidden)
    close_session(
        services,
        "S001",
        finish=BASE_START.replace(hour=15),
        touched=touched,
    )


def _build_agent(services: Services) -> tuple[PydanticAIFastAgent, list[list[ModelMessage]]]:
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
    return PydanticAIFastAgent(run_preparer=preparer, model=FunctionModel(_respond)), captured


def _first_user_payload(captured: list[list[ModelMessage]]) -> str:
    assert captured, "model must have been called"
    for message in captured[0]:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    return part.content
    raise AssertionError("first USER payload not captured")


def _run(agent: PydanticAIFastAgent, text: str = "Кто такая Ария?"):
    return agent.decide(
        text,
        execution_context=ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
            audit=None,
        ),
    )


# ── Hidden-data noninterference at the first actual model request ──────────


class TestFirstUserPayloadNoninterference:
    def test_hidden_only_difference_yields_identical_first_payload(self, tmp_path: Path) -> None:
        vault_a = tmp_path / "a"
        vault_b = tmp_path / "b"
        vault_a.mkdir()
        vault_b.mkdir()
        services_a = _initialized(vault_a)
        services_b = _initialized(vault_b)

        _seed(
            services_a,
            (
                ("npc-dm", _DM_NAME, Visibility.DM),
                ("npc-sys", _SYS_NAME, Visibility.SYSTEM),
            ),
        )
        # State B: same PLAYER evidence; hidden evidence differs in ids, names,
        # count and revisions.
        _seed(
            services_b,
            (
                ("npc-hidden-one", "Другая Тайна", Visibility.DM),
                ("npc-hidden-two", "Ещё Система", Visibility.SYSTEM),
                ("npc-hidden-three", "Третий", Visibility.DM),
            ),
        )

        agent_a, captured_a = _build_agent(services_a)
        agent_b, captured_b = _build_agent(services_b)
        decision_a = _run(agent_a)
        decision_b = _run(agent_b)

        payload_a = _first_user_payload(captured_a)
        payload_b = _first_user_payload(captured_b)
        assert payload_a == payload_b

        assert decision_a.prompt_version == "agent-v3"
        assert decision_b.prompt_version == "agent-v3"

        parsed = json.loads(payload_a)
        assert parsed["campaign_memory"] == {
            "recently_touched": [{"entity_id": "npc-player", "entity_type": "npc", "name": "Aria"}],
            "total_recently_touched": 1,
            "truncated": False,
        }
        for leaked in (
            _DM_NAME,
            _SYS_NAME,
            "npc-dm",
            "npc-sys",
            "npc-hidden-one",
            "npc-hidden-two",
            "npc-hidden-three",
            "Другая Тайна",
            "Ещё Система",
        ):
            assert leaked not in payload_a


# ── Production composition: READ-only maintenance ──────────────────────────


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[profiles.test-agent]\nprovider='ollama'\nmodel='test'\n"
        "base_url='http://localhost:11434'\nrole='agent'\n",
        encoding="utf-8",
    )
    return config_path


def _canonical_bytes(root: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for name in ("Characters", "Locations", "Quests", "Items"):
        base = root / name
        if base.exists():
            for path in base.rglob("*.md"):
                result[path.relative_to(root).as_posix()] = path.read_bytes()
    raw = root / "_system" / "raw"
    if raw.exists():
        for path in raw.rglob("*"):
            if path.is_file():
                result[path.relative_to(root).as_posix()] = path.read_bytes()
    world_time = root / "_system" / "world_time.json"
    if world_time.exists():
        result["_system/world_time.json"] = world_time.read_bytes()
    return result


class TestProductionCompositionReadOnly:
    def test_read_run_repairs_derived_state_without_canonical_change(self, tmp_path: Path) -> None:
        from dnd_assistant.cli.agent_runtime import compose_ask_runtime

        services = _initialized(tmp_path)
        _seed(services, (("npc-dm", _DM_NAME, Visibility.DM),))
        rebuild(services)
        # Make the derived generation stale by advancing canonical world time.
        services.world_time.set_current_world_time(
            999,
            expected_revision=1,
            audit=make_audit_context(operation_id="wt-set", real_time=BASE_START),
        )

        # Production composition uses the real FTS-backed search service.
        from dnd_assistant.retrieval.index import SqliteFtsIndex

        SqliteFtsIndex(vault_root=str(services.root)).rebuild(services.vault.list_entities())

        audit_path = services.root / "_system" / "audit" / "audit.jsonl"
        audit_before = audit_path.read_bytes()
        canonical_before = _canonical_bytes(services.root)

        def _respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content='{"kind":"respond","message":"ok"}')])

        runtime = compose_ask_runtime(
            vault_root=services.root,
            config_path=_write_config(tmp_path),
            profile_name="test-agent",
            model_factory=lambda p: FunctionModel(_respond),
        )
        try:
            assert runtime.execution_context.granted_permission is Permission.READ
            result = runtime.agent_runtime.run(
                "Какой сейчас игровой тик?",
                execution_context=runtime.execution_context,
            )
            assert result.initial_decision.prompt_version == "agent-v3"
            assert all(
                tool.permission is Permission.READ for tool in result.initial_decision.exposed_tools
            )
        finally:
            runtime.close()

        # Derived State was repaired...
        world_state = (services.root / "State" / "World State.md").read_text(encoding="utf-8")
        assert "999" in world_state
        # ...without canonical mutation or canonical audit.
        assert _canonical_bytes(services.root) == canonical_before
        assert audit_path.read_bytes() == audit_before


# ── Lazy consumer recovery ─────────────────────────────────────────────────


class TestLazyRecovery:
    def _seed(self, tmp_path: Path) -> Services:
        services = _initialized(tmp_path)
        _seed(services, (("npc-dm", _DM_NAME, Visibility.DM),))
        return services

    def test_outdated_render_v2_is_repaired(self, tmp_path: Path) -> None:
        services = self._seed(tmp_path)
        provider = _provider(services)
        assert provider.get_player_campaign_state() is not None

        # Downgrade the persisted render version to the pre-S12-05 generation.
        manifest_path = services.store.state_dir / ".campaign-state-manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["render_version"] == CAMPAIGN_STATE_RENDER_VERSION
        data["render_version"] = "2"
        manifest_path.write_text(json.dumps(data), encoding="utf-8")

        from dnd_assistant.application.campaign_state_materialization import (
            inspect_campaign_state,
        )

        assert (
            inspect_campaign_state(
                vault_repository=services.vault,
                session_repository=services.metadata,
                world_time_repository=services.world_time,
                derived_state_store=services.store,
                recent_session_limit=FAST_AGENT_RECENT_SESSION_LIMIT,
            ).status
            is CampaignStateStatus.OUTDATED
        )

        repaired = provider.get_player_campaign_state()
        assert repaired is not None
        assert [r.entity_id for r in repaired.recently_touched] == ["npc-player"]
        assert (
            json.loads(manifest_path.read_text(encoding="utf-8"))["render_version"]
            == CAMPAIGN_STATE_RENDER_VERSION
        )

    def test_corrupt_artifact_is_repaired(self, tmp_path: Path) -> None:
        services = self._seed(tmp_path)
        provider = _provider(services)
        assert provider.get_player_campaign_state() is not None

        artifact = services.store.state_dir / "World State.md"
        artifact.write_text("# tampered\n", encoding="utf-8")

        repaired = provider.get_player_campaign_state()
        assert repaired is not None
        assert "tampered" not in artifact.read_text(encoding="utf-8")

    def test_missing_generation_is_repaired(self, tmp_path: Path) -> None:
        services = self._seed(tmp_path)
        provider = _provider(services)
        assert not services.store.state_dir.exists()
        assert provider.get_player_campaign_state() is not None
        assert services.store.read_manifest_text() is not None

    def test_malformed_canonical_evidence_propagates(self, tmp_path: Path) -> None:
        services = self._seed(tmp_path)
        close_session(
            services,
            "S002",
            finish=BASE_START.replace(hour=16),
            touched=("npc-does-not-exist",),
        )
        with pytest.raises(CampaignStateSourceError):
            _provider(services).get_player_campaign_state()

    def test_unsafe_topology_fails_closed(self, tmp_path: Path) -> None:
        import os
        import subprocess

        services = self._seed(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        state_dir = services.root / "State"
        if os.name != "nt":
            pytest.skip("Windows junction test")
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(state_dir), str(outside)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not state_dir.is_junction():
            pytest.skip("host cannot create a Windows directory junction")
        try:
            with pytest.raises(StorageError):
                _provider(services).get_player_campaign_state()
        finally:
            if state_dir.is_junction():
                os.rmdir(state_dir)
