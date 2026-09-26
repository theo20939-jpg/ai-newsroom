"""Zero-cost evidence preflight for fresh viral candidates: the real daily evidence package (live article acquisition + media discovery) for
each event in the scratch DB, WITHOUT any model call - run with no OPENAI_API_KEY in the environment. A story whose evidence is BLOCKING
would stop at the evidence gate before Phase A, so it cannot be the one paid canary.
Usage: python scripts/_instagram_evidence_preflight.py <out dir> <event id> [<event id> ...]
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
assert not os.environ.get("OPENAI_API_KEY"), "the preflight runs without any provider credential"

import scripts._instagram_e2e_week as harness  # noqa: E402  (scratch DB env only)

from core.config import settings  # noqa: E402


async def main() -> None:
    out, ids = Path(sys.argv[1]), [UUID(x) for x in sys.argv[2:]]
    out.mkdir(parents=True, exist_ok=True)
    settings.article_acquisition_mode = "shadow"
    settings.image_intelligence_mode = "shadow"
    settings.image_candidate_persistence_mode = "finalists"
    settings.image_storage_root = str(out / "_image_storage")
    assert harness.SCRATCH_DB in settings.database_url
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from database.models.news_event import NewsEvent
    from database.models.news_source import NewsSource
    from services.instagram_evidence_package import build_daily_evidence_package
    from services.instagram_viral_format import substantive_facts

    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    rows = []
    for event_id in ids:
        async with factory() as session:
            event = await session.get(NewsEvent, event_id)
            source = await session.get(NewsSource, event.source_id)
            try:
                package = await build_daily_evidence_package(
                    post_id=str(event_id), fmt="meme_trend", title=event.title or "", url=event.url,
                    source_type=getattr(getattr(source, "type", None), "value", "RSS"), source_name=source.name,
                    stored_body=event.content or event.summary, event=event, event_id=event_id, session=session,
                    acquisition_enabled=True, media_mode="shadow")
                await session.commit()
                facts = package.director_evidence()
                rows.append({"id": str(event_id), "title": event.title, "evidence": package.quality, "why": package.why,
                             "source_media": package.media.status, "substantive_facts": len(substantive_facts(facts)),
                             "facts": [f[:220] for f in facts]})
            except Exception as exc:  # noqa: BLE001
                rows.append({"id": str(event_id), "title": event.title, "evidence": f"ERROR {type(exc).__name__}: {str(exc)[:200]}"})
    (out / "evidence_preflight.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in rows:
        print(r["evidence"], "|", r.get("source_media"), "| facts", r.get("substantive_facts"), "|", r["title"][:80], "|", r.get("why", "")[:90])
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
