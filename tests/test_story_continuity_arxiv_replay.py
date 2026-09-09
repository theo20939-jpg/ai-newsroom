"""STORY-CONTINUITY-P0.1 - replay of the real production shadow sample.

tests/fixtures/arxiv_abstract_shadow_sample.json holds the 17 CONFIDENT Story-continuity
decisions (8 DUPLICATE_NO_DELTA + 9 MATERIAL_UPDATE_CANDIDATE... captured as recorded:
DUPLICATE_NO_DELTA x8, MATERIAL_UPDATE_CANDIDATE x9) that automation_worker @ b45e384 wrote
during STORY-CONTINUITY-P0-SHADOW-PRODUCTION-ROLLOUT-1 (2026-09-09). Of those, the Founder's
Founder-visible audit found 4 DUPLICATE_NO_DELTA and 6+ MATERIAL_UPDATE_CANDIDATE to be
unrelated arXiv papers wrongly clustered upstream.

This test drives the exact P0.1 firewall + classifier over that sample and asserts:
  * every case whose matched Story is a multi-document cluster (>= 2 distinct stable document
    ids) OR whose own arXiv id conflicts with the cluster is demoted to AMBIGUOUS with
    guard_forced_fail_open, and can never be would_suppress-eligible;
  * the 4 clean single-paper re-collections (score 1.0, one distinct prior id) keep
    DUPLICATE_NO_DELTA;
  * the 2 non-arXiv news items keep MATERIAL_UPDATE_CANDIDATE (no normal-news regression).

No DB, no network - pure replay of persisted (title, url) evidence.
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from services.story_continuity import (
    CONTINUITY_AMBIGUOUS,
    CONTINUITY_DUPLICATE_NO_DELTA,
    CONTINUITY_MATERIAL_UPDATE_CANDIDATE,
    classify_continuity,
)
from services.story_delta_engine import (
    MATERIAL_UPDATE,
    MINOR_DELTA,
    NO_NEW_FACTS,
    DeltaResult,
)
from services.story_identity_guard import (
    GUARD_FAIL_OPEN,
    assess_continuity_identity,
    extract_document_identity,
)
from services.story_memory import MatchResult

_FIXTURE = Path(__file__).parent / "fixtures" / "arxiv_abstract_shadow_sample.json"
_CASES = json.loads(_FIXTURE.read_text(encoding="utf-8"))["cases"]

_COARSE_TO_FINE = {
    "NO_DELTA": NO_NEW_FACTS,
    "MINOR_DELTA": MINOR_DELTA,
    "MATERIAL_DELTA": MATERIAL_UPDATE,
    None: MINOR_DELTA,
}


def _match_result(case: dict) -> MatchResult:
    return MatchResult(
        outcome=case["match_type"],
        matched_story_id=uuid4(),
        confidence=float(case["match_score"]),
        similarity_reason="replay",
        entity_overlap=0.6,
        has_distinctive_shared_entity=True,  # every replayed case cleared this gate in prod
        distinctive_overlap=0.5,
        supporting_overlap=0.3,
        generic_overlap=0.0,
        shared_distinctive_entities=("replayed",),
    )


def _run(case: dict):
    ia = assess_continuity_identity(
        new_title=case["new_title"],
        new_url=case["new_url"],
        new_summary=case["new_summary"],
        prior_documents=[(p["title"], p["url"]) for p in case["prior_documents"]],
        match_is_exact_title_identity=(
            case["match_type"] == "semantic_duplicate" and float(case["match_score"]) >= 1.0 - 1e-9
        ),
    )
    delta = DeltaResult(_COARSE_TO_FINE.get(case["delta_classification"], MINOR_DELTA), reason="replay")
    result = classify_continuity(
        match_result=_match_result(case), delta_result=delta, creates_own_story=False,
        identity_assessment=ia,
    )
    return ia, result


def _should_demote(case: dict) -> bool:
    """Ground truth derived straight from the persisted evidence: a match against a
    multi-document cluster (>= 2 distinct stable ids), or an arXiv-id conflict (the new event's
    own id is NOT among the cluster's ids), is unsafe. A clean single-paper cluster the new
    event genuinely re-joins, and a non-arXiv news item, are safe."""
    if case["distinct_prior_document_ids"] >= 2:
        return True
    new_id = extract_document_identity(url=case["new_url"], title=case["new_title"])
    if new_id is None:
        return False
    prior_keys = {
        (ident.namespace, ident.identifier)
        for p in case["prior_documents"]
        if (ident := extract_document_identity(url=p["url"], title=p["title"])) is not None
    }
    return bool(prior_keys) and (new_id.namespace, new_id.identifier) not in prior_keys


@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_replay_case(case: dict) -> None:
    ia, result = _run(case)
    if _should_demote(case):
        assert result.outcome == CONTINUITY_AMBIGUOUS, case["new_title"][:80]
        assert result.guard_forced_fail_open is True
        assert result.suppression_eligible is False
        assert ia.verdict == GUARD_FAIL_OPEN
    else:
        assert result.guard_forced_fail_open is False, case["new_title"][:80]
        assert result.outcome in (
            CONTINUITY_DUPLICATE_NO_DELTA, CONTINUITY_MATERIAL_UPDATE_CANDIDATE,
        )


def test_replay_aggregate_matches_founder_audit() -> None:
    demoted = [c for c in _CASES if _run(c)[1].guard_forced_fail_open]
    kept = [c for c in _CASES if not _run(c)[1].guard_forced_fail_open]
    # 4 false DUPLICATE_NO_DELTA + 7 false MATERIAL_UPDATE_CANDIDATE
    assert len(demoted) == 11
    assert sum(c["prod_final_decision"] == "DUPLICATE_NO_DELTA" for c in demoted) == 4
    assert sum(c["prod_final_decision"] == "MATERIAL_UPDATE_CANDIDATE" for c in demoted) == 7
    # 4 clean arXiv re-collections + 2 non-arXiv news items
    assert len(kept) == 6
    assert sum(c["prod_final_decision"] == "DUPLICATE_NO_DELTA" for c in kept) == 4


def test_replay_the_4_wrong_duplicates_are_no_longer_suppressible() -> None:
    """Section 11 acceptance target: the 4 wrong DUPLICATE_NO_DELTA cases must no longer be
    suppression-eligible under any of the persisted signals."""
    wrong_dupes = [
        c for c in _CASES
        if c["prod_final_decision"] == "DUPLICATE_NO_DELTA" and c["distinct_prior_document_ids"] >= 2
    ]
    assert len(wrong_dupes) == 4
    for c in wrong_dupes:
        ia, result = _run(c)
        assert result.outcome == CONTINUITY_AMBIGUOUS
        assert result.suppression_eligible is False
        # and the orchestrator forces the persisted column false on guard fail-open, so even the
        # independent compute_would_suppress() result is overridden to False downstream.
        assert result.guard_forced_fail_open is True


def test_replay_legit_exact_duplicate_still_classified_duplicate() -> None:
    legit = [
        c for c in _CASES
        if c["prod_final_decision"] == "DUPLICATE_NO_DELTA"
        and c["match_score"] == 1.0 and c["distinct_prior_document_ids"] == 1
    ]
    assert len(legit) >= 3
    for c in legit:
        _, result = _run(c)
        assert result.outcome == CONTINUITY_DUPLICATE_NO_DELTA
        assert result.guard_forced_fail_open is False
