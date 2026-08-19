"""NINJA PULSE RECAP Phase R1.2 - production READ-ONLY clustering calibration.

Diagnostic-only. Never imported by any worker, application startup, or test suite. Intended to be
run manually on the VPS against the real production database, by hand, by the product owner -
NOT executed by this session (no VPS access here; local runs of this file are restricted to
static validation only - see scripts/_recap_r1_2_forensic.sql's own header for the paired SQL
forensic pass).

Hard safety properties (all enforced in code, not merely by convention):

1. READ-ONLY, VERIFIED, NOT ASSUMED: every query runs inside one transaction that issues
   `SET TRANSACTION READ ONLY` as its first statement and then verifies `SHOW transaction_read_only
   = 'on'` before any calibration query is allowed to run at all - see `_open_verified_read_only_
   session()`. If verification fails, `ReadOnlyGuardError` is raised and NOTHING else executes.
2. BOUNDED: a 30s `SET LOCAL statement_timeout` (transaction-scoped only - never `ALTER DATABASE`/
   `ALTER SYSTEM`) guards every query in this transaction; the Story scan itself is capped
   (`SCAN_LIMIT`), never a full-table scan.
3. NEVER COMMITS: the transaction is explicitly rolled back at the end, in a `finally` block,
   regardless of success or failure - this file contains no `session.add`/`session.add_all`/
   `session.delete`/`session.commit` call and no SQLAlchemy `insert()`/`update()`/`delete()`
   construct anywhere (grep-verifiable).
4. MINIMAL IMPORTS: only `core.config`, `database.models.news_event`, `database.models.story`,
   `services.recap_event` (pure clustering - confirmed side-effect-free at import time: it only
   defines dataclasses/constants/functions, no I/O at module scope), and `services.story_memory`
   (the same pure signature extractor R1/R1.1 already reuse). No collector, no workflow execution,
   no Research capability, no LLM provider, no Telegram bot, no article acquisition, no triage
   orchestrator, no HTTP client - grep-verifiable.
5. Reuses `services.recap_event.load_story_events()` unchanged for the authoritative
   confirmed-membership event set (item 10's mandatory match_type filter) - this file does not
   reimplement that filtering logic.

Output: /tmp/recap_r1_2_production_calibration.txt (VPS filesystem, outside the repo - never
written into this repository).

Run (on the VPS only): docker compose run --rm --no-deps backend python scripts/_recap_r1_2_production_calibration.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio  # noqa: E402
from collections import Counter  # noqa: E402
from itertools import combinations  # noqa: E402
from uuid import UUID  # noqa: E402

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from core.config import settings  # noqa: E402
from database.models.news_event import NewsEvent  # noqa: E402
from database.models.story import Story  # noqa: E402
from services.recap_event import (  # noqa: E402
    _CONFIRMED_MEMBERSHIP_MATCH_TYPES,
    _announcement_similarity,
    _normalize_domain,
    cluster_announcements,
    load_story_events,
)
from services.story_memory import extract_story_signature  # noqa: E402

OUTPUT_PATH = Path("/tmp/recap_r1_2_production_calibration.txt")

SCAN_LIMIT = 500  # bounded scan of recent Stories - never the whole table
TARGET_SAMPLE = 30
MIN_USABLE_AT_PRIMARY_FLOOR = 5
PRIMARY_EVENT_COUNT_FLOOR = 3
FALLBACK_EVENT_COUNT_FLOOR = 2
STATEMENT_TIMEOUT_MS = 30_000

THRESHOLDS: tuple[float, ...] = (0.65, 0.70, 0.75, 0.80, 0.85)
# Used only to pick which threshold's clustering result drives the post-hoc review-set
# categorization (item 12/16) - passed explicitly to cluster_announcements() like every other
# threshold tested here, NEVER read from settings.recap_announcement_cluster_threshold and never
# used to mutate it. Coincides with today's config default only because that is a reasonable
# diagnostic anchor point, not because this script depends on the live setting.
REVIEW_SET_THRESHOLD = 0.75

# Diagnostic-only sanity margins (item 15) - distinct from the 5 real calibration thresholds
# above, never fed back into clustering or config.
OVER_MERGE_PAIRWISE_FLOOR = 0.30
OVER_SPLIT_MARGIN = 0.05

_BOILERPLATE_TITLE_MARKERS = ("content cycle test event", "test event", "test source", "test story")


class ReadOnlyGuardError(RuntimeError):
    """Raised when SET TRANSACTION READ ONLY could not be verified - no calibration query is ever
    allowed to run without this guard passing first."""


def _is_boilerplate_title(title: str) -> bool:
    lowered = title.lower()
    return any(marker in lowered for marker in _BOILERPLATE_TITLE_MARKERS)


# ---------------------------------------------------------------------------
# Hard read-only guard (item 4) + bounded statement timeout (item 5)
# ---------------------------------------------------------------------------


async def _verify_read_only(conn: AsyncConnection) -> None:
    await conn.execute(text("SET TRANSACTION READ ONLY"))
    result = await conn.execute(text("SHOW transaction_read_only"))
    value = result.scalar()
    if str(value).strip().lower() != "on":
        raise ReadOnlyGuardError(
            f"SET TRANSACTION READ ONLY was not confirmed - SHOW transaction_read_only returned "
            f"{value!r}, expected 'on'. Refusing to run any calibration query."
        )
    await conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}'"))


# ---------------------------------------------------------------------------
# Sample selection (items 7-9)
# ---------------------------------------------------------------------------


async def _scan_candidates(session: AsyncSession, event_count_floor: int) -> dict:
    stmt = (
        select(Story)
        .where(Story.event_count >= event_count_floor)
        .order_by(Story.updated_at.desc())
        .limit(SCAN_LIMIT)
    )
    scanned = list((await session.execute(stmt)).scalars().all())

    boilerplate_removed = 0
    duplicate_removed = 0
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
        "event_count_floor": event_count_floor,
        "scanned": len(scanned),
        "boilerplate_removed": boilerplate_removed,
        "duplicate_removed": duplicate_removed,
        "usable": usable,
    }


async def _match_types_by_event_id(session: AsyncSession, story_id: UUID) -> dict[UUID, str]:
    """Supplementary, display-only lookup - the authoritative confirmed-member event set and
    count always come from `load_story_events()` (item 10's explicit preference); this only adds
    the match_type label for the per-event report line, which `load_story_events()` does not
    return."""
    from database.models.story_link import NewsEventStoryLink

    stmt = (
        select(NewsEventStoryLink.news_event_id, NewsEventStoryLink.match_type)
        .where(
            NewsEventStoryLink.story_id == story_id,
            NewsEventStoryLink.match_type.in_(_CONFIRMED_MEMBERSHIP_MATCH_TYPES),
        )
    )
    result = await session.execute(stmt)
    return {event_id: match_type for event_id, match_type in result}


async def _score_candidate(session: AsyncSession, story: Story) -> dict:
    events = await load_story_events(session, story.id)
    match_types = await _match_types_by_event_id(session, story.id)
    domains = {d for e in events if (d := _normalize_domain(e.url))}
    variety = len({match_types[e.id] for e in events if e.id in match_types})
    richness = len(events) + 2 * len(domains) + variety
    return {
        "story": story, "events": events, "match_types": match_types,
        "domains": domains, "richness": richness,
    }


async def select_sample(session: AsyncSession) -> tuple[list[dict], list[dict]]:
    """Returns (sample, scan_reports). `scan_reports` has one entry (primary floor) or two (primary
    + fallback, if the primary floor produced too few usable candidates - item 7's mandatory,
    explicitly-recorded fallback)."""
    scan_reports = []
    primary = await _scan_candidates(session, PRIMARY_EVENT_COUNT_FLOOR)
    scan_reports.append(primary)
    usable_stories = primary["usable"]

    if len(usable_stories) < MIN_USABLE_AT_PRIMARY_FLOOR:
        fallback = await _scan_candidates(session, FALLBACK_EVENT_COUNT_FLOOR)
        scan_reports.append(fallback)
        # Union by story id, primary-floor candidates first (already the richer, preferred set).
        seen_ids = {s.id for s in usable_stories}
        usable_stories = usable_stories + [s for s in fallback["usable"] if s.id not in seen_ids]

    scored = [await _score_candidate(session, story) for story in usable_stories]
    scored.sort(key=lambda c: c["richness"], reverse=True)
    return scored[:TARGET_SAMPLE], scan_reports


# ---------------------------------------------------------------------------
# Clustering at each threshold + diagnostic flags (items 12, 14, 15)
# ---------------------------------------------------------------------------


def _cluster_and_flag(events: list[NewsEvent], threshold: float) -> tuple[list, list[str]]:
    clusters = cluster_announcements(events, threshold=threshold)
    flags: list[str] = []
    events_by_id = {e.id: e for e in events}

    for cluster in clusters:
        members = [events_by_id[eid] for eid in cluster.event_ids if eid in events_by_id]
        for a, b in combinations(members, 2):
            sig_a = extract_story_signature(a.title, a.category)
            sig_b = extract_story_signature(b.title, b.category)
            similarity = _announcement_similarity(sig_a, a.title, sig_b, b.title)
            if similarity < OVER_MERGE_PAIRWISE_FLOOR:
                flags.append(
                    f"POSSIBLE_OVER_MERGE @{threshold}: cluster#{cluster.cluster_id} contains "
                    f"{a.title!r} and {b.title!r} with pairwise similarity {similarity:.2f} "
                    f"(< {OVER_MERGE_PAIRWISE_FLOOR}) - human review recommended"
                )

    for cluster_a, cluster_b in combinations(clusters, 2):
        anchor_a_event = next((e for e in events if e.title == cluster_a.headline), None)
        anchor_b_event = next((e for e in events if e.title == cluster_b.headline), None)
        if anchor_a_event is None or anchor_b_event is None:
            continue
        sig_a = extract_story_signature(anchor_a_event.title, anchor_a_event.category)
        sig_b = extract_story_signature(anchor_b_event.title, anchor_b_event.category)
        similarity = _announcement_similarity(sig_a, anchor_a_event.title, sig_b, anchor_b_event.title)
        if similarity >= threshold - OVER_SPLIT_MARGIN:
            flags.append(
                f"POSSIBLE_OVER_SPLIT @{threshold}: cluster#{cluster_a.cluster_id} "
                f"({cluster_a.headline!r}) and cluster#{cluster_b.cluster_id} ({cluster_b.headline!r}) "
                f"anchors have similarity {similarity:.2f} (>= threshold-{OVER_SPLIT_MARGIN}) - "
                "human review recommended"
            )

    return clusters, flags


# ---------------------------------------------------------------------------
# Report rendering (item 13) - no article bodies/summary/content/workflow JSON/secrets anywhere.
# ---------------------------------------------------------------------------


def render_story_block(candidate: dict) -> list[str]:
    story: Story = candidate["story"]
    events: list[NewsEvent] = candidate["events"]
    match_types: dict[UUID, str] = candidate["match_types"]

    lines = [
        f"Story {story.id}",
        f"  Title: {story.title!r}",
        f"  category: {story.category.value if story.category is not None else None}   topic_bucket: {story.topic_bucket!r}",
        f"  Story.event_count (declared): {story.event_count}   confirmed-member events (actual): {len(events)}",
    ]
    if story.event_count != len(events):
        lines.append(
            f"  FLAG: EVENT_COUNT_MISMATCH - declared={story.event_count}, actual confirmed-member "
            f"rows loaded={len(events)}. Not repaired here (diagnostic only)."
        )
    lines.append("  Events (chronological):")
    for event in events:
        ts = (event.published_at or event.collected_at).strftime("%Y-%m-%d %H:%M")
        domain = _normalize_domain(event.url) or "(no url)"
        match_type = match_types.get(event.id, "(unknown)")
        lines.append(f"    [{ts}] {event.id}  {event.title!r}  domain={domain}  match_type={match_type}")

    per_threshold_counts = []
    all_flags: list[str] = []
    for threshold in THRESHOLDS:
        clusters, flags = _cluster_and_flag(events, threshold)
        per_threshold_counts.append(len(clusters))
        all_flags.extend(flags)
        lines.append(f"  THRESHOLD {threshold}:")
        for cluster in clusters:
            lines.append(f"    cluster {cluster.cluster_id + 1}:")
            for eid in cluster.event_ids:
                member = next((e for e in events if e.id == eid), None)
                if member is not None:
                    lines.append(f"      - {member.title!r}")

    if len(set(per_threshold_counts)) > 1:
        all_flags.append(
            f"THRESHOLD_SENSITIVE: cluster count varies across thresholds - {dict(zip(THRESHOLDS, per_threshold_counts))}"
        )

    if all_flags:
        lines.append("  Diagnostic flags (human review only, never auto-applied):")
        for flag in all_flags:
            lines.append(f"    - {flag}")

    lines.append("")
    return lines


def render_scan_report(scan: dict) -> list[str]:
    return [
        f"  event_count floor: {scan['event_count_floor']}",
        f"    candidate rows scanned: {scan['scanned']}",
        f"    removed as boilerplate/test-fixture: {scan['boilerplate_removed']}",
        f"    removed as duplicate title: {scan['duplicate_removed']}",
        f"    remaining usable candidates: {len(scan['usable'])}",
    ]


def render_threshold_aggregate(sample: list[dict]) -> list[str]:
    lines = ["=" * 100, "THRESHOLD SENSITIVITY - aggregate", "=" * 100, ""]
    for threshold in THRESHOLDS:
        cluster_counts = [len(cluster_announcements(c["events"], threshold=threshold)) for c in sample]
        total_events = sum(len(c["events"]) for c in sample)
        total_clusters = sum(cluster_counts)
        dist = Counter(cluster_counts)
        lines.append(f"THRESHOLD {threshold}:")
        lines.append(f"  stories sampled: {len(sample)}   events sampled: {total_events}   total clusters: {total_clusters}")
        lines.append(f"  cluster-size distribution: {dict(sorted(dist.items()))}")
        lines.append(f"  stories producing 1 cluster: {sum(1 for c in cluster_counts if c == 1)}")
        lines.append(f"  stories producing 2 clusters: {sum(1 for c in cluster_counts if c == 2)}")
        lines.append(f"  stories producing 3 clusters: {sum(1 for c in cluster_counts if c == 3)}")
        lines.append(f"  stories producing 4+ clusters: {sum(1 for c in cluster_counts if c >= 4)}")
        lines.append("")
    return lines


def render_review_set(sample: list[dict]) -> list[str]:
    lines = ["=" * 100, "REVIEW SET (manual review only, never fabricated - fewer printed if fewer exist)", "=" * 100, ""]

    annotated = []
    for c in sample:
        counts = {t: len(cluster_announcements(c["events"], threshold=t)) for t in THRESHOLDS}
        annotated.append((c["story"], c["events"], counts))

    duplicate_heavy = sorted(annotated, key=lambda a: (a[2][REVIEW_SET_THRESHOLD] / max(1, len(a[1])), -len(a[1])))[:5]
    multi_dev = sorted(annotated, key=lambda a: (a[2][REVIEW_SET_THRESHOLD] / max(1, len(a[1]))), reverse=True)[:5]
    ambiguous = [a for a in annotated if len(set(a[2].values())) > 1][:5]

    for label, group in (
        ("Duplicate-heavy Stories", duplicate_heavy),
        ("Multi-development Stories", multi_dev),
        ("Threshold-sensitive / ambiguous Stories", ambiguous),
    ):
        lines.append(f"--- {label} ({len(group)} found) ---")
        for story, events, counts in group:
            lines.append(f"  Story {story.id}: {story.title!r} ({len(events)} confirmed events)")
            lines.append(f"    clusters by threshold: {counts}")
        lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Main (read-only orchestration)
# ---------------------------------------------------------------------------


async def main() -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    conn = await engine.connect()
    trans = await conn.begin()
    try:
        await _verify_read_only(conn)
        read_only_confirmed = True

        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
        sample, scan_reports = await select_sample(session)

        lines = [
            "NINJA PULSE RECAP Phase R1.2 - production clustering calibration report (READ ONLY)",
            "Source: production database (connection string never printed)",
            f"Read-only transaction verified: {read_only_confirmed}",
            f"Statement timeout: {STATEMENT_TIMEOUT_MS}ms (transaction-local, SET LOCAL)",
            f"Sample target: up to {TARGET_SAMPLE} Stories, ranked by diagnostic richness "
            "(event_count + 2*distinct_domains + match_type_variety - NOT an editorial score, "
            "never persisted, never used to change production behavior)",
            f"Sample size actually obtained: {len(sample)}",
            "",
            "=" * 100,
            "SAMPLE SELECTION",
            "=" * 100,
            "",
        ]
        for scan in scan_reports:
            lines += render_scan_report(scan)
            lines.append("")
        if len(scan_reports) > 1:
            lines.append(
                f"FALLBACK TRIGGERED: fewer than {MIN_USABLE_AT_PRIMARY_FLOOR} usable candidates at "
                f"event_count >= {PRIMARY_EVENT_COUNT_FLOOR}; retried at event_count >= {FALLBACK_EVENT_COUNT_FLOOR}."
            )
            lines.append("")

        lines += ["=" * 100, "PER-STORY DETAIL (all 5 thresholds)", "=" * 100, ""]
        for candidate in sample:
            lines += render_story_block(candidate)

        lines += render_threshold_aggregate(sample)
        lines += render_review_set(sample)

        OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")
        print(f"Wrote {OUTPUT_PATH} ({len(sample)} Stories sampled)")
    finally:
        # Never commits - always rolls back, regardless of success or failure (item 6).
        await trans.rollback()
        await conn.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
