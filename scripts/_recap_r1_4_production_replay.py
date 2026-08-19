"""NINJA PULSE RECAP Phase R1.4 - updated production READ-ONLY replay (Story Integrity Gate +
announcement identity precedence).

Diagnostic-only, mirrors scripts/_recap_r1_3_production_replay.py's own hard safety mechanisms
exactly (same `SET TRANSACTION READ ONLY` + `SHOW transaction_read_only` verification, same 30s
`SET LOCAL statement_timeout`, same never-commits/always-rollback discipline, same minimal-import
discipline, same bounded sample strategy). New for R1.4:

- shows OLD (pre-R1.4, naive 0.4/0.6-weighted, anchor-only) vs NEW (R1.4 identity-precedence)
  announcement_count side by side, for every integrity-PASS Story - the OLD formula is
  reconstructed LOCALLY in this script only, for comparison display purposes, never imported from
  or written back into services/recap_event.py;
- explicitly flags known production cases by title-substring match (OpenAI/Hugging Face, Taiwan,
  AI/VR classrooms, Bashkiria, and the known-bad generic-opener Story patterns from R1.3 §1) when
  present in the sample, so they are easy to find in a long report.

NOT EXECUTED by this session (no VPS access) - static validation only. NOT integrated into any
worker.

Run (on the VPS only, later, by hand): docker compose run --rm --no-deps backend python scripts/_recap_r1_4_production_replay.py
Output: /tmp/recap_r1_4_production_replay.txt (VPS filesystem, outside the repo)
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
    AnnouncementCluster,
    cluster_announcements,
    count_unique_sources,
    evaluate_recap_readiness,
    evaluate_recap_story_integrity,
    load_story_events,
)
from services.story_memory import extract_story_signature  # noqa: E402
from services.text_normalization import symmetric_token_overlap  # noqa: E402

OUTPUT_PATH = Path("/tmp/recap_r1_4_production_replay.txt")

SCAN_LIMIT = 500
TARGET_SAMPLE = 30
MIN_USABLE_AT_PRIMARY_FLOOR = 5
PRIMARY_EVENT_COUNT_FLOOR = 3
FALLBACK_EVENT_COUNT_FLOOR = 2
STATEMENT_TIMEOUT_MS = 30_000

_BOILERPLATE_TITLE_MARKERS = ("content cycle test event", "test event", "test source", "test story")

# Known production cases (R1.3 §1/§2, R1.4 §2/§3) - surfaced explicitly when present, purely by
# title substring, for readability in a long report. Never used for any clustering/integrity
# decision - decision logic never inspects these strings.
_KNOWN_CASES = {
    "OpenAI/Hugging Face": ("hugging face", "openai"),
    "Taiwan AI dividend": ("taiwan", "dividend"),
    "AI/VR classrooms": ("classroom",),
    "Bashkiria AI medicine": ("башкир",),
    "generic 'What...' opener": ("what are you doing",),
    "generic 'Large language models...' opener": ("large language model",),
}


class ReadOnlyGuardError(RuntimeError):
    """Raised when SET TRANSACTION READ ONLY could not be verified - no query runs without it."""


def _is_boilerplate_title(title: str) -> bool:
    lowered = title.lower()
    return any(marker in lowered for marker in _BOILERPLATE_TITLE_MARKERS)


def _known_case_labels(story_title: str, events: list[NewsEvent]) -> list[str]:
    haystack = " ".join([story_title, *(e.title for e in events)]).lower()
    return [label for label, markers in _KNOWN_CASES.items() if any(m in haystack for m in markers)]


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


# ---------------------------------------------------------------------------
# OLD (pre-R1.4) formula, reconstructed LOCALLY for comparison display only - never imported from
# or written back into services/recap_event.py. Naive 0.4*entity_jaccard + 0.6*title_dice, no
# identity-precedence layer, compared against the cluster's ORIGINAL anchor only.
# ---------------------------------------------------------------------------


def _old_jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _old_similarity(sig_a, title_a: str, sig_b, title_b: str) -> float:
    entity_overlap = _old_jaccard(set(sig_a.entities), set(sig_b.entities))
    title_overlap = symmetric_token_overlap(title_a, title_b)
    return min(1.0, 0.4 * entity_overlap + 0.6 * title_overlap)


def _old_cluster_announcements(events: list[NewsEvent]) -> int:
    clusters: list[dict] = []
    for event in events:
        signature = extract_story_signature(event.title, event.category)
        best_idx, best_score = None, 0.0
        for idx, cluster in enumerate(clusters):
            score = _old_similarity(signature, event.title, cluster["sig"], cluster["title"])
            if score > best_score:
                best_score, best_idx = score, idx
        if best_idx is not None and best_score >= settings.recap_announcement_cluster_threshold:
            clusters[best_idx]["event_ids"].append(event.id)
        else:
            clusters.append({"sig": signature, "title": event.title, "event_ids": [event.id]})
    return len(clusters)


def render_story(story: Story, events: list[NewsEvent]) -> list[str]:
    anchor = next((e for e in events if e.id == story.first_event_id), events[0] if events else None)
    known = _known_case_labels(story.title, events)
    lines = [
        f"Story {story.id}: {story.title!r}" + (f"  [KNOWN CASE: {', '.join(known)}]" if known else ""),
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

    if integrity.eligible:
        old_count = _old_cluster_announcements(events)
        new_clusters: list[AnnouncementCluster] = cluster_announcements(events)
        unique_sources = count_unique_sources(events)
        last_event_at = max((e.published_at or e.collected_at for e in events), default=story.updated_at)
        readiness = evaluate_recap_readiness(
            event_count=len(events), announcement_count=len(new_clusters), unique_source_count=unique_sources,
            last_event_at=last_event_at, now=story.updated_at, research_complete=False, unresolved_conflict_count=0,
            story_integrity_eligible=integrity.eligible, story_integrity_reasons=integrity.reasons,
        )
        lines.append(f"  OLD announcement_count (pre-R1.4, reconstructed for comparison): {old_count}")
        lines.append(f"  NEW announcement_count (R1.4 identity precedence): {len(new_clusters)}")
        lines.append("  NEW cluster membership:")
        for c in new_clusters:
            member_titles = []
            for eid in c.event_ids:
                member = next((e for e in events if e.id == eid), None)
                if member is not None:
                    member_titles.append(member.title)
            lines.append(f"    cluster#{c.cluster_id}: {member_titles}")
        lines.append(f"  Readiness: state={readiness.state}")
    else:
        lines.append("  (integrity FAILED - clustering/readiness not shown)")
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
            "NINJA PULSE RECAP Phase R1.4 - production replay report (READ ONLY)",
            "Source: production database (connection string never printed)",
            f"Sample size: {len(stories)} Stories (same bounded sample strategy as R1.2/R1.3)",
            "",
        ]
        verdicts: Counter[str] = Counter()
        known_case_hits: Counter[str] = Counter()
        for story in stories:
            events = await load_story_events(session, story.id)
            for label in _known_case_labels(story.title, events):
                known_case_hits[label] += 1
            block = render_story(story, events)
            lines += block
            verdicts["PASS" if any("PASS" in line for line in block[:3]) else "FAIL/SKIPPED"] += 1

        lines += [
            "=" * 100, "AGGREGATE", "=" * 100,
            f"Integrity verdicts: {dict(verdicts)}",
            f"Known production cases found in sample: {dict(known_case_hits) if known_case_hits else 'none'}",
        ]
        OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")
        print(f"Wrote {OUTPUT_PATH} ({len(stories)} Stories)")
    finally:
        await trans.rollback()
        await conn.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
