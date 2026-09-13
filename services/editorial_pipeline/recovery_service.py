"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-CUTOVER-1 (S8/S9): the real, durable RecoveryService.

The Founder review of the prior UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 phase found the recovery
state machine "partly aspirational rather than executable": `apply_telegram_recovery()` had zero
runtime callers, `RETRYING`/`RECOVERED` were never reached, several reason codes were never
produced, `next_retry_at` did not exist as a field. This module is the fix - a real, tested state
machine backed by the durable `database.models.recovery_job.RecoveryJob` table (added this phase,
migration `a126e750c727`), with real callers wired from `services.editorial_pipeline.orchestrator`
and `worker.content_cycle` (see `docs/unified_editorial_production_pipeline_cutover_1_report.md`
for the exact call sites).

State machine (mirrors `database.models.recovery_job.RecoveryJobState` exactly - this module never
defines a second, competing enum):

    PENDING     - the first failure for this (content_draft_id) has been recorded; a first retry
                  has been scheduled (`next_retry_at` set) but not yet attempted.
    RETRYING    - at least one retry has already been attempted and ALSO failed; another retry is
                  scheduled (`next_retry_at` set again, per the bounded backoff schedule below).
    RECOVERED   - a later attempt for the same draft succeeded (`mark_recovered()` was called).
    TERMINAL_HOLD - `attempt_count >= max_attempts`; no further retry is ever scheduled
                  (`next_retry_at` stays `None` from this point on) - bounded, never infinite.

