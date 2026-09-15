"""Contract tests: S10-05 ChangeSet workflow persistence and CLI boundaries.

These guards protect the Stage-10 ChangeSet workflow trust boundary:

- ``storage.changeset_store`` deals only in opaque text and must not depend on
  ChangeSet domain/application types, model/provider, tool, retrieval or CLI
  layers, nor import a framework;
- ``application.changeset_store`` depends only on the ``ChangeSetStore``
  protocol (no concrete storage implementation, no runtime storage import) and
  stays provider-neutral;
- ``cli.changeset`` performs UX only: no direct ``VaultRepository`` mutation, no
  ``EntityPatch`` construction, no direct artifact reads/writes and no
  provider/framework dependency.

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
    """Import a module from a clean ``sys.modules`` state."""
    import sys

    for key in list(sys.modules):
        if key.startswith("dnd_assistant"):
            del sys.modules[key]
    importlib.import_module(module_path)


def _modules_loaded() -> set[str]:
    """Return the set of ``dnd_assistant`` sub-modules currently loaded."""
    import sys

    return {m for m in sys.modules if m.startswith("dnd_assistant.")}


def _module_import_targets(module_path: str) -> set[str]:
    """Return every module named by an import statement at any nesting depth."""
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


def _module_name_nodes(module_path: str) -> set[str]:
    """Return every bare identifier name used in a module's AST."""
    spec = importlib.util.find_spec(module_path)
    assert spec is not None and spec.origin is not None, f"cannot locate module {module_path}"
    tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def _module_call_names(module_path: str) -> tuple[set[str], set[str]]:
    """Return (attribute-call names, bare-call names) for a module."""
    spec = importlib.util.find_spec(module_path)
    assert spec is not None and spec.origin is not None, f"cannot locate module {module_path}"
    tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    attrs = {node.func.attr for node in calls if isinstance(node.func, ast.Attribute)}
    names = {node.func.id for node in calls if isinstance(node.func, ast.Name)}
    return attrs, names


# ── storage/changeset_store ────────────────────────────────────────────────

_FORBIDDEN_CHANGESET_STORE_LAYERS: tuple[str, ...] = (
    "dnd_assistant.application",
    "dnd_assistant.models",
    "dnd_assistant.tools",
    "dnd_assistant.retrieval",
    "dnd_assistant.cli",
)


def test_storage_changeset_store_does_not_import_upper_layers() -> None:
    _clean_import("dnd_assistant.storage.changeset_store")
    loaded = _modules_loaded()
    offending = sorted(
        m
        for m in loaded
        if any(
            m == layer or m.startswith(f"{layer}.") for layer in _FORBIDDEN_CHANGESET_STORE_LAYERS
        )
    )
    assert not offending, f"storage.changeset_store imported forbidden layers: {offending}"


def test_storage_changeset_store_does_not_import_changeset_types() -> None:
    targets = _module_import_targets("dnd_assistant.storage.changeset_store")
    offending = sorted(
        target for target in targets if target.startswith("dnd_assistant.domain.changeset")
    )
    assert not offending, f"storage.changeset_store imported ChangeSet domain types: {offending}"


def test_storage_changeset_store_is_provider_neutral() -> None:
    targets = _module_import_targets("dnd_assistant.storage.changeset_store")
    roots = {target.split(".")[0] for target in targets}
    offending = sorted(roots & {"ollama", "pydantic_ai"})
    assert not offending, f"storage.changeset_store imported frameworks: {offending}"


# ── application/changeset_store ────────────────────────────────────────────

_FORBIDDEN_APPLICATION_CHANGESET_STORE_LAYERS: tuple[str, ...] = (
    "dnd_assistant.models",
    "dnd_assistant.tools",
    "dnd_assistant.retrieval",
    "dnd_assistant.cli",
)

# The ChangeSetStore protocol is declared in the cohesive storage module that
# also hosts its concrete implementation.  Only that protocol symbol may be
# referenced (under ``TYPE_CHECKING``); the concrete class must not be.
_ALLOWED_STORAGE_PROTOCOL_MODULES: frozenset[str] = frozenset(
    {"dnd_assistant.storage.changeset_store"}
)


