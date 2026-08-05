"""Phase 18.9 M6 - controlled-batch-runner safety tests (docs/phase18_9_controlled_run_plan.md).

Every test in "Budget safety"/"Queue safety" exercises the *pre-execution* checks (eligibility,
budget) against a real, rolled-back Postgres transaction - never a real capability/LLM call.
`dry_run=True` (the default) is exercised directly for its own sake; `dry_run=False` behavior past
the eligibility/budget gate is intentionally not exercised here (it would require a full fake AI
layer identical to tests/test_phase10_workflow_integration.py's own - out of scope for this
safety-gate-focused suite, which only needs to prove no paid call is *reachable* before those
gates pass, not to re-test WorkflowRunner/CapabilityExecutor themselves, already covered
elsewhere).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.ai_execution import AICapability, AIExecution
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import NewsEvent
from schemas.controlled_batch import BoundedTaskStatus
from schemas.workflow import WorkflowExecutionState, WorkflowType
from scripts.phase18_9_controlled_batch_runner import (
    MAX_ANALYSIS_BATCH_SIZE,
    MAX_CONTENT_BATCH_SIZE,
    run_bounded_analysis_batch,
    run_bounded_content_batch,
)


class _PoisonPillCapabilityRegistry:
    """A `CapabilityRegistry` stand-in that raises immediately on any attribute access.

    Injected into every `dry_run=False` test below instead of relying solely on the budget/
    eligibility check's own correctness to prevent a real call - defense in depth, added directly
    in response to a real incident during this phase's own development: an earlier version of
    `run_bounded_analysis_batch` always built the real, production `assemble_ai_integration_layer()`
    unconditionally (before any budget check), and a since-fixed budget-check bug (a stateful
    "delta since last call" cost query that computed a large negative "spent this run" figure,
    permanently incapable of ever exceeding a budget) let a real workflow execution reach
    `WorkflowRunner.run()` and complete in a test that should have been refused. With this poison
    pill injected, any future regression that similarly fails to refuse would raise here loudly,
    long before any capability/provider is ever touched - never again risk a silent real call."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(
            f"CapabilityRegistry.{name} must never be accessed - the budget/eligibility check "
            "should have refused this task before reaching real capability execution."
        )


def _fake_session_factory(db_session: AsyncSession):
    class _CM:
        async def __aenter__(self) -> AsyncSession:
            return db_session

        async def __aexit__(self, *exc: object) -> bool:
            return False

    return lambda: _CM()


async def _created_analysis_task(db_session: AsyncSession, event: NewsEvent) -> EditorialTask:
    state = WorkflowExecutionState(
        workflow_name=WorkflowType.NEWS_ANALYSIS, workflow_version=1,
        current_step="research", completed_steps=[], iteration_count=0, step_results=[], failure=None,
    )
    task = EditorialTask(
        event_id=event.id, priority=TaskPriority.B, workflow=state.model_dump(mode="json"),
        status=TaskStatus.CREATED,
    )
    db_session.add(task)
    await db_session.flush()
    return task


async def _completed_analysis_task(db_session: AsyncSession, event: NewsEvent) -> EditorialTask:
    task = await _created_analysis_task(db_session, event)
    task.status = TaskStatus.COMPLETED
    await db_session.flush()
    return task


async def _ai_execution(
    db_session: AsyncSession, task: EditorialTask, cost: Decimal, *, created_at: datetime | None = None,
) -> AIExecution:
    """`created_at` is explicitly settable because Postgres's `func.now()` (the column's own
    server_default) returns the *transaction* start timestamp, constant for the whole test's
    single SAVEPOINT-based transaction - relying on the default would make every row in a test
    appear simultaneous, unable to test before/after watermark semantics at all."""
    row = AIExecution(
        task_id=task.id, event_id=task.event_id, workflow_name="NEWS_ANALYSIS",
        capability=AICapability.RESEARCH, model="gpt-5.6-luna", retry_number=0,
        input_tokens=100, output_tokens=50, cost=cost, usage_source="provider_response",
        **({"created_at": created_at} if created_at is not None else {}),
    )
    db_session.add(row)
    await db_session.flush()
    return row


# ---------------------------------------------------------------------------
# Queue safety
# ---------------------------------------------------------------------------


