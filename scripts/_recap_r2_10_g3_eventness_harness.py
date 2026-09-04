"""R2.10G3-A - shadow eventness evaluation harness.

Manual, READ-ONLY, deterministic-by-default batch evaluator answering: "given the manifest's
manual editorial ground truth (scripts/_recap_r2_10_g3_eventness_manifest.py), how does that
compare against (a) existing RECAP readiness and (b) a set of deterministic, already-existing
observable features?" This is SHADOW-ONLY - it never mutates a Story, never writes a
NewsEventStoryLink, never changes readiness, never publishes, never sends Telegram.

Reuses, never duplicates:
  - scripts/_recap_r2_shadow_batch.py::build_shadow_report() / ShadowStoryReport (ported verbatim
    from feature/r2-shadow-preparation - confirmed import-compatible against this exact base
    before any adaptation) for the existing-readiness/candidate/evaluation_status observation.
  - scripts/_recap_r2_10_readiness_candidate_scanner.py::scan_story_readiness()/CandidateScanRow
    (already imported BY the batch script - not re-imported separately here).
  - services/recap_event.py's own unmodified primitives (cluster_announcements,
    count_unique_sources, evaluate_recap_story_integrity, evaluate_recap_readiness,
    load_story_events) and services/recap_origin_projection.py's own
    resolve_recap_origin_projection()/build_effective_recap_members() for the deeper feature set
    (span, match-type distribution, cluster sizes) neither existing script computes.

SAFE BY DEFAULT (mirrors both existing R2 CLI scripts' own established discipline):
  - No --with-llm argument anywhere in this parser - no code path here can construct a Gateway
    request. The synthesis path (scripts/_recap_r2_shadow_synthesize.py, unmodified, from
    feature/r2-shadow-preparation) is a SEPARATE, explicit, single-Story, opt-in script - never
    invoked automatically by this harness.
  - Never writes to the database (read-only transaction, verified and enforced - `_verify_read_only()`
    duplicated from the batch script's own identically-named, identically-behaved helper, per this
    codebase's own established per-script-private-helper convention).
  - Never touches Telegram, never touches a worker, never publishes anything.
  - Offline fixtures (manifest kind="offline") never touch the DB at all - pure in-memory
    NewsEvent construction, exactly mirroring feature/r2-11-announcement-identity's own test
    fixtures (VK/Apple, Marvell/Google, the VK synthetic 4-publisher negative control).
  - A "db" fixture whose story_id does not exist in the current database is SKIPPED, not failed -
    this harness's own manifest explicitly documents it must not require every Story ID to exist
    in every developer database.

Run (deterministic only, the only mode this script has):
    docker compose run --rm --no-deps backend python scripts/_recap_r2_10_g3_eventness_harness.py

NOT EXECUTED against any production database this session - developer/local DB only, per this
phase's own explicit safety boundary.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from core.config import settings  # noqa: E402
from database.models.news_event import EventCategory, NewsEvent  # noqa: E402
from database.models.story import Story  # noqa: E402
from scripts._recap_r2_10_g3_eventness_manifest import MANIFEST, ManifestEntry, OfflineEvent  # noqa: E402
from scripts._recap_r2_shadow_batch import ShadowStoryReport, build_shadow_report  # noqa: E402
from services.recap_event import (  # noqa: E402
    cluster_announcements,
    count_unique_sources,
    evaluate_recap_readiness,
    evaluate_recap_story_integrity,
    load_story_events,
)
from services.recap_origin_projection import (  # noqa: E402
    build_effective_recap_members,
    resolve_recap_origin_projection,
)

STATEMENT_TIMEOUT_MS = 30_000
DEFAULT_OUTPUT_ROOT = Path("/tmp/r2_10_g3_eventness_runs")

_READY_LIKE_STATES = frozenset({"READY"})


class ReadOnlyGuardError(RuntimeError):
    """Duplicated from scripts/_recap_r2_shadow_batch.py's own identically-named, identically-
    behaved guard - see that module's own docstring for why this is deliberate duplication, not
    an import (a private, per-script helper convention already established in this codebase)."""


async def _verify_read_only(conn: AsyncConnection) -> None:
    await conn.execute(text("SET TRANSACTION READ ONLY"))
    result = await conn.execute(text("SHOW transaction_read_only"))
    value = str(result.scalar()).strip().lower()
    if value != "on":
        raise ReadOnlyGuardError(f"transaction_read_only={value!r}, expected 'on' - refusing to run")
    await conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}'"))


@dataclass(frozen=True)
class DeterministicFeatures:
    """Every field is a direct, unmodified read of an existing signal - never a new derived score.
    `match_type_distribution` is empty for offline fixtures (no Story Memory / NewsEventStoryLink
    involved in a pure in-memory fixture)."""

    effective_event_count: int
    announcement_count: int
    unique_source_count: int
    integrity_eligible: bool
    integrity_reasons: list[str]
    origin_projection_applied: bool
    story_span_hours: float | None
    source_domains: list[str]
    announcement_cluster_sizes: list[int]
    single_event_cluster_count: int
    multi_source_cluster_count: int
    match_type_distribution: dict[str, int]
    story_entities: list[str]
    story_keywords: list[str]
    story_topic_bucket: str | None


@dataclass(frozen=True)
class EventnessEvaluation:
    fixture_id: str
    kind: str
    manual_class: str
    desired_eventness: str
    manual_confidence: str
    manual_rationale: str
    story_id: str | None
    title: str
    existing_readiness_state: str | None  # None only when a "db" fixture was skipped (missing)
    existing_rejection_reasons: list[str]
    shadow_evaluation_status: str | None  # r212 OBSERVED/NEEDS_REVIEW/REJECTED passthrough, or None if skipped
    features: DeterministicFeatures | None
    disagreement_flags: list[str]
    skipped_reason: str | None = None


def _normalize_domain(url: str | None) -> str | None:
    from urllib.parse import urlsplit

    if not url:
        return None
    netloc = urlsplit(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc or None


def _features_from_events(events: list, clusters, integrity, origin_applied: bool) -> DeterministicFeatures:
    timestamps = [e.published_at or e.collected_at for e in events]
    span_hours = (max(timestamps) - min(timestamps)).total_seconds() / 3600 if len(timestamps) > 1 else 0.0
    domains = sorted({d for e in events if (d := _normalize_domain(e.url))})
    cluster_sizes = [len(c.event_ids) for c in clusters]
    return DeterministicFeatures(
        effective_event_count=len(events),
        announcement_count=len(clusters),
        unique_source_count=count_unique_sources(events),
        integrity_eligible=integrity.eligible,
        integrity_reasons=list(integrity.reasons),
        origin_projection_applied=origin_applied,
        story_span_hours=round(span_hours, 2),
        source_domains=domains,
        announcement_cluster_sizes=cluster_sizes,
        single_event_cluster_count=sum(1 for s in cluster_sizes if s == 1),
        multi_source_cluster_count=sum(1 for c in clusters if len(set(c.source_domains)) > 1),
        match_type_distribution={},  # filled in by the DB path only
        story_entities=[], story_keywords=[], story_topic_bucket=None,  # filled in by the DB path only
    )


async def _match_type_distribution(session: AsyncSession, story_id: UUID) -> dict[str, int]:
    rows = (await session.execute(
        text("select match_type, count(*) from news_event_story_links where story_id = :sid group by 1"),
        {"sid": story_id},
    )).all()
    return {str(match_type): int(count) for match_type, count in rows}


def _disagreement_flags(entry: ManifestEntry, readiness_state: str | None) -> list[str]:
    flags: list[str] = []
    if readiness_state is None:
        return flags
    current_ready = readiness_state in _READY_LIKE_STATES
    if current_ready and entry.desired_eventness == "REJECT":
        flags.append("CURRENT_READY_BUT_MANUAL_REJECT")
    if (not current_ready) and entry.desired_eventness == "ACCEPT":
        flags.append("CURRENT_REJECT_BUT_MANUAL_ACCEPT")
    return flags


async def evaluate_db_fixture(session: AsyncSession, entry: ManifestEntry, *, now: datetime) -> EventnessEvaluation:
    assert entry.story_id is not None
    story = await session.get(Story, uuid.UUID(entry.story_id))
    if story is None:
        return EventnessEvaluation(
            fixture_id=entry.fixture_id, kind="db", manual_class=entry.manual_class,
            desired_eventness=entry.desired_eventness, manual_confidence=entry.confidence,
            manual_rationale=entry.rationale, story_id=entry.story_id, title=entry.title_snapshot or "",
            existing_readiness_state=None, existing_rejection_reasons=[], shadow_evaluation_status=None,
            features=None, disagreement_flags=[], skipped_reason="story_id not found in this database",
        )

    report: ShadowStoryReport = await build_shadow_report(session, story, now=now)

    events = await load_story_events(session, story.id)
    anchor = next((e for e in events if e.id == story.first_event_id), None)
    origin_applied = False
    if anchor is None:
        origin_event, decision = await resolve_recap_origin_projection(session, story)
        if decision.eligible and origin_event is not None:
            anchor = origin_event
            events = build_effective_recap_members(origin_event, events)
            origin_applied = True

    if anchor is None:
        features = None
        readiness_state = report.candidate.readiness_state if report.candidate else "REJECTED"
    else:
        clusters = cluster_announcements(events)
        integrity = evaluate_recap_story_integrity(anchor, events)
        features = _features_from_events(events, clusters, integrity, origin_applied)
        features = dataclasses.replace(
            features,
            match_type_distribution=await _match_type_distribution(session, story.id),
            story_entities=list(story.entities or []), story_keywords=list(story.keywords or []),
            story_topic_bucket=story.topic_bucket,
        )
        readiness_state = report.candidate.readiness_state if report.candidate else "REJECTED"

    return EventnessEvaluation(
        fixture_id=entry.fixture_id, kind="db", manual_class=entry.manual_class,
        desired_eventness=entry.desired_eventness, manual_confidence=entry.confidence,
        manual_rationale=entry.rationale, story_id=entry.story_id, title=story.title,
        existing_readiness_state=readiness_state,
        existing_rejection_reasons=report.rejection_reasons,
        shadow_evaluation_status=report.evaluation.evaluation_status,
        features=features, disagreement_flags=_disagreement_flags(entry, readiness_state),
    )


def _offline_news_events(offline_events: tuple[OfflineEvent, ...], *, now: datetime) -> list[NewsEvent]:
    return [
        NewsEvent(
            id=uuid.uuid4(), source_id=uuid.uuid4(), title=e.title, category=EventCategory.TECH,
            url=e.url, published_at=now - timedelta(hours=e.hours_ago), collected_at=now - timedelta(hours=e.hours_ago),
            hash=f"g3a-offline-{uuid.uuid4()}",
        )
        for e in offline_events
    ]


def evaluate_offline_fixture(entry: ManifestEntry, *, now: datetime) -> EventnessEvaluation:
    events = _offline_news_events(entry.offline_events, now=now)
    anchor = events[0]
    clusters = cluster_announcements(events)
    integrity = evaluate_recap_story_integrity(anchor, events)
    features = _features_from_events(events, clusters, integrity, origin_applied=False)

    last_event_at = max(e.published_at or e.collected_at for e in events)
    readiness = evaluate_recap_readiness(
        event_count=len(events), announcement_count=len(clusters),
        unique_source_count=count_unique_sources(events), last_event_at=last_event_at, now=now,
        research_complete=True,  # isolated evaluation signal only, mirrors R2.11's own test convention - never set True in real production
        unresolved_conflict_count=0, story_integrity_eligible=integrity.eligible,
        story_integrity_reasons=integrity.reasons,
    )
    return EventnessEvaluation(
        fixture_id=entry.fixture_id, kind="offline", manual_class=entry.manual_class,
        desired_eventness=entry.desired_eventness, manual_confidence=entry.confidence,
        manual_rationale=entry.rationale, story_id=None, title=anchor.title,
        existing_readiness_state=readiness.state, existing_rejection_reasons=list(readiness.reasons),
        shadow_evaluation_status=None, features=features,
        disagreement_flags=_disagreement_flags(entry, readiness.state),
    )


def compute_metrics(evaluations: list[EventnessEvaluation]) -> dict[str, object]:
    """Pure. FALSE_ACCEPT = current readiness reads READY while manual ground truth says REJECT -
    the highest-priority metric per this phase's own instruction (a bad RECAP is worse than a
    missed marginal one). FALSE_REJECT = the inverse. NEEDS_REVIEW = manual label itself is
    NEEDS_REVIEW or UNCERTAIN - not a system disagreement, a genuinely open question."""
    scored = [e for e in evaluations if e.skipped_reason is None]
    false_accept = [e for e in scored if "CURRENT_READY_BUT_MANUAL_REJECT" in e.disagreement_flags]
    false_reject = [e for e in scored if "CURRENT_REJECT_BUT_MANUAL_ACCEPT" in e.disagreement_flags]
    needs_review = [e for e in scored if e.desired_eventness in ("NEEDS_REVIEW", "UNCERTAIN")]
    n = len(scored) or 1
    return {
        "evaluated_count": len(scored),
        "skipped_count": len(evaluations) - len(scored),
        "false_accept_count": len(false_accept), "false_accept_ids": [e.fixture_id for e in false_accept],
        "false_accept_rate": round(len(false_accept) / n, 3),
        "false_reject_count": len(false_reject), "false_reject_ids": [e.fixture_id for e in false_reject],
        "false_reject_rate": round(len(false_reject) / n, 3),
        "needs_review_count": len(needs_review), "needs_review_ids": [e.fixture_id for e in needs_review],
        "needs_review_rate": round(len(needs_review) / n, 3),
    }


class _EventnessJSONEncoder(json.JSONEncoder):
    def default(self, o: object) -> object:
        if isinstance(o, UUID):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


async def run_evaluation(*, now: datetime | None = None) -> tuple[list[EventnessEvaluation], dict[str, object]]:
    """The one entry point tests/other callers should use. `now=None` uses the real current time
    for offline fixtures' own readiness computation (irrelevant to their own manual label, which
    is fixed) - deterministic given a fixed `now`, exercised explicitly by the determinism test."""
    resolved_now = now or datetime.now(timezone.utc)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            await _verify_read_only(conn)
            session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
            evaluations = []
            for entry in MANIFEST:
                if entry.kind == "db":
                    evaluations.append(await evaluate_db_fixture(session, entry, now=resolved_now))
                else:
                    evaluations.append(evaluate_offline_fixture(entry, now=resolved_now))
        finally:
            await trans.rollback()
            await conn.close()
    finally:
        await engine.dispose()
    metrics = compute_metrics(evaluations)
    return evaluations, metrics


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", type=Path, default=None, help="output directory (default: /tmp/r2_10_g3_eventness_runs/<timestamp>/)")
    args = parser.parse_args()

    print("LLM_ENABLED=False (this script has no --with-llm argument - it never imports the Gateway)")

    evaluations, metrics = await run_evaluation()

    now = datetime.now(timezone.utc)
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / now.strftime("%Y%m%dT%H%M%SZ"))
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "eventness_evaluations.json").write_text(
        json.dumps([dataclasses.asdict(e) for e in evaluations], cls=_EventnessJSONEncoder, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "eventness_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print(f"Evaluated {metrics['evaluated_count']} fixtures ({metrics['skipped_count']} skipped).")
    print(f"FALSE_ACCEPT={metrics['false_accept_count']} FALSE_REJECT={metrics['false_reject_count']} NEEDS_REVIEW={metrics['needs_review_count']}")
    print(f"Wrote output to {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
