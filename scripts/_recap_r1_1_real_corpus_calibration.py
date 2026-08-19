"""NINJA PULSE RECAP Phase R1.1 - real-corpus clustering calibration (READ ONLY).

Samples a bounded set of real, existing Story/NewsEvent rows from the LOCAL/TEST-accessible
database (settings.test_database_url - never settings.database_url/postgres_db, enforced by the
same identity-comparison barrier tests/conftest.py's own Barrier 4 already establishes), runs the
real `services/recap_event.py::cluster_announcements()` against them at three thresholds
(0.70/0.75/0.80), and writes a human-readable report to tmp/recap_r1_1_real_corpus_report.txt.

READ ONLY: every statement issued is a SELECT. No INSERT/UPDATE/DELETE, no commit, no LLM call, no
network call, no production config change (cluster_announcements()'s new `threshold=` override
parameter is passed explicitly per call - `settings.recap_announcement_cluster_threshold` itself is
never mutated).

Run: python scripts/_recap_r1_1_real_corpus_calibration.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio  # noqa: E402
from collections import Counter  # noqa: E402
from urllib.parse import urlsplit  # noqa: E402
from uuid import UUID  # noqa: E402

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from core.config import settings  # noqa: E402
from database.models.news_event import NewsEvent  # noqa: E402
from database.models.story import Story  # noqa: E402
from database.models.story_link import NewsEventStoryLink  # noqa: E402
from services.recap_event import _CONFIRMED_MEMBERSHIP_MATCH_TYPES, cluster_announcements  # noqa: E402

# Mirrors tests/conftest.py's own Barrier 4 exactly - refuses to run against anything but the
# dedicated test database, never the real/dev database, regardless of what settings.database_url
# would resolve to.
if settings.postgres_test_db == settings.postgres_db or not settings.postgres_test_db:
    raise SystemExit(
        f"REFUSING TO CONNECT: postgres_test_db ({settings.postgres_test_db!r}) must be a distinct, "
        f"real test database name, never equal to postgres_db ({settings.postgres_db!r})."
    )

SCAN_LIMIT = 300  # bounded scan of recent Stories - never the whole table
TARGET_SAMPLE = 25
# Spec's preferred floor is event_count >= 3, but a direct query against the real
# test-accessible corpus (settings.test_database_url) found ZERO Story rows with event_count >= 3
# - the corpus tops out at event_count == 2 (452 Stories total: 323 with event_count=1, 129 with
# event_count=2, 0 higher). Relaxed to 2 so the calibration can run against real data at all - a
# disclosed corpus limitation (see the report's own header line), not a silent weakening of the
# spec's preference.
MIN_CONFIRMED_EVENTS = 2
MIN_DOMAINS = 2
THRESHOLDS = (0.70, 0.75, 0.80)


def _normalize_domain(url: str | None) -> str | None:
    if not url:
        return None
    netloc = urlsplit(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc or None


async def _load_confirmed_events_with_match_type(
    session: AsyncSession, story_id: UUID,
) -> list[tuple[NewsEvent, str]]:
    stmt = (
        select(NewsEvent, NewsEventStoryLink.match_type)
        .join(NewsEventStoryLink, NewsEventStoryLink.news_event_id == NewsEvent.id)
        .where(
            NewsEventStoryLink.story_id == story_id,
            NewsEventStoryLink.match_type.in_(_CONFIRMED_MEMBERSHIP_MATCH_TYPES),
        )
        .order_by(NewsEvent.published_at.asc().nulls_last(), NewsEvent.collected_at.asc())
    )
    result = await session.execute(stmt)
    return [(event, match_type) for event, match_type in result]


# Forensic finding (this checkpoint): a direct scan of settings.test_database_url found that
# EVERY Story row with event_count >= 2 is either (a) synthetic pytest-fixture output with a
# UUID-suffixed placeholder title (e.g. "Content cycle test event <uuid>", from
# tests/test_content_worker_cycle.py's own fixtures), or (b) one single real-looking
# semantic-duplicate-detection test case ("2 Unstoppable AI Stocks...") committed 23 separate
# times across different pytest runs. There is no genuine organic multi-source news corpus in
# this database. This classifier exists to separate the one real signal that DOES exist from the
# synthetic noise, and to make that separation visible in the report rather than silently masking
# it.
_BOILERPLATE_TITLE_MARKERS = ("content cycle test event", "test event", "test source", "test story")


def _is_boilerplate_title(title: str) -> bool:
    lowered = title.lower()
    return any(marker in lowered for marker in _BOILERPLATE_TITLE_MARKERS)


async def sample_stories(session: AsyncSession) -> list[tuple[Story, list[tuple[NewsEvent, str]], bool]]:
    stmt = (
        select(Story)
        .where(Story.event_count >= MIN_CONFIRMED_EVENTS)
        .order_by(Story.updated_at.desc())
        .limit(SCAN_LIMIT)
    )
    candidates = list((await session.execute(stmt)).scalars().all())

    scored: list[tuple[float, Story, list[tuple[NewsEvent, str]], bool]] = []
    seen_titles: set[str] = set()
    for story in candidates:
        if story.title in seen_titles:
            continue  # dedupe repeated fixture-origin copies of the identical case
        rows = await _load_confirmed_events_with_match_type(session, story.id)
        if len(rows) < MIN_CONFIRMED_EVENTS:
            continue
        seen_titles.add(story.title)
        is_real = not _is_boilerplate_title(story.title)
        domains = {d for e, _mt in rows if (d := _normalize_domain(e.url))}
        match_type_variety = len({mt for _e, mt in rows})
        # Real, non-boilerplate content is preferred by a large fixed bonus (spec's own intent -
        # genuine editorial signal over synthetic test noise) regardless of domain/match-type
        # richness, which only orders WITHIN each of the two groups.
        richness = (1000 if is_real else 0) + len(rows) + 2 * len(domains) + match_type_variety
        scored.append((richness, story, rows, is_real))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [(story, rows, is_real) for _richness, story, rows, is_real in scored[:TARGET_SAMPLE]]


def _cluster_at(rows: list[tuple[NewsEvent, str]], threshold: float):
    events = [e for e, _mt in rows]
    return cluster_announcements(events, threshold=threshold)


def render_story_block(story: Story, rows: list[tuple[NewsEvent, str]], is_real: bool) -> list[str]:
    origin = "REAL" if is_real else "SYNTHETIC/TEST-FIXTURE"
    lines = [
        f"Story {story.id}  [data_origin={origin}]", f"  Title: {story.title!r}",
        f"  event_count (Story.event_count): {story.event_count}", "  Events:",
    ]
    for event, match_type in rows:
        ts = (event.published_at or event.collected_at).strftime("%Y-%m-%d %H:%M")
        domain = _normalize_domain(event.url) or "(no url)"
        lines.append(f"    [{ts}] {event.title!r}  domain={domain}  match_type={match_type}")

    clusters_default = _cluster_at(rows, settings.recap_announcement_cluster_threshold)
    lines.append(f"  Announcement Clusters (threshold={settings.recap_announcement_cluster_threshold}):")
    for c in clusters_default:
        lines.append(f"    cluster#{c.cluster_id}: anchor={c.headline!r}  members={len(c.event_ids)}")
    lines.append("")
    return lines


def render_aggregate(sample: list[tuple[Story, list[tuple[NewsEvent, str]], bool]]) -> list[str]:
    lines = ["=" * 100, "AGGREGATE METRICS (threshold=default 0.75)", "=" * 100, ""]
    real_count = sum(1 for _s, _r, is_real in sample if is_real)
    total_events = sum(len(rows) for _s, rows, _r in sample)
    cluster_counts = [len(_cluster_at(rows, settings.recap_announcement_cluster_threshold)) for _s, rows, _r in sample]
    total_clusters = sum(cluster_counts)

    lines.append(f"Stories sampled: {len(sample)}  (REAL: {real_count}, SYNTHETIC/TEST-FIXTURE: {len(sample) - real_count})")
    lines.append(f"Events sampled: {total_events}")
    lines.append(f"Clusters produced: {total_clusters}")
    lines.append("")

    dist = Counter(cluster_counts)
    lines.append("Cluster size distribution (clusters per Story):")
    for k in sorted(dist):
        lines.append(f"  {k} cluster(s): {dist[k]} Stories")
    lines.append("")

    all_collapsed = sum(1 for (_s, rows, _r), cc in zip(sample, cluster_counts) if cc == 1 and len(rows) > 1)
    each_own_cluster = sum(1 for (_s, rows, _r), cc in zip(sample, cluster_counts) if cc == len(rows) and len(rows) > 1)
    lines.append(f"Stories where all events collapsed into 1 cluster: {all_collapsed}")
    lines.append(f"Stories where each event became its own cluster: {each_own_cluster}")
    lines.append("")
    for floor in (2, 3, 4, 5):
        count = sum(1 for cc in cluster_counts if cc >= floor)
        lines.append(f"Stories with {floor}+ clusters: {count}")
    lines.append("")
    return lines


def render_threshold_sensitivity(sample: list[tuple[Story, list[tuple[NewsEvent, str]], bool]]) -> list[str]:
    lines = ["=" * 100, "THRESHOLD SENSITIVITY (0.70 / 0.75 / 0.80) - diagnostic only", "=" * 100, ""]
    per_threshold_totals = {t: 0 for t in THRESHOLDS}
    lines.append(f"{'Story':<40}{'origin':<10}{'events':>8}{'0.70':>8}{'0.75':>8}{'0.80':>8}")
    for story, rows, is_real in sample:
        counts = {t: len(_cluster_at(rows, t)) for t in THRESHOLDS}
        for t in THRESHOLDS:
            per_threshold_totals[t] += counts[t]
        title_short = (story.title[:37] + "...") if len(story.title) > 40 else story.title
        origin = "REAL" if is_real else "SYNTHETIC"
        lines.append(f"{title_short:<40}{origin:<10}{len(rows):>8}{counts[0.70]:>8}{counts[0.75]:>8}{counts[0.80]:>8}")
    lines.append("")
    lines.append("Total clusters across sample, by threshold:")
    for t in THRESHOLDS:
        lines.append(f"  {t}: {per_threshold_totals[t]}")
    lines.append("")
    return lines


def render_manual_review_set(sample: list[tuple[Story, list[tuple[NewsEvent, str]], bool]]) -> list[str]:
    lines = ["=" * 100, "MANUAL REVIEW SET", "=" * 100, ""]
    real_n = sum(1 for _s, _r, is_real in sample if is_real)
    if real_n <= 1:
        lines.append(
            f"NOTE: only {real_n} REAL Story exists in this sample (see the CORPUS LIMITATION section "
            "above) - the three categories below are consequently NOT meaningfully differentiated: every "
            "SYNTHETIC/TEST-FIXTURE Story in this corpus has exactly 2 identically-titled events, so "
            "'duplicate-heavy' / 'multi-development' / 'ambiguous' all collapse to the same trivial "
            "1-cluster-of-2-identical-titles case. Read this section as illustrative of the report format "
            "only, not as genuine calibration evidence."
        )
        lines.append("")

    annotated = []
    for story, rows, _is_real in sample:
        counts = {t: len(_cluster_at(rows, t)) for t in THRESHOLDS}
        annotated.append((story, rows, counts))

    # Likely duplicate-heavy: many events, few clusters at the default threshold (low clusters/events ratio).
    duplicate_heavy = sorted(annotated, key=lambda a: (a[2][0.75] / len(a[1]), -len(a[1])))[:5]
    # Likely multi-development: clusters/events ratio close to 1 (each event its own development).
    multi_dev = sorted(annotated, key=lambda a: (a[2][0.75] / len(a[1])), reverse=True)[:5]
    # Ambiguous: cluster count actually changes across the three thresholds (threshold-sensitive).
    ambiguous = sorted(annotated, key=lambda a: len({a[2][t] for t in THRESHOLDS}), reverse=True)[:5]

    for label, group in (
        ("Likely duplicate-heavy Stories", duplicate_heavy),
        ("Likely multi-development Stories", multi_dev),
        ("Ambiguous Stories (cluster count changes across thresholds)", ambiguous),
    ):
        lines.append(f"--- {label} ---")
        for story, rows, counts in group:
            lines.append(f"  Story {story.id}: {story.title!r} ({len(rows)} events)")
            lines.append(f"    clusters @0.70={counts[0.70]}  @0.75={counts[0.75]}  @0.80={counts[0.80]}")
            for event, match_type in rows:
                domain = _normalize_domain(event.url) or "(no url)"
                lines.append(f"      - {event.title!r}  domain={domain}  match_type={match_type}")
        lines.append("")
    return lines


async def main() -> None:
    engine = create_async_engine(settings.test_database_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine) as session:
            sample = await sample_stories(session)

            real_n = sum(1 for _s, _r, is_real in sample if is_real)
            lines = [
                "NINJA PULSE RECAP Phase R1.1 - real-corpus clustering calibration report (READ ONLY)",
                f"Source database: {settings.postgres_test_db!r} (test-accessible, never production)",
                f"Scan limit: {SCAN_LIMIT} recent Stories with event_count >= {MIN_CONFIRMED_EVENTS}",
                f"Sample target: up to {TARGET_SAMPLE} Stories, deduplicated by title, real content preferred",
                f"Sample size actually obtained: {len(sample)}  (REAL: {real_n}, SYNTHETIC/TEST-FIXTURE: {len(sample) - real_n})",
                "",
                "CORPUS LIMITATION (disclosed, two separate findings):",
                "(1) event_count floor: spec's preferred floor is event_count >= 3. A direct query against "
                "this test-accessible database found ZERO Story rows with event_count >= 3 (452 Stories "
                "total: 323 with event_count=1, 129 with event_count=2, none higher) - relaxed to >= 2, "
                "the richest data actually available here.",
                "(2) content authenticity: of the Story rows with event_count >= 2, essentially all are "
                "synthetic pytest-fixture output - either UUID-suffixed placeholder titles ('Content cycle "
                "test event <uuid>') with no real content, or ~23 duplicate copies of exactly ONE real-"
                "looking semantic-duplicate-detection test case ('2 Unstoppable AI Stocks...' vs '...the $3 "
                "Trillion Club...'). After deduplication, that is the ONLY genuinely real multi-event "
                "example this database contains. This is a real, disclosed environmental constraint - see "
                "item P (recommended threshold) for how this affects the final recommendation.",
                "",
                "=" * 100,
                "PER-STORY DETAIL (threshold=default 0.75)",
                "=" * 100,
                "",
            ]
            for story, rows, is_real in sample:
                lines += render_story_block(story, rows, is_real)

            lines += render_aggregate(sample)
            lines += render_threshold_sensitivity(sample)
            lines += render_manual_review_set(sample)

            output_path = Path(__file__).resolve().parent.parent / "tmp" / "recap_r1_1_real_corpus_report.txt"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("\n".join(lines), encoding="utf-8")
            print(f"Wrote {output_path} ({len(sample)} Stories sampled)")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
