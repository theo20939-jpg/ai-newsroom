"""KAGE Instagram EVIDENCE READINESS (zero-cost): the downstream evidence package for every post of the frozen 5-11 Aug 2026 week.

Selection is frozen and only READ: the daily posts are the enriched b9733c2 picks (feed_replay json) minus the Tuesday gym copy the frozen
cross-language dedup blocks; the weekly recap is the accepted v2 editor result. For each daily post the production builder
(services/instagram_evidence_package.py::build_daily_evidence_package) runs with NO session - plain web fetches through the existing
acquire_article() and image discovery through the existing run_shadow_discovery(); nothing is persisted. Recap bodies (event bodies and
already-acquired article text of the cited stories) are read from the local dev DB in read-only transactions, then sanitized.
No provider call of any kind.

Usage: python scripts/_instagram_evidence_readiness.py <window.json> <identity.json> <feed_replay.json> <weekly_editor_live.json> <out.json>
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.instagram_evidence_package import (  # noqa: E402
    build_daily_evidence_package,
    build_recap_story_package,
    clean_body,
)

DEDUP_BLOCKED = {("2026-08-11", "AI agent hacks gym to get its owner spot in pilates class")}


def _package_json(package, extra: dict) -> dict:
    return {**extra, "format": package.format, "premise": package.premise, "quality": package.quality, "why": package.why,
            "sources": [{"url": s.url, "type": s.source_type, "status": s.status, "chars": len(s.text)} for s in package.sources],
            "steps": [vars(i) for i in package.steps], "facts": [vars(i) for i in package.facts],
            "limitations": [vars(i) for i in package.limitations], "media": vars(package.media),
            "excluded_bodies": list(package.excluded_bodies), "director_evidence_lines": len(package.director_evidence())}


async def _recap_bodies(event_ids: list[str]) -> list[tuple[str, str]]:
    """Read-only: every cited event's stored body and its trusted acquired article text (cleaned on the fly)."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from core.config import settings

    engine = create_async_engine(settings.database_url, connect_args={"server_settings": {"default_transaction_read_only": "on"}})
    out: list[tuple[str, str]] = []
    async with engine.connect() as c:
        rows = (await c.execute(text("""select e.id::text, e.title, coalesce(e.content, e.summary, ''), coalesce(a.raw_extracted_text, ''),
                coalesce(a.acquisition_status, '') from news_events e left join news_event_article_acquisitions a on a.news_event_id = e.id
                where e.id = any(cast(:ids as uuid[]))"""), {"ids": event_ids})).all()
    await engine.dispose()
    for event_id, title, body, raw, status in rows:
        if body and len(body) > 40:
            out.append((f"event:{event_id}:body", body))
        if raw and status in ("FULL_TEXT", "PARTIAL_TEXT"):
            out.append((f"event:{event_id}:article", clean_body(raw, title)))
    return out


async def main() -> None:
    window, identity, replay, editor, out = (Path(a) for a in sys.argv[1:6])
    main_env = ROOT.parent.parent / ".env" if (ROOT.parent.parent / ".env").exists() else Path(r"C:/Users/Theodor/ai-newsroom/.env")
    for line in main_env.read_text(encoding="utf-8").splitlines():  # DB credentials only, never printed
        if line.startswith("POSTGRES_") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    events = {e["id"]: e for e in json.loads(window.read_text(encoding="utf-8"))["events"]}
    by_title = {}
    for e in events.values():
        by_title.setdefault((e["title"], e["source_name"]), e)
    report: dict = {"daily": [], "recap": [], "provider_calls": 0}
    for day in json.loads(replay.read_text(encoding="utf-8"))["days"]:
        for slot, post in enumerate(day["enriched"]["posts"], 1):
            e = by_title[(post["title"], post["source"])]
            if (day["day"], post["title"]) in DEDUP_BLOCKED:
                report["daily"].append({"day": day["day"], "slot": slot, "title": post["title"], "format": post["format"],
                                        "quality": "DEDUP_BLOCKED", "why": "frozen cross-language dedup: same premise as Monday's post"})
                continue
            kwargs = dict(post_id=e["id"], fmt=post["format"], title=post["title"], url=e.get("url"), source_type=e.get("source_type") or "RSS",
                          source_name=e.get("source_name"), stored_body=e.get("content") or e.get("summary"), event_id=UUID(e["id"]))
            package = await build_daily_evidence_package(**kwargs)
            retried = False
            if any(s.status == "FETCH_FAILED" for s in package.sources):  # this REPLAY re-attempts a transient network failure once
                package, retried = await build_daily_evidence_package(**kwargs), True
            report["daily"].append(_package_json(package, {"day": day["day"], "slot": slot, "title": post["title"], "replay_refetch": retried}))
            print(f"{day['day']} #{slot} {post['format']:10} {package.quality:10} steps={len(package.steps):2} facts={len(package.facts):2} "
                  f"lim={len(package.limitations)} media={package.media.status:13} | {package.why[:70]}")
    ident = json.loads(identity.read_text(encoding="utf-8"))
    members: dict[str, list[str]] = {}
    for eid, link in ident["links"].items():
        members.setdefault(link["story_id"], []).append(eid)
    for pick in json.loads(editor.read_text(encoding="utf-8"))["live"]["picks"]:
        eids: list[str] = []
        for sid in pick["story_ids"]:
            eids += [sid.split(":", 1)[1]] if sid.startswith("event:") else members.get(sid, [])
        cited_events = list(dict.fromkeys(eids))
        headlines = [events[i]["title"] for i in cited_events if i in events]
        bodies = await _recap_bodies(cited_events)
        package = await build_recap_story_package(post_id=f"recap-{pick['rank']}", premise=pick["weekly_premise"], headlines=headlines,
                                                  bodies=bodies)
        report["recap"].append(_package_json(package, {"rank": pick["rank"], "bodies_considered": len(bodies)}))
        print(f"RECAP #{pick['rank']} {package.quality:10} facts={len(package.facts):2} kept={len(bodies) - len(package.excluded_bodies):2} "
              f"excluded={len(package.excluded_bodies):2} | {pick['weekly_premise'][:60]}")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
