"""KAGE VIRAL STORY STRENGTH + ACTUALITY AUDIT (founder task 2026-09-26) - zero provider calls.

Inputs: two READ-ONLY pulls of production data (JSON lines): the last 48 hours of events (source, timestamps, Telegram engagement, story
link, the first 1,500 characters of the stored cleaned article) and the confirmed members of their stories (title, source, times) - from
which cluster_signals derives THIS event's momentum and first coverage, exactly as the planner does.
The most recent 24 hours first; extended to 48 hours only when fewer than 20 plausible KAGE candidates exist. Every plausible candidate
goes through the deterministic gate (services.instagram_viral_story_gate) - no Phase A, no Director, no image, no model.
Output: the per-candidate audit, the two products (A. strong viral stories, B. good KAGE news - not viral), the current best viral
candidate or the empty result. Only titles, sources, times, signals and verdicts are written - never the stored article text.
Usage: python scripts/_instagram_viral_story_audit.py <events.jsonl> <members.jsonl> <out dir>
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.instagram_feed_product import FeedCandidate, FeedFormat, _clean_title, kage_core, read_candidate  # noqa: E402
from services.instagram_viral_story_gate import (  # noqa: E402
    ClusterMember,
    assess_viral_story,
    best_viral_story,
    cluster_signals,
    same_event,
)

MIN_CANDIDATES = 20
AUDIT_SIZE = 25
EMPTY = "NO VIRAL STORY CURRENTLY STRONG ENOUGH"


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


MEMBERS: dict[str, list[ClusterMember]] = {}
RECENT: list[ClusterMember] = []  # every headline in the pull: cross-feed corroboration (the pull covers 48 of the planner's 72 hours)
NOW: list[datetime] = []


def candidate_of(row: dict) -> FeedCandidate:
    confirmed = row["match_type"] in ("story_update", "supporting_source", "semantic_duplicate", "new_story")
    cluster = cluster_signals(row["title"] or "", MEMBERS.get(row["story_id"], []) if confirmed else [], now=NOW[0],
                              recent_headlines=RECENT)
    return FeedCandidate(
        id=row["id"], title=row["title"] or "", summary=row["summary"] or "", source_name=row["source_name"] or "",
        source_type=row["source_type"] or "", category=row["category"] or "", views=row["views"],
        coverage=row["story_members"] or 1 if confirmed else 1, published_at=_dt(row["published_at"]),
        story_first_seen=cluster.get("story_first_seen"), independent_sources=cluster.get("independent_sources", 1),
        story_events_24h=cluster.get("story_events_24h", 1),
        on_hacker_news=bool(cluster.get("on_hacker_news")) or (row["source_name"] or "").lower().startswith("hacker news"),
        forwards=row["forwards"], reactions=row["reactions"])


GOLDENS = {
    # the accepted viral references, read with their OWN saved data on the day the replay planned them. Momentum then: DeepSeek came from
    # one source (Habr) - nothing else is recorded; the Hamster came from the Hacker News front page (its original: Runner's World).
    # Each golden is read twice: on its replay day (DeepSeek's Unit 42 disclosure is dated 30 July, 6 days before that replay - the
    # actuality gate now correctly calls that stale) and as a FRESH event (the day after its stated date), which is what the golden
    # characteristics regression is about: relevance, broad interest and inherent strength must stay STRONG.
    "deepseek": ("artifacts/instagram_feed_product/daily_media_cleanliness_20260926/live/2026-08-05_2_meme_trend", "2026-08-05T12:00:00+00:00",
                 "2026-07-31T12:00:00+00:00", {"independent_sources": 1, "on_hacker_news": False}),
    "hamster": ("artifacts/instagram_feed_product/e2e_week_2026-08-05_11/canary_run/2026-08-08_2_meme_trend", "2026-08-08T12:00:00+00:00",
                "2026-08-08T12:00:00+00:00", {"independent_sources": 1, "on_hacker_news": True}),
}


def golden_regression() -> dict:
    root = Path(__file__).resolve().parent.parent
    out = {}
    for name, (run, day, fresh_day, momentum) in GOLDENS.items():
        outcome = json.loads((root / run / "outcome.json").read_text(encoding="utf-8"))
        evidence = json.loads((root / run / "evidence_package.json").read_text(encoding="utf-8"))
        facts = " ".join(f.get("text", "") if isinstance(f, dict) else str(f) for f in evidence.get("facts") or [])
        candidate = FeedCandidate(id=name, title=outcome["title"], summary="", source_name=outcome["source"], source_type="RSS",
                                  published_at=None, **momentum)
        verdict = assess_viral_story(candidate, facts, now=datetime.fromisoformat(day))
        fresh = assess_viral_story(candidate, facts, now=datetime.fromisoformat(fresh_day))
        out[name] = {"title": outcome["title"], "replay_day": day[:10], "momentum_known": momentum,
                     "as_fresh_event": {"now": fresh_day[:10], "eligible": fresh.eligible, "first_failed_gate": fresh.failed_gate,
                                        "actuality": fresh.actuality.status, "strength": fresh.strength},
                     "eligible": verdict.eligible,
                     "first_failed_gate": verdict.failed_gate, "reason": verdict.reason, "actuality": verdict.actuality.status,
                     "date_source": verdict.actuality.date_source, "broad": verdict.broad_interest, "strength": verdict.strength,
                     "mechanisms": list(verdict.mechanisms), "hook": verdict.hook, "momentum": verdict.momentum}
    return out


def _key(row: dict) -> str:
    words = [w for w in re.findall(r"[a-zа-яё0-9]+", (row["title"] or "").lower()) if len(w) > 3]
    return "title:" + " ".join(words[:6])


def main() -> None:
    rows = [json.loads(line) for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if line.strip()]
    for line in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines():
        if line.strip():
            m = json.loads(line)
            MEMBERS.setdefault(m["story_id"], []).append(ClusterMember(
                title=m["title"] or "", source_id=m["source_id"], source_name=m["source_name"] or "",
                seen_at=_dt(m["published_at"]) or _dt(m["collected_at"]), collected_at=_dt(m["collected_at"])))
    RECENT.extend(ClusterMember(title=r["title"] or "", source_id=r["source_name"] or "", source_name=r["source_name"] or "",
                                seen_at=_dt(r["published_at"]) or _dt(r["collected_at"]), collected_at=_dt(r["collected_at"])) for r in rows)
    out = Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    now = _dt(rows[0]["now"])
    assert now is not None
    NOW.append(now)

    def plausible(window: timedelta) -> list[tuple[dict, FeedCandidate, object, object]]:
        """Every plausible KAGE candidate in the window, one per EVENT (same-event headlines collapse to the copy with the most stored
        text), with its gate verdict."""
        picked: list[tuple[dict, FeedCandidate, object, object]] = []
        for row in sorted(rows, key=lambda r: -len(r.get("article_text") or "")):
            if now - _dt(row["collected_at"]) > window:
                continue
            candidate = candidate_of(row)
            read = read_candidate(candidate)
            if read.format is FeedFormat.REJECT or not kage_core(_clean_title(candidate.title, candidate.source_name.lower())):
                continue
            if any(same_event(row["title"] or "", other[0]["title"] or "") for other in picked):
                continue
            picked.append((row, candidate, read, assess_viral_story(candidate, row.get("article_text") or "", now=now)))
        return picked

    window = timedelta(hours=24)
    pool = plausible(window)
    if len(pool) < MIN_CANDIDATES:
        window = timedelta(hours=48)
        pool = plausible(window)

    order = {"STRONG": 2, "MODERATE": 1, "NONE": 0}

    def viral_likeness(item: tuple) -> tuple:
        # the audit looks at the MOST viral-looking candidates: the gate's own signals, then the accepted read, then audience response
        row, candidate, read, verdict = item
        return (-verdict.eligible, -order[verdict.strength], -(verdict.broad_interest == "BROAD"),
                -(verdict.actuality.status == "CURRENT"), -order[verdict.momentum], -(read.format is FeedFormat.MEME_TREND and read.strong),
                -(candidate.views or 0))

    audited = sorted(pool, key=viral_likeness)[:AUDIT_SIZE]
    # the GTA IV mod story is classified under the general rule even when it falls outside the audited top rows
    gta = [r for r in rows if "GTA IV" in (r["title"] or "")][:1]
    extra = [(r, candidate_of(r), read_candidate(candidate_of(r))) for r in gta if all(r["id"] != a[0]["id"] for a in audited)]
    audited = [(r, c, rd) for r, c, rd, _v in audited]
    table, verdicts = [], []
    for row, candidate, read in [*audited, *extra[:1]]:
        verdict = assess_viral_story(candidate, row.get("article_text") or "", now=now)
        verdicts.append((candidate, verdict))
        age_h = round((now - (_dt(row["published_at"]) or _dt(row["collected_at"]))).total_seconds() / 3600, 1)
        table.append({
            "headline": _clean_title(candidate.title, candidate.source_name.lower()), "source": candidate.source_name,
            "event_id": row["id"], "story_id": row["story_id"], "article_published": row["published_at"],
            "event_actuality": verdict.actuality.status, "event_date_source": verdict.actuality.date_source, "article_age_hours": age_h,
            "feed_read": f"{read.format.value}{' (strong)' if read.strong else ''}", "kage_relevance": ", ".join(verdict.kage_core) or "NO",
            "broad_interest": verdict.broad_interest, "broad_reason": verdict.broad_reason, "strongest_factual_hook": verdict.hook,
            "viral_mechanisms": list(verdict.mechanisms), "inherent_strength": verdict.strength,
            "momentum": verdict.momentum, "momentum_evidence": list(verdict.momentum_signals), "visual_potential": verdict.visual_potential,
            "viral_eligible": "YES" if verdict.eligible and read.format is FeedFormat.MEME_TREND and read.strong
            else "YES (gate) - but not routed to the viral slot by the accepted KAGE-first read" if verdict.eligible else "NO",
            "first_failed_gate": verdict.failed_gate, "reason": verdict.reason, "good_kage_news": verdict.good_kage_news,
            "is_gta_reclassification_row": bool(extra) and row is extra[0][0],
        })
    routed = [(c, v) for (c, v), t in zip(verdicts, table) if t["viral_eligible"] == "YES"]
    best_routed = best_viral_story(routed)
    best_gate = best_viral_story(verdicts)
    gate_pass = [t for t in table if t["viral_eligible"] != "NO"]
    good_news = [t for t in table if t["viral_eligible"] == "NO" and t["good_kage_news"]]
    report = {
        "provider_calls": 0, "now": rows[0]["now"], "window_hours": int(window.total_seconds() // 3600),
        "events_in_pull": len(rows), "plausible_kage_candidates_in_window": len(pool), "audited": len(table),
        # A. stories that clear all six gates (rows can be copies of ONE event the lexical same-event test could not join)
        "strong_viral_stories": gate_pass,
        # B. relevant, not OLD, failed a later gate: usable as ordinary news
        "good_kage_news_not_viral": good_news,
        "best_gate_candidate": None if best_gate is None else next(t for t in table if t["event_id"] == best_gate[0].id),
        # what the planner does today: the viral slot takes only a strong MEME_TREND read that also clears the gate
        "as_routed_result": EMPTY if best_routed is None else next(t["headline"] for t in table if t["event_id"] == best_routed[0].id),
        "result": EMPTY if best_gate is None else "CANDIDATE", "golden_regression": golden_regression(), "audit": table,
    }
    (out / "viral_story_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# KAGE viral story audit - {report['now'][:16]} UTC, window {report['window_hours']}h", "",
             f"events pulled (48h): {len(rows)}; plausible KAGE candidates in window: {len(pool)}; audited: {len(table)}", "",
             "| # | headline | source | age h | actuality | KAGE | broad | strength | momentum | viral | first failed gate |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, t in enumerate(table, 1):
        lines.append(f"| {i} | {t['headline'][:90]} | {t['source'][:28]} | {t['article_age_hours']} | {t['event_actuality']} | "
                     f"{t['kage_relevance']} | {t['broad_interest']} | {t['inherent_strength']} | {t['momentum']} | "
                     f"{'YES' if t['viral_eligible'] == 'YES' else 'GATE' if t['viral_eligible'].startswith('YES') else 'NO'} | "
                     f"{t['first_failed_gate'] or '-'} |")
    lines += ["", "viral: YES = passes the gate and is routed to the viral slot; GATE = passes the gate but the accepted KAGE-first read does not "
              "route it to the viral slot; NO = fails a gate", "",
              f"**Gate result: {EMPTY if best_gate is None else 'best candidate: ' + report['best_gate_candidate']['headline']}**", "",
              f"**As routed today (planner viral slot): {report['as_routed_result']}**", "", "## Golden regression (saved data, replay day)", ""]
    for name, g in report["golden_regression"].items():
        f = g["as_fresh_event"]
        lines.append(f"- {name}: replay day {g['replay_day']}: eligible={g['eligible']}, first failed gate={g['first_failed_gate']}, "
                     f"actuality={g['actuality']} ({g['date_source']}), broad={g['broad']}, strength={g['strength']} {g['mechanisms']}, "
                     f"momentum={g['momentum']}; as a fresh event ({f['now']}): eligible={f['eligible']}, gate={f['first_failed_gate']}, "
                     f"actuality={f['actuality']}")
    (out / "viral_story_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("now", "window_hours", "plausible_kage_candidates_in_window", "audited", "result", "as_routed_result")}
                     | {"gate_pass": [t["headline"] for t in gate_pass], "good_news": len(good_news),
                        "golden": {k: (v["eligible"], v["first_failed_gate"], v["strength"], v["as_fresh_event"]["eligible"]) for k, v in report["golden_regression"].items()}},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