def test_application_changeset_store_does_not_import_upper_layers() -> None:
    _clean_import("dnd_assistant.application.changeset_store")
    loaded = _modules_loaded()
    offending = sorted(
        m
        for m in loaded
        if any(
            m == layer or m.startswith(f"{layer}.")
            for layer in _FORBIDDEN_APPLICATION_CHANGESET_STORE_LAYERS
        )
    )
    assert not offending, f"application.changeset_store imported forbidden layers: {offending}"


def test_application_changeset_store_does_not_import_concrete_storage() -> None:
    targets = _module_import_targets("dnd_assistant.application.changeset_store")
    offending = sorted(
        target
        for target in targets
        if target.startswith("dnd_assistant.storage.")
        and target not in _ALLOWED_STORAGE_PROTOCOL_MODULES
    )
    assert not offending, f"application.changeset_store imported concrete storage: {offending}"


def test_application_changeset_store_references_protocol_not_concrete_class() -> None:
    names = _module_name_nodes("dnd_assistant.application.changeset_store")
    assert "ObsidianChangeSetStore" not in names


def test_application_changeset_store_does_not_import_storage_at_runtime() -> None:
    _clean_import("dnd_assistant.application.changeset_store")
    loaded = _modules_loaded()
    offending = sorted(m for m in loaded if m.startswith("dnd_assistant.storage"))
    assert not offending, f"application.changeset_store imported storage at runtime: {offending}"


def test_application_changeset_store_is_provider_neutral() -> None:
    targets = _module_import_targets("dnd_assistant.application.changeset_store")
    roots = {target.split(".")[0] for target in targets}
    offending = sorted(roots & {"ollama", "pydantic_ai"})
    assert not offending, f"application.changeset_store imported frameworks: {offending}"


# ── cli/changeset ──────────────────────────────────────────────────────────

_CLI_CHANGESET = "dnd_assistant.cli.changeset"


def test_cli_changeset_does_not_mutate_vault_repository() -> None:
    call_attrs, _ = _module_call_names(_CLI_CHANGESET)
    assert call_attrs.isdisjoint({"create_entity", "patch_entity", "append_entity_fact"})


def test_cli_changeset_does_not_construct_entity_patch() -> None:
    assert "EntityPatch" not in _module_name_nodes(_CLI_CHANGESET)


def test_cli_changeset_does_not_write_artifacts_directly() -> None:
    call_attrs, call_names = _module_call_names(_CLI_CHANGESET)
    assert call_attrs.isdisjoint(
        {
            "create_proposal",
            "create_approval",
            "read_proposal",
            "read_approval",
            "read_proposal_if_present",
            "read_approval_if_present",
            "append_apply_attempt",
            "read_apply_attempts_if_present",
            "write_text",
            "write_bytes",
        }
    )
    assert "open" not in call_names


def test_cli_changeset_does_not_parse_audit_or_json_directly() -> None:
    call_attrs, _ = _module_call_names(_CLI_CHANGESET)
    # Audit records are obtained through AuditService (typed), never parsed by
    # the CLI; apply-attempt serialization stays in the application service.
    assert call_attrs.isdisjoint({"loads", "load", "dumps", "dump"})


def test_cli_changeset_is_provider_neutral() -> None:
    _clean_import(_CLI_CHANGESET)
    loaded = _modules_loaded()
    offending = sorted(
        m
        for m in loaded
        if m.startswith("dnd_assistant.models")
        or m == "ollama"
        or m.startswith("ollama.")
        or m == "pydantic_ai"
        or m.startswith("pydantic_ai.")
    )
    assert not offending, f"cli.changeset imported provider/framework modules: {offending}"


# ── application/changeset_status ───────────────────────────────────────────

_CHANGESET_STATUS = "dnd_assistant.application.changeset_status"

_FORBIDDEN_STATUS_LAYERS: tuple[str, ...] = (
    "dnd_assistant.models",
    "dnd_assistant.tools",
    "dnd_assistant.retrieval",
    "dnd_assistant.cli",
)

