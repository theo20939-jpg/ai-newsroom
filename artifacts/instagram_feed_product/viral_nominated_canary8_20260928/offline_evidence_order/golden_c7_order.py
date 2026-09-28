"""Golden-event check for the evidence-order change: canary 7's frozen pool at its own clock, the first 4 copies under the NEW order through
the accepted acquisition path + unchanged preflight (live fetch now; no LLM / image call, no DB write)."""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

WT = Path(r"C:\Users\Theodor\ai-newsroom\.worktrees\instagram-b61")
sys.path.insert(0, str(WT))
M = Path(__file__).resolve().parent


async def main() -> None:
    import scripts._instagram_evidence_order_replay as r
    import scripts._instagram_google_news_replay as gn
    import worker.content_cycle as cc

    outcome = json.loads((WT / "artifacts/instagram_feed_product/viral_nominated_canary7_20260927/outcome.json").read_text(encoding="utf-8"))
    ids = json.loads((M / "canary7_nomination.json").read_text())["candidate_ids"]
    event, now = gn.nominated_event(str(M / "canary7_pool.jsonl"), str(M / "canary7_members.jsonl"))
    assert event is not None and list(event.candidate_ids) == ids
    raw = {json.loads(line)["event"]["id"]: json.loads(line) for line in (M / "canary7_rows.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}
    rows = {UUID(c): SimpleNamespace(url=raw[c]["event"]["url"], collected_at=datetime.fromisoformat(raw[c]["event"]["collected_at"])) for c in ids}
    planned = UUID(outcome["planned_copy"]["id"])
    new = cc._order_evidence_copies(planned, rows, ids)
    old = r.old_order(planned, rows)
    attempts = []
    for c in new[: cc._VIRAL_EVIDENCE_COPIES]:
        res = await gn.replay_copy(raw[str(c)], event, now)
        attempts.append({"copy_id": str(c), **res})
        if res["preflight"] == "PASS":
            break
    report = {"clock": now.isoformat(), "old_order": [str(c) for c in old], "new_order": [str(c) for c in new], "attempts_new_order": attempts,
              "passing_copy": next((a["copy_id"] for a in attempts if a["preflight"] == "PASS"), None), "provider_calls": 0, "image_calls": 0}
    (M / "golden_c7_order.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("clock", now.isoformat())
    for a in attempts:
        print(f"  {a['copy_id'][:8]} {a['resolution_status'] or '-'} -> {a['publisher_domain'] or '-'} acq={a['acquisition_status']} err={a['acquisition_error']} "
              f"body={a['body_chars']} PREFLIGHT={a['preflight']} {a['checks']} | {a['preflight_reason']}")
    print("passing copy:", report["passing_copy"])


asyncio.run(main())
