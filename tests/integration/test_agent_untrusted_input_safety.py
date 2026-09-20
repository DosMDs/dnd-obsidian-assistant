"""S14-04 untrusted-input / path-safety cross-layer regression.

Proves that model-generated (untrusted) tool arguments travel the full
production path::

    scripted Pydantic AI FunctionModel
      -> compose_ask_runtime (real 12-tool production registry)
      -> PydanticAIToolBridge / DndAgentPolicy / ToolExecutor
      -> real registered production handler
      -> real application/retrieval/storage boundary

and that path-shaped values never grant filesystem authority.

Scope and contract
------------------

- ``EntityId`` is a *logical* identifier: it is deliberately loosely validated
  and may contain ``/``, ``\\``, ``:`` and path-like text.  It has **no**
  filesystem authority because the repository matches it against parsed
  canonical frontmatter after scanning approved entity directories.  The
  correct safety property is therefore **"path-shaped EntityId remains data"**,
  not "reject path-shaped EntityIds".
- ``session_id`` is the only model-facing field that becomes a filesystem path
  component; it is validated by ``storage/session_paths.py`` before any
  filesystem access.
- Content fields (note text, fact text) are persisted as content and never
  interpreted as paths.

Evidence limitation
-------------------

The outside-Vault sentinel proves containment and non-interference (bytes and
directory inventory unchanged, secret marker never returned) — it is **not** a
syscall-level "no read occurred" proof.

No Ollama, no network: the Pydantic AI model is a deterministic local
``FunctionModel``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from dnd_assistant.application.session_runtime import SessionRuntimeService
from dnd_assistant.composition.agent_runtime import compose_ask_runtime
from dnd_assistant.errors import NotFoundError, StorageError
from dnd_assistant.retrieval.index import SqliteFtsIndex
from dnd_assistant.storage.session_events import ObsidianSessionEventRepository
from tests.unit.campaign_state.helpers import (
    BASE_START,
    Services,
    create_entity,
    make_entity,
    make_services,
    setup_entity_dirs,
)
from tests.unit.post_session.helpers import make_audit_context, make_vault

# ── Hostile values ──────────────────────────────────────────────────────────

# Representative POSIX-, Windows-, absolute- and traversal-shaped identifiers.
_HOSTILE_SESSION_IDS: tuple[str, ...] = (
    "../outside/secret.md",
    "..\\outside\\secret.md",
    "/tmp/outside.md",
    "C:\\outside\\secret.md",
)

_HOSTILE_ENTITY_IDS: tuple[str, ...] = (
    "../../outside/secret.md",
    "..\\..\\outside\\secret.md",
    "/tmp/outside.md",
    "C:\\outside\\secret.md",
)

_CONTENT_FACT = "../../outside/secret.md"

_SENTINEL_BYTES = b"OUTSIDE SENTINEL: TOP_SECRET_9f3a\n"
_SENTINEL_MARKER = "TOP_SECRET_9f3a"


# ── Deterministic scripted model (local to this module) ─────────────────────


class _ScriptedModel:
    """Ordered scripted Pydantic AI model; fails loudly on extra requests."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = list(responses)
        self.request_count = 0

    def build(self) -> FunctionModel:
        def _respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            index = self.request_count
            self.request_count += 1
            if index >= len(self._responses):
                raise AssertionError("scripted model received an unexpected extra request")
            return self._responses[index]

        return FunctionModel(_respond)


def _tool_call(tool_name: str, arguments: dict[str, Any]) -> ModelResponse:
    return ModelResponse(
        parts=[ToolCallPart(tool_name=tool_name, args=arguments, tool_call_id="call_1")]
    )


def _respond(message: str) -> ModelResponse:
    content = '{"kind":"respond","message":"' + message + '"}'
    return ModelResponse(parts=[TextPart(content=content)])


# ── Vault / sentinel helpers ────────────────────────────────────────────────


def _make_vault(tmp_path: Path) -> tuple[Path, Services]:
    root = make_vault(tmp_path)
    setup_entity_dirs(root)
    services = make_services(root)
    services.world_time.initialize_current_world_time(
        1000, audit=make_audit_context(operation_id="wt-init", real_time=BASE_START)
    )
    _rebuild_fts(root, services)
    return root, services


def _rebuild_fts(root: Path, services: Services) -> None:
    SqliteFtsIndex(vault_root=str(root)).rebuild(services.vault.list_entities())


