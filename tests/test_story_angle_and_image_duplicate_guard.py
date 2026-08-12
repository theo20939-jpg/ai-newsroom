"""Phase 23.1N - required test cases (docs/phase23_1n_story_angle_meme_image_report.md, Part P).

Story cases (1-5) are prompt-content assertions - story preservation/meme-potential judgment is
an LLM-output-quality property verified via the golden replay
(docs/phase23_1n_story_angle_meme_image_report.md §8), mirroring every prior copywriting-version
test file's own established convention (tests/test_copywriting_v82_cases.py,
tests/test_copywriting_v83_naturalness_cases.py, tests/test_copywriting_v84_naturalness_cases.py).

Image cases (6-12): 6, 7, 9 (no candidates), 11, and 12 are already covered by the pre-existing
tests/test_router_media_integration.py suite (cases A/B/C/E/G/H/I/J) - unchanged this phase, not
duplicated here. Case 8 (story-specific image outranking a generic logo) is an existing
`services/image_relevance.py` ranking behavior, already exercised by real data (Phase 23.1H-23.1M
golden examples consistently rank `source_relationship=native_same_item/original_article`
candidates above generic ones - see docs/phase23_1n_story_angle_meme_image_report.md §9-10) - not
re-tested here since this phase makes no ranking-algorithm change. Case 10 (the actual new
behavior this phase adds - a cross-event duplicate-image guard) is the focus of this file,
covered directly at both the unit level (the new `get_recently_attached_image_source_urls()`
function) and the integration level (a real `run_content_cycle()` call proving the router skips a
recently-duplicated candidate and falls through to the next one / text-only).
"""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.image_candidate_record import ImageCandidateRecord, ImageStorageStatus
from database.models.news_event import NewsEvent
from database.models.news_source import SourceType
from services.editorial_treatment import STANDARD, EditorialTreatmentDecision
from services.image_persistence import get_recently_attached_image_source_urls, sanitize_url
from tests.test_content_worker_cycle import (
    _isolated_freshness_window,  # noqa: F401,F811
    _make_completed_news_analysis_task,
    _make_event,
    factory,  # noqa: F401,F811
    test_source,  # noqa: F401,F811
)
from tests.test_editorial_delivery_mode import _v6_capability_registry
from worker.content_cycle import run_content_cycle

async def _make_task_and_draft(db_session: AsyncSession, event: NewsEvent) -> ContentDraft:
    task = EditorialTask(event_id=event.id, priority=TaskPriority.B)
    db_session.add(task)
    await db_session.flush()
    draft = ContentDraft(task_id=task.id, type=ContentType.POST, title="t", body="b", hashtags=[])
    db_session.add(draft)
    await db_session.flush()
    return draft


_REAL_CHAT_ID = -1004297182444
_REAL_NEWS_TOPIC_ID = 2


def _prompt_text() -> str:
    raw = Path("prompts/copywriting/v8.5.yaml").read_text(encoding="utf-8")
    return " ".join(raw.split())


# ---------------------------------------------------------------------------
# CASE 1 - story-led bizarre event -> specific causal sequence retained
# ---------------------------------------------------------------------------


def test_case_1_prompt_contains_story_led_preservation_rule_with_who_wanted_what_happened() -> None:
    text = _prompt_text()
    assert "STORY-LED PRESERVATION" in text
    assert "WHO / WANTED WHAT / WHAT HAPPENED" in text
    assert "do NOT replace that sequence with an abstract conclusion" in text


# ---------------------------------------------------------------------------
# CASE 2 - standard corporate news -> no forced storytelling
# ---------------------------------------------------------------------------


def test_case_2_story_led_rule_explicitly_excludes_routine_announcements() -> None:
    text = _prompt_text()
    assert "not merely a routine announcement, product update, or financial/corporate fact pattern" in text
    assert "Set to false for ordinary fact-led news" in text


# ---------------------------------------------------------------------------
# CASE 3 - viral but factually uncertain -> story retained, certainty preserved
# ---------------------------------------------------------------------------


def test_case_3_semantic_precision_rule_still_applies_to_story_led_output() -> None:
    text = _prompt_text()
    # the pre-existing, carried-forward SEMANTIC PRECISION rule is what guarantees this - confirm
    # it was not weakened or removed when STORY-LED PRESERVATION was added.
    assert "SEMANTIC PRECISION IS NON-NEGOTIABLE" in text
    assert "certainty level" in text


# ---------------------------------------------------------------------------
# CASE 4 - serious/sensitive story -> meme potential NOT elevated solely because surprising
# ---------------------------------------------------------------------------


def test_case_4_prompt_forbids_elevating_meme_potential_for_serious_events() -> None:
    text = _prompt_text()
    assert "NEVER rate a serious or sensitive event" in text
    assert "death, injury, disaster, tragedy, serious crime, war" in text
    assert "surprising is not the same as meme-appropriate when real" in text


# ---------------------------------------------------------------------------
# CASE 5 - gym-like real case -> schema supports HIGH meme/viral rating (actual rating is an LLM
# judgment, verified via the golden replay, not here)
# ---------------------------------------------------------------------------


