"""Tests for services.content_draft_service.ContentDraftService (Phase 10 M3, docs/
phase10_production_content_pipeline_architecture_contract.md §7/§7.1/§12).

Most tests use `db_session`/`real_news_event` (real Postgres, rolled back at teardown via
SAVEPOINT) - session-reuse and query-correctness proofs don't need cross-connection durability.
The one mandatory independent-connection durability test (Contract §12 "ContentDraft tests") is
isolated in its own section near the bottom, reusing
`tests.test_triage_orchestrator_claims.independent_session_factory()`/`real_committed_event()`
(Phase 9 M2's own precedent, already reused by Phase 9.5 M2) - the `db_session` fixture's
SAVEPOINT semantics MUST NOT be relied upon for that one test, for the same false-pass reason
Phase 9.5 Contract Audit MAJOR-2 already established.
"""
import ast
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capabilities.executor import CapabilityExecutor
from capabilities.registry import build_registry
from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from integrations.llm_gateway.errors import NoRoutableCandidateError
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.llm_gateway.tools.registry import ToolRegistry
from integrations.prompts.file_repository import FilePromptRepository
from integrations.prompts.protocol import PromptRepository
from schemas.capability import CapabilityUsage
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowRunResult, WorkflowType
from services import workflow_service
from services.content_draft_service import ContentDraftService
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_infra import AllowingBudgetGuard
from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT
from tests.test_triage_orchestrator_claims import independent_session_factory, real_committed_event
from workflows.registry import registry as real_workflow_registry
from workflows.runner import WorkflowRunner

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_INTELLIGENCE_OUTPUT: dict[str, object] = {
    "significance": 0.7,
    "angle": "Market impact",
    "audience_relevance": "General audience",
    "recommendation": "Publish with standard priority",
}

_COPYWRITING_OUTPUT: dict[str, object] = {
    "title": "Example draft title",
    "body": "Example draft body text.",
    "hashtags": ["#example", "#news"],
}

_QUALITY_OUTPUT: dict[str, object] = {"passed": True, "issues": []}


def _prompt_repository() -> PromptRepository:
    return FilePromptRepository(_PROMPTS_ROOT)


def _generate_response(structured_output: dict[str, object]) -> GenerateResponse:
    return GenerateResponse(
        text=None,
        structured_output=structured_output,
        finish_reason="stop",
        model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    )


async def _run_content_generation_to_completed(
    session: AsyncSession, event_id: UUID
) -> tuple[UUID, WorkflowRunResult]:
    """Runs the real, production CONTENT_GENERATION chain (Phase 10 M2) to COMPLETED, exactly
    mirroring tests/test_phase10_workflow_integration.py's technique - returns a genuine
    WorkflowRunResult with a real "copywriting" step_results entry for ContentDraftService to
    consume."""
    gateway = FakeLLMGateway(
        generate_responses=[
            _generate_response(CANONICAL_RESEARCH_OUTPUT),
            _generate_response(_INTELLIGENCE_OUTPUT),
            _generate_response(_COPYWRITING_OUTPUT),
            _generate_response(_QUALITY_OUTPUT),
        ]
    )
    capability_registry = build_registry(gateway, _prompt_repository(), AllowingBudgetGuard(), ToolRegistry())  # type: ignore[arg-type]

    command = EditorialTaskCreate(event_id=event_id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B)
    task = await workflow_service.create_task(session, command)
    executor = CapabilityExecutor(session, task.id, capability_registry)
    result = await WorkflowRunner(executor=executor, registry=real_workflow_registry).run(session, task.id)
    return task.id, result


async def _run_content_generation_to_failed(session: AsyncSession, event_id: UUID) -> tuple[UUID, WorkflowRunResult]:
    """Fails immediately at "research" (the first step) - a genuine FAILED WorkflowRunResult
    with no "copywriting" step_results entry at all, for the misuse-guard tests below."""
    gateway = FakeLLMGateway(generate_error=NoRoutableCandidateError("no candidates"))
    capability_registry = build_registry(gateway, _prompt_repository(), AllowingBudgetGuard(), ToolRegistry())  # type: ignore[arg-type]

    command = EditorialTaskCreate(event_id=event_id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B)
    task = await workflow_service.create_task(session, command)
    executor = CapabilityExecutor(session, task.id, capability_registry)
    result = await WorkflowRunner(executor=executor, registry=real_workflow_registry).run(session, task.id)
    return task.id, result


