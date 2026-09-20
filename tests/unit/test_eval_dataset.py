"""Unit tests: product eval dataset contract and fingerprinting (S14-06)."""

from __future__ import annotations

import dataclasses

from dnd_assistant.evals.dataset import EvalDataset, EvalPermission
from dnd_assistant.evals.datasets.product_v1 import build_product_v1_dataset

PRODUCTION_TOOL_NAMES = {
    "search_entities",
    "get_entity",
    "patch_entity",
    "append_entity_fact",
    "get_active_session",
    "get_session",
    "list_sessions",
    "list_session_events",
    "start_session",
    "record_event",
    "record_note",
    "end_session",
}

PAIM_SYNTHETIC_NAMES = {
    "read_npc",
    "read_location",
    "read_quest",
    "write_quest_status",
    "write_campaign_note",
}


def _has_cyrillic(text: str) -> bool:
    return any("\u0400" <= ch <= "\u04ff" for ch in text)


def test_dataset_has_thirteen_stable_unique_ids() -> None:
    dataset = build_product_v1_dataset()
    ids = [case.scenario.scenario_id for case in dataset.cases]
    assert len(ids) == 13
    assert len(set(ids)) == 13
    assert all(scenario_id.startswith("EVAL-P1-") for scenario_id in ids)


def test_dataset_prompts_are_russian_and_non_empty() -> None:
    dataset = build_product_v1_dataset()
    for case in dataset.cases:
        assert case.scenario.user_input.strip()
        assert _has_cyrillic(case.scenario.user_input), case.scenario.scenario_id


def test_dataset_uses_only_current_production_tool_names() -> None:
    dataset = build_product_v1_dataset()
    for case in dataset.cases:
        for call in case.scenario.expectation.tool_calls:
            assert call.tool_name in PRODUCTION_TOOL_NAMES, call.tool_name
            assert call.tool_name not in PAIM_SYNTHETIC_NAMES


def test_dataset_expectations_are_explicit() -> None:
    dataset = build_product_v1_dataset()
    for case in dataset.cases:
        expectation = case.scenario.expectation
        for call in expectation.tool_calls:
            assert isinstance(call.arguments, dict)
            assert isinstance(call.is_write, bool)
        assert case.execution.permission in {EvalPermission.READ, EvalPermission.WRITE}
        assert case.execution.session_state is not None


def test_write_expected_calls_are_flagged_is_write() -> None:
    dataset = build_product_v1_dataset()
    for case in dataset.cases:
        expectation = case.scenario.expectation
        for call in expectation.tool_calls:
            if call.tool_name in {"record_note", "start_session", "append_entity_fact"}:
                assert call.is_write is True


def test_false_write_denominator_cases_exist() -> None:
    dataset = build_product_v1_dataset()
    denominator = [
        case
        for case in dataset.cases
        if case.execution.permission is EvalPermission.WRITE
        and not any(call.is_write for call in case.scenario.expectation.tool_calls)
    ]
    assert {case.scenario.scenario_id for case in denominator} == {
        "EVAL-P1-006",
        "EVAL-P1-008",
        "EVAL-P1-009",
    }


def test_hidden_write_case_exists() -> None:
    dataset = build_product_v1_dataset()
    hidden = [case for case in dataset.cases if case.scenario.hidden_write_expected]
    assert [case.scenario.scenario_id for case in hidden] == ["EVAL-P1-012"]


def test_fingerprint_is_stable_and_version_identity_present() -> None:
    first = build_product_v1_dataset()
    second = build_product_v1_dataset()
    assert first.fingerprint() == second.fingerprint()
    assert len(first.fingerprint()) == 64
    assert first.dataset_id == "product-agent"
    assert first.dataset_version == "1"
    assert first.sample_plan.fingerprint() == second.sample_plan.fingerprint()


def test_fingerprint_changes_when_semantic_ground_truth_changes() -> None:
    original = build_product_v1_dataset()
    changed_case = dataclasses.replace(
        original.cases[0],
        scenario=dataclasses.replace(original.cases[0].scenario, user_input="Изменённый вопрос?"),
    )
    changed = dataclasses.replace(original, cases=(changed_case, *original.cases[1:]))
    assert changed.fingerprint() != original.fingerprint()


def test_fingerprint_ignores_human_description() -> None:
    original = build_product_v1_dataset()
    rewording = dataclasses.replace(
        original.cases[0],
        scenario=dataclasses.replace(
            original.cases[0].scenario, description="Другое человеческое описание"
        ),
    )
    changed: EvalDataset = dataclasses.replace(original, cases=(rewording, *original.cases[1:]))
    assert changed.fingerprint() == original.fingerprint()
