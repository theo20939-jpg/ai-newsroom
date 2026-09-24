"""The KAGE Instagram feed product, wired to the database and the existing trigger (see services/instagram_feed_product.py).

Daily: from the content cycle's fresh eligible events, read what each one is, count what Instagram already published today, and try the
shortlist of each OPEN slot (AI_HACK first) through the existing evaluate-and-submit chain. The existing pre-generation Director decision
must agree with the planned format (`required_feed_format`), otherwise the candidate is dropped before any Creative Director call and the
next one is tried; when the shortlist runs out, the slot stays empty. Ordinary news is never submitted as a daily post.

Weekly: over the previous 7 days of Story Memory (coverage = Story.event_count), select the strongest AI / GADGET / VIRAL stories that
were not already a daily post and submit them as ONE news-recap carousel. Runs only when `instagram_weekly_recap_enabled` is on and no
recap was delivered in the previous 7 days; this module picks no publishing time.

No new table: today's counts come from `instagram_editorial_deliveries` (initial versions; HOLD / BLOCK never take a slot), the format
from the Creative Director archetype already recorded in each package snapshot."""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select

from database.models.instagram_editorial_delivery import InstagramEditorialDelivery, InstagramEditorialDeliveryState
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from services.instagram_feed_product import (
    ARCHETYPE_BY_FORMAT,
    FORMAT_BY_ARCHETYPE,
    FeedCandidate,
    FeedFormat,
    FeedRead,
    plan_daily_slots,
    read_candidate,
    select_weekly_recap,
)

logger = logging.getLogger(__name__)

_NOT_A_SLOT = (InstagramEditorialDeliveryState.HOLD, InstagramEditorialDeliveryState.BLOCK)
# a candidate the Director declined is not tried again the same day (events stay eligible across content cycles; without this every
# cycle would pay for the same declined decision). Per process - a worker restart may retry a candidate once.
_TRIED: dict[str, set[str]] = {}


@dataclass
class FeedUsage:
    today_by_format: Counter = field(default_factory=Counter)
    today_total: int = 0
    news_insight_this_week: int = 0
    recap_this_week: bool = False
    daily_story_ids_this_week: set[str] = field(default_factory=set)


def _archetype(snapshot: Any) -> str | None:
    if not isinstance(snapshot, dict):
        return None
    director_input = snapshot.get("director_input")
    if isinstance(director_input, dict) and director_input.get("content_archetype"):
        return str(director_input["content_archetype"])
    package = snapshot.get("package")
    media_plan = package.get("media_plan") if isinstance(package, dict) else None
    return str(media_plan.get("content_archetype")) if isinstance(media_plan, dict) and media_plan.get("content_archetype") else None


async def load_feed_usage(session: Any, *, now: datetime) -> FeedUsage:
    """What Instagram already published: today (UTC day) and in the previous 7 days."""
    day_start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    rows = (await session.execute(
        select(InstagramEditorialDelivery).where(
            InstagramEditorialDelivery.version == 1, InstagramEditorialDelivery.created_at >= week_start,
        )
    )).scalars().all()
    usage = FeedUsage()
    for row in rows:
        if row.state in _NOT_A_SLOT:
            continue
        archetype = _archetype(row.package_snapshot)
        if archetype == "news_recap":
            usage.recap_this_week = True
            if row.created_at >= day_start:
                usage.today_total += 1  # the weekly recap is a feed post too: it counts towards the day's hard maximum
            continue
        if row.source_story_id:
            usage.daily_story_ids_this_week.add(str(row.source_story_id))
        fmt = FORMAT_BY_ARCHETYPE.get(archetype or "")
        if fmt is FeedFormat.NEWS_INSIGHT:
            usage.news_insight_this_week += 1
        if row.created_at >= day_start:
            usage.today_total += 1
            if fmt is not None:
                usage.today_by_format[fmt] += 1
    return usage


FEED_POOL_HOURS = 36
FEED_POOL_LIMIT = 600


async def load_recent_event_ids(session: Any, *, now: datetime, hours: int = FEED_POOL_HOURS, limit: int = FEED_POOL_LIMIT) -> list[UUID]:
    """Instagram's OWN candidate pool: every event collected recently, from every source. The Telegram news queue (analysed, above
    the news-score bar) is the wrong pool for this product - a prompt trick or a hamster on Strava rarely scores as news. The
    deterministic read filters the pool for free; only a shortlist ever reaches a Director decision."""
    rows = (await session.execute(
        select(NewsEvent.id).where(NewsEvent.collected_at >= now - timedelta(hours=hours))
        .order_by(NewsEvent.collected_at.desc()).limit(limit)
    )).scalars().all()
    return list(rows)


