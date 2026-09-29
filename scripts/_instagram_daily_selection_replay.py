"""OFFLINE replay of the DAILY story selection over saved canary pools (founder task 2026-09-29: daily selection product). No provider /
LLM / image call, no database write.

For every saved pool (read-only production snapshots taken for canaries 1-10) this runs the real nomination
(services.instagram_viral_nomination.nominate_viral_events - the daily story slot's selection) and reports:
  - the winner and the eligible field ranked (strength band, the story's own points, momentum, visual);
  - a DAILY SEQUENCE: the winner is published and excluded (as the planner excludes published events), the next winner is taken, x5 -
    what the feed would realistically show over the following days from THIS pool alone (no quota, no forced category);
  - the verdict of each founder-named story.
Usage: python scripts/_instagram_daily_selection_replay.py <scratch dir with canary*_pool/members.jsonl> <out json>
"""
from __future__ import annotations

import json
import re
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

POOLS = ["canary", "canary2", "canary3", "canary4", "canary5", "canary6", "canary7", "canary8", "canary9", "canary10"]
NAMED = {
    "claude_48000_files": r"48\s*0{3}|снес разрабу", "blackjack_collusion": r"blackjack|блэкджек",
    "microsoft_17_trillion": r"17 trillion|Teenager hacks", "gemini_gems_skills": r"Gems with skills",
    "robot_spider_welding": r"робота-паука|robot[- ]spider", "amodei_snl": r"SNL", "un_bruteforce": r"bruteforce",
    "canary10_procedural": r"called to appear at Australian AI probe|will not appear at Senate inquiry",
    "enigma_astra": r"cracks 1941 Enigma-coded message in two days$",
}


def _family(v) -> str:
    m = set(v.mechanisms)
    if m & {"ai_launch"}:
        return "AI launch"
    if m & {"device_launch", "device_novelty"}:
        return "gadget / device"
    if m & {"unexpected_ai_behaviour", "real_failure", "absurd_measurable_outcome", "bizarre_event", "unlikely_pairing",
            "measurable_contradiction", "pop_culture_crossover", "ai_feat"}:
        return "viral / meme"
    if m & {"security_surprise", "consumer_consequence", "controversy", "human_vs_tech"}:
        return "serious incident"
    return "-"


def replay(name: str, scratch: Path) -> dict:
    import _instagram_viral_story_audit as a
    from services.instagram_feed_product import FeedFormat, _clean_title, kage_core, read_candidate
    from services.instagram_viral_nomination import nominate_viral_events
    from services.instagram_viral_story_gate import ClusterMember

    rows, members = a.load(str(scratch / f"{name}_pool.jsonl"), str(scratch / f"{name}_members.jsonl"))
    now = a._dt(rows[0]["now"])
    by = {r["id"]: r for r in rows}
    heads = [ClusterMember(title=r["title"] or "", source_id=r["source_name"], source_name=r["source_name"],
                           seen_at=a._dt(r["published_at"]) or a._dt(r["collected_at"]), collected_at=a._dt(r["collected_at"])) for r in rows]
    seen, allc, cands = set(), [], []
    for r in rows:
        if r["id"] in seen or now - a._dt(r["collected_at"]) > timedelta(hours=24):
            continue
        seen.add(r["id"])
        c = a.candidate_of(r, members)
        allc.append(c)
        if read_candidate(c).format is not FeedFormat.REJECT and kage_core(_clean_title(c.title, c.source_name.lower())):
            cands.append(c)
    n = nominate_viral_events(cands, headlines=heads, evidence={c.id: by[c.id].get("article_text") or "" for c in cands}, now=now)
    row = lambda e: {"event": e.key, "family": _family(e.verdict), "points": e.verdict.points, "strength": e.verdict.strength,  # noqa: E731
                     "mechanisms": list(e.verdict.mechanisms), "momentum": e.verdict.momentum, "outlets": len(e.outlets),
                     "broad_reason": e.verdict.broad_reason[:100], "hook": e.verdict.hook[:200]}
    eligible = [row(e) for e in n.eligible]
    # the daily sequence: nomination order IS the ranking; publishing the winner removes its event, the next eligible one follows
    sequence = [r["event"] for r in eligible[:5]]
    named = {}
    for key, pat in NAMED.items():
        c = next((c for c in allc if re.search(pat, c.title or "", re.I)), None)
        if c is None:
            continue
        ev = next((e for e in n.events if c.id in e.candidate_ids), None)
        v = ev.verdict if ev else None
        named[key] = {"title": c.title, "feed_read": read_candidate(c).format.value,
                      "verdict": None if v is None else {"eligible": v.eligible, "failed_gate": v.failed_gate, "strength": v.strength,
                                                       "points": v.points, "mechanisms": list(v.mechanisms), "broad": v.broad_interest,
                                                       "momentum": v.momentum, "actuality": v.actuality.status,
                                                       "rank_among_eligible": next((i for i, e in enumerate(n.eligible, 1) if e is ev), None),
                                                       "reason": v.reason[:220]}}
    return {"pool": name, "now": rows[0]["now"], "events": len(n.events), "eligible_count": len(eligible),
            "winner": n.best.key if n.best else None, "eligible": eligible, "daily_sequence": sequence, "named": named}


def main() -> None:
    """Optional pool names after the two paths replay only those pools and MERGE them into an existing report (one pool per process
    keeps memory low - a full run once hit the machine's memory limit)."""
    scratch, out = Path(sys.argv[1]), Path(sys.argv[2])
    names = sys.argv[3:] or POOLS
    report = json.loads(out.read_text(encoding="utf-8")) if sys.argv[3:] and out.exists() else {}
    report.update({name: replay(name, scratch) for name in names})
    report = {name: report[name] for name in POOLS if name in report}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, r in report.items():
        print(f"== {name}: eligible {r['eligible_count']} | winner: {r['winner']!r:.100}")
        for i, e in enumerate(r["eligible"][:6], 1):
            print(f"   {i}. [{e['family']}] p={e['points']} mom={e['momentum']} | {e['event'][:95]}")


if __name__ == "__main__":
    main()