def _start_active_session(
    root: Path, services: Services
) -> tuple[str, ObsidianSessionEventRepository]:
    event_repo = ObsidianSessionEventRepository(root, services.audit)
    runtime = SessionRuntimeService(services.metadata, services.world_time, event_repo)
    session = runtime.start_session(
        audit=make_audit_context(operation_id="sess-start", real_time=BASE_START)
    )
    return session.id, event_repo


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[profiles.test-agent]\nprovider='ollama'\nmodel='test'\n"
        "base_url='http://localhost:11434'\nrole='agent'\n",
        encoding="utf-8",
    )
    return config_path


def _compose(
    *,
    root: Path,
    config_path: Path,
    scripted: _ScriptedModel,
    allow_write: bool,
) -> Any:
    return compose_ask_runtime(
        vault_root=root,
        config_path=config_path,
        profile_name="test-agent",
        allow_write=allow_write,
        model_factory=lambda profile: scripted.build(),
    )


class _Sentinel:
    def __init__(self, base: Path) -> None:
        self.base = base
        base.mkdir()
        self.secret = base / "secret.md"
        self.secret.write_bytes(_SENTINEL_BYTES)
        self.digest = hashlib.sha256(_SENTINEL_BYTES).hexdigest()
        self.inventory = sorted(p.name for p in base.iterdir())

    def assert_untouched(self, forbidden_text: str) -> None:
        assert hashlib.sha256(self.secret.read_bytes()).hexdigest() == self.digest
        assert sorted(p.name for p in self.base.iterdir()) == self.inventory
        assert _SENTINEL_MARKER not in forbidden_text


