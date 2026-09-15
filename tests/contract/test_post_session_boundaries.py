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
