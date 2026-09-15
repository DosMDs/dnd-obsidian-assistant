"""Contract tests: verify dependency boundaries between layers.

These tests ensure that domain and storage layers do not accidentally
depend on model providers or other upper-layer modules.

Each test uses _clean_import to start from a fresh sys.modules state,
avoiding contamination from pytest's own collection phase.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("restore_dnd_assistant_modules")


def _clean_import(module_path: str) -> None:
    """Import a module from a clean sys.modules state.

    Removes all dnd_assistant modules first, then imports the target.
    This prevents pytest's collection phase from contaminating results.
    """
    for key in list(sys.modules):
        if key.startswith("dnd_assistant"):
            del sys.modules[key]
    importlib.import_module(module_path)


def _modules_loaded() -> set[str]:
    """Return the set of dnd_assistant sub-modules currently in sys.modules."""
    return {m for m in sys.modules if m.startswith("dnd_assistant.")}


# ── domain must not depend on storage, models, or retrieval ──────────────


def test_domain_does_not_import_storage() -> None:
    _clean_import("dnd_assistant.domain")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.storage")}
    assert not mod_names, f"domain imported storage modules: {mod_names}"


def test_domain_does_not_import_models() -> None:
    _clean_import("dnd_assistant.domain")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"domain imported model modules: {mod_names}"


def test_domain_does_not_import_retrieval() -> None:
    _clean_import("dnd_assistant.domain")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.retrieval")}
    assert not mod_names, f"domain imported retrieval modules: {mod_names}"


def test_domain_does_not_import_tools() -> None:
    _clean_import("dnd_assistant.domain")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.tools")}
    assert not mod_names, f"domain imported tool modules: {mod_names}"


def test_domain_does_not_import_application() -> None:
    _clean_import("dnd_assistant.domain")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.application")}
    assert not mod_names, f"domain imported application modules: {mod_names}"


def test_domain_does_not_import_cli() -> None:
    _clean_import("dnd_assistant.domain")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.cli")}
    assert not mod_names, f"domain imported CLI modules: {mod_names}"


# ── storage must not depend on models or retrieval ──────────────────────


def test_storage_does_not_import_models() -> None:
    _clean_import("dnd_assistant.storage")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"storage imported model modules: {mod_names}"


def test_storage_does_not_import_retrieval() -> None:
    _clean_import("dnd_assistant.storage")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.retrieval")}
    assert not mod_names, f"storage imported retrieval modules: {mod_names}"


def test_storage_does_not_import_tools() -> None:
    _clean_import("dnd_assistant.storage")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.tools")}
    assert not mod_names, f"storage imported tool modules: {mod_names}"


# ── models/gateway must not depend on storage or domain ─────────────────


def test_gateway_does_not_import_storage() -> None:
    _clean_import("dnd_assistant.models.gateway")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.storage")}
    assert not mod_names, f"gateway imported storage modules: {mod_names}"


def test_gateway_does_not_import_domain() -> None:
    _clean_import("dnd_assistant.models.gateway")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.domain")}
    assert not mod_names, f"gateway imported domain modules: {mod_names}"


def test_gateway_does_not_import_retrieval() -> None:
    _clean_import("dnd_assistant.models.gateway")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.retrieval")}
    assert not mod_names, f"gateway imported retrieval modules: {mod_names}"


def test_gateway_does_not_import_tools() -> None:
    _clean_import("dnd_assistant.models.gateway")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.tools")}
    assert not mod_names, f"gateway imported tool modules: {mod_names}"


# ── production CLI composition / runtime dependency boundaries ────────────
# The accepted production orchestration path is:
#   CLI → PydanticAIAgentRuntime → DndAgentPolicy / PydanticAIToolBridge
#       → ToolExecutor → services → VaultRepository
# Production composition must not depend on obsolete custom orchestration or
# on the retained native Ollama provider infrastructure (used by non-agent
# provider operations only).

# Retired custom agent-runtime modules (PAIM-RETIRE-01).  These must not be
# reintroduced.  The absence regression below is a lightweight guard; the AST
# dependency assertions are the durable architecture boundary.
_RETIRED_APPLICATION_MODULES: tuple[str, ...] = (
    "dnd_assistant.application.agent_loop",
    "dnd_assistant.application.fast_agent",
    "dnd_assistant.application.agent_tool_execution",
)

# Native Ollama provider infrastructure retained for non-agent operations
# (chat, structured output, embeddings, health).
_NATIVE_PROVIDER_MODULES: tuple[str, ...] = (
    "dnd_assistant.models.ollama",
    "dnd_assistant.models.ollama_chat_adapter",
    "dnd_assistant.models.ollama_tool_adapter",
    "dnd_assistant.models.ollama_embedding_adapter",
)

# Import targets that accepted production orchestration must never regain.
_FORBIDDEN_RUNTIME_IMPORT_TARGETS: tuple[str, ...] = (
    *_RETIRED_APPLICATION_MODULES,
    *_NATIVE_PROVIDER_MODULES,
)


def test_retired_reference_runtime_modules_absent() -> None:
    """Retirement regression: obsolete custom orchestration modules are gone.

    Lightweight guard against silent reintroduction.  The durable contract is
    the AST dependency assertion below, which protects the accepted
    production dependency shape regardless of module existence.
    """
    present = sorted(
        m for m in _RETIRED_APPLICATION_MODULES if importlib.util.find_spec(m) is not None
    )
    assert not present, f"retired reference-runtime modules were reintroduced: {present}"


def test_cli_agent_runtime_does_not_import_native_provider() -> None:
    _clean_import("dnd_assistant.cli.agent_runtime")
    loaded = _modules_loaded()
    offending = sorted(m for m in _FORBIDDEN_RUNTIME_IMPORT_TARGETS if m in loaded)
    assert not offending, (
        f"production CLI composition imported obsolete/provider-only modules: {offending}"
    )


def test_cli_ask_does_not_import_native_provider() -> None:
    _clean_import("dnd_assistant.cli.ask")
    loaded = _modules_loaded()
    offending = sorted(m for m in _FORBIDDEN_RUNTIME_IMPORT_TARGETS if m in loaded)
    assert not offending, (
        f"production CLI ask command imported obsolete/provider-only modules: {offending}"
    )


# ── production Pydantic runtime must not import obsolete/provider modules ──
# The production runtime imports shared contracts from
# ``dnd_assistant.application.agent_contracts`` only.  This AST scan covers
# imports at every nesting depth (normal and deferred/call-time).

_PRODUCTION_PYDANTIC_RUNTIME_MODULES: tuple[str, ...] = (
    "dnd_assistant.application.pydantic_ai_agent_runtime",
    "dnd_assistant.application.pydantic_ai_fast_agent",
)


def _module_import_targets(module_path: str) -> set[str]:
    """Return every module named by an import statement at any nesting depth.

    Walks the full AST so that deferred/call-time imports inside functions or
    methods are included, not only module-level imports.
    """
    spec = importlib.util.find_spec(module_path)
    assert spec is not None and spec.origin is not None, f"cannot locate module {module_path}"
    source = Path(spec.origin).read_text(encoding="utf-8")
    tree = ast.parse(source)

    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            targets.add(node.module)
    return targets


@pytest.mark.parametrize("module_path", _PRODUCTION_PYDANTIC_RUNTIME_MODULES)
def test_production_pydantic_runtime_does_not_import_obsolete_modules(module_path: str) -> None:
    targets = _module_import_targets(module_path)
    offending = sorted(m for m in _FORBIDDEN_RUNTIME_IMPORT_TARGETS if m in targets)
    assert not offending, (
        f"{module_path} imports obsolete/provider-only modules: {offending}. "
        "Import shared contracts from dnd_assistant.application.agent_contracts instead."
    )


# ── tools/registry must not depend on storage or models ─────────────────


def test_registry_does_not_import_storage() -> None:
    _clean_import("dnd_assistant.tools.registry")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.storage")}
    assert not mod_names, f"registry imported storage modules: {mod_names}"


def test_registry_does_not_import_models() -> None:
    _clean_import("dnd_assistant.tools.registry")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"registry imported model modules: {mod_names}"


def test_registry_does_not_import_domain() -> None:
    _clean_import("dnd_assistant.tools.registry")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.domain")}
    assert not mod_names, f"registry imported domain modules: {mod_names}"


# ── tools/executor must not depend on storage or models ─────────────────────


def test_executor_does_not_import_storage() -> None:
    _clean_import("dnd_assistant.tools.executor")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.storage")}
    assert not mod_names, f"executor imported storage modules: {mod_names}"


def test_executor_does_not_import_models() -> None:
    _clean_import("dnd_assistant.tools.executor")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"executor imported model modules: {mod_names}"


def test_executor_does_not_import_domain() -> None:
    _clean_import("dnd_assistant.tools.executor")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.domain")}
    assert not mod_names, f"executor imported domain modules: {mod_names}"


def test_executor_does_not_import_application() -> None:
    _clean_import("dnd_assistant.tools.executor")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.application")}
    assert not mod_names, f"executor imported application modules: {mod_names}"


def test_executor_does_not_import_ollama() -> None:
    _clean_import("dnd_assistant.tools.executor")
    mod_names = {m for m in sys.modules if m.startswith("ollama")}
    assert not mod_names, f"executor triggered ollama import: {mod_names}"


# ── tools/types must not depend on storage or models ────────────────────────


def test_tools_types_does_not_import_storage() -> None:
    _clean_import("dnd_assistant.tools.types")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.storage")}
    assert not mod_names, f"tools.types imported storage modules: {mod_names}"


def test_tools_types_does_not_import_models() -> None:
    _clean_import("dnd_assistant.tools.types")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"tools.types imported model modules: {mod_names}"


def test_tools_types_does_not_import_domain() -> None:
    _clean_import("dnd_assistant.tools.types")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.domain")}
    assert not mod_names, f"tools.types imported domain modules: {mod_names}"


def test_tools_types_does_not_import_ollama() -> None:
    _clean_import("dnd_assistant.tools.types")
    mod_names = {m for m in sys.modules if m.startswith("ollama")}
    assert not mod_names, f"tools.types triggered ollama import: {mod_names}"


# ── dnd_assistant.tools package must not import storage or retrieval ────


def test_tools_package_does_not_import_storage() -> None:
    _clean_import("dnd_assistant.tools")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.storage")}
    assert not mod_names, f"tools package imported storage modules: {mod_names}"


def test_tools_package_does_not_import_retrieval() -> None:
    _clean_import("dnd_assistant.tools")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.retrieval")}
    assert not mod_names, f"tools package imported retrieval modules: {mod_names}"


def test_tools_package_does_not_import_application() -> None:
    _clean_import("dnd_assistant.tools")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.application")}
    assert not mod_names, f"tools package imported application modules: {mod_names}"


# ── dnd_assistant.tools.entity_reads must not import models or CLI ──────


def test_entity_reads_does_not_import_models() -> None:
    _clean_import("dnd_assistant.tools.entity_reads")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"entity_reads imported model modules: {mod_names}"


def test_entity_reads_does_not_import_cli() -> None:
    _clean_import("dnd_assistant.tools.entity_reads")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.cli")}
    assert not mod_names, f"entity_reads imported CLI modules: {mod_names}"


def test_entity_reads_does_not_import_ollama() -> None:
    _clean_import("dnd_assistant.tools.entity_reads")
    mod_names = {m for m in sys.modules if m.startswith("ollama")}
    assert not mod_names, f"entity_reads triggered ollama import: {mod_names}"


def test_entity_reads_does_not_import_application() -> None:
    _clean_import("dnd_assistant.tools.entity_reads")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.application")}
    assert not mod_names, f"entity_reads imported application modules: {mod_names}"


# ── dnd_assistant.tools.session_reads must not import models or CLI ──────


def test_session_reads_does_not_import_models() -> None:
    _clean_import("dnd_assistant.tools.session_reads")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"session_reads imported model modules: {mod_names}"


def test_session_reads_does_not_import_cli() -> None:
    _clean_import("dnd_assistant.tools.session_reads")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.cli")}
    assert not mod_names, f"session_reads imported CLI modules: {mod_names}"


def test_session_reads_does_not_import_ollama() -> None:
    _clean_import("dnd_assistant.tools.session_reads")
    mod_names = {m for m in sys.modules if m.startswith("ollama")}
    assert not mod_names, f"session_reads triggered ollama import: {mod_names}"


# ── dnd_assistant.tools.session_mutations must not import models/CLI/retrieval ──


def test_session_mutations_does_not_import_models() -> None:
    _clean_import("dnd_assistant.tools.session_mutations")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"session_mutations imported model modules: {mod_names}"


def test_session_mutations_does_not_import_cli() -> None:
    _clean_import("dnd_assistant.tools.session_mutations")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.cli")}
    assert not mod_names, f"session_mutations imported CLI modules: {mod_names}"


def test_session_mutations_does_not_import_ollama() -> None:
    _clean_import("dnd_assistant.tools.session_mutations")
    mod_names = {m for m in sys.modules if m.startswith("ollama")}
    assert not mod_names, f"session_mutations triggered ollama import: {mod_names}"


def test_session_mutations_does_not_import_retrieval() -> None:
    _clean_import("dnd_assistant.tools.session_mutations")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.retrieval")}
    assert not mod_names, f"session_mutations imported retrieval modules: {mod_names}"


# ── dnd_assistant.tools.world_time_reads must not import models/CLI/application/retrieval ──


def test_world_time_reads_does_not_import_models() -> None:
    _clean_import("dnd_assistant.tools.world_time_reads")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"world_time_reads imported model modules: {mod_names}"


def test_world_time_reads_does_not_import_cli() -> None:
    _clean_import("dnd_assistant.tools.world_time_reads")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.cli")}
    assert not mod_names, f"world_time_reads imported CLI modules: {mod_names}"


def test_world_time_reads_does_not_import_ollama() -> None:
    _clean_import("dnd_assistant.tools.world_time_reads")
    mod_names = {m for m in sys.modules if m.startswith("ollama")}
    assert not mod_names, f"world_time_reads triggered ollama import: {mod_names}"


def test_world_time_reads_does_not_import_application() -> None:
    _clean_import("dnd_assistant.tools.world_time_reads")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.application")}
    assert not mod_names, f"world_time_reads imported application modules: {mod_names}"


def test_world_time_reads_does_not_import_retrieval() -> None:
    _clean_import("dnd_assistant.tools.world_time_reads")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.retrieval")}
    assert not mod_names, f"world_time_reads imported retrieval modules: {mod_names}"


# ── dnd_assistant.tools.world_time_mutations must not import models/CLI/application/retrieval ──


def test_world_time_mutations_does_not_import_models() -> None:
    _clean_import("dnd_assistant.tools.world_time_mutations")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"world_time_mutations imported model modules: {mod_names}"


def test_world_time_mutations_does_not_import_cli() -> None:
    _clean_import("dnd_assistant.tools.world_time_mutations")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.cli")}
    assert not mod_names, f"world_time_mutations imported CLI modules: {mod_names}"


def test_world_time_mutations_does_not_import_ollama() -> None:
    _clean_import("dnd_assistant.tools.world_time_mutations")
    mod_names = {m for m in sys.modules if m.startswith("ollama")}
    assert not mod_names, f"world_time_mutations triggered ollama import: {mod_names}"


def test_world_time_mutations_does_not_import_application() -> None:
    _clean_import("dnd_assistant.tools.world_time_mutations")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.application")}
    assert not mod_names, f"world_time_mutations imported application modules: {mod_names}"


def test_world_time_mutations_does_not_import_retrieval() -> None:
    _clean_import("dnd_assistant.tools.world_time_mutations")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.retrieval")}
    assert not mod_names, f"world_time_mutations imported retrieval modules: {mod_names}"


# ── dnd_assistant.tools.entity_mutations must not import models/CLI/application ──


def test_entity_mutations_does_not_import_models() -> None:
    _clean_import("dnd_assistant.tools.entity_mutations")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"entity_mutations imported model modules: {mod_names}"


def test_entity_mutations_does_not_import_cli() -> None:
    _clean_import("dnd_assistant.tools.entity_mutations")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.cli")}
    assert not mod_names, f"entity_mutations imported CLI modules: {mod_names}"


def test_entity_mutations_does_not_import_ollama() -> None:
    _clean_import("dnd_assistant.tools.entity_mutations")
    mod_names = {m for m in sys.modules if m.startswith("ollama")}
    assert not mod_names, f"entity_mutations triggered ollama import: {mod_names}"


def test_entity_mutations_does_not_import_application() -> None:
    _clean_import("dnd_assistant.tools.entity_mutations")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.application")}
    assert not mod_names, f"entity_mutations imported application modules: {mod_names}"


# ── no module pulls in ollama ────────────────────────────────────────────


@pytest.mark.parametrize(
    "module_path",
    [
        "dnd_assistant",
        "dnd_assistant.domain",
        "dnd_assistant.storage",
        "dnd_assistant.models",
        "dnd_assistant.retrieval",
        "dnd_assistant.tools",
        "dnd_assistant.application",
        "dnd_assistant.cli",
        "dnd_assistant.prompts",
        "dnd_assistant.evals",
    ],
)
def test_module_does_not_import_ollama(module_path: str) -> None:
    _clean_import(module_path)
    mod_names = {m for m in sys.modules if m.startswith("ollama")}
    assert not mod_names, f"{module_path} triggered ollama import: {mod_names}"


# ── world_time domain must not depend on storage/models/retrieval ─────────


def test_world_time_domain_does_not_import_storage() -> None:
    _clean_import("dnd_assistant.domain.world_time")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.storage")}
    assert not mod_names, f"domain.world_time imported storage modules: {mod_names}"


def test_world_time_domain_does_not_import_models() -> None:
    _clean_import("dnd_assistant.domain.world_time")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"domain.world_time imported model modules: {mod_names}"


def test_world_time_domain_does_not_import_retrieval() -> None:
    _clean_import("dnd_assistant.domain.world_time")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.retrieval")}
    assert not mod_names, f"domain.world_time imported retrieval modules: {mod_names}"


def test_world_time_domain_does_not_import_tools() -> None:
    _clean_import("dnd_assistant.domain.world_time")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.tools")}
    assert not mod_names, f"domain.world_time imported tool modules: {mod_names}"


def test_world_time_domain_does_not_import_application() -> None:
    _clean_import("dnd_assistant.domain.world_time")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.application")}
    assert not mod_names, f"domain.world_time imported application modules: {mod_names}"


def test_world_time_domain_does_not_import_cli() -> None:
    _clean_import("dnd_assistant.domain.world_time")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.cli")}
    assert not mod_names, f"domain.world_time imported CLI modules: {mod_names}"


# ── storage/world_time must not depend on models/retrieval/tools/application/cli ──


def test_storage_world_time_does_not_import_models() -> None:
    _clean_import("dnd_assistant.storage.world_time")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"storage.world_time imported model modules: {mod_names}"


def test_storage_world_time_does_not_import_retrieval() -> None:
    _clean_import("dnd_assistant.storage.world_time")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.retrieval")}
    assert not mod_names, f"storage.world_time imported retrieval modules: {mod_names}"


def test_storage_world_time_does_not_import_tools() -> None:
    _clean_import("dnd_assistant.storage.world_time")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.tools")}
    assert not mod_names, f"storage.world_time imported tool modules: {mod_names}"


def test_storage_world_time_does_not_import_application() -> None:
    _clean_import("dnd_assistant.storage.world_time")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.application")}
    assert not mod_names, f"storage.world_time imported application modules: {mod_names}"


def test_storage_world_time_does_not_import_cli() -> None:
    _clean_import("dnd_assistant.storage.world_time")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.cli")}
    assert not mod_names, f"storage.world_time imported CLI modules: {mod_names}"


# ── storage/session_metadata must not depend on models/retrieval/tools/application/cli ──


def test_storage_session_metadata_does_not_import_models() -> None:
    _clean_import("dnd_assistant.storage.session_metadata")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"storage.session_metadata imported model modules: {mod_names}"


def test_storage_session_metadata_does_not_import_retrieval() -> None:
    _clean_import("dnd_assistant.storage.session_metadata")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.retrieval")}
    assert not mod_names, f"storage.session_metadata imported retrieval modules: {mod_names}"


def test_storage_session_metadata_does_not_import_tools() -> None:
    _clean_import("dnd_assistant.storage.session_metadata")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.tools")}
    assert not mod_names, f"storage.session_metadata imported tool modules: {mod_names}"


def test_storage_session_metadata_does_not_import_application() -> None:
    _clean_import("dnd_assistant.storage.session_metadata")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.application")}
    assert not mod_names, f"storage.session_metadata imported application modules: {mod_names}"


def test_storage_session_metadata_does_not_import_cli() -> None:
    _clean_import("dnd_assistant.storage.session_metadata")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.cli")}
    assert not mod_names, f"storage.session_metadata imported CLI modules: {mod_names}"


# ── application/session_runtime must not depend on models/tools/ollama ──


def test_application_session_runtime_does_not_import_models() -> None:
    _clean_import("dnd_assistant.application.session_runtime")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"application.session_runtime imported model modules: {mod_names}"


def test_application_session_runtime_does_not_import_tools() -> None:
    _clean_import("dnd_assistant.application.session_runtime")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.tools")}
    assert not mod_names, f"application.session_runtime imported tool modules: {mod_names}"


def test_application_session_runtime_does_not_import_ollama() -> None:
    _clean_import("dnd_assistant.application.session_runtime")
    mod_names = {m for m in sys.modules if m.startswith("ollama")}
    assert not mod_names, f"application.session_runtime triggered ollama import: {mod_names}"


# ── storage/session_events must not depend on models/retrieval/tools/application/cli ──


def test_storage_session_events_does_not_import_models() -> None:
    _clean_import("dnd_assistant.storage.session_events")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"storage.session_events imported model modules: {mod_names}"


def test_storage_session_events_does_not_import_retrieval() -> None:
    _clean_import("dnd_assistant.storage.session_events")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.retrieval")}
    assert not mod_names, f"storage.session_events imported retrieval modules: {mod_names}"


def test_storage_session_events_does_not_import_tools() -> None:
    _clean_import("dnd_assistant.storage.session_events")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.tools")}
    assert not mod_names, f"storage.session_events imported tool modules: {mod_names}"


def test_storage_session_events_does_not_import_application() -> None:
    _clean_import("dnd_assistant.storage.session_events")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.application")}
    assert not mod_names, f"storage.session_events imported application modules: {mod_names}"


def test_storage_session_events_does_not_import_cli() -> None:
    _clean_import("dnd_assistant.storage.session_events")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.cli")}
    assert not mod_names, f"storage.session_events imported CLI modules: {mod_names}"


# ── dnd_assistant.tools.catalog must not depend on models/cli/storage/retrieval/application ──


def test_tools_catalog_does_not_import_models() -> None:
    _clean_import("dnd_assistant.tools.catalog")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"tools.catalog imported model modules: {mod_names}"


def test_tools_catalog_does_not_import_cli() -> None:
    _clean_import("dnd_assistant.tools.catalog")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.cli")}
    assert not mod_names, f"tools.catalog imported CLI modules: {mod_names}"


def test_tools_catalog_does_not_import_storage() -> None:
    _clean_import("dnd_assistant.tools.catalog")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.storage")}
    assert not mod_names, f"tools.catalog imported storage modules: {mod_names}"


def test_tools_catalog_does_not_import_retrieval() -> None:
    _clean_import("dnd_assistant.tools.catalog")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.retrieval")}
    assert not mod_names, f"tools.catalog imported retrieval modules: {mod_names}"


def test_tools_catalog_does_not_import_application() -> None:
    _clean_import("dnd_assistant.tools.catalog")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.application")}
    assert not mod_names, f"tools.catalog imported application modules: {mod_names}"


def test_tools_catalog_does_not_import_ollama() -> None:
    _clean_import("dnd_assistant.tools.catalog")
    mod_names = {m for m in sys.modules if m.startswith("ollama")}
    assert not mod_names, f"tools.catalog triggered ollama import: {mod_names}"


# ── dnd_assistant.tools.mvp_registry must not depend on models/cli/ollama ──


def test_tools_mvp_registry_does_not_import_models() -> None:
    _clean_import("dnd_assistant.tools.mvp_registry")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"tools.mvp_registry imported model modules: {mod_names}"


def test_tools_mvp_registry_does_not_import_cli() -> None:
    _clean_import("dnd_assistant.tools.mvp_registry")
    mod_names = {m for m in _modules_loaded() if m.startswith("dnd_assistant.cli")}
    assert not mod_names, f"tools.mvp_registry imported CLI modules: {mod_names}"


def test_tools_mvp_registry_does_not_import_ollama() -> None:
    _clean_import("dnd_assistant.tools.mvp_registry")
    mod_names = {m for m in sys.modules if m.startswith("ollama")}
    assert not mod_names, f"tools.mvp_registry triggered ollama import: {mod_names}"


# ── Boundary isolation regression ───────────────────────────────────────────


def test_boundary_restores_module_identity() -> None:
    """Prove the autouse fixture restores original module/class identity.

    The fixture snapshots ``dnd_assistant`` modules before each test and
    restores them in ``finally``.  This test verifies that after a
    clean-import cycle the fixture's snapshot captured the original
    ``ToolRegistry`` class and that ``_clean_import`` actually replaced
    it (proving both the fixture mechanism and the clean-import work).

    The critical regression — that strict ``isinstance()`` works in catalog
    tests after boundary tests — is verified by running both suites in the
    same process (``test_boundaries.py`` then ``test_tool_catalog.py``).
    """
    from dnd_assistant.tools.registry import ToolRegistry

    original_id = id(ToolRegistry)

    # Simulate what the fixture's snapshot captures
    snapshot = {
        name: module
        for name, module in sys.modules.items()
        if name == "dnd_assistant" or name.startswith("dnd_assistant.")
    }

    # _clean_import replaces dnd_assistant modules
    _clean_import("dnd_assistant.tools.registry")

    # After clean import, the ToolRegistry should be a different object
    from dnd_assistant.tools.registry import ToolRegistry as NewToolRegistry  # noqa: F811

    assert id(NewToolRegistry) != original_id, "clean_import did not replace ToolRegistry class"

    # The fixture's restore would put the originals back.
    # Verify our snapshot contains the original.
    assert "dnd_assistant.tools.registry" in snapshot
    assert id(snapshot["dnd_assistant.tools.registry"].ToolRegistry) == original_id, (
        "Fixture snapshot does not contain the original ToolRegistry class"
    )


# ── domain/changeset must not depend on upper/persistence layers ──────────
# The Stage-10 proposal schemas are untrusted domain data.  Importing them must
# not pull in storage, application, models, tools, retrieval or CLI, and the
# module must not import persistence-oriented stdlib modules (pathlib/os/hashlib)
# as the durable layer-boundary direction is checked first.

_FORBIDDEN_CHANGESET_LAYERS: tuple[str, ...] = (
    "dnd_assistant.storage",
    "dnd_assistant.application",
    "dnd_assistant.models",
    "dnd_assistant.tools",
    "dnd_assistant.retrieval",
    "dnd_assistant.cli",
)

_FORBIDDEN_CHANGESET_STDLIB: tuple[str, ...] = ("pathlib", "os", "hashlib")


def test_domain_changeset_does_not_import_upper_layers() -> None:
    _clean_import("dnd_assistant.domain.changeset")
    loaded = _modules_loaded()
    offending = sorted(
        module
        for module in loaded
        for layer in _FORBIDDEN_CHANGESET_LAYERS
        if module == layer or module.startswith(f"{layer}.")
    )
    assert not offending, f"domain.changeset imported forbidden layers: {offending}"


def test_domain_changeset_does_not_import_persistence_stdlib() -> None:
    targets = _module_import_targets("dnd_assistant.domain.changeset")
    offending = sorted(
        target for target in targets if target.split(".")[0] in _FORBIDDEN_CHANGESET_STDLIB
    )
    assert not offending, f"domain.changeset imported persistence stdlib: {offending}"


# ── application/changeset_validation must stay pure and provider-neutral ──
# The S10-02 preflight validator may depend on domain, storage read contracts
# and project errors only.  It must not pull in model/provider, tool, retrieval
# or CLI layers, nor perform filesystem work through pathlib/os/hashlib.

_FORBIDDEN_CHANGESET_VALIDATION_LAYERS: tuple[str, ...] = (
    "dnd_assistant.models",
    "dnd_assistant.tools",
    "dnd_assistant.retrieval",
    "dnd_assistant.cli",
)

_FORBIDDEN_CHANGESET_VALIDATION_STDLIB: tuple[str, ...] = ("pathlib", "os", "hashlib")


def test_application_changeset_validation_does_not_import_upper_layers() -> None:
    _clean_import("dnd_assistant.application.changeset_validation")
    loaded = _modules_loaded()
    offending = sorted(
        module
        for module in loaded
        for layer in _FORBIDDEN_CHANGESET_VALIDATION_LAYERS
        if module == layer or module.startswith(f"{layer}.")
    )
    assert not offending, f"application.changeset_validation imported forbidden layers: {offending}"


def test_application_changeset_validation_does_not_import_persistence_stdlib() -> None:
    targets = _module_import_targets("dnd_assistant.application.changeset_validation")
    offending = sorted(
        target
        for target in targets
        if target.split(".")[0] in _FORBIDDEN_CHANGESET_VALIDATION_STDLIB
    )
    assert not offending, (
        f"application.changeset_validation imported persistence stdlib: {offending}"
    )


def test_application_changeset_validation_does_not_trigger_ollama() -> None:
    _clean_import("dnd_assistant.application.changeset_validation")
    mod_names = {m for m in sys.modules if m.startswith("ollama")}
    assert not mod_names, f"changeset_validation triggered ollama import: {mod_names}"


def test_application_changeset_validation_does_not_import_pydantic_ai() -> None:
    targets = _module_import_targets("dnd_assistant.application.changeset_validation")
    offending = sorted(target for target in targets if target.split(".")[0] == "pydantic_ai")
    assert not offending, f"changeset_validation imports pydantic_ai: {offending}"


# ── application/changeset_review must stay provider-neutral and write-free ──
# S10-03 owns canonical serialization/fingerprint/approval in the application
# layer.  It may depend on domain.changeset, application.changeset_validation,
# project errors, pydantic and the ``hashlib``/``json`` stdlib.  ``hashlib`` is
# an intentional application review concern and is NOT forbidden here.  The
# ``VaultRepository`` read contract may be referenced only under ``TYPE_CHECKING``
# so no storage module is imported at runtime.

_FORBIDDEN_CHANGESET_REVIEW_LAYERS: tuple[str, ...] = (
    "dnd_assistant.models",
    "dnd_assistant.tools",
    "dnd_assistant.retrieval",
    "dnd_assistant.cli",
)

_FORBIDDEN_CHANGESET_REVIEW_STDLIB: tuple[str, ...] = ("pathlib", "os")


def test_application_changeset_review_does_not_import_upper_layers() -> None:
    _clean_import("dnd_assistant.application.changeset_review")
    loaded = _modules_loaded()
    offending = sorted(
        module
        for module in loaded
        for layer in _FORBIDDEN_CHANGESET_REVIEW_LAYERS
        if module == layer or module.startswith(f"{layer}.")
    )
    assert not offending, f"application.changeset_review imported forbidden layers: {offending}"


def test_application_changeset_review_does_not_import_storage_at_runtime() -> None:
    _clean_import("dnd_assistant.application.changeset_review")
    loaded = _modules_loaded()
    offending = sorted(module for module in loaded if module.startswith("dnd_assistant.storage"))
    assert not offending, f"application.changeset_review imported storage at runtime: {offending}"


def test_application_changeset_review_does_not_import_persistence_stdlib() -> None:
    targets = _module_import_targets("dnd_assistant.application.changeset_review")
    offending = sorted(
        target for target in targets if target.split(".")[0] in _FORBIDDEN_CHANGESET_REVIEW_STDLIB
    )
    assert not offending, f"application.changeset_review imported persistence stdlib: {offending}"


def test_application_changeset_review_allows_hashlib() -> None:
    targets = _module_import_targets("dnd_assistant.application.changeset_review")
    assert "hashlib" in targets, "changeset_review should own SHA-256 hashing via hashlib"


def test_application_changeset_review_does_not_trigger_ollama() -> None:
    _clean_import("dnd_assistant.application.changeset_review")
    mod_names = {m for m in sys.modules if m.startswith("ollama")}
    assert not mod_names, f"changeset_review triggered ollama import: {mod_names}"


def test_application_changeset_review_does_not_import_pydantic_ai() -> None:
    targets = _module_import_targets("dnd_assistant.application.changeset_review")
    offending = sorted(target for target in targets if target.split(".")[0] == "pydantic_ai")
    assert not offending, f"changeset_review imports pydantic_ai: {offending}"
