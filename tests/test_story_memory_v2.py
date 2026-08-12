"""Phase 20 M3/M4/M5: permanent regression suite for Story Memory V2 (candidate retrieval,
symmetric title overlap, word-boundary topic classification, RELATED_STORY). Seeds the exact real
titles from docs/phase20_story_memory_calibration_dataset.md / tests/fixtures/
phase20_calibration_cases.json against freshly-created Story rows (not the ephemeral, already-
partly-contaminated real data from the Phase 19 overnight run) - reproducible independent of that
run's own state. Integration-tier: real Postgres (db_session, SAVEPOINT-rolled-back).
"""
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from services.story_memory import (
    NEW_STORY,
    RELATED_STORY,
    SEMANTIC_DUPLICATE,
    STORY_UPDATE,
    SUPPORTING_SOURCE,
    UNCERTAIN_MATCH,
    extract_story_signature,
    match_story,
)
from services.text_normalization import symmetric_token_overlap

_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "phase20_calibration_cases.json"
_OUTCOME_BY_NAME = {
    "new_story": NEW_STORY, "story_update": STORY_UPDATE, "supporting_source": SUPPORTING_SOURCE,
    "semantic_duplicate": SEMANTIC_DUPLICATE, "uncertain_match": UNCERTAIN_MATCH, "related_story": RELATED_STORY,
}


def _load_calibration() -> dict:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


