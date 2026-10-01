"""Offline selection snapshot for the final natural acceptance: the canary's own section 1 (nomination from the fresh KAGE pool), with no
provider call and no write. Usage: python scripts/_instagram_final_selection_snapshot.py <pool.jsonl> <members.jsonl> <out.json>"""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts._instagram_viral_story_audit as audit  # noqa: E402
from services.instagram_feed_product import DAILY_SHORTLIST_PER_FORMAT, FeedFormat, _clean_title, kage_core, read_candidate  # noqa: E402
from services.instagram_viral_nomination import nominate_viral_events, nominated_reads  # noqa: E402
from services.instagram_viral_story_gate import ClusterMember  # noqa: E402


def main() -> None:
    pool_path, members_path, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    rows, members = audit.load(pool_path, members_path)
    now = audit._dt(rows[0]["now"])
    by_id = {r["id"]: r for r in rows}
    headlines = [ClusterMember(title=r["title"] or "", source_id=r["source_name"] or "", source_name=r["source_name"] or "",
                               seen_at=audit._dt(r["published_at"]) or audit._dt(r["collected_at"]), collected_at=audit._dt(r["collected_at"]))
                 for r in rows]
    seen: set[str] = set()
    current, candidates = 0, []
    for r in rows:
        if r["id"] in seen or now - audit._dt(r["collected_at"]) > timedelta(hours=24):
            continue
        seen.add(r["id"])
        current += 1
        c = audit.candidate_of(r, members)
        if read_candidate(c).format is not FeedFormat.REJECT and kage_core(_clean_title(c.title, c.source_name.lower())):
            candidates.append(c)
    nomination = nominate_viral_events(candidates, headlines=headlines,
                                       evidence={c.id: by_id[c.id].get("article_text") or "" for c in candidates}, now=now)
    shortlist = nominated_reads(nomination, 8)
    snapshot = {
        "now": rows[0]["now"], "events_48h": len(rows), "events_24h": current, "kage_relevant": len(candidates),
        "distinct_events": len(nomination.events), "daily_eligible": len(nomination.eligible),
        "worker_shortlist_size": DAILY_SHORTLIST_PER_FORMAT,
        "eligible_events": [e.key for e in nomination.eligible],
        "shortlist": [
            {"rank": i + 1, "event": read.viral_event.key, "planned_copy": {"id": p.id, "source": p.source_name, "title": p.title},
             "copies": list(read.viral_event.candidate_ids), "outlets": list(read.viral_event.outlets),
             "mechanisms": list(read.viral_event.verdict.mechanisms), "strength": read.viral_event.verdict.strength,
             "broad": read.viral_event.verdict.broad_interest, "momentum": read.viral_event.verdict.momentum,
             "actuality": read.viral_event.verdict.actuality.type, "hook": read.viral_event.verdict.hook, "reason": read.viral_event.verdict.reason}
            for i, (p, read) in enumerate(shortlist)
        ],
    }
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in snapshot.items() if k not in ("shortlist", "eligible_events")}, ensure_ascii=False))
    for s in snapshot["shortlist"]:
        print(s["rank"], s["event"], "|", s["planned_copy"]["source"], "|", s["mechanisms"], s["strength"], s["broad"], s["momentum"], "| copies", len(s["copies"]))


if __name__ == "__main__":
    main()
