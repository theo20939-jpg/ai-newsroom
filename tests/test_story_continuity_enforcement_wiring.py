"""STORY-CONTINUITY-P0-ENFORCEMENT-WIRING-FIX-1 — lifecycle + idempotency regression.

Reproduces the production defect: the constrained-enforcement suppress path committed a
`NewsEventStoryLink` without an editorial task and left the event `PROCESSING`, so every
stale-recovery re-processing of it raised `news_event_story_links_pkey` `UniqueViolation`
(`phase9_triage_phase_b_failed`). The fix is two independent safeguards in
`services/triage_orchestrator.py`:

* **lifecycle** — a suppressed event transitions to `EventStatus.ANALYZED` (terminal, never a
  stale-recovery candidate);
* **idempotency** — `_apply_story_memory()` short-circuits when a `NewsEventStoryLink` already
  exists for the event (no re-match, no re-link, no `event_count` re-bump), re-deriving the
  suppression decision from the persisted link.

The enforcement predicate itself is unchanged (see `test_story_continuity_constrained_enforcement.py`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.news_event import EventCategory, EventStatus, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from services.story_memory import SEMANTIC_DUPLICATE, MatchResult, extract_story_signature
from services.triage_orchestrator import (
    TriageCycleReport,
    _apply_story_memory,
    _run_phase_b,
    _select_recovery_candidates,
)
from tests.test_triage_orchestrator_claims import independent_session_factory

_UTC = timezone.utc


async def _seed(db_session: AsyncSession, title: str):
    src = NewsSource(name=f"p0ewf-{uuid4()}", type=SourceType.RSS, active=True)
    db_session.add(src)
    await db_session.flush()
    prior = NewsEvent(source_id=src.id, title=title, category=EventCategory.AI, hash=f"p0ewf-{uuid4()}")
    db_session.add(prior)
    await db_session.flush()
    sig = extract_story_signature(title, EventCategory.AI)
    story = Story(
        id=uuid4(), title=title, category=EventCategory.AI, entities=sig.entities,
        keywords=sig.keywords, topic_bucket=sig.topic_bucket, first_event_id=prior.id, event_count=3,
    )
    db_session.add(story)
    await db_session.flush()
    db_session.add(NewsEventStoryLink(
        news_event_id=prior.id, story_id=story.id, match_type="new_story", match_score=1.0,
    ))
    await db_session.flush()
    return src, story, sig


# =============================================================================================
# Idempotency — _apply_story_memory() short-circuits on an existing link
# =============================================================================================
@pytest.mark.asyncio
async def test_idempotent_when_link_already_exists_suppressed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")
    src, story, _ = await _seed(db_session, "OpenAI ships GPT-6 to GA")
    evt = NewsEvent(source_id=src.id, title="OpenAI ships GPT-6 to GA", category=EventCategory.AI, hash=f"p0ewf-{uuid4()}")
    db_session.add(evt)
    await db_session.flush()
    # a pre-existing SUPPRESSED link for this event (as the enforcement suppress path leaves it)
    db_session.add(NewsEventStoryLink(
        news_event_id=evt.id, story_id=story.id, match_type="semantic_duplicate", match_score=1.0,
        final_decision="DUPLICATE_NO_DELTA",
        decision_reason="DUPLICATE_NO_DELTA ... actually_suppressed=True enforcement=actually_suppressed:DUPLICATE_NO_DELTA ...",
        material_delta=["same_story", "actually_suppressed", "enforced:p0_constrained_v1"],
    ))
    await db_session.flush()

    def _boom(*a, **k):  # match_story must NOT be called
        raise AssertionError("match_story() was re-run for an event that already has a link")

    monkeypatch.setattr("services.triage_orchestrator.match_story", _boom)

    report = TriageCycleReport()
    result = await _apply_story_memory(db_session, evt, report)

    assert result is True  # re-derived from the persisted actually_suppressed=True
    links = (
        await db_session.execute(select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == evt.id))
    ).scalars().all()
    assert len(links) == 1  # no duplicate link
    await db_session.refresh(story)
    assert story.event_count == 3  # NOT re-bumped
    assert report.story_semantic_duplicates == 0  # no re-classification
    assert report.story_tasks_suppressed == 0  # not re-counted


@pytest.mark.asyncio
async def test_idempotent_when_link_already_exists_not_suppressed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")
    src, story, _ = await _seed(db_session, "Anthropic releases Claude 5")
    evt = NewsEvent(source_id=src.id, title="Anthropic releases Claude 5", category=EventCategory.AI, hash=f"p0ewf-{uuid4()}")
    db_session.add(evt)
    await db_session.flush()
    db_session.add(NewsEventStoryLink(
        news_event_id=evt.id, story_id=story.id, match_type="semantic_duplicate", match_score=1.0,
        final_decision="DUPLICATE_NO_DELTA",
        decision_reason="DUPLICATE_NO_DELTA ... actually_suppressed=False enforcement=fail_open:flag_disabled ...",
    ))
    await db_session.flush()
    monkeypatch.setattr(
        "services.triage_orchestrator.match_story",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("match_story re-run")),
    )
    result = await _apply_story_memory(db_session, evt, TriageCycleReport())
    assert result is False
    links = (
        await db_session.execute(select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == evt.id))
    ).scalars().all()
    assert len(links) == 1


@pytest.mark.asyncio
async def test_first_pass_still_inserts_exactly_one_link(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")
    monkeypatch.setattr(settings, "story_continuity_p0_constrained_enforcement_enabled", False)
    src, story, sig = await _seed(db_session, "Google DeepMind announces Gemini 3")
    evt = NewsEvent(source_id=src.id, title="Google DeepMind announces Gemini 3", category=EventCategory.AI, hash=f"p0ewf-{uuid4()}")
    db_session.add(evt)
    await db_session.flush()

    async def _fake(_s, *, title, category):  # noqa: ANN001, ARG001
        return sig, MatchResult(
            SEMANTIC_DUPLICATE, story.id, 1.0, "exact normalized title match",
            entity_overlap=0.0, has_distinctive_shared_entity=True,
        )

    monkeypatch.setattr("services.triage_orchestrator.match_story", _fake)
    await _apply_story_memory(db_session, evt, TriageCycleReport())
    links = (
        await db_session.execute(select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == evt.id))
    ).scalars().all()
    assert len(links) == 1
    # a genuine second pass (recovery) must be a no-op, not a UniqueViolation
    monkeypatch.setattr(
        "services.triage_orchestrator.match_story",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("match_story re-run on 2nd pass")),
    )
    await _apply_story_memory(db_session, evt, TriageCycleReport())
    links = (
        await db_session.execute(select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == evt.id))
    ).scalars().all()
    assert len(links) == 1  # still exactly one


# =============================================================================================
# Lifecycle — _select_recovery_candidates never selects an ANALYZED event
# =============================================================================================
@pytest.mark.asyncio
async def test_analyzed_event_is_not_a_recovery_candidate(db_session: AsyncSession) -> None:
    src = NewsSource(name=f"p0ewf-{uuid4()}", type=SourceType.RSS, active=True)
    db_session.add(src)
    await db_session.flush()
    stale = datetime.now(_UTC) - timedelta(hours=2)
    evt = NewsEvent(
        source_id=src.id, title="suppressed dup", category=EventCategory.AI, hash=f"p0ewf-{uuid4()}",
        status=EventStatus.ANALYZED,
    )
    db_session.add(evt)
    await db_session.flush()
    evt.updated_at = stale
    await db_session.flush()
    cands = await _select_recovery_candidates(
        db_session, now=datetime.now(_UTC), staleness_threshold_seconds=900
    )
    assert evt.id not in {c.id for c in cands}


# =============================================================================================
# End-to-end — the exact production bug: recovery of a suppressed event
# =============================================================================================
@pytest.mark.asyncio
async def test_recovery_of_suppressed_event_no_unique_violation_and_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1) event is a constrained-suppressible DUPLICATE_NO_DELTA  2) link committed, no task
    3) event reaches ANALYZED  4) a later recovery pass re-runs Phase B for it
    5) _apply_story_memory sees the existing link  6) NO UniqueViolation  7) still one link
    8) still zero tasks  9) audit evidence intact  10) event still ANALYZED.

    Drives `_run_phase_b()` directly for exactly this one event (not `run_triage_cycle()`, which
    would churn every other event in the shared test DB and pollute later tests)."""
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")
    monkeypatch.setattr(settings, "story_continuity_p0_constrained_enforcement_enabled", True)

    engine, factory = independent_session_factory()
    title = "Meta ships Muse agent to GA"
    from database.models.editorial_task import EditorialTask
    try:
        async with factory() as s:
            src = NewsSource(name=f"p0ewf-{uuid4()}", type=SourceType.RSS, active=True)
            s.add(src)
            await s.flush()
            prior = NewsEvent(source_id=src.id, title=title, category=EventCategory.AI, hash=f"p0ewf-{uuid4()}")
            s.add(prior)
            await s.flush()
            sig = extract_story_signature(title, EventCategory.AI)
            story = Story(
                id=uuid4(), title=title, category=EventCategory.AI, entities=sig.entities,
                keywords=sig.keywords, topic_bucket=sig.topic_bucket, first_event_id=prior.id, event_count=1,
            )
            s.add(story)
            await s.flush()
            s.add(NewsEventStoryLink(
                news_event_id=prior.id, story_id=story.id, match_type="new_story", match_score=1.0,
            ))
            evt = NewsEvent(source_id=src.id, title=title, category=EventCategory.AI,
                            hash=f"p0ewf-{uuid4()}", status=EventStatus.PROCESSING)
            s.add(evt)
            await s.flush()
            src_id, story_id, evt_id = src.id, story.id, evt.id
            await s.commit()

        async def _fake(_s, *, title, category):  # noqa: ANN001, ARG001
            return sig, MatchResult(
                SEMANTIC_DUPLICATE, story_id, 1.0, "exact normalized title match",
                entity_overlap=0.0, has_distinctive_shared_entity=True,
            )

        monkeypatch.setattr("services.triage_orchestrator.match_story", _fake)

        # --- Phase B #1: the event is suppressed ---
        async with factory() as s:
            r1 = TriageCycleReport()
            await _run_phase_b(s, evt_id, r1)
        assert r1.story_tasks_suppressed == 1
        assert r1.tasks_created == 0
        assert r1.other_failures == 0

        async with factory() as s:
            e = await s.get(NewsEvent, evt_id)
            assert e.status == EventStatus.ANALYZED          # lifecycle fix: terminal, not PROCESSING
            links = (await s.execute(select(NewsEventStoryLink).where(
                NewsEventStoryLink.news_event_id == evt_id))).scalars().all()
            assert len(links) == 1
            assert "actually_suppressed=True" in links[0].decision_reason
            tasks = (await s.execute(select(EditorialTask).where(EditorialTask.event_id == evt_id))).scalars().all()
            assert tasks == []
            # it is ANALYZED -> not a recovery candidate
            cands = await _select_recovery_candidates(
                s, now=datetime.now(_UTC), staleness_threshold_seconds=900
            )
            assert evt_id not in {c.id for c in cands}

        # --- force it back to stale PROCESSING (the pre-fix bug state) and re-run Phase B ---
        async with factory() as s:
            e = await s.get(NewsEvent, evt_id)
            e.status = EventStatus.PROCESSING
            e.updated_at = datetime.now(_UTC) - timedelta(hours=2)
            await s.commit()
        monkeypatch.setattr(
            "services.triage_orchestrator.match_story",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("match_story re-run in recovery")),
        )
        async with factory() as s:
            r2 = TriageCycleReport()
            await _run_phase_b(s, evt_id, r2)               # must NOT raise
        assert r2.other_failures == 0                       # no phase9_triage_phase_b_failed
        assert r2.tasks_created == 0

        async with factory() as s:
            e = await s.get(NewsEvent, evt_id)
            assert e.status == EventStatus.ANALYZED          # self-healed back to terminal
            links = (await s.execute(select(NewsEventStoryLink).where(
                NewsEventStoryLink.news_event_id == evt_id))).scalars().all()
            assert len(links) == 1                           # no duplicate link
            assert "actually_suppressed=True" in links[0].decision_reason  # audit preserved
            tasks = (await s.execute(select(EditorialTask).where(EditorialTask.event_id == evt_id))).scalars().all()
            assert tasks == []                               # still no task
    finally:
        async with factory() as s:
            from database.models.editorial_task import EditorialTask
            await s.execute(EditorialTask.__table__.delete().where(EditorialTask.event_id.in_(
                select(NewsEvent.id).where(NewsEvent.source_id == src_id))))
            await s.execute(NewsEventStoryLink.__table__.delete().where(
                NewsEventStoryLink.story_id == story_id))
            await s.execute(Story.__table__.delete().where(Story.id == story_id))  # before its first_event
            await s.execute(NewsEvent.__table__.delete().where(NewsEvent.source_id == src_id))
            await s.execute(NewsSource.__table__.delete().where(NewsSource.id == src_id))
            await s.commit()
        await engine.dispose()


