"""Golden check of the TEMPORAL-DIVERSITY evidence order on every frozen canary pool: the first 4 copies under the new order through the
accepted acquisition path + unchanged preflight at each canary's own clock (live fetch now; no LLM / image call, no DB write).
Usage: python golden_temporal.py canary canary2 ..."""
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
RUNS = {"canary": "viral_nominated_canary_20260926", "canary2": "viral_nominated_canary2_20260927", "canary3": "viral_nominated_canary3_20260927",
        "canary4": "viral_nominated_canary4_20260927", "canary5": "viral_nominated_canary5_20260927", "canary6": "viral_nominated_canary6_20260927",
        "canary7": "viral_nominated_canary7_20260927", "canary8": "viral_nominated_canary8_20260928"}


async def one(name: str) -> dict:
    import scripts._instagram_google_news_replay as gn
    import worker.content_cycle as cc

    outcome = json.loads((WT / "artifacts/instagram_feed_product" / RUNS[name] / "outcome.json").read_text(encoding="utf-8"))
    event, now = gn.nominated_event(str(M / f"{name}_pool.jsonl"), str(M / f"{name}_members.jsonl"))
    ids = list(outcome.get("copies") or json.loads((M / f"{name}_nomination.json").read_text())["candidate_ids"])
    assert event is not None and sorted(event.candidate_ids) == sorted(ids), f"{name}: nomination changed"
    raw = {json.loads(line)["event"]["id"]: json.loads(line) for line in (M / f"{name}_rows.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}
    rows = {UUID(c): SimpleNamespace(url=raw[c]["event"]["url"], collected_at=datetime.fromisoformat(raw[c]["event"]["collected_at"])) for c in ids}
    planned = UUID((outcome.get("planned_copy") or {}).get("id") or ids[0])
    new = cc._order_evidence_copies(planned, rows)
    known = {a["event_id"]: a["preflight"] for a in outcome.get("evidence_attempts", []) if a.get("event_id")}
    attempts = []
    for c in new[: cc._VIRAL_EVIDENCE_COPIES]:
        if known.get(str(c)) in ("FAIL", "PENDING") and str(c) != str(planned) and False:
            pass
        res = await gn.replay_copy(raw[str(c)], event, now)
        attempts.append({"copy_id": str(c), "age_hours": round((now - rows[c].collected_at).total_seconds() / 3600, 1),
                         "result_in_original_run": known.get(str(c)), **res})
        if res["preflight"] == "PASS":
            break
    return {"canary": name, "clock": now.isoformat(), "new_first4": [str(c) for c in new[:4]], "attempts": attempts,
            "passing_copy": next((a["copy_id"] for a in attempts if a["preflight"] == "PASS"), None),
            "original_passing": [c for c, v in known.items() if v == "PASS"]}


async def main() -> None:
    results = [await one(n) for n in sys.argv[1:]]
    (M / "golden_temporal.json").write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for r in results:
        print(f"== {r['canary']} clock {r['clock'][:16]} original PASS {[c[:8] for c in r['original_passing']]} -> new-order PASS {r['passing_copy'] and r['passing_copy'][:8]}")
        for a in r["attempts"]:
            print(f"   {a['copy_id'][:8]} {a['age_hours']:>5}h orig={a['result_in_original_run'] or '-':<8} {a['resolution_status'] or '-'} -> "
                  f"{a['publisher_domain'] or (a['original_url'] or '')[8:40]} acq={a['acquisition_status']} err={a['acquisition_error']} body={a['body_chars']} "
                  f"PREFLIGHT={a['preflight']} {a['checks']}")


asyncio.run(main())
