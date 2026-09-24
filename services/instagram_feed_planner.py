"""The KAGE Instagram feed product, wired to the database and the existing trigger (see services/instagram_feed_product.py).

Daily: from the content cycle's fresh eligible events, read what each one is, count what Instagram already published today, and try the
shortlist of each OPEN slot (AI_HACK first) through the existing evaluate-and-submit chain. The existing pre-generation Director decision
must agree with the planned format (`required_feed_format`), otherwise the candidate is dropped before any Creative Director call and the
next one is tried; when the shortlist runs out, the slot stays empty. Ordinary news is never submitted as a daily post.

Weekly: over the previous 7 days of production Story identity (confirmed membership, fragments consolidated with Story Memory's own
match rule - services/instagram_weekly_recap.py), select what defined the week (AI / GADGET / VIRAL) that was not already a daily post
and submit it as ONE news-recap carousel. Runs only when `instagram_weekly_recap_enabled` is on and no
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
    read_with_evidence,
    stage_one_shortlist,
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
    daily_titles_this_week: list[str] = field(default_factory=list)
    daily_premise_by_story: dict[str, str] = field(default_factory=dict)  # the exact premise each daily post ran with


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
        director_input = row.package_snapshot.get("director_input") if isinstance(row.package_snapshot, dict) else None
        if isinstance(director_input, dict) and director_input.get("opportunity_summary"):
            usage.daily_titles_this_week.append(str(director_input["opportunity_summary"]))
            if row.source_story_id:
                usage.daily_premise_by_story[str(row.source_story_id)] = str(director_input["opportunity_summary"])
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
        select(NewsEvent, NewsSource.name, NewsSource.type, Story.event_count, Story.first_event_id, NewsEventStoryLink.match_type)
        .join(NewsSource, NewsSource.id == NewsEvent.source_id)
        .outerjoin(NewsEventStoryLink, NewsEventStoryLink.news_event_id == NewsEvent.id)
        .outerjoin(Story, Story.id == NewsEventStoryLink.story_id)
        .where(NewsEvent.id.in_(event_ids))
    )).all()
    seen: set[str] = set()
    candidates = []
    for event, source_name, source_type, event_count, first_event_id, match_type in rows:
        if str(event.id) in seen:
            continue
        seen.add(str(event.id))
        # a strong UNCERTAIN_MATCH is linked to a story for observability only - it must not inherit that story's coverage
        confirmed = first_event_id == event.id or match_type in CONFIRMED_MATCH_TYPES
        candidates.append(FeedCandidate(
            id=str(event.id), title=event.title or "", summary=(event.summary or event.content or "")[:600],
            source_name=source_name or "", source_type=getattr(source_type, "value", str(source_type or "")),
            category=getattr(event.category, "value", str(event.category or "")), views=event.views_count,
            coverage=int(event_count or 1) if confirmed else 1,
        ))
    return candidates


CONFIRMED_MATCH_TYPES = ("story_update", "supporting_source", "semantic_duplicate")


async def load_feed_evidence(session: Any, event_ids: list[UUID]) -> dict[str, str]:
    """The strongest STORED source material for a shortlist (no fetch, no model): the cleaned article text when article acquisition
    kept it, the event's own stored body, its confirmed Story siblings' bodies, and research facts when a NEWS_ANALYSIS already ran.
    NEWS_ANALYSIS is never required - it only adds what already exists."""
    from database.models.editorial_task import EditorialTask, TaskStatus
    from schemas.workflow import WorkflowType
    from database.models.news_event_article_acquisition import NewsEventArticleAcquisition
    from services.instagram_recap_bundle import _research_facts

    if not event_ids:
        return {}
    events = {e.id: e for e in (await session.execute(select(NewsEvent).where(NewsEvent.id.in_(event_ids)))).scalars().all()}
    acquisitions = {a.news_event_id: a for a in (await session.execute(
        select(NewsEventArticleAcquisition).where(NewsEventArticleAcquisition.news_event_id.in_(event_ids))
    )).scalars().all()}
    links = {link.news_event_id: link for link in (await session.execute(
        select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id.in_(event_ids))
    )).scalars().all()}
    story_ids = {link.story_id for link in links.values()}
    siblings: dict[Any, list[str]] = {}
    if story_ids:
        for link, body in (await session.execute(
            select(NewsEventStoryLink, NewsEvent.content).join(NewsEvent, NewsEvent.id == NewsEventStoryLink.news_event_id)
            .where(NewsEventStoryLink.story_id.in_(story_ids), NewsEventStoryLink.match_type.in_(CONFIRMED_MATCH_TYPES))
        )).all():
            if body:
                siblings.setdefault(link.story_id, []).append(body)
    tasks = {}
    for task in (await session.execute(
        select(EditorialTask).where(
            EditorialTask.event_id.in_(event_ids), EditorialTask.status == TaskStatus.COMPLETED,
            EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
        )
    )).scalars().all():
        tasks[task.event_id] = task
    out: dict[str, str] = {}
    for event_id, event in events.items():
        parts = []
        acquisition = acquisitions.get(event_id)
        if acquisition is not None and acquisition.cleaned_text:
            parts.append(acquisition.cleaned_text)
        if event.content:
            parts.append(event.content)
        link = links.get(event_id)
        # siblings only through a confirmed membership (or the story's own origin) - never through an observability-only link
        confirmed_link = link is not None and link.match_type in (*CONFIRMED_MATCH_TYPES, "new_story", "related_story")
        if confirmed_link:
            parts.extend(siblings.get(link.story_id, [])[:3])
        task = tasks.get(event_id)
        if task is not None:
            parts.extend(_research_facts(task.workflow))
        out[str(event_id)] = "\n".join(dict.fromkeys(p for p in parts if p and len(p) > 40))
    return out


def open_slots(candidates: list[FeedCandidate], usage: FeedUsage, *, day_key: str, evidence: dict[str, str] | None = None):
    """Pure planning step over loaded candidates: today's open slots with their shortlists (already-tried candidates excluded).
    With `evidence` (stage 2), only the cheap-screen shortlist is planned, each read again with its stored source material."""
    reads: list[tuple[FeedCandidate, FeedRead]] = [(c, read_candidate(c)) for c in candidates]
    if evidence is not None:
        reads = [(c, read_with_evidence(c, r, evidence.get(c.id, ""))) for c, r in stage_one_shortlist(reads)]
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


async def select_weekly_recap_candidates(
    session: Any, *, now: datetime, used_story_ids: set[str], daily_titles: list[str] | None = None,
    daily_premise_by_story: dict[str, str] | None = None, editor_gateway: Any = None, editor_prompt_repository: Any = None,
):
    """The week's recap on PRODUCTION Story identity (services/instagram_weekly_recap.py): every Story touched in the previous 7 days
    with its CONFIRMED members, plus each event that production linked only for observability (a strong UNCERTAIN_MATCH belongs to no
    confirmed story - it is its own unit), consolidated with Story Memory's own confirmed-match rule. With an editor gateway, the
    final selection is ONE weekly editor call over a deterministic candidate set (services/instagram_weekly_recap_editor.py); without
    one, or when that call fails or answers outside its contract, the deterministic "what defined the week" selection. Either way this
    week's daily stories and premises are not repeated. Returns `WeeklyRecapCandidate`s for `build_instagram_recap_bundle`."""
    from services.instagram_weekly_recap import RecapStory, consolidate, select_weekly_recap_items
    from services.instagram_weekly_recap_editor import WeeklyRecapEditorError
    from services.text_normalization import is_google_news_provenance
    from services.weekly_recap_selection import WeeklyRecapCandidate

    week_start = now - timedelta(days=7)
    rows = (await session.execute(
        select(NewsEventStoryLink, NewsEvent, NewsSource, Story)
        .join(NewsEvent, NewsEvent.id == NewsEventStoryLink.news_event_id)
        .join(NewsSource, NewsSource.id == NewsEvent.source_id)
        .join(Story, Story.id == NewsEventStoryLink.story_id)
        .where(NewsEvent.collected_at >= week_start)
    )).all()
    units: dict[str, list[tuple[Any, Any]]] = {}
    for link, event, source, story in rows:
        confirmed = story.first_event_id == event.id or link.match_type in CONFIRMED_MATCH_TYPES
        units.setdefault(str(story.id) if confirmed else f"event:{event.id}", []).append((event, source))
    stories = []
    representative: dict[str, Any] = {}
    for unit_id, members in units.items():
        members.sort(key=lambda m: m[0].collected_at)
        stories.append(RecapStory(
            story_id=unit_id, titles=tuple(e.title or "" for e, _ in members),
            sources=frozenset(src.name for e, src in members if not is_google_news_provenance(e.url, src.url)),
            first_seen=members[0][0].collected_at, category=getattr(members[0][0].category, "value", ""),
        ))
        representative[unit_id] = members[0][0]
    items = consolidate(stories)
    if editor_gateway is not None and editor_prompt_repository is not None:
        try:
            return await _weekly_editor_candidates(
                session, items, representative, now=now, daily_titles=daily_titles or [],
                daily_premise_by_story=daily_premise_by_story or {}, gateway=editor_gateway, prompt_repository=editor_prompt_repository,
            )
        except WeeklyRecapEditorError as exc:
            logger.warning("instagram_weekly_recap_editor_failed_deterministic_fallback", extra={"error": str(exc)[:300]})
    picks = select_weekly_recap_items(items, daily_story_ids=used_story_ids, daily_titles=daily_titles or [])
    out = []
    for pick in picks:
        main = max(pick.item.stories, key=lambda s: len(s.sources))
        event = representative[main.story_id]
        story_uuid = UUID(main.story_id) if not main.story_id.startswith("event:") else event.id
        out.append(WeeklyRecapCandidate(
            story_id=story_uuid, representative_event_id=event.id, relevance_tier=f"INSTAGRAM_WEEKLY_{pick.category}", score=None,
            significance=None, major_impact_override=False, company_key=None, entities=list(pick.item.evidence),
            updated_at=event.collected_at, reason=pick.why, rank_score=float(pick.score),
        ))
    return out