def test_case_5_output_schema_requires_story_led_and_potential_fields() -> None:
    import yaml

    raw = yaml.safe_load(Path("prompts/copywriting/v8.5.yaml").read_text(encoding="utf-8"))
    required = raw["output_schema"]["required"]
    assert "story_led" in required
    assert "viral_potential" in required
    assert "meme_potential" in required
    assert raw["output_schema"]["properties"]["meme_potential"]["enum"] == ["NONE", "LOW", "MEDIUM", "HIGH"]


def test_v85_is_new_and_earlier_versions_remain_byte_unmodified() -> None:
    v85_only_marker = "STORY-LED PRESERVATION"
    for frozen_version in ("v6", "v7", "v8", "v8.1", "v8.2", "v8.3", "v8.4"):
        frozen_text = Path(f"prompts/copywriting/{frozen_version}.yaml").read_text(encoding="utf-8")
        assert v85_only_marker not in frozen_text


# ---------------------------------------------------------------------------
# CASE 10 - duplicate same image on adjacent unrelated post -> fallback if safe
# ---------------------------------------------------------------------------


def _standard_decision() -> EditorialTreatmentDecision:
    return EditorialTreatmentDecision(STANDARD, human_review_required=False, reason="test")


@pytest.mark.asyncio
async def test_get_recently_attached_image_source_urls_finds_a_rank_1_attached_candidate_from_another_event(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    other_draft = await _make_task_and_draft(db_session, real_news_event)
    shared_url = "https://example.com/shared-photo.jpg?token=abc123"
    db_session.add(ImageCandidateRecord(
        news_event_id=real_news_event.id, content_draft_id=other_draft.id, candidate_id="cand-other",
        rank=1, source_url=shared_url, source_type=SourceType.RSS, discovery_method="og_image",
        storage_status=ImageStorageStatus.STORED, storage_key="fake/key.jpg", eligible_for_editorial=True,
    ))
    await db_session.flush()

    unrelated_event_id = uuid4()
    found = await get_recently_attached_image_source_urls(db_session, exclude_news_event_id=unrelated_event_id)
    assert sanitize_url(shared_url) in found


@pytest.mark.asyncio
async def test_get_recently_attached_image_source_urls_excludes_the_events_own_rows(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    draft = await _make_task_and_draft(db_session, real_news_event)
    own_url = "https://example.com/own-photo.jpg"
    db_session.add(ImageCandidateRecord(
        news_event_id=real_news_event.id, content_draft_id=draft.id, candidate_id="cand-own",
        rank=1, source_url=own_url, source_type=SourceType.RSS, discovery_method="og_image",
        storage_status=ImageStorageStatus.STORED, storage_key="fake/key.jpg", eligible_for_editorial=True,
    ))
    await db_session.flush()

    found = await get_recently_attached_image_source_urls(db_session, exclude_news_event_id=real_news_event.id)
    assert sanitize_url(own_url) not in found


@pytest.mark.asyncio
async def test_router_skips_a_recently_duplicated_image_and_falls_back_to_text_only(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CASE 10 integration proof: the router's own image-selection loop must skip a candidate
    whose source_url was already used by a different, unrelated recent post, per Part J."""
    settings.editorial_delivery_mode = "router"
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _REAL_CHAT_ID)
    monkeypatch.setattr(settings, "news_topic_id", _REAL_NEWS_TOPIC_ID)
    monkeypatch.setattr(settings, "content_generation_dry_run", False)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "6")

    duplicate_url = "https://example.com/reused-photo.jpg"
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        session.add(event)
        await session.commit()
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

        # a real, separate prior post (event + task + draft) that already used this same image
        other_event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        session.add(other_event)
        await session.commit()
        other_task = EditorialTask(event_id=other_event.id, priority=TaskPriority.B)
        session.add(other_task)
        await session.flush()
        other_draft = ContentDraft(task_id=other_task.id, type=ContentType.POST, title="t", body="b", hashtags=[])
        session.add(other_draft)
        await session.flush()
        other_event_id = other_event.id
        session.add(ImageCandidateRecord(
            news_event_id=other_event.id, content_draft_id=other_draft.id, candidate_id="cand-prior-post",
            rank=1, source_url=duplicate_url, source_type=SourceType.RSS, discovery_method="og_image",
            storage_status=ImageStorageStatus.STORED, storage_key="fake/key.jpg", eligible_for_editorial=True,
        ))
        await session.commit()

    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_message.return_value.message_id = 1

    from services.image_persistence import EditorialImageCandidate

    duplicate_candidate = EditorialImageCandidate(
        id=uuid4(), candidate_id="cand-dup", rank=1, relevance_score=90, quality_score=90,
        discovery_method="og_image", source_relationship="original_article", relevance_reason="high overlap",
        width=1200, height=800, observed_mime="image/jpeg", image_format="JPEG",
        storage_status="stored", storage_key="fake/key.jpg", telegram_file_id="FAKE_FILE_ID_DUP",
        editor_decision=None, source_url="https://example.com/reused-photo.jpg",
        article_url="https://example.com/article", warnings=None, is_expired=False,
    )

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch(
            "worker.content_cycle.get_editorial_image_candidates",
            new=AsyncMock(return_value=[duplicate_candidate]),
        ),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_photo.assert_not_called()
    fake_bot.send_message.assert_called_once()
    assert result.notified == 1
    assert result.router_image_sent == 0

    async with factory() as session:
        from sqlalchemy import delete
        await session.execute(delete(ImageCandidateRecord).where(ImageCandidateRecord.news_event_id == other_event_id))
        await session.commit()
