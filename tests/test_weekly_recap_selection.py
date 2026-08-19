"""NINJA PULSE RECAP Phase R1 / R1.1 - WEEKLY_RECAP selection tests. Pure eligibility/ranking/
diversity tests build `WeeklyRecapCandidate` objects directly (deterministic, offline, no DB); one
end-to-end test uses the real `db_session` fixture to prove the async orchestration is Story-level
(one candidate per Story row, never per NewsEvent).

Phase R1.1 quality-floor correction: pipeline order is now eligibility -> ranking -> diversity ->
selection (services/weekly_recap_selection.py::select_weekly_recap_stories_from_candidates()'s own
docstring). "Quality > count" - weak/ineligible candidates must never fill unused slots."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from core.config import settings
from database.models.news_event import EventCategory, NewsEvent
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from services.story_memory import NEW_STORY
from services.weekly_recap_selection import (
    WeeklyRecapCandidate,
    select_weekly_recap_stories,
    select_weekly_recap_stories_from_candidates,
)

_NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)


def _candidate(
    *, rank_score: float, company_key: str | None, tier: str = "CORE",
    major_impact_override: bool = False, score: int | None = None, significance: float | int | None = None,
) -> WeeklyRecapCandidate:
    return WeeklyRecapCandidate(
        story_id=uuid.uuid4(), representative_event_id=uuid.uuid4(), relevance_tier=tier,
        score=score, significance=significance, major_impact_override=major_impact_override,
        company_key=company_key, entities=[company_key] if company_key else [], updated_at=_NOW,
        reason="test", rank_score=rank_score,
    )


# ---------------------------------------------------------------------------
# Diversity (all candidates CORE-eligible here - diversity behavior only, unaffected by R1.1)
# ---------------------------------------------------------------------------


def test_diversity_cap_admits_at_most_max_per_company_when_enough_alternatives_exist():
    candidates = (
        [_candidate(rank_score=s, company_key="openai") for s in (100, 90, 80, 70)]
        + [_candidate(rank_score=s, company_key="google") for s in (60, 50, 40, 30)]
        + [_candidate(rank_score=s, company_key=None) for s in (20, 10)]
    )
    selected, excluded = select_weekly_recap_stories_from_candidates(candidates)

    openai_selected = [c for c in selected if c.company_key == "openai"]
    google_selected = [c for c in selected if c.company_key == "google"]
    assert len(openai_selected) == 2
    assert len(google_selected) == 2
    assert len(selected) == 6  # 2 openai + 2 google + both None-keyed candidates
    assert {c.rank_score for c in excluded} == {80, 70, 40, 30}  # the capped-out lower-ranked duplicates


def test_diversity_cap_relaxes_via_fallback_when_too_few_alternatives():
    # All 5 candidates share one company_key - strict cap (2) alone would leave only 2 selected,
    # below weekly_recap_target_min (5) - spec §12's own "should not reduce the result below a
    # useful minimum" fallback must admit the rest, in rank order.
    candidates = [_candidate(rank_score=s, company_key="openai") for s in (100, 90, 80, 70, 60)]
    selected, excluded = select_weekly_recap_stories_from_candidates(candidates)

    assert len(selected) == 5
    assert {c.rank_score for c in selected} == {100, 90, 80, 70, 60}
    assert excluded == []


def test_fallback_never_exceeds_target_max():
    candidates = [_candidate(rank_score=s, company_key="openai") for s in range(200, 100, -10)]  # 10 candidates
    selected, _excluded = select_weekly_recap_stories_from_candidates(candidates)
    assert len(selected) <= 8  # weekly_recap_target_max default


def test_none_keyed_candidates_are_never_capped_against_each_other():
    candidates = [_candidate(rank_score=s, company_key=None) for s in (100, 90, 80, 70, 60, 70)]
    selected, excluded = select_weekly_recap_stories_from_candidates(candidates)
    assert len(selected) == 6  # capped at target_max=8, all 6 fit - cap never applies to key=None
    assert excluded == []


def test_core_technology_outranks_ineligible_peripheral_business_noise():
    # A CORE story outranks a PERIPHERAL story that has no major-impact override - and, per R1.1,
    # the PERIPHERAL candidate is not merely ranked lower, it is dropped entirely by the quality
    # floor before ranking even runs.
    core = _candidate(rank_score=50 + 10, company_key="anthropic", tier="CORE")
    peripheral = _candidate(rank_score=70 - 12, company_key="fundco", tier="PERIPHERAL")
    selected, excluded = select_weekly_recap_stories_from_candidates([peripheral, core])
    assert selected == [core]
    assert excluded == [peripheral]


def test_major_impact_override_peripheral_outranks_ordinary_peripheral_noise():
    # Both are PERIPHERAL tier - only the major_impact_override=True one clears the R1.1
    # eligibility floor at all; the ordinary one is dropped, not merely ranked lower.
    major_impact = _candidate(rank_score=0 + 5, company_key="bigco", tier="PERIPHERAL", major_impact_override=True)
    ordinary_peripheral = _candidate(rank_score=0 - 12, company_key="smallco", tier="PERIPHERAL")
    selected, excluded = select_weekly_recap_stories_from_candidates([ordinary_peripheral, major_impact])
    assert selected == [major_impact]
    assert excluded == [ordinary_peripheral]


# ---------------------------------------------------------------------------
# Phase R1.1 quality floor - spec's own test matrix A-F
# ---------------------------------------------------------------------------


def test_case_a_four_strong_core_plus_weak_peripheral_noise_returns_four_not_padded():
    strong = [_candidate(rank_score=s, company_key=f"core{i}", tier="CORE") for i, s in enumerate((90, 80, 70, 60))]
    weak = [_candidate(rank_score=s, company_key=f"weak{i}", tier="PERIPHERAL") for i, s in enumerate(range(50, -50, -10))]
    assert len(weak) == 10
    selected, excluded = select_weekly_recap_stories_from_candidates(strong + weak)

    assert len(selected) == 4  # never padded up to weekly_recap_target_min (5) with weak filler
    assert {c.company_key for c in selected} == {"core0", "core1", "core2", "core3"}
    assert {c.story_id for c in excluded} == {c.story_id for c in weak}


def test_case_b_six_strong_core_and_adjacent_plus_noise_returns_six():
    core = [_candidate(rank_score=s, company_key=f"core{i}", tier="CORE") for i, s in enumerate((90, 80, 70))]
    adjacent = [
        _candidate(rank_score=s, company_key=f"adj{i}", tier="ADJACENT", score=settings.weekly_recap_adjacent_min_score)
        for i, s in enumerate((60, 50, 40))
    ]
    noise = [_candidate(rank_score=s, company_key=f"noise{i}", tier="PERIPHERAL") for i, s in enumerate((10, 0, -10))]
    selected, excluded = select_weekly_recap_stories_from_candidates(core + adjacent + noise)

    assert len(selected) == 6
    assert {c.company_key for c in selected} == {"core0", "core1", "core2", "adj0", "adj1", "adj2"}
    assert {c.story_id for c in excluded} == {c.story_id for c in noise}


def test_case_c_quality_filter_runs_before_company_diversity_capped_at_target_max():
    openai_strong = [_candidate(rank_score=s, company_key="openai", tier="CORE") for s in (100, 95, 90, 85)]
    other_strong = [_candidate(rank_score=s, company_key=f"co{i}", tier="CORE") for i, s in enumerate((80, 75, 70, 65, 60, 55))]
    assert len(openai_strong) == 4 and len(other_strong) == 6  # 10 total, all quality-eligible

    selected, excluded = select_weekly_recap_stories_from_candidates(openai_strong + other_strong)

    assert len(selected) == 8  # weekly_recap_target_max default
    openai_selected = [c for c in selected if c.company_key == "openai"]
    assert len(openai_selected) == 2  # diversity cap still applies, but only after quality passed everyone
    assert {c.rank_score for c in openai_selected} == {100, 95}  # the two highest-ranked openai candidates
    assert len(excluded) == 2  # the 2 lowest-ranked openai candidates, capped out


def test_case_d_peripheral_with_real_major_impact_override_remains_eligible():
    candidate = _candidate(rank_score=5, company_key="bigco", tier="PERIPHERAL", major_impact_override=True)
    selected, _excluded = select_weekly_recap_stories_from_candidates([candidate])
    assert selected == [candidate]


def test_case_e_peripheral_routine_funding_earnings_legal_excluded_without_override():
    candidate = _candidate(rank_score=41, company_key="smallco", tier="PERIPHERAL", major_impact_override=False)
    selected, excluded = select_weekly_recap_stories_from_candidates([candidate])
    assert selected == []
    assert excluded == [candidate]


def test_case_f_out_of_scope_always_excluded_even_with_a_high_rank_score():
    candidate = _candidate(rank_score=999, company_key="anything", tier="OUT_OF_SCOPE")
    selected, excluded = select_weekly_recap_stories_from_candidates([candidate])
    assert selected == []
    assert excluded == [candidate]


def test_adjacent_eligible_via_significance_signal_alone():
    candidate = _candidate(
        rank_score=10, company_key="x", tier="ADJACENT",
        significance=settings.weekly_recap_adjacent_min_significance,
    )
    selected, _excluded = select_weekly_recap_stories_from_candidates([candidate])
    assert selected == [candidate]


def test_adjacent_with_no_score_or_significance_signal_fails_closed():
    candidate = _candidate(rank_score=10, company_key="x", tier="ADJACENT", score=None, significance=None)
    selected, excluded = select_weekly_recap_stories_from_candidates([candidate])
    assert selected == []
    assert excluded == [candidate]


def test_diversity_fallback_never_admits_an_ineligible_candidate():
    # Only one CORE candidate exists; the rest of the pool is PERIPHERAL noise with no override.
    # Even though selected (1) is far below weekly_recap_target_min (5) and there ARE capped-out-
    # style leftover candidates in the pool, the fallback pass draws only from the already-eligible
    # `capped_out` list - it must never reach into the ineligible pool to pad the result.
    core = _candidate(rank_score=90, company_key="core", tier="CORE")
    noise = [_candidate(rank_score=s, company_key=f"n{i}", tier="PERIPHERAL") for i, s in enumerate((50, 40, 30, 20, 10, 0))]
    selected, excluded = select_weekly_recap_stories_from_candidates([core, *noise])
    assert selected == [core]
    assert {c.story_id for c in excluded} == {c.story_id for c in noise}


# ---------------------------------------------------------------------------
# End-to-end: async orchestration is Story-level (one candidate per Story row)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_weekly_recap_stories_produces_at_most_one_candidate_per_story(db_session):
    from database.models.editorial_task import EditorialTask, TaskPriority
    from database.models.news_source import NewsSource, SourceType

    source = NewsSource(name="Test", type=SourceType.RSS, url="https://example.com/feed.xml", active=True)
    db_session.add(source)
    await db_session.flush()

    stories = []
    for i in range(2):
        event = NewsEvent(
            source_id=source.id, title=f"Company{i} launches new product {i}", category=EventCategory.TECH,
            url=f"https://example.com/e{i}", hash=f"h-{uuid.uuid4()}",
        )
        db_session.add(event)
        await db_session.flush()

        story = Story(
            title=event.title, category=EventCategory.TECH, entities=[f"company{i}"], keywords=[],
            topic_bucket="product", first_event_id=event.id, event_count=1,
            updated_at=_NOW - timedelta(days=1),
        )
        db_session.add(story)
        await db_session.flush()

        db_session.add(NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=NEW_STORY, match_score=1.0))
        # A second, unrelated EditorialTask row for the SAME event - must not produce a second
        # candidate, since selection is keyed off Story rows, never EditorialTask rows.
        db_session.add(EditorialTask(event_id=event.id, priority=TaskPriority.B, workflow=None))
        await db_session.flush()
        stories.append(story)

    selected, excluded = await select_weekly_recap_stories(db_session, now=_NOW)
    all_candidates = selected + excluded
    story_ids = [c.story_id for c in all_candidates]
    # Never two candidates for the same story - checked across the WHOLE result set, not just our
    # two fixture stories, since the shared test database may contain other pre-existing Story
    # rows within the same 7-day window (this test does not assume database emptiness).
    assert len(story_ids) == len(set(story_ids))
    our_story_ids = {s.id for s in stories}
    assert our_story_ids.issubset(set(story_ids))  # both fixture stories were found and included exactly once
