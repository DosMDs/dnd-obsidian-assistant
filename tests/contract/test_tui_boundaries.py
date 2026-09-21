"""Contract tests: TUI presentation boundary and semantic-core guard (TUI-03).

Enforces the accepted TUI-03 boundaries:

    domain/storage/retrieval/tools/models/application/composition -> tui   FORBIDDEN
    tui -> cli                                                             FORBIDDEN
    cli -> tui                                                             lazy only (function body)

and the structural presentation/auth separation:

    SemanticCommand exposes only presentation predicates (applicable/enabled),
    no authorization/policy field; the dispatcher evaluates no write policy.

Checks are static (AST) or structural (dataclass schema) and read-only: no Git,
no shell, no network. This module is separate from
``tests/contract/test_textual_boundaries.py`` (TUI-01) and
``tests/contract/test_composition_boundaries.py`` (TUI-02) and does not grow
``tests/contract/test_boundaries.py``.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

from dnd_assistant.tui import commands as tui_commands
from dnd_assistant.tui.commands import SemanticCommand

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = REPO_ROOT / "src" / "dnd_assistant"
TUI_ROOT = SRC_ROOT / "tui"
CLI_MAIN = SRC_ROOT / "cli" / "main.py"

TUI_PACKAGE = "dnd_assistant.tui"
CLI_PACKAGE = "dnd_assistant.cli"
TEXTUAL_ROOT = "textual"

TRUSTED_AND_SHARED_LAYERS: tuple[str, ...] = (
    "domain",
    "storage",
    "retrieval",
    "tools",
    "models",
    "application",
    "composition",
)

EXPECTED_COMMAND_FIELDS = {
    "id",
    "title",
    "description",
    "handler",
    "scope",
    "default_keys",
    "palette",
    "applicable",
    "enabled",
}

FORBIDDEN_FIELD_SUBSTRINGS = (
    "authoriz",
    "permission",
    "permit",
    "policy",
    "can_write",
    "write",
)


def _module_import_targets(path: Path) -> set[str]:
    """Return every absolute module name imported anywhere in a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            targets.add(node.module)
    return targets


