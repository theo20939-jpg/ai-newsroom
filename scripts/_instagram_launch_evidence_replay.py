"""OFFLINE replay of the final natural canary's launch attempts (founder task 2026-09-29: launch story evidence contract). No provider /
LLM / image call, no database, no network.

Inputs (all saved by the canary, commit 36b25f9):
  - the canary's read-only production pool + story members (the SAME nomination: the saved events' own hook, actuality and headlines);
  - artifacts/instagram_launch_evidence/saved_sources.jsonl: each attempted copy's stored body and its persisted acquisition
    (raw_extracted_text) exactly as the canary's evidence step read them.
For each attempted copy the package is rebuilt with the worker's own inputs (stored-body paragraphs + the ORIGINAL_ARTICLE raw text ->
assemble_package, premise = the copy's title, format = the viral slot's) and checked with viral_evidence_preflight at the canary clock.
Usage: python scripts/_instagram_launch_evidence_replay.py <pool.jsonl> <members.jsonl> <out json>
"""
from __future__ import annotations

import json
import pickle
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "artifacts/instagram_launch_evidence/saved_sources.jsonl"
ATTEMPTS = {  # the canary's attempted copies, in the worker's order (outcome.json of attempt_1 / attempt_2)
    "attempt_1": ["da549220-9650-4e69-9b3d-ba4dd856db0e"],
    "attempt_2": ["c728f8d6-248a-4ea0-83bf-20a9520d4007", "10906658-9628-4699-ae52-2f93d0c11f4c"],
    "attempt_3": ["01c007ff-f291-4592-9cd2-e08ddb7b410a"],  # the incident story that PASSed live: the regression anchor
}


def nominated_events(pool: str, members: str, cache: Path | None = None):
    """The canary's own nomination over the saved pool (optionally cached: the nomination takes minutes)."""
    if cache is not None and cache.exists():
        return pickle.loads(cache.read_bytes())
    import _instagram_viral_story_audit as a
    from services.instagram_feed_product import FeedFormat, _clean_title, kage_core, read_candidate
    from services.instagram_viral_nomination import nominate_viral_events
    from services.instagram_viral_story_gate import ClusterMember

    rows, mem = a.load(pool, members)
    now = a._dt(rows[0]["now"])
    by = {r["id"]: r for r in rows}
    heads = [ClusterMember(title=r["title"] or "", source_id=r["source_name"], source_name=r["source_name"],
                           seen_at=a._dt(r["published_at"]) or a._dt(r["collected_at"]), collected_at=a._dt(r["collected_at"])) for r in rows]
    seen, cands = set(), []
    for r in rows:
        if r["id"] in seen or now - a._dt(r["collected_at"]) > timedelta(hours=24):
            continue
        seen.add(r["id"])
        c = a.candidate_of(r, mem)
        if read_candidate(c).format is not FeedFormat.REJECT and kage_core(_clean_title(c.title, c.source_name.lower())):
            cands.append(c)
    n = nominate_viral_events(cands, headlines=heads, evidence={c.id: by[c.id].get("article_text") or "" for c in cands}, now=now)
    wanted = {cid for ids in ATTEMPTS.values() for cid in ids}
    events = {cid: e for e in n.eligible for cid in e.candidate_ids if cid in wanted}
    result = (now, events)
    if cache is not None:
        cache.write_bytes(pickle.dumps(result))
    return result


def replay_copy(saved: dict, event, now: datetime) -> dict:
    from services.instagram_evidence_package import (
        NOT_AVAILABLE,
        ORIGINAL_ARTICLE,
        STORED_BODY,
        EvidenceSource,
        SourceMedia,
        assemble_package,
        recap_paragraphs,
    )
    from services.instagram_feed_product import FeedFormat
    from services.instagram_viral_nomination import viral_evidence_preflight

    stored = saved["content"] or saved["summary"]
    sources = [EvidenceSource(url=None, source_type=STORED_BODY, text=p) for p in recap_paragraphs(stored)] if stored else []
    sources.append(EvidenceSource(url=saved["canonical_url"], source_type=ORIGINAL_ARTICLE, text=saved["raw"] or "", status=saved["status"]))
    package = assemble_package(post_id=saved["event_id"], fmt=FeedFormat.MEME_TREND.value, premise=saved["title"] or "", sources=sources,
                               media=SourceMedia(status=NOT_AVAILABLE, reason="offline replay"))
    body = package.preflight_lines()
    published = datetime.fromisoformat(saved["published_at"]) if saved.get("published_at") else None
    pf = viral_evidence_preflight(event, title=saved["title"] or "", body_lines=body, published_at=published, now=now)
    return {"event_id": saved["event_id"], "source": saved["source_name"], "title": saved["title"], "hook": event.verdict.hook,
            "actuality": event.verdict.actuality.type, "package_quality": package.quality, "package_why": package.why,
            "facts": [i.exact_text for i in package.facts], "limitations": [i.exact_text for i in package.limitations],
            "dateline": getattr(package, "dateline", None),
            "preflight": pf.status, "checks": pf.checks, "reason": pf.reason}


def main() -> None:
    pool, members, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    cache = Path(sys.argv[4]) if len(sys.argv) > 4 else None
    now, events = nominated_events(pool, members, cache)
    saved = {d["event_id"]: d for d in (json.loads(line) for line in SOURCES.read_text(encoding="utf-8").splitlines() if line.strip())}
    report = {"clock": now.isoformat(), "provider_calls": 0, "image_calls": 0, "attempts": {}}
    for name, ids in ATTEMPTS.items():
        copies = [replay_copy(saved[cid], events[cid], now) for cid in ids]
        report["attempts"][name] = {"event": events[ids[0]].key, "copies": copies,
                                    "result": next((c["preflight"] for c in copies if c["preflight"] == "PASS"), copies[-1]["preflight"])}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, a in report["attempts"].items():
        print(f"== {name}: {a['event'][:90]} -> {a['result']}")
        for c in a["copies"]:
            print(f"   {c['source']}: {c['preflight']} {c['checks']} | {c['reason']}")
            for f in c["facts"]:
                print(f"      FACT {f[:150]}")


if __name__ == "__main__":
    main()
