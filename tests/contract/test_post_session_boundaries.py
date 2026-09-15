"""Contract tests: S11-01 post-session processing layer boundaries.

Guards the accepted dependency direction for the S11-01 foundations:

- ``domain.post_session`` is pure schema data: no storage/application/model/
  tool/retrieval/CLI import and no persistence stdlib;
- ``application.post_session_identity`` / ``_eligibility`` / ``_ledger`` stay
  provider-neutral, import no model/tool/retrieval/CLI layer and reference no
  concrete storage implementation at runtime;
- ``storage.post_session_processing`` depends only on storage/domain/errors and
  is provider-neutral.

Each clean-import test opts into ``restore_dnd_assistant_modules``.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("restore_dnd_assistant_modules")


def _clean_import(module_path: str) -> None:
    import sys

    for key in list(sys.modules):
        if key.startswith("dnd_assistant"):
            del sys.modules[key]
    importlib.import_module(module_path)


def _modules_loaded() -> set[str]:
    import sys

    return {m for m in sys.modules if m.startswith("dnd_assistant.")}


def _module_import_targets(module_path: str) -> set[str]:
    spec = importlib.util.find_spec(module_path)
    assert spec is not None and spec.origin is not None, f"cannot locate module {module_path}"
    tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            targets.add(node.module)
    return targets


def _module_name_nodes(module_path: str) -> set[str]:
    spec = importlib.util.find_spec(module_path)
    assert spec is not None and spec.origin is not None, f"cannot locate module {module_path}"
    tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


_FORBIDDEN_UPPER_LAYERS: tuple[str, ...] = (
    "dnd_assistant.models",
    "dnd_assistant.tools",
    "dnd_assistant.retrieval",
    "dnd_assistant.cli",
)

_PROVIDER_ROOTS = {"ollama", "pydantic_ai"}


def _assert_no_upper_layers(module_path: str) -> None:
    _clean_import(module_path)
    loaded = _modules_loaded()
    offending = sorted(
        m
        for m in loaded
        if any(m == layer or m.startswith(f"{layer}.") for layer in _FORBIDDEN_UPPER_LAYERS)
    )
    assert not offending, f"{module_path} imported forbidden layers: {offending}"


def _assert_provider_neutral(module_path: str) -> None:
    targets = _module_import_targets(module_path)
    roots = {target.split(".")[0] for target in targets}
    offending = sorted(roots & _PROVIDER_ROOTS)
    assert not offending, f"{module_path} imported provider/framework modules: {offending}"
    _clean_import(module_path)
    assert not {m for m in _modules_loaded() if m.split(".")[0] in _PROVIDER_ROOTS}


# ── domain/post_session ────────────────────────────────────────────────────

_DOMAIN_MODULE = "dnd_assistant.domain.post_session"
_FORBIDDEN_DOMAIN_STDLIB = {"pathlib", "os", "hashlib"}


def test_domain_post_session_imports_no_upper_layers() -> None:
    _assert_no_upper_layers(_DOMAIN_MODULE)


def test_domain_post_session_does_not_import_storage_or_application() -> None:
    _clean_import(_DOMAIN_MODULE)
    loaded = _modules_loaded()
    offending = sorted(
        m
        for m in loaded
        if m.startswith("dnd_assistant.storage") or m.startswith("dnd_assistant.application")
    )
    assert not offending, f"domain.post_session imported storage/application: {offending}"


def test_domain_post_session_has_no_persistence_stdlib() -> None:
    targets = _module_import_targets(_DOMAIN_MODULE)
    offending = sorted(
        target for target in targets if target.split(".")[0] in _FORBIDDEN_DOMAIN_STDLIB
    )
    assert not offending, f"domain.post_session imported persistence stdlib: {offending}"


def test_domain_post_session_is_provider_neutral() -> None:
    _assert_provider_neutral(_DOMAIN_MODULE)


# ── application identity ───────────────────────────────────────────────────

_IDENTITY_MODULE = "dnd_assistant.application.post_session_identity"


def test_application_identity_imports_no_upper_layers() -> None:
    _assert_no_upper_layers(_IDENTITY_MODULE)


def test_application_identity_does_not_import_storage_at_runtime() -> None:
    _clean_import(_IDENTITY_MODULE)
    offending = sorted(m for m in _modules_loaded() if m.startswith("dnd_assistant.storage"))
    assert not offending, f"application.post_session_identity imported storage: {offending}"


def test_application_identity_is_provider_neutral() -> None:
    _assert_provider_neutral(_IDENTITY_MODULE)


# ── application eligibility ────────────────────────────────────────────────

_ELIGIBILITY_MODULE = "dnd_assistant.application.post_session_eligibility"


def test_application_eligibility_imports_no_upper_layers() -> None:
    _assert_no_upper_layers(_ELIGIBILITY_MODULE)


def test_application_eligibility_does_not_import_storage_at_runtime() -> None:
    _clean_import(_ELIGIBILITY_MODULE)
    offending = sorted(m for m in _modules_loaded() if m.startswith("dnd_assistant.storage"))
    assert not offending, f"application.post_session_eligibility imported storage: {offending}"


def test_application_eligibility_names_no_concrete_storage_class() -> None:
    names = _module_name_nodes(_ELIGIBILITY_MODULE)
    assert "ObsidianSessionMetadataRepository" not in names
    assert "ObsidianSessionEventRepository" not in names
    assert "ObsidianPostSessionProcessingStore" not in names


def test_application_eligibility_is_provider_neutral() -> None:
    _assert_provider_neutral(_ELIGIBILITY_MODULE)


# ── application ledger ─────────────────────────────────────────────────────

_LEDGER_MODULE = "dnd_assistant.application.post_session_ledger"


def test_application_ledger_imports_no_upper_layers() -> None:
    _assert_no_upper_layers(_LEDGER_MODULE)


def test_application_ledger_does_not_import_storage_at_runtime() -> None:
    _clean_import(_LEDGER_MODULE)
    offending = sorted(m for m in _modules_loaded() if m.startswith("dnd_assistant.storage"))
    assert not offending, f"application.post_session_ledger imported storage: {offending}"


def test_application_ledger_names_no_concrete_storage_class() -> None:
    names = _module_name_nodes(_LEDGER_MODULE)
    assert "ObsidianPostSessionProcessingStore" not in names


def test_application_ledger_is_provider_neutral() -> None:
    _assert_provider_neutral(_LEDGER_MODULE)


# ── application context (S11-02) ───────────────────────────────────────────

_CONTEXT_MODULE = "dnd_assistant.application.post_session_context"

_WRITE_CAPABLE_METHOD_NAMES = {
    "create_entity",
    "patch_entity",
    "append_entity_fact",
}


def test_application_context_imports_no_upper_layers() -> None:
    _assert_no_upper_layers(_CONTEXT_MODULE)


def test_application_context_does_not_import_storage_at_runtime() -> None:
    _clean_import(_CONTEXT_MODULE)
    offending = sorted(m for m in _modules_loaded() if m.startswith("dnd_assistant.storage"))
    assert not offending, f"application.post_session_context imported storage: {offending}"


def test_application_context_names_no_concrete_storage_class() -> None:
    names = _module_name_nodes(_CONTEXT_MODULE)
    assert "ObsidianVaultRepository" not in names
    assert "ObsidianSessionMetadataRepository" not in names
    assert "ObsidianSessionEventRepository" not in names
    assert "ObsidianPostSessionProcessingStore" not in names


def test_application_context_names_no_write_capable_repository_method() -> None:
    names = _module_name_nodes(_CONTEXT_MODULE)
    offending = sorted(names & _WRITE_CAPABLE_METHOD_NAMES)
    assert not offending, f"application.post_session_context references writes: {offending}"


def test_application_context_imports_no_model_or_ledger_or_retrieval() -> None:
    targets = _module_import_targets(_CONTEXT_MODULE)
    offending = sorted(
        target
        for target in targets
        if target.startswith("dnd_assistant.models")
        or target.startswith("dnd_assistant.tools")
        or target.startswith("dnd_assistant.cli")
        or target.startswith("dnd_assistant.retrieval")
        or target == "dnd_assistant.application.post_session_ledger"
    )
    assert not offending, f"application.post_session_context imported forbidden deps: {offending}"


def test_application_context_is_provider_neutral() -> None:
    _assert_provider_neutral(_CONTEXT_MODULE)


# ── domain/post_session_extraction (S11-03) ────────────────────────────────

_EXTRACTION_DOMAIN_MODULE = "dnd_assistant.domain.post_session_extraction"


def test_extraction_domain_imports_no_upper_layers() -> None:
    _assert_no_upper_layers(_EXTRACTION_DOMAIN_MODULE)


def test_extraction_domain_does_not_import_storage_or_application() -> None:
    _clean_import(_EXTRACTION_DOMAIN_MODULE)
    loaded = _modules_loaded()
    offending = sorted(
        m
        for m in loaded
        if m.startswith("dnd_assistant.storage") or m.startswith("dnd_assistant.application")
    )
    assert not offending, (
        f"domain.post_session_extraction imported storage/application: {offending}"
    )


def test_extraction_domain_has_no_persistence_stdlib() -> None:
    targets = _module_import_targets(_EXTRACTION_DOMAIN_MODULE)
    offending = sorted(
        target for target in targets if target.split(".")[0] in _FORBIDDEN_DOMAIN_STDLIB
    )
    assert not offending, f"domain.post_session_extraction imported persistence stdlib: {offending}"


def test_extraction_domain_is_provider_neutral() -> None:
    _assert_provider_neutral(_EXTRACTION_DOMAIN_MODULE)


# ── application/post_session_extraction (S11-03) ──────────────────────────

_EXTRACTION_POLICY_MODULE = "dnd_assistant.application.post_session_extraction"


def test_extraction_policy_imports_no_upper_layers() -> None:
    _assert_no_upper_layers(_EXTRACTION_POLICY_MODULE)


def test_extraction_policy_does_not_import_storage_at_runtime() -> None:
    _clean_import(_EXTRACTION_POLICY_MODULE)
    offending = sorted(m for m in _modules_loaded() if m.startswith("dnd_assistant.storage"))
    assert not offending, f"application.post_session_extraction imported storage: {offending}"


def test_extraction_policy_names_no_concrete_storage_class() -> None:
    names = _module_name_nodes(_EXTRACTION_POLICY_MODULE)
    assert "ObsidianVaultRepository" not in names
    assert "ObsidianChangeSetStore" not in names
    assert "ToolExecutor" not in names


def test_extraction_policy_is_provider_neutral() -> None:
    _assert_provider_neutral(_EXTRACTION_POLICY_MODULE)


def test_extraction_policy_imports_no_tools_cli_retrieval() -> None:
    targets = _module_import_targets(_EXTRACTION_POLICY_MODULE)
    offending = sorted(
        target
        for target in targets
        if target.startswith("dnd_assistant.models")
        or target.startswith("dnd_assistant.tools")
        or target.startswith("dnd_assistant.cli")
        or target.startswith("dnd_assistant.retrieval")
    )
    assert not offending, (
        f"application.post_session_extraction imported forbidden deps: {offending}"
    )


# ── application/pydantic_ai_post_session adapter (S11-03) ─────────────────

_EXTRACTION_ADAPTER_MODULE = "dnd_assistant.application.pydantic_ai_post_session"


def test_extraction_adapter_does_not_import_storage_tools_cli_retrieval() -> None:
    targets = _module_import_targets(_EXTRACTION_ADAPTER_MODULE)
    offending = sorted(
        target
        for target in targets
        if target.startswith("dnd_assistant.storage")
        or target.startswith("dnd_assistant.tools")
        or target.startswith("dnd_assistant.cli")
        or target.startswith("dnd_assistant.retrieval")
    )
    assert not offending, f"pydantic_ai_post_session imported forbidden deps: {offending}"


def test_extraction_adapter_does_not_import_vault_repository_or_models_layer() -> None:
    names = _module_name_nodes(_EXTRACTION_ADAPTER_MODULE)
    for forbidden in ("ToolExecutor", "ToolRegistry", "ExternalToolset", "VaultRepository"):
        assert forbidden not in names, f"pydantic_ai_post_session references {forbidden}"


def test_extraction_modules_do_not_import_tool_executor() -> None:
    for module_path in (
        "dnd_assistant.domain.post_session_extraction",
        "dnd_assistant.application.post_session_extraction",
        "dnd_assistant.application.pydantic_ai_post_session",
        "dnd_assistant.prompts.post_session_extraction_v1",
    ):
        targets = _module_import_targets(module_path)
        offending = sorted(target for target in targets if target == "dnd_assistant.tools.executor")
        assert not offending, f"{module_path} imported ToolExecutor"


def test_extraction_prompt_is_provider_neutral() -> None:
    _assert_provider_neutral("dnd_assistant.prompts.post_session_extraction_v1")


# ── storage/post_session_processing ───────────────────────────────────────

_STORAGE_MODULE = "dnd_assistant.storage.post_session_processing"


def test_storage_processing_depends_only_on_storage_domain_errors() -> None:
    targets = _module_import_targets(_STORAGE_MODULE)
    offending = sorted(
        target
        for target in targets
        if target.startswith("dnd_assistant.")
        and not target.startswith("dnd_assistant.storage")
        and target != "dnd_assistant.errors"
    )
    assert not offending, f"storage.post_session_processing imported non-storage deps: {offending}"


def test_storage_processing_imports_no_upper_layers() -> None:
    _assert_no_upper_layers(_STORAGE_MODULE)


def test_storage_processing_is_provider_neutral() -> None:
    _assert_provider_neutral(_STORAGE_MODULE)


def test_storage_processing_does_not_import_application() -> None:
    _clean_import(_STORAGE_MODULE)
    offending = sorted(m for m in _modules_loaded() if m.startswith("dnd_assistant.application"))
    assert not offending, f"storage.post_session_processing imported application: {offending}"


# ── domain/post_session_artifacts (S11-04) ─────────────────────────────────

_ARTIFACTS_DOMAIN_MODULE = "dnd_assistant.domain.post_session_artifacts"


def test_artifacts_domain_imports_no_upper_layers() -> None:
    _assert_no_upper_layers(_ARTIFACTS_DOMAIN_MODULE)


def test_artifacts_domain_does_not_import_storage_or_application() -> None:
    _clean_import(_ARTIFACTS_DOMAIN_MODULE)
    loaded = _modules_loaded()
    offending = sorted(
        m
        for m in loaded
        if m.startswith("dnd_assistant.storage") or m.startswith("dnd_assistant.application")
    )
    assert not offending, f"domain.post_session_artifacts imported storage/application: {offending}"


def test_artifacts_domain_has_no_persistence_stdlib() -> None:
    targets = _module_import_targets(_ARTIFACTS_DOMAIN_MODULE)
    offending = sorted(
        target for target in targets if target.split(".")[0] in _FORBIDDEN_DOMAIN_STDLIB
    )
    assert not offending, f"domain.post_session_artifacts imported persistence stdlib: {offending}"


def test_artifacts_domain_is_provider_neutral() -> None:
    _assert_provider_neutral(_ARTIFACTS_DOMAIN_MODULE)


# ── application/post_session_visibility (S11-04) ───────────────────────────

_VISIBILITY_MODULE = "dnd_assistant.application.post_session_visibility"


def test_visibility_imports_no_upper_layers() -> None:
    _assert_no_upper_layers(_VISIBILITY_MODULE)


def test_visibility_does_not_import_storage_at_runtime() -> None:
    _clean_import(_VISIBILITY_MODULE)
    offending = sorted(m for m in _modules_loaded() if m.startswith("dnd_assistant.storage"))
    assert not offending, f"application.post_session_visibility imported storage: {offending}"


def test_visibility_names_no_concrete_storage_class() -> None:
    names = _module_name_nodes(_VISIBILITY_MODULE)
    assert "ObsidianVaultRepository" not in names
    assert "ObsidianPostSessionProcessingStore" not in names
    assert "ToolExecutor" not in names


def test_visibility_is_provider_neutral() -> None:
    _assert_provider_neutral(_VISIBILITY_MODULE)


# ── application/post_session_rendering (S11-04) ────────────────────────────

_RENDERING_MODULE = "dnd_assistant.application.post_session_rendering"


def test_rendering_imports_no_upper_layers() -> None:
    _assert_no_upper_layers(_RENDERING_MODULE)


def test_rendering_does_not_import_storage_at_runtime() -> None:
    _clean_import(_RENDERING_MODULE)
    offending = sorted(m for m in _modules_loaded() if m.startswith("dnd_assistant.storage"))
    assert not offending, f"application.post_session_rendering imported storage: {offending}"


def test_rendering_names_no_concrete_storage_class_or_write_method() -> None:
    names = _module_name_nodes(_RENDERING_MODULE)
    assert "ObsidianVaultRepository" not in names
    assert "ObsidianChangeSetStore" not in names
    assert "ToolExecutor" not in names
    offending = sorted(names & _WRITE_CAPABLE_METHOD_NAMES)
    assert not offending, f"application.post_session_rendering references writes: {offending}"


def test_rendering_is_provider_neutral() -> None:
    _assert_provider_neutral(_RENDERING_MODULE)


# ── application/pydantic_ai_post_session_rendering adapter (S11-04) ────────

_RENDERING_ADAPTER_MODULE = "dnd_assistant.application.pydantic_ai_post_session_rendering"


def test_rendering_adapter_does_not_import_storage_tools_cli_retrieval() -> None:
    targets = _module_import_targets(_RENDERING_ADAPTER_MODULE)
    offending = sorted(
        target
        for target in targets
        if target.startswith("dnd_assistant.storage")
        or target.startswith("dnd_assistant.tools")
        or target.startswith("dnd_assistant.cli")
        or target.startswith("dnd_assistant.retrieval")
    )
    assert not offending, f"pydantic_ai_post_session_rendering imported forbidden deps: {offending}"


def test_rendering_adapter_does_not_reference_tool_or_vault_surface() -> None:
    names = _module_name_nodes(_RENDERING_ADAPTER_MODULE)
    for forbidden in ("ToolExecutor", "ToolRegistry", "ExternalToolset", "VaultRepository"):
        assert forbidden not in names, f"rendering adapter references {forbidden}"


def test_rendering_modules_do_not_import_tool_executor() -> None:
    for module_path in (
        "dnd_assistant.domain.post_session_artifacts",
        "dnd_assistant.application.post_session_visibility",
        "dnd_assistant.application.post_session_rendering",
        "dnd_assistant.application.pydantic_ai_post_session_rendering",
        "dnd_assistant.prompts.post_session_summary_v1",
        "dnd_assistant.prompts.post_session_recap_v1",
    ):
        targets = _module_import_targets(module_path)
        offending = sorted(target for target in targets if target == "dnd_assistant.tools.executor")
        assert not offending, f"{module_path} imported ToolExecutor"


def test_shared_error_classifier_is_provider_adjacent_only() -> None:
    targets = _module_import_targets("dnd_assistant.application.pydantic_ai_model_errors")
    offending = sorted(
        target
        for target in targets
        if target.startswith("dnd_assistant.storage")
        or target.startswith("dnd_assistant.tools")
        or target.startswith("dnd_assistant.cli")
        or target.startswith("dnd_assistant.retrieval")
    )
    assert not offending, f"pydantic_ai_model_errors imported forbidden deps: {offending}"


def test_rendering_prompts_are_provider_neutral() -> None:
    _assert_provider_neutral("dnd_assistant.prompts.post_session_summary_v1")
    _assert_provider_neutral("dnd_assistant.prompts.post_session_recap_v1")


# ── S11-05 producer / binding / allocator / shared provenance ──────────────

_S11_05_APP_MODULES: tuple[str, ...] = (
    "dnd_assistant.application.post_session_changeset",
    "dnd_assistant.application.post_session_binding",
    "dnd_assistant.application.entity_id_allocator",
    "dnd_assistant.application.post_session_provenance",
)

_PLAYER_RETRIEVAL_SYMBOLS: frozenset[str] = frozenset(
    {
        "SearchService",
        "EntityResolver",
        "VaultSearchService",
        "SearchHit",
        "SearchQuery",
        "MatchKind",
    }
)

_PLAYER_RETRIEVAL_MODULES: frozenset[str] = frozenset(
    {
        "dnd_assistant.retrieval.search",
        "dnd_assistant.retrieval.service",
        "dnd_assistant.retrieval.resolver",
        "dnd_assistant.retrieval.index",
        "dnd_assistant.retrieval.lexical",
    }
)


def test_s11_05_modules_do_not_use_player_resolver_or_service() -> None:
    for module_path in _S11_05_APP_MODULES:
        names = _module_name_nodes(module_path)
        offending = sorted(names & _PLAYER_RETRIEVAL_SYMBOLS)
        assert not offending, f"{module_path} references player retrieval symbols: {offending}"

        targets = _module_import_targets(module_path)
        offending_modules = sorted(
            target for target in targets if target in _PLAYER_RETRIEVAL_MODULES
        )
        assert not offending_modules, (
            f"{module_path} imports player retrieval modules: {offending_modules}"
        )


def test_s11_05_modules_name_no_concrete_storage_or_write_method() -> None:
    for module_path in _S11_05_APP_MODULES:
        names = _module_name_nodes(module_path)
        assert "ObsidianVaultRepository" not in names, module_path
        assert "ObsidianChangeSetStore" not in names, module_path
        assert "ToolExecutor" not in names, module_path
        offending = sorted(names & _WRITE_CAPABLE_METHOD_NAMES)
        assert not offending, f"{module_path} references writes: {offending}"


def test_s11_05_modules_import_no_tools_cli_or_models() -> None:
    for module_path in _S11_05_APP_MODULES:
        targets = _module_import_targets(module_path)
        offending = sorted(
            target
            for target in targets
            if target.startswith("dnd_assistant.models")
            or target.startswith("dnd_assistant.tools")
            or target.startswith("dnd_assistant.cli")
        )
        assert not offending, f"{module_path} imported forbidden deps: {offending}"


def test_s11_05_producer_has_no_apply_or_persistence_authority() -> None:
    module_path = "dnd_assistant.application.post_session_changeset"
    targets = _module_import_targets(module_path)
    offending = sorted(
        target
        for target in targets
        if target
        in {
            "dnd_assistant.application.changeset_apply",
            "dnd_assistant.application.changeset_store",
        }
    )
    assert not offending, f"{module_path} imported apply/store authority: {offending}"

    names = _module_name_nodes(module_path)
    for forbidden in ("apply_changeset", "ChangeSetApproval", "persist_proposal"):
        assert forbidden not in names, f"{module_path} references {forbidden}"


def test_s11_05_modules_are_provider_neutral() -> None:
    for module_path in _S11_05_APP_MODULES:
        _assert_provider_neutral(module_path)


def test_exact_matching_helper_is_pure_and_provider_neutral() -> None:
    targets = _module_import_targets("dnd_assistant.retrieval.exact_matching")
    offending = sorted(target for target in targets if target.startswith("dnd_assistant"))
    assert not offending, f"exact_matching imported dnd_assistant modules: {offending}"
    _assert_provider_neutral("dnd_assistant.retrieval.exact_matching")
