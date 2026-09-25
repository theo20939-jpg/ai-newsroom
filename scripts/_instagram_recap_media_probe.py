"""Zero-cost probe: how much REAL media the frozen 7-story recap can have when image discovery covers each story's cited member events,
not only its representative. Runs the existing run_shadow_discovery (network fetches, NO LLM call) in the scratch DB, then reports every
stored candidate per story with the deterministic final-visual profile, and writes a contact sheet per story.
Usage: python scripts/_instagram_recap_media_probe.py <recap_cited.json> <out dir> [max events per story]
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from io import BytesIO
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parent.parent
for line in (ROOT.parent.parent / ".env").read_text(encoding="utf-8").splitlines():  # DB credentials only, never printed
    if line.startswith("POSTGRES_") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")
os.environ["POSTGRES_DB"] = "kage_e2e_20260925"
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from core.config import settings  # noqa: E402


async def main() -> None:
    cited, out = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")), Path(sys.argv[2])
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    out.mkdir(parents=True, exist_ok=True)
    settings.image_intelligence_mode = "shadow"
    settings.image_candidate_persistence_mode = "finalists"
    settings.image_storage_root = str(out / "_image_storage")
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from database.models.news_event import NewsEvent
    from database.models.news_source import NewsSource
    from services.image_intelligence import run_shadow_discovery
    from services.image_persistence import get_editorial_image_candidates, read_candidate_bytes
    from services.instagram_asset_profile import profile_asset

    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    report = []
    for story in cited:
        events = [story["rep"]] + [e for e in story["cited"] if e != story["rep"]][: limit - 1]
        rows = []
        async with factory() as session:
            for eid in events:
                ev = await session.get(NewsEvent, UUID(eid))
                if ev is None:
                    continue
                src = await session.get(NewsSource, ev.source_id)
                try:
                    await run_shadow_discovery(event_id=ev.id, source_type=src.type, content=ev.content, article_url=ev.url, mode="shadow",
                                               event_title=ev.title, source_name=src.name, session=session)
                    await session.commit()
                except Exception as exc:  # noqa: BLE001
                    await session.rollback()
                    rows.append({"event": eid, "error": type(exc).__name__})
                    continue
                for cand in await get_editorial_image_candidates(session, news_event_id=ev.id, limit=10):
                    data = read_candidate_bytes(cand)
                    if not data:
                        continue
                    try:
                        with Image.open(BytesIO(data)) as im:
                            img = im.convert("RGB")
                    except (OSError, ValueError):
                        continue
                    prof = profile_asset(img, subject_key=story["key"])
                    name = f"{story['key']}_{len(rows):02d}.jpg"
                    img.thumbnail((360, 360))
                    img.save(out / name, quality=80)
                    rows.append({"event": eid, "source": src.name, "title": (ev.title or "")[:80], "size": [cand.width, cand.height],
                                 "rank": cand.rank, "relationship": cand.source_relationship, "suitable": prof.suitable_for_final_visual,
                                 "thumb": name})
        n_ok = sum(1 for r in rows if r.get("suitable"))
        report.append({"key": story["key"], "title": story["title"], "events_probed": len(events), "candidates": len(rows) - sum(1 for r in rows if "error" in r),
                       "suitable": n_ok, "rows": rows})
        print(f"{story['key']}: probed {len(events)} events, {len(rows)} rows, {n_ok} profile-suitable", flush=True)
    (out / "probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
