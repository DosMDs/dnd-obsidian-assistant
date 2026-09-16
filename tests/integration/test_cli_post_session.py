"""S11-07 CLI post-session integration tests against a real temporary Vault.

Exercises the full CLI path -- selector -> POST_SESSION profile load -> real
Obsidian stores -> S11-06 processor -> a deterministic fake Pydantic AI model
(``FunctionModel``) -> immutable artifacts -> optional Stage-10 proposal ->
CLI output.  No live Ollama, no network.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import openai
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from typer.testing import CliRunner

from dnd_assistant.application.post_session_attempt_state import (
    AttemptState,
    fold_attempt_state,
)
from dnd_assistant.application.post_session_context import build_post_session_input
from dnd_assistant.application.post_session_eligibility import (
    evaluate_processing_eligibility,
)
from dnd_assistant.application.post_session_ledger import (
    load_ledger_events,
    new_ledger_event_id,
    record_ledger_event,
)
from dnd_assistant.application.post_session_persistence import (
    EMPTY_RECAP_ARTIFACT_TEXT,
)
from dnd_assistant.cli.main import app
from dnd_assistant.domain.post_session import (
    AttemptFailed,
    AttemptStarted,
    PersistedArtifactKind,
)
from dnd_assistant.domain.post_session_artifacts import (
    POST_SESSION_RENDER_SCHEMA_VERSION,
    PostSessionRenderOutput,
)
from dnd_assistant.domain.post_session_extraction import PostSessionExtraction
from dnd_assistant.domain.types import EntityType
from dnd_assistant.storage.audit import AuditRecord, AuditService
from dnd_assistant.storage.post_session_artifacts import ObsidianPostSessionArtifactStore
from dnd_assistant.storage.post_session_processing import ObsidianPostSessionProcessingStore
from dnd_assistant.storage.session_events import ObsidianSessionEventRepository
from dnd_assistant.storage.session_metadata import ObsidianSessionMetadataRepository
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository
from tests.integration.test_post_session_context import _build_vault
from tests.unit.post_session.extraction_helpers import (
    make_claim,
    make_extraction,
    make_mention,
)
from tests.unit.post_session.helpers import (
    BASE_END,
    BASE_START,
    make_audit_context,
    make_session,
    make_vault,
)

runner = CliRunner()

_ENTITY_DIRS = ("Characters", "Locations", "Quests", "Items")
PRODUCED_ATTEMPT = "att_" + "a" * 32
NO_CHANGES_ATTEMPT = "att_" + "b" * 32


# ── Helpers ────────────────────────────────────────────────────────────────


def _write_config(tmp_path: Path, *, role: str = "post_session", provider: str = "ollama") -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        "[profiles.ps]\n"
        f"provider='{provider}'\n"
        "model='post-session-model'\n"
        "base_url='http://localhost:11434'\n"
        f"role='{role}'\n",
        encoding="utf-8",
    )
    return path


def _canonical_snapshot(root: Path) -> dict[str, bytes]:
    """Entity files + S001 metadata only (excludes workflow/change artifacts)."""
    result: dict[str, bytes] = {}
    for base in _ENTITY_DIRS:
        directory = root / base
        if directory.exists():
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    result[path.relative_to(root).as_posix()] = path.read_bytes()
    meta = root / "_system" / "raw" / "sessions" / "S001" / "metadata.json"
    result["metadata.json"] = meta.read_bytes()
    return result


def _append_extraction(root: Path, audit: AuditService) -> PostSessionExtraction:
    events = ObsidianSessionEventRepository(root, audit).list_events("S001")
    event_id = events[0].event_id
    return make_extraction(
        claims=(
            make_claim(
                text="Aria gained a new scar.",
                evidence_event_ids=(event_id,),
                entity_mentions=(
                    make_mention(
                        text="Aria",
                        candidate_entity_id="npc-aria",
                        entity_type=EntityType.NPC,
                        evidence_event_ids=(event_id,),
                    ),
                ),
            ),
        )
    )


class ScriptedPostSessionModel:
    """Deterministic Pydantic AI model dispatching on the output schema."""

    def __init__(
        self,
        *,
        extraction: PostSessionExtraction | None = None,
        render_body: str = "# Summary\n\nBody.",
        extraction_error: BaseException | None = None,
        render_error: BaseException | None = None,
    ) -> None:
        self._extraction = extraction
        self._render_body = render_body
        self._extraction_error = extraction_error
        self._render_error = render_error
        self.extraction_calls = 0
        self.render_calls = 0
        self._model = FunctionModel(self._respond)

    def _respond(self, messages: list[Any], info: AgentInfo) -> ModelResponse:
        output_tool = info.output_tools[0]
        properties = output_tool.parameters_json_schema.get("properties", {})
        if "claims" in properties:
            self.extraction_calls += 1
            if self._extraction_error is not None:
                raise self._extraction_error
            assert self._extraction is not None
            return ModelResponse(
                parts=[ToolCallPart(output_tool.name, self._extraction.model_dump(mode="json"))]
            )
        self.render_calls += 1
        if self._render_error is not None:
            raise self._render_error
        output = PostSessionRenderOutput(
            schema_version=POST_SESSION_RENDER_SCHEMA_VERSION,
            body=self._render_body,
        )
        return ModelResponse(parts=[ToolCallPart(output_tool.name, output.model_dump(mode="json"))])

    def build(self) -> FunctionModel:
        return self._model


def _invoke_process(
    root: Path,
    config: Path,
    model: ScriptedPostSessionModel | MagicMock,
    *,
    args: list[str] | None = None,
    attempt_id: str | None = None,
) -> Any:
    model_value = model.build() if isinstance(model, ScriptedPostSessionModel) else model
    patches = [
        patch(
            "dnd_assistant.cli.post_session_runtime._build_post_session_model",
            return_value=model_value,
        )
    ]
    if attempt_id is not None:
        patches.append(
            patch(
                "dnd_assistant.cli.post_session.new_attempt_id",
                return_value=attempt_id,
            )
        )
    for patcher in patches:
        patcher.start()
    try:
        return runner.invoke(
            app,
            [
                "session",
                "process",
                *(args or []),
                "--vault",
                str(root),
                "--config",
                str(config),
                "--profile",
                "ps",
            ],
        )
    finally:
        for patcher in patches:
            patcher.stop()


def _invoke_outputs(root: Path, session_id: str = "S001") -> Any:
    return runner.invoke(app, ["session", "outputs", session_id, "--vault", str(root)])


def _add_completed_session(
    root: Path,
    audit: AuditService,
    session_id: str,
    finish: Any,
    *,
    touched: tuple[str, ...] = ("npc-aria",),
) -> None:
    repo = ObsidianSessionMetadataRepository(root, audit)
    repo.create_session(
        make_session(session_id=session_id, status="active"),
        audit=make_audit_context(operation_id=f"{session_id}-start", real_time=BASE_START),
    )
    repo.close_session(
        session_id,
        expected_revision=1,
        world_tick_end=200,
        touched_entity_ids=list(touched),
        audit=make_audit_context(operation_id=f"{session_id}-end", real_time=finish),
    )


def _audit_path(root: Path) -> Path:
    return root / "_system" / "audit" / "audit.jsonl"


# ── Produced / no_changes / EMPTY ──────────────────────────────────────────


class TestProduced:
    def test_produced_is_proposal_only_and_mutates_nothing(self, tmp_path: Path) -> None:
        root, audit, _ = _build_vault(tmp_path)
        config = _write_config(tmp_path)
        model = ScriptedPostSessionModel(extraction=_append_extraction(root, audit))
        canonical_before = _canonical_snapshot(root)
        audit_before = audit.read_all()

        result = _invoke_process(root, config, model, args=["S001"], attempt_id=PRODUCED_ATTEMPT)

        assert result.exit_code == 0
        assert f"cs_S001_{PRODUCED_ATTEMPT}" in result.stdout
        assert "ТОЛЬКО предложение" in result.stdout
        assert f"dnd changeset review cs_S001_{PRODUCED_ATTEMPT}" in result.stdout
        assert model.extraction_calls == 1
        assert model.render_calls == 1

        proposal = root / "_system" / "changesets" / f"cs_S001_{PRODUCED_ATTEMPT}.proposal.json"
        assert proposal.is_file()
        assert not (
            root / "_system" / "changesets" / f"cs_S001_{PRODUCED_ATTEMPT}.approval.json"
        ).exists()
        assert not (
            root / "_system" / "changesets" / f"cs_S001_{PRODUCED_ATTEMPT}.apply.jsonl"
        ).exists()
        assert _canonical_snapshot(root) == canonical_before
        assert audit.read_all() == audit_before


class TestNoChanges:
    def test_no_changes_keeps_artifacts_and_creates_no_proposal(self, tmp_path: Path) -> None:
        root, audit, _ = _build_vault(tmp_path)
        config = _write_config(tmp_path)
        model = ScriptedPostSessionModel(extraction=make_extraction())
        canonical_before = _canonical_snapshot(root)

        result = _invoke_process(root, config, model, args=["S001"], attempt_id=NO_CHANGES_ATTEMPT)

        assert result.exit_code == 0
        assert "ChangeSet не создан" in result.stdout
        assert "Сущности кампании не изменялись" in result.stdout
        assert not (root / "_system" / "changesets").exists()
        assert _canonical_snapshot(root) == canonical_before

        store = ObsidianPostSessionArtifactStore(root)
        for kind in PersistedArtifactKind:
            assert store.artifact_exists("S001", NO_CHANGES_ATTEMPT, kind)

    def test_empty_recap_reported_without_reading_body(self, tmp_path: Path) -> None:
        root, audit, _ = _build_vault(tmp_path)
        config = _write_config(tmp_path)
        model = ScriptedPostSessionModel(extraction=make_extraction())

        result = _invoke_process(root, config, model, args=["S001"], attempt_id=NO_CHANGES_ATTEMPT)

        assert result.exit_code == 0
        assert "Recap пуст (детерминированно): да" in result.stdout
        assert EMPTY_RECAP_ARTIFACT_TEXT not in result.stdout
        store = ObsidianPostSessionArtifactStore(root)
        recap_path = store.expected_relative_path(
            "S001", NO_CHANGES_ATTEMPT, PersistedArtifactKind.RECAP
        )
        assert (root / recap_path).is_file()


# ── Selector / resolution: zero model work ─────────────────────────────────


class TestZeroModelWork:
    def test_missing_explicit_session_does_not_build_model(self, tmp_path: Path) -> None:
        root, _audit_service, _ = _build_vault(tmp_path)
        config = _write_config(tmp_path)
        factory = MagicMock()

        with patch("dnd_assistant.cli.post_session_runtime._build_post_session_model", factory):
            result = runner.invoke(
                app,
                [
                    "session",
                    "process",
                    "S999",
                    "--vault",
                    str(root),
                    "--config",
                    str(config),
                    "--profile",
                    "ps",
                ],
            )

        assert result.exit_code == 1
        factory.assert_not_called()
        assert not (root / "_system" / "raw" / "sessions" / "S999").exists()

    def test_no_latest_candidate_does_not_build_model(self, tmp_path: Path) -> None:
        root = make_vault(tmp_path)
        audit = AuditService(_audit_path(root))
        # Only an active (non-completed) session exists.
        ObsidianSessionMetadataRepository(root, audit).create_session(
            make_session(session_id="S001", status="active"),
            audit=make_audit_context(operation_id="S001-start"),
        )
        config = _write_config(tmp_path)
        factory = MagicMock()

        with patch("dnd_assistant.cli.post_session_runtime._build_post_session_model", factory):
            result = runner.invoke(
                app,
                [
                    "session",
                    "process",
                    "--latest",
                    "--vault",
                    str(root),
                    "--config",
                    str(config),
                    "--profile",
                    "ps",
                ],
            )

        assert result.exit_code == 1
        factory.assert_not_called()

    def test_wrong_role_profile_does_not_build_model(self, tmp_path: Path) -> None:
        root, _audit_service, _ = _build_vault(tmp_path)
        config = _write_config(tmp_path, role="agent")
        factory = MagicMock()

        with patch("dnd_assistant.cli.post_session_runtime._build_post_session_model", factory):
            result = runner.invoke(
                app,
                [
                    "session",
                    "process",
                    "S001",
                    "--vault",
                    str(root),
                    "--config",
                    str(config),
                    "--profile",
                    "ps",
                ],
            )

        assert result.exit_code == 1
        factory.assert_not_called()
        assert not (root / "_system" / "raw" / "sessions" / "S001" / "processing").exists()

    def test_provider_construction_failure_writes_nothing(self, tmp_path: Path) -> None:
        root, _audit_service, _ = _build_vault(tmp_path)
        config = _write_config(tmp_path, provider="openai")

        result = runner.invoke(
            app,
            [
                "session",
                "process",
                "S001",
                "--vault",
                str(root),
                "--config",
                str(config),
                "--profile",
                "ps",
            ],
        )

        assert result.exit_code == 1
        assert not (root / "_system" / "raw" / "sessions" / "S001" / "processing").exists()

    def test_blocking_recovery_prevents_model_work(self, tmp_path: Path) -> None:
        root, audit, _ = _build_vault(tmp_path)
        # A genuine session-owned unresolved audit intent blocks mutations.
        ObsidianSessionMetadataRepository(root, audit).create_session(
            make_session(session_id="S003", status="active"),
            audit=make_audit_context(operation_id="S003-start"),
        )
        audit.append(
            AuditRecord(
                operation_id="genuine-op",
                real_time=BASE_END,
                session="S003",
                operation="create_entity",
                entity_id="npc-other",
                source="test",
                phase="intent",
            )
        )
        config = _write_config(tmp_path)
        factory = MagicMock()

        with patch("dnd_assistant.cli.post_session_runtime._build_post_session_model", factory):
            result = runner.invoke(
                app,
                [
                    "session",
                    "process",
                    "S001",
                    "--vault",
                    str(root),
                    "--config",
                    str(config),
                    "--profile",
                    "ps",
                ],
            )

        assert result.exit_code == 1
        assert "Обнаружено" in result.stderr
        factory.assert_not_called()
        assert not (root / "_system" / "raw" / "sessions" / "S001" / "processing").exists()


# ── Latest selection integration ───────────────────────────────────────────


class TestLatestSelectionIntegration:
    def test_latest_picks_most_recently_finished(self, tmp_path: Path) -> None:
        root, audit, _ = _build_vault(tmp_path)
        _add_completed_session(root, audit, "S002", BASE_END + timedelta(hours=1))
        config = _write_config(tmp_path)
        model = ScriptedPostSessionModel(extraction=make_extraction())

        result = _invoke_process(root, config, model, args=["--latest"])

        assert result.exit_code == 0
        assert "Обработка сессии S002 завершена" in result.stdout


# ── Failures ───────────────────────────────────────────────────────────────


class TestFailures:
    def test_extraction_provider_error_is_safe(self, tmp_path: Path) -> None:
        root, audit, _ = _build_vault(tmp_path)
        config = _write_config(tmp_path)
        error = ModelAPIError("MODEL_SECRET_CANARY", "provider failed: MODEL_SECRET_CANARY")
        error.__cause__ = openai.APIConnectionError(request=None)  # type: ignore[arg-type]
        model = ScriptedPostSessionModel(
            extraction=_append_extraction(root, audit), extraction_error=error
        )

        result = _invoke_process(root, config, model, args=["S001"], attempt_id=PRODUCED_ATTEMPT)

        assert result.exit_code == 1
        assert "модель недоступна" in result.stdout
        assert "MODEL_SECRET_CANARY" not in result.stdout
        assert "MODEL_SECRET_CANARY" not in result.stderr

    def test_render_provider_error_is_safe(self, tmp_path: Path) -> None:
        root, audit, _ = _build_vault(tmp_path)
        config = _write_config(tmp_path)
        error = ModelAPIError("RENDER_SECRET_CANARY", "render failed: RENDER_SECRET_CANARY")
        error.__cause__ = openai.APITimeoutError(request=None)  # type: ignore[arg-type]
        model = ScriptedPostSessionModel(
            extraction=_append_extraction(root, audit), render_error=error
        )

        result = _invoke_process(root, config, model, args=["S001"], attempt_id=PRODUCED_ATTEMPT)

        assert result.exit_code == 1
        assert "таймаут модели" in result.stdout
        assert "RENDER_SECRET_CANARY" not in result.stdout
        assert "RENDER_SECRET_CANARY" not in result.stderr

    def test_claim_conflict_is_interrupted_without_model(self, tmp_path: Path) -> None:
        root, audit, _ = _build_vault(tmp_path)
        ObsidianPostSessionArtifactStore(root).claim_attempt("S001", PRODUCED_ATTEMPT)
        config = _write_config(tmp_path)
        model = ScriptedPostSessionModel(extraction=_append_extraction(root, audit))

        result = _invoke_process(root, config, model, args=["S001"], attempt_id=PRODUCED_ATTEMPT)

        assert result.exit_code == 1
        assert "не была завершена" in result.stdout
        assert model.extraction_calls == 0

    def test_failure_recording_uncertainty_is_reported(self, tmp_path: Path) -> None:
        from dnd_assistant.application.post_session_ledger import (
            record_ledger_event as real_record,
        )
        from dnd_assistant.errors import StorageError

        root, audit, _ = _build_vault(tmp_path)
        config = _write_config(tmp_path)
        error = ModelAPIError("boom", "failed")
        error.__cause__ = openai.APIConnectionError(request=None)  # type: ignore[arg-type]
        model = ScriptedPostSessionModel(
            extraction=_append_extraction(root, audit), extraction_error=error
        )

        def _boom(store: Any, session_id: str, event: Any) -> Any:
            if isinstance(event, AttemptFailed):
                raise StorageError("ledger append failed")
            return real_record(store, session_id, event)

        with patch(
            "dnd_assistant.application.post_session_processor_support.record_ledger_event",
            side_effect=_boom,
        ):
            result = _invoke_process(
                root, config, model, args=["S001"], attempt_id=PRODUCED_ATTEMPT
            )

        assert result.exit_code == 1
        assert "не удалось надёжно сохранить" in result.stderr
        assert PRODUCED_ATTEMPT in result.stderr

        store = ObsidianPostSessionProcessingStore(root)
        fold = fold_attempt_state(load_ledger_events(store, "S001"), PRODUCED_ATTEMPT)
        assert fold.state is AttemptState.STARTED


# ── `session outputs` integrity behavior ───────────────────────────────────


def _run_no_changes(root: Path, config: Path, attempt_id: str = NO_CHANGES_ATTEMPT) -> None:
    model = ScriptedPostSessionModel(extraction=make_extraction())
    result = _invoke_process(root, config, model, args=["S001"], attempt_id=attempt_id)
    assert result.exit_code == 0


class TestSessionOutputs:
    def test_verified_completed_renders_normally(self, tmp_path: Path) -> None:
        root, _audit_service, _ = _build_vault(tmp_path)
        config = _write_config(tmp_path)
        _run_no_changes(root, config)

        result = _invoke_outputs(root, "S001")

        assert result.exit_code == 0
        assert "Проверка терминальных доказательств: подтверждена" in result.stdout
        assert "завершена" in result.stdout
        assert NO_CHANGES_ATTEMPT in result.stdout

    def test_missing_summary_fails_closed(self, tmp_path: Path) -> None:
        root, _audit_service, _ = _build_vault(tmp_path)
        config = _write_config(tmp_path)
        _run_no_changes(root, config)

        store = ObsidianPostSessionArtifactStore(root)
        summary = store.expected_relative_path(
            "S001", NO_CHANGES_ATTEMPT, PersistedArtifactKind.SUMMARY
        )
        (root / summary).unlink()

        result = _invoke_outputs(root, "S001")

        assert result.exit_code == 1
        assert "artifact_missing" in result.stderr
        assert NO_CHANGES_ATTEMPT in result.stderr
        assert "не подтверждено" in result.stderr

    def test_artifact_hash_mismatch_fails_closed(self, tmp_path: Path) -> None:
        root, _audit_service, _ = _build_vault(tmp_path)
        config = _write_config(tmp_path)
        _run_no_changes(root, config)

        store = ObsidianPostSessionArtifactStore(root)
        recap = store.expected_relative_path(
            "S001", NO_CHANGES_ATTEMPT, PersistedArtifactKind.RECAP
        )
        (root / recap).write_bytes(b"tampered\n")

        result = _invoke_outputs(root, "S001")

        assert result.exit_code == 1
        assert "artifact_hash_mismatch" in result.stderr

    def test_missing_proposal_fails_closed(self, tmp_path: Path) -> None:
        root, audit, _ = _build_vault(tmp_path)
        config = _write_config(tmp_path)
        model = ScriptedPostSessionModel(extraction=_append_extraction(root, audit))
        assert (
            _invoke_process(
                root, config, model, args=["S001"], attempt_id=PRODUCED_ATTEMPT
            ).exit_code
            == 0
        )
        proposal = root / "_system" / "changesets" / f"cs_S001_{PRODUCED_ATTEMPT}.proposal.json"
        proposal.unlink()

        result = _invoke_outputs(root, "S001")

        assert result.exit_code == 1
        assert "proposal_missing" in result.stderr

    def test_no_changes_orphan_proposal_fails_closed(self, tmp_path: Path) -> None:
        root, _audit_service, _ = _build_vault(tmp_path)
        config = _write_config(tmp_path)
        _run_no_changes(root, config)

        changesets = root / "_system" / "changesets"
        changesets.mkdir(parents=True, exist_ok=True)
        (changesets / f"cs_S001_{NO_CHANGES_ATTEMPT}.proposal.json").write_text(
            "{}", encoding="utf-8"
        )

        result = _invoke_outputs(root, "S001")

        assert result.exit_code == 1
        assert "unexpected_proposal" in result.stderr

    def test_existing_session_without_attempts_is_informational(self, tmp_path: Path) -> None:
        root, _audit_service, _ = _build_vault(tmp_path)

        result = _invoke_outputs(root, "S001")

        assert result.exit_code == 0
        assert "Попыток обработки нет" in result.stdout

    def test_missing_session_is_an_error(self, tmp_path: Path) -> None:
        root, _audit_service, _ = _build_vault(tmp_path)

        result = _invoke_outputs(root, "S999")

        assert result.exit_code == 1
        assert "не найдена" in result.stderr

    def test_started_attempt_is_inspectable(self, tmp_path: Path) -> None:
        root, audit, _ = _build_vault(tmp_path)
        store = ObsidianPostSessionProcessingStore(root)
        ObsidianPostSessionArtifactStore(root).claim_attempt("S001", NO_CHANGES_ATTEMPT)
        record_ledger_event(
            store,
            "S001",
            AttemptStarted(
                event_id=new_ledger_event_id(),
                attempt_id=NO_CHANGES_ATTEMPT,
                session_ref="S001",
                real_time=BASE_END,
                input_fingerprint=_prepared_fingerprint(root, audit),
                processor_version="2",
                prompt_version="post-session-extraction-v1",
            ),
        )

        result = _invoke_outputs(root, "S001")

        assert result.exit_code == 0
        assert NO_CHANGES_ATTEMPT in result.stdout
        assert "начата (прервана)" in result.stdout
        assert "подтверждена" not in result.stdout

    def test_failed_attempt_is_inspectable(self, tmp_path: Path) -> None:
        root, audit, _ = _build_vault(tmp_path)
        config = _write_config(tmp_path)
        error = ModelAPIError("boom", "failed")
        error.__cause__ = openai.APIConnectionError(request=None)  # type: ignore[arg-type]
        model = ScriptedPostSessionModel(
            extraction=_append_extraction(root, audit), extraction_error=error
        )
        assert (
            _invoke_process(
                root, config, model, args=["S001"], attempt_id=PRODUCED_ATTEMPT
            ).exit_code
            == 1
        )

        result = _invoke_outputs(root, "S001")

        assert result.exit_code == 0
        assert "ошибка" in result.stdout
        assert "модель недоступна" in result.stdout


def _prepared_fingerprint(root: Path, audit: AuditService):
    metadata_repo = ObsidianSessionMetadataRepository(root, audit)
    event_repo = ObsidianSessionEventRepository(root, audit)
    store = ObsidianPostSessionProcessingStore(root)
    eligibility = evaluate_processing_eligibility(metadata_repo, event_repo, store, "S001")
    assert eligibility.eligible is True
    return build_post_session_input(
        metadata_repo=metadata_repo,
        event_repo=event_repo,
        vault_repo=ObsidianVaultRepository(str(root), audit),
        session_id="S001",
        eligibility=eligibility,
    ).fingerprint
