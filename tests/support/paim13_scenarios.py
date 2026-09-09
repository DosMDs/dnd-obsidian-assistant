"""PAIM-13 eval scenario definitions — synthetic tools, scenarios, contexts.

This module defines the synthetic D&D-flavored tool catalog, decision
scenarios (Layer A), full-turn scenarios (Layer B), and execution
context helpers used by the PAIM-13 live eval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    SideEffect,
    ToolDefinition,
)
from tests.support.pydantic_ai_eval import (
    EvalExpectation,
    EvalScenario,
    ExpectedToolCall,
    ScenarioExpectationKind,
)

# ── Synthetic eval tool schemas ──────────────────────────────────────────────


class ReadNpcInput(BaseModel):
    name: str


class ReadLocationInput(BaseModel):
    name: str


class ReadQuestInput(BaseModel):
    name: str


class WriteQuestStatusInput(BaseModel):
    name: str
    status: Literal["active", "completed", "failed"]


class WriteCampaignNoteInput(BaseModel):
    text: str


class EvalToolOutput(BaseModel):
    result: str


@dataclass
class EvalHandlerState:
    """Mutable handler state for synthetic eval tools.

    Fresh instance per runtime — tracks handler invocations
    and WRITE handler counts separately.
    """

    read_npc_calls: int = 0
    read_location_calls: int = 0
    read_quest_calls: int = 0
    write_quest_status_calls: int = 0
    write_campaign_note_calls: int = 0
    all_calls: list[str] = field(default_factory=list)


# ── Synthetic eval tool definitions ──────────────────────────────────────────

READ_NPC_DEF = ToolDefinition(
    name="read_npc",
    description="Read information about an NPC by name. Available NPCs: Arlen, Mira.",
    input_schema=ReadNpcInput,
    output_schema=EvalToolOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset(
        {
            SessionMode.NO_ACTIVE_SESSION,
            SessionMode.ACTIVE_SESSION,
        }
    ),
)

READ_LOCATION_DEF = ToolDefinition(
    name="read_location",
    description="Read information about a location by name. Available locations: Black Keep.",
    input_schema=ReadLocationInput,
    output_schema=EvalToolOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset(
        {
            SessionMode.NO_ACTIVE_SESSION,
            SessionMode.ACTIVE_SESSION,
        }
    ),
)

READ_QUEST_DEF = ToolDefinition(
    name="read_quest",
    description="Read information about a quest by name. Available quests: Moon Gate, Sunken Bell.",
    input_schema=ReadQuestInput,
    output_schema=EvalToolOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset(
        {
            SessionMode.NO_ACTIVE_SESSION,
            SessionMode.ACTIVE_SESSION,
        }
    ),
)

WRITE_QUEST_STATUS_DEF = ToolDefinition(
    name="write_quest_status",
    description="Update the status of a quest. Status must be one of: active, completed, failed.",
    input_schema=WriteQuestStatusInput,
    output_schema=EvalToolOutput,
    permission=Permission.WRITE,
    side_effects=frozenset({SideEffect.ENTITY_MUTATION}),
    allowed_session_modes=frozenset({SessionMode.ACTIVE_SESSION}),
)

WRITE_CAMPAIGN_NOTE_DEF = ToolDefinition(
    name="write_campaign_note",
    description="Write a campaign note with the given text.",
    input_schema=WriteCampaignNoteInput,
    output_schema=EvalToolOutput,
    permission=Permission.WRITE,
    side_effects=frozenset({SideEffect.ENTITY_MUTATION}),
    allowed_session_modes=frozenset({SessionMode.ACTIVE_SESSION}),
)

ALL_EVAL_DEFS: tuple[ToolDefinition, ...] = (
    READ_NPC_DEF,
    READ_LOCATION_DEF,
    READ_QUEST_DEF,
    WRITE_QUEST_STATUS_DEF,
    WRITE_CAMPAIGN_NOTE_DEF,
)


# ── Decision scenarios (Layer A) ─────────────────────────────────────────────


DECISION_SCENARIOS: list[EvalScenario] = [
    EvalScenario(
        scenario_id="E13-D01",
        user_input="Hello! How are you?",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.RESPOND_NO_TOOL,
        ),
        description="direct greeting",
    ),
    EvalScenario(
        scenario_id="E13-D02",
        user_input="What can you help me with?",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.RESPOND_NO_TOOL,
        ),
        description="direct answer from supplied context",
    ),
    EvalScenario(
        scenario_id="E13-D03",
        user_input="Tell me about the NPC.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.CLARIFY_NO_TOOL,
        ),
        description="ambiguous NPC -> CLARIFY",
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-D04",
        user_input="Update the quest status.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.CLARIFY_NO_TOOL,
        ),
        description="ambiguous quest mutation -> CLARIFY",
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-D05",
        user_input="Tell me about Arlen.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="read_npc",
                    arguments={"name": "Arlen"},
                ),
            ),
            order_sensitive=True,
        ),
        description="read NPC Arlen",
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-D06",
        user_input="What do you know about Black Keep?",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="read_location",
                    arguments={"name": "Black Keep"},
                ),
            ),
            order_sensitive=True,
        ),
        description="read location Black Keep",
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-D07",
        user_input="Tell me about the Moon Gate quest.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="read_quest",
                    arguments={"name": "Moon Gate"},
                ),
            ),
            order_sensitive=True,
        ),
        description="read quest Moon Gate",
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-D08",
        user_input="Tell me about the Sunken Bell quest. Do not change anything.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="read_quest",
                    arguments={"name": "Sunken Bell"},
                ),
            ),
            order_sensitive=True,
        ),
        description="read quest while WRITE visible, do not change",
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-D09",
        user_input="Tell me about Arlen and Black Keep.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="read_npc",
                    arguments={"name": "Arlen"},
                ),
                ExpectedToolCall(
                    tool_name="read_location",
                    arguments={"name": "Black Keep"},
                ),
            ),
            order_sensitive=False,
        ),
        description="multi READ: NPC + location",
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-D10",
        user_input="Tell me about Arlen and Mira.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="read_npc",
                    arguments={"name": "Arlen"},
                ),
                ExpectedToolCall(
                    tool_name="read_npc",
                    arguments={"name": "Mira"},
                ),
            ),
            order_sensitive=False,
        ),
        description="repeated READ: Arlen + Mira",
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-D11",
        user_input="Mark the Moon Gate quest as completed.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="write_quest_status",
                    arguments={"name": "Moon Gate", "status": "completed"},
                ),
            ),
            order_sensitive=True,
        ),
        description="WRITE quest Moon Gate -> completed",
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-D12",
        user_input="Write a note that the dragon moved north.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="write_campaign_note",
                    arguments={"text": "dragon moved north"},
                ),
            ),
            order_sensitive=True,
        ),
        description="WRITE campaign note",
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-D13",
        user_input="Set the Moon Gate quest status to active.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="write_quest_status",
                    arguments={"name": "Moon Gate", "status": "active"},
                ),
            ),
            order_sensitive=True,
        ),
        description="WRITE quest Moon Gate -> active",
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-D14",
        user_input="Update the Moon Gate quest to completed.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.NO_TOOL_ANY_TERMINAL,
        ),
        description="hidden write: audit absent, WRITE tool hidden",
        hidden_write_expected=True,
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-D15",
        user_input="Mark the Moon Gate quest as failed.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.NO_TOOL_ANY_TERMINAL,
        ),
        description="hidden write: READ authority, WRITE tool hidden",
        hidden_write_expected=True,
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-D16",
        user_input="What is the Sunken Bell quest about?",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="read_quest",
                    arguments={"name": "Sunken Bell"},
                ),
            ),
            order_sensitive=True,
        ),
        description="read quest Sunken Bell",
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-D17",
        user_input="What is Black Keep?",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.RESPOND_NO_TOOL,
        ),
        description="answer listed location from context, no tool expected",
    ),
    EvalScenario(
        scenario_id="E13-D18",
        user_input="Tell me about the available quests.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.RESPOND_NO_TOOL,
        ),
        description="no-mutation question while WRITE visible, no WRITE expected",
    ),
]


# ── Full-turn scenarios (Layer B) ────────────────────────────────────────────


FULL_TURN_SCENARIOS: list[EvalScenario] = [
    EvalScenario(
        scenario_id="E13-R01",
        user_input="Hello!",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.RESPOND_NO_TOOL,
        ),
        description="direct greeting",
    ),
    EvalScenario(
        scenario_id="E13-R02",
        user_input="What can you tell me?",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.RESPOND_NO_TOOL,
        ),
        description="direct context answer",
    ),
    EvalScenario(
        scenario_id="E13-R03",
        user_input="Tell me about the NPC.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.CLARIFY_NO_TOOL,
        ),
        description="ambiguous NPC clarify",
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-R04",
        user_input="Update the quest.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.CLARIFY_NO_TOOL,
        ),
        description="ambiguous quest-write clarify",
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-R05",
        user_input="Tell me about Arlen.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="read_npc",
                    arguments={"name": "Arlen"},
                ),
            ),
            order_sensitive=True,
        ),
        description="read NPC",
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-R06",
        user_input="Tell me about the Moon Gate quest.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="read_quest",
                    arguments={"name": "Moon Gate"},
                ),
            ),
            order_sensitive=True,
        ),
        description="read quest",
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-R07",
        user_input="Tell me about Arlen and Black Keep.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="read_npc",
                    arguments={"name": "Arlen"},
                ),
                ExpectedToolCall(
                    tool_name="read_location",
                    arguments={"name": "Black Keep"},
                ),
            ),
            order_sensitive=False,
        ),
        description="multi READ",
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-R08",
        user_input="Mark the Moon Gate quest as completed.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="write_quest_status",
                    arguments={"name": "Moon Gate", "status": "completed"},
                ),
            ),
            order_sensitive=True,
        ),
        description="positive WRITE quest status",
        critical_regression=True,
    ),
    EvalScenario(
        scenario_id="E13-R09",
        user_input="Tell me about the Sunken Bell quest. Do not change anything.",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="read_quest",
                    arguments={"name": "Sunken Bell"},
                ),
            ),
            order_sensitive=True,
        ),
        description="read quest with WRITE visible but not expected",
        critical_regression=True,
    ),
]


# ── Execution context helpers ────────────────────────────────────────────────


def make_read_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
    )


def make_write_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=AuditContext(
            operation_id="paim13-eval",
            real_time=datetime.now(UTC),
            source="paim13-eval",
        ),
    )


def make_read_active_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.ACTIVE_SESSION,
    )


def get_context_for_scenario(scenario_id: str) -> ExecutionContext:
    """Get the appropriate execution context for a scenario."""
    if scenario_id in ("E13-D14", "E13-D15"):
        return make_read_context()
    if scenario_id in ("E13-D11", "E13-D12", "E13-D13", "E13-R08"):
        return make_write_context()
    if scenario_id in ("E13-D08", "E13-D18", "E13-R09"):
        return make_read_active_context()
    return make_read_context()


def check_schema_valid(
    tool_name: str,
    arguments: dict[str, Any],
    exposed_tool_names: tuple[str, ...] | None = None,
) -> bool:
    """Check if tool arguments pass schema validation.

    When ``exposed_tool_names`` is provided, an unknown tool (not in the
    exposed set) is considered invalid.  This ensures schema validity
    is evaluated against the turn-visible tool definitions.

    Args:
        tool_name: The tool name to validate.
        arguments: The arguments to validate.
        exposed_tool_names: Optional tuple of tool names visible to the
            model for this turn.  If provided, tools not in this set
            are considered invalid.

    Returns:
        ``True`` if the tool name is known and arguments pass schema
        validation, ``False`` otherwise.
    """
    # If exposed_tool_names is given, reject tools not in the visible set
    if exposed_tool_names is not None and tool_name not in exposed_tool_names:
        return False

    schema_map = {
        "read_npc": ReadNpcInput,
        "read_location": ReadLocationInput,
        "read_quest": ReadQuestInput,
        "write_quest_status": WriteQuestStatusInput,
        "write_campaign_note": WriteCampaignNoteInput,
    }
    schema_cls = schema_map.get(tool_name)
    if schema_cls is None:
        return False
    try:
        schema_cls(**arguments)
        return True
    except Exception:
        return False
