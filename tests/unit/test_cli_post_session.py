"""S11-07 CLI post-session command unit tests (no Vault writes, no Ollama).

Covers selector validation, deterministic ``--latest`` selection, POST_SESSION
profile loading, exit-code mapping, typed result rendering, the failure-recording
uncertainty renderer and model-lifetime cleanup.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.function import FunctionModel
from typer.testing import CliRunner

from dnd_assistant.application.post_session_processor_support import (
    PostSessionProcessorResult,
    PostSessionProcessorStatus,
)
from dnd_assistant.cli.main import app
from dnd_assistant.cli.post_session import (
    _exit_code_for,
    _render_process_result,
)
from dnd_assistant.cli.post_session_runtime import (
    LatestSelectionError,
    LatestSelectionReason,
    _load_post_session_profile,
    compose_post_session_runtime,
    new_attempt_id,
    select_latest_completed_session,
)
from dnd_assistant.domain.post_session import (
    FailureCategory,
    ProcessingOutcome,
    ProcessingPhase,
    Sha256Fingerprint,
)
from dnd_assistant.domain.session import Session
from dnd_assistant.errors import ValidationError
from dnd_assistant.storage.session_metadata import RawSessionMetadata
from tests.unit.post_session.helpers import BASE_END, BASE_START, make_vault

runner = CliRunner()

_ATTEMPT = "att_" + "a" * 32


def _dummy_model() -> FunctionModel:
    return FunctionModel(lambda messages, info: ModelResponse(parts=[]))


def _write_config(
    tmp_path: Path,
    *,
    profile_name: str = "ps",
    role: str = "post_session",
    provider: str = "ollama",
) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        f"[profiles.{profile_name}]\n"
        f"provider='{provider}'\n"
        "model='post-session-model'\n"
        "base_url='http://localhost:11434'\n"
        f"role='{role}'\n",
        encoding="utf-8",
    )
    return path


def _result(status: PostSessionProcessorStatus, **overrides: object) -> PostSessionProcessorResult:
    return PostSessionProcessorResult(
        status=status,
        session_id="S001",
        attempt_id=_ATTEMPT,
        **overrides,  # type: ignore[arg-type]
    )


# ── Pure latest selection ──────────────────────────────────────────────────


def _meta(
    session_id: str,
    *,
    status: str = "completed",
    finished: datetime | None = BASE_END,
) -> RawSessionMetadata:
    kwargs: dict[str, object] = {
        "id": session_id,
        "type": "session",
        "status": status,
        "revision": 1,
        "real_started_at": BASE_START,
        "world_tick_start": 100,
    }
    if status == "completed":
        kwargs["real_finished_at"] = finished
        kwargs["world_tick_end"] = 200
    return RawSessionMetadata(session=Session.model_validate(kwargs))


class TestLatestSelection:
    def test_selects_greatest_finish_time(self) -> None:
        earlier = _meta("S001", finished=BASE_END)
        later = _meta("S002", finished=BASE_END + timedelta(hours=1))
        assert select_latest_completed_session([later, earlier]) == "S002"

    def test_tie_breaks_by_numeric_id_rank(self) -> None:
        s2 = _meta("S2", finished=BASE_END)
        s10 = _meta("S10", finished=BASE_END)
        assert select_latest_completed_session([s2, s10]) == "S10"

    def test_active_sessions_are_excluded(self) -> None:
        completed = _meta("S001", finished=BASE_END)
        active = _meta("S002", status="active", finished=None)
        assert select_latest_completed_session([completed, active]) == "S001"

    def test_no_completed_sessions_fails_closed(self) -> None:
        active = _meta("S001", status="active", finished=None)
        try:
            select_latest_completed_session([active])
        except LatestSelectionError as exc:
            assert exc.reason is LatestSelectionReason.NO_COMPLETED_SESSIONS
        else:  # pragma: no cover
            raise AssertionError("expected LatestSelectionError")

    def test_missing_finish_metadata_fails_closed(self) -> None:
        good = _meta("S001", finished=BASE_END)
        malformed = RawSessionMetadata(
            session=Session.model_validate(
                {
                    "id": "S002",
                    "type": "session",
                    "status": "completed",
                    "revision": 1,
                    "real_started_at": BASE_START,
                    "world_tick_start": 100,
                }
            )
        )
        try:
            select_latest_completed_session([good, malformed])
        except LatestSelectionError as exc:
            assert exc.reason is LatestSelectionReason.MISSING_FINISH_METADATA
            assert exc.session_ids == ("S002",)
        else:  # pragma: no cover
            raise AssertionError("expected LatestSelectionError")


# ── Profile loading ────────────────────────────────────────────────────────


class TestProfileLoading:
    def test_post_session_profile_accepted(self, tmp_path: Path) -> None:
        config = _write_config(tmp_path)
        profile = _load_post_session_profile(config, "ps")
        assert profile.role.value == "post_session"

    def test_missing_profile_rejected(self, tmp_path: Path) -> None:
        config = _write_config(tmp_path, profile_name="other")
        try:
            _load_post_session_profile(config, "ps")
        except ValidationError:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected ValidationError")

    def test_agent_profile_rejected(self, tmp_path: Path) -> None:
        config = _write_config(tmp_path, role="agent")
        try:
            _load_post_session_profile(config, "ps")
        except ValidationError:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected ValidationError")


# ── Exit codes and rendering ───────────────────────────────────────────────


class TestExitCodes:
    def test_completed_and_terminal_are_success(self) -> None:
        assert _exit_code_for(_result(PostSessionProcessorStatus.COMPLETED)) == 0
        assert _exit_code_for(_result(PostSessionProcessorStatus.ALREADY_TERMINAL)) == 0

    def test_non_terminal_states_are_failures(self) -> None:
        for status in (
            PostSessionProcessorStatus.INELIGIBLE,
            PostSessionProcessorStatus.INTERRUPTED,
            PostSessionProcessorStatus.FAILED,
        ):
            assert _exit_code_for(_result(status)) == 1


class TestRendering:
    def test_produced_renders_proposal_only(self, tmp_path: Path) -> None:
        result = _result(
            PostSessionProcessorStatus.COMPLETED,
            outcome=ProcessingOutcome.PRODUCED,
            summary_path="s/summary.md",
            recap_path="s/recap.md",
            workflow_path="s/workflow.json",
            changeset_id="cs_S001_att",
            changeset_fingerprint=Sha256Fingerprint(digest="0" * 64),
            recap_was_empty=True,
            unresolved_count=3,
        )
        text = _render_process_result(result, tmp_path)
        assert "предложение изменений" in text
        assert "ТОЛЬКО предложение" in text
        assert f"dnd changeset review cs_S001_att --vault {tmp_path}" in text
        assert "Recap пуст (детерминированно): да" in text
        assert "Нерешённых ссылок: 3" in text

    def test_no_changes_renders_no_proposal(self, tmp_path: Path) -> None:
        result = _result(
            PostSessionProcessorStatus.COMPLETED,
            outcome=ProcessingOutcome.NO_CHANGES,
            summary_path="s/summary.md",
            recap_path="s/recap.md",
            workflow_path="s/workflow.json",
        )
        text = _render_process_result(result, tmp_path)
        assert "ChangeSet не создан" in text
        assert "Сущности кампании не изменялись" in text

    def test_already_terminal_is_idempotent(self, tmp_path: Path) -> None:
        result = _result(
            PostSessionProcessorStatus.ALREADY_TERMINAL,
            outcome=ProcessingOutcome.NO_CHANGES,
        )
        text = _render_process_result(result, tmp_path)
        assert "идемпотентный повтор" in text
        assert "Модель не вызывалась" in text

    def test_interrupted_never_claims_retry_or_rollback(self, tmp_path: Path) -> None:
        result = _result(PostSessionProcessorStatus.INTERRUPTED, reason="attempt_interrupted")
        text = _render_process_result(result, tmp_path)
        assert "attempt_interrupted" in text
        assert "Откат не выполнялся" in text
        assert "новая попытка" in text

    def test_ineligible_does_not_claim_model_run(self, tmp_path: Path) -> None:
        result = _result(PostSessionProcessorStatus.INELIGIBLE, reason="session_not_completed")
        text = _render_process_result(result, tmp_path)
        assert "session_not_completed" in text
        assert "Модельная обработка не запускалась" in text

    def test_failed_renders_bounded_metadata(self, tmp_path: Path) -> None:
        result = _result(
            PostSessionProcessorStatus.FAILED,
            phase=ProcessingPhase.RENDERING,
            failure_category=FailureCategory.MODEL_TIMEOUT,
            failure_recorded=True,
            reason="Post-session rendering failed: model_timeout",
        )
        text = _render_process_result(result, tmp_path)
        assert "рендеринг" in text
        assert "таймаут модели" in text
        assert "Терминальная ошибка сохранена: да" in text
        assert "model_timeout" in text


# ── Model lifetime ─────────────────────────────────────────────────────────


class TestModelLifetime:
    def test_close_is_idempotent(self, tmp_path: Path) -> None:
        vault_root = make_vault(tmp_path)
        config = _write_config(tmp_path)
        with patch("dnd_assistant.cli.post_session_runtime._close_model") as close_mock:
            runtime = compose_post_session_runtime(
                vault_root=vault_root,
                config_path=config,
                profile_name="ps",
                model_factory=lambda profile: _dummy_model(),
            )
            runtime.close()
            runtime.close()
        assert close_mock.call_count == 1

    def test_composition_failure_after_model_closes_model(self, tmp_path: Path) -> None:
        vault_root = make_vault(tmp_path)
        config = _write_config(tmp_path)
        # A missing audit directory makes VaultRepository composition fail after
        # the model is created.
        (vault_root / "_system" / "audit").rmdir()
        with patch("dnd_assistant.cli.post_session_runtime._close_model") as close_mock:
            try:
                compose_post_session_runtime(
                    vault_root=vault_root,
                    config_path=config,
                    profile_name="ps",
                    model_factory=lambda profile: _dummy_model(),
                )
            except Exception:
                pass
        assert close_mock.call_count == 1


# ── Attempt id + registration ──────────────────────────────────────────────


class TestAttemptId:
    def test_new_attempt_id_is_trusted_shape(self) -> None:
        value = new_attempt_id()
        assert value.startswith("att_")
        assert len(value) == 4 + 32

    def test_attempt_id_generation_is_patchable(self) -> None:
        with patch(
            "dnd_assistant.cli.post_session.new_attempt_id", return_value=_ATTEMPT
        ) as factory:
            from dnd_assistant.cli import post_session

            assert post_session.new_attempt_id() == _ATTEMPT
        factory.assert_called_once()


class TestHelpAndRegistration:
    def test_session_help_exposes_process_and_outputs(self) -> None:
        with patch("dnd_assistant.cli.post_session_runtime._build_post_session_model") as factory:
            result = runner.invoke(app, ["session", "--help"])
        assert result.exit_code == 0
        assert "process" in result.stdout
        assert "outputs" in result.stdout
        factory.assert_not_called()

    def test_process_help_exposes_options(self) -> None:
        result = runner.invoke(app, ["session", "process", "--help"])
        assert result.exit_code == 0
        assert "--vault" in result.stdout
        assert "--config" in result.stdout
        assert "--profile" in result.stdout
        assert "--latest" in result.stdout


# ── Selector validation: zero model construction ───────────────────────────


class TestSelectorValidation:
    def test_both_selectors_rejected_before_model(self, tmp_path: Path) -> None:
        vault_root = make_vault(tmp_path)
        config = _write_config(tmp_path)
        with patch("dnd_assistant.cli.post_session_runtime._build_post_session_model") as factory:
            result = runner.invoke(
                app,
                [
                    "session",
                    "process",
                    "S001",
                    "--latest",
                    "--vault",
                    str(vault_root),
                    "--config",
                    str(config),
                    "--profile",
                    "ps",
                ],
            )
        assert result.exit_code == 1
        factory.assert_not_called()

    def test_no_selector_rejected_before_model(self, tmp_path: Path) -> None:
        vault_root = make_vault(tmp_path)
        config = _write_config(tmp_path)
        with patch("dnd_assistant.cli.post_session_runtime._build_post_session_model") as factory:
            result = runner.invoke(
                app,
                [
                    "session",
                    "process",
                    "--vault",
                    str(vault_root),
                    "--config",
                    str(config),
                    "--profile",
                    "ps",
                ],
            )
        assert result.exit_code == 1
        factory.assert_not_called()


# ── Failure-recording uncertainty renderer ─────────────────────────────────


class TestRecordingUncertainty:
    def test_renderer_reports_attempt_and_no_retry(self) -> None:
        from dnd_assistant.application.post_session_processor_support import (
            PostSessionFailureRecordingError,
        )
        from dnd_assistant.cli.post_session import _render_recording_uncertainty

        exc = PostSessionFailureRecordingError(
            ProcessingPhase.PERSISTENCE,
            FailureCategory.STORAGE_ERROR,
            "Processing storage failure",
        )
        text = _render_recording_uncertainty("S001", _ATTEMPT, exc)
        assert _ATTEMPT in text
        assert "не удалось надёжно сохранить" in text
        assert "Автоматический повтор не выполнялся" in text
        # Raw original message / cause is never echoed.
        assert "Processing storage failure" not in text
