"""Contract tests: curated provider/runtime upgrade regression gate.

This module protects the durable S14-05 ``provider_upgrade`` marker selection
from silent erosion.  It is a static, deterministic, offline contract:

- it parses ``pyproject.toml`` for the marker declaration;
- it AST-scans the test tree for module-level ``pytestmark`` markers and for
  individually decorated tests;
- it compares the observed selection against an explicit reviewed inventory.

It deliberately does NOT assert a total collected test count and does not run
pytest, a subprocess, a plugin, a custom collector or the network.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

# ── Repository roots ─────────────────────────────────────────────────────────

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
TESTS_ROOT = REPO_ROOT / "tests"
PYPROJECT = REPO_ROOT / "pyproject.toml"

MARKER = "provider_upgrade"

# ── Reviewed curated inventory (explicit, path-relative, forward slashes) ────

EXPECTED_OFFLINE_MODULES: frozenset[str] = frozenset(
    {
        "integration/test_pydantic_ai_agent_runtime.py",
        "integration/test_pydantic_ai_agent_runtime_boundaries.py",
        "integration/test_pydantic_ai_agent_runtime_evidence.py",
        "integration/test_pydantic_ai_agent_runtime_literal_evidence.py",
        "integration/test_pydantic_ai_agent_runtime_literal_evidence_p2.py",
        "integration/test_pydantic_ai_agent_runtime_literal_evidence_p3.py",
        "integration/test_pydantic_ai_blocker_limits.py",
        "integration/test_pydantic_ai_ollama_runtime.py",
        "integration/test_pydantic_ai_sync_thread_literal_evidence.py",
        "integration/test_pydantic_ai_sync_thread_literal_evidence_p2.py",
        "unit/post_session/test_pydantic_ai_post_session.py",
        "unit/post_session/test_pydantic_ai_post_session_rendering.py",
        "unit/test_bootstrap_composition.py",
        "unit/test_bootstrap_pydantic_ai.py",
        "unit/test_cli_agent_runtime.py",
        "unit/test_dnd_agent_policy.py",
        "unit/test_pydantic_ai_ollama.py",
        "unit/test_pydantic_ai_response_adapter.py",
        "unit/test_pydantic_ai_run_deps.py",
        "unit/test_pydantic_ai_tool_bridge.py",
        "unit/test_pydantic_ai_tool_bridge_authority.py",
    }
)

EXPECTED_LIVE_MODULES: frozenset[str] = frozenset(
    {
        "integration/test_pydantic_ai_ollama_live_runtime.py",
        "integration/test_pydantic_ai_ollama_smoke.py",
    }
)

# The qualification module is intentionally NOT marked wholesale: it mixes
# current production canaries with historical framework-default characterization.
QUALIFICATION_MODULE = "integration/test_pydantic_ai_qualification.py"

EXPECTED_QUALIFICATION_TESTS: frozenset[str] = frozenset(
    {
        "test_q1_import_and_version",
        "test_q1_ollama_classes_importable",
        "test_q2_run_sync",
        "test_q3_plain_text_response",
        "test_q4_structured_output",
        "test_q5_single_tool",
        "test_q7_custom_ollama_base_url",
        "test_q7_custom_ollama_base_url_with_openai_provider",
        "test_q8_connection_failure",
        "test_q8_structured_output_validation_failure",
        "test_q8b_unknown_tool_zero_retries",
        "test_public_exception_classes",
    }
)

# Mandatory semantic families; every member must be in the offline inventory.
SEMANTIC_FAMILIES: dict[str, frozenset[str]] = {
    "tool_executor_policy_bridge": frozenset(
        {
            "unit/test_dnd_agent_policy.py",
            "unit/test_pydantic_ai_tool_bridge.py",
            "unit/test_pydantic_ai_tool_bridge_authority.py",
        }
    ),
    "request_retry_limits": frozenset({"integration/test_pydantic_ai_blocker_limits.py"}),
    "bounded_runtime": frozenset(
        {
            "integration/test_pydantic_ai_agent_runtime.py",
            "integration/test_pydantic_ai_agent_runtime_boundaries.py",
        }
    ),
    "sync_thread_literal_evidence": frozenset(
        {
            "integration/test_pydantic_ai_sync_thread_literal_evidence.py",
            "integration/test_pydantic_ai_sync_thread_literal_evidence_p2.py",
        }
    ),
    "ollama_factory_mock_transport": frozenset(
        {
            "unit/test_pydantic_ai_ollama.py",
            "integration/test_pydantic_ai_ollama_runtime.py",
        }
    ),
    "bootstrap_structured_extraction": frozenset({"unit/test_bootstrap_pydantic_ai.py"}),
    "post_session_structured_extraction_rendering": frozenset(
        {
            "unit/post_session/test_pydantic_ai_post_session.py",
            "unit/post_session/test_pydantic_ai_post_session_rendering.py",
        }
    ),
    "composition_wiring": frozenset(
        {
            "unit/test_cli_agent_runtime.py",
            "unit/test_bootstrap_composition.py",
        }
    ),
}


# ── AST helpers ──────────────────────────────────────────────────────────────


def _relative_path(path: Path) -> str:
    return str(path.relative_to(TESTS_ROOT)).replace("\\", "/")


def _attr_chain(node: ast.AST) -> tuple[str, ...] | None:
    """Return the dotted attribute chain for ``a.b.c`` attribute/name nodes."""
    parts: list[str] = []
    current: ast.AST | None = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        parts.reverse()
        return tuple(parts)
    return None


def _marker_names(value: ast.AST) -> set[str]:
    """Extract ``pytest.mark.<name>`` marker names from an assignment value."""
    names: set[str] = set()

    def _add(node: ast.AST) -> None:
        chain = _attr_chain(node)
        if chain is not None and len(chain) == 3 and chain[:2] == ("pytest", "mark"):
            names.add(chain[2])

    if isinstance(value, (ast.List, ast.Tuple)):
        for elt in value.elts:
            _add(elt)
    else:
        _add(value)
    return names


def _module_level_markers(tree: ast.Module) -> set[str]:
    markers: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "pytestmark":
                    markers |= _marker_names(node.value)
    return markers


def _decorated_provider_upgrade_tests(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                chain = _attr_chain(decorator)
                if chain == ("pytest", "mark", MARKER):
                    names.add(node.name)
    return names


def _collect_py_files() -> list[Path]:
    return sorted(TESTS_ROOT.rglob("*.py"))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _observed() -> tuple[set[str], set[str], dict[str, set[str]]]:
    module_level: set[str] = set()
    individual: dict[str, set[str]] = {}
    for path in _collect_py_files():
        tree = _parse(path)
        rel = _relative_path(path)
        if MARKER in _module_level_markers(tree):
            module_level.add(rel)
        marks = _decorated_provider_upgrade_tests(tree)
        if marks:
            individual[rel] = marks
    return module_level, set(individual), individual


# ── Tests ────────────────────────────────────────────────────────────────────


def test_marker_registered_in_pyproject() -> None:
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    markers = config["tool"]["pytest"]["ini_options"]["markers"]
    declared = {entry.split(":", 1)[0].strip() for entry in markers}
    assert MARKER in declared, f"{MARKER!r} is not registered in pyproject.toml markers"


def test_all_expected_modules_exist() -> None:
    for rel in EXPECTED_OFFLINE_MODULES | EXPECTED_LIVE_MODULES | {QUALIFICATION_MODULE}:
        assert (TESTS_ROOT / rel).is_file(), f"reviewed gate module is missing: {rel}"


def test_reviewed_module_inventory_matches_selection() -> None:
    module_level, _, _ = _observed()
    expected = set(EXPECTED_OFFLINE_MODULES) | set(EXPECTED_LIVE_MODULES)
    missing = expected - module_level
    unexpected = module_level - expected
    assert not missing and not unexpected, (
        "provider_upgrade module-level marker inventory drifted. "
        f"Missing markers: {sorted(missing)}; unexpected markers: {sorted(unexpected)}"
    )


def test_qualification_tests_marked_individually() -> None:
    module_level, _, individual = _observed()
    assert QUALIFICATION_MODULE not in module_level, (
        "qualification module must not be marked wholesale"
    )
    observed = individual.get(QUALIFICATION_MODULE, set())
    missing = set(EXPECTED_QUALIFICATION_TESTS) - observed
    unexpected = observed - set(EXPECTED_QUALIFICATION_TESTS)
    assert not missing and not unexpected, (
        "individually-marked qualification canaries drifted. "
        f"Missing: {sorted(missing)}; unexpected: {sorted(unexpected)}"
    )


def test_live_modules_also_carry_ollama() -> None:
    for rel in EXPECTED_LIVE_MODULES:
        tree = _parse(TESTS_ROOT / rel)
        markers = _module_level_markers(tree)
        assert "ollama" in markers, f"live module {rel} must also carry the ollama marker"


def test_no_live_module_in_offline_inventory() -> None:
    overlap = set(EXPECTED_OFFLINE_MODULES) & set(EXPECTED_LIVE_MODULES)
    assert not overlap, f"modules cannot be both offline-only and live: {sorted(overlap)}"


def test_mandatory_semantic_families_present() -> None:
    for family, members in SEMANTIC_FAMILIES.items():
        missing = members - set(EXPECTED_OFFLINE_MODULES)
        assert not missing, f"semantic family {family!r} lacks offline modules: {sorted(missing)}"
