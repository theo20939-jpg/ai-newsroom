"""OFFLINE REPLAY of canary 8's evidence-copy ORDER (founder task 2026-09-28): the frozen canary-8 pool at its original clock
(2026-09-27 21:27:34 UTC) and its frozen 24-hour eligibility set, the OLD order (planned, direct publishers, Google News in nomination
order) vs the NEW order (worker.content_cycle._order_evidence_copies: Google News newest first), then the existing acquisition path and
the unchanged evidence preflight on the first _VIRAL_EVIDENCE_COPIES copies of the NEW order. No provider / LLM / image call, no DB write.

Acquisition is the accepted live path (resolver + safe fetch), so page contents are fetched at replay time; eligibility, the nominated
event and the preflight clock are canary 8's. Writes copy_order_fixture.json (ids, urls, collected_at, nomination order - the test input).
Usage: python scripts/_instagram_evidence_order_replay.py <canary8 pool.jsonl> <canary8 members.jsonl> <canary8 rows.jsonl> <out dir>
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
OUTCOME = ROOT / "artifacts/instagram_feed_product/viral_nominated_canary8_20260928/outcome.json"


def old_order(event_id: UUID, rows: dict) -> list[UUID]:
    """The ordering exactly as it ran in canary 8 (before 2026-09-28): planned, then a stable sort that puts shells last."""
    from services.text_normalization import is_google_news_redirect_host

    return [event_id, *sorted((c for c in rows if c != event_id), key=lambda c: is_google_news_redirect_host(rows[c].url or ""))]


async def main_async(pool: str, members: str, rows_path: str, out: Path) -> dict:
    import scripts._instagram_google_news_replay as gn
    import worker.content_cycle as cc
    from services.text_normalization import is_google_news_redirect_host

    outcome = json.loads(OUTCOME.read_text(encoding="utf-8"))
    candidate_ids = list(outcome["copies"])  # the nomination's candidate order the canary-8 run used
    event, now = gn.nominated_event(pool, members)
    assert event is not None and list(event.candidate_ids) == candidate_ids, "the frozen nomination changed"
    raw = {json.loads(line)["event"]["id"]: json.loads(line) for line in Path(rows_path).read_text(encoding="utf-8").splitlines() if line.strip()}
    rows = {UUID(cid): SimpleNamespace(url=raw[cid]["event"]["url"], collected_at=datetime.fromisoformat(raw[cid]["event"]["collected_at"]))
            for cid in candidate_ids}
    planned = UUID(outcome["planned_copy"]["id"])
    old, new = old_order(planned, rows), cc._order_evidence_copies(planned, rows, candidate_ids)

    def describe(order: list[UUID], *, algorithm: str) -> list[dict]:
        return [{"position": i, "copy_id": str(c), "source_type": "google_news" if is_google_news_redirect_host(rows[c].url) else "direct",
                 "collected_at": rows[c].collected_at.isoformat(), "age_hours": round((now - rows[c].collected_at).total_seconds() / 3600, 1),
                 "publisher": raw[str(c)]["source"].get("name"), "host": urlsplit(rows[c].url).hostname,
                 "ordering_key": "planned" if c == planned else (
                     f"direct, nomination #{candidate_ids.index(str(c))}" if not is_google_news_redirect_host(rows[c].url)
                     else f"google_news, nomination #{candidate_ids.index(str(c))} (stable)" if algorithm == "old"
                     else f"google_news, collected_at DESC {rows[c].collected_at.isoformat()}, nomination #{candidate_ids.index(str(c))}")}
                for i, c in enumerate(order, 1)]

    fixture = {"clock": now.isoformat(), "planned": str(planned), "candidate_ids": candidate_ids,
               "copies": {str(c): {"url": rows[c].url, "collected_at": rows[c].collected_at.isoformat()} for c in rows}}
    (out / "copy_order_fixture.json").write_text(json.dumps(fixture, indent=1), encoding="utf-8")
    attempts = []
    for c in new[:cc._VIRAL_EVIDENCE_COPIES]:
        result = await gn.replay_copy(raw[str(c)], event, now)
        attempts.append({"copy_id": str(c), **result})
        if result["preflight"] == "PASS":
            break  # the worker stops at the first passing copy
    return {"provider_calls": 0, "image_calls": 0, "clock": now.isoformat(), "event": event.key, "max_copies": cc._VIRAL_EVIDENCE_COPIES,
            "old_order": describe(old, algorithm="old"), "new_order": describe(new, algorithm="new"), "attempts_new_order": attempts,
            "passing_copy": next((a["copy_id"] for a in attempts if a["preflight"] == "PASS"), None)}


def main() -> None:
    out = Path(sys.argv[4])
    out.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(main_async(sys.argv[1], sys.argv[2], sys.argv[3], out))
    (out / "evidence_order_replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for name in ("old_order", "new_order"):
        print(name)
        for p in report[name]:
            print(f"  {p['position']} {p['copy_id'][:8]} {p['source_type']:<11} {p['age_hours']:>5}h {p['host']:<22} {p['ordering_key']}")
    print("attempts (new order, max", report["max_copies"], ")")
    for a in report["attempts_new_order"]:
        print(f"  {a['copy_id'][:8]} {a['resolution_status'] or '-'} -> {a['publisher_domain'] or '-'} acq={a['acquisition_status']} "
              f"err={a['acquisition_error']} body={a['body_chars']} PREFLIGHT={a['preflight']} {a['checks']} | {a['preflight_reason']}")
    print("passing copy:", report["passing_copy"])


if __name__ == "__main__":
    main()
