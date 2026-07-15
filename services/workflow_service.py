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

from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import NewsEvent
from schemas.editorial_task import EditorialTaskRead
from schemas.workflow import WorkflowExecutionState, WorkflowType
from workflows.errors import DuplicateActiveTaskError, NewsEventNotFoundError, TaskNotFoundError
from workflows.registry import WorkflowRegistry
from workflows.registry import registry as default_registry

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = (TaskStatus.CREATED, TaskStatus.RUNNING)


async def create_task(
    session: AsyncSession,
    event_id: UUID,
    workflow_type: WorkflowType,
    priority: TaskPriority,
    registry: WorkflowRegistry = default_registry,
) -> EditorialTaskRead:
    """Create an EditorialTask for event_id, or raise if one cannot be created.

    Validation order: NewsEvent existence, then workflow_type registration,
    then active-task uniqueness - each is an independent precondition, so
    unrelated failures are reported without wasting the later checks.
    """
    event = await session.get(NewsEvent, event_id)
    if event is None:
        raise NewsEventNotFoundError(f"No NewsEvent with id {event_id}")

    definition = registry.resolve(workflow_type)  # raises UnknownWorkflowTypeError if unregistered

    existing = await _find_active_task(session, event_id, workflow_type)
    if existing is not None:
        raise DuplicateActiveTaskError(
            f"An active task already exists for event {event_id} / workflow {workflow_type.value} "
            f"(task {existing.id}, status {existing.status.value})"
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
        event_id=event_id,
        priority=priority,
        workflow=state.model_dump(mode="json"),
        status=TaskStatus.CREATED,
        retry_count=0,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    logger.info(
        "Created EditorialTask %s: event=%s workflow=%s priority=%s",
        task.id, event_id, workflow_type.value, priority.value,
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
    """Find an active (CREATED/RUNNING) task for (event_id, workflow_type), if any.

    workflow_type is matched against the JSON snapshot's workflow_name field,
    since EditorialTask has no dedicated column for it.
    """
    result = await session.execute(
        select(EditorialTask).where(
            EditorialTask.event_id == event_id,
            EditorialTask.status.in_(ACTIVE_STATUSES),
        )
    )
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