_FORBIDDEN_STATUS_STDLIB: frozenset[str] = frozenset(
    {"pathlib", "os", "shutil", "tempfile", "subprocess"}
)


def test_application_changeset_status_does_not_import_upper_layers() -> None:
    _clean_import(_CHANGESET_STATUS)
    loaded = _modules_loaded()
    offending = sorted(
        m
        for m in loaded
        if any(m == layer or m.startswith(f"{layer}.") for layer in _FORBIDDEN_STATUS_LAYERS)
    )
    assert not offending, f"application.changeset_status imported forbidden layers: {offending}"


def test_application_changeset_status_is_filesystem_free_and_provider_neutral() -> None:
    targets = _module_import_targets(_CHANGESET_STATUS)
    roots = {target.split(".")[0] for target in targets}
    offending = sorted(roots & (_FORBIDDEN_STATUS_STDLIB | {"ollama", "pydantic_ai"}))
    assert not offending, f"application.changeset_status imported forbidden modules: {offending}"


def test_application_changeset_status_references_no_concrete_storage_classes() -> None:
    # Storage is referenced only through the application layer / protocol types;
    # the status module itself names no concrete storage implementation.
    names = _module_name_nodes(_CHANGESET_STATUS)
    assert names.isdisjoint({"ObsidianChangeSetStore", "ObsidianVaultRepository"})


# ── storage/changeset_store dependency direction ───────────────────────────

_STORAGE_CHANGESET = "dnd_assistant.storage.changeset_store"


def test_storage_changeset_store_depends_only_on_storage_and_errors() -> None:
    targets = _module_import_targets(_STORAGE_CHANGESET)
    offending = sorted(
        target
        for target in targets
        if target.startswith("dnd_assistant.")
        and not target.startswith("dnd_assistant.storage")
        and target != "dnd_assistant.errors"
    )
    assert not offending, f"storage.changeset_store imported non-storage dependencies: {offending}"


# ── application/changeset_recovery (R1 ownership classification) ───────────

_CHANGESET_RECOVERY = "dnd_assistant.application.changeset_recovery"

_FORBIDDEN_RECOVERY_LAYERS: tuple[str, ...] = (
    "dnd_assistant.models",
    "dnd_assistant.tools",
    "dnd_assistant.retrieval",
    "dnd_assistant.cli",
)

_FORBIDDEN_RECOVERY_STDLIB: frozenset[str] = frozenset(
    {"pathlib", "os", "shutil", "tempfile", "subprocess"}
)


def test_application_changeset_recovery_does_not_import_upper_layers() -> None:
    _clean_import(_CHANGESET_RECOVERY)
    loaded = _modules_loaded()
    offending = sorted(
        m
        for m in loaded
        if any(m == layer or m.startswith(f"{layer}.") for layer in _FORBIDDEN_RECOVERY_LAYERS)
    )
    assert not offending, f"application.changeset_recovery imported forbidden layers: {offending}"


def test_application_changeset_recovery_is_filesystem_free_and_provider_neutral() -> None:
    targets = _module_import_targets(_CHANGESET_RECOVERY)
    roots = {target.split(".")[0] for target in targets}
    offending = sorted(roots & (_FORBIDDEN_RECOVERY_STDLIB | {"ollama", "pydantic_ai"}))
    assert not offending, f"application.changeset_recovery imported forbidden modules: {offending}"


def test_application_changeset_recovery_names_no_concrete_storage_classes() -> None:
    names = _module_name_nodes(_CHANGESET_RECOVERY)
    assert names.isdisjoint(
        {
            "ObsidianChangeSetStore",
            "ObsidianVaultRepository",
            "ObsidianSessionRecoveryRepository",
        }
    )


def test_application_session_recovery_stays_changeset_agnostic() -> None:
    targets = _module_import_targets("dnd_assistant.application.session_recovery")
    offending = sorted(
        target for target in targets if target.startswith("dnd_assistant.application.changeset")
    )
    assert not offending, f"application.session_recovery imported ChangeSet modules: {offending}"
