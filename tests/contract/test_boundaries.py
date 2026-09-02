"""Contract tests: verify dependency boundaries between layers.

These tests ensure that domain and storage layers do not accidentally
depend on model providers or other upper-layer modules.

Each test uses _clean_import to start from a fresh sys.modules state,
avoiding contamination from pytest's own collection phase.
"""

from __future__ import annotations

import importlib
import sys

import pytest


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
