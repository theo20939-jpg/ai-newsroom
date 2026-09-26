"""KAGE VIRAL NOMINATION + EVIDENCE AUDIT (founder tasks 2026-09-26) - zero provider calls, zero database writes.

Inputs: two READ-ONLY pulls of production data (JSON lines): the last 48 hours of events (url, source, timestamps, Telegram engagement,
story link, the first 1,500 characters of the stored cleaned article) and the confirmed members of their stories.
The planner's own path, offline: the fresh KAGE pool of the most recent 24 hours (extended to 48 hours only when fewer than 20 plausible
candidates exist) -> services.instagram_viral_nomination (distinct FACTUAL events, event-level actuality / momentum, the accepted gate)
-> for each event the evidence preflight on its STORED body evidence, and - with --acquire - on the body the EXISTING acquisition path
returns (build_daily_evidence_package in its offline mode: session=None, a plain acquire_article() fetch, nothing persisted, no media, no
model). No Phase A, no Director, no image. Only titles, sources, times, signals, checks and verdicts are written - never article text.
Usage: python scripts/_instagram_viral_story_audit.py <events.jsonl> <members.jsonl> <out dir> [--acquire]
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.instagram_feed_product import FeedCandidate, FeedFormat, _clean_title, kage_core, read_candidate  # noqa: E402
from services.instagram_viral_nomination import (  # noqa: E402
    ViralEvent,
    evidence_preflight,
    nominate_viral_events,
    viral_evidence_preflight,
)
from services.instagram_viral_story_gate import ClusterMember, assess_viral_story, plain_text  # noqa: E402

MIN_CANDIDATES = 20
AUDIT_EVENTS = 25
EMPTY = "NO VIRAL STORY CURRENTLY STRONG ENOUGH"
CONFIRMED = ("story_update", "supporting_source", "semantic_duplicate", "new_story")


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def load(events_path: str, members_path: str):
    rows = [json.loads(line) for line in Path(events_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    members: dict[str, list[ClusterMember]] = {}
    for line in Path(members_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            m = json.loads(line)
            members.setdefault(m["story_id"], []).append(ClusterMember(
                title=m["title"] or "", source_id=m["source_id"], source_name=m["source_name"] or "",
                seen_at=_dt(m["published_at"]) or _dt(m["collected_at"]), collected_at=_dt(m["collected_at"])))
    return rows, members


def candidate_of(row: dict, members: dict[str, list[ClusterMember]]) -> FeedCandidate:
    confirmed = row["match_type"] in CONFIRMED
    return FeedCandidate(
        id=row["id"], title=row["title"] or "", summary=row["summary"] or "", source_name=row["source_name"] or "",
        source_type=row["source_type"] or "", category=row["category"] or "", views=row["views"], published_at=_dt(row["published_at"]),
        forwards=row["forwards"], reactions=row["reactions"],
        story_history=tuple(members.get(row["story_id"], [])) if confirmed and row["story_id"] else ())


def stored_body(event: ViralEvent, by_id: dict[str, dict]) -> list[str]:
    """What load_feed_evidence would give this event: stored article text and stored (non-headline) summaries of its copies."""
    lines: list[str] = []
    for cid in event.candidate_ids:
        row = by_id[cid]
        lines += [t for t in (row.get("article_text") or "", plain_text(row.get("summary") or "")) if t]
    return lines


async def acquire(event: ViralEvent, by_id: dict[str, dict]) -> dict:
    """The EXISTING acquisition path, offline (no session => plain acquire_article(), nothing persisted; media off; no model)."""
    from services.instagram_evidence_package import build_daily_evidence_package

    from worker.content_cycle import _VIRAL_EVIDENCE_COPIES

    tried = []
    # exactly the worker's order and bound (worker.content_cycle._viral_evidence_copy): the planned evidence copy, then the other copies
    from services.text_normalization import is_google_news_redirect_host

    others = [cid for cid in event.candidate_ids if cid != event.evidence_candidate.id]
    order = [event.evidence_candidate.id, *sorted(others, key=lambda cid: is_google_news_redirect_host(by_id[cid].get("url") or ""))]
    for cid in order[:_VIRAL_EVIDENCE_COPIES]:
        row = by_id[cid]
        package = await build_daily_evidence_package(
            post_id=cid, fmt=FeedFormat.MEME_TREND.value, title=row["title"] or "", url=row.get("url"), source_type=row["source_type"] or "RSS",
            source_name=row["source_name"], stored_body=row.get("summary"), event=None, event_id=UUID(cid), session=None,
            acquisition_enabled=True, media_mode="off")
        body = [item.exact_text for item in (*package.steps, *package.facts, *package.limitations)]
        preflight = viral_evidence_preflight(event, title=row["title"] or "", body_lines=body, published_at=_dt(row["published_at"]))
        statuses = [s.status for s in package.sources if s.source_type in ("original_article", "linked_article", "ORIGINAL_ARTICLE", "LINKED_ARTICLE")]
        tried.append({"source": row["source_name"], "headline": row["title"], "url_host": (row.get("url") or "").split("/")[2] if row.get("url") else None,
                      "acquisition_status": statuses[0] if statuses else "NO_URL", "body_chars": sum(len(b) for b in body),
                      "package_quality": package.quality, "preflight": preflight.status, "checks": preflight.checks, "reason": preflight.reason})
        if preflight.status == "PASS":
            break
    best = "PASS" if any(t["preflight"] == "PASS" for t in tried) else "FAIL" if any(t["preflight"] == "FAIL" for t in tried) else "PENDING"
    return {"status": best, "attempts": tried}


GOLDENS = {
    # the accepted viral references with their OWN saved data: on the replay day and as a FRESH event (the day after its stated date)
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
        candidate = FeedCandidate(id=name, title=outcome["title"], summary="", source_name=outcome["source"], source_type="RSS", **momentum)
        replay = assess_viral_story(candidate, facts, now=datetime.fromisoformat(day))
        fresh = assess_viral_story(candidate, facts, now=datetime.fromisoformat(fresh_day))
        out[name] = {"title": outcome["title"], "strength": replay.strength, "mechanisms": list(replay.mechanisms),
                     "replay_day": {"now": day[:10], "eligible": replay.eligible, "gate": replay.failed_gate, "actuality": replay.actuality.type},
                     "as_fresh_event": {"now": fresh_day[:10], "eligible": fresh.eligible, "gate": fresh.failed_gate,
                                        "actuality": fresh.actuality.type}}
    return out


def main() -> None:
    rows, members = load(sys.argv[1], sys.argv[2])
    out = Path(sys.argv[3])
    do_acquire = "--acquire" in sys.argv
    out.mkdir(parents=True, exist_ok=True)
    now = _dt(rows[0]["now"])
    assert now is not None
    by_id = {r["id"]: r for r in rows}
    headlines = [ClusterMember(title=r["title"] or "", source_id=r["source_name"] or "", source_name=r["source_name"] or "",
                               seen_at=_dt(r["published_at"]) or _dt(r["collected_at"]), collected_at=_dt(r["collected_at"])) for r in rows]

    def pool(window: timedelta) -> list[FeedCandidate]:
        seen: set[str] = set()
        picked = []
        for row in rows:
            if row["id"] in seen or now - _dt(row["collected_at"]) > window:
                continue
            seen.add(row["id"])
            candidate = candidate_of(row, members)
            if read_candidate(candidate).format is FeedFormat.REJECT or not kage_core(_clean_title(candidate.title, candidate.source_name.lower())):
                continue
            picked.append(candidate)
        return picked

    window = timedelta(hours=24)
    candidates = pool(window)
    nomination = nominate_viral_events(candidates, headlines=headlines, evidence={c.id: by_id[c.id].get("article_text") or "" for c in candidates},
                                       now=now)
    if len(nomination.events) < MIN_CANDIDATES:
        window = timedelta(hours=48)
        candidates = pool(window)
        nomination = nominate_viral_events(candidates, headlines=headlines,
                                           evidence={c.id: by_id[c.id].get("article_text") or "" for c in candidates}, now=now)

    order = {"STRONG": 2, "MODERATE": 1, "NONE": 0}
    ranked = sorted(nomination.events, key=lambda e: (not e.verdict.eligible, -order[e.verdict.strength], e.verdict.broad_interest != "BROAD",
                                                      e.verdict.actuality.status != "CURRENT", -len(e.outlets)))
    audited = ranked[:AUDIT_EVENTS]
    gta = next((e for e in nomination.events if any("GTA IV" in (by_id[c]["title"] or "") for c in e.candidate_ids)), None)
    if gta is not None and gta not in audited:
        audited.append(gta)

    table = []
    for event in audited:
        v = event.verdict
        rep = by_id[event.hook_candidate.id]
        body = stored_body(event, by_id)
        stored = evidence_preflight(v.hook, body, actuality=v.actuality, now=now, headlines=list(event.headlines))
        acquired = asyncio.run(acquire(event, by_id)) if do_acquire and v.eligible else None
        first = min((_dt(by_id[c]["published_at"]) or _dt(by_id[c]["collected_at"]) for c in event.candidate_ids), default=None)
        legacy = {read_candidate(candidate_of(by_id[c], members)).format.value for c in event.candidate_ids}
        table.append({
            "event": event.key, "copies_in_pool": len(event.candidate_ids), "articles_72h": event.members,
            "representative_sources": list(event.outlets[:8]), "strongest_hook_source": rep["source_name"],
            "newest_article_age_hours": round(min((now - (_dt(by_id[c]["published_at"]) or _dt(by_id[c]["collected_at"]))).total_seconds()
                                                  for c in event.candidate_ids) / 3600, 1),
            "first_seen": event.first_seen.isoformat() if event.first_seen else None, "earliest_pool_article": first.isoformat() if first else None,
            "actuality_type": v.actuality.type, "actuality_reason": v.actuality.date_source, "underlying_time": v.actuality.underlying_time,
            "disclosed_at": v.actuality.disclosed_at.isoformat() if v.actuality.disclosed_at else None,
            "newly_disclosed": list(v.actuality.newly_disclosed), "kage_relevance": ", ".join(v.kage_core) or "NO",
            "broad_interest": v.broad_interest, "inherent_strength": v.strength, "mechanisms": list(v.mechanisms),
            "momentum_band": v.momentum, "momentum_evidence": list(v.momentum_signals), "strongest_factual_hook_candidate": v.hook,
            "hook_chronology": v.details.get("hook_chronology"), "legacy_reads": sorted(legacy),
            "stored_body_chars": sum(len(b) for b in body), "evidence_preflight_stored": stored.status, "stored_checks": stored.checks,
            "evidence_preflight_acquired": acquired["status"] if acquired else None, "acquisition": acquired,
            "viral_nominated": "YES" if v.eligible else "NO", "first_failed_gate": v.failed_gate, "reason": v.reason,
            "good_kage_news": v.good_kage_news,
        })
    nominated = [t for t in table if t["viral_nominated"] == "YES"]
    ready = [t for t in nominated if (t["evidence_preflight_acquired"] or t["evidence_preflight_stored"]) == "PASS"]
    report = {
        "provider_calls": 0, "database_writes": 0, "now": rows[0]["now"], "window_hours": int(window.total_seconds() // 3600),
        "events_in_pull": len(rows), "fresh_kage_candidates": len(candidates), "distinct_events": len(nomination.events),
        "audited_events": len(table), "acquisition_dry_run": do_acquire,
        "strong_viral_nominations": nominated, "generation_ready": [t["event"] for t in ready],
        "good_kage_news_not_viral": [t for t in table if t["viral_nominated"] == "NO" and t["good_kage_news"]],
        "result": EMPTY if not nominated else nominated[0]["event"], "golden_regression": golden_regression(), "audit": table,
    }
    (out / "viral_nomination_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# KAGE viral nomination audit - {report['now'][:16]} UTC, window {report['window_hours']}h", "",
             f"events pulled (48h): {len(rows)}; fresh KAGE candidates: {len(candidates)}; distinct events: {len(nomination.events)}; "
             f"audited: {len(table)}; acquisition dry run: {do_acquire}", "",
             "| # | event | copies | outlets | newest h | actuality | broad | strength | momentum | legacy read | evidence (stored / acquired) | nominated | first failed gate |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, t in enumerate(table, 1):
        lines.append(f"| {i} | {t['event'][:80]} | {t['copies_in_pool']} | {len(t['representative_sources'])} | {t['newest_article_age_hours']} | "
                     f"{t['actuality_type']} | {t['broad_interest']} | {t['inherent_strength']} | {t['momentum_band']} | "
                     f"{'/'.join(t['legacy_reads'])} | {t['evidence_preflight_stored']} / {t['evidence_preflight_acquired'] or '-'} | "
                     f"{t['viral_nominated']} | {t['first_failed_gate'] or '-'} |")
    lines += ["", f"**Viral slot: {report['result']}**", "", f"**Generation-ready (nominated AND preflight PASS): {report['generation_ready'] or 'NONE'}**",
              "", "## Golden regression", ""]
    for name, g in report["golden_regression"].items():
        lines.append(f"- {name}: strength={g['strength']} {g['mechanisms']}; replay day {g['replay_day']}; as a fresh event {g['as_fresh_event']}")
    (out / "viral_nomination_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("now", "window_hours", "fresh_kage_candidates", "distinct_events", "audited_events", "result",
                                              "generation_ready")}
                     | {"nominated": [(t["event"], t["actuality_type"], t["momentum_band"], t["evidence_preflight_stored"],
                                       t["evidence_preflight_acquired"]) for t in nominated]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