# ---------------------------------------------------------------------------
# Happy path: field mapping, task association, fixed status/type/version.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_from_result_persists_expected_fields(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    task_id, result = await _run_content_generation_to_completed(db_session, real_news_event.id)
    assert result.status == "COMPLETED"

    draft = await ContentDraftService(db_session).create_from_result(task_id, result)

    assert draft.task_id == task_id
    assert draft.type == ContentType.POST
    assert draft.title == _COPYWRITING_OUTPUT["title"]
    assert draft.body == _COPYWRITING_OUTPUT["body"]
    assert draft.hashtags == _COPYWRITING_OUTPUT["hashtags"]
    assert draft.version == 1
    assert draft.status == "draft"
    assert draft.id is not None
    assert draft.created_at is not None
    assert draft.updated_at is not None


@pytest.mark.asyncio
async def test_create_from_result_creates_exactly_one_row(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    task_id, result = await _run_content_generation_to_completed(db_session, real_news_event.id)

    await ContentDraftService(db_session).create_from_result(task_id, result)

    rows = (await db_session.execute(select(ContentDraft).where(ContentDraft.task_id == task_id))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_session_reuse_after_workflow_runner_commit_succeeds(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    """Proves the expire_on_commit=False precondition (Contract §7.1) actually holds: the same
    session already used for WorkflowRunner.run()'s own commit is reused, unmodified, for a
    subsequent ContentDraftService(session).create_from_result() call, which itself succeeds and
    commits - not merely assumed by analogy to Phase 9.5."""
    task_id, result = await _run_content_generation_to_completed(db_session, real_news_event.id)
    assert result.status == "COMPLETED"  # WorkflowRunner.run() already committed on this session

    draft = await ContentDraftService(db_session).create_from_result(task_id, result)

    assert draft.task_id == task_id
    reloaded = await db_session.get(ContentDraft, draft.id)
    assert reloaded is not None


# ---------------------------------------------------------------------------
# Misuse guard: never on a FAILED run (Contract §12 "ContentDraft tests").
# "Never mid-run" is structural, not separately testable: WorkflowRunner.run() (frozen,
# unmodified) only ever returns a WorkflowRunResult once terminal - there is no way to obtain a
# "mid-run" WorkflowRunResult object to call create_from_result() with.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_workflow_run_never_produces_a_content_draft(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    task_id, result = await _run_content_generation_to_failed(db_session, real_news_event.id)
    assert result.status == "FAILED"
    assert [r.step_name for r in result.step_results] == ["research"]

    # A caller that (incorrectly) called create_from_result() on a FAILED result gets a loud,
    # typed failure - not a silently-created, wrong ContentDraft (Contract §7.1: no reformatting,
    # no silent discarding of required structured content).
    with pytest.raises(ValueError, match="no successful 'copywriting' step"):
        await ContentDraftService(db_session).create_from_result(task_id, result)

    # And, following the correct calling convention (Contract §9: only call on COMPLETED),
    # exactly zero ContentDraft rows exist for this task - never on a FAILED run.
    rows = (await db_session.execute(select(ContentDraft).where(ContentDraft.task_id == task_id))).scalars().all()
    assert rows == []


# ---------------------------------------------------------------------------
# Ownership: no Capability ever creates a ContentDraft (Contract §7, §12).
# ---------------------------------------------------------------------------


def test_capabilities_never_import_content_draft() -> None:
    """Mechanical check, mirroring the architecture validator's own named-file pattern: no file
    under capabilities/ imports database.models.content_draft.ContentDraft - proven, not merely
    asserted in prose."""
    capabilities_dir = Path("capabilities")
    for path in sorted(capabilities_dir.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)
        assert not any("content_draft" in module for module in imported_modules), (
            f"{path} imports something from content_draft - Capabilities MUST NOT create, "
            "update, or hold any reference to a ContentDraft row (Contract §7)."
        )


# ---------------------------------------------------------------------------
# Discoverability (Contract §7.1/§14, corrects MINOR-1 of the Final Re-Audit's own re-audit):
# a COMPLETED CONTENT_GENERATION task with no ContentDraft is discoverable via a direct query
# against existing, unmodified columns - EditorialTask.status (indexed), EditorialTask.workflow
# (JSON, workflow_name key, matching services/workflow_service.py::_find_active_task()'s own
# established convention of filtering this field in Python, not via a new SQL JSON operator),
# and ContentDraft.task_id (FK). No new column, index, or migration.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completed_content_generation_tasks_without_drafts_are_discoverable(
    db_session: AsyncSession,
) -> None:
    async def _new_event() -> NewsEvent:
        source = NewsSource(name="Discoverability Test Source", type=SourceType.RSS, active=True)
        db_session.add(source)
        await db_session.flush()
        event = NewsEvent(
            source_id=source.id,
            title="Discoverability test event",
            content="Test content",
            category=EventCategory.AI,
            hash=f"discoverability-test-{uuid.uuid4()}",
        )
        db_session.add(event)
        await db_session.flush()
        return event

    event_with_draft = await _new_event()
    event_without_draft = await _new_event()

    task_id_with_draft, result_with_draft = await _run_content_generation_to_completed(db_session, event_with_draft.id)
    await ContentDraftService(db_session).create_from_result(task_id_with_draft, result_with_draft)

    task_id_without_draft, result_without_draft = await _run_content_generation_to_completed(
        db_session, event_without_draft.id
    )
    assert result_without_draft.status == "COMPLETED"
    # Deliberately never calling ContentDraftService here - simulates Contract §7.1's disclosed
    # gap (e.g. a transient DB error between WorkflowRunner.run() and ContentDraftService).

    # The discovery query itself: status is the one dedicated, indexed EditorialTask column
    # (database/models/editorial_task.py); workflow_name is read from the JSON `workflow` blob in
    # Python, exactly as _find_active_task() already does; ContentDraft.task_id is the existing FK.
    completed = (
        (await db_session.execute(select(EditorialTask).where(EditorialTask.status == TaskStatus.COMPLETED)))
        .scalars()
        .all()
    )
    completed_content_generation_tasks = [
        t for t in completed if t.workflow is not None and t.workflow.get("workflow_name") == WorkflowType.CONTENT_GENERATION.value
    ]
    candidate_ids = [t.id for t in completed_content_generation_tasks]
    drafted_ids = {
        row[0]
        for row in (
            await db_session.execute(select(ContentDraft.task_id).where(ContentDraft.task_id.in_(candidate_ids)))
        ).all()
    }
    missing_ids = {t.id for t in completed_content_generation_tasks} - drafted_ids

    assert task_id_without_draft in missing_ids
    assert task_id_with_draft not in missing_ids


# ---------------------------------------------------------------------------
# Mandatory independent-connection durability test (Contract §12, corrects MINOR-2 of the
# Contract Audit) - isolated here, deliberately separate from the tests above, mirroring Phase
# 9.5 M2's own precedent for the same reason: this is the highest-scrutiny test in this
# milestone.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine, session_factory = independent_session_factory()
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_content_draft_is_durable_to_a_genuinely_independent_connection(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with real_committed_event(factory) as event_id:
        async with factory() as run_session:
            task_id, result = await _run_content_generation_to_completed(run_session, event_id)
            assert result.status == "COMPLETED"
            draft = await ContentDraftService(run_session).create_from_result(task_id, result)

        # A physically separate connection from the one that produced the commit - proving
        # genuine cross-connection durability, not merely same-session/SAVEPOINT visibility.
        async with factory() as independent_session:
            persisted = await independent_session.get(ContentDraft, draft.id)
            assert persisted is not None
            assert persisted.task_id == task_id
            assert persisted.title == _COPYWRITING_OUTPUT["title"]
            assert persisted.body == _COPYWRITING_OUTPUT["body"]
            assert persisted.hashtags == _COPYWRITING_OUTPUT["hashtags"]

        # Explicit cleanup before real_committed_event's own teardown deletes the EditorialTask -
        # ContentDraft.task_id has no ON DELETE CASCADE, so the draft must go first.
        async with factory() as cleanup_session:
            existing_draft = await cleanup_session.get(ContentDraft, draft.id)
            if existing_draft is not None:
                await cleanup_session.delete(existing_draft)
                await cleanup_session.commit()
