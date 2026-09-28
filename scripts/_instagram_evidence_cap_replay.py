"""OFFLINE REPLAY of every frozen canary evidence pool through the REAL worker.content_cycle._viral_evidence_copy (founder task 2026-09-28:
evidence copy cap 4 -> 8, ordering unchanged). The production ordering, bound and stop-at-first-PASS run as they are; only the database
session is a stub serving the frozen rows, and _feed_evidence_package builds the SAME evidence package offline (session=None - the
accepted acquisition path: resolver, safe fetch, body limits; media off), timing each copy. Each canary uses its own nominated event and
its own clock (the 24-hour window unchanged). No provider / LLM / image call, no DB write. Pages are fetched at replay time.
Usage: python scripts/_instagram_evidence_cap_replay.py <scratch dir with canary*_pool/members/rows/nomination> <out dir> [canary ...]
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
RUNS = {"canary": "viral_nominated_canary_20260926", "canary2": "viral_nominated_canary2_20260927", "canary3": "viral_nominated_canary3_20260927",
        "canary4": "viral_nominated_canary4_20260927", "canary5": "viral_nominated_canary5_20260927", "canary6": "viral_nominated_canary6_20260927",
        "canary7": "viral_nominated_canary7_20260927", "canary8": "viral_nominated_canary8_20260928"}


async def replay(name: str, scratch: Path) -> dict:
    import scripts._instagram_google_news_replay as gn
    import worker.content_cycle as cc
    from services.instagram_evidence_package import build_daily_evidence_package
    from services.instagram_feed_product import FeedFormat

    outcome = json.loads((ROOT / "artifacts/instagram_feed_product" / RUNS[name] / "outcome.json").read_text(encoding="utf-8"))
    event, now = gn.nominated_event(str(scratch / f"{name}_pool.jsonl"), str(scratch / f"{name}_members.jsonl"))
    ids = list(outcome.get("copies") or json.loads((scratch / f"{name}_nomination.json").read_text())["candidate_ids"])
    assert event is not None and sorted(event.candidate_ids) == sorted(ids), f"{name}: the frozen nomination changed"
    raw = {json.loads(line)["event"]["id"]: json.loads(line) for line in (scratch / f"{name}_rows.jsonl").read_text(encoding="utf-8").splitlines()
           if line.strip()}

    def as_row(cid: str) -> SimpleNamespace:
        ev = raw[cid]["event"]
        return SimpleNamespace(id=cid, title=ev["title"], url=ev["url"], summary=ev.get("summary"), content=ev.get("content"),
                               source_id=cid, published_at=datetime.fromisoformat(ev["published_at"]) if ev.get("published_at") else None,
                               collected_at=datetime.fromisoformat(ev["collected_at"]))

    rows = {cid: as_row(cid) for cid in ids}

    class Session:  # serves the frozen rows exactly as session.get(NewsEvent, id) would
        async def get(self, model, ident):
            return rows.get(str(ident))

    attempts: list[dict] = []

    async def package(session, event_id, row, slot_format):  # the worker's _feed_evidence_package, offline (session=None)
        src = raw[str(event_id)]["source"]
        started = time.monotonic()
        pkg = await build_daily_evidence_package(
            post_id=str(event_id), fmt=slot_format.value, title=row.title or "", url=row.url, source_type=src.get("type") or "RSS",
            source_name=src.get("name"), stored_body=row.content or row.summary, event=None, event_id=event_id, session=None,
            acquisition_enabled=True, media_mode="off")
        article = next((s for s in pkg.sources if s.source_type in ("ORIGINAL_ARTICLE", "LINKED_ARTICLE")), None)
        attempts.append({"position": len(attempts) + 1, "copy_id": str(event_id), "source": src.get("name"),
                         "age_hours": round((now - row.collected_at).total_seconds() / 3600, 1),
                         "google_news": "news.google.com" in (row.url or ""), "evidence_url": article.url if article else None,
                         "resolution_method": getattr(article, "resolution_method", None) if article else None,
                         "package_quality": pkg.quality, "seconds": round(time.monotonic() - started, 2)})
        return pkg

    real = cc._feed_evidence_package
    cc._feed_evidence_package = package
    started = time.monotonic()
    try:
        planned = str((outcome.get("planned_copy") or {}).get("id") or ids[0])
        copy_id, _row, _pkg, preflight = await cc._viral_evidence_copy(Session(), event, UUID(planned), rows[planned],
                                                                       slot_format=FeedFormat.MEME_TREND, now=now)
    finally:
        cc._feed_evidence_package = real  # never leak the stub
    elapsed = round(time.monotonic() - started, 2)
    original = [[a.get("event_id"), a["preflight"]] for a in outcome.get("evidence_attempts", [])]
    for a in attempts:  # the preflight verdict of each attempt (the last one is the returned verdict; earlier ones did not pass)
        a["preflight"] = preflight.status if a["copy_id"] == str(copy_id) else "not PASS"
    first_pass = next((a["position"] for a in attempts if a["copy_id"] == str(copy_id)), None) if preflight.status == "PASS" else None
    return {"canary": name, "clock": now.isoformat(), "eligible_copies": len(ids), "cap": cc._VIRAL_EVIDENCE_COPIES, "attempts": attempts,
            "copies_fetched": len(attempts), "first_pass_position": first_pass, "result": preflight.status,
            "result_copy": str(copy_id), "checks": {k: v for k, v in preflight.checks.items() if v != "NOT_USED"},
            "reason": preflight.reason, "elapsed_seconds": elapsed, "original_run": original,
            "original_passing": [c for c, v in original if v == "PASS"]}


def main() -> None:
    scratch, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    names = sys.argv[3:] or list(RUNS)
    results = [asyncio.run(replay(n, scratch)) for n in names]
    report = {"provider_calls": 0, "image_calls": 0, "replayed_at": datetime.now().astimezone().isoformat(), "canaries": results,
              "max_copies_attempted": max(r["copies_fetched"] for r in results),
              "max_elapsed_seconds": max(r["elapsed_seconds"] for r in results),
              "mean_copies_before_pass": round(sum(r["first_pass_position"] for r in results if r["first_pass_position"])
                                               / max(1, sum(1 for r in results if r["first_pass_position"])), 2)}
    (out / "evidence_cap_replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for r in results:
        orig = [c[:8] for c in r["original_passing"]]
        print(f"== {r['canary']} clock {r['clock'][:16]} eligible={r['eligible_copies']} fetched={r['copies_fetched']} "
              f"first PASS at {r['first_pass_position']} -> {r['result']} ({r['result_copy'][:8]}) {r['checks']} | {r['elapsed_seconds']}s | original PASS {orig}")
        for a in r["attempts"]:
            print(f"    {a['position']} {a['copy_id'][:8]} {a['source'][:24]:<24} {a['age_hours']:>5}h {'GN' if a['google_news'] else 'direct':<6} "
                  f"-> {(a['evidence_url'] or '-')[:55]:<55} {a['seconds']}s {a['preflight']}")
    print("max copies attempted", report["max_copies_attempted"], "| max elapsed", report["max_elapsed_seconds"], "s | mean copies before PASS",
          report["mean_copies_before_pass"])


if __name__ == "__main__":
    main()
