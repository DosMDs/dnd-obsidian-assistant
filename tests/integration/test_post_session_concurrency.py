"""S11-08 concurrency hardening for the durable post-session workflow.

Proves a single model-running owner per attempt, independent different-attempt
execution over a shared ledger, and safe concurrent ledger reads.  Uses
``multiprocessing`` ``spawn`` with explicit ``Event``/``Value``/``Queue``
synchronization; no timing-only sleeps.
"""

from __future__ import annotations

import multiprocessing
from dataclasses import replace
from pathlib import Path

from dnd_assistant.application.post_session_attempt_state import (
    AttemptState,
    fold_attempt_state,
)
from dnd_assistant.application.post_session_ledger import (
    load_ledger_events,
    serialize_ledger_event,
)
from dnd_assistant.application.post_session_processor import (
    PostSessionProcessorStatus,
    run_post_session_processing,
)
from dnd_assistant.domain.post_session import (
    AttemptStarted,
    PersistedArtifactKind,
    Sha256Fingerprint,
)
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.post_session_artifacts import ObsidianPostSessionArtifactStore
from dnd_assistant.storage.post_session_processing import ObsidianPostSessionProcessingStore
from tests.integration.post_session_processor_helpers import (
    ATTEMPT_A,
    ATTEMPT_B,
    build_deps,
    fixed_clock,
)
from tests.integration.test_post_session_context import _build, _build_vault
from tests.support.post_session_truth import canonical_truth_snapshot
from tests.unit.post_session.extraction_helpers import (
    FakePostSessionExtractionModel,
    make_extraction,
)
from tests.unit.post_session.rendering_helpers import (
    FakePostSessionRenderingModel,
    make_render_output,
)

_QUEUE_TIMEOUT = 120


def _deps(root: Path, audit: AuditService, *, extraction_model, rendering_model):
    deps = build_deps(root, audit)
    return replace(
        deps,
        extraction_model=extraction_model,
        rendering_model=rendering_model,
    )


class _BlockingExtractionModel:
    """Signals entry, then blocks until released; counts model-running owners."""

    def __init__(self, counter, entered, release) -> None:
        self._counter = counter
        self._entered = entered
        self._release = release

    def extract(self, request):
        with self._counter.get_lock():
            self._counter.value += 1
        self._entered.set()
        if not self._release.wait(timeout=_QUEUE_TIMEOUT):
            raise TimeoutError("test release event was never set")
        return make_extraction()


def _worker_blocking(root_str: str, counter, entered, release, queue) -> None:
    root = Path(root_str)
    audit = AuditService(root / "_system" / "audit" / "audit.jsonl")
    deps = _deps(
        root,
        audit,
        extraction_model=_BlockingExtractionModel(counter, entered, release),
        rendering_model=FakePostSessionRenderingModel(make_render_output()),
    )
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)
    queue.put((result.status.value, counter.value))


def _worker_no_changes(root_str: str, attempt: str, queue) -> None:
    root = Path(root_str)
    audit = AuditService(root / "_system" / "audit" / "audit.jsonl")
    model = FakePostSessionExtractionModel(make_extraction())
    deps = _deps(
        root,
        audit,
        extraction_model=model,
        rendering_model=FakePostSessionRenderingModel(make_render_output()),
    )
    result = run_post_session_processing(deps, "S001", attempt, clock=fixed_clock)
    queue.put((result.status.value, len(model.requests)))


