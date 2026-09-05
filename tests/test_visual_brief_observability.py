"""PRODUCTION-SOURCE-RECONCILIATION-1B §17/§18: closes the known Visual Design Autonomy
observability debt. Uses `caplog` (real Python logging capture) rather than mocking
services.visual_brief_observability itself, so these tests prove the REAL wiring inside
services/visual_designer_brief_service.py and services/visual_regression_service.py actually
fires, not just that the observability module's own functions work in isolation."""
from __future__ import annotations

import logging
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.visual_regression import VisualRegressionCase, VisualRegressionOutcome
from services.visual_designer_brief_service import (
    create_candidate_brief,
    create_initial_brief,
    freeze_brief,
    get_active_brief,
    promote_candidate,
    reject_candidate,
    rollback_to,
    unfreeze_brief,
)
from services.visual_regression_service import run_regression_validation

pytestmark = pytest.mark.asyncio


def _scope() -> str:
    return f"test-scope-{uuid4().hex[:8]}"


def _extra(record: logging.LogRecord, field: str) -> object:
    """`extra={...}` fields land as plain attributes on the LogRecord instance - not declared on
    the stdlib type, so accessed via __dict__ rather than direct attribute access (which mypy
    correctly flags as attr-defined on the untyped stdlib class)."""
    return record.__dict__[field]


async def test_candidate_creation_emits_event(db_session: AsyncSession, caplog: pytest.LogCaptureFixture) -> None:
    scope = _scope()
    await create_initial_brief(db_session, scope=scope, brief_text="v1 baseline brief text")
    with caplog.at_level(logging.INFO):
        candidate = await create_candidate_brief(db_session, scope=scope, brief_text="candidate brief text", reason="drift detected")
    assert any(r.message == "visual_brief_candidate_created" for r in caplog.records)
    record = next(r for r in caplog.records if r.message == "visual_brief_candidate_created")
    assert _extra(record, "brief_version_id") == str(candidate.id)
    assert _extra(record, "reason_code") == "drift detected"


async def test_validation_emits_pass_fail_event(db_session: AsyncSession, caplog: pytest.LogCaptureFixture) -> None:
    scope = _scope()
    baseline = await create_initial_brief(db_session, scope=scope, brief_text="baseline")
    candidate = await create_candidate_brief(db_session, scope=scope, brief_text="candidate", reason="test")
    case = VisualRegressionCase(
        scope=scope, name="busy_photo", stress_condition="busy_photo", description="a busy photo stress case", active=True,
    )
    db_session.add(case)
    await db_session.commit()
    await db_session.refresh(case)

    async def fake_art_director(_case: VisualRegressionCase, _version_id) -> tuple[VisualRegressionOutcome, list[str], float | None]:
        return VisualRegressionOutcome.PASS, [], 0.01

    with caplog.at_level(logging.INFO):
        await run_regression_validation(
            db_session, candidate_brief_version_id=candidate.id, baseline_brief_version_id=baseline.id,
            cases=[case], art_director_fn=fake_art_director,
        )
    record = next(r for r in caplog.records if r.message == "visual_brief_candidate_validated")
    assert _extra(record, "result") == "pass"
    assert _extra(record, "scope") == scope


async def test_promotion_emits_event(db_session: AsyncSession, caplog: pytest.LogCaptureFixture) -> None:
    scope = _scope()
    await create_initial_brief(db_session, scope=scope, brief_text="baseline")
    candidate = await create_candidate_brief(db_session, scope=scope, brief_text="candidate", reason="test")
    with caplog.at_level(logging.INFO):
        await promote_candidate(db_session, candidate.id)
    record = next(r for r in caplog.records if r.message == "visual_brief_promoted")
    assert _extra(record, "brief_version_id") == str(candidate.id)


async def test_rejection_emits_event(db_session: AsyncSession, caplog: pytest.LogCaptureFixture) -> None:
    scope = _scope()
    await create_initial_brief(db_session, scope=scope, brief_text="baseline")
    candidate = await create_candidate_brief(db_session, scope=scope, brief_text="candidate", reason="test")
    with caplog.at_level(logging.INFO):
        await reject_candidate(db_session, candidate.id, reason="failed brand core check")
    record = next(r for r in caplog.records if r.message == "visual_brief_candidate_rejected")
    assert _extra(record, "reason_code") == "failed brand core check"


async def test_rollback_emits_event(db_session: AsyncSession, caplog: pytest.LogCaptureFixture) -> None:
    scope = _scope()
    v1 = await create_initial_brief(db_session, scope=scope, brief_text="v1")
    candidate = await create_candidate_brief(db_session, scope=scope, brief_text="v2", reason="test")
    await promote_candidate(db_session, candidate.id)
    with caplog.at_level(logging.INFO):
        await rollback_to(db_session, scope, target_version_id=v1.id, reason="v2 caused visible regressions")
    record = next(r for r in caplog.records if r.message == "visual_brief_rolled_back")
    assert _extra(record, "reason_code") == "v2 caused visible regressions"


async def test_freeze_and_unfreeze_each_emit_their_own_event(db_session: AsyncSession, caplog: pytest.LogCaptureFixture) -> None:
    scope = _scope()
    await create_initial_brief(db_session, scope=scope, brief_text="v1")
    with caplog.at_level(logging.INFO):
        await freeze_brief(db_session, scope, reason="founder locked it manually")
    assert any(r.message == "visual_brief_frozen" for r in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.INFO):
        await unfreeze_brief(db_session, scope, reason="founder unlocked it")
    assert any(r.message == "visual_brief_unfrozen" for r in caplog.records)


async def test_raw_brief_text_never_appears_in_any_lifecycle_log_payload(db_session: AsyncSession, caplog: pytest.LogCaptureFixture) -> None:
    scope = _scope()
    secret_text = "THIS-EXACT-BRIEF-TEXT-MUST-NEVER-APPEAR-IN-LOGS"
    await create_initial_brief(db_session, scope=scope, brief_text=secret_text)
    with caplog.at_level(logging.INFO):
        candidate = await create_candidate_brief(db_session, scope=scope, brief_text=secret_text + "-candidate", reason="test")
        await promote_candidate(db_session, candidate.id)
    for record in caplog.records:
        assert secret_text not in record.getMessage()
        for value in vars(record).values():
            assert secret_text not in str(value)


async def test_normal_design_read_emits_no_mutation_lifecycle_events(db_session: AsyncSession, caplog: pytest.LogCaptureFixture) -> None:
    scope = _scope()
    await create_initial_brief(db_session, scope=scope, brief_text="v1")
    caplog.clear()
    lifecycle_events = {
        "visual_brief_candidate_created", "visual_brief_candidate_validated", "visual_brief_promoted",
        "visual_brief_candidate_rejected", "visual_brief_rolled_back", "visual_brief_frozen", "visual_brief_unfrozen",
    }
    with caplog.at_level(logging.INFO):
        result = await get_active_brief(db_session, scope)
    assert result is not None
    assert not any(r.message in lifecycle_events for r in caplog.records)
