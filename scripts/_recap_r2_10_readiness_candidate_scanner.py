"""NINJA PULSE RECAP Phase R2.10 Night 2 - manual, READ-ONLY readiness candidate scanner.

Answers one question, deterministically and offline: "of a bounded set of recent Stories, which
ones are worth a human looking at as a candidate for the first controlled paid EVENT_RECAP
synthesis?" - never a scheduler, never a worker, never production activation. A human runs this by
hand, reads the output, and makes the actual selection themselves (services/event_recap.py's own
build_event_recap_candidate() is the only thing this script calls to answer that question - no new
scoring architecture, no new algorithm, no threshold of its own).

SAFE BY DEFAULT (mirrors scripts/_recap_r2_event_shadow.py's own established discipline exactly):
  - Zero LLM/Gateway calls, zero network access, zero cost - this script has no --with-llm flag at
    all, unlike its sibling script; it never imports integrations.llm_gateway.* anywhere.
  - Never writes to the database (read-only transaction, verified and enforced - `_verify_read_only()`
    below is a direct, deliberate duplication of the sibling script's own private helper - this
    codebase's own established per-script-private-helper convention, e.g. services/event_recap.py's
    own `_normalize_domain()` docstring cross-reference).
  - Never touches Telegram, never touches a worker, never publishes anything.
  - `--limit` is required to have a bounded default (never an unbounded scan).

Ranking discipline (spec's own explicit "prefer filtering/grouping over opaque scoring"): this
script computes NO numeric score. It reuses build_event_recap_candidate()'s own existing,
already-frozen-or-R2-owned semantics UNCHANGED and simply reports what they already say - grouped
by `readiness_state`, most-actionable first (READY, then COOLING, then ACTIVE, then DISCOVERED,
then integrity-rejected/anchor-rejected last). No new threshold, weight, or algorithm anywhere in
this file.

Run (deterministic only, the only mode this script has):
    docker compose run --rm --no-deps backend python scripts/_recap_r2_10_readiness_candidate_scanner.py --limit 20

NOT EXECUTED by the author of this script - no VPS/production DB access this session.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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
from services.recap_eventness_shadow import EventnessShadowEvaluation  # noqa: E402
from services.recap_origin_projection import ORIGIN_PROJECTION_NOT_NEEDED, resolve_recap_origin_projection  # noqa: E402

STATEMENT_TIMEOUT_MS = 30_000
DEFAULT_LIMIT = 20
MAX_LIMIT = 200  # a hard ceiling, independent of whatever --limit a human passes - never unbounded

# Most-actionable first - a fixed, explicit ordering (never a numeric score) mirroring
# services/recap_event.py's own DISCOVERED/ACTIVE/COOLING/READY state names verbatim.
_STATE_RANK = {"READY": 0, "COOLING": 1, "ACTIVE": 2, "DISCOVERED": 3, "REJECTED": 4}


class ReadOnlyGuardError(RuntimeError):
    """Raised if the read-only transaction guard cannot be verified - the script refuses to run
    any query in that case. Mirrors scripts/_recap_r2_event_shadow.py's own identically-named,
    identically-behaved guard exactly - deliberately duplicated, not imported (see module
    docstring)."""


async def _verify_read_only(conn: AsyncConnection) -> None:
    await conn.execute(text("SET TRANSACTION READ ONLY"))
    result = await conn.execute(text("SHOW transaction_read_only"))
    value = str(result.scalar()).strip().lower()
    if value != "on":
        raise ReadOnlyGuardError(f"transaction_read_only={value!r}, expected 'on' - refusing to run")
    await conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}'"))


@dataclass(frozen=True)
class CandidateScanRow:
    """One Story's deterministic, read-only EVENT_RECAP readiness snapshot - every field is a
    direct, unmodified read of an existing signal (build_event_recap_candidate()/
    resolve_recap_origin_projection()), never a new derived score."""

    story_id: UUID
    title: str
    event_count: int
    origin_projection_status: str  # "not_needed" | "applied" | "ineligible:<reason_code>"
    story_integrity_eligible: bool | None  # None only when rejected before integrity was ever computed
    announcement_count: int | None
    readiness_source_count: int | None
    readiness_state: str  # DISCOVERED/ACTIVE/COOLING/READY, or "REJECTED" when candidate is None
    rejection_reasons: list[str]
    research_complete_tracked: bool  # always False - see docstring: this signal is not persisted anywhere
    recommended_for_manual_review: bool
    # R2.10G3-E1 (§19): SHADOW-ONLY diagnostic, carried through verbatim from
    # EventRecapCandidate.eventness_shadow - None unless settings.recap_eventness_shadow_enabled
    # is True (default False everywhere) or the candidate itself is None. Never influences
    # `readiness_state`/`rejection_reasons`/`recommended_for_manual_review` above - those are all
    # already fully computed before this field is populated.
    eventness_shadow: EventnessShadowEvaluation | None = None


async def scan_story_readiness(session: AsyncSession, story: Story, *, now: datetime) -> CandidateScanRow:
    """Pure orchestration over already-existing, already-frozen-or-R2-owned functions - computes
    nothing new. `research_complete_tracked` is unconditionally `False`: no column or table in
    this schema currently persists a "recap research complete" signal for any Story (confirmed by
    inspection - services/event_recap.py's own `research_complete` parameter, Phase R2.10A.3, is
    caller-supplied per call, never stored) - reported honestly as untracked rather than guessed."""
    confirmed = await load_story_events(session, story.id)
    _origin_event, projection_decision = await resolve_recap_origin_projection(session, story)
    origin_projection_status = (
        "not_needed" if projection_decision.reason_code == ORIGIN_PROJECTION_NOT_NEEDED
        else "applied" if projection_decision.eligible
        else f"ineligible:{projection_decision.reason_code}"
    )

    result = await build_event_recap_candidate(session, story, force_shadow=True, now=now)
    if result.candidate is None:
        return CandidateScanRow(
            story_id=story.id, title=story.title, event_count=len(confirmed),
            origin_projection_status=origin_projection_status, story_integrity_eligible=None,
            announcement_count=None, readiness_source_count=None, readiness_state="REJECTED",
            rejection_reasons=result.rejection_reasons, research_complete_tracked=False,
            recommended_for_manual_review=False,
        )

    # candidate is not None here => story_integrity_eligible is always True (an integrity FAIL
    # always rejects outright above, regardless of force_shadow) - c.readiness_state alone
    # (DISCOVERED/ACTIVE/COOLING/READY) already conveys how close to natural READY this Story is;
    # for the exact blocking reasons on a specific Story, the operator's next step is the sibling
    # single-Story script (scripts/_recap_r2_event_shadow.py --story-id <id>), which already prints
    # them in full - this scanner's own job is triage/ranking across MANY Stories, not full detail
    # for one (Phase R2.10 Night 2 runbook's own explicit "scanner -> shortlist -> human evidence
    # inspection" division of labor).
    c = result.candidate
    return CandidateScanRow(
        story_id=story.id, title=story.title, event_count=len(confirmed),
        origin_projection_status=origin_projection_status,
        story_integrity_eligible=c.story_integrity_eligible,
        announcement_count=c.announcement_count, readiness_source_count=c.readiness_source_count,
        readiness_state=c.readiness_state, rejection_reasons=[], research_complete_tracked=False,
        recommended_for_manual_review=(c.story_integrity_eligible and c.readiness_state in ("READY", "COOLING")),
        eventness_shadow=c.eventness_shadow,
    )


def rank_rows(rows: list[CandidateScanRow]) -> list[CandidateScanRow]:
    """Deterministic sort only - never a numeric score (module docstring). Most-actionable
    readiness_state first, ties broken by higher announcement_count, then by story_id for a total
    order."""
    return sorted(
        rows,
        key=lambda r: (
            _STATE_RANK.get(r.readiness_state, 99),
            -(r.announcement_count or 0),
            str(r.story_id),
        ),
    )


class _ScanJSONEncoder(json.JSONEncoder):
    def default(self, o: object) -> object:
        if isinstance(o, UUID):
            return str(o)
        return super().default(o)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"max Stories to scan (default {DEFAULT_LIMIT}, hard ceiling {MAX_LIMIT})")
    parser.add_argument("--output", type=Path, default=None, help="JSON output path (default: print to stdout only)")
    args = parser.parse_args()

    if args.limit < 1 or args.limit > MAX_LIMIT:
        print(f"--limit must be between 1 and {MAX_LIMIT}, got {args.limit}", file=sys.stderr)
        return 2

    print("LLM_ENABLED=False (this script has no --with-llm flag - it never imports the Gateway)")

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            await _verify_read_only(conn)
            session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
            now = datetime.now(timezone.utc)

            stories = (
                await session.execute(select(Story).order_by(Story.updated_at.desc()).limit(args.limit))
            ).scalars().all()

            rows = [await scan_story_readiness(session, story, now=now) for story in stories]
        finally:
            await trans.rollback()
            await conn.close()
    finally:
        await engine.dispose()

    ranked = rank_rows(rows)
    print(f"Scanned {len(ranked)} Stories (limit={args.limit}).")
    for row in ranked:
        marker = "***" if row.recommended_for_manual_review else "   "
        print(
            f"{marker} {row.readiness_state:10s} events={row.event_count:3d} "
            f"announcements={row.announcement_count} sources={row.readiness_source_count} "
            f"origin={row.origin_projection_status:30s} {row.story_id} {row.title[:70]!r}"
        )

    if args.output:
        payload = [asdict(row) for row in ranked]
        args.output.write_text(json.dumps(payload, cls=_ScanJSONEncoder, indent=2), encoding="utf-8")
        print(f"Wrote {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
