"""Phase 20 M6: deterministic Delta Engine tests.

Pure-function tests cover `classify_delta()` directly, including the exact worked examples from
the Phase 20 M6 product spec ("OpenAI launches X" + confirmation / date / benchmark / rewording
only). One integration test exercises `compute_story_delta()`'s real DB join against a real
Postgres `db_session` (SAVEPOINT-rolled-back), matching this codebase's established convention
(see tests/test_story_memory_v2.py).
"""
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from services.story_delta_engine import (
    CONFIRMATION_ONLY,
    MATERIAL_UPDATE,
    MINOR_DELTA,
    NO_NEW_FACTS,
    UNCERTAIN_DELTA,
    classify_delta,
    compute_story_delta,
)


# --- pure classify_delta() - worked examples from the M6 product spec ----------------------


def test_confirmation_by_another_source_is_not_a_new_fact() -> None:
    """'OpenAI launches X' + 'another source says OpenAI launches X' -> not a material update."""
    result = classify_delta(
        "OpenAI launches new voice assistant",
        ["OpenAI launches new voice assistant, TechCrunch reports"],
    )
    assert result.classification in (NO_NEW_FACTS, CONFIRMATION_ONLY)


def test_new_release_date_is_a_material_update() -> None:
    """'OpenAI launches X' + release date becomes known -> MATERIAL_UPDATE."""
    result = classify_delta(
        "OpenAI voice assistant will launch on March 15, 2026",
        ["OpenAI launches new voice assistant"],
    )
    assert result.classification == MATERIAL_UPDATE
    assert any("2026" in c for c in result.new_material_claims)


def test_independent_benchmark_is_a_material_update() -> None:
    """'OpenAI launches X' + independent benchmark numbers appear -> MATERIAL_UPDATE."""
    result = classify_delta(
        "OpenAI voice assistant scores 92% on independent benchmark",
        ["OpenAI launches new voice assistant"],
    )
    assert result.classification == MATERIAL_UPDATE
    assert result.new_material_claims == ["92%"]


def test_different_wording_alone_is_not_a_delta() -> None:
    """Different wording alone is NOT a delta - must not reach MATERIAL_UPDATE."""
    result = classify_delta(
        "OpenAI unveils voice assistant product",
        ["OpenAI launches new voice assistant"],
    )
    assert result.classification != MATERIAL_UPDATE


def test_template_headline_with_new_distinctive_subject_is_not_confirmation_only() -> None:
    """Phase 20 Checkpoint 4 finding: a real suppression-packet false-positive-risk case (M11.3
    replay) - two guide-style headlines share almost the entire template ("X romance walkthrough:
    All the best gifts for the Y in Fields of Mistria") but name a DIFFERENT specific subject
    (Juniper/arrogant witch vs March/grumpy blacksmith) - genuinely different content, not a
    same-story rehash. High title_overlap alone must not be sufficient for CONFIRMATION_ONLY when
    real new distinctive keywords are present - this is exactly what MINOR_DELTA/UNCERTAIN_DELTA
    exist to represent."""
    result = classify_delta(
        "Juniper romance walkthrough: All the best gifts for the arrogant witch in Fields of Mistria",
        ["March romance walkthrough: All the best gifts for the grumpy blacksmith in Fields of Mistria"],
    )
    assert result.classification != CONFIRMATION_ONLY
    assert result.new_keywords  # the distinctive new subject must still be surfaced


def test_near_identical_repeat_is_no_new_facts() -> None:
    result = classify_delta(
        "Company launches new flagship product today",
        ["Company launches new flagship product today"],
    )
    assert result.classification == NO_NEW_FACTS


def test_google_news_publisher_suffix_is_not_a_new_keyword() -> None:
    """Real observed production false negative: a Google News RSS wrapper of "ИИ-модель DeepSeek
    V4 Pro выпущена официально" arrives titled "...официально - 3DNews" - the same real article,
    already correctly classified by Story Memory as semantic_duplicate/same story_id
    (match_score≈0.713636). Before this fix, extract_story_signature() had no publisher-suffix
    awareness, so "3dnews" was extracted as a spuriously "new" distinctive keyword, producing
    MINOR_DELTA (new_keywords=["3dnews"]) and letting Story Memory V2 suppression allow the
    duplicate through (would_suppress=False). strip_google_news_title_suffix() normalization
    (shared with services/article_acquisition.py, never a second regex) must make this collapse
    to NO_NEW_FACTS with no fabricated keyword, so the existing duplicate guard blocks it exactly
    as it already does for the direct-feed/direct-feed duplicate case above."""
    result = classify_delta(
        "ИИ-модель DeepSeek V4 Pro выпущена официально - 3DNews",
        ["ИИ-модель DeepSeek V4 Pro выпущена официально"],
        new_title_is_google_news_wrapper=True,
    )
    assert result.classification == NO_NEW_FACTS
    assert result.new_keywords == []
    assert result.new_material_claims == []


