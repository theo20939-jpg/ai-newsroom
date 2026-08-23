"""NINJA PULSE RECAP Phase R2 - read-only Story candidate scan for shadow synthesis testing.

Scans the most recently created Stories in the real database and, for each one, runs the exact
same deterministic R2 pipeline every other R2 diagnostic already uses -
`services.recap_event.load_story_events()` (confirmed-member loading, FROZEN, reused unchanged)
and `services.event_recap.build_event_recap_candidate()` (Story Integrity Gate, announcement
clustering via R1's own `cluster_announcements()`, readiness) - never a hand-rolled reimplementation
of clustering, and never a raw `SELECT COUNT(*) FROM news_events` substitute for either
`event_count` or `announcement_count`. Reports which real Stories are the richest, most
structurally interesting candidates for a manual `--with-llm` shadow synthesis run via
scripts/_recap_r2_event_shadow.py.

SAFE BY DEFAULT (mirrors scripts/_recap_r2_event_shadow.py's own guarantees, same guard, same
overall shape):
  - Zero LLM/Gateway calls, zero network access anywhere in this script - `load_story_events()`
    and `build_event_recap_candidate()` are both pure, deterministic reads/computations (the
    latter's own docstring: "exactly as safe to call as any R1 diagnostic").
  - `force_shadow=True` is passed to every `build_event_recap_candidate()` call (module purpose:
    surfacing rich candidates for a LATER manual shadow test, not gating on live readiness) -
    `EventRecapCandidate.readiness_overridden` on each result already records whenever this
    happened; no other readiness/threshold/clustering constant is touched.
  - Never writes to the database - the entire scan runs inside ONE read-only transaction
    (`_verify_read_only()`, the exact same guard `scripts/_recap_r2_event_shadow.py` already uses),
    explicitly `ROLLBACK`ed (never committed) once the scan finishes, regardless of outcome.
  - No migrations, no schema changes, no architecture changes - reuses the existing R2 pipeline
    entry points exactly as every other caller does; this file only ranks and prints their output.

Run (read-only, no LLM, no cost):
    docker compose run --rm --no-deps backend python scripts/_recap_r2_story_candidate_scan.py --limit 20
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from core.config import settings  # noqa: E402
from database.models.story import Story  # noqa: E402
from services.event_recap import build_event_recap_candidate  # noqa: E402
from services.recap_event import load_story_events  # noqa: E402

STATEMENT_TIMEOUT_MS = 30_000
DEFAULT_SCAN_LIMIT = 200
DEFAULT_REPORT_LIMIT = 20


class ReadOnlyGuardError(RuntimeError):
    """Raised if the read-only transaction guard cannot be verified - the script refuses to run
    any query in that case (same guard/behavior as scripts/_recap_r2_event_shadow.py)."""


async def _verify_read_only(conn: AsyncConnection) -> None:
    await conn.execute(text("SET TRANSACTION READ ONLY"))
    result = await conn.execute(text("SHOW transaction_read_only"))
    value = str(result.scalar()).strip().lower()
    if value != "on":
        raise ReadOnlyGuardError(f"transaction_read_only={value!r}, expected 'on' - refusing to run")
    await conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}'"))


@dataclass(frozen=True)
class CandidateRow:
    """One scanned Story's diagnostic summary - a presentation-only shape local to this script,
    never a production dataclass and never persisted anywhere."""

    story_id: UUID
    title: str
    event_count: int
    announcement_count: int | None
    readiness_state: str | None
    readiness_source_count: int | None
    evidence_reference_count: int | None
    integrity_status: str
    rejection_reason: str | None


def _sort_key(row: CandidateRow) -> tuple[int, int]:
    """Primary: announcement_count DESC. Secondary: event_count DESC (ties within the same
    announcement_count). Rejected rows (no candidate at all, announcement_count=None) sort last -
    a Story build_event_recap_candidate() rejected outright is never a usable shadow-synthesis
    candidate, regardless of its raw event_count."""
    return (row.announcement_count if row.announcement_count is not None else -1, row.event_count)


async def _scan_story(session: AsyncSession, story: Story) -> CandidateRow:
    """One Story through the real pipeline: `load_story_events()` for the confirmed-member
    `event_count` (never a SQL COUNT(*) substitute), then `build_event_recap_candidate()` for
    everything clustering/readiness/integrity-derived - never recomputed by hand here."""
    events = await load_story_events(session, story.id)
    result = await build_event_recap_candidate(session, story, force_shadow=True)

    if result.rejected or result.candidate is None:
        return CandidateRow(
            story_id=story.id, title=story.title, event_count=len(events),
            announcement_count=None, readiness_state=None, readiness_source_count=None,
            evidence_reference_count=None, integrity_status="rejected",
            rejection_reason="; ".join(result.rejection_reasons) or None,
        )

    candidate = result.candidate
    return CandidateRow(
        story_id=story.id, title=story.title, event_count=len(events),
        announcement_count=candidate.announcement_count, readiness_state=candidate.readiness_state,
        readiness_source_count=candidate.readiness_source_count,
        evidence_reference_count=candidate.evidence_reference_count,
        integrity_status="eligible" if candidate.story_integrity_eligible else "ineligible",
        rejection_reason=None,
    )


def _print_report(rows: list[CandidateRow], report_limit: int) -> None:
    top = sorted(rows, key=_sort_key, reverse=True)[:report_limit]
    header = (
        f"{'story_id':<36} {'events':>6} {'announce':>8} {'readiness':<10} "
        f"{'src':>4} {'evid':>4} {'integrity':<10} title"
    )
    print(header)
    print("-" * len(header))
    for row in top:
        print(
            f"{str(row.story_id):<36} {row.event_count:>6} "
            f"{row.announcement_count if row.announcement_count is not None else '-':>8} "
            f"{row.readiness_state or '-':<10} "
            f"{row.readiness_source_count if row.readiness_source_count is not None else '-':>4} "
            f"{row.evidence_reference_count if row.evidence_reference_count is not None else '-':>4} "
            f"{row.integrity_status:<10} "
            f"{row.title[:80]}"
        )
        if row.rejection_reason:
            print(f"    rejection_reason: {row.rejection_reason}")


async def _run(scan_limit: int, report_limit: int) -> int:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            await _verify_read_only(conn)
            session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)

            stmt = select(Story).order_by(Story.created_at.desc()).limit(scan_limit)
            stories = (await session.execute(stmt)).scalars().all()
            print(f"Scanning {len(stories)} most recent Story rows (scan_limit={scan_limit})...")

            rows = [await _scan_story(session, story) for story in stories]
        finally:
            # Always rolled back, never committed - this script never persists anything, success
            # or failure alike (module docstring's own "never writes to the database" guarantee).
            await trans.rollback()
            await conn.close()
    finally:
        await engine.dispose()

    print(
        f"\nTOP {report_limit} R2 shadow-synthesis candidates "
        f"(sorted by announcement_count DESC, event_count DESC):\n"
    )
    _print_report(rows, report_limit)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_REPORT_LIMIT,
        help=f"Number of top candidates to print in the final report (default: {DEFAULT_REPORT_LIMIT}).",
    )
    parser.add_argument(
        "--scan-limit", type=int, default=DEFAULT_SCAN_LIMIT,
        help=f"Number of most recent Story rows to scan before ranking (default: {DEFAULT_SCAN_LIMIT}).",
    )
    args = parser.parse_args()
    return asyncio.run(_run(scan_limit=args.scan_limit, report_limit=args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
