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
    MAX_BOOTSTRAP_CLAIMS,
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


def test_merge_scopes_batch_local_ids_deterministically() -> None:
    ref = "src_" + "a" * 32
    reference = make_reference("r1", "Варос", EntityType.NPC, [ref])
    first = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(make_candidate("c1", "A", EntityType.NPC, [ref]),),
        claims=(make_claim("claim1", "fact", [ref], references=[reference]),),
    )
    second = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(make_candidate("c1", "B", EntityType.ITEM, [ref]),),
        claims=(make_claim("claim1", "other", [ref], references=[reference]),),
    )
    merged = merge_bootstrap_extractions([first, second])
    candidate_ids = [c.candidate_id for c in merged.candidates]
    claim_ids = [c.claim_id for c in merged.claims]
    reference_ids = [r.reference_id for c in merged.claims for r in c.references]
    assert len(candidate_ids) == len(set(candidate_ids)) == 2
    assert len(claim_ids) == len(set(claim_ids)) == 2
    assert len(reference_ids) == len(set(reference_ids)) == 2
    # Retry-stable and batch-order deterministic.
    assert merge_bootstrap_extractions([first, second]) == merged


def test_merge_does_not_create_false_cross_batch_conflict_group() -> None:
    ref = "src_" + "a" * 32
    first = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        claims=(make_claim("k1", "fact", [ref], conflict_group="g1"),),
    )
    second = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        claims=(make_claim("k1", "fact", [ref], conflict_group="g1"),),
    )
    merged = merge_bootstrap_extractions([first, second])
    groups = [c.conflict_group for c in merged.claims]
    assert groups[0] is not None and groups[1] is not None
    assert groups[0] != groups[1]


def test_merge_run_wide_claim_overflow_fails_typed() -> None:
    ref = "src_" + "a" * 32
    one = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        claims=(make_claim("k1", "fact", [ref]),),
    )
    extractions = [one] * (MAX_BOOTSTRAP_CLAIMS + 1)
    with pytest.raises(BootstrapExtractionError) as exc:
        merge_bootstrap_extractions(extractions)
    assert exc.value.reason is BootstrapExtractionFailureReason.OUTPUT_BOUNDS_EXCEEDED


def test_merge_run_wide_total_char_overflow_fails_typed() -> None:
    from dnd_assistant.application.bootstrap_extraction import (
        MAX_BOOTSTRAP_EXTRACTION_TOTAL_CHARS,
    )

    ref = "src_" + "a" * 32
    big = "x" * 4000
    batches: list[BootstrapExtraction] = []
    total = 0
    while total <= MAX_BOOTSTRAP_EXTRACTION_TOTAL_CHARS:
        batches.append(
            BootstrapExtraction(
                schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
                claims=(make_claim("k1", big, [ref]),),
            )
        )
        total += len(big) + len(ref)
    with pytest.raises(BootstrapExtractionError) as exc:
        merge_bootstrap_extractions(batches)
    assert exc.value.reason is BootstrapExtractionFailureReason.OUTPUT_BOUNDS_EXCEEDED


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
