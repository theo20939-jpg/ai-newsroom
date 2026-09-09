"""STORY-CONTINUITY-P0 - continuity classifier + capability-aware delta (pure-function unit
tests). The DB-integration adversarial matrix and the frozen Meta-Muse incident replay live in
tests/test_story_continuity_meta_replay.py."""
from __future__ import annotations

from uuid import uuid4

import pytest

from services.story_continuity import (
    CONTINUITY_AMBIGUOUS,
    CONTINUITY_DUPLICATE_NO_DELTA,
    CONTINUITY_MATERIAL_UPDATE_CANDIDATE,
    CONTINUITY_NEW_STORY,
    classify_continuity,
)
from services.story_delta_engine import (
    DELTA_MATERIAL,
    DELTA_MINOR,
    DELTA_NONE,
    MATERIAL_UPDATE,
    NO_NEW_FACTS,
    UNCERTAIN_DELTA,
    DeltaResult,
    classify_delta,
    coarse_delta_class,
)
from services.story_memory import (
    NEW_STORY,
    RELATED_STORY,
    SEMANTIC_DUPLICATE,
    STORY_UPDATE,
    SUPPORTING_SOURCE,
    UNCERTAIN_MATCH,
    MatchResult,
)

_SID = uuid4()


def _mr(outcome: str, *, conf: float = 0.7, distinctive: bool = True, company_only: bool = False,
        matched: bool = True) -> MatchResult:
    return MatchResult(
        outcome=outcome,
        matched_story_id=_SID if matched else None,
        confidence=conf,
        similarity_reason="test",
        entity_overlap=0.6,
        has_distinctive_shared_entity=distinctive,
        distinctive_overlap=0.5 if distinctive else 0.0,
        supporting_overlap=1.0 if company_only else 0.3,
        generic_overlap=0.0,
        shared_distinctive_entities=("muse voice transcribe",) if distinctive else (),
        company_only_match=company_only,
    )


def _delta(classification: str) -> DeltaResult:
    return DeltaResult(classification=classification, reason="test")


# --- coarse_delta_class ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "fine,coarse",
    [
        (NO_NEW_FACTS, DELTA_NONE),
        ("confirmation_only", DELTA_NONE),
        ("minor_delta", DELTA_MINOR),
        (MATERIAL_UPDATE, DELTA_MATERIAL),
        (UNCERTAIN_DELTA, DELTA_MINOR),  # conservative: never NO_DELTA
    ],
)
def test_coarse_delta_class(fine: str, coarse: str) -> None:
    assert coarse_delta_class(_delta(fine)) == coarse


def test_coarse_delta_class_none_is_minor_never_none() -> None:
    assert coarse_delta_class(None) == DELTA_MINOR


# --- capability-aware classify_delta ------------------------------------------------------------

def test_delta_new_capability_keyword_escalates_to_material() -> None:
    """A genuinely new capability/availability keyword makes it a MATERIAL_UPDATE even with no
    numeric claim - the exact gap the forensic found (diarization / multilingual / API / iOS app
    developments registered at most as MINOR_DELTA before)."""
    d = classify_delta(
        "Meta reveals its AI agent that can shop, send emails and plan trips on your behalf",
        ["Meta launches Muse, a personal AI agent"],
    )
    assert d.classification == MATERIAL_UPDATE
    assert coarse_delta_class(d) == DELTA_MATERIAL


def test_delta_pure_rewording_stays_no_delta() -> None:
    d = classify_delta(
        "Meta launches Muse personal AI agent",
        ["Meta launches Muse, a personal AI agent"],
    )
    assert coarse_delta_class(d) in (DELTA_NONE, DELTA_MINOR)


def test_delta_capability_keyword_already_present_is_not_new() -> None:
    d = classify_delta(
        "Meta's Muse agent now supports multilingual voice",
        ["Meta launches Muse agent with multilingual voice support"],
    )
    assert coarse_delta_class(d) in (DELTA_NONE, DELTA_MINOR)  # "multilingual" not NEW


# --- classify_continuity ---------------------------------------------------------------------

def test_continuity_new_story() -> None:
    r = classify_continuity(match_result=_mr(NEW_STORY, matched=False), delta_result=None, creates_own_story=True)
    assert r.outcome == CONTINUITY_NEW_STORY
    assert r.suppression_eligible is False
    assert r.matched_story_id is None


