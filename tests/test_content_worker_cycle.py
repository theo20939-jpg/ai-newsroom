"""Tests for worker.content_cycle (Phase 14 M1/M2).

Real Postgres, no separate test database - independent_session_factory() (imported from
tests.test_triage_orchestrator_claims, the already-established, already-proven helper Phase 12/13
own integration tests reuse) with explicit, FK-safe, test-owned cleanup - never rollback-only
isolation, never a table-wide delete.

CRITICAL isolation note (mirrors tests/test_analysis_worker_cycle.py's own identical concern,
discovered and fixed during Phase 13 M3): run_content_cycle()/_select_eligible_events() call the
real, deliberately-unscoped eligibility query against the shared dev database, which may contain
real, currently-fresh-eligible COMPLETED NEWS_ANALYSIS tasks with no CONTENT_GENERATION sibling
yet. Every test below that queries eligibility narrows settings.content_generation_freshness_
cutoff_hours to a few minutes first, so only this test's own just-created rows are ever eligible -
never real backlog.
"""
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capabilities.registry import build_registry
from core.config import settings
from database.models.content_draft import ContentDraft
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.llm_gateway.tools.registry import ToolRegistry
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowType
from services import workflow_service
from services.telegram_notifier import NotificationOutcome
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_infra import AllowingBudgetGuard
from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT
from tests.test_triage_orchestrator_claims import independent_session_factory
from worker.content_cycle import _select_eligible_events, run_content_cycle

_PROMPTS_ROOT_PATH = Path("prompts")

_INTELLIGENCE_OUTPUT: dict[str, object] = {
    "significance": 0.7,
    "angle": "Market impact",
    "audience_relevance": "General audience",
    "recommendation": "Publish with standard priority",
}
_COPYWRITING_OUTPUT: dict[str, object] = {
    "title": "Example draft title",
    "body": "Example draft body text.",
    "what_happened": "Example event happened.",
    "why_it_matters": "Example editorial interpretation of the impact.",
    "what_remains_unknown": None,
    "quote": None,
}
_QUALITY_OUTPUT: dict[str, object] = {"passed": True, "issues": []}


def _generate_response(structured_output: dict[str, object]) -> GenerateResponse:
    return GenerateResponse(
        text=None,
        structured_output=structured_output,
        finish_reason="stop",
        model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    )


def _real_capability_registry():
    gateway = FakeLLMGateway(
        generate_responses=[
            _generate_response(CANONICAL_RESEARCH_OUTPUT),
            _generate_response(_INTELLIGENCE_OUTPUT),
            _generate_response(_COPYWRITING_OUTPUT),
            _generate_response(_QUALITY_OUTPUT),
        ]
    )
    registry = build_registry(
        gateway, FilePromptRepository(_PROMPTS_ROOT_PATH), AllowingBudgetGuard(), ToolRegistry()  # type: ignore[arg-type]
    )
    return gateway, registry


@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine, session_factory = independent_session_factory()
    yield session_factory
    await engine.dispose()


