"""MEME PRODUCTION PIPELINE (overnight phase): services.meme_diversity -
build_recent_diversity_context(). Real Postgres (db_session fixture) - a bounded read query over
the existing MemeCandidate table, no new persistence.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.meme_candidate import MemeCandidate, MemeCandidateStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from services.meme_diversity import build_recent_diversity_context


async def _make_event(db_session: AsyncSession) -> NewsEvent:
    source = NewsSource(name=f"Diversity test source {uuid.uuid4()}", type=SourceType.RSS, active=True)
    db_session.add(source)
    await db_session.flush()
    event = NewsEvent(
        source_id=source.id, title="Diversity test event", content="x", category=EventCategory.AI,
        hash=f"diversity-{uuid.uuid4()}",
    )
    db_session.add(event)
    await db_session.flush()
    return event


async def _make_candidate(
    db_session: AsyncSession, event: NewsEvent, *, meme_format: str, humor_mechanism: str,
    visual_punchline: str | None = None,
) -> MemeCandidate:
    concept_data = {"meme_format": meme_format, "humor_mechanism": humor_mechanism}
    if visual_punchline is not None:
        concept_data["visual_punchline"] = visual_punchline
    candidate = MemeCandidate(
        news_event_id=event.id, status=MemeCandidateStatus.CONCEPT_GENERATED,
        concept_schema_version="v1",
        concept_data=concept_data,
        concept_regeneration_count=0,
    )
    db_session.add(candidate)
    await db_session.commit()
    await db_session.refresh(candidate)
    return candidate


@pytest.mark.asyncio
async def test_zero_prior_candidates_returns_none(db_session: AsyncSession) -> None:
    context = await build_recent_diversity_context(db_session, limit=10)
    assert context is None


@pytest.mark.asyncio
async def test_includes_format_and_mechanism_from_recent_candidates(db_session: AsyncSession) -> None:
    event = await _make_event(db_session)
    await _make_candidate(db_session, event, meme_format="drake_comparison", humor_mechanism="irony")

    context = await build_recent_diversity_context(db_session, limit=10)
    assert context is not None
    assert "drake_comparison" in context
    assert "irony" in context


@pytest.mark.asyncio
async def test_bounded_by_limit_never_unbounded(db_session: AsyncSession) -> None:
    event = await _make_event(db_session)
    for i in range(5):
        await _make_candidate(db_session, event, meme_format=f"format_{i}", humor_mechanism=f"mechanism_{i}")

    context = await build_recent_diversity_context(db_session, limit=2)
    assert context is not None
    formats_present = sum(1 for i in range(5) if f"format_{i}" in context)
    assert formats_present == 2  # never more than the bound, regardless of how many rows exist


@pytest.mark.asyncio
async def test_uses_settings_default_when_limit_not_supplied(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "meme_recent_diversity_lookback", 1)
    event = await _make_event(db_session)
    await _make_candidate(db_session, event, meme_format="format_a", humor_mechanism="mech_a")
    await _make_candidate(db_session, event, meme_format="format_b", humor_mechanism="mech_b")

    context = await build_recent_diversity_context(db_session)
    assert context is not None
    assert "format_b" in context  # most recent
    assert "format_a" not in context  # bound to 1, the older one is excluded


@pytest.mark.asyncio
async def test_malformed_concept_data_row_skipped_not_raised(db_session: AsyncSession) -> None:
    event = await _make_event(db_session)
    malformed = MemeCandidate(
        news_event_id=event.id, status=MemeCandidateStatus.CONCEPT_GENERATED,
        concept_schema_version="v1", concept_data={"unrelated_key": "x"}, concept_regeneration_count=0,
    )
    db_session.add(malformed)
    await db_session.commit()

    context = await build_recent_diversity_context(db_session, limit=10)
    assert context is None  # the one row has neither meme_format nor humor_mechanism - skipped


@pytest.mark.asyncio
async def test_includes_truncated_visual_punchline_snippet(db_session: AsyncSession) -> None:
    """MEME-PROD-4: visual_punchline is a stronger repetition signal than format/mechanism alone
    (two concepts can share a format label while telling a different joke) - surfaced truncated,
    never the full sentence."""
    event = await _make_event(db_session)
    long_punchline = "A" * 120
    await _make_candidate(
        db_session, event, meme_format="reaction", humor_mechanism="irony", visual_punchline=long_punchline,
    )

    context = await build_recent_diversity_context(db_session, limit=10)
    assert context is not None
    assert "visual_punchline~=" in context
    assert long_punchline not in context  # truncated, not the full sentence
    assert "A" * 60 in context  # the truncated prefix is present


@pytest.mark.asyncio
async def test_row_with_only_visual_punchline_is_not_skipped(db_session: AsyncSession) -> None:
    event = await _make_event(db_session)
    candidate = MemeCandidate(
        news_event_id=event.id, status=MemeCandidateStatus.CONCEPT_GENERATED,
        concept_schema_version="v1", concept_data={"visual_punchline": "A cat in sunglasses."},
        concept_regeneration_count=0,
    )
    db_session.add(candidate)
    await db_session.commit()

    context = await build_recent_diversity_context(db_session, limit=10)
    assert context is not None
    assert "A cat in sunglasses" in context