async def load_feed_candidates(session: Any, event_ids: list[UUID]) -> list[FeedCandidate]:
    if not event_ids:
        return []
    rows = (await session.execute(
        select(NewsEvent, NewsSource.name, NewsSource.type, Story.event_count)
        .join(NewsSource, NewsSource.id == NewsEvent.source_id)
        .outerjoin(NewsEventStoryLink, NewsEventStoryLink.news_event_id == NewsEvent.id)
        .outerjoin(Story, Story.id == NewsEventStoryLink.story_id)
        .where(NewsEvent.id.in_(event_ids))
    )).all()
    seen: set[str] = set()
    candidates = []
    for event, source_name, source_type, event_count in rows:
        if str(event.id) in seen:
            continue
        seen.add(str(event.id))
        candidates.append(FeedCandidate(
            id=str(event.id), title=event.title or "", summary=(event.summary or event.content or "")[:600],
            source_name=source_name or "", source_type=getattr(source_type, "value", str(source_type or "")),
            category=getattr(event.category, "value", str(event.category or "")), views=event.views_count, coverage=int(event_count or 1),
        ))
    return candidates


def open_slots(candidates: list[FeedCandidate], usage: FeedUsage, *, day_key: str):
    """Pure planning step over loaded candidates: today's open slots with their shortlists (already-tried candidates excluded)."""
    reads: list[tuple[FeedCandidate, FeedRead]] = [(c, read_candidate(c)) for c in candidates]
    usage_counts = {fmt: usage.today_by_format.get(fmt, 0) for fmt in ARCHETYPE_BY_FORMAT}
    # posts whose format is unknown (a SINGLE / REEL package) still count towards the hard daily maximum
    unknown = max(0, usage.today_total - sum(usage_counts.values()))
    if unknown:
        usage_counts[FeedFormat.NEWS_INSIGHT] = usage_counts.get(FeedFormat.NEWS_INSIGHT, 0) + unknown
    return reads, plan_daily_slots(reads, published_today=usage_counts, news_insight_this_week=usage.news_insight_this_week,
                                   exclude_ids=_TRIED.get(day_key, set()))


def mark_tried(day_key: str, candidate_id: str) -> None:
    for key in [k for k in _TRIED if k != day_key]:
        del _TRIED[key]
    _TRIED.setdefault(day_key, set()).add(candidate_id)


def weekly_recap_identity(now: datetime) -> str:
    """One recap per ISO week - the opportunity id (and therefore the package identity) is keyed by it."""
    year, week, _ = now.isocalendar()
    return f"kage-weekly-news-recap-{year}-W{week:02d}"


async def select_weekly_recap_candidates(session: Any, *, now: datetime, used_story_ids: set[str]):
    """Story-level weekly selection: every Story touched in the previous 7 days, read at its representative headline, with
    Story Memory's event_count as coverage. Returns `WeeklyRecapCandidate`s for `build_instagram_recap_bundle` (editorial order)."""
    from services.weekly_recap_selection import WeeklyRecapCandidate

    stories = (await session.execute(select(Story).where(Story.updated_at >= now - timedelta(days=7)))).scalars().all()
    if not stories:
        return []
    events = {e.id: e for e in (await session.execute(
        select(NewsEvent).where(NewsEvent.id.in_([s.first_event_id for s in stories]))
    )).scalars().all()}
    sources = {s.id: s for s in (await session.execute(
        select(NewsSource).where(NewsSource.id.in_({e.source_id for e in events.values()}))
    )).scalars().all()}
    reads = []
    by_id = {}
    for story in stories:
        event = events.get(story.first_event_id)
        if event is None:
            continue
        source = sources.get(event.source_id)
        candidate = FeedCandidate(
            id=str(story.id), title=story.title or event.title or "", summary=(event.summary or "")[:600],
            source_name=source.name if source else "", source_type=getattr(getattr(source, "type", None), "value", ""),
            category=getattr(story.category, "value", str(story.category or "")), coverage=int(story.event_count or 1),
        )
        reads.append((candidate, read_candidate(candidate)))
        by_id[candidate.id] = (story, event)
    picked = select_weekly_recap(reads, used_daily_ids=used_story_ids)
    out = []
    for candidate, read, category in picked:
        story, event = by_id[candidate.id]
        out.append(WeeklyRecapCandidate(
            story_id=story.id, representative_event_id=event.id, relevance_tier=f"INSTAGRAM_WEEKLY_{category}", score=None,
            significance=None, major_impact_override=False, company_key=None, entities=list(story.entities or []),
            updated_at=story.updated_at, reason=read.reason, rank_score=float(candidate.coverage),
        ))
    return out