@pytest_asyncio.fixture
async def test_source(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[NewsSource]:
    unique_name = f"phase14-content-cycle-test-{uuid4()}"
    async with factory() as session:
        source = NewsSource(name=unique_name, type=SourceType.RSS, active=True)
        session.add(source)
        await session.commit()

    try:
        yield source
    finally:
        async with factory() as session:
            event_ids = (
                await session.execute(select(NewsEvent.id).where(NewsEvent.source_id == source.id))
            ).scalars().all()
            if event_ids:
                await session.execute(delete(ContentDraft).where(ContentDraft.task_id.in_(
                    select(EditorialTask.id).where(EditorialTask.event_id.in_(event_ids))
                )))
                await session.execute(delete(EditorialTask).where(EditorialTask.event_id.in_(event_ids)))
                await session.execute(delete(NewsEvent).where(NewsEvent.id.in_(event_ids)))
            await session.execute(delete(NewsSource).where(NewsSource.id == source.id))
            await session.commit()


@pytest_asyncio.fixture
async def _isolated_freshness_window() -> AsyncIterator[None]:
    original = settings.content_generation_freshness_cutoff_hours
    settings.content_generation_freshness_cutoff_hours = 0.05  # 3 minutes - far below any real
    # backlog's minimum age, comfortably above this test's own runtime.
    try:
        yield
    finally:
        settings.content_generation_freshness_cutoff_hours = original


async def _make_event(session: AsyncSession, source: NewsSource, *, published_at: datetime) -> NewsEvent:
    event = NewsEvent(
        source_id=source.id,
        title=f"Content cycle test event {uuid4()}",
        category=EventCategory.AI,
        hash=f"content-cycle-test-{uuid4()}",
        published_at=published_at,
    )
    session.add(event)
    await session.flush()
    await session.commit()
    return event


async def _make_completed_news_analysis_task(
    session: AsyncSession, event: NewsEvent, *, score: int | None, completed_at: datetime | None = None
) -> EditorialTask:
    """Directly constructs a COMPLETED NEWS_ANALYSIS task with a controlled scoring result -
    mirrors tests/test_workflow_runner.py's own established raw-task-mutation technique
    (test_max_iterations_exceeded_fails_without_running_any_step) rather than running a real
    WorkflowRunner pass, since these are eligibility-query-focused tests, not workflow-execution
    tests (already covered by tests/test_news_analysis_integration.py)."""
    command = EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.NEWS_ANALYSIS, priority=TaskPriority.B)
    read = await workflow_service.create_task(session, command)
    task = await session.get(EditorialTask, read.id)
    assert task is not None

    step_results = [
        {
            "step_name": "scoring", "status": "SUCCESS", "attempt": 1,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
            "result": {"score": score, "rationale": "test"} if score is not None else None,
        }
    ] if score is not None else []
    # Reassign the whole dict (never mutate a nested key in place) - EditorialTask.workflow is a
    # plain JSON column with no MutableDict tracking, mirroring workflows/runner.py's own
    # `task.workflow = state.model_dump(mode="json")` convention exactly, for the same reason:
    # in-place mutation of a sub-key is not detected by SQLAlchemy's change tracking.
    task.workflow = {**(task.workflow or {}), "step_results": step_results}
    task.status = TaskStatus.COMPLETED
    await session.commit()
    if completed_at is not None:
        # updated_at has onupdate=func.now() - override explicitly after the commit above already
        # set it, via a direct UPDATE, so the freshness-window tests can control it precisely.
        from sqlalchemy import update

        await session.execute(
            update(EditorialTask).where(EditorialTask.id == task.id).values(updated_at=completed_at)
        )
        await session.commit()
        await session.refresh(task)
    return task


async def _make_content_generation_sibling(session: AsyncSession, event: NewsEvent, status: TaskStatus) -> EditorialTask:
    command = EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B)
    read = await workflow_service.create_task(session, command)
    task = await session.get(EditorialTask, read.id)
    assert task is not None
    task.status = status
    await session.commit()
    return task


# ---------------------------------------------------------------------------
# _select_eligible_events() - SQL-side filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completed_news_analysis_above_threshold_is_eligible(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

        eligible = await _select_eligible_events(session)

        assert event.id in eligible


