"""Contract tests: S12-01 Campaign State layer boundaries.

Guards the accepted dependency direction for the S12-01 foundations:

- ``domain.campaign_state`` is pure schema/value data: no storage/
  application/model/tool/retrieval/CLI import and no persistence stdlib;
- ``application.campaign_state_identity`` stays provider-neutral, imports no
  model/tool/retrieval/CLI layer, references no concrete storage implementation
  at runtime and may use the ``hashlib``/``json`` stdlib for canonical hashing;
- the promoted foundational value types keep backward-compatible re-exports.
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


# ── domain/campaign_state ──────────────────────────────────────────────────

_DOMAIN_MODULE = "dnd_assistant.domain.campaign_state"
_FORBIDDEN_DOMAIN_STDLIB = {"pathlib", "os", "hashlib"}


def test_domain_campaign_state_imports_no_upper_layers() -> None:
    _assert_no_upper_layers(_DOMAIN_MODULE)


def test_domain_campaign_state_does_not_import_storage_or_application() -> None:
    _clean_import(_DOMAIN_MODULE)
    loaded = _modules_loaded()
    offending = sorted(
        m
        for m in loaded
        if m.startswith("dnd_assistant.storage") or m.startswith("dnd_assistant.application")
    )
    assert not offending, f"domain.campaign_state imported storage/application: {offending}"


def test_domain_campaign_state_has_no_persistence_stdlib() -> None:
    targets = _module_import_targets(_DOMAIN_MODULE)
    offending = sorted(
        target for target in targets if target.split(".")[0] in _FORBIDDEN_DOMAIN_STDLIB
    )
    assert not offending, f"domain.campaign_state imported persistence stdlib: {offending}"


def test_domain_campaign_state_is_provider_neutral() -> None:
    _assert_provider_neutral(_DOMAIN_MODULE)


# ── application/campaign_state_identity ────────────────────────────────────

_IDENTITY_MODULE = "dnd_assistant.application.campaign_state_identity"
_FORBIDDEN_IDENTITY_STDLIB = {"pathlib", "os"}


def test_application_campaign_state_identity_imports_no_upper_layers() -> None:
    _assert_no_upper_layers(_IDENTITY_MODULE)


def test_application_campaign_state_identity_does_not_import_storage_at_runtime() -> None:
    _clean_import(_IDENTITY_MODULE)
    loaded = _modules_loaded()
    offending = sorted(m for m in loaded if m.startswith("dnd_assistant.storage"))
    assert not offending, f"application.campaign_state_identity imported storage: {offending}"


def test_application_campaign_state_identity_has_no_persistence_stdlib() -> None:
    targets = _module_import_targets(_IDENTITY_MODULE)
    offending = sorted(
        target for target in targets if target.split(".")[0] in _FORBIDDEN_IDENTITY_STDLIB
    )
    assert not offending, f"application.campaign_state_identity stdlib: {offending}"


def test_application_campaign_state_identity_allows_hashlib() -> None:
    targets = _module_import_targets(_IDENTITY_MODULE)
    assert "hashlib" in targets, "campaign_state_identity should own SHA-256 hashing via hashlib"


def test_application_campaign_state_identity_is_provider_neutral() -> None:
    _assert_provider_neutral(_IDENTITY_MODULE)


# ── application/campaign_state_source (S12-02) ─────────────────────────────

_SOURCE_MODULE = "dnd_assistant.application.campaign_state_source"
_FORBIDDEN_SOURCE_STDLIB = {"pathlib", "os", "hashlib", "json"}


def test_application_campaign_state_source_imports_no_upper_layers() -> None:
    _assert_no_upper_layers(_SOURCE_MODULE)


def test_application_campaign_state_source_does_not_import_storage_at_runtime() -> None:
    _clean_import(_SOURCE_MODULE)
    loaded = _modules_loaded()
    offending = sorted(m for m in loaded if m.startswith("dnd_assistant.storage"))
    assert not offending, f"application.campaign_state_source imported storage: {offending}"


def test_application_campaign_state_source_does_not_import_retrieval_at_runtime() -> None:
    _clean_import(_SOURCE_MODULE)
    loaded = _modules_loaded()
    offending = sorted(m for m in loaded if m.startswith("dnd_assistant.retrieval"))
    assert not offending, f"application.campaign_state_source imported retrieval: {offending}"


def test_application_campaign_state_source_has_no_persistence_stdlib() -> None:
    targets = _module_import_targets(_SOURCE_MODULE)
    offending = sorted(
        target for target in targets if target.split(".")[0] in _FORBIDDEN_SOURCE_STDLIB
    )
    assert not offending, f"application.campaign_state_source stdlib: {offending}"


def test_application_campaign_state_source_is_provider_neutral() -> None:
    _assert_provider_neutral(_SOURCE_MODULE)


# ── application/campaign_state_render (S12-03) ─────────────────────────────

_RENDER_MODULE = "dnd_assistant.application.campaign_state_render"
_FORBIDDEN_RENDER_STDLIB = {"pathlib", "os"}


def test_application_campaign_state_render_imports_no_upper_layers() -> None:
    _assert_no_upper_layers(_RENDER_MODULE)


def test_application_campaign_state_render_does_not_import_storage_at_runtime() -> None:
    _clean_import(_RENDER_MODULE)
    loaded = _modules_loaded()
    offending = sorted(m for m in loaded if m.startswith("dnd_assistant.storage"))
    assert not offending, f"application.campaign_state_render imported storage: {offending}"


def test_application_campaign_state_render_has_no_filesystem_stdlib() -> None:
    targets = _module_import_targets(_RENDER_MODULE)
    offending = sorted(
        target for target in targets if target.split(".")[0] in _FORBIDDEN_RENDER_STDLIB
    )
    assert not offending, f"application.campaign_state_render stdlib: {offending}"


def test_application_campaign_state_render_allows_hashlib_and_json() -> None:
    targets = _module_import_targets(_RENDER_MODULE)
    assert "hashlib" in targets
    assert "json" in targets


def test_application_campaign_state_render_is_provider_neutral() -> None:
    _assert_provider_neutral(_RENDER_MODULE)


# ── application/campaign_state_materialization (S12-03) ────────────────────

_MATERIALIZATION_MODULE = "dnd_assistant.application.campaign_state_materialization"
_FORBIDDEN_MATERIALIZATION_STDLIB = {"pathlib", "os", "hashlib", "json"}


def test_application_campaign_state_materialization_imports_no_upper_layers() -> None:
    _assert_no_upper_layers(_MATERIALIZATION_MODULE)


def test_application_campaign_state_materialization_has_no_storage_runtime_import() -> None:
    _clean_import(_MATERIALIZATION_MODULE)
    loaded = _modules_loaded()
    offending = sorted(m for m in loaded if m.startswith("dnd_assistant.storage"))
    assert not offending, (
        f"application.campaign_state_materialization imported storage at runtime: {offending}"
    )


def test_application_campaign_state_materialization_has_no_filesystem_stdlib() -> None:
    targets = _module_import_targets(_MATERIALIZATION_MODULE)
    offending = sorted(
        target for target in targets if target.split(".")[0] in _FORBIDDEN_MATERIALIZATION_STDLIB
    )
    assert not offending, f"application.campaign_state_materialization stdlib: {offending}"


def test_application_campaign_state_materialization_is_provider_neutral() -> None:
    _assert_provider_neutral(_MATERIALIZATION_MODULE)


# ── application/campaign_state_projection (S12-04) ─────────────────────────

_PROJECTION_MODULE = "dnd_assistant.application.campaign_state_projection"
_FORBIDDEN_PROJECTION_STDLIB = {"pathlib", "os", "hashlib", "json"}


def test_application_campaign_state_projection_imports_no_upper_layers() -> None:
    _assert_no_upper_layers(_PROJECTION_MODULE)


def test_application_campaign_state_projection_does_not_import_storage_at_runtime() -> None:
    _clean_import(_PROJECTION_MODULE)
    loaded = _modules_loaded()
    offending = sorted(m for m in loaded if m.startswith("dnd_assistant.storage"))
    assert not offending, f"application.campaign_state_projection imported storage: {offending}"


def test_application_campaign_state_projection_has_no_persistence_stdlib() -> None:
    targets = _module_import_targets(_PROJECTION_MODULE)
    offending = sorted(
        target for target in targets if target.split(".")[0] in _FORBIDDEN_PROJECTION_STDLIB
    )
    assert not offending, f"application.campaign_state_projection stdlib: {offending}"


def test_application_campaign_state_projection_is_provider_neutral() -> None:
    _assert_provider_neutral(_PROJECTION_MODULE)


# ── application/campaign_state_consumer (S12-04) ───────────────────────────

_CONSUMER_MODULE = "dnd_assistant.application.campaign_state_consumer"
_FORBIDDEN_CONSUMER_STDLIB = {"pathlib", "os", "hashlib", "json"}


def test_application_campaign_state_consumer_imports_no_upper_layers() -> None:
    _assert_no_upper_layers(_CONSUMER_MODULE)


def test_application_campaign_state_consumer_has_no_storage_runtime_import() -> None:
    _clean_import(_CONSUMER_MODULE)
    loaded = _modules_loaded()
    offending = sorted(m for m in loaded if m.startswith("dnd_assistant.storage"))
    assert not offending, f"application.campaign_state_consumer imported storage: {offending}"


def test_application_campaign_state_consumer_has_no_filesystem_stdlib() -> None:
    targets = _module_import_targets(_CONSUMER_MODULE)
    offending = sorted(
        target for target in targets if target.split(".")[0] in _FORBIDDEN_CONSUMER_STDLIB
    )
    assert not offending, f"application.campaign_state_consumer stdlib: {offending}"


def test_application_campaign_state_consumer_is_provider_neutral() -> None:
    _assert_provider_neutral(_CONSUMER_MODULE)


# ── storage/derived_state (S12-03) ─────────────────────────────────────────

_STORE_MODULE = "dnd_assistant.storage.derived_state"


def test_storage_derived_state_imports_no_application_or_upper_layers() -> None:
    _clean_import(_STORE_MODULE)
    loaded = _modules_loaded()
    forbidden = (
        "dnd_assistant.application",
        "dnd_assistant.models",
        "dnd_assistant.tools",
        "dnd_assistant.retrieval",
        "dnd_assistant.cli",
    )
    offending = sorted(
        m for m in loaded if any(m == layer or m.startswith(f"{layer}.") for layer in forbidden)
    )
    assert not offending, f"storage.derived_state imported forbidden layers: {offending}"


def test_storage_derived_state_is_provider_neutral() -> None:
    _assert_provider_neutral(_STORE_MODULE)


# ── promoted foundational value types keep Stage-10/11 imports working ─────


def test_promoted_value_types_have_backward_compatible_exports() -> None:
    from dnd_assistant.domain.post_session import (
        RelativeArtifactPath as PostSessionRelativePath,
    )
    from dnd_assistant.domain.post_session import (
        Sha256Fingerprint as PostSessionFingerprint,
    )
    from dnd_assistant.domain.types import (
        RelativeArtifactPath as FoundationalRelativePath,
    )
    from dnd_assistant.domain.types import (
        Sha256Fingerprint as FoundationalFingerprint,
    )

    assert PostSessionFingerprint is FoundationalFingerprint
    assert PostSessionRelativePath is FoundationalRelativePath