def test_continuity_related_story_is_new_story_never_merged() -> None:
    r = classify_continuity(match_result=_mr(RELATED_STORY, matched=False), delta_result=None, creates_own_story=True)
    assert r.outcome == CONTINUITY_NEW_STORY
    assert "related_story_not_merged" in r.reason_codes


def test_continuity_semantic_duplicate_no_delta_is_suppression_eligible() -> None:
    r = classify_continuity(
        match_result=_mr(SEMANTIC_DUPLICATE), delta_result=_delta(NO_NEW_FACTS), creates_own_story=False,
    )
    assert r.outcome == CONTINUITY_DUPLICATE_NO_DELTA
    assert r.suppression_eligible is True
    assert r.delta_class == DELTA_NONE


def test_continuity_supporting_source_material_delta_is_update_candidate_not_suppressed() -> None:
    r = classify_continuity(
        match_result=_mr(SUPPORTING_SOURCE), delta_result=_delta(MATERIAL_UPDATE), creates_own_story=False,
    )
    assert r.outcome == CONTINUITY_MATERIAL_UPDATE_CANDIDATE
    assert r.suppression_eligible is False
    assert r.delta_class == DELTA_MATERIAL


def test_continuity_minor_delta_is_safe_never_suppressed() -> None:
    """Section 11 - a small/uncertain new fact must never be silently suppressed."""
    r = classify_continuity(
        match_result=_mr(SEMANTIC_DUPLICATE), delta_result=_delta("minor_delta"), creates_own_story=False,
    )
    assert r.outcome == CONTINUITY_MATERIAL_UPDATE_CANDIDATE
    assert r.suppression_eligible is False
    assert r.delta_class == DELTA_MINOR
    assert "not_suppressed_conservative" in r.reason_codes


def test_continuity_confident_score_without_distinctive_entity_is_ambiguous() -> None:
    """A confident match_type that is NOT backed by a distinctive shared entity must never be a
    confident continuity outcome - it degrades to AMBIGUOUS, never DUPLICATE_NO_DELTA."""
    r = classify_continuity(
        match_result=_mr(SUPPORTING_SOURCE, distinctive=False, company_only=True),
        delta_result=_delta(NO_NEW_FACTS), creates_own_story=False,
    )
    assert r.outcome == CONTINUITY_AMBIGUOUS
    assert r.suppression_eligible is False


def test_continuity_uncertain_match_is_ambiguous() -> None:
    r = classify_continuity(
        match_result=_mr(UNCERTAIN_MATCH, distinctive=False), delta_result=_delta(UNCERTAIN_DELTA),
        creates_own_story=False,
    )
    assert r.outcome == CONTINUITY_AMBIGUOUS
    assert r.suppression_eligible is False


def test_continuity_story_update_is_material_update_candidate() -> None:
    r = classify_continuity(
        match_result=_mr(STORY_UPDATE), delta_result=_delta(MATERIAL_UPDATE), creates_own_story=False,
    )
    assert r.outcome == CONTINUITY_MATERIAL_UPDATE_CANDIDATE
    assert r.suppression_eligible is False


def test_continuity_result_carries_structured_evidence_no_prose() -> None:
    r = classify_continuity(
        match_result=_mr(SEMANTIC_DUPLICATE), delta_result=_delta(NO_NEW_FACTS), creates_own_story=False,
    )
    assert set(r.match_components) >= {
        "match_score", "entity_overlap", "distinctive_overlap", "supporting_overlap", "generic_overlap",
    }
    assert all(isinstance(c, str) and " " not in c for c in r.reason_codes)  # machine-readable


def test_continuity_outcomes_are_mutually_exclusive() -> None:
    """No input can produce two outcomes / contradictory suppression state."""
    seen: set[str] = set()
    for mt in (NEW_STORY, RELATED_STORY, UNCERTAIN_MATCH, SEMANTIC_DUPLICATE, SUPPORTING_SOURCE, STORY_UPDATE):
        for dc in (NO_NEW_FACTS, "minor_delta", MATERIAL_UPDATE, UNCERTAIN_DELTA):
            for own in (True, False):
                r = classify_continuity(
                    match_result=_mr(mt, matched=not own), delta_result=_delta(dc), creates_own_story=own,
                )
                seen.add(r.outcome)
                if r.suppression_eligible:
                    assert r.outcome == CONTINUITY_DUPLICATE_NO_DELTA  # only this outcome may be suppression-eligible
    assert seen <= {
        CONTINUITY_NEW_STORY, CONTINUITY_DUPLICATE_NO_DELTA,
        CONTINUITY_MATERIAL_UPDATE_CANDIDATE, CONTINUITY_AMBIGUOUS,
    }