@pytest.mark.asyncio
async def test_below_threshold_score_is_excluded(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        await _make_completed_news_analysis_task(
            session, event, score=settings.content_generation_min_score - 1
        )

        eligible = await _select_eligible_events(session)

        assert event.id not in eligible


@pytest.mark.asyncio
async def test_missing_scoring_result_is_excluded(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        await _make_completed_news_analysis_task(session, event, score=None)

        eligible = await _select_eligible_events(session)

        assert event.id not in eligible


@pytest.mark.asyncio
async def test_non_completed_news_analysis_is_excluded(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        command = EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.NEWS_ANALYSIS, priority=TaskPriority.B)
        task_read = await workflow_service.create_task(session, command)  # left CREATED - never completed

        eligible = await _select_eligible_events(session)

        assert event.id not in eligible
        assert task_read.status.value == "CREATED"


@pytest.mark.asyncio
async def test_stale_completed_task_beyond_freshness_cutoff_is_excluded(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        stale_completed_at = datetime.now(timezone.utc) - timedelta(hours=1)  # older than the
        # 3-minute isolated window above.
        await _make_completed_news_analysis_task(
            session, event, score=settings.content_generation_min_score, completed_at=stale_completed_at
        )

        eligible = await _select_eligible_events(session)

        assert event.id not in eligible


@pytest.mark.asyncio
@pytest.mark.parametrize("sibling_status", [TaskStatus.CREATED, TaskStatus.RUNNING, TaskStatus.COMPLETED, TaskStatus.FAILED])
async def test_duplicate_content_generation_sibling_excludes_regardless_of_status(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None,
    sibling_status: TaskStatus,
) -> None:
    """The load-bearing duplicate-prevention case (docs/phase14_autonomous_newsroom_
    implementation_plan.md §3): a NewsEvent must never receive a second CONTENT_GENERATION task,
    regardless of the existing sibling's own status - CREATED, RUNNING, COMPLETED, and FAILED are
    all tested separately, not merged into one case."""
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)
        await _make_content_generation_sibling(session, event, sibling_status)

        eligible = await _select_eligible_events(session)

        assert event.id not in eligible


@pytest.mark.asyncio
async def test_scan_limit_caps_candidates_before_score_filtering(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    """The scan-limit guarantee (§3 of the Plan): the SQL query itself never returns more
    candidate rows than content_generation_scan_limit, even before the Python-side score
    threshold is applied - proven directly by temporarily lowering scan_limit below the number of
    genuinely eligible test-owned rows and confirming the total selected count is capped."""
    original_scan_limit = settings.content_generation_scan_limit
    original_batch_size = settings.content_generation_batch_size
    settings.content_generation_scan_limit = 3
    settings.content_generation_batch_size = 3
    try:
        async with factory() as session:
            created_event_ids = []
            for _ in range(6):
                event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
                await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)
                created_event_ids.append(event.id)

            eligible = await _select_eligible_events(session)

            matched = [eid for eid in eligible if eid in created_event_ids]
            assert len(matched) == 3  # capped at scan_limit, not the 6 genuinely-eligible rows
    finally:
        settings.content_generation_scan_limit = original_scan_limit
        settings.content_generation_batch_size = original_batch_size


@pytest.mark.asyncio
async def test_batch_size_caps_final_selection_within_a_larger_scan(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    original_batch_size = settings.content_generation_batch_size
    settings.content_generation_batch_size = 2
    try:
        async with factory() as session:
            created_event_ids = []
            for _ in range(4):
                event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
                await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)
                created_event_ids.append(event.id)

            eligible = await _select_eligible_events(session)

            matched = [eid for eid in eligible if eid in created_event_ids]
            assert len(matched) == 2  # batch_size, even though scan_limit (default 50) allows more
    finally:
        settings.content_generation_batch_size = original_batch_size


def test_scan_limit_is_at_least_batch_size() -> None:
    assert settings.content_generation_scan_limit >= settings.content_generation_batch_size


# ---------------------------------------------------------------------------
# Phase 15 M5.2 - candidate-starvation fix (freshest-editorial-content-first ordering).
# Every test below exercises only _select_eligible_events() directly - a pure selection-query
# call, no draft generation, no LLM call, no Telegram send - so "no manual delivery side
# effects" (the task's own item J) is satisfied structurally, not by a separate assertion.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_starvation_reproduction_fresh_high_score_event_survives_a_full_scan_window(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    """Reproduces the exact real starvation this milestone fixes: under the OLD ordering
    (oldest-task-completed-first), a backlog of `scan_limit` older-completed, low-score
    candidates would fill the entire scan window before a single fresher, genuinely eligible,
    high-score event is ever considered - even though that fresher event completed its own
    NEWS_ANALYSIS run only slightly later. Under the NEW ordering (freshest-editorial-content-
    first), the fresh event's own recent `published_at` guarantees it is scanned regardless of
    how many older-but-still-freshness-window-eligible tasks exist."""
    original_scan_limit = settings.content_generation_scan_limit
    settings.content_generation_scan_limit = 5
    try:
        async with factory() as session:
            now = datetime.now(timezone.utc)
            old_event_ids = []
            for _ in range(5):
                # Old EDITORIAL content (published 10 hours ago) whose NEWS_ANALYSIS task
                # completed EARLIER (task updated_at) than the fresh event below - exactly the
                # shape a provider-outage backlog produces (old news, recently caught up on).
                old_event = await _make_event(session, test_source, published_at=now - timedelta(hours=10))
                await _make_completed_news_analysis_task(
                    session, old_event, score=settings.content_generation_min_score,
                    completed_at=now - timedelta(minutes=2),
                )
                old_event_ids.append(old_event.id)

            # Fresh EDITORIAL content (published just now) whose task completed LAST (most
            # recent task updated_at) - the real scenario: a just-analyzed, genuinely fresh,
            # high-score story arriving after a backlog of older-but-still-eligible tasks.
            fresh_event = await _make_event(session, test_source, published_at=now)
            await _make_completed_news_analysis_task(
                session, fresh_event, score=settings.content_generation_min_score, completed_at=now,
            )

            eligible = await _select_eligible_events(session)

            assert fresh_event.id in eligible, (
                "the fresh, high-score event must not be starved out by an older backlog "
                "filling the bounded scan window"
            )
    finally:
        settings.content_generation_scan_limit = original_scan_limit


@pytest.mark.asyncio
async def test_b_freshness_priority_orders_by_published_at_descending(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    original_batch_size = settings.content_generation_batch_size
    settings.content_generation_batch_size = 1  # forces selection of exactly the single top-priority candidate
    try:
        async with factory() as session:
            now = datetime.now(timezone.utc)
            old_event = await _make_event(session, test_source, published_at=now - timedelta(hours=5))
            await _make_completed_news_analysis_task(session, old_event, score=settings.content_generation_min_score)
            medium_event = await _make_event(session, test_source, published_at=now - timedelta(hours=1))
            await _make_completed_news_analysis_task(session, medium_event, score=settings.content_generation_min_score)
            fresh_event = await _make_event(session, test_source, published_at=now)
            await _make_completed_news_analysis_task(session, fresh_event, score=settings.content_generation_min_score)

            eligible = await _select_eligible_events(session)

            assert eligible == [fresh_event.id]  # the single freshest of the three, not an arbitrary one
    finally:
        settings.content_generation_batch_size = original_batch_size


@pytest.mark.asyncio
async def test_c_tie_breaking_is_stable_and_deterministic_across_repeated_calls(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    """Two events with an identical published_at (a real, possible tie - e.g. two stories
    ingested from the same source batch) must still produce a stable, reproducible ordering,
    not one that varies call-to-call - satisfied by the EditorialTask.id ASC tie-breaker."""
    async with factory() as session:
        now = datetime.now(timezone.utc)
        event_a = await _make_event(session, test_source, published_at=now)
        task_a = await _make_completed_news_analysis_task(session, event_a, score=settings.content_generation_min_score)
        event_b = await _make_event(session, test_source, published_at=now)
        task_b = await _make_completed_news_analysis_task(session, event_b, score=settings.content_generation_min_score)

        first_call = await _select_eligible_events(session)
        second_call = await _select_eligible_events(session)

        assert first_call == second_call  # stable across repeated calls, not merely non-crashing
        expected_first = event_a.id if task_a.id < task_b.id else event_b.id
        assert first_call[0] == expected_first  # matches the documented EditorialTask.id ASC tie-break


@pytest.mark.asyncio
async def test_c2_tie_breaking_with_missing_published_at_falls_back_to_collected_at(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    """A NewsEvent with no published_at at all (a real, common case - many RSS/NEWS_API items
    never carry one) must not crash the ordering or be silently dropped - it falls back to
    NewsEvent.collected_at, the same coalesce anchor already established for NEWS_ANALYSIS's own
    eligibility query (worker/analysis_cycle.py)."""
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=None)  # type: ignore[arg-type]
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

        eligible = await _select_eligible_events(session)

        assert event.id in eligible


@pytest.mark.asyncio
async def test_d_stale_task_outside_freshness_cutoff_remains_ineligible_despite_high_score_and_fresh_content(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    """Proves the M5.2 ordering change did not touch the existing eligibility WHERE clause: a
    task whose own `updated_at` (completion time) is older than the freshness cutoff remains
    excluded, even when paired with a very recent `published_at` and a qualifying score - the
    cutoff is still evaluated on task-completion time, unchanged, exactly as before this fix."""
    async with factory() as session:
        now = datetime.now(timezone.utc)
        event = await _make_event(session, test_source, published_at=now)  # very fresh content
        await _make_completed_news_analysis_task(
            session, event, score=settings.content_generation_min_score,
            completed_at=now - timedelta(hours=1),  # older than the 3-minute isolated window
        )

        eligible = await _select_eligible_events(session)

        assert event.id not in eligible


@pytest.mark.asyncio
async def test_e_duplicate_content_generation_sibling_still_excludes_the_freshest_event(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    """Re-confirms M5.2 did not weaken duplicate protection: even the single freshest, highest-
    priority candidate is still excluded once any CONTENT_GENERATION sibling exists for it."""
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)
        await _make_content_generation_sibling(session, event, TaskStatus.COMPLETED)

        eligible = await _select_eligible_events(session)

        assert event.id not in eligible


@pytest.mark.asyncio
async def test_g_fresh_event_below_threshold_is_not_selected(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    """The freshest possible event still must not bypass the score threshold - freshness
    priority is an ordering concern only, never a substitute for the eligibility/score gate."""
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score - 1)

        eligible = await _select_eligible_events(session)

        assert event.id not in eligible


def test_h_ordering_contains_no_source_type_reference() -> None:
    """Structural: the M5.2 ordering fix is source-agnostic by construction - it reads only
    NewsEvent.published_at/.collected_at, never NewsSource.type or any per-source-type branch."""
    source = Path("worker/content_cycle.py").read_text(encoding="utf-8")
    assert "SourceType" not in source
    assert "source.type" not in source
    assert "source_type" not in source


def test_i_content_cycle_module_imports_no_llm_gateway_or_capability_execution() -> None:
    """Structural: the M5.2 change (a `func`/`NewsEvent` join for ordering only) introduces no
    new provider-call surface - content_cycle.py still only imports CapabilityRegistry as a
    type, never the gateway/executor machinery that would actually dispatch a call."""
    import_lines = [
        line.strip() for line in Path("worker/content_cycle.py").read_text(encoding="utf-8").splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    for line in import_lines:
        assert "llm_gateway" not in line
        assert "capabilities.executor" not in line


# ---------------------------------------------------------------------------
# run_content_cycle() - orchestration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_content_cycle_sequential_no_gather_and_notifies_after_draft_creation(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    source_text = Path("worker/content_cycle.py").read_text(encoding="utf-8")
    assert "gather" not in source_text

    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    with patch(
        "worker.content_cycle.send_editorial_card",
        new=AsyncMock(return_value=NotificationOutcome(chat_id=1, rendered_html="<html>", sent=False)),
    ) as mock_notify:
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.eligible_found == 1
    assert result.completed == 1
    assert result.failed == 0
    mock_notify.assert_called_once()
    assert result.dry_run_rendered == 1  # content_generation_dry_run defaults True

    async with factory() as verify_session:
        content_gen_tasks = (
            await verify_session.execute(
                select(EditorialTask).where(
                    EditorialTask.event_id == event.id,
                    EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.CONTENT_GENERATION.value,
                )
            )
        ).scalars().all()
        assert len(content_gen_tasks) == 1
        assert content_gen_tasks[0].status == TaskStatus.COMPLETED

        drafts = (
            await verify_session.execute(select(ContentDraft).where(ContentDraft.task_id == content_gen_tasks[0].id))
        ).scalars().all()
        assert len(drafts) == 1

        # NEWS_ANALYSIS task itself must never be mutated by the content cycle.
        news_analysis_tasks = (
            await verify_session.execute(
                select(EditorialTask).where(
                    EditorialTask.event_id == event.id,
                    EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
                )
            )
        ).scalars().all()
        assert len(news_analysis_tasks) == 1
        assert news_analysis_tasks[0].status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_run_content_cycle_dry_run_never_calls_bot_send_message(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    assert settings.content_generation_dry_run is True  # the safe default, exercised here directly
    result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_message.assert_not_called()
    assert result.dry_run_rendered == 1
    assert result.notified == 0
