"""Tests for Stage 5 retrieval-layer contracts (S5-00).

Covers:
- retrieval types import correctly from the public API
- public exports are intentional
- MatchKind values and ordering semantics
- SearchQuery construction and validation
- SearchHit construction and properties
- ResolutionOutcome types (Resolved, Ambiguous, NotFound)
- ResolutionOutcome is a correct union type
- SearchService protocol is structurally usable
- EntityResolver protocol is structurally usable
- validation rejects malformed values
- Unicode query/name data is supported
- no dependency from domain/storage back into retrieval
- no model/Ollama/tool/session-runtime dependency
- no SQLite/FTS implementation pulled into S5-00
"""

from __future__ import annotations

import ast
from typing import cast

import pytest

from dnd_assistant.domain.types import EntityId, EntityType
from dnd_assistant.errors import DndAssistantError
from dnd_assistant.retrieval import (
    Ambiguous,
    EntityResolver,
    MatchKind,
    NotFound,
    ResolutionOutcome,
    Resolved,
    SearchHit,
    SearchQuery,
    SearchService,
)


class TestImports:
    def test_retrieval_package_importable(self) -> None:
        import dnd_assistant.retrieval  # noqa: F401

    def test_all_types_imported(self) -> None:
        assert all(
            t is not None
            for t in [
                MatchKind,
                SearchQuery,
                SearchHit,
                Resolved,
                Ambiguous,
                NotFound,
                ResolutionOutcome,
                SearchService,
                EntityResolver,
            ]
        )


class TestPublicExports:
    def test_retrieval_all_exports(self) -> None:
        from dnd_assistant.retrieval import __all__ as retrieval_all

        expected = {
            "Ambiguous",
            "EntityResolver",
            "MatchKind",
            "NotFound",
            "Resolved",
            "ResolutionOutcome",
            "SearchHit",
            "SearchQuery",
            "SearchService",
        }
        assert set(retrieval_all) == expected


class TestMatchKind:
    def test_values(self) -> None:
        assert MatchKind.EXACT_ID.value == "exact_id"
        assert MatchKind.EXACT_NAME.value == "exact_name"
        assert MatchKind.EXACT_ALIAS.value == "exact_alias"
        assert MatchKind.FUZZY_NAME.value == "fuzzy_name"
        assert MatchKind.FTS.value == "fts"

    def test_all_members(self) -> None:
        assert set(MatchKind) == {
            MatchKind.EXACT_ID,
            MatchKind.EXACT_NAME,
            MatchKind.EXACT_ALIAS,
            MatchKind.FUZZY_NAME,
            MatchKind.FTS,
        }

    def test_precedence_order(self) -> None:
        assert list(MatchKind) == [
            MatchKind.EXACT_ID,
            MatchKind.EXACT_NAME,
            MatchKind.EXACT_ALIAS,
            MatchKind.FUZZY_NAME,
            MatchKind.FTS,
        ]

    def test_str_representation(self) -> None:
        assert str(MatchKind.EXACT_ID) == "exact_id"


class TestSearchQuery:
    def test_minimal_query(self) -> None:
        q = SearchQuery(text="Varos")
        assert q.text == "Varos"
        assert q.entity_types is None

    def test_with_entity_types(self) -> None:
        q = SearchQuery(text="lighthouse", entity_types={EntityType.LOCATION})
        assert q.entity_types == {EntityType.LOCATION}

    def test_empty_entity_types_set(self) -> None:
        q = SearchQuery(text="test", entity_types=set())
        assert q.entity_types == set()

    def test_unicode_query(self) -> None:
        q = SearchQuery(text="Chyornoe Solntse")
        assert q.text == "Chyornoe Solntse"

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            SearchQuery(text="test", unknown_field="x")  # type: ignore[call-arg]

    @pytest.mark.parametrize(
        "invalid_text",
        [
            "",
            "   ",
            "\t",
            "\n",
            " \n ",
        ],
    )
    def test_empty_or_whitespace_rejected(self, invalid_text: str) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            SearchQuery(text=invalid_text)

    @pytest.mark.parametrize(
        "invalid_text",
        [
            "test\x00",
            "test\x1f",
            "test\x7f",
            "\x00test",
        ],
    )
    def test_control_characters_rejected(self, invalid_text: str) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            SearchQuery(text=invalid_text)

    @pytest.mark.parametrize(
        "invalid_value",
        [
            True,
            False,
            42,
            3.14,
            None,
            ["test"],
            {"key": "value"},
        ],
    )
    def test_non_string_rejected(self, invalid_value: object) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            SearchQuery(text=invalid_value)  # type: ignore[arg-type]