# --- STORY-CONTINUITY-P0.1: the abstract-quality / stable-document-identity firewall ----------

def _identity(verdict: str, *, status: str = "INSUFFICIENT_DOCUMENT_IDENTITY",
              quality: str = "ABSTRACT_LIKE", codes: tuple[str, ...] = ("test_guard_reason",)):
    from services.story_identity_guard import ContinuityIdentityAssessment
    return ContinuityIdentityAssessment(
        verdict=verdict, identity_status=status, identity_namespace="arxiv",
        title_quality=quality, new_identity=None, reason_codes=codes,
    )


def test_p0_1_guard_fail_open_demotes_confident_duplicate_to_ambiguous() -> None:
    """The exact production failure class: SUPPORTING_SOURCE + NO_DELTA with a distinctive shared
    entity would be DUPLICATE_NO_DELTA (suppression-eligible) - the identity firewall demotes it."""
    r = classify_continuity(
        match_result=_mr(SUPPORTING_SOURCE), delta_result=_delta(NO_NEW_FACTS), creates_own_story=False,
        identity_assessment=_identity("FAIL_OPEN"),
    )
    assert r.outcome == CONTINUITY_AMBIGUOUS
    assert r.guard_forced_fail_open is True
    assert r.suppression_eligible is False
    assert "guard_forced_fail_open" in r.reason_codes
    assert "test_guard_reason" in r.reason_codes


@pytest.mark.parametrize("delta", [NO_NEW_FACTS, "minor_delta", MATERIAL_UPDATE, UNCERTAIN_DELTA])
def test_p0_1_guard_fail_open_never_leaves_a_suppression_eligible_outcome(delta: str) -> None:
    for mt in (SEMANTIC_DUPLICATE, SUPPORTING_SOURCE, STORY_UPDATE):
        r = classify_continuity(
            match_result=_mr(mt), delta_result=_delta(delta), creates_own_story=False,
            identity_assessment=_identity("FAIL_OPEN"),
        )
        assert r.outcome == CONTINUITY_AMBIGUOUS
        assert r.suppression_eligible is False
        assert r.guard_forced_fail_open is True


def test_p0_1_guard_safe_leaves_confident_outcome_untouched() -> None:
    r = classify_continuity(
        match_result=_mr(SEMANTIC_DUPLICATE), delta_result=_delta(NO_NEW_FACTS), creates_own_story=False,
        identity_assessment=_identity("SAFE", status="STABLE_IDENTITY_MATCH",
                                     codes=("stable_document_identity_match",)),
    )
    assert r.outcome == CONTINUITY_DUPLICATE_NO_DELTA
    assert r.guard_forced_fail_open is False
    assert "stable_document_identity_match" in r.reason_codes


def test_p0_1_absent_identity_assessment_is_byte_identical_behaviour() -> None:
    """Default (None) must not change any outcome vs. the pre-P0.1 classifier."""
    for mt in (NEW_STORY, RELATED_STORY, UNCERTAIN_MATCH, SEMANTIC_DUPLICATE, SUPPORTING_SOURCE, STORY_UPDATE):
        for dc in (NO_NEW_FACTS, "minor_delta", MATERIAL_UPDATE, UNCERTAIN_DELTA):
            for own in (True, False):
                a = classify_continuity(
                    match_result=_mr(mt, matched=not own), delta_result=_delta(dc), creates_own_story=own,
                )
                b = classify_continuity(
                    match_result=_mr(mt, matched=not own), delta_result=_delta(dc), creates_own_story=own,
                    identity_assessment=None,
                )
                assert a.outcome == b.outcome
                assert a.suppression_eligible == b.suppression_eligible
                assert b.guard_forced_fail_open is False
                assert b.title_semantic_quality is None


def test_p0_1_guard_does_not_touch_new_story_or_ambiguous_paths() -> None:
    r = classify_continuity(
        match_result=_mr(NEW_STORY, matched=False), delta_result=None, creates_own_story=True,
        identity_assessment=_identity("FAIL_OPEN"),
    )
    assert r.outcome == CONTINUITY_NEW_STORY
    assert r.guard_forced_fail_open is False  # branch 1 never carries the guard flag