def test_same_attempt_has_at_most_one_model_owner(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    _build(root, audit)  # prepared input must exist before workers run
    before = canonical_truth_snapshot(root)

    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    counter = ctx.Value("i", 0, lock=True)
    entered = ctx.Event()
    release = ctx.Event()
    worker = ctx.Process(
        target=_worker_blocking, args=(str(root), counter, entered, release, queue)
    )
    worker.start()
    try:
        assert entered.wait(timeout=_QUEUE_TIMEOUT), "worker A never entered the model"

        model_b = FakePostSessionExtractionModel(make_extraction())
        deps_b = _deps(
            root,
            audit,
            extraction_model=model_b,
            rendering_model=FakePostSessionRenderingModel(make_render_output()),
        )
        result_b = run_post_session_processing(deps_b, "S001", ATTEMPT_A, clock=fixed_clock)

        assert result_b.status is PostSessionProcessorStatus.INTERRUPTED
        assert model_b.requests == []

        release.set()
        worker.join(timeout=_QUEUE_TIMEOUT)
        assert worker.exitcode == 0

        status_a, owners_a = _collect_result(queue)
        assert status_a == PostSessionProcessorStatus.COMPLETED.value
        assert owners_a == 1
    finally:
        release.set()
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=30)

    store = ObsidianPostSessionProcessingStore(root)
    events = load_ledger_events(store, "S001")
    started = [e for e in events if isinstance(e, AttemptStarted) and e.attempt_id == ATTEMPT_A]
    assert len(started) == 1
    fold = fold_attempt_state(events, ATTEMPT_A)
    assert fold.state is AttemptState.COMPLETED
    assert canonical_truth_snapshot(root) == before


def _collect_result(queue) -> tuple[str, int]:
    while True:
        try:
            item = queue.get(timeout=_QUEUE_TIMEOUT)
        except Exception as exc:  # pragma: no cover - only on failure
            raise AssertionError("worker produced no result") from exc
        if isinstance(item, tuple) and len(item) == 2:
            return str(item[0]), int(item[1])


def test_different_attempts_share_ledger_independently(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    _build(root, audit)
    before = canonical_truth_snapshot(root)

    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    workers = [
        ctx.Process(target=_worker_no_changes, args=(str(root), attempt, queue))
        for attempt in (ATTEMPT_A, ATTEMPT_B)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=_QUEUE_TIMEOUT)
        assert worker.exitcode == 0

    results = [_collect_result(queue) for _ in workers]
    assert all(item[0] == PostSessionProcessorStatus.COMPLETED.value for item in results)
    assert all(item[1] == 1 for item in results)

    store = ObsidianPostSessionProcessingStore(root)
    events = load_ledger_events(store, "S001")
    assert store.read_ledger_if_present("S001") is not None
    for attempt in (ATTEMPT_A, ATTEMPT_B):
        fold = fold_attempt_state(events, attempt)
        assert fold.state is AttemptState.COMPLETED
    artifact_store = ObsidianPostSessionArtifactStore(root)
    for attempt in (ATTEMPT_A, ATTEMPT_B):
        assert artifact_store.artifact_exists("S001", attempt, PersistedArtifactKind.SUMMARY)
        assert artifact_store.artifact_exists("S001", attempt, PersistedArtifactKind.WORKFLOW)
    assert canonical_truth_snapshot(root) == before


def _writer_process(root_str: str, count: int, done) -> None:
    root = Path(root_str)
    store = ObsidianPostSessionProcessingStore(root)
    for index in range(count):
        event = AttemptStarted(
            event_id="le_" + f"{index:032x}",
            attempt_id="att_" + f"{index:032x}",
            session_ref="S001",
            real_time=fixed_clock(),
            input_fingerprint=Sha256Fingerprint(digest="c" * 64),
            processor_version="2",
            prompt_version="v1",
        )
        store.append_ledger_line("S001", serialize_ledger_event(event) + "\n")
    done.set()


def test_concurrent_ledger_reads_never_observe_partial_records(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    _build(root, audit)

    ctx = multiprocessing.get_context("spawn")
    done = ctx.Event()
    count = 40
    writer = ctx.Process(target=_writer_process, args=(str(root), count, done))
    writer.start()

    store = ObsidianPostSessionProcessingStore(root)
    reads = 0
    try:
        while not done.is_set():
            load_ledger_events(store, "S001")  # must never raise on a torn record
            reads += 1
        writer.join(timeout=_QUEUE_TIMEOUT)
        assert writer.exitcode == 0
        final = load_ledger_events(store, "S001")
        assert len(final) == count
        assert reads >= 1
    finally:
        if writer.is_alive():
            writer.terminate()
            writer.join(timeout=30)
