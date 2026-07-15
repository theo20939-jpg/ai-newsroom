"""Pydantic read/write contracts for EditorialTask (Phase 5).

Reuses TaskPriority/TaskStatus from database.models.editorial_task rather
than duplicating them, following the precedent set by
schemas/source_import.py (which reuses SourceType from database.models).
"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from database.models.editorial_task import TaskPriority, TaskStatus
from schemas.workflow import WorkflowType


class EditorialTaskCreate(BaseModel):
    """Input to WorkflowService.create_task()."""

    event_id: UUID
    workflow_type: WorkflowType
    priority: TaskPriority


class EditorialTaskRead(BaseModel):
    """Returned by WorkflowService.create_task()/get_task() - never a raw ORM object.

    current_step is derived from EditorialTask.workflow (JSON) at read time -
    it is not a database column.
    """

    id: UUID
    event_id: UUID
    priority: TaskPriority
    status: TaskStatus
    retry_count: int
    current_step: str | None
    created_at: datetime
    updated_at: datetime
