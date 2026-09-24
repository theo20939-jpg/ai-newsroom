"""Replay PRODUCTION Story identity over a real event window - in memory, zero-cost, no database writes.

Every event goes, in collection order, through the real `services.story_memory.match_story()` (same entity extraction, scoring,
thresholds and lookback), and its outcome is applied with the exact rules of `services.triage_orchestrator._apply_story_memory()`:
NEW_STORY / RELATED_STORY / a weak or company-only UNCERTAIN_MATCH create their own Story; the other outcomes attach to the matched
Story and only STORY_UPDATE / SUPPORTING_SOURCE / SEMANTIC_DUPLICATE bump `event_count`. Google News titles are stripped of their
publisher suffix only when provenance proves Google News, as the orchestrator does.

The only substitution: candidate Stories come from memory instead of `SELECT ... FROM stories` (`_fetch_candidate_stories`, same
lookback window, same updated_at ordering, same cap). arXiv papers are left out (their academic-identity filter reads persisted links;
they never enter an Instagram product anyway).

This exists because Story Memory was switched on in the local environment only on 2026-08-07 18:22 - most of the 5-11 Aug window was
never linked. Production links every triaged event.

Usage: python scripts/_instagram_story_identity_replay.py <window.json> <out.json>"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import services.story_memory as sm  # noqa: E402
from core.config import settings  # noqa: E402
from database.models.news_event import EventCategory  # noqa: E402
from database.models.story import Story  # noqa: E402
from services.text_normalization import is_google_news_provenance, strip_google_news_title_suffix  # noqa: E402

_SKIP_SOURCES = ("arXiv", "phase13-", "phase14-", "claims-test")


class _Memory:
    def __init__(self) -> None:
        self.stories: dict = {}  # insertion order == updated_at order (oldest first); re-inserted on update

    def touch(self, story: Story, when: datetime) -> None:
        story.updated_at = when
        self.stories.pop(story.id, None)
        self.stories[story.id] = story


class _Session:
    def __init__(self, memory: _Memory) -> None:
        self.memory = memory

    async def get(self, model, ident):
        return self.memory.stories.get(ident)

    async def execute(self, *args, **kwargs):  # only the academic-identity filter would query; arXiv events are skipped
        raise RuntimeError("unexpected query in story identity replay")


async def main() -> None:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    events = sorted((e for e in data["events"] if not e["source_name"].startswith(_SKIP_SOURCES)), key=lambda e: e["created_at"])
    memory = _Memory()

    async def fetch_candidates(session, *, now):
        cutoff = now - timedelta(days=settings.story_match_lookback_days)
        out = []
        for story in reversed(memory.stories.values()):  # newest first
            if story.updated_at < cutoff:
                break
            out.append(story)
            if len(out) >= sm._RETRIEVAL_FETCH_SAFETY_CAP:
                break
        return out

    docs: dict = {}  # story id -> [(title, url)] of its linked events - what the academic filter reads from news_event_story_links

    async def academic_filter(session, *, new_url, new_title, candidates):
        # same verdict function over the same per-story documents; only the SELECT is served from memory
        if not candidates or sm.extract_document_identity(url=new_url, title=new_title) is None:
            return candidates, []
        eligible, removed = [], []
        for candidate in candidates:
            verdict, reason = sm.candidate_story_identity_verdict(new_url=new_url, new_title=new_title,
                                                                  candidate_documents=docs.get(candidate.id, []))
            (eligible if verdict == sm.CANDIDATE_ELIGIBLE else removed).append(candidate if verdict == sm.CANDIDATE_ELIGIBLE
                                                                              else (candidate.id, reason))
        return eligible, removed

    sm._fetch_candidate_stories = fetch_candidates
    sm._filter_academic_identity_conflicts = academic_filter
    session = _Session(memory)
    links: dict[str, dict] = {}
    outcomes: dict[str, int] = {}
    for n, event in enumerate(events):
        when = datetime.fromisoformat(event["created_at"])
        title = event["title"]
        if is_google_news_provenance(event.get("url"), event.get("source_url")):
            title = strip_google_news_title_suffix(title)
        try:
            category = EventCategory(event.get("category") or "UNKNOWN")
        except ValueError:
            category = EventCategory.UNKNOWN
        signature, result = await sm.match_story(session, title=title, category=category, now=when, url=event.get("url"))
        outcomes[result.outcome] = outcomes.get(result.outcome, 0) + 1
        own = result.outcome in (sm.NEW_STORY, sm.RELATED_STORY) or (
            result.outcome == sm.UNCERTAIN_MATCH and result.entity_overlap < sm._RELATED_STORY_ENTITY_FLOOR
        ) or (result.outcome == sm.UNCERTAIN_MATCH and result.company_only_match and result.distinctive_overlap == 0.0)
        if own:
            story = Story(id=uuid4(), title=title, category=category, entities=signature.entities, keywords=signature.keywords,
                          topic_bucket=signature.topic_bucket, first_event_id=event["id"], event_count=1)
            story.created_at = when
            memory.touch(story, when)
        else:
            story = memory.stories[result.matched_story_id]
            if result.outcome in (sm.STORY_UPDATE, sm.SUPPORTING_SOURCE, sm.SEMANTIC_DUPLICATE):
                story.event_count += 1
                memory.touch(story, when)
        links[event["id"]] = {"story_id": str(story.id), "outcome": result.outcome}
        docs.setdefault(story.id, []).append((event["title"], event.get("url")))
        if n % 1000 == 0:
            print(f"{n}/{len(events)} stories={len(memory.stories)}", flush=True)
    stories = {str(s.id): {"title": s.title, "event_count": s.event_count, "first_event_id": str(s.first_event_id),
                           "category": s.category.value, "entities": list(s.entities or [])} for s in memory.stories.values()}
    Path(sys.argv[2]).write_text(json.dumps({"window": data["window"], "provider_calls": 0, "writes": 0, "outcomes": outcomes,
                                             "links": links, "stories": stories}, ensure_ascii=False), encoding="utf-8")
    print("events", len(events), "stories", len(stories), "outcomes", outcomes)


asyncio.run(main())
