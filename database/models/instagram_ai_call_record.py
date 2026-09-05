"""INSTAGRAM-GROWTH-3, item 17: cost accounting for Instagram's own AI Gateway usage (semantic
matching, Creative Director, reference analysis). `database/models/ai_execution.py::AIExecution`
cannot be reused here - its `task_id` column is a NOT-NULL foreign key to `editorial_tasks.id`, and
none of these Instagram features run inside a real EditorialTask/Workflow (they use the same
lighter-weight `capabilities/gateway_call.py::call_generate()` one-shot path
services/business_context_command_parser.py already established as sanctioned for a non-Story-bound
caller). Rather than forcing a synthetic EditorialTask into existence purely to satisfy that FK (an
"ill-fitting architecture graft", to use that module's own words), this is a small, honestly-scoped,
additive table capturing exactly the same underlying facts (capability/model/tokens/cost),
populated from the SAME `schemas.capability.CapabilityCall`/`services.cost_tracker.compute_call_cost`
machinery every real Capability already uses - never an independently-invented cost formula."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class InstagramAICallRecord(Base):
    __tablename__ = "instagram_ai_call_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    capability_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    prompt_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Nullable, never a fabricated 0 - stays NULL if pricing for `model_used` is unavailable
    # (mirrors services/instagram_performance.py's own "unobserved stays null" discipline).
    cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
