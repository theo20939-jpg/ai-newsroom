"""ARXIV-STORY-CLUSTERING-REPAIR-1 — the upstream candidate-eligibility filter.

`candidate_story_identity_verdict()` (pure) and `match_story()` (real DB) must refuse to let a
new academic event join a Story that carries a *conflicting* trusted stable document identity
(different arXiv base id / different DOI in the same namespace) or that is already a polluted
multi-document academic Story - BEFORE any fuzzy / exact-title score can attach it. Same base id
(any version) and missing identity keep the candidate eligible; normal non-academic clustering
is byte-identical.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from services.story_identity_guard import (
    CANDIDATE_ELIGIBLE,
    CANDIDATE_INELIGIBLE,
    REASON_CANDIDATE_NO_COMPARABLE_IDENTITY,
    REASON_CANDIDATE_NO_STABLE_IDENTITY,
    REASON_POLLUTED_STORY,
    REASON_STABLE_IDENTITY_MATCH,
    candidate_story_identity_verdict,
)
from services.story_memory import NEW_STORY, SEMANTIC_DUPLICATE, extract_story_signature, match_story

_ABS = "https://arxiv.org/abs/"

# =============================================================================================
# Pure helper - candidate_story_identity_verdict()
# =============================================================================================
def _v(new_url, docs, new_title="Some academic paper about large language models"):
    return candidate_story_identity_verdict(new_url=new_url, new_title=new_title, candidate_documents=docs)


def test_different_arxiv_base_ids_high_title_similarity_is_ineligible() -> None:
    # both templated-abstract openers, high lexical overlap, different ids
    verdict, reason = _v(
        f"{_ABS}2609.11111v1",
        [("Large Language Models (LLMs) have demonstrated impressive capabilities, however …", f"{_ABS}2609.22222v1")],
        new_title="Large Language Models (LLMs) have demonstrated impressive capabilities, but they struggle …",
    )
    assert verdict == CANDIDATE_INELIGIBLE
    assert reason == "arxiv_identity_mismatch"


def test_different_arxiv_base_ids_identical_title_is_ineligible() -> None:
    # identical title must NOT beat the stable-identity conflict (spec sec 14)
    title = "Multimodal Large Language Models for Gigapixel Pathology"
    verdict, reason = _v(f"{_ABS}2609.33333", [(title, f"{_ABS}2609.44444")], new_title=title)
    assert verdict == CANDIDATE_INELIGIBLE
    assert reason == "arxiv_identity_mismatch"


@pytest.mark.parametrize("prior_url", [f"{_ABS}2609.06385", f"{_ABS}2609.06385v1", f"{_ABS}2609.06385v3"])
def test_same_arxiv_base_id_any_version_is_eligible(prior_url: str) -> None:
    verdict, reason = _v(f"{_ABS}2609.06385v2", [("same paper, later version", prior_url)])
    assert verdict == CANDIDATE_ELIGIBLE
    assert reason == REASON_STABLE_IDENTITY_MATCH


def test_candidate_with_no_comparable_identity_is_eligible() -> None:
    # new event is academic, candidate Story has only ordinary news events -> NOT a conflict
    verdict, reason = _v(
        f"{_ABS}2609.06385v1",
        [("Meta launches Muse agent", "https://www.theverge.com/2026/9/9/meta-muse"),
         ("Meta's Muse agent explained", "https://news.google.com/rss/articles/abc")],
    )
    assert verdict == CANDIDATE_ELIGIBLE
    assert reason == REASON_CANDIDATE_NO_COMPARABLE_IDENTITY


def test_new_event_without_stable_identity_is_always_eligible() -> None:
    verdict, reason = _v(
        "https://www.theguardian.com/tech/2026/sep/10/story",
        [("an arXiv paper", f"{_ABS}2609.06385v1")],
        new_title="Streaming from the cloud was meant to change games forever",
    )
    assert verdict == CANDIDATE_ELIGIBLE
    assert reason == REASON_CANDIDATE_NO_STABLE_IDENTITY


def test_polluted_story_two_distinct_arxiv_ids_is_ineligible() -> None:
    verdict, reason = _v(
        f"{_ABS}2609.09999v1",
        [("paper A", f"{_ABS}2608.11111v1"), ("paper B", f"{_ABS}2608.22222v1"), ("paper C", f"{_ABS}2609.09999v1")],
    )
    assert verdict == CANDIDATE_INELIGIBLE
    assert reason == REASON_POLLUTED_STORY


def test_polluted_story_wins_even_when_new_id_is_present() -> None:
    # new id IS among the pile, but the pile has >=2 distinct ids -> still polluted -> ineligible
    verdict, reason = _v(
        f"{_ABS}2609.09999",
        [("A", f"{_ABS}2608.11111"), ("mine", f"{_ABS}2609.09999")],
    )
    assert verdict == CANDIDATE_INELIGIBLE
    assert reason == REASON_POLLUTED_STORY


def test_same_doi_is_eligible_different_doi_is_ineligible() -> None:
    ok, ok_reason = _v("https://doi.org/10.1038/s41586-024-07123-4",
                       [("same paper", "https://doi.org/10.1038/s41586-024-07123-4")])
    assert ok == CANDIDATE_ELIGIBLE and ok_reason == REASON_STABLE_IDENTITY_MATCH
    bad, bad_reason = _v("https://doi.org/10.1038/s41586-024-07123-4",
                         [("other paper", "https://doi.org/10.1000/xyz123")])
    assert bad == CANDIDATE_INELIGIBLE and bad_reason == "doi_identity_mismatch"


def test_doi_missing_on_one_side_is_not_a_conflict() -> None:
    verdict, reason = _v("https://doi.org/10.1038/s41586-024-07123-4",
                         [("news wrapper", "https://news.google.com/rss/articles/xyz")])
    assert verdict == CANDIDATE_ELIGIBLE
    assert reason == REASON_CANDIDATE_NO_COMPARABLE_IDENTITY


def test_arxiv_new_event_vs_doi_only_candidate_is_not_a_conflict() -> None:
    # different namespaces -> no comparable identity -> eligible (existing behaviour preserved)
    verdict, reason = _v(f"{_ABS}2609.06385v1",
                         [("a DOI paper", "https://doi.org/10.1000/xyz123")])
    assert verdict == CANDIDATE_ELIGIBLE
    assert reason == REASON_CANDIDATE_NO_COMPARABLE_IDENTITY


# =============================================================================================
# Integration - match_story() against a real DB
#
# Titles use rare, non-ML tokens plus a random suffix so that in the shared test DB ONLY the
# story this test seeds is ever preselected as a candidate - which makes the identity filter's
# effect on `outcome` deterministic instead of being masked by an unrelated low-scoring story.
# =============================================================================================
def _rare_title(stem: str) -> str:
    return f"Zyxwvut {stem} Quokkabottle Perpendicular Widgetsmithing {uuid4().hex[:10]}"


async def _seed_academic_story(session: AsyncSession, title: str, arxiv_urls: list[str]):
    src = NewsSource(name=f"asc-{uuid4()}", type=SourceType.RSS, active=True)
    session.add(src)
    await session.flush()
    first = None
    story_id = uuid4()
    for i, u in enumerate(arxiv_urls):
        ev = NewsEvent(source_id=src.id, title=title, category=EventCategory.AI,
                       hash=f"asc-{uuid4()}", url=u)
        session.add(ev)
        await session.flush()
        if first is None:
            first = ev.id
            sig = extract_story_signature(title, EventCategory.AI)
            session.add(Story(
                id=story_id, title=title, category=EventCategory.AI, entities=sig.entities,
                keywords=sig.keywords, topic_bucket=sig.topic_bucket, first_event_id=first,
                event_count=len(arxiv_urls),
            ))
            await session.flush()
        session.add(NewsEventStoryLink(
            news_event_id=ev.id, story_id=story_id, match_type="new_story" if i == 0 else "semantic_duplicate",
            match_score=1.0,
        ))
    await session.flush()
    return src, story_id


@pytest.mark.asyncio
async def test_match_story_blocks_different_arxiv_id_even_with_identical_title(
    db_session: AsyncSession,
) -> None:
    title = _rare_title("Attention")
    _src, story_id = await _seed_academic_story(db_session, title, [f"{_ABS}2609.10001v1"])

    # CONTROL: with no stable identity on the new event the filter is a no-op, so the identical
    # title short-circuits straight to SEMANTIC_DUPLICATE against this very story.
    _sig, control = await match_story(db_session, title=title, category=EventCategory.AI, url=None)
    assert control.outcome == SEMANTIC_DUPLICATE
    assert control.matched_story_id == story_id

    # REAL: a different arXiv base id must override the identical title (spec sec 14).
    _sig, result = await match_story(
        db_session, title=title, category=EventCategory.AI, url=f"{_ABS}2609.10002v1",
    )
    assert result.outcome == NEW_STORY
    assert result.matched_story_id != story_id


@pytest.mark.asyncio
async def test_match_story_keeps_same_arxiv_base_id_eligible(db_session: AsyncSession) -> None:
    title = _rare_title("Mixtureofexperts")
    await _seed_academic_story(db_session, title, [f"{_ABS}2609.10010v1"])
    _sig, result = await match_story(
        db_session, title=title, category=EventCategory.AI, url=f"{_ABS}2609.10010v2",
    )
    # same base id -> candidate stays eligible -> the exact-title short-circuit still fires
    assert result.outcome == SEMANTIC_DUPLICATE
    assert result.matched_story_id is not None


@pytest.mark.asyncio
async def test_match_story_blocks_polluted_academic_story(db_session: AsyncSession) -> None:
    title = _rare_title("Graphretrieval")
    _src, story_id = await _seed_academic_story(
        db_session, title, [f"{_ABS}2608.20001v1", f"{_ABS}2608.20002v1", f"{_ABS}2609.20003v1"],
    )

    # CONTROL: no identity on the new event -> filter no-op -> identical title short-circuits.
    _sig, control = await match_story(db_session, title=title, category=EventCategory.AI, url=None)
    assert control.outcome == SEMANTIC_DUPLICATE
    assert control.matched_story_id == story_id

    # REAL: the story already holds >1 distinct academic identity -> unsafe for a confident
    # automatic match even when the new event's own id is one of them.
    _sig, result = await match_story(
        db_session, title=title, category=EventCategory.AI, url=f"{_ABS}2608.20001v1",
    )
    assert result.outcome == NEW_STORY
    assert result.matched_story_id != story_id


@pytest.mark.asyncio
async def test_match_story_non_academic_event_unaffected_by_the_filter(
    db_session: AsyncSession,
) -> None:
    # a normal news event with an identical title still matches its Story - the filter is a no-op
    title = _rare_title("Musevoiceagent")
    await _seed_academic_story(db_session, title, ["https://www.theverge.com/2026/9/9/meta-muse"])
    _sig, result = await match_story(
        db_session, title=title, category=EventCategory.AI,
        url="https://news.google.com/rss/articles/meta-muse-wrapper",
    )
    assert result.outcome == SEMANTIC_DUPLICATE  # unchanged behaviour


@pytest.mark.asyncio
async def test_match_story_academic_event_vs_nonacademic_story_still_matches(
    db_session: AsyncSession,
) -> None:
    # new event is academic, candidate Story has NO stable id -> absence is not a conflict
    title = _rare_title("Dialogueserving")
    await _seed_academic_story(db_session, title, ["https://blog.example.com/rag-serving"])
    _sig, result = await match_story(
        db_session, title=title, category=EventCategory.AI, url=f"{_ABS}2609.30001v1",
    )
    assert result.outcome == SEMANTIC_DUPLICATE
    assert result.matched_story_id is not None


# =============================================================================================
# Guard-rails: this phase must not have touched the P0.1 identity guard or the P0 constrained
# enforcement predicate. Full coverage lives in test_story_identity_guard.py /
# test_story_continuity_constrained_enforcement.py (both unchanged & green); these are a fast
# tripwire so a regression there also fails THIS file.
# =============================================================================================
def test_p0_1_identity_guard_semantics_unchanged() -> None:
    from services.story_identity_guard import (
        GUARD_FAIL_OPEN,
        IDENTITY_CONFLICT,
        _STORY_IDENTITY_POLLUTION_FLOOR,
        assess_continuity_identity,
    )

    assert _STORY_IDENTITY_POLLUTION_FLOOR == 2
    a = assess_continuity_identity(
        new_title="A paper",
        new_url=f"{_ABS}2609.00001v1",
        prior_documents=[("Another paper", f"{_ABS}2609.00002v1")],
        match_is_exact_title_identity=True,
    )
    assert a.identity_status == IDENTITY_CONFLICT
    assert a.verdict == GUARD_FAIL_OPEN


def test_constrained_enforcement_predicate_signature_unchanged() -> None:
    import inspect

    from services.story_continuity import (
        CONSTRAINED_ENFORCEMENT_POLICY_VERSION,
        evaluate_constrained_enforcement,
    )

    assert CONSTRAINED_ENFORCEMENT_POLICY_VERSION == "p0_constrained_v1"
    params = set(inspect.signature(evaluate_constrained_enforcement).parameters)
    assert params == {
        "enabled",
        "continuity",
        "would_suppress_flag",
        "identity_assessment",
        "exact_normalized_title_match",
    }