def _canonical_entity_files(root: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for relative in ("Characters", "Locations", "Quests", "Items"):
        base = root / relative
        if base.exists():
            for path in base.rglob("*.md"):
                result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def _audit_bytes(root: Path) -> bytes:
    return (root / "_system" / "audit" / "audit.jsonl").read_bytes()


# ── A. session_id path-shaped values (get_session / list_session_events) ────


@pytest.mark.parametrize("tool_name", ["get_session", "list_session_events"])
@pytest.mark.parametrize("hostile_id", _HOSTILE_SESSION_IDS)
def test_session_read_path_shaped_id_rejected_by_real_storage(
    tmp_path: Path, tool_name: str, hostile_id: str
) -> None:
    """Model-generated session_id reaches the real validator, not the filesystem."""
    root, _services = _make_vault(tmp_path)
    sentinel = _Sentinel(tmp_path / "outside")
    config_path = _write_config(tmp_path)
    scripted = _ScriptedModel([_tool_call(tool_name, {"session_id": hostile_id})])

    runtime = _compose(root=root, config_path=config_path, scripted=scripted, allow_write=False)
    try:
        with pytest.raises(StorageError) as exc_info:
            runtime.agent_runtime.run(
                "Прочитай сессию",
                execution_context=runtime.execution_context,
            )
    finally:
        runtime.close()

    # Literal model request count: one tool-call response, no terminal replay.
    assert scripted.request_count == 1

    # The error originates at the real storage session-path validator.
    assert "Session ID must not" in str(exc_info.value)
    assert str(root) not in str(exc_info.value)

    sentinel.assert_untouched(str(exc_info.value))


# ── B. get_entity path-shaped EntityId remains logical data ─────────────────


@pytest.mark.parametrize("hostile_id", _HOSTILE_ENTITY_IDS)
def test_entity_read_path_shaped_id_is_data_not_authority(tmp_path: Path, hostile_id: str) -> None:
    """A path-shaped EntityId is compared as data and grants no filesystem authority."""
    root, _services = _make_vault(tmp_path)
    sentinel = _Sentinel(tmp_path / "outside")
    config_path = _write_config(tmp_path)
    scripted = _ScriptedModel([_tool_call("get_entity", {"entity_id": hostile_id})])

    runtime = _compose(root=root, config_path=config_path, scripted=scripted, allow_write=False)
    try:
        with pytest.raises(NotFoundError) as exc_info:
            runtime.agent_runtime.run(
                "Найди сущность",
                execution_context=runtime.execution_context,
            )
    finally:
        runtime.close()

    assert scripted.request_count == 1
    assert str(exc_info.value) == "Entity not found or not accessible"
    assert _SENTINEL_MARKER not in str(exc_info.value)

    sentinel.assert_untouched(str(exc_info.value))


# ── C. patch_entity path-shaped target: handler invoked, no mutation ────────


def test_patch_entity_path_shaped_target_authorizes_zero_mutation(tmp_path: Path) -> None:
    """Real WRITE handler runs, authorization fails, canonical mutation is zero."""
    root, _services = _make_vault(tmp_path)
    sentinel = _Sentinel(tmp_path / "outside")
    config_path = _write_config(tmp_path)
    scripted = _ScriptedModel(
        [
            _tool_call(
                "patch_entity",
                {
                    "entity_id": "../../outside/secret.md",
                    "expected_revision": 1,
                    "patch": {"name": "Hostile"},
                },
            )
        ]
    )

    canonical_before = _canonical_entity_files(root)
    audit_before = _audit_bytes(root)

    runtime = _compose(root=root, config_path=config_path, scripted=scripted, allow_write=True)
    try:
        with pytest.raises(NotFoundError) as exc_info:
            runtime.agent_runtime.run(
                "Измени сущность",
                execution_context=runtime.execution_context,
            )
    finally:
        runtime.close()

    # model-generated WRITE tool call attempted; real handler invoked
    # (generic authorization message); canonical repository mutation did not occur.
    assert scripted.request_count == 1
    assert str(exc_info.value) == "Entity not found or not accessible"
    assert _canonical_entity_files(root) == canonical_before
    assert _audit_bytes(root) == audit_before

    sentinel.assert_untouched(str(exc_info.value))


# ── D. record_note path-shaped content remains content ──────────────────────


def test_record_note_path_shaped_content_persisted_as_content(tmp_path: Path) -> None:
    """Path-shaped note text is persisted verbatim as session content."""
    root, services = _make_vault(tmp_path)
    session_id, event_repo = _start_active_session(root, services)
    sentinel = _Sentinel(tmp_path / "outside")
    config_path = _write_config(tmp_path)
    scripted = _ScriptedModel(
        [
            _tool_call("record_note", {"text": _CONTENT_FACT}),
            _respond("Заметка сохранена."),
        ]
    )

    canonical_before = _canonical_entity_files(root)

    runtime = _compose(root=root, config_path=config_path, scripted=scripted, allow_write=True)
    try:
        result = runtime.agent_runtime.run(
            "Запиши заметку",
            execution_context=runtime.execution_context,
        )
    finally:
        runtime.close()

    assert scripted.request_count == 2

    events = event_repo.list_events(session_id)
    notes = [event for event in events if event.type == "note"]
    assert notes
    assert notes[-1].extra_fields.get("text") == _CONTENT_FACT

    assert _canonical_entity_files(root) == canonical_before

    final_text = result.final_response.message.content or ""
    sentinel.assert_untouched(str(final_text))


# ── E. append_entity_fact path-shaped content into the canonical body ───────


def test_append_entity_fact_path_shaped_content_is_canonical_content(tmp_path: Path) -> None:
    """Path-shaped fact is canonical Markdown content; only the target changes."""
    root, services = _make_vault(tmp_path)
    create_entity(services, make_entity("npc-target", name="Target"))
    create_entity(services, make_entity("npc-other", name="Other"))
    _rebuild_fts(root, services)
    sentinel = _Sentinel(tmp_path / "outside")
    config_path = _write_config(tmp_path)
    scripted = _ScriptedModel(
        [
            _tool_call(
                "append_entity_fact",
                {
                    "entity_id": "npc-target",
                    "expected_revision": 1,
                    "fact": _CONTENT_FACT,
                },
            ),
            _respond("Факт добавлен."),
        ]
    )

    canonical_before = _canonical_entity_files(root)

    runtime = _compose(root=root, config_path=config_path, scripted=scripted, allow_write=True)
    try:
        result = runtime.agent_runtime.run(
            "Добавь факт",
            execution_context=runtime.execution_context,
        )
    finally:
        runtime.close()

    assert scripted.request_count == 2

    target = services.vault.get_entity("npc-target")
    other = services.vault.get_entity("npc-other")
    assert target.entity.id == "npc-target"
    assert target.entity.revision == 2
    assert _CONTENT_FACT in target.body
    assert other.entity.revision == 1

    canonical_after = _canonical_entity_files(root)
    assert set(canonical_after) == set(canonical_before)
    # Exactly one canonical file changed (the authorised target); all others are byte-identical.
    changed = {
        path for path in canonical_after if canonical_before.get(path) != canonical_after[path]
    }
    assert len(changed) == 1
    for path, data in canonical_after.items():
        if path not in changed:
            assert data == canonical_before[path]

    final_text = result.final_response.message.content or ""
    sentinel.assert_untouched(str(final_text))
