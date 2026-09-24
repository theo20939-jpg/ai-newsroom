"""Replay the KAGE Instagram feed product over a real candidate window (zero-cost: no model, no network, no writes).

Inputs:
  window.json   - a read-only export of real news_events (title, stored content, source, views, created_at, and the CURRENT news-first
                  system's MAJOR treatment for analysed events);
  identity.json - production Story identity for the same window (scripts/_instagram_story_identity_replay.py: the real
                  story_memory.match_story() + the triage orchestrator's outcome rules).

Story identity is the production one - no title clustering. Coverage counts confirmed Story members only (origin + STORY_UPDATE /
SUPPORTING_SOURCE / SEMANTIC_DUPLICATE, as Story.event_count does), as unique outlets, over the event's consolidated fragments
(services/instagram_weekly_recap.py::consolidate, Story Memory's own entity evidence).

For every day it plans the daily feed twice: as commit b9733c2 did (headline read only) and with stage-2 evidence enrichment (the
shortlist read again with its stored source material: the event's own stored text plus its Story siblings' text). Then it selects the
week's news recap. "First strong candidate wins" stands in for the Director confirmation production requires before generation.

Usage: python scripts/_instagram_feed_replay.py <window.json> <identity.json> <out.json>"""
from __future__ import annotations

import collections
import functools
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.instagram_feed_product import (  # noqa: E402
    FeedCandidate, FeedFormat, plan_daily_slots, read_candidate, read_with_evidence, stage_one_shortlist,
)
from services.instagram_weekly_recap import RecapStory, consolidate, select_weekly_recap_items  # noqa: E402

_AGGREGATORS = ("Google News", "arXiv")
_STEM_STOP = {"that", "this", "with", "from", "have", "will", "your", "about", "after", "over", "what", "when", "their", "they", "just",
              "more", "than", "says", "said", "news", "systems", "систем", "которы", "теперь", "после"}


@functools.lru_cache(maxsize=None)
def _stems(title: str) -> frozenset[str]:
    from database.models.news_event import EventCategory
    from services.story_memory import extract_story_signature

    return frozenset(k[:6] for k in extract_story_signature(title, EventCategory.UNKNOWN).keywords if len(k) >= 4 and k[:6] not in _STEM_STOP)


_CONFIRMED = ("story_update", "supporting_source", "semantic_duplicate")


def main() -> None:
    events = {e["id"]: e for e in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["events"]}
    identity = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    confirmed: dict[str, list[dict]] = collections.defaultdict(list)
    for event_id, link in identity["links"].items():
        story = identity["stories"][link["story_id"]]
        if story["first_event_id"] == event_id or link["outcome"] in _CONFIRMED:
            confirmed[link["story_id"]].append(events[event_id])
        else:
            # production links a strong UNCERTAIN_MATCH to a story for observability without making it a member; such an event
            # belongs to no confirmed story, so it is its own unit here (otherwise every story-level view silently drops it)
            confirmed[f"event:{event_id}"].append(events[event_id])
    stories = []
    for story_id, members in confirmed.items():
        members.sort(key=lambda e: e["created_at"])
        stories.append(RecapStory(
            story_id=story_id, titles=tuple(e["title"] for e in members),
            sources=frozenset(e["source_name"] for e in members if not e["source_name"].startswith(_AGGREGATORS)),
            first_seen=datetime.fromisoformat(members[0]["created_at"]), category=members[0].get("category") or "",
        ))
    items = consolidate(stories)
    item_of = {sid: n for n, item in enumerate(items) for sid in item.story_ids}
    unit_of = {e['id']: uid for uid, members in confirmed.items() for e in members}
    days = sorted({s.first_seen.date().isoformat() for s in stories})
    report = {"window": identity["window"], "provider_calls": 0, "story_identity": "production story_memory.match_story replay",
              "stories": len(stories), "consolidated_items": len(items), "days": []}
    used_items = {"b9733c2": set(), "enriched": set()}
    used_titles: dict[str, list[str]] = {"b9733c2": [], "enriched": []}
    daily_ids: list[str] = []
    daily_titles: list[str] = []
    for day in days:
        reads = []
        evidence_of = {}
        for story in (s for s in stories if s.first_seen.date().isoformat() == day):
            members = confirmed[story.story_id]
            coverage = items[item_of[story.story_id]].coverage
            best = None
            for e in members:  # a story is read at its best-framed member
                cand = FeedCandidate(id=story.story_id, title=e["title"], summary=e.get("summary") or "", source_name=e["source_name"],
                                     source_type=e.get("source_type") or "", category=e.get("category") or "", views=e.get("views_count"),
                                     coverage=coverage)
                read = read_candidate(cand)
                key = (read.strong and read.format in (FeedFormat.AI_HACK, FeedFormat.MEME_TREND, FeedFormat.NEWS_INSIGHT), read.rank,
                       not e["source_name"].startswith(_AGGREGATORS))
                if best is None or key > best[0]:
                    best = (key, cand, read, e)
            reads.append((best[1], best[2]))
            # stored evidence: this member's own stored text first, then its confirmed Story siblings' (no fetch, no model)
            texts = [best[3].get("content") or ""] + [m.get("content") or "" for m in members if m is not best[3]]
            evidence_of[story.story_id] = "\n".join(dict.fromkeys(t for t in texts if t and len(t) > 40))
        day_report = {"day": day, "candidates": len(reads)}
        for mode in ("b9733c2", "enriched"):
            if mode == "enriched":
                final = [(c, read_with_evidence(c, r, evidence_of.get(c.id, ""))) for c, r in stage_one_shortlist(reads)]
            else:
                final = reads
            # the same event is never a daily post twice: production uses the Story identity AND the Phase A angle guard (the
            # Director's language-agnostic angle). The replay cannot run the Director, so it emulates that guard with Story Memory's
            # own keywords (6-letter stems, 3+ shared) against the posts already made - labelled emulation, not identity.
            excluded = {c.id for c, _ in final if item_of[c.id] in used_items[mode]
                        or any(len(_stems(c.title) & _stems(t)) >= 3 for t in used_titles[mode])}
            plans = plan_daily_slots(final, exclude_ids=excluded)
            picks = []
            for p in plans:
                c, r = p.shortlist[0]
                picks.append({"format": p.format.value, "story_id": c.id, "title": c.title, "source": c.source_name, "reason": r.reason,
                              "coverage": c.coverage, "shortlist": [{"title": x.title, "source": x.source_name, "rank": y.rank,
                                                                     "reason": y.reason} for x, y in p.shortlist]})
                used_items[mode].add(item_of[c.id])
                used_titles[mode].extend([c.title] + [x.title for x, _ in p.shortlist])
                if mode == "enriched":
                    daily_ids.extend(items[item_of[c.id]].story_ids)
                    daily_titles.append(c.title)
            upgrades = [{"title": c.title, "format": r.format.value, "reason": r.reason} for c, r in final
                        if mode == "enriched" and "stored evidence" in r.reason]
            demotions = [{"title": c.title, "reason": r.reason} for c, r in final if mode == "enriched" and "the body shows" in r.reason]
            day_report[mode] = {"posts": picks, "upgrades": upgrades, "demotions": demotions}
        old = [e for e in events.values() if e["created_at"][:10] == day and e.get("treatment") == "MAJOR"]
        old_units = {unit_of[e["id"]] for e in old if e["id"] in unit_of}
        day_report["old_system_major_stories"] = len({item_of[u] for u in old_units})
        day_report["old_major_given_daily_slot"] = [p["title"] for p in day_report["enriched"]["posts"]
                                                    if item_of[p["story_id"]] in {item_of[u] for u in old_units}]
        report["days"].append(day_report)
    recap = select_weekly_recap_items(items, daily_story_ids=daily_ids, daily_titles=daily_titles)
    report["weekly_recap"] = [{"headline": p.item.headline, "category": p.category, "coverage": p.item.coverage,
                               "languages": sorted(p.item.languages), "fragments": len(p.item.stories), "why": p.why,
                               "titles": list(p.item.titles)[:12], "evidence": list(p.item.evidence)} for p in recap]
    Path(sys.argv[3]).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for d in report["days"]:
        for mode in ("b9733c2", "enriched"):
            print(f"{d['day']} {mode:8}: " + " | ".join(f"{p['format']}: {p['title'][:70]}" for p in d[mode]["posts"]))
    print("RECAP:", *[f"[{r['category']} x{r['coverage']} {'+'.join(r['languages'])} f{r['fragments']}] {r['headline'][:90]}"
                      for r in report["weekly_recap"]], sep="\n  ")


if __name__ == "__main__":
    main()