async def _weekly_editor_candidates(
    session: Any, items: list, representative: dict[str, Any], *, now: datetime, daily_titles: list[str],
    daily_premise_by_story: dict[str, str], gateway: Any, prompt_repository: Any,
) -> list:
    """ONE editor call; its validated picks become `WeeklyRecapCandidate`s (the primary candidate's widest Story fragment represents
    the item). A valid answer with no picks is respected - no recap, never filler."""
    from services.instagram_weekly_recap_editor import (
        EDITOR_MAX_ITEMS,
        EVIDENCE_TOP,
        attach_evidence,
        build_editor_candidates,
        run_weekly_recap_editor,
    )
    from services.weekly_recap_selection import WeeklyRecapCandidate

    candidates = build_editor_candidates(items, daily_premise_by_story=daily_premise_by_story)
    headline_event = {}
    for candidate in candidates[:EVIDENCE_TOP]:
        story = next((s for s in candidate.item.stories if candidate.headline in s.titles), None)
        if story is not None:
            headline_event[story.story_id] = representative[story.story_id].id
    by_event = await load_feed_evidence(session, list(headline_event.values()))
    candidates = attach_evidence(candidates, {sid: by_event.get(str(eid), "") for sid, eid in headline_event.items()})
    week_start = (now - timedelta(days=7)).date()
    result, _call = await run_weekly_recap_editor(
        gateway, prompt_repository, candidates=candidates, daily_premises=daily_titles,
        week_label=f"{week_start:%d %b} - {now.date():%d %b %Y}",
    )
    logger.info("instagram_weekly_recap_editor_selected", extra={
        "candidates": len(candidates), "picks": len(result.picks), "dropped": list(result.dropped)})
    out = []
    for pick in result.picks:
        main = max(pick.primary.item.stories, key=lambda s: len(s.sources))
        event = representative[main.story_id]
        story_uuid = UUID(main.story_id) if not main.story_id.startswith("event:") else event.id
        out.append(WeeklyRecapCandidate(
            story_id=story_uuid, representative_event_id=event.id, relevance_tier=f"INSTAGRAM_WEEKLY_{pick.category}", score=None,
            significance=None, major_impact_override=False, company_key=None, entities=list(pick.primary.item.evidence),
            updated_at=event.collected_at, reason=f"{pick.weekly_premise} - {pick.why_this_made_the_week}",
            rank_score=float(EDITOR_MAX_ITEMS + 1 - pick.rank),
        ))
    return out