def _module_level_import_targets(path: Path) -> set[str]:
    """Return imports reachable at module scope, excluding function bodies."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: set[str] = set()

    def visit(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, ast.Import):
                targets.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module is not None and node.level == 0:
                    targets.add(node.module)
            elif isinstance(node, (ast.ClassDef,)):
                continue
            elif isinstance(node, (ast.If, ast.Try)):
                visit(node.body)
                for handler in getattr(node, "handlers", []):
                    visit(handler.body)
                visit(getattr(node, "orelse", []))
                visit(getattr(node, "finalbody", []))

    visit(tree.body)
    return targets


def _tui_files() -> list[Path]:
    files = sorted(TUI_ROOT.rglob("*.py"))
    assert files, f"expected TUI package files under {TUI_ROOT}"
    return files


def _is_or_under(module: str, package: str) -> bool:
    return module == package or module.startswith(f"{package}.")


# ── Trusted/shared layers must not depend on the TUI ─────────────────────────


def test_trusted_and_shared_layers_do_not_import_tui() -> None:
    offenders: list[str] = []
    for layer in TRUSTED_AND_SHARED_LAYERS:
        layer_dir = SRC_ROOT / layer
        assert layer_dir.is_dir(), f"expected layer directory: {layer_dir}"
        for path in sorted(layer_dir.rglob("*.py")):
            for target in _module_import_targets(path):
                if _is_or_under(target, TUI_PACKAGE):
                    offenders.append(f"{path.relative_to(REPO_ROOT)} imports {target}")
    assert not offenders, f"trusted/shared layers import TUI: {offenders}"


# ── TUI must not depend on the CLI ───────────────────────────────────────────


def test_tui_does_not_import_cli() -> None:
    offenders: list[str] = []
    for path in _tui_files():
        for target in _module_import_targets(path):
            if _is_or_under(target, CLI_PACKAGE):
                offenders.append(f"{path.relative_to(REPO_ROOT)} imports {target}")
    assert not offenders, f"TUI imports CLI: {offenders}"


def test_tui_package_init_has_no_eager_internal_imports() -> None:
    init = TUI_ROOT / "__init__.py"
    assert init.is_file(), f"missing TUI package marker: {init}"
    internal = sorted(
        target for target in _module_import_targets(init) if target.startswith("dnd_assistant")
    )
    assert not internal, f"tui/__init__.py eagerly imports: {internal}"


def test_semantic_core_modules_are_textual_free() -> None:
    for name in ("commands.py", "dispatch.py"):
        path = TUI_ROOT / name
        assert path.is_file(), f"missing semantic-core module: {path}"
        targets = _module_import_targets(path)
        assert TEXTUAL_ROOT not in {target.split(".")[0] for target in targets}, (
            f"{name} imports Textual; the semantic core must stay framework-free"
        )


# ── CLI -> TUI is lazy only ──────────────────────────────────────────────────


def test_cli_main_does_not_import_tui_at_module_scope() -> None:
    targets = _module_level_import_targets(CLI_MAIN)
    for target in targets:
        assert not _is_or_under(target, TUI_PACKAGE), (
            f"cli/main.py imports TUI at module scope: {target}"
        )
        assert target.split(".")[0] != TEXTUAL_ROOT, (
            f"cli/main.py imports textual at module scope: {target}"
        )


# ── Structural presentation / authorization separation ───────────────────────


def test_semantic_command_exposes_only_presentation_fields() -> None:
    field_names = {field.name for field in dataclasses.fields(SemanticCommand)}
    assert field_names == EXPECTED_COMMAND_FIELDS


def test_semantic_command_has_no_authorization_field() -> None:
    for field in dataclasses.fields(SemanticCommand):
        lowered = field.name.lower()
        for forbidden in FORBIDDEN_FIELD_SUBSTRINGS:
            assert forbidden not in lowered, (
                f"SemanticCommand.{field.name} looks like authorization/policy; "
                "applicable/enabled are presentation predicates only"
            )


def test_dispatcher_imports_no_write_policy_layer() -> None:
    targets = _module_import_targets(TUI_ROOT / "dispatch.py")
    forbidden_layers = ("tools", "application", "storage", "retrieval", "models")
    for target in targets:
        if not target.startswith("dnd_assistant."):
            continue
        rest = target.removeprefix("dnd_assistant.")
        assert not any(
            rest == layer or rest.startswith(f"{layer}.") for layer in forbidden_layers
        ), f"dispatcher imports trusted write-capable layer: {target}"


def test_semantic_command_module_documents_predicates_as_presentation() -> None:
    doc = tui_commands.__doc__ or ""
    assert "presentation predicates only" in doc
    assert "never an authorization boundary" in doc


# ── TUI-04 capability modules keep the privacy/UI boundaries ─────────────────


def _imports(path: Path) -> set[str]:
    return _module_import_targets(path)


def test_campaign_state_view_does_not_import_materialization_or_storage() -> None:
    """The player-facing Campaign-State view must not see internal state."""
    targets = _imports(TUI_ROOT / "campaign_state.py")
    forbidden = (
        "dnd_assistant.application.campaign_state_materialization",
        "dnd_assistant.application.campaign_state_projection",
        "dnd_assistant.application.campaign_state_source",
        "dnd_assistant.storage",
        "pathlib",
    )
    for target in targets:
        for prefix in forbidden:
            assert not _is_or_under(target, prefix), (
                f"tui/campaign_state.py imports internal implementation: {target}"
            )


def test_capability_views_do_not_import_cli() -> None:
    for name in (
        "assistant.py",
        "session.py",
        "campaign_state.py",
        "services.py",
        "view.py",
        "inputs.py",
        "errors.py",
        "styles.py",
        "screens.py",
        "sidebar.py",
        "transcript.py",
    ):
        path = TUI_ROOT / name
        if not path.is_file():
            continue
        targets = _imports(path)
        assert not any(_is_or_under(target, CLI_PACKAGE) for target in targets), (
            f"tui/{name} imports CLI"
        )


def test_sidebar_and_transcript_have_no_persistence_or_internal_imports() -> None:
    """The new presentation modules must not reach Vault/internal state directly."""
    forbidden_roots = {"pathlib", "os", "json", "hashlib", "shutil"}
    forbidden_modules = (
        "dnd_assistant.storage",
        "dnd_assistant.application.campaign_state_materialization",
        "dnd_assistant.application.campaign_state_projection",
        "dnd_assistant.application.campaign_state_source",
    )
    for name in ("sidebar.py", "transcript.py"):
        path = TUI_ROOT / name
        assert path.is_file(), f"missing presentation module: {path}"
        for target in _imports(path):
            assert target.split(".")[0] not in forbidden_roots, (
                f"tui/{name} imports persistence/IO module: {target}"
            )
            for prefix in forbidden_modules:
                assert not _is_or_under(target, prefix), (
                    f"tui/{name} imports internal implementation: {target}"
                )


def test_textual_free_tui_modules_stay_framework_free() -> None:
    for name in (
        "commands.py",
        "dispatch.py",
        "inflight.py",
        "services.py",
        "errors.py",
        "styles.py",
    ):
        path = TUI_ROOT / name
        if not path.is_file():
            continue
        roots = {target.split(".")[0] for target in _imports(path)}
        assert TEXTUAL_ROOT not in roots, f"tui/{name} must stay Textual-free"


def test_services_bundle_has_no_service_locator_surface() -> None:
    from dnd_assistant.tui.services import TuiServices

    for name in ("get_service", "get", "__getitem__", "registry"):
        assert not hasattr(TuiServices, name), (
            f"TuiServices must not expose service-locator surface {name!r}"
        )


def test_player_campaign_state_view_has_only_player_safe_fields() -> None:
    from dnd_assistant.composition.campaign_state import PlayerCampaignStateView

    field_names = {field.name for field in dataclasses.fields(PlayerCampaignStateView)}
    assert field_names == {"status", "recently_touched"}
    for forbidden in ("state", "manifest", "fingerprint", "cause", "detail", "visibility"):
        assert forbidden not in field_names


def test_in_flight_gate_is_textual_free_and_has_no_queue() -> None:
    from dnd_assistant.tui.inflight import InFlightGate

    targets = _imports(TUI_ROOT / "inflight.py")
    assert TEXTUAL_ROOT not in {target.split(".")[0] for target in targets}
    for name in ("put", "enqueue", "queue", "schedule", "submit"):
        assert not hasattr(InFlightGate, name)


# ── TUI-05 hardening boundaries ──────────────────────────────────────────────


def test_paste_hardening_uses_public_event_surface() -> None:
    """Input paste hardening must use the public ``on_paste`` handler.

    Pinned Textual 8.2.8 dispatches a subclass private ``_on_paste`` alongside
    the base handler; the public surface plus ``prevent_default`` is the
    supported suppression path.
    """
    source = (TUI_ROOT / "inputs.py").read_text(encoding="utf-8")
    assert "def on_paste" in source
    assert "def _on_paste" not in source


def test_no_trusted_worker_cancellation_in_production_tui() -> None:
    """No production TUI code may cancel trusted thread work."""
    offenders: list[str] = []
    for path in _tui_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "cancel"
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert not offenders, f"production TUI calls cancel(): {offenders}"


# ── Detector self-tests (guards must not be vacuous) ─────────────────────────


def test_detector_recognizes_tui_import(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from dnd_assistant.tui.app import DndTuiApp\n",
        encoding="utf-8",
    )
    assert any(_is_or_under(t, TUI_PACKAGE) for t in _module_import_targets(sample))


def test_detector_ignores_unrelated_and_relative_imports(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import textual_helpers\nfrom .tui_helpers import thing\nimport dnd_assistant.tuition\n",
        encoding="utf-8",
    )
    targets = _module_import_targets(sample)
    assert not any(_is_or_under(t, TUI_PACKAGE) for t in targets)
    assert "textual" not in {t.split(".")[0] for t in targets}


def test_module_level_detector_skips_function_local_imports(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def command() -> None:\n    from dnd_assistant.tui.launcher import run\n    run()\n",
        encoding="utf-8",
    )
    assert not _module_level_import_targets(sample)


def test_module_level_detector_sees_top_level_imports(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("from dnd_assistant.tui.app import DndTuiApp\n", encoding="utf-8")
    assert any(_is_or_under(t, TUI_PACKAGE) for t in _module_level_import_targets(sample))
