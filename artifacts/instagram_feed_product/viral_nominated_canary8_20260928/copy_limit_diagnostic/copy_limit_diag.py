"""READ-ONLY diagnostic (founder task 2026-09-28): canary 8's three untried in-window copies (positions 5-7 under the frozen ordering)
through the accepted replay path of scripts/_instagram_google_news_replay.py - acquire_article (accepted resolver + safe fetch) ->
build_daily_evidence_package (offline, session=None, media off) -> viral_evidence_preflight against the SAME nominated event and the SAME
canary-8 clock (24h window unchanged). No LLM / image call, no DB write, no code change."""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

WT = Path(r"C:\Users\Theodor\ai-newsroom\.worktrees\instagram-b61")
sys.path.insert(0, str(WT))
M = Path(__file__).resolve().parent
POSITIONS = {"10856ebf": 5, "d08eaab6": 6, "a6b32ec3": 7}


async def main() -> None:
    import scripts._instagram_google_news_replay as gn

    started = datetime.now(timezone.utc).isoformat()
    event, now = gn.nominated_event(str(M / "canary8_pool.jsonl"), str(M / "canary8_members.jsonl"))
    rows = [json.loads(line) for line in (M / "canary8_rows.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    targets = sorted((r for r in rows if r["event"]["id"][:8] in POSITIONS), key=lambda r: POSITIONS[r["event"]["id"][:8]])
    results = []
    for row in targets:
        age_h = (now - datetime.fromisoformat(row["event"]["collected_at"])).total_seconds() / 3600
        res = await gn.replay_copy(row, event, now)
        results.append({"position": POSITIONS[row["event"]["id"][:8]], "event_id": row["event"]["id"], "age_hours_at_canary8": round(age_h, 1), **res})
    report = {"diagnostic_started_utc": started, "canary8_clock": now.isoformat(), "event": event.key if event else None,
              "provider_calls": 0, "image_calls": 0, "copies": results}
    (M / "copy_limit_diag.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("started", started, "| canary-8 clock", now.isoformat(), "| event", (event.key if event else None)[:70])
    for r in results:
        print(f"pos {r['position']} {r['event_id'][:8]} age={r['age_hours_at_canary8']}h | res={r['resolution_status']} {r['resolution_method']} -> "
              f"{r['resolved_url']} | acq={r['acquisition_status']} err={r['acquisition_error']} chars={r['extracted_chars']} | body={r['body_chars']} "
              f"quality={r['package_quality']} | PREFLIGHT={r['preflight']} {r['checks']} | {r['preflight_reason']}")


asyncio.run(main())