class TestSearchHit:
    def test_exact_id_hit(self) -> None:
        hit = SearchHit(
            entity_id=cast(EntityId, "npc_varos"),
            match_kind=MatchKind.EXACT_ID,
        )
        assert hit.entity_id == "npc_varos"
        assert hit.match_kind == MatchKind.EXACT_ID
        assert hit.score is None

    def test_fuzzy_hit_with_score(self) -> None:
        hit = SearchHit(
            entity_id=cast(EntityId, "npc_varos"),
            match_kind=MatchKind.FUZZY_NAME,
            score=85.5,
        )
        assert hit.score == 85.5

    def test_fts_hit_with_negative_score(self) -> None:
        hit = SearchHit(
            entity_id=cast(EntityId, "npc_varos"),
            match_kind=MatchKind.FTS,
            score=-2.5,
        )
        assert hit.score == -2.5

    def test_zero_score_valid(self) -> None:
        hit = SearchHit(
            entity_id=cast(EntityId, "npc_varos"),
            match_kind=MatchKind.FTS,
            score=0.0,
        )
        assert hit.score == 0.0

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            SearchHit(
                entity_id=cast(EntityId, "x"),
                match_kind=MatchKind.EXACT_ID,
                unknown=True,  # type: ignore[call-arg]
            )

    # ── Score validation: exact matches must have score=None ─────────────

    @pytest.mark.parametrize(
        "kind, bad_score",
        [
            (MatchKind.EXACT_ID, 0.0),
            (MatchKind.EXACT_ID, 100.0),
            (MatchKind.EXACT_NAME, 0.0),
            (MatchKind.EXACT_NAME, 42.0),
            (MatchKind.EXACT_ALIAS, 0.0),
            (MatchKind.EXACT_ALIAS, 99.9),
        ],
    )
    def test_exact_match_rejects_score(self, kind: MatchKind, bad_score: float) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            SearchHit(
                entity_id=cast(EntityId, "x"),
                match_kind=kind,
                score=bad_score,
            )

    # ── Score validation: FUZZY_NAME must have score in [0.0, 100.0] ────

    @pytest.mark.parametrize(
        "bad_score",
        [
            None,
            -0.1,
            -1.0,
            100.1,
            200.0,
            float("nan"),
            float("inf"),
            float("-inf"),
            True,
            False,
        ],
    )
    def test_fuzzy_rejects_invalid_score(self, bad_score: object) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            SearchHit(
                entity_id=cast(EntityId, "x"),
                match_kind=MatchKind.FUZZY_NAME,
                score=bad_score,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize("valid_score", [0.0, 50.0, 100.0, 0.5, 99.999])
    def test_fuzzy_accepts_valid_score(self, valid_score: float) -> None:
        hit = SearchHit(
            entity_id=cast(EntityId, "x"),
            match_kind=MatchKind.FUZZY_NAME,
            score=valid_score,
        )
        assert hit.score == valid_score

    # ── Score validation: FTS accepts None or finite numeric ─────────────

    @pytest.mark.parametrize(
        "bad_score",
        [
            float("nan"),
            float("inf"),
            float("-inf"),
            True,
            False,
        ],
    )
    def test_fts_rejects_invalid_score(self, bad_score: object) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            SearchHit(
                entity_id=cast(EntityId, "x"),
                match_kind=MatchKind.FTS,
                score=bad_score,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize("valid_score", [None, 0.0, -2.5, -100.0, 1.5])
    def test_fts_accepts_valid_score(self, valid_score: float | None) -> None:
        hit = SearchHit(
            entity_id=cast(EntityId, "x"),
            match_kind=MatchKind.FTS,
            score=valid_score,
        )
        assert hit.score == valid_score


class TestResolved:
    def test_construction(self) -> None:
        result = Resolved(
            entity_id=cast(EntityId, "npc_varos"),
            match_kind=MatchKind.EXACT_NAME,
        )
        assert result.entity_id == "npc_varos"
        assert result.match_kind == MatchKind.EXACT_NAME

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            Resolved(
                entity_id=cast(EntityId, "x"),
                match_kind=MatchKind.EXACT_ID,
                extra=True,  # type: ignore[call-arg]
            )


class TestAmbiguous:
    def test_with_two_candidates(self) -> None:
        candidates = [
            SearchHit(entity_id=cast(EntityId, "npc_varos"), match_kind=MatchKind.EXACT_ALIAS),
            SearchHit(
                entity_id=cast(EntityId, "npc_varos_junior"), match_kind=MatchKind.EXACT_ALIAS
            ),
        ]
        result = Ambiguous(candidates=candidates)
        assert len(result.candidates) == 2

    def test_with_one_candidate(self) -> None:
        """Single-candidate ambiguous represents low-confidence uncertainty."""
        candidates = [
            SearchHit(
                entity_id=cast(EntityId, "npc_varos"), match_kind=MatchKind.FUZZY_NAME, score=45.0
            ),
        ]
        result = Ambiguous(candidates=candidates)
        assert len(result.candidates) == 1

    def test_empty_candidates_rejected(self) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            Ambiguous(candidates=[])

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            Ambiguous(
                candidates=[
                    SearchHit(entity_id=cast(EntityId, "x"), match_kind=MatchKind.EXACT_ID),
                ],
                extra=True,  # type: ignore[call-arg]
            )


class TestNotFound:
    def test_construction(self) -> None:
        result = NotFound(query="unknown entity")
        assert result.query == "unknown entity"

    def test_unicode_query(self) -> None:
        result = NotFound(query="Чёрное Солнце")
        assert result.query == "Чёрное Солнце"

    def test_empty_rejected(self) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            NotFound(query="")

    def test_whitespace_only_rejected(self) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            NotFound(query="   ")

    def test_control_chars_rejected(self) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            NotFound(query="test\x00")

    def test_non_string_rejected(self) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            NotFound(query=42)  # type: ignore[arg-type]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            NotFound(query="x", extra=True)  # type: ignore[call-arg]


class TestResolutionOutcome:
    def test_resolved_is_outcome(self) -> None:
        outcome: ResolutionOutcome = Resolved(
            entity_id=cast(EntityId, "npc_varos"),
            match_kind=MatchKind.EXACT_NAME,
        )
        assert isinstance(outcome, Resolved)
        assert not isinstance(outcome, (Ambiguous, NotFound))

    def test_ambiguous_is_outcome(self) -> None:
        outcome: ResolutionOutcome = Ambiguous(
            candidates=[
                SearchHit(entity_id=cast(EntityId, "npc_varos"), match_kind=MatchKind.EXACT_ALIAS),
            ]
        )
        assert isinstance(outcome, Ambiguous)
        assert not isinstance(outcome, (Resolved, NotFound))

    def test_not_found_is_outcome(self) -> None:
        outcome: ResolutionOutcome = NotFound(query="x")
        assert isinstance(outcome, NotFound)
        assert not isinstance(outcome, (Resolved, Ambiguous))

    def test_outcomes_are_mutually_exclusive(self) -> None:
        resolved = Resolved(entity_id=cast(EntityId, "x"), match_kind=MatchKind.EXACT_ID)
        ambiguous = Ambiguous(
            candidates=[
                SearchHit(entity_id=cast(EntityId, "x"), match_kind=MatchKind.EXACT_ALIAS),
            ]
        )
        not_found = NotFound(query="x")
        assert not isinstance(resolved, (Ambiguous, NotFound))
        assert not isinstance(ambiguous, (Resolved, NotFound))
        assert not isinstance(not_found, (Resolved, Ambiguous))

    def test_resolution_outcome_is_union(self) -> None:
        from typing import get_args

        args = get_args(ResolutionOutcome)
        assert Resolved in args
        assert Ambiguous in args
        assert NotFound in args
        assert len(args) == 3


class TestSearchServiceProtocol:
    def test_protocol_is_runtime_checkable(self) -> None:
        assert hasattr(SearchService, "__instancecheck__")

    def test_protocol_has_required_methods(self) -> None:
        methods = {"search", "get_by_id"}
        protocol_methods = {m for m in dir(SearchService) if not m.startswith("_")}
        assert methods.issubset(protocol_methods)

    def test_concrete_class_can_satisfy_protocol(self) -> None:
        class FakeSearchService:
            def search(self, query: SearchQuery, *, limit: int = 20) -> list[SearchHit]:
                return []

            def get_by_id(self, entity_id: EntityId) -> SearchHit | None:
                return None

        assert isinstance(FakeSearchService(), SearchService)


class TestEntityResolverProtocol:
    def test_protocol_is_runtime_checkable(self) -> None:
        assert hasattr(EntityResolver, "__instancecheck__")

    def test_protocol_has_resolve_method(self) -> None:
        assert hasattr(EntityResolver, "resolve")

    def test_concrete_class_can_satisfy_protocol(self) -> None:
        class FakeResolver:
            def resolve(
                self, reference: str, *, entity_type: EntityType | None = None
            ) -> ResolutionOutcome:
                return NotFound(query=reference)

        assert isinstance(FakeResolver(), EntityResolver)


# ── Shared AST import helpers ───────────────────────────────────────────────


def _get_package_name(module_path: str) -> str:
    """Return the package name for *module_path*.

    If *module_path* is itself a package (has ``__path__``), returns
    *module_path* unchanged.  Otherwise returns the parent package
    (e.g. ``"dnd_assistant.retrieval.service"`` → ``"dnd_assistant.retrieval"``).
    """
    import importlib

    mod = importlib.import_module(module_path)
    return module_path if hasattr(mod, "__path__") else module_path.rsplit(".", 1)[0]


def _resolve_relative_import(module_path: str, level: int, relative_module: str | None) -> str:
    """Resolve a relative ``ImportFrom`` to an absolute module path.

    Parameters
    ----------
    module_path:
        The fully-qualified module being inspected
        (e.g. ``"dnd_assistant.retrieval.service"``).
    level:
        The ``node.level`` from the AST ``ImportFrom`` node
        (1 = ``.``, 2 = ``..``, etc.).
    relative_module:
        The ``node.module`` from the AST ``ImportFrom`` node
        (e.g. ``"types"``, ``"storage"``), or ``None`` for a bare
        relative import such as ``from . import X``.

    Returns
    -------
    The resolved absolute module path.

    Raises
    ------
    ValueError
        If *level* is < 1 or exceeds the package depth.
    """
    if level < 1:
        raise ValueError(f"Relative import level must be >= 1, got {level}")

    package = _get_package_name(module_path)
    parts = package.split(".")
    if level > len(parts):
        raise ValueError(f"Relative import level {level} exceeds package depth of {package!r}")
    base = parts[: len(parts) - (level - 1)] if level > 1 else parts
    if relative_module:
        base.extend(relative_module.split("."))
    return ".".join(base)


def _parse_imports_from_source(source: str, *, module_path: str | None = None) -> set[str]:
    """Parse *source* as Python code and return the set of full imported
    module paths.

    Inspects all syntactically present import nodes in the module AST,
    including imports inside ``TYPE_CHECKING`` blocks, functions, classes,
    and conditional branches.  This is intentional: dependency-boundary
    verification must catch all syntactically present imports, not only
    those that execute at runtime.

    When *module_path* is provided, relative ``ImportFrom`` nodes
    (``from .foo import X``, ``from ..bar import Y``) are resolved to
    absolute module paths relative to the given module.  When
    *module_path* is ``None``, relative imports are collected as-is
    (their ``node.module`` value without resolution).

    For ``ImportFrom`` nodes with named aliases (``from pkg import sub``),
    the resolved base module **and** each qualified alias
    (``pkg.sub``) are added as candidates.  This ensures that a bare
    ``ImportFrom`` such as ``from dnd_assistant import storage`` is
    detectable as ``dnd_assistant.storage`` by prefix-based boundary
    checks.  ``from package import *`` produces only the base module
    (no meaningless ``package.*`` candidate).

    Parameters
    ----------
    source:
        Python source text to parse.
    module_path:
        Fully-qualified module path for resolving relative imports
        (e.g. ``"dnd_assistant.retrieval.service"``).

    Returns
    -------
    Set of imported module paths (absolute when *module_path* is given).
    """
    tree = ast.parse(source)
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # Relative import
                if module_path is not None:
                    resolved = _resolve_relative_import(module_path, node.level, node.module)
                    result.add(resolved)
                    _add_qualified_aliases(result, resolved, node)
                elif node.module:
                    result.add(node.module)
            elif node.module:
                result.add(node.module)
                _add_qualified_aliases(result, node.module, node)
    return result


def _add_qualified_aliases(result: set[str], base_module: str, node: ast.ImportFrom) -> None:
    """For each named alias in an ``ImportFrom`` node, add a qualified
    ``base_module.alias_name`` candidate to *result*.

    ``from package import *`` produces no aliases and is silently skipped.
    """
    for alias in node.names:
        if alias.name == "*":
            continue
        result.add(f"{base_module}.{alias.name}")


def _has_forbidden_prefix(module: str, forbidden_prefixes: set[str]) -> bool:
    """Check if *module* matches any prefix in *forbidden_prefixes*.

    Semantics: ``module == prefix or module.startswith(prefix + ".")``
    for any prefix in *forbidden_prefixes*.
    """
    for prefix in forbidden_prefixes:
        if module == prefix or module.startswith(prefix + "."):
            return True
    return False


class TestBoundaries:
    """Verify architectural boundaries are preserved.

    Uses two complementary techniques:
    1. ``sys.modules`` inspection after clean import — catches runtime
       transitive imports.
    2. AST-based source inspection of import statements — catches
       ``TYPE_CHECKING``-guarded imports and is independent of
       ``sys.modules`` contamination.
    """

    # ── sys.modules-based checks ─────────────────────────────────────────

    def _clean_import(self, module_path: str) -> None:
        """Import a module from a clean sys.modules state."""
        import importlib
        import sys

        for key in list(sys.modules):
            if key.startswith("dnd_assistant"):
                del sys.modules[key]
        importlib.import_module(module_path)

    def _assert_no_modules_loaded(
        self, module_path: str, forbidden_prefix: str, label: str
    ) -> None:
        import sys

        self._clean_import(module_path)
        loaded = {m for m in sys.modules if m.startswith(forbidden_prefix)}
        assert not loaded, f"{module_path} triggered {label} imports: {loaded}"

    def test_retrieval_does_not_import_storage(self) -> None:
        self._assert_no_modules_loaded(
            "dnd_assistant.retrieval",
            "dnd_assistant.storage",
            "storage",
        )

    def test_retrieval_does_not_import_models(self) -> None:
        self._assert_no_modules_loaded(
            "dnd_assistant.retrieval",
            "dnd_assistant.models",
            "models",
        )

    def test_retrieval_does_not_import_tools(self) -> None:
        self._assert_no_modules_loaded(
            "dnd_assistant.retrieval",
            "dnd_assistant.tools",
            "tools",
        )

    def test_retrieval_does_not_import_application(self) -> None:
        self._assert_no_modules_loaded(
            "dnd_assistant.retrieval",
            "dnd_assistant.application",
            "application",
        )

    def test_retrieval_does_not_import_session_runtime(self) -> None:
        self._assert_no_modules_loaded(
            "dnd_assistant.retrieval",
            "dnd_assistant.session",
            "session",
        )

    def test_retrieval_does_not_import_ollama(self) -> None:
        self._assert_no_modules_loaded(
            "dnd_assistant.retrieval",
            "ollama",
            "ollama",
        )

    # ── AST-based source inspection ──────────────────────────────────────

    @staticmethod
    def _ast_imports(module_path: str) -> set[str]:
        """Return the set of full imported module paths
        found via AST in the given module's source file.

        Inspects all syntactically present import nodes (including
        ``TYPE_CHECKING`` blocks, functions, classes, and conditional
        branches) via ``ast.walk()``.

        Relative imports are resolved to absolute module paths using
        *module_path* as the context.

        ``ImportFrom`` aliases are qualified: ``from pkg import sub``
        produces both ``pkg`` and ``pkg.sub`` as candidates.

        Examples
        --------
        ``import sqlite3`` → ``{"sqlite3"}``
        ``import dnd_assistant.storage.types`` → ``{"dnd_assistant.storage.types"}``
        ``from dnd_assistant.storage import VaultRepository`` → ``{"dnd_assistant.storage", "dnd_assistant.storage.VaultRepository"}``
        ``from .types import SearchHit`` → ``{"dnd_assistant.retrieval.types", "dnd_assistant.retrieval.types.SearchHit"}``
        """
        import importlib

        mod = importlib.import_module(module_path)
        assert mod.__file__ is not None
        with open(mod.__file__, encoding="utf-8") as f:
            source = f.read()

        return _parse_imports_from_source(source, module_path=module_path)

    def test_retrieval_types_no_forbidden_imports(self) -> None:
        imports = self._ast_imports("dnd_assistant.retrieval.types")
        forbidden = {
            "dnd_assistant.storage",
            "dnd_assistant.models",
            "dnd_assistant.tools",
            "dnd_assistant.application",
            "ollama",
        }
        actual = {i for i in imports if _has_forbidden_prefix(i, forbidden)}
        assert not actual, f"retrieval/types.py imports forbidden modules: {actual}"

    def test_retrieval_service_no_forbidden_imports(self) -> None:
        imports = self._ast_imports("dnd_assistant.retrieval.service")
        forbidden = {
            "dnd_assistant.storage",
            "dnd_assistant.models",
            "dnd_assistant.tools",
            "dnd_assistant.application",
            "ollama",
        }
        actual = {i for i in imports if _has_forbidden_prefix(i, forbidden)}
        assert not actual, f"retrieval/service.py imports forbidden modules: {actual}"

    def test_no_sqlite_import_in_retrieval(self) -> None:
        imports = self._ast_imports("dnd_assistant.retrieval.types")
        imports |= self._ast_imports("dnd_assistant.retrieval.service")
        assert "sqlite3" not in imports, "retrieval imports sqlite3"
        # Also check no 'sqlite' appears in import strings
        assert not any("sqlite" in i for i in imports), (
            f"retrieval imports sqlite-related module: {imports}"
        )

    def test_no_rapidfuzz_import_in_retrieval(self) -> None:
        imports = self._ast_imports("dnd_assistant.retrieval.types")
        imports |= self._ast_imports("dnd_assistant.retrieval.service")
        assert "rapidfuzz" not in imports, "retrieval imports rapidfuzz"

    # ── Reverse-boundary protection ──────────────────────────────────────

    def test_domain_does_not_import_retrieval(self) -> None:
        self._assert_no_modules_loaded(
            "dnd_assistant.domain",
            "dnd_assistant.retrieval",
            "retrieval",
        )

    def test_storage_does_not_import_retrieval(self) -> None:
        self._assert_no_modules_loaded(
            "dnd_assistant.storage",
            "dnd_assistant.retrieval",
            "retrieval",
        )


class TestAstImportChecker:
    """Regression tests for the AST-based import checker itself.

    These tests verify that ``_ast_imports`` preserves full dotted paths
    and that ``_has_forbidden_prefix`` correctly detects forbidden imports.
    They use synthetic source text rather than production module files.
    """

    @staticmethod
    def _parse_imports(source: str) -> set[str]:
        """Parse *source* as Python code and return the set of full
        imported module paths.

        Delegates to the module-level ``_parse_imports_from_source``
        without a *module_path*, so relative imports are collected
        as-is (not resolved).
        """
        return _parse_imports_from_source(source)

    @staticmethod
    def _has_forbidden_prefix(module: str, forbidden_prefixes: set[str]) -> bool:
        """Check if *module* matches any prefix in *forbidden_prefixes*.

        Delegates to the module-level ``_has_forbidden_prefix``.
        """
        return _has_forbidden_prefix(module, forbidden_prefixes)

    # ── Full dotted paths preserved ──────────────────────────────────────

    def test_import_sqlite3(self) -> None:
        imports = self._parse_imports("import sqlite3")
        assert imports == {"sqlite3"}

    def test_import_dotted_storage_types(self) -> None:
        imports = self._parse_imports("import dnd_assistant.storage.types")
        assert imports == {"dnd_assistant.storage.types"}

    def test_from_import_storage(self) -> None:
        imports = self._parse_imports("from dnd_assistant.storage import VaultRepository")
        assert imports == {
            "dnd_assistant.storage",
            "dnd_assistant.storage.VaultRepository",
        }

    def test_from_import_models_gateway(self) -> None:
        imports = self._parse_imports("from dnd_assistant.models.gateway import ModelGateway")
        assert imports == {
            "dnd_assistant.models.gateway",
            "dnd_assistant.models.gateway.ModelGateway",
        }

    def test_import_rapidfuzz(self) -> None:
        imports = self._parse_imports("import rapidfuzz.fuzz")
        assert imports == {"rapidfuzz.fuzz"}

    def test_import_tools_registry(self) -> None:
        imports = self._parse_imports("import dnd_assistant.tools.registry")
        assert imports == {"dnd_assistant.tools.registry"}

    # ── Forbidden-prefix detection ───────────────────────────────────────

    def test_detect_storage_from_import(self) -> None:
        """from dnd_assistant.storage import VaultRepository is detected."""
        imports = self._parse_imports("from dnd_assistant.storage import VaultRepository")
        forbidden = {"dnd_assistant.storage"}
        actual = {i for i in imports if self._has_forbidden_prefix(i, forbidden)}
        assert actual == {
            "dnd_assistant.storage",
            "dnd_assistant.storage.VaultRepository",
        }

    def test_detect_storage_subpackage_import(self) -> None:
        """import dnd_assistant.storage.types is detected."""
        imports = self._parse_imports("import dnd_assistant.storage.types")
        forbidden = {"dnd_assistant.storage"}
        actual = {i for i in imports if self._has_forbidden_prefix(i, forbidden)}
        assert actual == {"dnd_assistant.storage.types"}

    def test_detect_models_gateway_from_import(self) -> None:
        """from dnd_assistant.models.gateway import ModelGateway is detected."""
        imports = self._parse_imports("from dnd_assistant.models.gateway import ModelGateway")
        forbidden = {"dnd_assistant.models"}
        actual = {i for i in imports if self._has_forbidden_prefix(i, forbidden)}
        assert actual == {
            "dnd_assistant.models.gateway",
            "dnd_assistant.models.gateway.ModelGateway",
        }

    def test_detect_tools_registry_import(self) -> None:
        """import dnd_assistant.tools.registry is detected."""
        imports = self._parse_imports("import dnd_assistant.tools.registry")
        forbidden = {"dnd_assistant.tools"}
        actual = {i for i in imports if self._has_forbidden_prefix(i, forbidden)}
        assert actual == {"dnd_assistant.tools.registry"}

    def test_detect_sqlite3_import(self) -> None:
        imports = self._parse_imports("import sqlite3")
        forbidden = {"sqlite3"}
        actual = {i for i in imports if self._has_forbidden_prefix(i, forbidden)}
        assert actual == {"sqlite3"}

    def test_detect_rapidfuzz_import(self) -> None:
        imports = self._parse_imports("from rapidfuzz import fuzz")
        forbidden = {"rapidfuzz"}
        actual = {i for i in imports if self._has_forbidden_prefix(i, forbidden)}
        assert actual == {"rapidfuzz", "rapidfuzz.fuzz"}

    # ── ImportFrom alias gap regression (S5-C03) ─────────────────────────
    #
    # ``from dnd_assistant import storage`` must produce
    # ``dnd_assistant.storage`` as a detectable candidate.
    # The old code only recorded ``node.module`` (``dnd_assistant``)
    # and did not qualify alias names.

    def test_absolute_alias_storage_detected(self) -> None:
        """``from dnd_assistant import storage`` must be detectable."""
        imports = self._parse_imports("from dnd_assistant import storage")
        assert "dnd_assistant.storage" in imports
        forbidden = {"dnd_assistant.storage"}
        actual = {i for i in imports if self._has_forbidden_prefix(i, forbidden)}
        assert "dnd_assistant.storage" in actual

    def test_absolute_alias_models_detected(self) -> None:
        """``from dnd_assistant import models`` must be detectable."""
        imports = self._parse_imports("from dnd_assistant import models")
        assert "dnd_assistant.models" in imports
        forbidden = {"dnd_assistant.models"}
        actual = {i for i in imports if self._has_forbidden_prefix(i, forbidden)}
        assert "dnd_assistant.models" in actual

    def test_absolute_alias_tools_detected(self) -> None:
        """``from dnd_assistant import tools`` must be detectable."""
        imports = self._parse_imports("from dnd_assistant import tools")
        assert "dnd_assistant.tools" in imports
        forbidden = {"dnd_assistant.tools"}
        actual = {i for i in imports if self._has_forbidden_prefix(i, forbidden)}
        assert "dnd_assistant.tools" in actual

    def test_relative_alias_storage_detected(self) -> None:
        """``from .. import storage`` in retrieval/service context
        must produce ``dnd_assistant.storage``.
        """
        imports = _parse_imports_from_source(
            "from .. import storage",
            module_path="dnd_assistant.retrieval.service",
        )
        assert "dnd_assistant.storage" in imports
        forbidden = {"dnd_assistant.storage"}
        actual = {i for i in imports if _has_forbidden_prefix(i, forbidden)}
        assert "dnd_assistant.storage" in actual

    def test_relative_alias_models_detected(self) -> None:
        """``from .. import models`` in retrieval/service context
        must produce ``dnd_assistant.models``.
        """
        imports = _parse_imports_from_source(
            "from .. import models",
            module_path="dnd_assistant.retrieval.service",
        )
        assert "dnd_assistant.models" in imports
        forbidden = {"dnd_assistant.models"}
        actual = {i for i in imports if _has_forbidden_prefix(i, forbidden)}
        assert "dnd_assistant.models" in actual

    def test_relative_alias_tools_detected(self) -> None:
        """``from .. import tools`` in retrieval/service context
        must produce ``dnd_assistant.tools``.
        """
        imports = _parse_imports_from_source(
            "from .. import tools",
            module_path="dnd_assistant.retrieval.service",
        )
        assert "dnd_assistant.tools" in imports
        forbidden = {"dnd_assistant.tools"}
        actual = {i for i in imports if _has_forbidden_prefix(i, forbidden)}
        assert "dnd_assistant.tools" in actual

    def test_absolute_alias_domain_allowed(self) -> None:
        """``from dnd_assistant import domain`` is NOT a forbidden
        import for retrieval contracts.
        """
        imports = self._parse_imports("from dnd_assistant import domain")
        assert "dnd_assistant.domain" in imports
        forbidden = {
            "dnd_assistant.storage",
            "dnd_assistant.models",
            "dnd_assistant.tools",
            "dnd_assistant.application",
        }
        actual = {i for i in imports if self._has_forbidden_prefix(i, forbidden)}
        assert not actual

    def test_relative_dot_types_allowed(self) -> None:
        """``from . import types`` in retrieval/service context
        resolves to ``dnd_assistant.retrieval.types`` and is NOT rejected.
        """
        imports = _parse_imports_from_source(
            "from . import types",
            module_path="dnd_assistant.retrieval.service",
        )
        assert "dnd_assistant.retrieval.types" in imports
        forbidden = {
            "dnd_assistant.storage",
            "dnd_assistant.models",
            "dnd_assistant.tools",
            "dnd_assistant.application",
        }
        actual = {i for i in imports if _has_forbidden_prefix(i, forbidden)}
        assert not actual

    def test_star_import_no_alias_candidate(self) -> None:
        """``from package import *`` must NOT produce a meaningless
        ``package.*`` candidate.
        """
        imports = self._parse_imports("from dnd_assistant import *")
        assert "dnd_assistant" in imports
        assert "dnd_assistant.*" not in imports

    # ── Allowed imports not falsely rejected ─────────────────────────────

    def test_allowed_domain_import_not_falsely_rejected(self) -> None:
        imports = self._parse_imports("from dnd_assistant.domain.types import EntityId")
        assert "dnd_assistant.domain.types" in imports
        assert "dnd_assistant.domain.types.EntityId" in imports
        forbidden = {
            "dnd_assistant.storage",
            "dnd_assistant.models",
            "dnd_assistant.tools",
            "dnd_assistant.application",
        }
        actual = {i for i in imports if self._has_forbidden_prefix(i, forbidden)}
        assert not actual

    def test_allowed_retrieval_import_not_falsely_rejected(self) -> None:
        imports = self._parse_imports("from dnd_assistant.retrieval.types import SearchHit")
        assert "dnd_assistant.retrieval.types" in imports
        assert "dnd_assistant.retrieval.types.SearchHit" in imports
        forbidden = {
            "dnd_assistant.storage",
            "dnd_assistant.models",
            "dnd_assistant.tools",
            "dnd_assistant.application",
        }
        actual = {i for i in imports if self._has_forbidden_prefix(i, forbidden)}
        assert not actual

    # ── Regression: split(".")[0] would miss these ──────────────────────

    def test_regression_buggy_split_dot_zero_detects_storage(self) -> None:
        """Prove that the old ``split(\".\")[0]`` behaviour would NOT detect
        ``from dnd_assistant.storage import ...`` because it collapses to
        ``dnd_assistant``, but the corrected full-path logic does detect it.
        """
        imports = self._parse_imports("from dnd_assistant.storage import VaultRepository")
        # Old buggy behaviour would produce {"dnd_assistant"}
        old_buggy = {name.split(".")[0] for name in imports}
        assert old_buggy == {"dnd_assistant"}
        assert "storage" not in old_buggy  # old code missed it

        # Correct behaviour
        forbidden = {"dnd_assistant.storage"}
        actual = {i for i in imports if self._has_forbidden_prefix(i, forbidden)}
        assert actual == {
            "dnd_assistant.storage",
            "dnd_assistant.storage.VaultRepository",
        }

    def test_regression_buggy_split_dot_zero_detects_models(self) -> None:
        """Same regression proof for models import."""
        imports = self._parse_imports("from dnd_assistant.models.gateway import ModelGateway")
        old_buggy = {name.split(".")[0] for name in imports}
        assert old_buggy == {"dnd_assistant"}
        assert "models" not in old_buggy

        forbidden = {"dnd_assistant.models"}
        actual = {i for i in imports if self._has_forbidden_prefix(i, forbidden)}
        assert actual == {
            "dnd_assistant.models.gateway",
            "dnd_assistant.models.gateway.ModelGateway",
        }

    def test_regression_buggy_split_dot_zero_detects_tools(self) -> None:
        """Same regression proof for tools import."""
        imports = self._parse_imports("import dnd_assistant.tools.registry")
        old_buggy = {name.split(".")[0] for name in imports}
        assert old_buggy == {"dnd_assistant"}
        assert "tools" not in old_buggy

        forbidden = {"dnd_assistant.tools"}
        actual = {i for i in imports if self._has_forbidden_prefix(i, forbidden)}
        assert actual == {"dnd_assistant.tools.registry"}

    # ── Relative-import resolution ────────────────────────────────────────

    def test_relative_retrieval_types_allowed(self) -> None:
        """``from .types import SearchHit`` in retrieval/service context
        resolves to ``dnd_assistant.retrieval.types`` and is NOT rejected.
        """
        imports = _parse_imports_from_source(
            "from .types import SearchHit",
            module_path="dnd_assistant.retrieval.service",
        )
        assert imports == {
            "dnd_assistant.retrieval.types",
            "dnd_assistant.retrieval.types.SearchHit",
        }
        forbidden = {
            "dnd_assistant.storage",
            "dnd_assistant.models",
            "dnd_assistant.tools",
            "dnd_assistant.application",
        }
        actual = {i for i in imports if _has_forbidden_prefix(i, forbidden)}
        assert not actual

    def test_relative_domain_import_allowed(self) -> None:
        """``from ..domain.types import EntityId`` in retrieval/service
        context resolves to ``dnd_assistant.domain.types`` and is NOT
        rejected by the S5-00 forbidden set.
        """
        imports = _parse_imports_from_source(
            "from ..domain.types import EntityId",
            module_path="dnd_assistant.retrieval.service",
        )
        assert imports == {
            "dnd_assistant.domain.types",
            "dnd_assistant.domain.types.EntityId",
        }
        forbidden = {
            "dnd_assistant.storage",
            "dnd_assistant.models",
            "dnd_assistant.tools",
            "dnd_assistant.application",
        }
        actual = {i for i in imports if _has_forbidden_prefix(i, forbidden)}
        assert not actual

    def test_relative_storage_import_detected(self) -> None:
        """``from ..storage import VaultRepository`` in retrieval/service
        context resolves to ``dnd_assistant.storage`` and MUST be detected.
        """
        imports = _parse_imports_from_source(
            "from ..storage import VaultRepository",
            module_path="dnd_assistant.retrieval.service",
        )
        assert imports == {
            "dnd_assistant.storage",
            "dnd_assistant.storage.VaultRepository",
        }
        forbidden = {"dnd_assistant.storage"}
        actual = {i for i in imports if _has_forbidden_prefix(i, forbidden)}
        assert actual == {
            "dnd_assistant.storage",
            "dnd_assistant.storage.VaultRepository",
        }

    def test_relative_models_import_detected(self) -> None:
        """``from ..models.gateway import ModelGateway`` in retrieval/service
        context resolves to ``dnd_assistant.models.gateway`` and MUST be
        detected.
        """
        imports = _parse_imports_from_source(
            "from ..models.gateway import ModelGateway",
            module_path="dnd_assistant.retrieval.service",
        )
        assert imports == {
            "dnd_assistant.models.gateway",
            "dnd_assistant.models.gateway.ModelGateway",
        }
        forbidden = {"dnd_assistant.models"}
        actual = {i for i in imports if _has_forbidden_prefix(i, forbidden)}
        assert actual == {
            "dnd_assistant.models.gateway",
            "dnd_assistant.models.gateway.ModelGateway",
        }

    def test_relative_tools_import_detected(self) -> None:
        """``from ..tools.registry import ToolRegistry`` in retrieval/service
        context resolves to ``dnd_assistant.tools.registry`` and MUST be
        detected.
        """
        imports = _parse_imports_from_source(
            "from ..tools.registry import ToolRegistry",
            module_path="dnd_assistant.retrieval.service",
        )
        assert imports == {
            "dnd_assistant.tools.registry",
            "dnd_assistant.tools.registry.ToolRegistry",
        }
        forbidden = {"dnd_assistant.tools"}
        actual = {i for i in imports if _has_forbidden_prefix(i, forbidden)}
        assert actual == {
            "dnd_assistant.tools.registry",
            "dnd_assistant.tools.registry.ToolRegistry",
        }

    # ── Regression: previous S5-C01 ignored node.level ────────────────────

    def test_regression_old_code_missed_relative_storage(self) -> None:
        """Prove that the old S5-C01 implementation (which ignored
        ``node.level`` and only collected ``node.module``) would
        represent ``from ..storage import VaultRepository`` as
        ``\"storage\"`` (not ``\"dnd_assistant.storage\"``) and therefore
        bypass the ``\"dnd_assistant.storage\"`` prefix check.
        """
        # Old behaviour: just collect node.module, ignore node.level
        old_imports = _parse_imports_from_source(
            "from ..storage import VaultRepository",
            # No module_path → relative imports collected as-is
        )
        assert old_imports == {"storage"}
        assert "dnd_assistant.storage" not in old_imports

        # Correct behaviour with module_path
        resolved = _parse_imports_from_source(
            "from ..storage import VaultRepository",
            module_path="dnd_assistant.retrieval.service",
        )
        assert resolved == {
            "dnd_assistant.storage",
            "dnd_assistant.storage.VaultRepository",
        }
        forbidden = {"dnd_assistant.storage"}
        actual = {i for i in resolved if _has_forbidden_prefix(i, forbidden)}
        assert actual == {
            "dnd_assistant.storage",
            "dnd_assistant.storage.VaultRepository",
        }

    def test_regression_old_code_missed_relative_models(self) -> None:
        """Same regression proof for relative models import."""
        old_imports = _parse_imports_from_source(
            "from ..models.gateway import ModelGateway",
        )
        assert old_imports == {"models.gateway"}
        assert "dnd_assistant.models" not in old_imports

        resolved = _parse_imports_from_source(
            "from ..models.gateway import ModelGateway",
            module_path="dnd_assistant.retrieval.service",
        )
        assert resolved == {
            "dnd_assistant.models.gateway",
            "dnd_assistant.models.gateway.ModelGateway",
        }
        forbidden = {"dnd_assistant.models"}
        actual = {i for i in resolved if _has_forbidden_prefix(i, forbidden)}
        assert actual == {
            "dnd_assistant.models.gateway",
            "dnd_assistant.models.gateway.ModelGateway",
        }
