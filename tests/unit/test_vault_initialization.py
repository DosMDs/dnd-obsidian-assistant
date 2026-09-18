"""S13-01 unit tests: config codec, managed layout and application policy."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from dnd_assistant.application.vault_initialization import (
    VaultInitializationResult,
    VaultInitializationService,
    VaultInitializationStatus,
    generate_campaign_id,
)
from dnd_assistant.errors import StorageError
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.storage.types import EntityDirectory
from dnd_assistant.storage.vault_initialization import (
    CAMPAIGN_CONFIG_RELATIVE,
    MANAGED_DIRECTORIES,
    CampaignConfigState,
    VaultInitializationOutcome,
    VaultLayoutReport,
    parse_campaign_config,
    serialize_new_campaign_config,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _audit() -> AuditContext:
    from datetime import UTC, datetime

    return AuditContext(
        operation_id="op-1",
        real_time=datetime(2026, 9, 18, tzinfo=UTC),
        source="test",
    )


class _FakeInitializer:
    def __init__(
        self,
        report: VaultLayoutReport,
        *,
        outcome: VaultInitializationOutcome | None = None,
    ) -> None:
        self._report = report
        self._outcome = outcome
        self.inspect_calls = 0
        self.commit_calls: list[str] = []
        self.repair_calls = 0

    def inspect(self) -> VaultLayoutReport:
        self.inspect_calls += 1
        return self._report

    def commit_initialization(
        self, campaign_id: str, *, audit: AuditContext
    ) -> VaultInitializationOutcome:
        self.commit_calls.append(campaign_id)
        if self._outcome is not None:
            return self._outcome
        return VaultInitializationOutcome(
            campaign_id=campaign_id,
            created_directories=(Path("Sessions"),),
            published_config=True,
        )

    def repair_layout(self, *, audit: AuditContext) -> VaultInitializationOutcome:
        self.repair_calls += 1
        if self._outcome is not None:
            return self._outcome
        return VaultInitializationOutcome(
            campaign_id="camp_existing",
            created_directories=(Path("Locations"),),
            published_config=False,
        )


# ── parse_campaign_config ────────────────────────────────────────────────────


class TestParseCampaignConfig:
    def test_minimal_valid(self) -> None:
        envelope = parse_campaign_config("schema_version: 1\ncampaign_id: camp_abc\n")
        assert envelope.campaign_id == "camp_abc"

    def test_extra_keys_are_opaque_and_accepted(self) -> None:
        text = (
            "schema_version: 1\n"
            "campaign_id: camp_golden_001\n"
            "campaign_name: Тени над Серым Бродом\n"
            "calendar_id: golden_calendar\n"
            "assistant:\n"
            "  perspective: player\n"
            "features:\n"
            "  embeddings: false\n"
        )
        envelope = parse_campaign_config(text)
        assert envelope.campaign_id == "camp_golden_001"

    def test_missing_schema_version_rejected(self) -> None:
        with pytest.raises(StorageError, match="schema_version"):
            parse_campaign_config("campaign_id: camp_abc\n")

    def test_unsupported_schema_version_rejected(self) -> None:
        with pytest.raises(StorageError, match="schema_version"):
            parse_campaign_config("schema_version: 2\ncampaign_id: camp_abc\n")

    def test_bool_schema_version_rejected(self) -> None:
        with pytest.raises(StorageError, match="schema_version"):
            parse_campaign_config("schema_version: true\ncampaign_id: camp_abc\n")

    def test_missing_campaign_id_rejected(self) -> None:
        with pytest.raises(StorageError, match="campaign_id"):
            parse_campaign_config("schema_version: 1\n")

    def test_empty_campaign_id_rejected(self) -> None:
        with pytest.raises(StorageError, match="campaign_id"):
            parse_campaign_config("schema_version: 1\ncampaign_id: ''\n")

    def test_invalid_yaml_rejected(self) -> None:
        with pytest.raises(StorageError):
            parse_campaign_config("schema_version: [unclosed\n")

    def test_non_mapping_root_rejected(self) -> None:
        with pytest.raises(StorageError):
            parse_campaign_config("- a\n- b\n")

    def test_cyrillic_campaign_id_accepted(self) -> None:
        envelope = parse_campaign_config("schema_version: 1\ncampaign_id: кампания\n")
        assert envelope.campaign_id == "кампания"


# ── serialize_new_campaign_config ────────────────────────────────────────────


class TestSerializeNewCampaignConfig:
    def test_writes_only_minimum_core(self) -> None:
        text = serialize_new_campaign_config("camp_abc")
        assert "schema_version: 1" in text
        assert "campaign_id: camp_abc" in text
        # No inferred campaign metadata.
        assert "campaign_name" not in text
        assert "calendar" not in text
        assert "features" not in text

    def test_round_trip(self) -> None:
        text = serialize_new_campaign_config("camp_round")
        assert parse_campaign_config(text).campaign_id == "camp_round"

    def test_cyrillic_round_trip(self) -> None:
        text = serialize_new_campaign_config("кампания-1")
        assert parse_campaign_config(text).campaign_id == "кампания-1"

    def test_invalid_id_rejected(self) -> None:
        with pytest.raises(StorageError):
            serialize_new_campaign_config("")


# ── MANAGED_DIRECTORIES ──────────────────────────────────────────────────────


class TestManagedDirectories:
    def test_contains_required_runtime_roots(self) -> None:
        as_str = {p.as_posix() for p in MANAGED_DIRECTORIES}
        assert {
            "Sessions",
            "_system",
            "_system/raw",
            "_system/raw/sessions",
            "_system/audit",
        } <= as_str

    def test_derives_entity_directories(self) -> None:
        as_str = {p.as_posix() for p in MANAGED_DIRECTORIES}
        for entity_directory in EntityDirectory:
            assert entity_directory.value in as_str

    def test_parents_precede_children(self) -> None:
        seen: set[Path] = set()
        for relative in MANAGED_DIRECTORIES:
            for parent in relative.parents:
                if parent != Path("."):
                    assert parent in seen, f"{parent} not created before {relative}"
            seen.add(relative)

    def test_no_derived_or_speculative_directories(self) -> None:
        as_str = {p.as_posix() for p in MANAGED_DIRECTORIES}
        forbidden = {
            "_system/indexes",
            "_system/changesets",
            "_system/cache",
            "State",
            "Campaign",
            "Events",
        }
        assert not (as_str & forbidden)


# ── generate_campaign_id ─────────────────────────────────────────────────────


class TestGenerateCampaignId:
    def test_format(self) -> None:
        value = generate_campaign_id()
        assert value.startswith("camp_")
        assert len(value) == len("camp_") + 32
        int(value.removeprefix("camp_"), 16)

    def test_unique(self) -> None:
        assert generate_campaign_id() != generate_campaign_id()


# ── VaultInitializationService ───────────────────────────────────────────────


def _report(state: CampaignConfigState, campaign_id: str | None, missing: tuple[Path, ...]):
    return VaultLayoutReport(
        config_state=state,
        campaign_id=campaign_id,
        missing_directories=missing,
    )


class TestServiceAlreadyInitialized:
    def test_valid_full_layout_is_zero_write(self) -> None:
        fake = _FakeInitializer(_report(CampaignConfigState.VALID, "camp_x", ()))
        factory_calls: list[int] = []
        service = VaultInitializationService(
            fake, campaign_id_factory=lambda: factory_calls.append(1) or "camp_new"
        )
        result = service.initialize(audit=_audit())
        assert result.status is VaultInitializationStatus.ALREADY_INITIALIZED
        assert result.campaign_id == "camp_x"
        assert result.created_directories == ()
        assert result.audit_recorded is False
        assert fake.commit_calls == []
        assert fake.repair_calls == 0
        assert factory_calls == []


class TestServiceCompletedPartial:
    def test_valid_missing_dirs_triggers_audited_repair(self) -> None:
        fake = _FakeInitializer(_report(CampaignConfigState.VALID, "camp_x", (Path("Locations"),)))
        factory_calls: list[int] = []
        service = VaultInitializationService(
            fake, campaign_id_factory=lambda: factory_calls.append(1) or "camp_new"
        )
        result = service.initialize(audit=_audit())
        assert result.status is VaultInitializationStatus.COMPLETED_PARTIAL
        assert result.campaign_id == "camp_existing"
        assert result.created_directories == ("Locations",)
        assert result.audit_recorded is True
        assert fake.repair_calls == 1
        assert fake.commit_calls == []
        assert factory_calls == []


class TestServiceCreated:
    def test_absent_config_calls_factory_once_and_commits(self) -> None:
        fake = _FakeInitializer(_report(CampaignConfigState.ABSENT, None, (Path("Sessions"),)))
        factory_calls: list[int] = []
        service = VaultInitializationService(
            fake, campaign_id_factory=lambda: factory_calls.append(1) or "camp_new"
        )
        result = service.initialize(audit=_audit())
        assert result.status is VaultInitializationStatus.CREATED
        assert result.campaign_id == "camp_new"
        assert result.created_directories == ("Sessions",)
        assert result.audit_recorded is True
        assert fake.commit_calls == ["camp_new"]
        assert factory_calls == [1]

    def test_concurrent_adoption_maps_to_already_initialized(self) -> None:
        fake = _FakeInitializer(
            _report(CampaignConfigState.ABSENT, None, ()),
            outcome=VaultInitializationOutcome(
                campaign_id="camp_winner",
                created_directories=(),
                published_config=False,
            ),
        )
        service = VaultInitializationService(fake, campaign_id_factory=lambda: "camp_loser")
        result = service.initialize(audit=_audit())
        assert result.status is VaultInitializationStatus.ALREADY_INITIALIZED
        assert result.campaign_id == "camp_winner"


def test_result_is_frozen() -> None:
    result = VaultInitializationResult(
        status=VaultInitializationStatus.CREATED,
        campaign_id="camp_x",
        created_directories=(),
        config_relative_path=CAMPAIGN_CONFIG_RELATIVE.as_posix(),
        audit_recorded=True,
    )
    with pytest.raises(FrozenInstanceError):
        result.campaign_id = "changed"  # type: ignore[misc]
