"""UNIFIED-EDITORIAL-PIPELINE-VISION-GATE-CLOSURE-1: end-to-end production-shaped replays through
the REAL `services.editorial_pipeline.media.MediaResearchService.research()` (which calls the real,
unmodified `services.media_research_selection.research_and_select_media()` and `services.media_
candidate_scoring.py` dominance/exclusion policy), with the vision-gate classifier injected exactly
as `services.editorial_pipeline.telegram_integration.run_unified_telegram_delivery()` wires it in
production. Proves SELECTION outcomes, not merely classifier output in isolation (see
`tests/test_unified_pipeline_vision_gate.py` for that narrower proof) - candidates deliberately
carry weak/no caption text, so the deterministic classifier alone cannot decide and the vision gate
is what actually determines the outcome. No real network dependency anywhere in this file."""
from __future__ import annotations

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
from services.editorial_pipeline.media import MediaResearchService
from services.editorial_pipeline.subject_match_vision_gate import build_vision_gate_subject_match_classifier

pytestmark = pytest.mark.asyncio


class _ScriptedVisionCapability:
    """Returns a scripted verdict keyed by candidate_id (via the intent summary text, which always
    includes real candidate provenance) - never a real network/LLM call."""

    def __init__(self, verdict_by_candidate_id: dict[str, SubjectMatchClassification]) -> None:
        self._verdicts = verdict_by_candidate_id
        self.calls: list[str] = []

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        summary = context.business.media_subject_match_intent_summary or ""
        matched_id = next((cid for cid in self._verdicts if cid in summary), None)
        self.calls.append(matched_id or "UNMATCHED")
        classification = self._verdicts.get(matched_id, SubjectMatchClassification.GENERIC_CONTEXT)
        verdict = SubjectMatchValidation(
            depicted_subject_description="scripted vision verdict", subject_match=classification,
            must_not_imply_violated=classification == SubjectMatchClassification.MISMATCH,
            reason="scripted for test",
        )
        return CapabilityResult(
            status="SUCCESS", structured_output=verdict.model_dump(),
            started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc), duration_seconds=0.01,
        )


def _candidate(candidate_id: str, *, tier: DiscoveryTier = DiscoveryTier.TIER1_CURRENT_SOURCE, width: int = 1200, height: int = 800) -> ResolvedMediaCandidate:
    """Deliberately NO caption_or_alt - weak/no metadata, matching the phase's own explicit test
    framing ("weak/no metadata"): the deterministic classifier alone can only ever produce
    GENERIC_CONTEXT for these, so the vision gate is what actually decides the outcome."""
    return ResolvedMediaCandidate(
        candidate_id=candidate_id,
        provenance=MediaProvenance(
            origin_url=f"https://example.com/{candidate_id}", asset_url=f"https://example.com/{candidate_id}.jpg",
            discovered_at=datetime.now(timezone.utc), discovery_tier=tier,
        ),
        usage_classification=MediaUsageClassification.APPROVED_SOURCE_MEDIA, width=width, height=height,
    )


def _classifier(vision_capability) -> object:
    return build_vision_gate_subject_match_classifier(
        vision_capability=vision_capability, image_bytes_provider=lambda c: b"fake-bytes-for-" + c.candidate_id.encode(),
    )


# ---------------------------------------------------------------------------
# Case 1/2 - foldable iPhone, weak/no metadata.
# ---------------------------------------------------------------------------

_FOLDABLE_IPHONE_INTENT = MediaIntent(
    subject_type=MediaSubjectType.PRODUCT, primary_entity="foldable iPhone", product_name="iPhone",
    model_name="foldable iPhone", must_show=["foldable design"], desired_visual_type=DesiredVisualType.PRODUCT_PHOTO,
)


async def test_case1_standard_iphone_weak_metadata_rejected_via_vision() -> None:
    wrong_candidate = _candidate("standard-iphone", width=6000, height=4000)
    vision = _ScriptedVisionCapability({"standard-iphone": SubjectMatchClassification.MISMATCH})
    service = MediaResearchService()
    selection = await service.research(
        _FOLDABLE_IPHONE_INTENT, tier1_candidates=[wrong_candidate], subject_match_classifier=_classifier(vision),
    )
    assert selection.selected is None
    assert selection.exact_subject_media_not_found is True
    assert vision.calls == ["standard-iphone"]  # vision genuinely ran - metadata was insufficient