def test_genuine_semantic_hyphen_tail_is_not_silently_stripped() -> None:
    """Negative control (review finding): a legitimate editorial title can have the exact same
    shape as a Google News wrapper (" - X" trailing segment) without X being a publisher credit
    at all. strip_google_news_title_suffix() must NOT be applied here, because the RAW pair's
    own title overlap (0.667) never reaches _NO_NEW_FACTS_TITLE_OVERLAP (0.85) - unlike the real
    DeepSeek pair (raw overlap 0.909) - so there is no pair evidence the suffix is attribution-
    only. The semantic tail ("что изменится для пользователей") must remain real comparison
    input and surface as a delta, not be silently discarded."""
    result = classify_delta(
        "Apple представила новую функцию - что изменится для пользователей",
        ["Apple представила новую функцию"],
    )
    assert result.classification != NO_NEW_FACTS
    assert result.new_keywords  # the semantic tail's own distinctive keywords must survive


def test_repeated_material_claim_across_sources_is_not_genuinely_new() -> None:
    """A claim already present in ANY prior title must not count as new, even if the new
    title's wording around it differs (money claim echoed by a second source)."""
    result = classify_delta(
        "Startup raises $50 million in new funding round, sources confirm",
        ["Startup raises $50 million in Series B funding round"],
    )
    assert result.classification != MATERIAL_UPDATE


def test_small_number_of_new_keywords_without_material_claim_is_minor_delta() -> None:
    result = classify_delta(
        "Regulator opens preliminary inquiry into merger",
        ["Regulator scrutinizes proposed merger deal"],
    )
    assert result.classification in (MINOR_DELTA, UNCERTAIN_DELTA)
    assert result.classification != NO_NEW_FACTS


def test_empty_prior_titles_is_uncertain_not_a_crash() -> None:
    result = classify_delta("Some new headline", [])
    assert result.classification == UNCERTAIN_DELTA


def test_material_update_pools_new_facts_across_all_prior_titles_not_pairwise() -> None:
    """A claim present in ANY one of several prior titles is not genuinely new, even if it is
    absent from the others - the pool is a union, not a pairwise comparison."""
    result = classify_delta(
        "Company reports 15% revenue growth this quarter",
        ["Company posts strong quarterly results", "Company revenue up 15% year over year"],
    )
    assert result.classification != MATERIAL_UPDATE


def test_reason_is_always_populated() -> None:
    for result in (
        classify_delta("X", []),
        classify_delta("Company launches product", ["Company launches product"]),
        classify_delta("Company launches product at $10, up 5%", ["Totally unrelated headline"]),
    ):
        assert result.reason


# --- compute_story_delta() - real DB join ---------------------------------------------------


async def _seed_event(session: AsyncSession, title: str, *, category: EventCategory = EventCategory.AI) -> NewsEvent:
    source = NewsSource(name=f"phase20-delta-test-{uuid4()}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(source_id=source.id, title=title, category=category, hash=f"phase20-delta-test-{uuid4()}")
    session.add(event)
    await session.flush()
    return event


async def _seed_story_with_links(session: AsyncSession, titles: list[str]) -> tuple[Story, list[NewsEvent]]:
    events = [await _seed_event(session, title) for title in titles]
    story = Story(
        id=uuid4(), title=titles[0], category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="other", first_event_id=events[0].id, event_count=len(events),
    )
    session.add(story)
    await session.flush()
    for event in events:
        session.add(NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type="new_story", match_score=1.0))
    await session.flush()
    return story, events


@pytest.mark.asyncio
async def test_compute_story_delta_fetches_real_prior_titles(db_session: AsyncSession) -> None:
    story, events = await _seed_story_with_links(
        db_session, ["OpenAI launches new voice assistant", "OpenAI voice assistant rollout confirmed by sources"],
    )

    result = await compute_story_delta(
        db_session, new_title="OpenAI voice assistant scores 92% on independent benchmark", story_id=story.id,
    )
    assert result.classification == MATERIAL_UPDATE


@pytest.mark.asyncio
async def test_compute_story_delta_excludes_the_given_event_id(db_session: AsyncSession) -> None:
    """If the event being classified was already linked (defensive path), excluding its own id
    must not let it count as its own 'prior' evidence."""
    story, events = await _seed_story_with_links(db_session, ["Only real prior headline about the story"])
    self_event = await _seed_event(db_session, "The exact new headline itself")
    db_session.add(NewsEventStoryLink(news_event_id=self_event.id, story_id=story.id, match_type="new_story", match_score=1.0))
    await db_session.flush()

    result = await compute_story_delta(
        db_session, new_title="The exact new headline itself", story_id=story.id, exclude_event_id=self_event.id,
    )
    # Only "Only real prior headline about the story" remains as prior evidence - a completely
    # different headline, so the self-link's own identical title must not suppress this to
    # NO_NEW_FACTS via a false self-match.
    assert result.classification != NO_NEW_FACTS


@pytest.mark.asyncio
async def test_compute_story_delta_no_prior_titles_is_uncertain(db_session: AsyncSession) -> None:
    story, events = await _seed_story_with_links(db_session, ["Only event so far"])

    result = await compute_story_delta(
        db_session, new_title="Only event so far", story_id=story.id, exclude_event_id=events[0].id,
    )
    assert result.classification == UNCERTAIN_DELTA
