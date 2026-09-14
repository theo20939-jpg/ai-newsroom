"""UNIFIED-EDITORIAL-PIPELINE-VISION-GATE-CLOSURE-1: the vision-gate subject-match classifier.
No real external network dependency anywhere in this file - `_FakeVisionCapability` never makes a
real Gateway/LLM call."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from schemas.capability import CapabilityContext, CapabilityResult
from schemas.media_intent import DesiredVisualType, MediaIntent, MediaSubjectType
from schemas.media_subject_match import (
    DiscoveryTier,
    MediaProvenance,
    MediaUsageClassification,
    ResolvedMediaCandidate,
    SubjectMatchClassification,
    SubjectMatchValidation,
)
from services.editorial_pipeline.subject_match_vision_gate import build_vision_gate_subject_match_classifier

pytestmark = pytest.mark.asyncio


class _FakeVisionCapability:
    """A trivial, deterministic fake - never touches the network, never imports a real Gateway."""

    def __init__(self, response: SubjectMatchValidation | None = None, *, raises: Exception | None = None, hang_seconds: float | None = None):
        self._response = response
        self._raises = raises
        self._hang_seconds = hang_seconds
        self.call_count = 0
        self.last_context: CapabilityContext | None = None

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        self.call_count += 1
        self.last_context = context
        if self._hang_seconds is not None:
            await asyncio.sleep(self._hang_seconds)
        if self._raises is not None:
            raise self._raises
        assert self._response is not None
        return CapabilityResult(
            status="SUCCESS", structured_output=self._response.model_dump(),
            started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc), duration_seconds=0.01,
        )


def _validation(classification: SubjectMatchClassification, *, description: str = "vision result") -> SubjectMatchValidation:
    return SubjectMatchValidation(
        depicted_subject_description=description, subject_match=classification,
        must_not_imply_violated=classification == SubjectMatchClassification.MISMATCH,
        reason="vision-based classification",
    )


def _candidate(candidate_id: str = "c1", *, caption_or_alt: str | None = None, sha256: str | None = None) -> ResolvedMediaCandidate:
    return ResolvedMediaCandidate(
        candidate_id=candidate_id,
        provenance=MediaProvenance(
            origin_url="https://example.com/a", asset_url="https://example.com/a.jpg",
            discovered_at=datetime.now(timezone.utc), discovery_tier=DiscoveryTier.TIER1_CURRENT_SOURCE,
            caption_or_alt=caption_or_alt,
        ),
        usage_classification=MediaUsageClassification.APPROVED_SOURCE_MEDIA, sha256=sha256,
    )


_EXACT_SUBJECT_INTENT = MediaIntent(
    subject_type=MediaSubjectType.PRODUCT, primary_entity="foldable iPhone", product_name="iPhone",
    model_name="foldable iPhone", must_show=["foldable design"], must_not_imply=["standard non-folding design"],
    desired_visual_type=DesiredVisualType.PRODUCT_PHOTO,
)
_CONCEPT_INTENT = MediaIntent(
    subject_type=MediaSubjectType.CONCEPT, primary_entity="AI regulation", desired_visual_type=DesiredVisualType.GRAPHIC_LAYOUT,
)


async def test_ambiguous_exact_subject_intent_escalates_and_vision_confirms_exact() -> None:
    """Case: metadata insufficient (no caption) + exact-subject-requiring intent -> escalates;
    vision confirms EXACT -> upgraded."""
    candidate = _candidate()  # no caption_or_alt -> deterministic verdict is GENERIC_CONTEXT
    capability = _FakeVisionCapability(_validation(SubjectMatchClassification.EXACT_SUBJECT))
    classifier = build_vision_gate_subject_match_classifier(
        vision_capability=capability, image_bytes_provider=lambda c: b"fake-jpeg-bytes",
    )
    result = await classifier(candidate, _EXACT_SUBJECT_INTENT)
    assert result.subject_match == SubjectMatchClassification.EXACT_SUBJECT
    assert capability.call_count == 1


async def test_ambiguous_exact_subject_intent_escalates_and_vision_confirms_mismatch() -> None:
    candidate = _candidate()
    capability = _FakeVisionCapability(_validation(SubjectMatchClassification.MISMATCH))
    classifier = build_vision_gate_subject_match_classifier(
        vision_capability=capability, image_bytes_provider=lambda c: b"fake-jpeg-bytes",
    )
    result = await classifier(candidate, _EXACT_SUBJECT_INTENT)
    assert result.subject_match == SubjectMatchClassification.MISMATCH
    assert capability.call_count == 1


async def test_deterministic_mismatch_never_escalates_to_vision() -> None:
    """A candidate whose caption text already matches a forbidden implication is MISMATCH
    deterministically - vision must never be called (it cannot make a rejected candidate more
    rejected, and the phase brief explicitly forbids unnecessary vision calls)."""
    candidate = _candidate(caption_or_alt="standard non-folding design iPhone")
    capability = _FakeVisionCapability(_validation(SubjectMatchClassification.EXACT_SUBJECT))  # would
    # be wrong if ever called - proves the escalation gate, not the vision result itself
    classifier = build_vision_gate_subject_match_classifier(vision_capability=capability, image_bytes_provider=lambda c: b"x")
    result = await classifier(candidate, _EXACT_SUBJECT_INTENT)
    assert result.subject_match == SubjectMatchClassification.MISMATCH
    assert capability.call_count == 0


async def test_deterministic_exact_never_escalates_to_vision() -> None:
    candidate = _candidate(caption_or_alt="foldable iPhone foldable design shown folded and unfolded")
    capability = _FakeVisionCapability(_validation(SubjectMatchClassification.MISMATCH))  # would be
    # wrong if ever called
    classifier = build_vision_gate_subject_match_classifier(vision_capability=capability, image_bytes_provider=lambda c: b"x")
    result = await classifier(candidate, _EXACT_SUBJECT_INTENT)
    assert result.subject_match == SubjectMatchClassification.EXACT_SUBJECT
    assert capability.call_count == 0


async def test_concept_intent_with_no_required_terms_never_escalates() -> None:
    """Case 6: a generic concept story where exact depiction is not required - vision must not be
    called even though the deterministic verdict is GENERIC_CONTEXT."""
    candidate = _candidate()
    capability = _FakeVisionCapability(_validation(SubjectMatchClassification.EXACT_SUBJECT))
    classifier = build_vision_gate_subject_match_classifier(vision_capability=capability, image_bytes_provider=lambda c: b"x")
    result = await classifier(candidate, _CONCEPT_INTENT)
    assert result.subject_match == SubjectMatchClassification.GENERIC_CONTEXT
    assert capability.call_count == 0


async def test_no_image_bytes_available_skips_vision_never_crashes() -> None:
    candidate = _candidate()
    capability = _FakeVisionCapability(_validation(SubjectMatchClassification.EXACT_SUBJECT))
    classifier = build_vision_gate_subject_match_classifier(vision_capability=capability, image_bytes_provider=lambda c: None)
    result = await classifier(candidate, _EXACT_SUBJECT_INTENT)
    assert result.subject_match == SubjectMatchClassification.GENERIC_CONTEXT  # unchanged, never upgraded
    assert capability.call_count == 0


async def test_image_bytes_provider_failure_returns_deterministic_verdict_never_raises() -> None:
    """A bytes-provider failure (e.g. a real storage lookup error) must never crash the classifier
    or discard the deterministic verdict already computed."""
    candidate = _candidate()
    capability = _FakeVisionCapability(_validation(SubjectMatchClassification.EXACT_SUBJECT))

    def _raising_provider(c):
        raise RuntimeError("simulated storage failure")

    classifier = build_vision_gate_subject_match_classifier(vision_capability=capability, image_bytes_provider=_raising_provider)
    result = await classifier(candidate, _EXACT_SUBJECT_INTENT)
    assert result.subject_match == SubjectMatchClassification.GENERIC_CONTEXT
    assert capability.call_count == 0


async def test_vision_timeout_never_upgrades_to_exact() -> None:
    """Case 7: vision backend timeout - no false EXACT upgrade, deterministic GENERIC_CONTEXT
    verdict stands, truthful HOLD/fallback remains available upstream."""
    candidate = _candidate()
    capability = _FakeVisionCapability(hang_seconds=5.0)
    classifier = build_vision_gate_subject_match_classifier(
        vision_capability=capability, image_bytes_provider=lambda c: b"x", timeout_seconds=0.05,
    )
    result = await classifier(candidate, _EXACT_SUBJECT_INTENT)
    assert result.subject_match == SubjectMatchClassification.GENERIC_CONTEXT
    assert result.subject_match != SubjectMatchClassification.EXACT_SUBJECT


async def test_vision_error_never_upgrades_to_exact() -> None:
    candidate = _candidate()
    capability = _FakeVisionCapability(raises=RuntimeError("simulated gateway failure"))
    classifier = build_vision_gate_subject_match_classifier(vision_capability=capability, image_bytes_provider=lambda c: b"x")
    result = await classifier(candidate, _EXACT_SUBJECT_INTENT)
    assert result.subject_match == SubjectMatchClassification.GENERIC_CONTEXT


async def test_vision_generic_result_leaves_deterministic_verdict_unchanged() -> None:
    """Vision genuinely ran but could not confirm anything either way - must never be treated as a
    failure (still cached), but also never invents confidence beyond GENERIC_CONTEXT."""
    candidate = _candidate()
    capability = _FakeVisionCapability(_validation(SubjectMatchClassification.GENERIC_CONTEXT))
    classifier = build_vision_gate_subject_match_classifier(vision_capability=capability, image_bytes_provider=lambda c: b"x")
    result = await classifier(candidate, _EXACT_SUBJECT_INTENT)
    assert result.subject_match == SubjectMatchClassification.GENERIC_CONTEXT
    assert capability.call_count == 1  # it DID run - this is not the "skipped" path


async def test_same_media_candidate_encountered_twice_is_cached_and_bounded() -> None:
    """Case 8: the same media identity (by sha256) must not be vision-checked twice."""
    candidate_a = _candidate("c1", sha256="a" * 64)
    candidate_b = _candidate("c2", sha256="a" * 64)  # different candidate_id, SAME content hash
    capability = _FakeVisionCapability(_validation(SubjectMatchClassification.EXACT_SUBJECT))
    cache: dict = {}
    classifier = build_vision_gate_subject_match_classifier(
        vision_capability=capability, image_bytes_provider=lambda c: b"x", cache=cache,
    )
    result_a = await classifier(candidate_a, _EXACT_SUBJECT_INTENT)
    result_b = await classifier(candidate_b, _EXACT_SUBJECT_INTENT)
    assert result_a.subject_match == SubjectMatchClassification.EXACT_SUBJECT
    assert result_b.subject_match == SubjectMatchClassification.EXACT_SUBJECT
    assert capability.call_count == 1  # the second call was served from cache, never re-invoked


async def test_named_person_wrong_person_rejected_via_vision() -> None:
    """Case 3: named person story, wrong person's image, no useful caption text."""
    intent = MediaIntent(
        subject_type=MediaSubjectType.PERSON, primary_entity="Dario Amodei", person="Dario Amodei",
        must_not_imply=["a different AI company executive"], desired_visual_type=DesiredVisualType.PORTRAIT,
    )
    candidate = _candidate()  # no caption - deterministic GENERIC_CONTEXT
    capability = _FakeVisionCapability(_validation(SubjectMatchClassification.MISMATCH, description="depicts a different executive"))
    classifier = build_vision_gate_subject_match_classifier(vision_capability=capability, image_bytes_provider=lambda c: b"x")
    result = await classifier(candidate, intent)
    assert result.subject_match == SubjectMatchClassification.MISMATCH


async def test_named_person_correct_person_accepted_via_vision() -> None:
    """Case 4: named person, correct image accepted."""
    intent = MediaIntent(
        subject_type=MediaSubjectType.PERSON, primary_entity="Dario Amodei", person="Dario Amodei",
        desired_visual_type=DesiredVisualType.PORTRAIT,
    )
    candidate = _candidate()
    capability = _FakeVisionCapability(_validation(SubjectMatchClassification.EXACT_SUBJECT, description="depicts Dario Amodei"))
    classifier = build_vision_gate_subject_match_classifier(vision_capability=capability, image_bytes_provider=lambda c: b"x")
    result = await classifier(candidate, intent)
    assert result.subject_match == SubjectMatchClassification.EXACT_SUBJECT