async def test_case2_true_foldable_weak_metadata_accepted_via_vision() -> None:
    correct_candidate = _candidate("true-foldable", width=800, height=600)
    vision = _ScriptedVisionCapability({"true-foldable": SubjectMatchClassification.EXACT_SUBJECT})
    service = MediaResearchService()
    selection = await service.research(
        _FOLDABLE_IPHONE_INTENT, tier1_candidates=[correct_candidate], subject_match_classifier=_classifier(vision),
    )
    assert selection.selected is not None
    assert selection.selected.candidate_id == "true-foldable"
    assert selection.exact_subject_media_not_found is False
    assert vision.calls == ["true-foldable"]


async def test_case1and2_combined_exact_wins_over_wrong_via_vision() -> None:
    wrong_candidate = _candidate("standard-iphone-2", width=6000, height=4000)
    correct_candidate = _candidate("true-foldable-2", width=800, height=600)
    vision = _ScriptedVisionCapability({
        "standard-iphone-2": SubjectMatchClassification.MISMATCH,
        "true-foldable-2": SubjectMatchClassification.EXACT_SUBJECT,
    })
    service = MediaResearchService()
    selection = await service.research(
        _FOLDABLE_IPHONE_INTENT, tier1_candidates=[wrong_candidate, correct_candidate],
        subject_match_classifier=_classifier(vision),
    )
    assert selection.selected is not None
    assert selection.selected.candidate_id == "true-foldable-2"


# ---------------------------------------------------------------------------
# Case 5 - product/model story: exact model vs a visually similar wrong model, weak metadata.
# ---------------------------------------------------------------------------

_GPT6_INTENT = MediaIntent(
    subject_type=MediaSubjectType.PRODUCT, primary_entity="GPT-6", product_name="GPT", model_name="GPT-6",
    company="OpenAI", desired_visual_type=DesiredVisualType.SCREENSHOT,
)


async def test_case5_visually_similar_wrong_model_rejected_where_vision_can_distinguish() -> None:
    wrong_model = _candidate("gpt5-screenshot")  # visually near-identical UI, wrong version
    exact_model = _candidate("gpt6-screenshot")
    vision = _ScriptedVisionCapability({
        "gpt5-screenshot": SubjectMatchClassification.MISMATCH,
        "gpt6-screenshot": SubjectMatchClassification.EXACT_SUBJECT,
    })
    service = MediaResearchService()
    selection = await service.research(
        _GPT6_INTENT, tier1_candidates=[wrong_model, exact_model], subject_match_classifier=_classifier(vision),
    )
    assert selection.selected is not None
    assert selection.selected.candidate_id == "gpt6-screenshot"
    assert selection.selected.candidate_id != "gpt5-screenshot"


# ---------------------------------------------------------------------------
# Case 6 - generic concept story, exact depiction not required: vision must not be called.
# ---------------------------------------------------------------------------

_CONCEPT_INTENT = MediaIntent(subject_type=MediaSubjectType.CONCEPT, primary_entity="AI regulation", desired_visual_type=DesiredVisualType.GRAPHIC_LAYOUT)


async def test_case6_generic_concept_story_never_calls_vision() -> None:
    candidate = _candidate("generic-ai-photo")
    vision = _ScriptedVisionCapability({"generic-ai-photo": SubjectMatchClassification.EXACT_SUBJECT})  # would
    # be wrong if ever consulted - proves the gate, not the vision result
    service = MediaResearchService()
    selection = await service.research(_CONCEPT_INTENT, tier1_candidates=[candidate], subject_match_classifier=_classifier(vision))
    assert vision.calls == []
    # GENERIC_CONTEXT is still selectable (never excluded) - this is about the intent not requiring
    # exact depiction, not about the candidate being rejected.
    assert selection.selected is not None
    assert selection.exact_subject_media_not_found is True
