"""INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §8/§12: durable Instagram publication lifecycle state -
closes the gap `docs/instagram_production_rollout_1_report.md` §E/§F disclosed
(`PublicationResult` was in-memory only; `InstagramContentPackage.package_id` a random `uuid4()`,
not a deterministic idempotency identity).

One row per REAL publication attempt lifecycle, keyed by a real, deterministic idempotency
identity (`idempotency_key` - see `services.instagram_publication_state.compute_idempotency_key()`)
derived from `(platform, package_identity, content_format, schema_version)`, never from the
package's own random `package_id`. A partial unique index on `(idempotency_key)` WHERE state is
still open mirrors the exact same real, DB-enforced concurrency pattern
`database/models/recovery_job.py::ix_recovery_jobs_open_lifecycle_identity` already established
for Telegram recovery (RUNTIME-CLOSURE-1) - never a second, divergent concurrency-safety
convention."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class InstagramPublicationState(str, enum.Enum):
    """The exact §8/§12 required states - never a second, competing vocabulary."""

    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    CREATING_CONTAINER = "CREATING_CONTAINER"
    CONTAINER_CREATED = "CONTAINER_CREATED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    AMBIGUOUS = "AMBIGUOUS"
    HOLD = "HOLD"


_OPEN_STATES = ("NOT_ATTEMPTED", "CREATING_CONTAINER", "CONTAINER_CREATED", "PUBLISHING", "AMBIGUOUS")
"""States a retry/reconciliation attempt may still act on - `PUBLISHED`/`FAILED`/`HOLD` are
terminal for THIS row (a genuinely new attempt after `FAILED`/`HOLD` gets a NEW row only if the
caller deliberately changes the identity inputs - e.g. a materially different package - never an
automatic re-open of a resolved row)."""


class InstagramPublicationJob(Base):
    __tablename__ = "instagram_publication_jobs"
    __table_args__ = (
        Index(
            "ix_instagram_publication_jobs_open_identity", "idempotency_key",
            unique=True, postgresql_where=text(f"state IN ({', '.join(repr(s) for s in _OPEN_STATES)})"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    package_id: Mapped[str] = mapped_column(String(64), nullable=False)
    package_identity: Mapped[str] = mapped_column(String(255), nullable=False)  # opportunity_id/story_id-derived, human-inspectable
    content_format: Mapped[str] = mapped_column(String(32), nullable=False)
    account_key: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    state: Mapped[InstagramPublicationState] = mapped_column(
        Enum(InstagramPublicationState, name="instagram_publication_state"), nullable=False,
        default=InstagramPublicationState.NOT_ATTEMPTED, index=True,
    )
    container_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    media_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    permalink: Mapped[str | None] = mapped_column(String(500), nullable=True)
    failure_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
