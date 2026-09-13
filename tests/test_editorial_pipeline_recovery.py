"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 S23/S35: recovery as a first-class workflow."""
from uuid import uuid4

from services.editorial_pipeline.contracts import RecoveryReasonCode, RecoveryState
from services.editorial_pipeline.recovery import DEFAULT_MAX_ATTEMPTS, create_recovery_job


def test_recovery_job_is_terminal_by_default_no_infinite_retries() -> None:
    job = create_recovery_job(
        content_draft_id=uuid4(), reason_code=RecoveryReasonCode.NO_SUITABLE_MEDIA, failed_stage="media_research",
    )
    assert job.max_attempts == DEFAULT_MAX_ATTEMPTS == 1
    assert job.attempt_count == 1
    assert job.is_terminal is True
    assert job.state == RecoveryState.TERMINAL


def test_recovery_job_reason_code_and_diagnostics_are_preserved() -> None:
    job = create_recovery_job(
        content_draft_id=uuid4(), reason_code=RecoveryReasonCode.MEDIA_SEND_FAILED, failed_stage="telegram_send",
        last_error="TelegramAPIError: timeout", candidate_diagnostics=("candidate-1: rejected, low quality",),
    )
    assert job.reason_code == RecoveryReasonCode.MEDIA_SEND_FAILED
    assert job.last_error == "TelegramAPIError: timeout"
    assert job.candidate_diagnostics == ("candidate-1: rejected, low quality",)


def test_recovery_job_respects_an_explicit_bounded_max_attempts() -> None:
    job = create_recovery_job(
        content_draft_id=uuid4(), reason_code=RecoveryReasonCode.MEDIA_RESEARCH_TIMEOUT,
        failed_stage="media_research", max_attempts=2,
    )
    assert job.is_terminal is False  # attempt 1 of 2 - not yet terminal
    assert job.state == RecoveryState.OPEN
