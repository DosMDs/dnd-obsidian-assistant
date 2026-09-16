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
