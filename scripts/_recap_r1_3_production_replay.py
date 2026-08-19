"""NINJA PULSE RECAP Phase R1.3 - OPTIONAL production READ-ONLY Story Integrity Gate replay.

Diagnostic-only, mirrors scripts/_recap_r1_2_production_calibration.py's own hard safety
mechanisms exactly (same `SET TRANSACTION READ ONLY` + `SHOW transaction_read_only` verification,
same 30s `SET LOCAL statement_timeout`, same never-commits/always-rollback discipline, same
minimal-import discipline) - the ONLY functional addition is running `evaluate_recap_story_
integrity()` per sampled Story, BEFORE showing announcement clustering, exactly mirroring
scripts/_recap_r1_3_offline_diagnostic.py's own presentation choice (only show clustering/
readiness detail for a story whose integrity gate PASSED).

NOT EXECUTED by this session (no VPS access) - static validation only. NOT integrated into any
worker. Intended to later run against the SAME kind of bounded production sample R1.2 used (event_
count >= 3 primary floor, event_count >= 2 fallback, boilerplate/duplicate-title filtered,
richness-ranked, up to 30 Stories).

Run (on the VPS only, later, by hand): docker compose run --rm --no-deps backend python scripts/_recap_r1_3_production_replay.py
Output: /tmp/recap_r1_3_production_replay.txt (VPS filesystem, outside the repo)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio  # noqa: E402
from collections import Counter  # noqa: E402

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from core.config import settings  # noqa: E402
from database.models.news_event import NewsEvent  # noqa: E402
from database.models.story import Story  # noqa: E402
from services.recap_event import (  # noqa: E402
    cluster_announcements,
    count_unique_sources,
    evaluate_recap_readiness,
    evaluate_recap_story_integrity,
    load_story_events,
)

OUTPUT_PATH = Path("/tmp/recap_r1_3_production_replay.txt")

SCAN_LIMIT = 500
TARGET_SAMPLE = 30
MIN_USABLE_AT_PRIMARY_FLOOR = 5
PRIMARY_EVENT_COUNT_FLOOR = 3
FALLBACK_EVENT_COUNT_FLOOR = 2
STATEMENT_TIMEOUT_MS = 30_000

_BOILERPLATE_TITLE_MARKERS = ("content cycle test event", "test event", "test source", "test story")


class ReadOnlyGuardError(RuntimeError):
    """Raised when SET TRANSACTION READ ONLY could not be verified - no query runs without it."""


def _is_boilerplate_title(title: str) -> bool:
    lowered = title.lower()
    return any(marker in lowered for marker in _BOILERPLATE_TITLE_MARKERS)


async def _verify_read_only(conn: AsyncConnection) -> None:
    await conn.execute(text("SET TRANSACTION READ ONLY"))
    result = await conn.execute(text("SHOW transaction_read_only"))
    value = result.scalar()
    if str(value).strip().lower() != "on":
        raise ReadOnlyGuardError(f"SET TRANSACTION READ ONLY not confirmed - got {value!r}. Refusing to query.")
    await conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}'"))


async def _scan_candidates(session: AsyncSession, event_count_floor: int) -> dict:
    stmt = select(Story).where(Story.event_count >= event_count_floor).order_by(Story.updated_at.desc()).limit(SCAN_LIMIT)
    scanned = list((await session.execute(stmt)).scalars().all())
    boilerplate_removed, duplicate_removed = 0, 0
    seen_titles: set[str] = set()
    usable: list[Story] = []
    for story in scanned:
        if _is_boilerplate_title(story.title):
            boilerplate_removed += 1
            continue
        if story.title in seen_titles:
            duplicate_removed += 1
            continue
        seen_titles.add(story.title)
        usable.append(story)
    return {
        "event_count_floor": event_count_floor, "scanned": len(scanned),
        "boilerplate_removed": boilerplate_removed, "duplicate_removed": duplicate_removed, "usable": usable,
    }


async def select_sample(session: AsyncSession) -> list[Story]:
    primary = await _scan_candidates(session, PRIMARY_EVENT_COUNT_FLOOR)
    usable = primary["usable"]
    if len(usable) < MIN_USABLE_AT_PRIMARY_FLOOR:
        fallback = await _scan_candidates(session, FALLBACK_EVENT_COUNT_FLOOR)
        seen_ids = {s.id for s in usable}
        usable = usable + [s for s in fallback["usable"] if s.id not in seen_ids]
    return usable[:TARGET_SAMPLE]


def render_story(story: Story, events: list[NewsEvent]) -> list[str]:
    anchor = next((e for e in events if e.id == story.first_event_id), events[0] if events else None)
    lines = [
        f"Story {story.id}: {story.title!r}",
        f"  declared event_count={story.event_count}  confirmed-member events={len(events)}",
    ]
    if anchor is None:
        lines.append("  SKIPPED - no confirmed member events loaded")
        lines.append("")
        return lines

    integrity = evaluate_recap_story_integrity(anchor, events)
    verdict = "PASS" if integrity.eligible else "FAIL"
    lines.append(f"  Story Integrity Gate: {verdict}")
    lines.append(f"    reasons: {integrity.reasons}")
    lines.append(f"    metrics: {integrity.metrics}")

    if integrity.eligible:
        clusters = cluster_announcements(events)
        unique_sources = count_unique_sources(events)
        last_event_at = max((e.published_at or e.collected_at for e in events), default=story.updated_at)
        readiness = evaluate_recap_readiness(
            event_count=len(events), announcement_count=len(clusters), unique_source_count=unique_sources,
            last_event_at=last_event_at, now=story.updated_at, research_complete=False, unresolved_conflict_count=0,
            story_integrity_eligible=integrity.eligible, story_integrity_reasons=integrity.reasons,
        )
        lines.append(f"  Announcement Clusters ({len(clusters)}):")
        for c in clusters:
            lines.append(f"    cluster#{c.cluster_id}: {len(c.event_ids)} event(s), anchor={c.headline!r}")
        lines.append(f"  Readiness: state={readiness.state}")
    else:
        lines.append("  (integrity FAILED - clustering/readiness not shown, matching the offline diagnostic's own presentation rule)")
    lines.append("")
    return lines


async def main() -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    conn = await engine.connect()
    trans = await conn.begin()
    try:
        await _verify_read_only(conn)
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)

        stories = await select_sample(session)
        lines = [
            "NINJA PULSE RECAP Phase R1.3 - production Story Integrity Gate replay report (READ ONLY)",
            "Source: production database (connection string never printed)",
            f"Sample size: {len(stories)} Stories (same bounded sample strategy as R1.2)",
            "",
        ]
        verdicts: Counter[str] = Counter()
        for story in stories:
            events = await load_story_events(session, story.id)
            block = render_story(story, events)
            lines += block
            verdicts["PASS" if any("PASS" in line for line in block[:4]) else "FAIL/SKIPPED"] += 1

        lines += ["=" * 100, "AGGREGATE", "=" * 100, f"Integrity verdicts: {dict(verdicts)}"]
        OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")
        print(f"Wrote {OUTPUT_PATH} ({len(stories)} Stories)")
    finally:
        await trans.rollback()
        await conn.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
