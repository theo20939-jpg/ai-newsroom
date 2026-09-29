"""OFFLINE daily-selection replay for the point-release false positive (founder task 2026-09-29). No provider / LLM / image call, no database.

For ONE saved read-only production pool (canary 1-10 or the final natural canary), the daily story slot's own nomination
(services.instagram_viral_nomination.nominate_viral_events, exactly as scripts/_instagram_daily_selection_replay.py runs it) is recorded:
every eligible event in rank order, and the full verdict of every event carrying a software-release headline (so a before / after run
shows exactly which events changed and why).
The code under test is the tree at KAGE_CODE_ROOT (default: this repository) - the BEFORE run points it at a worktree of the base commit.
Usage: python scripts/_instagram_point_release_replay.py <scratch dir with <name>_pool/members.jsonl> <name> <out json>
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import timedelta
from pathlib import Path

CODE = Path(os.environ.get("KAGE_CODE_ROOT", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(CODE))
sys.path.insert(0, str(CODE / "scripts"))

# which verdicts to print in full: headlines about an OS / firmware / app release, any vendor (reporting filter only - never a rule)
SOFTWARE_HEADLINE = re.compile(r"\b(?:ios|ipados|macos|watchos|visionos|android|windows|one ui|hyperos|firmware|прошивк\w*|update|обновлени\w*|"
                               r"patch\w*|патч\w*)\b|\b\d+\.\d+\.\d+\b", re.IGNORECASE)


def main() -> None:
    scratch, name, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    import _instagram_viral_story_audit as a
    from services.instagram_feed_product import FeedFormat, _clean_title, kage_core, read_candidate
    from services.instagram_viral_nomination import nominate_viral_events
    from services.instagram_viral_story_gate import ClusterMember

    rows, members = a.load(str(scratch / f"{name}_pool.jsonl"), str(scratch / f"{name}_members.jsonl"))
    now = a._dt(rows[0]["now"])
    by = {r["id"]: r for r in rows}
    heads = [ClusterMember(title=r["title"] or "", source_id=r["source_name"], source_name=r["source_name"],
                           seen_at=a._dt(r["published_at"]) or a._dt(r["collected_at"]), collected_at=a._dt(r["collected_at"])) for r in rows]
    seen, cands = set(), []
    for r in rows:
        if r["id"] in seen or now - a._dt(r["collected_at"]) > timedelta(hours=24):
            continue
        seen.add(r["id"])
        c = a.candidate_of(r, members)
        if read_candidate(c).format is not FeedFormat.REJECT and kage_core(_clean_title(c.title, c.source_name.lower())):
            cands.append(c)
    n = nominate_viral_events(cands, headlines=heads, evidence={c.id: by[c.id].get("article_text") or "" for c in cands}, now=now)

    def verdict(e) -> dict:
        v = e.verdict
        return {"event": e.key, "copies": list(e.candidate_ids), "eligible": v.eligible, "failed_gate": v.failed_gate, "strength": v.strength,
                "points": v.points, "mechanisms": list(v.mechanisms), "broad": v.broad_interest, "broad_reason": v.broad_reason,
                "momentum": v.momentum, "actuality": v.actuality.status, "hook": v.hook[:300], "reason": v.reason[:400]}

    software = [verdict(e) for e in n.events
                if any(SOFTWARE_HEADLINE.search(by[cid]["title"] or "") for cid in e.candidate_ids if cid in by)]
    report = {"pool": name, "now": rows[0]["now"], "code_root": str(CODE), "candidates": len(cands), "events": len(n.events),
              "eligible": [{"rank": i, **verdict(e)} for i, e in enumerate(n.eligible, 1)], "winner": n.best.key if n.best else None,
              "software_release_events": software, "provider_calls": 0, "image_calls": 0}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"== {name}: {len(n.eligible)} eligible | winner: {report['winner']!r:.90}")
    for e in report["eligible"]:
        print(f"   {e['rank']:2}. p={e['points']} {e['mechanisms']} | {e['event'][:90]}")


if __name__ == "__main__":
    main()