def test_analysis_batch_rejects_more_than_max_size() -> None:
    import asyncio

    task_ids = [uuid4() for _ in range(MAX_ANALYSIS_BATCH_SIZE + 1)]
    with pytest.raises(ValueError):
        asyncio.run(run_bounded_analysis_batch(task_ids, max_budget_usd=Decimal("1.00")))


def test_content_batch_rejects_more_than_max_size() -> None:
    import asyncio

    event_ids = [uuid4() for _ in range(MAX_CONTENT_BATCH_SIZE + 1)]
    with pytest.raises(ValueError):
        asyncio.run(run_bounded_content_batch(event_ids, max_budget_usd=Decimal("1.00")))


@pytest.mark.asyncio
async def test_analysis_batch_only_touches_the_explicit_allowlist(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    """A shared backlog of 5 other CREATED tasks exists - only the allowlisted one is previewed."""
    for _ in range(5):
        other_source_event = NewsEvent(
            source_id=real_news_event.source_id, title="Unrelated backlog event", content="x",
            category=real_news_event.category, hash=f"unrelated-{uuid4()}",
        )
        db_session.add(other_source_event)
        await db_session.flush()
        await _created_analysis_task(db_session, other_source_event)

    target_task = await _created_analysis_task(db_session, real_news_event)
    result = await run_bounded_analysis_batch(
        [target_task.id], max_budget_usd=Decimal("1.00"), dry_run=True,
        session_factory=_fake_session_factory(db_session),
    )
    assert [o.id for o in result.outcomes] == [target_task.id]


@pytest.mark.asyncio
async def test_analysis_batch_skips_task_not_in_created_status(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    task = await _completed_analysis_task(db_session, real_news_event)
    result = await run_bounded_analysis_batch(
        [task.id], max_budget_usd=Decimal("1.00"), dry_run=True, session_factory=_fake_session_factory(db_session),
    )
    assert result.outcomes[0].status == BoundedTaskStatus.SKIPPED_NOT_ELIGIBLE


@pytest.mark.asyncio
async def test_analysis_batch_skips_nonexistent_task_id(db_session: AsyncSession) -> None:
    result = await run_bounded_analysis_batch(
        [uuid4()], max_budget_usd=Decimal("1.00"), dry_run=True, session_factory=_fake_session_factory(db_session),
    )
    assert result.outcomes[0].status == BoundedTaskStatus.SKIPPED_NOT_ELIGIBLE
    assert result.outcomes[0].detail == "status=not_found"


@pytest.mark.asyncio
async def test_content_batch_skips_event_without_completed_analysis(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    result = await run_bounded_content_batch(
        [real_news_event.id], max_budget_usd=Decimal("1.00"), dry_run=True,
        session_factory=_fake_session_factory(db_session),
    )
    assert result.outcomes[0].status == BoundedTaskStatus.SKIPPED_NOT_ELIGIBLE
    assert result.outcomes[0].detail == "no_completed_analysis"


@pytest.mark.asyncio
async def test_content_batch_eligible_when_analysis_completed(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    await _completed_analysis_task(db_session, real_news_event)
    result = await run_bounded_content_batch(
        [real_news_event.id], max_budget_usd=Decimal("1.00"), dry_run=True,
        session_factory=_fake_session_factory(db_session),
    )
    assert result.outcomes[0].status == BoundedTaskStatus.DRY_RUN_PREVIEW


# ---------------------------------------------------------------------------
# Budget safety
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poison_pill_registry_fires_when_budget_and_eligibility_both_pass(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    """Validates the poison pill itself actually fires when reached (a safety net that's never
    proven to trigger isn't proven at all) - budget is generous and the task is eligible, so
    execution must reach the poison pill and be reported as an unexpected error, never silently
    succeed."""
    task = await _created_analysis_task(db_session, real_news_event)
    result = await run_bounded_analysis_batch(
        [task.id], max_budget_usd=Decimal("100.00"), dry_run=False,
        capability_registry=_PoisonPillCapabilityRegistry(),  # type: ignore[arg-type]
        session_factory=_fake_session_factory(db_session),
    )
    assert result.outcomes[0].status == BoundedTaskStatus.STOPPED_UNEXPECTED_ERROR
    assert result.outcomes[0].detail is not None and "must never be accessed" in result.outcomes[0].detail


@pytest.mark.asyncio
async def test_large_preexisting_historical_cost_does_not_produce_negative_spend(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    """Direct regression test for the exact incident (docs/phase18_9_paid_pipeline_audit.md):
    a huge amount of pre-existing `AIExecution` cost (simulating the real ~$6.82/4,632-row
    production history) must never make "spend during this run" appear negative or otherwise
    permanently under budget. `_cost_spent_since()` is time-scoped (`created_at >= run_started_at`,
    all historical rows predate the run), so old spend must not count against this run's own
    budget at all - and a fresh, over-budget task must still be refused."""
    prior_task = await _completed_analysis_task(db_session, real_news_event)
    for _ in range(20):
        await _ai_execution(db_session, prior_task, Decimal("50.00"))  # $1,000 of "historical" cost

    new_task = await _created_analysis_task(db_session, real_news_event)
    result = await run_bounded_analysis_batch(
        [new_task.id], max_budget_usd=Decimal("0.01"), dry_run=False,
        capability_registry=_PoisonPillCapabilityRegistry(),  # type: ignore[arg-type]
        session_factory=_fake_session_factory(db_session),
    )
    assert result.outcomes[0].status == BoundedTaskStatus.SKIPPED_BUDGET_EXCEEDED
    assert result.stop_reason == "budget_ceiling_would_be_exceeded"


@pytest.mark.asyncio
async def test_dry_run_never_charged_against_budget_and_never_mutates(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    task = await _created_analysis_task(db_session, real_news_event)
    result = await run_bounded_analysis_batch(
        [task.id], max_budget_usd=Decimal("1.00"), dry_run=True, session_factory=_fake_session_factory(db_session),
    )
    assert result.total_cost == Decimal("0")
    reloaded = await db_session.get(EditorialTask, task.id)
    assert reloaded is not None
    assert reloaded.status == TaskStatus.CREATED  # untouched


@pytest.mark.asyncio
async def test_task_refused_when_conservative_estimate_would_exceed_remaining_budget(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    """A budget of $0.01 is far below the $0.035 conservative per-task estimate - the very first
    (non-dry-run-gated) budget check must refuse before ever reaching the eligibility/execution
    branch."""
    task = await _created_analysis_task(db_session, real_news_event)
    result = await run_bounded_analysis_batch(
        [task.id], max_budget_usd=Decimal("0.01"), dry_run=False,
        capability_registry=_PoisonPillCapabilityRegistry(),  # type: ignore[arg-type]
        session_factory=_fake_session_factory(db_session),
    )
    assert result.outcomes[0].status == BoundedTaskStatus.SKIPPED_BUDGET_EXCEEDED
    assert result.stopped_early is True
    assert result.stop_reason == "budget_ceiling_would_be_exceeded"


@pytest.mark.asyncio
async def test_cost_spent_since_only_counts_rows_created_at_or_after_the_watermark(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    """Direct unit test of the time-scoping semantics `run_bounded_analysis_batch`'s own budget
    check depends on: spend from *before* a run started (real historical `AIExecution` rows, or a
    completely separate prior run) must never count against *this* run's own budget - only spend
    recorded at-or-after the watermark does. This is the deliberate, correct replacement for the
    old, buggy "delta since last call" design (see the large-preexisting-cost regression test
    above) - genuinely prior spend is out of scope for a bounded run's own ceiling by design (the
    separate, pre-existing `LLM_BUDGET_MODE=enforce` daily ledger is what spans across runs)."""
    from datetime import timedelta

    from scripts.phase18_9_controlled_batch_runner import _cost_spent_since

    now = datetime.now(timezone.utc)
    watermark = now

    old_task = await _completed_analysis_task(db_session, real_news_event)
    await _ai_execution(db_session, old_task, Decimal("0.97"), created_at=now - timedelta(hours=1))

    new_task = await _completed_analysis_task(db_session, real_news_event)
    await _ai_execution(db_session, new_task, Decimal("0.05"), created_at=now + timedelta(seconds=1))

    spent = await _cost_spent_since(db_session, watermark)
    assert spent == Decimal("0.05")  # only the post-watermark row counts, not the $0.97


@pytest.mark.asyncio
async def test_content_batch_budget_check_mirrors_analysis(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    await _completed_analysis_task(db_session, real_news_event)
    result = await run_bounded_content_batch(
        [real_news_event.id], max_budget_usd=Decimal("0.01"), dry_run=False,
        capability_registry=_PoisonPillCapabilityRegistry(),  # type: ignore[arg-type]
        session_factory=_fake_session_factory(db_session),
    )
    assert result.outcomes[0].status == BoundedTaskStatus.SKIPPED_BUDGET_EXCEEDED


@pytest.mark.asyncio
async def test_missing_cost_information_fails_closed(db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the cumulative-cost query itself raises, the batch must stop rather than assume $0 and
    proceed - simulated by monkeypatching the internal cost-query helper to raise."""
    import scripts.phase18_9_controlled_batch_runner as runner_module

    async def _boom(*args: object, **kwargs: object) -> Decimal:
        raise RuntimeError("simulated ledger read failure")

    monkeypatch.setattr(runner_module, "_cost_spent_since", _boom)
    task = await _created_analysis_task(db_session, real_news_event)
    result = await run_bounded_analysis_batch(
        [task.id], max_budget_usd=Decimal("1.00"), dry_run=False,
        capability_registry=_PoisonPillCapabilityRegistry(),  # type: ignore[arg-type]
        session_factory=_fake_session_factory(db_session),
    )
    assert result.stopped_early is True
    assert result.stop_reason is not None and "budget_check_failed_closed" in result.stop_reason
    assert result.outcomes == []  # never even reached the eligibility/execution branch


# ---------------------------------------------------------------------------
# Configuration safety
# ---------------------------------------------------------------------------


def test_meme_mode_flags_remain_off() -> None:
    assert settings.meme_opportunity_mode == "off"
    assert settings.meme_safety_gate_mode == "off"
    assert settings.meme_image_generation_mode == "off"
    assert settings.meme_telegram_preview_mode == "off"


def test_calibration_versions_remain_v1() -> None:
    assert settings.meme_opportunity_calibration_version == "v1"
    assert settings.meme_safety_calibration_version == "v1"


def test_runner_functions_default_to_dry_run() -> None:
    import inspect

    analysis_sig = inspect.signature(run_bounded_analysis_batch)
    content_sig = inspect.signature(run_bounded_content_batch)
    assert analysis_sig.parameters["dry_run"].default is True
    assert content_sig.parameters["dry_run"].default is True


# ---------------------------------------------------------------------------
# Side-effect safety - import-boundary check (mirrors every Phase 18.5-18.8 precedent)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_path", [
    "scripts/phase18_9_controlled_batch_runner.py",
    "schemas/controlled_batch.py",
])
def test_no_forbidden_imports(module_path: str) -> None:
    import ast
    from pathlib import Path

    source = Path(module_path).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    forbidden_substrings = (
        "bot.", "telegram_notifier", "image_preview_notifier", "meme_image_generation",
        "meme_preview_notifier", "meme_candidate_service", "meme_concept", "meme_copywriting",
    )
    for module in imported_modules:
        for forbidden in forbidden_substrings:
            assert forbidden not in module, f"{module_path} must never import {module!r}"


def test_no_write_statements_outside_reused_production_helpers() -> None:
    """Textual guard: this file must never construct its own INSERT/UPDATE/DELETE - all real
    persistence must flow through the reused WorkflowRunner/ContentDraftService/create_task()
    helpers, never a raw statement of its own."""
    from pathlib import Path

    source = Path("scripts/phase18_9_controlled_batch_runner.py").read_text(encoding="utf-8").lower()
    for forbidden in ("insert(", "update(editorialtask", "delete(", ".execute(text("):
        assert forbidden not in source


def test_migration_head_unchanged_by_this_phase() -> None:
    """This phase must never apply the pending meme_candidates migration - a static guard that no
    alembic upgrade call exists anywhere in this phase's own new files."""
    from pathlib import Path

    for path in ("scripts/phase18_9_controlled_batch_runner.py",):
        source = Path(path).read_text(encoding="utf-8").lower()
        assert "alembic" not in source
        assert "upgrade head" not in source