# =============================================================================================
# Flag-OFF parity — no lifecycle change for non-suppressed events
# =============================================================================================
@pytest.mark.asyncio
async def test_flag_off_leaves_duplicate_no_delta_in_normal_flow(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")
    monkeypatch.setattr(settings, "story_continuity_p0_constrained_enforcement_enabled", False)
    src, story, sig = await _seed(db_session, "NVIDIA unveils Rubin GPU")
    evt = NewsEvent(source_id=src.id, title="NVIDIA unveils Rubin GPU", category=EventCategory.AI, hash=f"p0ewf-{uuid4()}")
    db_session.add(evt)
    await db_session.flush()

    async def _fake(_s, *, title, category):  # noqa: ANN001, ARG001
        return sig, MatchResult(
            SEMANTIC_DUPLICATE, story.id, 1.0, "exact normalized title match",
            entity_overlap=0.0, has_distinctive_shared_entity=True,
        )

    monkeypatch.setattr("services.triage_orchestrator.match_story", _fake)
    report = TriageCycleReport()
    suppress = await _apply_story_memory(db_session, evt, report)
    assert suppress is False
    assert report.story_tasks_suppressed == 0
    link = (
        await db_session.execute(select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == evt.id))
    ).scalar_one()
    assert link.final_decision == "DUPLICATE_NO_DELTA"
    assert "actually_suppressed=False" in link.decision_reason
