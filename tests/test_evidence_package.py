"""Phase 19 M2: DB-integration tests for services.evidence_package (real Postgres, db_session,
rolled back at teardown). build_evidence_package() unconditionally queries
news_event_article_acquisitions (via get_effective_acquisition()) regardless of
article_acquisition_mode - it does not itself guard against the table not existing yet (see its
own docstring: that is a genuine schema mismatch, left to callers to catch). This file therefore
requires the Phase 19 M1 migration. The caller-level graceful-degradation guarantee (calling code
never crashes even with article_acquisition_mode == "enforce" before the migration lands) is
covered separately, without needing the migration, in tests/test_evidence_package_degradation.py.
"""
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from services.article_acquisition import compute_text_hash
from services.evidence_package import build_evidence_package

pytestmark = pytest.mark.skip(
    reason=(
        "Requires Alembic migration a3f7c9e15d02 (adds the 'news_event_article_acquisitions' "
        "table) to be applied first - build_evidence_package() unconditionally queries this "
        "table via get_effective_acquisition(). Remove this skip once the migration has been "
        "applied to the target database."
    )
)


async def _seed_event(session: AsyncSession, *, content: str | None, title: str = "A real headline") -> NewsEvent:
    source = NewsSource(id=uuid4(), name=f"src-{uuid4().hex[:6]}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        id=uuid4(), source_id=source.id, title=title, content=content, category=EventCategory.UNKNOWN,
        hash=f"h-{uuid4()}",
    )
    session.add(event)
    await session.flush()
    return event


@pytest.mark.asyncio
async def test_falls_back_to_rss_excerpt_when_no_acquisition_exists(db_session: AsyncSession) -> None:
    """The news_event_article_acquisitions table does not exist in this test database (migration
    unapplied) - get_effective_acquisition() degrades to None, and this must not raise; the
    package must fall back to the RSS excerpt exactly as pre-Phase-19 behavior would."""
    event = await _seed_event(db_session, content="This is the RSS excerpt content for the story.")

    package = await build_evidence_package(db_session, event)

    assert package.selected_editorial_text == "This is the RSS excerpt content for the story."
    assert package.rss_excerpt == "This is the RSS excerpt content for the story."
    assert package.completeness_level == "excerpt_only"
    assert package.extraction_method == "rss_excerpt_fallback"
    assert package.full_text is None
    assert package.canonical_url is None


@pytest.mark.asyncio
async def test_missing_content_falls_back_to_empty_string_not_none(db_session: AsyncSession) -> None:
    event = await _seed_event(db_session, content=None)

    package = await build_evidence_package(db_session, event)

    assert package.selected_editorial_text == ""
    assert package.rss_excerpt is None


@pytest.mark.asyncio
async def test_selected_editorial_text_hash_is_consistent_with_compute_text_hash(db_session: AsyncSession) -> None:
    event = await _seed_event(db_session, content="Some excerpt text.")

    package = await build_evidence_package(db_session, event)

    assert package.selected_editorial_text_hash == compute_text_hash("Some excerpt text.")


@pytest.mark.asyncio
async def test_known_evidence_gaps_reflect_missing_metadata(db_session: AsyncSession) -> None:
    event = await _seed_event(db_session, content="Excerpt only, no full article.")

    package = await build_evidence_package(db_session, event)

    assert "no_author_metadata" in package.known_evidence_gaps
    assert "no_language_detection" in package.known_evidence_gaps
    assert "single_source_only" in package.known_evidence_gaps
    assert "full_article_unavailable" in package.known_evidence_gaps


@pytest.mark.asyncio
async def test_source_metadata_is_populated_from_the_real_news_source(db_session: AsyncSession) -> None:
    event = await _seed_event(db_session, content="x")

    package = await build_evidence_package(db_session, event)

    assert package.source_type == "RSS"
    assert package.source_name is not None


@pytest.mark.asyncio
async def test_story_fields_stay_none_when_story_memory_mode_is_off(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.config import settings
    monkeypatch.setattr(settings, "story_memory_mode", "off")
    event = await _seed_event(db_session, content="x")

    package = await build_evidence_package(db_session, event)

    assert package.story_id is None
    assert package.story_match_type is None
    assert package.previous_coverage_summary is None


@pytest.mark.asyncio
async def test_quote_and_media_candidates_are_empty_lists_this_phase(db_session: AsyncSession) -> None:
    """Not yet implemented (Phase 19 M5/M9-M11) - the fields exist now so the schema shape does
    not change later, but they must never be None (always a well-typed empty list)."""
    event = await _seed_event(db_session, content="x")

    package = await build_evidence_package(db_session, event)

    assert package.quote_candidates == []
    assert package.media_candidates == []


@pytest.mark.asyncio
async def test_original_headline_is_always_the_real_news_event_title(db_session: AsyncSession) -> None:
    event = await _seed_event(db_session, content="x", title="Exact Real Title Here")

    package = await build_evidence_package(db_session, event)

    assert package.original_headline == "Exact Real Title Here"
