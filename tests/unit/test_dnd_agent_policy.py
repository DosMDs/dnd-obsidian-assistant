"""Tests for DndAgentPolicy — explicit D&D agent safety policy (PAIM-05).

Admission matrix
────────────────

| Scenario                      | Result     | Admitted count | Handler calls |
| ----------------------------- | ---------- | -------------: | ------------: |
| POL-01 single READ            | admitted   |              1 |             0 |
| POL-02 single WRITE           | admitted   |              1 |             0 |
| POL-03 two READ               | admitted   |              2 |             0 |
| POL-04 four READ              | admitted   |              4 |             0 |
| POL-05 five calls             | ModelError |              0 |             0 |
| POL-06 READ+WRITE             | ModelError |              0 |             0 |
| POL-07 WRITE+WRITE            | ModelError |              0 |             0 |
| POL-08 duplicate non-null ID  | ModelError |              0 |             0 |
| POL-09 distinct IDs           | admitted   |              2 |             0 |
| POL-10 repeated same READ     | admitted   |              2 |             0 |
| POL-11 hidden registered tool | ModelError |              0 |             0 |
| POL-12 completely unknown     | ModelError |              0 |             0 |

Second-batch tests
──────────────────

| Scenario                                    | Result     |
| ------------------------------------------- | ---------- |
| POL-13 first valid → second valid           | ModelError |
| POL-14 first rejected → second valid        | ModelError |
| POL-15 new policy instance fresh state      | admitted   |
| POL-20 empty → subsequent first real batch  | admitted   |

Snapshot capability tests
─────────────────────────

| Scenario                                           | Result         |
| -------------------------------------------------- | -------------- |
| POL-16 cross-bridge snapshot                       | ValidationError|
| POL-17 copied snapshot (dataclasses.replace)       | ValidationError|
| POL-18 stolen owner token but non-issued snapshot  | ValidationError|

Structural input tests
──────────────────────

| Scenario                    | Result         |
| --------------------------- | -------------- |
| POL-19 non-ToolCallPart     | ValidationError|
| POL-20 empty batch          | ValidationError|

Argument-separation test
────────────────────────

| Scenario                    | Policy result | Bridge execute result |
| --------------------------- | ------------- | -------------------- |
| POL-21 malformed args       | admitted      | ValidationError      |

Single-WRITE authorization separation
─────────────────────────────────────

| Scenario                    | Policy result | ToolExecutor result        |
| --------------------------- | ------------- | -------------------------- |
| POL-22 single WRITE READ ctx| admitted      | ConflictError              |

Immutable admission proof
─────────────────────────

| Property                         | Assertion           |
| -------------------------------- | ------------------- |
| DndAgentBatchAdmission frozen    | cannot modify calls |
| calls is tuple                   | isinstance          |
| AdmittedToolCall frozen          | cannot modify       |
| canonical definition identity    | exact snapshot defs |
| order preservation               | model batch order   |
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from pydantic_ai.messages import ToolCallPart

from dnd_assistant.application.dnd_agent_policy import (
    MAX_TOOL_CALLS_PER_RUN,
    DndAgentPolicy,
)
from dnd_assistant.application.pydantic_ai_tool_bridge import (
    PydanticAIToolBridge,
    PydanticAIToolSnapshot,
)
from dnd_assistant.errors import ModelError, ValidationError
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import ExecutionContext, Permission, SessionMode, ToolDefinition
from tests.support.pydantic_ai_runtime import (
    READ_ALPHA_DEF,
    READ_BETA_DEF,
    WRITE_ALPHA_DEF,
    AlphaInput,
    HandlerCounters,
    ToolOutput,
    make_tool_executor,
    make_tool_registry,
)

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def counters() -> HandlerCounters:
    return HandlerCounters()


@pytest.fixture
def registry(counters: HandlerCounters) -> ToolRegistry:
    return make_tool_registry(counters)


@pytest.fixture
def executor(registry: ToolRegistry) -> ToolExecutor:
    return make_tool_executor(registry)


@pytest.fixture
def bridge(registry: ToolRegistry) -> PydanticAIToolBridge:
    return PydanticAIToolBridge(registry=registry)


@pytest.fixture
def snapshot(bridge: PydanticAIToolBridge) -> PydanticAIToolSnapshot:
    """Freeze a snapshot with read_alpha, read_beta, write_alpha."""
    from dnd_assistant.tools.catalog import ToolPublicDefinition

    defs: list[ToolPublicDefinition] = []
    for td in [READ_ALPHA_DEF, READ_BETA_DEF, WRITE_ALPHA_DEF]:
        defs.append(
            ToolPublicDefinition(
                name=td.name,
                description=td.description,
                input_schema=td.input_schema.model_json_schema(),
                output_schema=td.output_schema.model_json_schema(),
                permission=td.permission,
                side_effects=list(td.side_effects),
                allowed_session_modes=list(td.allowed_session_modes),
            )
        )
    return bridge.freeze(defs)


@pytest.fixture
def read_only_snapshot(bridge: PydanticAIToolBridge) -> PydanticAIToolSnapshot:
    """Freeze a snapshot with only read_alpha and read_beta."""
    from dnd_assistant.tools.catalog import ToolPublicDefinition

    defs: list[ToolPublicDefinition] = []
    for td in [READ_ALPHA_DEF, READ_BETA_DEF]:
        defs.append(
            ToolPublicDefinition(
                name=td.name,
                description=td.description,
                input_schema=td.input_schema.model_json_schema(),
                output_schema=td.output_schema.model_json_schema(),
                permission=td.permission,
                side_effects=list(td.side_effects),
                allowed_session_modes=list(td.allowed_session_modes),
            )
        )
    return bridge.freeze(defs)


@pytest.fixture
def policy(
    bridge: PydanticAIToolBridge,
    snapshot: PydanticAIToolSnapshot,
) -> DndAgentPolicy:
    return DndAgentPolicy(tool_bridge=bridge, snapshot=snapshot)


@pytest.fixture
def read_only_policy(
    bridge: PydanticAIToolBridge,
    read_only_snapshot: PydanticAIToolSnapshot,
) -> DndAgentPolicy:
    return DndAgentPolicy(tool_bridge=bridge, snapshot=read_only_snapshot)


# ==============================================================================
# Helper: build ToolCallPart from tool name and optional ID
# ==============================================================================


def _make_tool_call(
    tool_name: str,
    *,
    args: dict[str, Any] | None = None,
    tool_call_id: str | None = None,
) -> ToolCallPart:
    """Build a ToolCallPart with the given tool name and optional ID.

    By default, ``tool_call_id`` is ``None`` (framework auto-assigns).
    Tests that need distinct IDs should pass them explicitly.
    """
    kwargs: dict[str, Any] = {"tool_name": tool_name}
    if args is not None:
        kwargs["args"] = args
    if tool_call_id is not None:
        kwargs["tool_call_id"] = tool_call_id
    return ToolCallPart(**kwargs)


# ==============================================================================
# POL-01 — single READ
# ==============================================================================


class TestPol01SingleRead:
    def test_single_read_admitted(self, policy: DndAgentPolicy) -> None:
        calls = [_make_tool_call("read_alpha")]
        admission = policy.admit_tool_batch(calls)
        assert len(admission.calls) == 1
        assert admission.calls[0].tool_name == "read_alpha"
        assert admission.calls[0].position == 0

    def test_zero_handler_calls(self, policy: DndAgentPolicy, counters: HandlerCounters) -> None:
        calls = [_make_tool_call("read_alpha")]
        policy.admit_tool_batch(calls)
        assert counters.alpha == 0
        assert counters.beta == 0
        assert counters.write_alpha == 0


# ==============================================================================
# POL-02 — single WRITE
# ==============================================================================


class TestPol02SingleWrite:
    def test_single_write_admitted_by_policy(self, policy: DndAgentPolicy) -> None:
        calls = [_make_tool_call("write_alpha")]
        admission = policy.admit_tool_batch(calls)
        assert len(admission.calls) == 1
        assert admission.calls[0].tool_name == "write_alpha"

    def test_zero_handler_calls(self, policy: DndAgentPolicy, counters: HandlerCounters) -> None:
        calls = [_make_tool_call("write_alpha")]
        policy.admit_tool_batch(calls)
        assert counters.write_alpha == 0


# ==============================================================================
# POL-03 — two READ
# ==============================================================================


class TestPol03TwoRead:
    def test_two_read_admitted_in_order(self, policy: DndAgentPolicy) -> None:
        calls = [
            _make_tool_call("read_beta"),
            _make_tool_call("read_alpha"),
        ]
        admission = policy.admit_tool_batch(calls)
        assert len(admission.calls) == 2
        assert admission.calls[0].tool_name == "read_beta"
        assert admission.calls[0].position == 0
        assert admission.calls[1].tool_name == "read_alpha"
        assert admission.calls[1].position == 1

    def test_zero_handler_calls(self, policy: DndAgentPolicy, counters: HandlerCounters) -> None:
        calls = [_make_tool_call("read_alpha"), _make_tool_call("read_beta")]
        policy.admit_tool_batch(calls)
        assert counters.alpha == 0
        assert counters.beta == 0


# ==============================================================================
# POL-04 — four READ
# ==============================================================================


class TestPol04FourRead:
    def test_four_read_admitted(self, read_only_policy: DndAgentPolicy) -> None:
        calls = [
            _make_tool_call("read_alpha"),
            _make_tool_call("read_beta"),
            _make_tool_call("read_alpha"),
            _make_tool_call("read_beta"),
        ]
        admission = read_only_policy.admit_tool_batch(calls)
        assert len(admission.calls) == 4

    def test_zero_handler_calls(
        self, read_only_policy: DndAgentPolicy, counters: HandlerCounters
    ) -> None:
        calls = [
            _make_tool_call("read_alpha"),
            _make_tool_call("read_beta"),
            _make_tool_call("read_alpha"),
            _make_tool_call("read_beta"),
        ]
        read_only_policy.admit_tool_batch(calls)
        assert counters.alpha == 0
        assert counters.beta == 0


# ==============================================================================
# POL-05 — five calls
# ==============================================================================


class TestPol05FiveCalls:
    def test_five_calls_rejected(self, read_only_policy: DndAgentPolicy) -> None:
        calls = [
            _make_tool_call("read_alpha"),
            _make_tool_call("read_beta"),
            _make_tool_call("read_alpha"),
            _make_tool_call("read_beta"),
            _make_tool_call("read_alpha"),
        ]
        with pytest.raises(ModelError) as excinfo:
            read_only_policy.admit_tool_batch(calls)
        assert str(MAX_TOOL_CALLS_PER_RUN) in str(excinfo.value)

    def test_zero_handler_calls(
        self, read_only_policy: DndAgentPolicy, counters: HandlerCounters
    ) -> None:
        calls = [
            _make_tool_call("read_alpha"),
            _make_tool_call("read_beta"),
            _make_tool_call("read_alpha"),
            _make_tool_call("read_beta"),
            _make_tool_call("read_alpha"),
        ]
        with pytest.raises(ModelError):
            read_only_policy.admit_tool_batch(calls)
        assert counters.alpha == 0
        assert counters.beta == 0


# ==============================================================================
# POL-06 — mixed multi-call (READ + WRITE)
# ==============================================================================


class TestPol06ReadWrite:
    def test_read_write_rejected(self, policy: DndAgentPolicy) -> None:
        calls = [_make_tool_call("read_alpha"), _make_tool_call("write_alpha")]
        with pytest.raises(ModelError) as excinfo:
            policy.admit_tool_batch(calls)
        assert "WRITE" in str(excinfo.value)

    def test_zero_handler_calls(self, policy: DndAgentPolicy, counters: HandlerCounters) -> None:
        calls = [_make_tool_call("read_alpha"), _make_tool_call("write_alpha")]
        with pytest.raises(ModelError):
            policy.admit_tool_batch(calls)
        assert counters.alpha == 0
        assert counters.write_alpha == 0


# ==============================================================================
# POL-07 — multiple WRITE
# ==============================================================================


class TestPol07WriteWrite:
    def test_write_write_rejected(self, policy: DndAgentPolicy) -> None:
        calls = [_make_tool_call("write_alpha"), _make_tool_call("write_alpha")]
        with pytest.raises(ModelError) as excinfo:
            policy.admit_tool_batch(calls)
        assert "WRITE" in str(excinfo.value)

    def test_zero_handler_calls(self, policy: DndAgentPolicy, counters: HandlerCounters) -> None:
        calls = [_make_tool_call("write_alpha"), _make_tool_call("write_alpha")]
        with pytest.raises(ModelError):
            policy.admit_tool_batch(calls)
        assert counters.write_alpha == 0


# ==============================================================================
# POL-08 — duplicate non-null ID
# ==============================================================================


class TestPol08DuplicateId:
    def test_duplicate_id_rejected(self, policy: DndAgentPolicy) -> None:
        calls = [
            _make_tool_call("read_alpha", tool_call_id="dup"),
            _make_tool_call("read_beta", tool_call_id="dup"),
        ]
        with pytest.raises(ModelError) as excinfo:
            policy.admit_tool_batch(calls)
        assert "Duplicate" in str(excinfo.value)

    def test_zero_handler_calls(self, policy: DndAgentPolicy, counters: HandlerCounters) -> None:
        calls = [
            _make_tool_call("read_alpha", tool_call_id="dup"),
            _make_tool_call("read_beta", tool_call_id="dup"),
        ]
        with pytest.raises(ModelError):
            policy.admit_tool_batch(calls)
        assert counters.alpha == 0
        assert counters.beta == 0


# ==============================================================================
# POL-09 — distinct IDs
# ==============================================================================


class TestPol09DistinctIds:
    def test_distinct_ids_admitted(self, policy: DndAgentPolicy) -> None:
        calls = [
            _make_tool_call("read_alpha", tool_call_id="id_a"),
            _make_tool_call("read_beta", tool_call_id="id_b"),
        ]
        admission = policy.admit_tool_batch(calls)
        assert len(admission.calls) == 2


# ==============================================================================
# POL-10 — repeated same tool name
# ==============================================================================


class TestPol10RepeatedSameName:
    def test_repeated_same_name_admitted(self, read_only_policy: DndAgentPolicy) -> None:
        calls = [
            _make_tool_call("read_alpha", tool_call_id="id_a"),
            _make_tool_call("read_alpha", tool_call_id="id_b"),
        ]
        admission = read_only_policy.admit_tool_batch(calls)
        assert len(admission.calls) == 2
        assert admission.calls[0].tool_name == "read_alpha"
        assert admission.calls[1].tool_name == "read_alpha"


# ==============================================================================
# POL-11 — hidden registered tool
# ==============================================================================


class TestPol11HiddenTool:
    def test_hidden_tool_rejected(
        self, bridge: PydanticAIToolBridge, registry: ToolRegistry
    ) -> None:
        """Freeze snapshot, then register a hidden tool, then try to call it."""
        from dnd_assistant.tools.catalog import ToolPublicDefinition

        defs: list[ToolPublicDefinition] = []
        for td in [READ_ALPHA_DEF]:
            defs.append(
                ToolPublicDefinition(
                    name=td.name,
                    description=td.description,
                    input_schema=td.input_schema.model_json_schema(),
                    output_schema=td.output_schema.model_json_schema(),
                    permission=td.permission,
                    side_effects=list(td.side_effects),
                    allowed_session_modes=list(td.allowed_session_modes),
                )
            )
        snap = bridge.freeze(defs)

        # Register hidden tool after snapshot
        from dnd_assistant.tools.types import ToolDefinition

        hidden_canonical = ToolDefinition(
            name="hidden_tool",
            description="Hidden after freeze",
            input_schema=AlphaInput,
            output_schema=ToolOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )

        def hidden_handler(inp: AlphaInput, ctx: object) -> ToolOutput:
            return ToolOutput(result="hidden")

        registry.register(hidden_canonical, hidden_handler)

        pol = DndAgentPolicy(tool_bridge=bridge, snapshot=snap)
        calls = [_make_tool_call("hidden_tool")]
        with pytest.raises(ModelError) as excinfo:
            pol.admit_tool_batch(calls)
        assert "not in the frozen exposure" in str(excinfo.value)

    def test_zero_handler_calls(self, bridge: PydanticAIToolBridge, registry: ToolRegistry) -> None:
        from dnd_assistant.tools.catalog import ToolPublicDefinition

        defs: list[ToolPublicDefinition] = []
        for td in [READ_ALPHA_DEF]:
            defs.append(
                ToolPublicDefinition(
                    name=td.name,
                    description=td.description,
                    input_schema=td.input_schema.model_json_schema(),
                    output_schema=td.output_schema.model_json_schema(),
                    permission=td.permission,
                    side_effects=list(td.side_effects),
                    allowed_session_modes=list(td.allowed_session_modes),
                )
            )
        snap = bridge.freeze(defs)

        hidden_canonical = ToolDefinition(
            name="hidden_tool",
            description="Hidden after freeze",
            input_schema=AlphaInput,
            output_schema=ToolOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )

        hidden_calls = 0

        def hidden_handler(inp: AlphaInput, ctx: object) -> ToolOutput:
            nonlocal hidden_calls
            hidden_calls += 1
            return ToolOutput(result="hidden")

        registry.register(hidden_canonical, hidden_handler)

        pol = DndAgentPolicy(tool_bridge=bridge, snapshot=snap)
        calls = [_make_tool_call("hidden_tool")]
        with pytest.raises(ModelError):
            pol.admit_tool_batch(calls)
        assert hidden_calls == 0


# ==============================================================================
# POL-12 — completely unknown tool
# ==============================================================================


class TestPol12UnknownTool:
    def test_unknown_tool_rejected(self, policy: DndAgentPolicy) -> None:
        calls = [_make_tool_call("nonexistent_tool")]
        with pytest.raises(ModelError) as excinfo:
            policy.admit_tool_batch(calls)
        assert "not in the frozen exposure" in str(excinfo.value)

    def test_zero_handler_calls(self, policy: DndAgentPolicy, counters: HandlerCounters) -> None:
        calls = [_make_tool_call("nonexistent_tool")]
        with pytest.raises(ModelError):
            policy.admit_tool_batch(calls)
        assert counters.alpha == 0
        assert counters.beta == 0
        assert counters.write_alpha == 0


# ==============================================================================
# POL-13 — second batch rejected after first valid batch
# ==============================================================================


class TestPol13SecondBatchRejected:
    def test_second_valid_batch_rejected(self, policy: DndAgentPolicy) -> None:
        first = [_make_tool_call("read_alpha")]
        policy.admit_tool_batch(first)

        second = [_make_tool_call("read_beta")]
        with pytest.raises(ModelError) as excinfo:
            policy.admit_tool_batch(second)
        assert "already been observed" in str(excinfo.value)

    def test_zero_handler_calls(self, policy: DndAgentPolicy, counters: HandlerCounters) -> None:
        first = [_make_tool_call("read_alpha")]
        policy.admit_tool_batch(first)
        second = [_make_tool_call("read_beta")]
        with pytest.raises(ModelError):
            policy.admit_tool_batch(second)
        assert counters.alpha == 0
        assert counters.beta == 0


# ==============================================================================
# POL-14 — first rejected batch still consumes batch opportunity
# ==============================================================================


class TestPol14FirstRejectedConsumes:
    def test_rejected_first_still_blocks_second(self, policy: DndAgentPolicy) -> None:
        first = [_make_tool_call("read_alpha"), _make_tool_call("write_alpha")]
        with pytest.raises(ModelError):
            policy.admit_tool_batch(first)

        second = [_make_tool_call("read_alpha")]
        with pytest.raises(ModelError) as excinfo:
            policy.admit_tool_batch(second)
        assert "already been observed" in str(excinfo.value)

    def test_zero_handler_calls(self, policy: DndAgentPolicy, counters: HandlerCounters) -> None:
        first = [_make_tool_call("read_alpha"), _make_tool_call("write_alpha")]
        with pytest.raises(ModelError):
            policy.admit_tool_batch(first)
        second = [_make_tool_call("read_alpha")]
        with pytest.raises(ModelError):
            policy.admit_tool_batch(second)
        assert counters.alpha == 0
        assert counters.write_alpha == 0


# ==============================================================================
# POL-15 — new policy instance has fresh run state
# ==============================================================================


class TestPol15FreshPolicyInstance:
    def test_new_policy_instance_fresh_state(
        self,
        bridge: PydanticAIToolBridge,
        snapshot: PydanticAIToolSnapshot,
    ) -> None:
        pol_a = DndAgentPolicy(tool_bridge=bridge, snapshot=snapshot)
        pol_a.admit_tool_batch([_make_tool_call("read_alpha")])

        pol_b = DndAgentPolicy(tool_bridge=bridge, snapshot=snapshot)
        admission = pol_b.admit_tool_batch([_make_tool_call("read_beta")])
        assert len(admission.calls) == 1
        assert admission.calls[0].tool_name == "read_beta"


# ==============================================================================
# POL-16 — cross-bridge snapshot
# ==============================================================================


class TestPol16CrossBridgeSnapshot:
    def test_cross_bridge_snapshot_rejected(
        self, registry: ToolRegistry, snapshot: PydanticAIToolSnapshot
    ) -> None:
        bridge_b = PydanticAIToolBridge(registry=registry)
        with pytest.raises(ValidationError) as excinfo:
            DndAgentPolicy(tool_bridge=bridge_b, snapshot=snapshot)
        assert "different bridge" in str(excinfo.value)


# ==============================================================================
# POL-17 — copied snapshot (dataclasses.replace)
# ==============================================================================


class TestPol17CopiedSnapshot:
    def test_copied_snapshot_rejected(
        self, bridge: PydanticAIToolBridge, snapshot: PydanticAIToolSnapshot
    ) -> None:
        copied = dataclasses.replace(snapshot)
        with pytest.raises(ValidationError) as excinfo:
            DndAgentPolicy(tool_bridge=bridge, snapshot=copied)
        assert "not issued" in str(excinfo.value)


# ==============================================================================
# POL-18 — stolen owner token but non-issued snapshot
# ==============================================================================


class TestPol18StolenTokenNonIssued:
    def test_stolen_token_rejected(self, bridge: PydanticAIToolBridge) -> None:
        stolen = bridge._snapshot_owner_token  # type: ignore[attr-defined]
        forged = PydanticAIToolSnapshot._create(
            definitions=(READ_ALPHA_DEF,),
            owner_token=stolen,
        )
        with pytest.raises(ValidationError) as excinfo:
            DndAgentPolicy(tool_bridge=bridge, snapshot=forged)
        assert "not issued" in str(excinfo.value)


# ==============================================================================
# POL-19 — non-ToolCallPart in batch
# ==============================================================================


class TestPol19NonToolCallPart:
    def test_non_tool_call_part_rejected(self, policy: DndAgentPolicy) -> None:
        calls: list[object] = [object()]
        with pytest.raises(ValidationError) as excinfo:
            policy.admit_tool_batch(calls)  # type: ignore[arg-type]
        assert "ToolCallPart" in str(excinfo.value)


# ==============================================================================
# POL-20 — empty batch
# ==============================================================================


class TestPol20EmptyBatch:
    def test_empty_batch_rejected(self, policy: DndAgentPolicy) -> None:
        with pytest.raises(ValidationError) as excinfo:
            policy.admit_tool_batch([])
        assert "must not be empty" in str(excinfo.value)

    def test_empty_batch_does_not_consume_state(self, policy: DndAgentPolicy) -> None:
        with pytest.raises(ValidationError):
            policy.admit_tool_batch([])
        admission = policy.admit_tool_batch([_make_tool_call("read_alpha")])
        assert len(admission.calls) == 1


# ==============================================================================
# PAIM-C09 — Runtime Sequence validation + immutable tuple snapshot
# ==============================================================================
#
# | Scenario                              | Result         | State consumed |
# | ------------------------------------- | -------------- | -------------- |
# | C09-S1 arbitrary object               | ValidationError| NO             |
# | C09-S2 generator                      | ValidationError| NO             |
# | C09-S3 non-ToolCallPart entry         | ValidationError| NO             |
# | C09-S4 mutable list captured once     | admitted       | YES            |


class TestPaimC09SequenceBoundary:
    """PAIM-C09: Runtime Sequence validation and immutable tuple snapshot."""

    def test_c09_s1_arbitrary_object(self, policy: DndAgentPolicy) -> None:
        """Arbitrary object() raises ValidationError, does not consume state."""
        with pytest.raises(ValidationError) as excinfo:
            policy.admit_tool_batch(object())  # type: ignore[arg-type]
        assert "Sequence" in str(excinfo.value)

        # Subsequent valid batch is still admitted.
        admission = policy.admit_tool_batch([_make_tool_call("read_alpha")])
        assert len(admission.calls) == 1
        assert admission.calls[0].tool_name == "read_alpha"

    def test_c09_s2_generator(self, policy: DndAgentPolicy) -> None:
        """Generator expression raises ValidationError, does not consume state."""
        gen = (tc for tc in [_make_tool_call("read_alpha")])
        with pytest.raises(ValidationError) as excinfo:
            policy.admit_tool_batch(gen)  # type: ignore[arg-type]
        assert "Sequence" in str(excinfo.value)

        # Subsequent valid batch is still admitted.
        admission = policy.admit_tool_batch([_make_tool_call("read_alpha")])
        assert len(admission.calls) == 1

    def test_c09_s3_non_tool_call_part(self, policy: DndAgentPolicy) -> None:
        """Non-ToolCallPart entry raises ValidationError, does not consume state."""
        calls: list[object] = ["not_a_tool_call_part"]
        with pytest.raises(ValidationError) as excinfo:
            policy.admit_tool_batch(calls)  # type: ignore[arg-type]
        assert "ToolCallPart" in str(excinfo.value)

        # Subsequent valid batch is still admitted.
        admission = policy.admit_tool_batch([_make_tool_call("read_alpha")])
        assert len(admission.calls) == 1

    def test_c09_s4_mutable_list_captured_once(self, policy: DndAgentPolicy) -> None:
        """Mutable list is captured as an immutable tuple; caller mutation after
        the call returns does not affect the admission result."""
        original = [_make_tool_call("read_alpha"), _make_tool_call("read_beta")]
        admission = policy.admit_tool_batch(original)

        # Mutate the original list after the call.
        original.clear()

        # Admission result is independent of caller mutation.
        assert len(admission.calls) == 2
        assert admission.calls[0].tool_name == "read_alpha"
        assert admission.calls[1].tool_name == "read_beta"

    def test_c09_s5_five_calls_still_consumes_opportunity(
        self, read_only_policy: DndAgentPolicy
    ) -> None:
        """Structurally valid but policy-rejected batch (5 calls) still
        consumes the batch opportunity."""
        five = [
            _make_tool_call("read_alpha"),
            _make_tool_call("read_beta"),
            _make_tool_call("read_alpha"),
            _make_tool_call("read_beta"),
            _make_tool_call("read_alpha"),
        ]
        with pytest.raises(ModelError):
            read_only_policy.admit_tool_batch(five)

        # Second real batch is rejected (opportunity consumed).
        second = [_make_tool_call("read_alpha")]
        with pytest.raises(ModelError) as excinfo:
            read_only_policy.admit_tool_batch(second)
        assert "already been observed" in str(excinfo.value)

    def test_c09_s6_read_write_still_consumes_opportunity(self, policy: DndAgentPolicy) -> None:
        """Structurally valid but policy-rejected batch (READ+WRITE) still
        consumes the batch opportunity."""
        mixed = [_make_tool_call("read_alpha"), _make_tool_call("write_alpha")]
        with pytest.raises(ModelError):
            policy.admit_tool_batch(mixed)

        # Second real batch is rejected (opportunity consumed).
        second = [_make_tool_call("read_alpha")]
        with pytest.raises(ModelError) as excinfo:
            policy.admit_tool_batch(second)
        assert "already been observed" in str(excinfo.value)


# ==============================================================================
# POL-21 — argument-separation: policy does not parse args
# ==============================================================================


class TestPol21ArgumentSeparation:
    def test_malformed_args_still_admitted_by_policy(self, policy: DndAgentPolicy) -> None:
        calls = [
            ToolCallPart(
                tool_name="read_alpha",
                args="{broken",
                tool_call_id="call_1",
            )
        ]
        admission = policy.admit_tool_batch(calls)
        assert len(admission.calls) == 1
        assert admission.calls[0].tool_name == "read_alpha"

    def test_bridge_execute_rejects_malformed_args(
        self,
        bridge: PydanticAIToolBridge,
        snapshot: PydanticAIToolSnapshot,
    ) -> None:
        from dnd_assistant.tools.types import ExecutionContext

        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        call = ToolCallPart(
            tool_name="read_alpha",
            args="{broken",
            tool_call_id="call_1",
        )
        with pytest.raises(ValidationError) as excinfo:
            bridge.execute(snapshot, call, execution_context=ctx)
        assert "Failed to parse arguments" in str(excinfo.value)

    def test_zero_handler_calls(
        self,
        policy: DndAgentPolicy,
        counters: HandlerCounters,
    ) -> None:
        calls = [
            ToolCallPart(
                tool_name="read_alpha",
                args="{broken",
                tool_call_id="call_1",
            )
        ]
        policy.admit_tool_batch(calls)
        assert counters.alpha == 0


# ==============================================================================
# POL-22 — single WRITE authorization separation
# ==============================================================================


class TestPol22WriteAuthorizationSeparation:
    def test_single_write_admitted_by_policy(self, policy: DndAgentPolicy) -> None:
        calls = [_make_tool_call("write_alpha")]
        admission = policy.admit_tool_batch(calls)
        assert len(admission.calls) == 1
        assert admission.calls[0].tool_name == "write_alpha"

    def test_same_write_rejected_by_tool_executor_under_read_context(
        self,
        bridge: PydanticAIToolBridge,
        snapshot: PydanticAIToolSnapshot,
    ) -> None:
        from dnd_assistant.errors import ConflictError

        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.ACTIVE_SESSION,
            audit=None,
        )
        call = ToolCallPart(
            tool_name="write_alpha",
            args={"value": "test"},
            tool_call_id="call_1",
        )
        with pytest.raises(ConflictError) as excinfo:
            bridge.execute(snapshot, call, execution_context=ctx)
        assert "Permission denied" in str(excinfo.value)

    def test_zero_handler_calls(
        self,
        bridge: PydanticAIToolBridge,
        snapshot: PydanticAIToolSnapshot,
        counters: HandlerCounters,
    ) -> None:
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.ACTIVE_SESSION,
            audit=None,
        )
        call = ToolCallPart(
            tool_name="write_alpha",
            args={"value": "test"},
            tool_call_id="call_1",
        )
        from dnd_assistant.errors import ConflictError

        with pytest.raises(ConflictError):
            bridge.execute(snapshot, call, execution_context=ctx)
        assert counters.write_alpha == 0


# ==============================================================================
# Immutable admission proof
# ==============================================================================


class TestAdmissionImmutability:
    def test_admission_calls_is_tuple(self, policy: DndAgentPolicy) -> None:
        calls = [_make_tool_call("read_alpha")]
        admission = policy.admit_tool_batch(calls)
        assert isinstance(admission.calls, tuple)

    def test_cannot_append_to_calls(self, policy: DndAgentPolicy) -> None:
        calls = [_make_tool_call("read_alpha")]
        admission = policy.admit_tool_batch(calls)
        with pytest.raises(AttributeError):
            admission.calls.append(admission.calls[0])  # type: ignore[attr-defined]

    def test_admitted_tool_call_frozen(self, policy: DndAgentPolicy) -> None:
        calls = [_make_tool_call("read_alpha")]
        admission = policy.admit_tool_batch(calls)
        admitted = admission.calls[0]
        with pytest.raises(AttributeError):
            admitted.tool_name = "other"  # type: ignore[misc]

    def test_canonical_definition_identity(
        self, policy: DndAgentPolicy, snapshot: PydanticAIToolSnapshot
    ) -> None:
        calls = [_make_tool_call("read_alpha")]
        admission = policy.admit_tool_batch(calls)
        snapshot_def = snapshot.definitions[0]
        assert admission.calls[0].definition is snapshot_def

    def test_order_preserved(self, policy: DndAgentPolicy) -> None:
        calls = [
            _make_tool_call("read_beta"),
            _make_tool_call("read_alpha"),
        ]
        admission = policy.admit_tool_batch(calls)
        assert admission.calls[0].tool_name == "read_beta"
        assert admission.calls[1].tool_name == "read_alpha"
        assert admission.calls[0].position == 0
        assert admission.calls[1].position == 1


# ==============================================================================
# Constant parity with AgentLoop
# ==============================================================================


class TestConstantParity:
    def test_max_tool_calls_matches_agent_loop(self) -> None:
        from dnd_assistant.application.agent_loop import (
            MAX_TOOL_CALLS_PER_RUN as REF,
        )

        assert MAX_TOOL_CALLS_PER_RUN == REF == 4
