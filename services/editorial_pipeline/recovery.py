"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 (S23): recovery as a first-class workflow.

`content_drafts.status = "hold_for_visual"` (this session's own prior TELEGRAM-TEXT-ONLY-VISUAL-
FALLBACK-REPAIR-1 phase, `worker.content_cycle.HOLD_FOR_VISUAL_STATUS`/`_hold_for_visual_recovery()`
- currently deployed to production) remains the real, durable Telegram persistence mechanism - this
module does not replace it. It adds the first-class `RecoveryJob`/`RecoveryResult` structure the
orchestrator (S25) actually reasons about, and bridges to that same production mechanism for
Telegram, bounded (never an infinite retry - S23's own explicit rule) and reason-coded (S4-E: every
failure "bounded, observable, reason-coded, recoverable where appropriate, terminal after explicit
max attempts").
"""
from __future__ import annotations

import logging
from uuid import UUID

from services.editorial_pipeline.contracts import RecoveryJob, RecoveryReasonCode, RecoveryResult

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 1
"""S4-E/S23: bounded - this phase's own recovery workflow makes zero extra render/generation
attempts by default (matching this session's own prior TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1
precedent, MAX_VISUAL_FALLBACK_ATTEMPTS=0) - a RecoveryJob's first failure is already its terminal
one unless a caller explicitly raises max_attempts for a specific, bounded reason."""


def create_recovery_job(
    *, content_draft_id: UUID, reason_code: RecoveryReasonCode, failed_stage: str,
    last_error: str | None = None, candidate_diagnostics: tuple[str, ...] = (),
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> RecoveryJob:
    job = RecoveryJob(
        content_draft_id=content_draft_id, reason_code=reason_code, failed_stage=failed_stage,
        attempt_count=1, max_attempts=max_attempts, last_error=last_error,
        candidate_diagnostics=candidate_diagnostics,
    )
    logger.warning(
        "recovery_created",
        extra={
            "content_draft_id": str(content_draft_id), "reason_code": reason_code.value,
            "failed_stage": failed_stage, "attempt_count": job.attempt_count, "max_attempts": job.max_attempts,
            "is_terminal": job.is_terminal, "state": job.state.value,
        },
    )
    return job


async def apply_telegram_recovery(job: RecoveryJob, *, session_factory, bot, event, presentation_type: str) -> RecoveryResult:
    """Bridges a `RecoveryJob` to the real, already-deployed, already-tested Telegram mechanism -
    `worker.content_cycle._hold_for_visual_recovery()` - rather than a second, competing
    persistence path. Imported lazily to avoid a hard import-time dependency from this
    platform-neutral package onto `worker.content_cycle` (which itself will come to depend on this
    package once S25/S26 wire it in - a lazy import here breaks that cycle cleanly)."""
    from worker.content_cycle import HOLD_REASON_NO_VISUAL_RESOLVED, _hold_for_visual_recovery

    await _hold_for_visual_recovery(
        session_factory, bot, draft_id=job.content_draft_id, event=event, presentation_type=presentation_type,
        reason=HOLD_REASON_NO_VISUAL_RESOLVED, dry_run=False,
    )
    # `_hold_for_visual_recovery()` itself never raises and never reports whether the notice send
    # specifically succeeded (by design - the DB status write is the one durable guarantee, proven
    # by that phase's own test_hold_survives_the_notice_send_itself_failing). `notice_sent=True`
    # here means "the attempt completed", not "delivery confirmed" - RecoveryResult.notice_sent's
    # own docstring already frames this field as best-effort, never the durable guarantee.
    return RecoveryResult(job=job, notice_sent=True)
