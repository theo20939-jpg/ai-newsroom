"""Workflow Service: creates and reads EditorialTask rows (Workflow Service).

Scoped to exactly two functions - create_task() and get_task(). Never
changes an EditorialTask's status: that is workflows.runner.WorkflowRunner's
exclusive responsibility. Mirrors the plain-function style already used by
services/collector.py and services/deduplication.py rather than a class.
"""
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.news_event import NewsEvent
from schemas.editorial_task import EditorialTaskCreate, EditorialTaskRead
from schemas.workflow import WorkflowExecutionState, WorkflowType
from workflows.errors import DuplicateActiveTaskError, NewsEventNotFoundError, TaskNotFoundError
from workflows.registry import WorkflowRegistry
from workflows.registry import registry as default_registry

logger = logging.getLogger(__name__)


async def create_task(
    session: AsyncSession,
    command: EditorialTaskCreate,
    registry: WorkflowRegistry = default_registry,
    *,
    commit: bool = True,
) -> EditorialTaskRead:
    """Create an EditorialTask from a validated EditorialTaskCreate command, or raise.

    Validation order: NewsEvent existence, then workflow_type registration,
    then existing-task uniqueness - each is an independent precondition, so
    unrelated failures are reported without wasting the later checks. No ORM
    model crosses this boundary in either direction - callers pass and
    receive only these Pydantic schemas.

    `commit` (TELEGRAPH Checkpoint 3 correctness fix, additive/backward-compatible - defaults to
    `True`, byte-identical to every pre-existing caller's behavior): pass `commit=False` when the
    caller wants this INSERT to participate in a larger caller-owned transaction (e.g. services.
    telegraph_research_processor.process_approved_telegraph_proposal()'s own atomic claim+create+
    link sequence) rather than committing independently. `session.flush()` + `session.refresh()`
    are still performed either way, so the returned `EditorialTaskRead` always reflects real,
    server-assigned values (`id`, `created_at`/`updated_at` defaults) even before the caller's own
    later commit - `refresh()` reads the current transaction's own uncommitted-but-flushed row,
    which is always visible to the same session/connection.
    """
    event = await session.get(NewsEvent, command.event_id)
    if event is None:
        raise NewsEventNotFoundError(f"No NewsEvent with id {command.event_id}")

    definition = registry.resolve(command.workflow_type)  # raises UnknownWorkflowTypeError if unregistered

    existing = await _find_active_task(session, command.event_id, command.workflow_type)
    if existing is not None:
        raise DuplicateActiveTaskError(
            f"A task already exists for event {command.event_id} / "
            f"workflow {command.workflow_type.value} (task {existing.id}, status {existing.status.value})"
        )

    state = WorkflowExecutionState(
        workflow_name=definition.name,
        workflow_version=definition.version,
        current_step=definition.steps[0].name,
        completed_steps=[],
        iteration_count=0,
        step_results=[],
        failure=None,
    )

    task = EditorialTask(
        event_id=command.event_id,
        priority=command.priority,
        workflow=state.model_dump(mode="json"),
        status=TaskStatus.CREATED,
        retry_count=0,
    )
    session.add(task)
    if commit:
        await session.commit()
    else:
        await session.flush()
    await session.refresh(task)

    logger.info(
        "Created EditorialTask %s: event=%s workflow=%s priority=%s",
        task.id, command.event_id, command.workflow_type.value, command.priority.value,
    )
    return _to_read_schema(task)


async def get_task(session: AsyncSession, task_id: UUID) -> EditorialTaskRead:
    """Look up one EditorialTask by id, or raise TaskNotFoundError. Never mutates it."""
    task = await session.get(EditorialTask, task_id)
    if task is None:
        raise TaskNotFoundError(f"No EditorialTask with id {task_id}")
    return _to_read_schema(task)


async def _find_active_task(
    session: AsyncSession, event_id: UUID, workflow_type: WorkflowType
) -> EditorialTask | None:
    """Find an existing task for (event_id, workflow_type), in any status, if any.

    workflow_type is matched against the JSON snapshot's workflow_name field,
    since EditorialTask has no dedicated column for it.

    Phase 15 M1: matches any TaskStatus, not only CREATED/RUNNING. Phase 15 M0
    found 108 NewsEvent rows with duplicate NEWS_ANALYSIS tasks, caused by this
    query's previous active-only scope: a status.in_(CREATED, RUNNING) filter
    means a COMPLETED or FAILED sibling is invisible here, so both this
    function's callers - create_task()'s own duplicate check, and
    services.triage_orchestrator._select_recovery_candidates()'s "no active
    task" gate - would treat an event whose task already finished as if no
    task had ever been created for it, and (for a recovered event) let a
    fresh, unwanted duplicate task be created. The one-task-per-(event,
    workflow_type) contract this module documents was always meant to be
    permanent, not "until the task leaves CREATED/RUNNING" - retries of a
    single task happen in place (EditorialTask.retry_count, entirely inside
    WorkflowRunner) and never call create_task() a second time, so widening
    this check cannot affect legitimate in-task retry/failure handling.
    """
    result = await session.execute(select(EditorialTask).where(EditorialTask.event_id == event_id))
    for task in result.scalars().all():
        if task.workflow is not None and task.workflow.get("workflow_name") == workflow_type.value:
            return task
    return None


def _to_read_schema(task: EditorialTask) -> EditorialTaskRead:
    """Build EditorialTaskRead from an ORM row - current_step is derived from the JSON snapshot."""
    current_step = (task.workflow or {}).get("current_step")
    return EditorialTaskRead(
        id=task.id,
        event_id=task.event_id,
        priority=task.priority,
        status=task.status,
        retry_count=task.retry_count,
        current_step=current_step,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )
