"""Replay the KAGE Instagram feed product over a real candidate window (zero-cost: no model, no network, no writes).

Input: a JSON export of real news_events for a window (read-only extraction from the local database: title, lead, source, views,
created_at, and the CURRENT system's MAJOR treatment per analysed event). For every day it shows what the old news-first lane would
have sent to Instagram (every MAJOR story) and what the feed product plans (`services/instagram_feed_product.py`): at most 2 posts,
AI_HACK first, TREND selective, no daily news. It then selects the week's news recap.

Coverage (how widely a story was carried) comes from Story Memory in production; the export has few story links, so this replay
approximates it by clustering near-identical titles across all events of the window (disclosed approximation).

The replay stands in for the Director confirmation with "first strong candidate wins" - in production each shortlisted item must
also be confirmed by the existing pre-generation Director decision, otherwise the slot stays empty.

Usage: python scripts/_instagram_feed_replay.py <window.json> <out.json>"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.instagram_feed_product import (  # noqa: E402
    FeedCandidate, FeedFormat, plan_daily_slots, read_candidate, select_weekly_recap,
)

_STOP = set(("that this with from have will your about into after over what when their they just more than been were says said "
             "artificial intelligence news could would should 2026 report reports first new года году после через также")
            .split())
_AGGREGATORS = ("Google News", "arXiv")
_NOISE_SOURCES = ("phase13-", "phase14-", "claims-test")


def _tokens(title: str) -> frozenset[str]:
    """Crude stems (first 6 letters), so 'австралиец' / 'австралийского' and 'спортзал' / 'спортзала' meet."""
    title = re.sub(r"\s+-\s+[^-]{2,40}$", "", title)  # Google News "Headline - Outlet"
    return frozenset(w[:6] for w in re.findall(r"[a-zа-яё0-9]+", title.lower()) if len(w) > 3 and w not in _STOP)


def _short_tokens(title: str) -> frozenset[str]:
    """For 'was this story already a daily post': stems of 3+ letters ('gym' counts), generic words excluded."""
    return frozenset(w[:6] for w in re.findall(r"[a-zа-яё0-9]+", title.lower()) if len(w) >= 3 and w not in _STOP
                     and w not in {"the", "and", "for", "its", "has", "now", "new", "как", "что", "это", "его", "все"})


def _same_story(a: str, b: str, df: collections.Counter) -> bool:
    """Brand names shared by many stories (Google, Gemini, agent) do not make two headlines one story; rare stems ('gym') do."""
    shared = [t for t in _short_tokens(a) & _short_tokens(b) if df[t] <= 25]
    return len(shared) >= 2 or (any(df[t] <= 10 for t in shared) and len(_short_tokens(a) & _short_tokens(b)) >= 2)


def _cluster(events: list[dict]) -> dict[str, int]:
    """event id -> story id. Two headlines are the same story when they share at least two RARE tokens (names such as Hassabis,
    DeepMind, Fold, GTA - rare across the window) within three days; linked transitively (union-find). A stand-in for Story Memory."""
    toks = [_tokens(e["title"]) for e in events]
    df = collections.Counter(t for ts in toks for t in ts)
    rare = [frozenset(t for t in ts if df[t] <= 12) for ts in toks]
    day = [e["created_at"][:10] for e in events]
    parent = list(range(len(events)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    postings = collections.defaultdict(list)
    for i, rs in enumerate(rare):
        for t in rs:
            postings[t].append(i)
    for i, rs in enumerate(rare):
        shared = collections.Counter(j for t in rs for j in postings[t] if j < i)
        for j, n in shared.items():
            if abs((_date(day[i]) - _date(day[j])).days) > 3:
                continue
            if n >= 2 and n >= 0.5 * min(len(rs), len(rare[j])):
                parent[find(i)] = find(j)
    return {e["id"]: find(i) for i, e in enumerate(events)}


def _date(value: str):
    from datetime import date

    return date.fromisoformat(value)


def main() -> None:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    events = [e for e in data["events"] if not e["source_name"].startswith(_NOISE_SOURCES)]
    owner = _cluster(events)
    short_df = collections.Counter(t for e in events for t in _short_tokens(e["title"]))
    # coverage = how many DIFFERENT outlets carried the story (aggregator copies and papers do not count)
    outlets: dict[int, set[str]] = collections.defaultdict(set)
    for e in events:
        if not e["source_name"].startswith(_AGGREGATORS):  # aggregator copies (incl. regional reposts) do not count
            outlets[owner[e["id"]]].add(e["source_name"].lower())
    size = {cid: max(1, len(names)) for cid, names in outlets.items()}
    size = collections.defaultdict(lambda: 1, size)
    reps: dict[int, dict] = {}
    for e in events:  # representative: the first non-aggregator, non-paper event of each cluster
        cid = owner[e["id"]]
        cur = reps.get(cid)
        if cur is None or (cur["source_name"].startswith(("Google News", "arXiv")) and not e["source_name"].startswith(("Google News", "arXiv"))):
            reps[cid] = e
    days = sorted({e["created_at"][:10] for e in events})
    report = {"window": data["window"], "provider_calls": 0, "days": [], "weekly_recap": []}
    week_reads = []
    used_daily: list[str] = []
    used_titles: list[str] = []
    for day in days:
        day_events = [e for e in events if e["created_at"][:10] == day]
        old = [e for e in day_events if e.get("treatment") == "MAJOR"]
        old_unique = {owner[e["id"]]: e for e in old}
        reads = []
        members = collections.defaultdict(list)
        for e in day_events:
            members[owner[e["id"]]].append(e)
        for cid, group in members.items():
            if reps[cid]["created_at"][:10] != day:
                continue  # a story belongs to the day it first appeared
            # a story is read at its best-framed version (the "here's how" article, not the plain news copy of the same launch)
            best = None
            for e in group:
                cand = FeedCandidate(id=e["id"], title=e["title"], summary=e.get("summary") or "", source_name=e["source_name"],
                                     source_type=e.get("source_type") or "", category=e.get("category") or "", views=e.get("views_count"),
                                     coverage=size[cid])
                read = read_candidate(cand)
                key = (read.strong and read.format.value in ("ai_hack", "meme_trend", "news_insight"), read.rank,
                       not e["source_name"].startswith(_AGGREGATORS))
                if best is None or key > best[0]:
                    best = (key, cand, read)
            reads.append((best[1], best[2]))
        week_reads.extend(reads)
        # the same story is never a daily post twice (production: the Phase A canonical-Story + angle duplicate guard)
        already = {c.id for c, _ in reads if any(_same_story(c.title, t, short_df) for t in used_titles)}
        plans = plan_daily_slots(reads, exclude_ids=already)
        picks = [{"format": p.format.value, "id": p.shortlist[0][0].id, "title": p.shortlist[0][0].title, "source": p.shortlist[0][0].source_name,
                  "reason": p.shortlist[0][1].reason,
                  "shortlist": [{"id": c.id, "title": c.title, "source": c.source_name, "rank": r.rank} for c, r in p.shortlist]} for p in plans]
        used_daily += [p["id"] for p in picks]
        # every version of a used story counts as used - emulates the production Phase A angle guard, which compares the Director's
        # language-agnostic angle; here the slot's shortlist carries the story's other framings (English / Russian copies). A later
        # candidate is only blocked when it shares 2+ stems with one of these titles, so unrelated neighbours block nothing unrelated.
        used_titles += [s["title"] for p in picks for s in p["shortlist"]]
        used_titles += [p["title"] for p in picks]
        fmt_counts = collections.Counter(r.format.value for _, r in reads)
        daily_news_leak = [c.title for c, r in reads if r.format is FeedFormat.WEEKLY_NEWS and r.strong]
        major_clusters = {owner[e["id"]] for e in old}
        old_major_given_daily_slot = [p["title"] for p in picks if owner.get(p["id"]) in major_clusters]
        report["days"].append({
            "day": day, "candidates": len(reads), "read_formats": dict(fmt_counts),
            "old_system_major": [{"title": e["title"], "source": e["source_name"]} for e in old_unique.values()],
            "old_system_posts": len(old_unique), "feed_posts": picks,
            "old_major_suppressed": [{"title": e["title"], "read": read_candidate(FeedCandidate(
                id=e["id"], title=e["title"], summary=e.get("summary") or "", source_name=e["source_name"], category=e.get("category") or "",
                coverage=size[owner[e["id"]]])).format.value} for e in old_unique.values()],
            "strong_weekly_news_as_daily": daily_news_leak, "old_major_given_daily_slot": old_major_given_daily_slot,
        })
    recap = select_weekly_recap(week_reads, used_daily_ids=used_daily)
    report["weekly_recap"] = [{"title": c.title, "source": c.source_name, "category": cat, "coverage": c.coverage, "kinds": list(r.kinds)}
                              for c, r, cat in recap]
    Path(sys.argv[2]).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for d in report["days"]:
        print(f"{d['day']}: old={d['old_system_posts']} feed={len(d['feed_posts'])} :: " +
              " | ".join(f"{p['format']}: {p['title'][:70]}" for p in d["feed_posts"]))
    print("RECAP:", *[f"[{r['category']} x{r['coverage']}] {r['title'][:80]}" for r in report["weekly_recap"]], sep="\n  ")


if __name__ == "__main__":
    main()
