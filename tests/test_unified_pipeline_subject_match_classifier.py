"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-FINAL-HARDENING-1: direct unit tests of
`services.editorial_pipeline.subject_match.classify_subject_match()` - the real, central,
deterministic subject-match authority this phase wires into `MediaResearchService.research()`.

Deliberately spans multiple domains (product/version, vehicle, person, event) - the classifier
itself is generic (driven entirely by whatever `MediaIntent` fields a caller supplies), and this
suite proves that genericity directly rather than only ever re-testing one product family."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from schemas.media_intent import DesiredVisualType, MediaIntent, MediaSubjectType
from schemas.media_subject_match import (
    DiscoveryTier,
    MediaProvenance,
    MediaUsageClassification,
    ResolvedMediaCandidate,
    SubjectMatchClassification,
)
from services.editorial_pipeline.subject_match import classify_subject_match

pytestmark = pytest.mark.asyncio


def _candidate(caption_or_alt: str | None, *, candidate_id: str = "c1") -> ResolvedMediaCandidate:
    return ResolvedMediaCandidate(
        candidate_id=candidate_id,
        provenance=MediaProvenance(
            origin_url="https://example.com/article",
            asset_url="https://example.com/image.jpg",
            discovered_at=datetime.now(timezone.utc),
            discovery_tier=DiscoveryTier.TIER4_WEB_IMAGE_DISCOVERY,
            caption_or_alt=caption_or_alt,
        ),
        usage_classification=MediaUsageClassification.EDITORIAL_REVIEW_REQUIRED,
    )


def _intent(
    *, primary_entity: str, product_name: str | None = None, model_name: str | None = None,
    company: str | None = None, person: str | None = None, event: str | None = None,
    must_show: list[str] | None = None, must_not_imply: list[str] | None = None,
) -> MediaIntent:
    return MediaIntent(
        subject_type=MediaSubjectType.PRODUCT, primary_entity=primary_entity,
        product_name=product_name, model_name=model_name, company=company, person=person, event=event,
        must_show=must_show or [], must_not_imply=must_not_imply or [],
        desired_visual_type=DesiredVisualType.PRODUCT_PHOTO,
    )


# ---------------------------------------------------------------------------
# 1. Same brand, wrong exact product
# ---------------------------------------------------------------------------


async def test_same_brand_wrong_exact_product_is_strong_context_not_exact() -> None:
    intent = _intent(
        primary_entity="Acme flagship laptop", company="Acme", product_name="Acme laptop",
        model_name="Acme UltraBook Pro 16",
    )
    candidate = _candidate("Acme mini tablet, 8-inch, entry-level lineup")
    result = await classify_subject_match(candidate, intent)
    assert result.subject_match == SubjectMatchClassification.STRONG_CONTEXT
    assert result.subject_match != SubjectMatchClassification.EXACT_SUBJECT


# ---------------------------------------------------------------------------
# 2. Same product family, wrong generation/version
# ---------------------------------------------------------------------------


async def test_same_product_family_wrong_generation_is_strong_context_not_exact() -> None:
    intent = _intent(
        primary_entity="Acme UltraBook Pro 16 (2027)", company="Acme", product_name="Acme UltraBook",
        model_name="Acme UltraBook Pro 16 (2027)",
    )
    candidate = _candidate("Acme UltraBook Pro 14 (2024), previous generation model")
    result = await classify_subject_match(candidate, intent)
    assert result.subject_match == SubjectMatchClassification.STRONG_CONTEXT
    assert result.confidence in ("medium", "low")


# ---------------------------------------------------------------------------
# 3. Correct exact subject
# ---------------------------------------------------------------------------


async def test_correct_exact_subject_is_exact_subject() -> None:
    intent = _intent(
        primary_entity="Acme UltraBook Pro 16 (2027)", company="Acme", product_name="Acme UltraBook",
        model_name="Acme UltraBook Pro 16 (2027)",
    )
    candidate = _candidate("The new Acme UltraBook Pro 16 (2027), official press photo")
    result = await classify_subject_match(candidate, intent)
    assert result.subject_match == SubjectMatchClassification.EXACT_SUBJECT
    assert result.confidence == "high"