async def _seed_story(session: AsyncSession, title: str, *, category: EventCategory) -> Story:
    source = NewsSource(name=f"phase20-v2-test-{uuid4()}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(source_id=source.id, title=title, category=category, hash=f"phase20-v2-test-{uuid4()}")
    session.add(event)
    await session.flush()
    signature = extract_story_signature(title, category)
    story = Story(
        id=uuid4(), title=title, category=category, entities=signature.entities,
        keywords=signature.keywords, topic_bucket=signature.topic_bucket, first_event_id=event.id, event_count=1,
    )
    session.add(story)
    await session.flush()
    return story


def _category(name: str) -> EventCategory:
    return EventCategory[name]


async def _match_against_only(
    monkeypatch: pytest.MonkeyPatch, session: AsyncSession, *, title: str, category: EventCategory, only_candidate: Story,
):
    """Isolates Stage B (relationship classification) from Stage A (candidate retrieval) - real
    stories.md rows created by the authorized Phase 19 overnight harness run still exist in the
    real DB (e.g. Kitesurf's own event-13 duplicate, created before this fix existed) and would
    otherwise out-score a freshly-seeded test root under M3's now-intentionally-wide retrieval
    (not scoped to this test). Monkeypatching retrieval to return exactly one candidate tests the
    real match_story() end-to-end (real thresholds, real banding) without depending on incidental
    real-DB state this test doesn't own or control - a legitimate, narrow patch of the retrieval
    boundary, not a stub of the classification logic being tested."""
    import services.story_memory as story_memory_module

    async def _fake_fetch(_session: AsyncSession, *, now):  # noqa: ANN001, ARG001
        return [only_candidate]

    monkeypatch.setattr(story_memory_module, "_fetch_candidate_stories", _fake_fetch)
    return await match_story(session, title=title, category=category)


# --- M2/M3/M4/M5: the four real Phase 19 regression cases, seeded fresh -------------------------


@pytest.mark.asyncio
async def test_kitesurf_now_links_across_categories(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case A - the category hard-gate bug. Fixed: real cross-category match now found."""
    data = _load_calibration()
    case = next(c for c in data["real_cases"] if c["case_id"] == "kitesurf")
    root_event, second_event = case["events"]

    root = await _seed_story(db_session, root_event["title"], category=_category(root_event["category"]))
    _signature, result = await _match_against_only(
        monkeypatch, db_session, title=second_event["title"], category=_category(second_event["category"]), only_candidate=root,
    )

    assert result.outcome in {_OUTCOME_BY_NAME[o] for o in case["expected_match_type_any_of"]}
    assert result.matched_story_id == root.id


@pytest.mark.asyncio
async def test_ai_olympiad_event8_links_confidently(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Already worked pre-Phase-20 - regression guard that M3/M4/M5 didn't break it."""
    data = _load_calibration()
    case = next(c for c in data["real_cases"] if c["case_id"] == "ai_olympiad_cluster")
    root_event, event8, _event14 = case["events"]

    root = await _seed_story(db_session, root_event["title"], category=_category(root_event["category"]))
    _signature, result = await _match_against_only(
        monkeypatch, db_session, title=event8["title"], category=_category(event8["category"]), only_candidate=root,
    )

    assert result.outcome in {_OUTCOME_BY_NAME[o] for o in case["expected_match_type_any_of"]}
    assert result.matched_story_id == root.id


@pytest.mark.asyncio
async def test_ai_olympiad_event14_no_longer_silently_lost(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case B - partial fix, honestly asserted. Event 14 previously vanished as a confident-
    looking NEW_STORY (confidence 1.0-ish); it must now at least surface as UNCERTAIN_MATCH
    (flagged for review) rather than being silently dropped. Not asserting a confident merge -
    the residual lemmatization gap (see calibration dataset) is real and disclosed."""
    data = _load_calibration()
    case = next(c for c in data["real_cases"] if c["case_id"] == "ai_olympiad_cluster")
    root_event, _event8, event14 = case["events"]

    root = await _seed_story(db_session, root_event["title"], category=_category(root_event["category"]))
    _signature, result = await _match_against_only(
        monkeypatch, db_session, title=event14["title"], category=_category(event14["category"]), only_candidate=root,
    )

    expected = {_OUTCOME_BY_NAME[o] for o in case["expected_match_type_any_of_event14_specifically"]}
    assert result.outcome in expected, f"got {result.outcome}, expected one of {expected}"
    assert result.outcome != NEW_STORY, "must not silently vanish as an uninformative NEW_STORY"
    assert result.matched_story_id == root.id


@pytest.mark.asyncio
async def test_moscow_student_pair_no_longer_silently_lost(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case C - the topic-bucket substring bug ("иск" false-matching inside "искусственному").
    Fixed: event 11 is now genuinely compared (previously excluded before scoring). Partial fix,
    honestly asserted - lands as UNCERTAIN_MATCH, not a confident automatic merge (correctly
    conservative per the "false suppression is worse" philosophy, given only two real data
    points)."""
    data = _load_calibration()
    case = next(c for c in data["real_cases"] if c["case_id"] == "moscow_student_pair")
    event10, event11 = case["events"]

    root = await _seed_story(db_session, event10["title"], category=_category(event10["category"]))
    signature, result = await _match_against_only(
        monkeypatch, db_session, title=event11["title"], category=_category(event11["category"]), only_candidate=root,
    )

    from services.story_memory import TOPIC_LEGAL_REGULATORY

    assert signature.topic_bucket != TOPIC_LEGAL_REGULATORY, "the 'иск' substring bug must stay fixed"
    expected = {_OUTCOME_BY_NAME[o] for o in case["expected_match_type_any_of"]}
    assert result.outcome in expected
    assert result.outcome != NEW_STORY, "must not silently vanish as an uninformative NEW_STORY"
    assert result.matched_story_id == root.id


@pytest.mark.asyncio
async def test_gta_negative_control_stays_separate(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case D - the single most important precision regression test in the suite. Once the
    category gate that accidentally protected this pair is removed, only real signal (here:
    entity/title dissimilarity) may keep it separate - never a SAME_STORY outcome."""
    data = _load_calibration()
    case = next(c for c in data["real_cases"] if c["case_id"] == "gta_negative_control")
    event1, event5 = case["events"]

    root = await _seed_story(db_session, event1["title"], category=_category(event1["category"]))
    _signature, result = await _match_against_only(
        monkeypatch, db_session, title=event5["title"], category=_category(event5["category"]), only_candidate=root,
    )

    expected = {_OUTCOME_BY_NAME[o] for o in case["expected_match_type_any_of"]}
    assert result.outcome in expected
    assert result.outcome not in (STORY_UPDATE, SUPPORTING_SOURCE, SEMANTIC_DUPLICATE), (
        "GTA VI preorders and GTA VI Netflix marketing must never SAME_STORY-merge"
    )


# --- Synthetic entity-overlap-trap negative controls (+ one positive control) --------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id", [
    "openai_two_unrelated_announcements", "company_lawsuit_vs_product_launch",
    "model_benchmark_vs_pricing", "person_quote_vs_company_event",
    "same_company_two_launches", "same_named_event_different_year",
])
async def test_synthetic_entity_overlap_traps_never_same_story_merge(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, case_id: str,
) -> None:
    data = _load_calibration()
    case = next(c for c in data["synthetic_cases"] if c["case_id"] == case_id)
    first, second = case["events"]

    root = await _seed_story(db_session, first["title"], category=_category(first["category"]))
    _signature, result = await _match_against_only(
        monkeypatch, db_session, title=second["title"], category=_category(second["category"]), only_candidate=root,
    )

    assert result.outcome not in (STORY_UPDATE, SUPPORTING_SOURCE, SEMANTIC_DUPLICATE), (
        f"{case_id}: same-entity, different-event pair must never SAME_STORY-merge, got {result.outcome}"
    )


@pytest.mark.asyncio
async def test_synthetic_positive_control_genuine_update_still_links(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """apple_same_product_different_dates - the one positive control among the synthetic cases:
    a real update (pricing revealed after unveiling) must still link, proving the negative-control
    fixes above didn't overcorrect into never matching anything."""
    data = _load_calibration()
    case = next(c for c in data["synthetic_cases"] if c["case_id"] == "apple_same_product_different_dates")
    first, second = case["events"]

    root = await _seed_story(db_session, first["title"], category=_category(first["category"]))
    _signature, result = await _match_against_only(
        monkeypatch, db_session, title=second["title"], category=_category(second["category"]), only_candidate=root,
    )

    expected = {_OUTCOME_BY_NAME[o] for o in case["expected_match_type_any_of"]}
    assert result.outcome in expected
    assert result.matched_story_id == root.id


# --- M3: candidate retrieval no longer category-gated (unit-level, pure where possible) ----------


@pytest.mark.asyncio
async def test_candidate_retrieval_is_not_category_filtered(db_session: AsyncSession) -> None:
    from services.story_memory import _fetch_candidate_stories

    await _seed_story(db_session, f"Cross-category retrieval test {uuid4()}", category=EventCategory.GADGETS)
    from datetime import datetime, timezone

    candidates = await _fetch_candidate_stories(db_session, now=datetime.now(timezone.utc))
    # No category argument accepted at all anymore - if this call succeeds and finds the
    # just-seeded GADGETS story while never having been told a category, retrieval is confirmed
    # category-blind by construction, not merely "happened to match".
    assert any(c.title.startswith("Cross-category retrieval test") for c in candidates)


# --- M4: symmetric overlap is genuinely symmetric, unlike the original asymmetric ratio ----------


def test_symmetric_overlap_is_order_independent() -> None:
    a = "Российские школьники в третий раз стали чемпионами на Международной олимпиаде по ИИ"
    b = "Школьная сборная России третий год подряд стала абсолютным чемпионом на Международной олимпиаде по ИИ"
    assert symmetric_token_overlap(a, b) == symmetric_token_overlap(b, a)


def test_symmetric_overlap_not_penalized_by_longer_paraphrase() -> None:
    """The exact bug this fix addresses: a longer restatement of the same facts must not score
    lower purely because it has more words - Dice normalizes by the average length, not just the
    new event's own (potentially larger) token count."""
    from services.text_normalization import token_overlap_ratio

    short = "Company launches new product today"
    long_paraphrase = "Company officially launches its brand new flagship product line today across all markets"
    # The OLD asymmetric ratio, evaluated new-title-first, is diluted by the longer title's own
    # larger denominator; the new symmetric measure must be more forgiving of the same absolute
    # overlap under a longer restatement.
    old_style = token_overlap_ratio(long_paraphrase, short)
    new_style = symmetric_token_overlap(long_paraphrase, short)
    assert new_style >= old_style


# --- M5: RELATED_STORY never appears alongside a real matched_story_id being treated as a merge --


@pytest.mark.asyncio
async def test_related_story_result_is_never_a_same_story_outcome() -> None:
    """Pure, no DB: RELATED_STORY must be structurally distinct from every SAME_STORY outcome -
    defensive test against an accidental future rename/merge of the two concepts."""
    same_story_outcomes = {STORY_UPDATE, SUPPORTING_SOURCE, SEMANTIC_DUPLICATE}
    assert RELATED_STORY not in same_story_outcomes
