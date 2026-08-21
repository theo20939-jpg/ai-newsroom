"""NINJA PULSE RECAP - R2 Shadow, first canary. Manual, READ-ONLY, deterministic-only, multi-Story
full-evidence batch collector.

Design record (read before changing anything here): docs/r2_shadow_contract.md,
docs/r2_shadow_execution_plan.md, docs/r2_shadow_implementation_plan.md. This script is the
"minimal first canary" scoped and approved there - deterministic stage only, no synthesis, no
Telegram-shape generation (both explicitly deferred to a later, separately-reviewed canary).

WHAT THIS IS: for a bounded, recent set of Stories, build the real, deterministic
EventRecapCandidate (services/event_recap.py::build_event_recap_candidate(), unchanged, reused
directly) and write one JSON + one TXT report per Story, plus one aggregate shadow_summary.json for
the whole run - a scanning/reporting harness over architecture that already exists, never a new
one. `scripts/_recap_r2_10_readiness_candidate_scanner.py::scan_story_readiness()`/
`CandidateScanRow` (imported directly, not duplicated - the one legitimate cross-script import
here, since it is substantial existing evaluation logic, not a trivial helper) supplies the
Story-level readiness/origin-projection classification this script reuses unchanged.

SAFE BY DEFAULT (mirrors both existing R2 CLI scripts' own established discipline exactly):
  - This script has NO --with-llm argument anywhere in its parser - not a flag defaulting to off,
    an argument that does not exist. There is no code path in this file that can construct a
    Gateway request.
  - Never writes to the database (read-only transaction, verified and enforced -
    `_verify_read_only()` below is a direct, deliberate duplication of the sibling scripts' own
    identically-named, identically-behaved private helper - this codebase's own established
    per-script-private-helper convention, e.g. services/event_recap.py's own `_normalize_domain()`
    docstring cross-reference).
  - Never touches Telegram, never touches a worker, never publishes anything.
  - `--limit` has a bounded default and a hard ceiling - never an unbounded scan.

VISUAL INTEGRATION IS OBSERVATION-ONLY (owner correction, approval round): this script never
extends services/brand_renderer.py and never renders a RECAP post. It emits plain metadata fields
(media_candidate_count, media_spans_multiple_events, has_media, visual_checklist) - never a
template, never a `RecapVisual` implementation. See docs/r2_shadow_contract.md section 4.

EVALUATION VOCABULARY IS SHADOW-LOCAL (owner correction, approval round): `evaluation_status` is
OBSERVED / NEEDS_REVIEW / REJECTED - deliberately NOT services/fact_safety.py's pass/review/block
vocabulary. Shadow observation is a different concern from fact verification and must not silently
inherit its semantics or thresholds by reusing its words.

Run (deterministic only, the only mode this script has):
    docker compose run --rm --no-deps backend python scripts/_recap_r2_shadow_batch.py --limit 20

NOT EXECUTED by the author of this script - no VPS/production DB access this session.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from core.config import settings  # noqa: E402
from database.models.story import Story  # noqa: E402
from scripts._recap_r2_10_readiness_candidate_scanner import (  # noqa: E402
    CandidateScanRow, scan_story_readiness,
)
from services.event_recap import (  # noqa: E402
    EventRecapCandidate, build_event_recap_candidate, render_event_recap_bundle_text,
)

STATEMENT_TIMEOUT_MS = 30_000
DEFAULT_LIMIT = 20
MAX_LIMIT = 200  # a hard ceiling, independent of whatever --limit a human passes - never unbounded

DEFAULT_OUTPUT_ROOT = Path("/tmp/r2_shadow_runs")

# Fixed, static reviewer checklist (docs/r2_shadow_contract.md section 5) - shadow makes zero
# Telegram calls, so none of these can be code-verified; always emitted unchecked.
_VISUAL_CHECKLIST: tuple[str, ...] = (
    "mobile appearance",
    "desktop appearance (real message width, wallpaper visible)",
    "forwarded-message appearance (source button correctly absent - expected, not a defect)",
    "Telegram topics (if the editorial destination uses forum topics)",
    "button behavior in editorial chat vs. after forward",
)


class ReadOnlyGuardError(RuntimeError):
    """Raised if the read-only transaction guard cannot be verified - the script refuses to run
    any query in that case. Mirrors both sibling R2 scripts' own identically-named, identically-
    behaved guard exactly - deliberately duplicated, not imported (see module docstring)."""


async def _verify_read_only(conn: AsyncConnection) -> None:
    await conn.execute(text("SET TRANSACTION READ ONLY"))
    result = await conn.execute(text("SHOW transaction_read_only"))
    value = str(result.scalar()).strip().lower()
    if value != "on":
        raise ReadOnlyGuardError(f"transaction_read_only={value!r}, expected 'on' - refusing to run")
    await conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}'"))


@dataclass(frozen=True)
class ShadowVisualObservation:
    """Observation-only metadata - never a rendering (module docstring). Every field is a plain
    read of `EventRecapCandidate.media_candidates`, never a new relevance/quality judgment (the
    existing `services.image_persistence`/`services.video_discovery_persistence` machinery already
    decided that, upstream, before this candidate was ever built)."""

    media_candidate_count: int
    media_spans_multiple_events: bool
    has_media: bool
    visual_checklist: list[str]


@dataclass(frozen=True)
class ShadowEvaluation:
    evaluation_status: str  # "OBSERVED" | "NEEDS_REVIEW" | "REJECTED" - shadow-local vocabulary
    manual_review_required: bool
    quality_notes: list[str]
    visual: ShadowVisualObservation


@dataclass(frozen=True)
class ShadowStoryReport:
    """One Story's shadow observation. `candidate` is the real, complete, unmodified
    `EventRecapCandidate` (or `None` when the Story was rejected outright) - this script computes
    no candidate field of its own; `evaluation` is the one genuinely new piece (docs/
    r2_shadow_contract.md section 3)."""

    story_id: UUID
    title: str
    candidate: EventRecapCandidate | None
    rejection_reasons: list[str]
    evaluation: ShadowEvaluation


def _build_visual_observation(candidate: EventRecapCandidate) -> ShadowVisualObservation:
    event_ids = {m.event_id for m in candidate.media_candidates}
    return ShadowVisualObservation(
        media_candidate_count=len(candidate.media_candidates),
        media_spans_multiple_events=len(event_ids) > 1,
        has_media=bool(candidate.media_candidates),
        visual_checklist=list(_VISUAL_CHECKLIST),
    )


def _empty_visual_observation() -> ShadowVisualObservation:
    return ShadowVisualObservation(
        media_candidate_count=0, media_spans_multiple_events=False, has_media=False,
        visual_checklist=list(_VISUAL_CHECKLIST),
    )


def _compute_quality_notes(candidate: EventRecapCandidate, visual: ShadowVisualObservation) -> list[str]:
    """Plain, deterministic strings only - never a synthetic score (mirrors
    `EventRecapCandidate.quality_flags`'s own established shape, reused, not reinvented)."""
    notes: list[str] = []
    if not visual.has_media:
        notes.append("media_candidates empty")
    if visual.media_spans_multiple_events:
        notes.append(
            "media spans multiple distinct events - possible anchor mismatch (R2.10 Night 2 Phase 19, unresolved)"
        )
    if candidate.announcement_count > 1:
        notes.append(
            "announcement_count reflects raw report-level clusters, not confirmed distinct "
            "developments - see docs/r2_11_announcement_identity_findings.md"
        )
    return notes


def _compute_evaluation_status(row: CandidateScanRow, quality_notes: list[str]) -> str:
    """Shadow-local vocabulary (owner correction, approval round) - deliberately NOT
    services/fact_safety.py's pass/review/block. `REJECTED` maps to a Story that never produced a
    candidate at all; `NEEDS_REVIEW` maps to the scanner's own existing manual-review signal OR any
    non-empty quality note; `OBSERVED` is the default otherwise."""
    if row.readiness_state == "REJECTED":
        return "REJECTED"
    if row.recommended_for_manual_review or quality_notes:
        return "NEEDS_REVIEW"
    return "OBSERVED"


async def build_shadow_report(session: AsyncSession, story: Story, *, now: datetime) -> ShadowStoryReport:
    """Reuses `scan_story_readiness()` (Story-level readiness/origin-projection classification,
    unchanged) and `build_event_recap_candidate()` (the full candidate, unchanged) - computes no
    readiness, clustering, or integrity logic of its own. Evaluates a Story twice when a candidate
    exists (once inside `scan_story_readiness()`, once directly here) - a deliberate trade-off: a
    handful of extra read-only queries per Story, bounded by this script's own small `--limit`, in
    exchange for zero duplicated evaluation logic (docs/r2_shadow_implementation_plan.md section 2)."""
    row = await scan_story_readiness(session, story, now=now)
    if row.readiness_state == "REJECTED":
        return ShadowStoryReport(
            story_id=story.id, title=story.title, candidate=None,
            rejection_reasons=row.rejection_reasons,
            evaluation=ShadowEvaluation(
                evaluation_status="REJECTED", manual_review_required=False, quality_notes=[],
                visual=_empty_visual_observation(),
            ),
        )

    result = await build_event_recap_candidate(session, story, force_shadow=True, now=now)
    assert result.candidate is not None  # row already proved a candidate builds for this Story
    candidate = result.candidate
    visual = _build_visual_observation(candidate)
    quality_notes = _compute_quality_notes(candidate, visual)
    evaluation_status = _compute_evaluation_status(row, quality_notes)
    return ShadowStoryReport(
        story_id=story.id, title=story.title, candidate=candidate, rejection_reasons=[],
        evaluation=ShadowEvaluation(
            evaluation_status=evaluation_status, manual_review_required=row.recommended_for_manual_review,
            quality_notes=quality_notes, visual=visual,
        ),
    )


def build_shadow_summary(reports: list[ShadowStoryReport]) -> dict[str, object]:
    """Pure. Deterministic counts only - never a numeric score (mirrors
    `scripts/_recap_r2_10_readiness_candidate_scanner.py::rank_rows()`'s own "no scoring"
    discipline)."""
    rejection_reasons_distribution: dict[str, int] = {}
    readiness_states_distribution: dict[str, int] = {}
    candidate_count = 0
    for report in reports:
        if report.candidate is None:
            for reason in report.rejection_reasons:
                rejection_reasons_distribution[reason] = rejection_reasons_distribution.get(reason, 0) + 1
        else:
            candidate_count += 1
            state = report.candidate.readiness_state
            readiness_states_distribution[state] = readiness_states_distribution.get(state, 0) + 1
    return {
        "scanned_count": len(reports),
        "candidate_count": candidate_count,
        "rejection_reasons_distribution": rejection_reasons_distribution,
        "readiness_states_distribution": readiness_states_distribution,
    }


class _ShadowJSONEncoder(json.JSONEncoder):
    def default(self, o: object) -> object:
        if isinstance(o, UUID):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


def _write_story_report(output_dir: Path, report: ShadowStoryReport) -> None:
    json_path = output_dir / f"story_{report.story_id}.json"
    json_path.write_text(
        json.dumps(dataclasses.asdict(report), cls=_ShadowJSONEncoder, indent=2), encoding="utf-8",
    )

    txt_path = output_dir / f"story_{report.story_id}.txt"
    if report.candidate is not None:
        txt_content = render_event_recap_bundle_text(report.candidate)
    else:
        txt_content = (
            f"Story: {report.title}\n"
            f"evaluation_status: REJECTED\n"
            f"rejection_reasons: {report.rejection_reasons}\n"
        )
    txt_path.write_text(txt_content, encoding="utf-8")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"max Stories to scan (default {DEFAULT_LIMIT}, hard ceiling {MAX_LIMIT})")
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="output directory (default: /tmp/r2_shadow_runs/<timestamp>/)",
    )
    args = parser.parse_args()

    if args.limit < 1 or args.limit > MAX_LIMIT:
        print(f"--limit must be between 1 and {MAX_LIMIT}, got {args.limit}", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / now.strftime("%Y%m%dT%H%M%SZ"))
    output_dir.mkdir(parents=True, exist_ok=True)

    # Runtime-visible proof, printed before any DB access, regardless of outcome - unambiguous for
    # both a human reading stdout and an automated check grepping for this exact line.
    print("LLM_ENABLED=False (this script has no --with-llm argument - it never imports the Gateway)")

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            await _verify_read_only(conn)
            session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)

            stories = (
                await session.execute(select(Story).order_by(Story.updated_at.desc()).limit(args.limit))
            ).scalars().all()

            reports = [await build_shadow_report(session, story, now=now) for story in stories]
        finally:
            await trans.rollback()
            await conn.close()
    finally:
        await engine.dispose()

    for report in reports:
        _write_story_report(output_dir, report)

    summary = build_shadow_summary(reports)
    (output_dir / "shadow_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Scanned {summary['scanned_count']} Stories, {summary['candidate_count']} candidates built.")
    print(f"Wrote output to {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