`create_or_retry()` is the one entry point for every real failure site (S9's own required reason
codes: NO_SUITABLE_MEDIA, MEDIA_RESEARCH_TIMEOUT, MEDIA_SEND_FAILED, AMBIGUOUS_TRANSPORT_RESULT,
CAPTION_BUDGET_FAILED, RENDER_FAILED, QUALITY_GATE_FAILED) - it looks up any already-open recovery
row for this draft (`find_open_recovery()`) and either increments it (a genuine retry, unlike the
prior phase's own `create_recovery_job()`, which "always constructs a job with attempt_count=1,
hardcoded" per that phase's own disclosed gap) or creates a fresh PENDING row.

`QUALITY_GATE_FAILED` is deliberately NOT bounded-retried by this service in practice - the
orchestrator (S25/orchestrator.py) passes `max_attempts=1` for it, so it reaches TERMINAL_HOLD (via
this same real state machine, not a special case) on its very first failure: a quality/safety
verdict does not change on a blind retry of unchanged content, and the orchestrator surfaces it to
the worker as `OrchestratorVerdict.BLOCK`, never `RETRY` (see `orchestrator.py`'s own mapping).

UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-FINAL-HARDENING-1: `AMBIGUOUS_TRANSPORT_RESULT` receives the
SAME always-terminal-on-first-occurrence treatment as `QUALITY_GATE_FAILED` - but enforced HERE,
centrally, inside `create_or_retry()` itself (`_ALWAYS_TERMINAL_ON_FIRST_FAILURE_REASON_CODES`
below), not merely by a caller remembering to pass `max_attempts=1`. This is the Founder-mandated
fix for "duplicate published post is worse than a HOLD": an ambiguous Telegram result means this
service cannot prove whether Telegram already accepted the post, so bounded-retry semantics (which
exist precisely to let a transient, DEFINITELY-failed-before-acceptance error be tried again) must
never apply - the row goes straight to `TERMINAL_HOLD`, `next_retry_at=None`, on the very FIRST
occurrence, regardless of what `max_attempts` value any caller (present or future) supplies. Since
`find_open_recovery()` only ever returns `PENDING`/`RETRYING` rows, a `TERMINAL_HOLD` row is
structurally invisible to any retry-consumer, present or future (S9/S12: "generic retry processing
CANNOT automatically resend it... require reconciliation/operator decision"). No new migration, no
new state, no second retry subsystem - the existing state machine already expresses this safely.

Durable by construction (S9: "do not pretend an in-memory state machine is durable"): every method
here takes an explicit `AsyncSession` and calls only `session.add()`/`session.flush()` - it never
commits (the caller's own `async with session_factory() as session: ... await session.commit()`
convention, matching every other write path in this codebase, e.g. `worker/content_cycle.py`'s own
`_hold_for_visual_recovery()`) and never holds a session across calls, so a fresh `RecoveryService()`
instance after a worker restart/process death sees exactly the same durable state a pre-restart
instance would have (S20's own explicit "persisted recovery state remains recoverable" requirement)
- proven by `tests/test_unified_pipeline_recovery_service.py::
test_persisted_state_survives_a_fresh_service_instance_after_a_simulated_restart`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.recovery_job import RecoveryJob as RecoveryJobRow
from database.models.recovery_job import RecoveryJobState
from database.models.recovery_job import RecoveryPlatform as DBRecoveryPlatform
from database.models.recovery_job import RecoveryReasonCode as DBRecoveryReasonCode
from services.editorial_pipeline.contracts import Platform, RecoveryReasonCode

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 3
"""The durable service's own bounded retry budget (distinct from the pre-existing in-process
`services.editorial_pipeline.recovery.DEFAULT_MAX_ATTEMPTS = 1`, which that module's own docstring
already ties to the TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1 precedent of zero extra attempts -
that module is untouched by this phase and keeps its own, separate default). 3 gives a real,
observable RETRYING window (PENDING -> RETRYING -> RETRYING -> TERMINAL_HOLD) before this phase's
own required "max attempts exhausted -> TERMINAL_HOLD" test can exercise it, while still bounded -
never unbounded, never a loop inside this service itself (the caller/a future scheduler decides
WHEN to actually retry, honoring `next_retry_at` - this service only ever computes and persists it,
per the same "renderer does layout, not policy" discipline the rest of this pipeline already uses).
"""

_BACKOFF_SCHEDULE_SECONDS: tuple[int, ...] = (60, 300, 900)
"""Deterministic, no jitter - attempt 1's retry is scheduled 60s out, attempt 2's 300s out, attempt
3's (and beyond, if `max_attempts` is ever raised past 3) 900s out. A test can assert the exact
`next_retry_at` rather than merely "some future time"."""

_PLATFORM_TO_DB: dict[Platform, DBRecoveryPlatform] = {
    Platform.TELEGRAM: DBRecoveryPlatform.TELEGRAM,
    Platform.INSTAGRAM: DBRecoveryPlatform.INSTAGRAM,
}
_REASON_TO_DB: dict[RecoveryReasonCode, DBRecoveryReasonCode] = {
    code: DBRecoveryReasonCode(code.value) for code in RecoveryReasonCode
}


def _next_retry_delay_seconds(attempt_count: int) -> int:
    index = min(max(attempt_count - 1, 0), len(_BACKOFF_SCHEDULE_SECONDS) - 1)
    return _BACKOFF_SCHEDULE_SECONDS[index]


_ALWAYS_TERMINAL_ON_FIRST_FAILURE_REASON_CODES = frozenset({
    RecoveryReasonCode.QUALITY_GATE_FAILED,
    RecoveryReasonCode.AMBIGUOUS_TRANSPORT_RESULT,
})
"""FINAL-HARDENING-1: reason codes this service itself forces to `max_attempts=1` (terminal on
first occurrence), regardless of the `max_attempts` value any caller passes. `QUALITY_GATE_FAILED`
already got this treatment from `orchestrator.py`'s own caller-side `max_attempts=1`; enforcing it
here too makes that defense-in-depth rather than the only guard. `AMBIGUOUS_TRANSPORT_RESULT` is
the new, Founder-mandated addition - see the module docstring's own "duplicate published post is
worse than a HOLD" reasoning. This set is deliberately narrow and explicit - it is never inferred
from a "looks risky" heuristic, only these two named, reviewed reason codes."""


class RecoveryService:
    """Stateless (holds no per-call state of its own - safe to construct fresh per call, per
    request, or once per process; every method takes its own `session` explicitly, matching this
    codebase's own `async with session_factory() as session:` convention rather than the service
    holding a session across calls)."""

    async def find_open_recovery(
        self, session: AsyncSession, *, content_draft_id: UUID, platform: Platform | None = None,
    ) -> RecoveryJobRow | None:
        """'(content_draft_id, platform, state)' is the meaningful lookup (RUNTIME-CLOSURE-1 S22 -
        the model's own docstring previously said `(content_draft_id, state)`, which was the actual
        Founder audit gap: a Telegram recovery lookup could accidentally return/reuse an Instagram
        recovery row for the SAME draft, since both platforms can recover the same underlying
        `ContentDraft`). 'open' means not yet resolved (`RECOVERED`/`TERMINAL_HOLD`).

        `platform=None` preserves the old, unscoped lookup for any caller that has a genuine reason
        to look across platforms (none exists in this codebase today - kept only so this is an
        additive, backward-compatible signature change, not a breaking one). Every real call site
        in this module (`create_or_retry()`) always passes a real `platform` now - see there.

        The most recently created open row is returned when more than one somehow exists (should
        not happen in practice for a given (content_draft_id, platform) pair - the DB-level partial
        unique index `ix_recovery_jobs_open_lifecycle_identity` (§23) makes this structurally
        enforced going forward, not merely a convention)."""
        stmt = (
            select(RecoveryJobRow)
            .where(RecoveryJobRow.content_draft_id == content_draft_id)
            .where(RecoveryJobRow.state.in_((RecoveryJobState.PENDING, RecoveryJobState.RETRYING)))
        )
        if platform is not None:
            stmt = stmt.where(RecoveryJobRow.platform == _PLATFORM_TO_DB[platform])
        stmt = stmt.order_by(RecoveryJobRow.created_at.desc())
        result = await session.execute(stmt)
        return result.scalars().first()

    async def get(self, session: AsyncSession, *, recovery_job_id: UUID) -> RecoveryJobRow | None:
        return await session.get(RecoveryJobRow, recovery_job_id)

    async def create_or_retry(
        self,
        session: AsyncSession,
        *,
        content_draft_id: UUID,
        platform: Platform,
        reason_code: RecoveryReasonCode,
        failed_stage: str,
        last_error: str | None = None,
        candidate_diagnostics: list[str] | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        now: datetime | None = None,
    ) -> RecoveryJobRow:
        """The one real entry point for every failure site (S9). Increments an existing open job
        in place (a genuine retry - the exact gap the Founder review flagged as missing:
        "no mechanism anywhere... that takes an EXISTING RecoveryJob, increments its attempt_count,
        and re-evaluates it") rather than always constructing attempt_count=1 from scratch.

        FINAL-HARDENING-1: `effective_max_attempts` overrides the caller-supplied `max_attempts` to
        `1` whenever `reason_code` is in `_ALWAYS_TERMINAL_ON_FIRST_FAILURE_REASON_CODES` - this is
        a service-level invariant, not a per-caller convention, so it holds even for a caller that
        forgets (or a future caller that does not yet exist) to pass `max_attempts=1` itself. When
        an EXISTING open row (created under a different, bounded-retry reason code) receives a NEW
        failure whose reason code is in that set, the row is forced terminal immediately on this
        very call, regardless of its own prior `attempt_count`/`max_attempts` history."""
        now = now or datetime.now(timezone.utc)
        db_reason = _REASON_TO_DB[reason_code]
        diagnostics = list(candidate_diagnostics or [])
        last_error_summary = (last_error or "")[:500] or None
        effective_max_attempts = 1 if reason_code in _ALWAYS_TERMINAL_ON_FIRST_FAILURE_REASON_CODES else max_attempts

        def _increment(row: RecoveryJobRow) -> RecoveryJobRow:
            row.attempt_count += 1
            row.reason_code = db_reason
            row.failed_stage = failed_stage
            row.last_error_summary = last_error_summary
            row.candidate_diagnostics = diagnostics
            row.max_attempts = effective_max_attempts
            if row.attempt_count >= row.max_attempts:
                row.state = RecoveryJobState.TERMINAL_HOLD
                row.next_retry_at = None
                row.resolved_at = now
            else:
                row.state = RecoveryJobState.RETRYING
                row.next_retry_at = now + timedelta(seconds=_next_retry_delay_seconds(row.attempt_count))
            return row

        # RUNTIME-CLOSURE-1 (S22): platform-scoped - a Telegram failure for this draft must never
        # find/increment an Instagram recovery row for the same draft, or vice versa.
        existing = await self.find_open_recovery(session, content_draft_id=content_draft_id, platform=platform)
        if existing is not None:
            job = _increment(existing)
            await session.flush()
        else:
            attempt_count = 1
            is_terminal_immediately = attempt_count >= effective_max_attempts
            job = RecoveryJobRow(
                id=uuid4(),
                content_draft_id=content_draft_id,
                platform=_PLATFORM_TO_DB[platform],
                reason_code=db_reason,
                failed_stage=failed_stage,
                state=RecoveryJobState.TERMINAL_HOLD if is_terminal_immediately else RecoveryJobState.PENDING,
                attempt_count=attempt_count,
                max_attempts=effective_max_attempts,
                next_retry_at=(
                    None if is_terminal_immediately
                    else now + timedelta(seconds=_next_retry_delay_seconds(attempt_count))
                ),
                last_error_summary=last_error_summary,
                candidate_diagnostics=diagnostics,
                resolved_at=now if is_terminal_immediately else None,
            )
            # RUNTIME-CLOSURE-1 (S23): real, DB-level concurrency safety - two concurrent
            # transactions can both pass the `find_open_recovery()` check above (neither has
            # committed yet) and both reach this insert. A SAVEPOINT (`begin_nested()`) isolates
            # the insert attempt: if the partial unique index `ix_recovery_jobs_open_lifecycle_
            # identity` (§23 migration) rejects it as a duplicate, only this savepoint rolls back -
            # the OUTER transaction/session stays healthy - and the loser re-reads (now finding the
            # winner's row, committed-or-not-within-the-same-transaction-visible-via-flush) and
            # increments it instead, via the SAME `_increment()` the normal retry path uses. This
            # is "a safe upsert pattern" (§23's own phrasing), not merely a Python-side check.
            try:
                async with session.begin_nested():
                    session.add(job)
                    await session.flush()
            except IntegrityError:
                winner = await self.find_open_recovery(session, content_draft_id=content_draft_id, platform=platform)
                if winner is None:  # pragma: no cover - would mean the row that caused the
                    # violation vanished between the failed insert and this re-read; re-raise
                    # rather than silently losing this failure report.
                    raise
                job = _increment(winner)
                await session.flush()
        event_name = "recovery_created" if job.attempt_count == 1 else "recovery_retry_scheduled"
        logger.warning(
            event_name,
            extra={
                "content_draft_id": str(content_draft_id),
                "recovery_job_id": str(job.id),
                "reason_code": job.reason_code.value,
                "failed_stage": job.failed_stage,
                "attempt_count": job.attempt_count,
                "max_attempts": job.max_attempts,
                "state": job.state.value,
                "next_retry_at": job.next_retry_at.isoformat() if job.next_retry_at else None,
            },
        )
        if job.state == RecoveryJobState.TERMINAL_HOLD:
            logger.warning(
                "recovery_terminal_hold",
                extra={
                    "content_draft_id": str(content_draft_id), "recovery_job_id": str(job.id),
                    "reason_code": job.reason_code.value, "attempt_count": job.attempt_count,
                },
            )
        return job

    async def note_attempt_started(self, session: AsyncSession, *, job: RecoveryJobRow) -> None:
        """Observability only (S32's own `recovery_attempt_started` event) - called by a caller
        that is about to re-run the pipeline for a draft with an existing open RecoveryJob (i.e.
        `next_retry_at` has passed). Never mutates state itself - `create_or_retry()`/
        `mark_recovered()` are the only state-changing methods, so a caller that logs this and then
        crashes before either of those runs leaves the durable state exactly as it was (no lost or
        double-counted attempt)."""
        logger.info(
            "recovery_attempt_started",
            extra={
                "content_draft_id": str(job.content_draft_id), "recovery_job_id": str(job.id),
                "reason_code": job.reason_code.value, "attempt_count": job.attempt_count,
                "max_attempts": job.max_attempts,
            },
        )

    async def mark_recovered(
        self, session: AsyncSession, *, job: RecoveryJobRow, now: datetime | None = None,
    ) -> RecoveryJobRow:
        now = now or datetime.now(timezone.utc)
        job.state = RecoveryJobState.RECOVERED
        job.resolved_at = now
        job.next_retry_at = None
        await session.flush()
        logger.info(
            "recovery_recovered",
            extra={
                "content_draft_id": str(job.content_draft_id), "recovery_job_id": str(job.id),
                "attempt_count": job.attempt_count, "reason_code": job.reason_code.value,
            },
        )
        return job

    async def due_for_retry(
        self, session: AsyncSession, *, now: datetime | None = None, limit: int = 50,
    ) -> list[RecoveryJobRow]:
        """Every row in `RETRYING`/`PENDING` whose `next_retry_at` has passed - the query a future
        scheduled retry-consumer (out of this phase's own scope; S9 asks only that the state be
        real and durable, not that a retry-consumer loop be built) would page through. Exists now,
        tested now, so that future work has a real, already-proven query to build on rather than
        inventing one from scratch."""
        now = now or datetime.now(timezone.utc)
        stmt = (
            select(RecoveryJobRow)
            .where(RecoveryJobRow.state.in_((RecoveryJobState.PENDING, RecoveryJobState.RETRYING)))
            .where(RecoveryJobRow.next_retry_at.is_not(None))
            .where(RecoveryJobRow.next_retry_at <= now)
            .order_by(RecoveryJobRow.next_retry_at.asc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


LEGACY_HOLD_FOR_VISUAL_EQUIVALENT_REASON = "LEGACY_HOLD_FOR_VISUAL"
"""S10: the compatibility mapping label for a `content_drafts.status == 'hold_for_visual'` row
predating this phase (written by the still-live, unmodified `worker.content_cycle.
_hold_for_visual_recovery()` - see that function's own docstring). Not one of the real
`RecoveryReasonCode` values (it is not produced by any `RecoveryService` call site) - a distinct,
clearly-labeled marker so a report/dashboard can tell a genuinely pre-cutover legacy hold apart
from a real, reason-coded `recovery_jobs` row, never conflating the two."""


def describe_legacy_hold_for_visual_as_terminal_hold(*, content_draft_id: UUID) -> dict[str, object]:
    """S10's own explicit compatibility mapping - 'existing held drafts must remain interpretable
    during migration... provide compatibility mapping: legacy hold_for_visual -> new recovery/
    terminal-hold semantics.' A PURE, read-only, in-process description (never writes a row, never
    touches `content_drafts`, never mutates anything) - it exists purely so a caller building an
    audit/report can render a legacy `hold_for_visual` draft using the SAME semantic vocabulary
    (`state`, `reason_code`, `terminal`) as a real `RecoveryJob` row, without this phase ever
    silently creating a durable `recovery_jobs` row for a pre-existing hold (S10's own explicit
    'do NOT automatically resend old held posts' - this function makes no send/retry decision of
    any kind, it only describes)."""
    return {
        "content_draft_id": str(content_draft_id),
        "state": RecoveryJobState.TERMINAL_HOLD.value,
        "reason_code": LEGACY_HOLD_FOR_VISUAL_EQUIVALENT_REASON,
        "terminal": True,
        "source": "legacy_content_drafts_status_column",
        "note": (
            "Pre-cutover hold, written by worker.content_cycle._hold_for_visual_recovery() - "
            "interpreted here as equivalent to TERMINAL_HOLD for reporting only. Never "
            "automatically resent or converted into a real recovery_jobs row by this function."
        ),
    }
