"""S13-03 bootstrap extraction request, validation and merge tests."""

from __future__ import annotations

import pytest

from dnd_assistant.application.bootstrap_extraction import (
    BootstrapExtractionError,
    BootstrapExtractionFailureReason,
    build_bootstrap_extraction_request,
    merge_bootstrap_extractions,
    run_bootstrap_extraction,
    validate_bootstrap_extraction,
)
from dnd_assistant.application.bootstrap_input import prepare_bootstrap_input
from dnd_assistant.application.vault_discovery import SourceClass
from dnd_assistant.domain.bootstrap_extraction import (
    BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
    BootstrapClaim,
    BootstrapEntityReference,
    BootstrapExtraction,
)
from dnd_assistant.domain.types import EntityType
from tests.unit.bootstrap.helpers import (
    FakeBootstrapModel,
    make_candidate,
    make_claim,
    make_reference,
    make_report,
    make_source,
)


def _projection():
    return prepare_bootstrap_input(
        make_report("camp-1", [make_source("Notes/a.md", SourceClass.USER_SOURCE, "варос")])
    )


def _request():
    projection = _projection()
    return build_bootstrap_extraction_request(
        projection,
        projection.batches[0],
        processor_version="p",
        prompt_version="v",
    )


def test_fabricated_source_reference_is_rejected() -> None:
    request = _request()
    extraction = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(make_candidate("c1", "Варос", EntityType.NPC, ["src_" + "b" * 32]),),
    )
    with pytest.raises(BootstrapExtractionError) as exc:
        validate_bootstrap_extraction(extraction, request)
    assert exc.value.reason is BootstrapExtractionFailureReason.INVALID_SOURCE_REFERENCE


def test_valid_source_reference_is_kept_and_deduplicated() -> None:
    request = _request()
    ref = request.expected_source_refs[0]
    extraction = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(make_candidate("c1", "Варос", EntityType.NPC, [ref, ref]),),
    )
    validated = validate_bootstrap_extraction(extraction, request)
    assert validated.extraction.candidates[0].source_refs == (ref,)


def test_duplicate_candidate_id_rejected() -> None:
    request = _request()
    ref = request.expected_source_refs[0]
    extraction = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(
            make_candidate("c1", "A", EntityType.NPC, [ref]),
            make_candidate("c1", "B", EntityType.NPC, [ref]),
        ),
    )
    with pytest.raises(BootstrapExtractionError) as exc:
        validate_bootstrap_extraction(extraction, request)
    assert exc.value.reason is BootstrapExtractionFailureReason.DUPLICATE_CANDIDATE_ID


def test_duplicate_reference_id_rejected_across_claims() -> None:
    request = _request()
    ref = request.expected_source_refs[0]
    reference = make_reference("r1", "Варос", EntityType.NPC, [ref])
    extraction = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        claims=(
            make_claim("k1", "fact one", [ref], references=[reference]),
            make_claim("k2", "fact two", [ref], references=[reference]),
        ),
    )
    with pytest.raises(BootstrapExtractionError) as exc:
        validate_bootstrap_extraction(extraction, request)
    assert exc.value.reason is BootstrapExtractionFailureReason.DUPLICATE_REFERENCE_ID


def test_schema_version_mismatch_rejected() -> None:
    request = _request()
    extraction = BootstrapExtraction(schema_version=999)
    with pytest.raises(BootstrapExtractionError) as exc:
        validate_bootstrap_extraction(extraction, request)
    assert exc.value.reason is BootstrapExtractionFailureReason.UNSUPPORTED_SCHEMA_VERSION


def test_merge_preserves_order_and_rejects_cross_batch_duplicates() -> None:
    ref = "src_" + "a" * 32
    first = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(make_candidate("c1", "A", EntityType.NPC, [ref]),),
    )
    second = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(make_candidate("c2", "B", EntityType.ITEM, [ref]),),
    )
    merged = merge_bootstrap_extractions([first, second])
    assert [c.candidate_id for c in merged.candidates] == ["c1", "c2"]

    duplicate = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(make_candidate("c1", "A", EntityType.NPC, [ref]),),
    )
    with pytest.raises(BootstrapExtractionError) as exc:
        merge_bootstrap_extractions([first, duplicate])
    assert exc.value.reason is BootstrapExtractionFailureReason.DUPLICATE_CANDIDATE_ID


def test_run_bootstrap_extraction_surfaces_model_failure() -> None:
    request = _request()
    error = BootstrapExtractionError(BootstrapExtractionFailureReason.MODEL_UNAVAILABLE, "down")
    with pytest.raises(BootstrapExtractionError) as exc:
        run_bootstrap_extraction(FakeBootstrapModel(error=error), request)
    assert exc.value.reason is BootstrapExtractionFailureReason.MODEL_UNAVAILABLE


def test_request_context_is_never_empty() -> None:
    projection = prepare_bootstrap_input(
        make_report("camp-1", [make_source("Notes/a.md", SourceClass.USER_SOURCE, "x")])
    )
    request = build_bootstrap_extraction_request(
        projection, projection.batches[0], processor_version="p", prompt_version="v"
    )
    assert request.context_text
    assert request.batch_id == "batch_0"


def test_claim_references_are_sanitized() -> None:
    request = _request()
    ref = request.expected_source_refs[0]
    claim = BootstrapClaim(
        claim_id="k1",
        text="fact",
        source_refs=(ref,),
        references=(
            BootstrapEntityReference(
                reference_id="r1",
                text="Варос",
                entity_type=EntityType.NPC,
                source_refs=(ref,),
            ),
        ),
    )
    validated = validate_bootstrap_extraction(
        BootstrapExtraction(schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION, claims=(claim,)),
        request,
    )
    assert validated.extraction.claims[0].references[0].reference_id == "r1"