# ---------------------------------------------------------------------------
# 4. Strong contextual candidate
# ---------------------------------------------------------------------------


async def test_strong_contextual_candidate() -> None:
    intent = _intent(
        primary_entity="Acme corporate announcement", company="Acme",
    )
    candidate = _candidate("Acme corporate headquarters building, exterior photo")
    result = await classify_subject_match(candidate, intent)
    assert result.subject_match == SubjectMatchClassification.STRONG_CONTEXT


# ---------------------------------------------------------------------------
# 5. Generic contextual candidate
# ---------------------------------------------------------------------------


async def test_generic_contextual_candidate() -> None:
    intent = _intent(primary_entity="AI regulation policy debate")
    candidate = _candidate("A stock photo of a laptop keyboard close-up")
    result = await classify_subject_match(candidate, intent)
    assert result.subject_match == SubjectMatchClassification.GENERIC_CONTEXT


# ---------------------------------------------------------------------------
# 6. Explicit mismatch with excellent technical quality
# ---------------------------------------------------------------------------


async def test_explicit_mismatch_with_excellent_technical_quality_still_mismatches() -> None:
    intent = _intent(
        primary_entity="Acme UltraBook Pro 16 (2027)", company="Acme", product_name="Acme UltraBook",
        model_name="Acme UltraBook Pro 16 (2027)",
        must_not_imply=["Acme UltraBook Air, a different and unrelated product line"],
    )
    candidate = ResolvedMediaCandidate(
        candidate_id="hq-wrong",
        provenance=MediaProvenance(
            origin_url="https://reputable-example.com/article",
            asset_url="https://reputable-example.com/hq-image.jpg",
            discovered_at=datetime.now(timezone.utc),
            discovery_tier=DiscoveryTier.TIER2_OFFICIAL_PRIMARY,
            caption_or_alt="Acme UltraBook Air, a different and unrelated product line - studio photo",
        ),
        usage_classification=MediaUsageClassification.OFFICIAL_PRESS_ASSET,
        width=4000, height=3000,  # excellent resolution
    )
    result = await classify_subject_match(candidate, intent)
    assert result.subject_match == SubjectMatchClassification.MISMATCH
    assert result.must_not_imply_violated is True


# ---------------------------------------------------------------------------
# 7. No exact media available
# ---------------------------------------------------------------------------


async def test_no_exact_media_available_falls_to_generic_never_fabricates_exact() -> None:
    intent = _intent(
        primary_entity="Acme UltraBook Pro 16 (2027)", company="Acme", product_name="Acme UltraBook",
        model_name="Acme UltraBook Pro 16 (2027)",
    )
    candidate = _candidate(None)  # no descriptive text at all
    result = await classify_subject_match(candidate, intent)
    assert result.subject_match == SubjectMatchClassification.GENERIC_CONTEXT
    assert result.confidence == "low"


# ---------------------------------------------------------------------------
# 8. Multiple candidates: lower-quality exact candidate must beat a high-quality mismatch
#    (proves the classifier feeds the EXISTING, unmodified scoring dominance invariant correctly -
#    see tests/test_unified_pipeline_media_truthfulness_replay.py for the full selection-level proof)
# ---------------------------------------------------------------------------


