"""Pydantic read contract for ContentDraft (Phase 10, docs/
phase10_production_content_pipeline_architecture_contract.md §7.1, corrects MINOR-1 of the
Final Re-Audit).

Mirrors schemas/editorial_task.py's EditorialTaskRead pattern exactly: returned by
ContentDraftService.create_from_result() - never a raw ORM object crosses this boundary.
"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from database.models.content_draft import ContentType


class ContentDraftRead(BaseModel):
    """Returned by ContentDraftService.create_from_result() - never a raw ORM object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    task_id: UUID
    type: ContentType
    title: str | None
    body: str | None
    hashtags: list[str] | None
    version: int
    status: str | None
    created_at: datetime
    updated_at: datetime