async def test_low_quality_exact_candidate_still_classified_exact_regardless_of_resolution() -> None:
    intent = _intent(
        primary_entity="Acme UltraBook Pro 16 (2027)", company="Acme", product_name="Acme UltraBook",
        model_name="Acme UltraBook Pro 16 (2027)",
    )
    low_quality_exact = ResolvedMediaCandidate(
        candidate_id="low-quality-exact",
        provenance=MediaProvenance(
            origin_url="https://example.com/a", asset_url="https://example.com/a.jpg",
            discovered_at=datetime.now(timezone.utc), discovery_tier=DiscoveryTier.TIER4_WEB_IMAGE_DISCOVERY,
            caption_or_alt="Acme UltraBook Pro 16 (2027) leaked blurry photo",
        ),
        usage_classification=MediaUsageClassification.EDITORIAL_REVIEW_REQUIRED,
        width=200, height=150,  # poor resolution
    )
    result = await classify_subject_match(low_quality_exact, intent)
    assert result.subject_match == SubjectMatchClassification.EXACT_SUBJECT  # classification is
    # about IDENTITY, never about resolution/quality - scoring (a separate, unmodified module)
    # is what actually weighs resolution, and only among already-selectable candidates.


# ---------------------------------------------------------------------------
# 9. Person identity mismatch
# ---------------------------------------------------------------------------


async def test_person_identity_mismatch() -> None:
    intent = _intent(
        primary_entity="CEO statement", person="Jordan Alvarez",
        must_not_imply=["Sam Whitfield, a different executive"],
    )
    wrong_person = _candidate("Sam Whitfield, a different executive, speaking at a conference")
    result = await classify_subject_match(wrong_person, intent)
    assert result.subject_match == SubjectMatchClassification.MISMATCH

    right_person = _candidate("Jordan Alvarez speaking at the announcement event")
    result2 = await classify_subject_match(right_person, intent)
    assert result2.subject_match == SubjectMatchClassification.STRONG_CONTEXT  # `person` alone is
    # a category-tier term in this classifier's design (no `must_show` qualifier was set) - real,
    # non-mismatch, but not asserted EXACT without a more specific required term confirmed too.


# ---------------------------------------------------------------------------
# 10. Vehicle/model identity case
# ---------------------------------------------------------------------------


async def test_vehicle_model_identity_case() -> None:
    intent = _intent(
        primary_entity="Voltara Model S electric sedan (2027 refresh)", company="Voltara",
        product_name="Voltara Model S", model_name="Voltara Model S 2027 refresh",
        must_not_imply=["Voltara Model S 2024, the previous body style"],
    )
    wrong_model_year = _candidate("Voltara Model S 2024, the previous body style, studio shot")
    result = await classify_subject_match(wrong_model_year, intent)
    assert result.subject_match == SubjectMatchClassification.MISMATCH

    right_model_year = _candidate("The new Voltara Model S 2027 refresh, official reveal photo")
    result2 = await classify_subject_match(right_model_year, intent)
    assert result2.subject_match == SubjectMatchClassification.EXACT_SUBJECT


# ---------------------------------------------------------------------------
# Structural invariants, named exactly as the phase brief states them
# ---------------------------------------------------------------------------


async def test_same_brand_never_equals_same_product() -> None:
    intent = _intent(primary_entity="X", company="Acme", model_name="Acme Widget Z")
    candidate = _candidate("An Acme-branded accessory, unrelated to the Widget Z line")
    result = await classify_subject_match(candidate, intent)
    assert result.subject_match != SubjectMatchClassification.EXACT_SUBJECT


async def test_same_product_family_never_equals_same_version() -> None:
    intent = _intent(primary_entity="X", product_name="Acme Widget", model_name="Acme Widget Z (v3)")
    candidate = _candidate("Acme Widget, general product line photo, version unspecified")
    result = await classify_subject_match(candidate, intent)
    assert result.subject_match != SubjectMatchClassification.EXACT_SUBJECT


async def test_related_event_never_equals_exact_event() -> None:
    intent = _intent(primary_entity="X", event="Acme Developer Summit 2027 keynote")
    candidate = _candidate("Acme Developer Summit 2025, an earlier, unrelated year's event")
    result = await classify_subject_match(candidate, intent)
    assert result.subject_match != SubjectMatchClassification.EXACT_SUBJECT
