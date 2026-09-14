"""INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §8/§9/§12: durable, idempotent Instagram publication
lifecycle management - `database.models.instagram_publication_job.InstagramPublicationJob` is the
durable backing; this module is the one real service-layer entry point every future live-publish
call site must use, mirroring `services.editorial_pipeline.recovery_service.RecoveryService`'s own
established shape and concurrency-safety pattern exactly (never a second, divergent convention).
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_publication_job import InstagramPublicationJob, InstagramPublicationState

logger = logging.getLogger(__name__)

_OPEN_STATES = (
    InstagramPublicationState.NOT_ATTEMPTED, InstagramPublicationState.CREATING_CONTAINER,
    InstagramPublicationState.CONTAINER_CREATED, InstagramPublicationState.PUBLISHING,
    InstagramPublicationState.AMBIGUOUS,
)


def compute_idempotency_key(*, platform: str, package_identity: str, content_format: str, schema_version: str) -> str:
    """§12's own explicit minimum: `platform` + `content/package identity` + `format/version`.
    Deliberately NEVER `InstagramContentPackage.package_id` (a random `uuid4()` per build - see
    `docs/instagram_production_rollout_1_report.md` §F's own disclosed gap) - `package_identity`
    must be something STABLE across repeated builds of "the same story/opportunity as the same
    format" (e.g. `opportunity.id` or `story_id`), so a genuine retry recomputes the SAME key and
    converges onto the SAME durable row, never a fresh one."""
    payload = f"{platform}:{package_identity}:{content_format}:{schema_version}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class InstagramPublicationStateService:
    """Stateless, like `RecoveryService` - safe to construct fresh per call."""

    async def find_open_job(self, session: AsyncSession, *, idempotency_key: str) -> InstagramPublicationJob | None:
        stmt = (
            select(InstagramPublicationJob)
            .where(InstagramPublicationJob.idempotency_key == idempotency_key)
            .where(InstagramPublicationJob.state.in_(_OPEN_STATES))
            .order_by(InstagramPublicationJob.created_at.desc())
        )
        result = await session.execute(stmt)
        return result.scalars().first()

    async def find_any_job(self, session: AsyncSession, *, idempotency_key: str) -> InstagramPublicationJob | None:
        """Includes terminal (`PUBLISHED`/`FAILED`/`HOLD`) rows too - the ambiguous-write
        reconciliation path (§9) needs to see a PUBLISHED row from a prior attempt even though it
        is no longer "open"."""
        stmt = (
            select(InstagramPublicationJob)
            .where(InstagramPublicationJob.idempotency_key == idempotency_key)
            .order_by(InstagramPublicationJob.created_at.desc())
        )
        result = await session.execute(stmt)
        return result.scalars().first()

    async def get_or_create(
        self, session: AsyncSession, *, idempotency_key: str, package_id: str, package_identity: str,
        content_format: str, account_key: str = "default",
    ) -> InstagramPublicationJob:
        """The one real entry point before any publish attempt begins. Returns the EXISTING open
        row for this exact idempotency identity if one already exists (a genuine retry converges
        onto it, never creating a duplicate) - concurrency-safe via the SAME SAVEPOINT +
        `IntegrityError`-recovery pattern `services.editorial_pipeline.recovery_service.
        RecoveryService.create_or_retry()` already established for Telegram recovery (RUNTIME-
        CLOSURE-1 §23) - never a second, divergent concurrency convention."""
        existing = await self.find_open_job(session, idempotency_key=idempotency_key)
        if existing is not None:
            return existing

        job = InstagramPublicationJob(
            idempotency_key=idempotency_key, package_id=package_id, package_identity=package_identity,
            content_format=content_format, account_key=account_key, state=InstagramPublicationState.NOT_ATTEMPTED,
            attempt_count=0,
        )
        try:
            async with session.begin_nested():
                session.add(job)
                await session.flush()
        except IntegrityError:
            winner = await self.find_open_job(session, idempotency_key=idempotency_key)
            if winner is None:  # pragma: no cover - the violation proves a row exists
                raise
            return winner
        logger.info(
            "instagram_publication_job_created",
            extra={"idempotency_key": idempotency_key, "job_id": str(job.id), "package_identity": package_identity},
        )
        return job

    async def transition(
        self, session: AsyncSession, *, job: InstagramPublicationJob, state: InstagramPublicationState,
        container_ids: list[str] | None = None, media_id: str | None = None, permalink: str | None = None,
        failure_class: str | None = None, increment_attempt: bool = False,
    ) -> InstagramPublicationJob:
        job.state = state
        if container_ids is not None:
            job.container_ids = container_ids
        if media_id is not None:
            job.media_id = media_id
        if permalink is not None:
            job.permalink = permalink
        if failure_class is not None:
            job.failure_class = failure_class
        if increment_attempt:
            job.attempt_count += 1
        if state in (InstagramPublicationState.PUBLISHED, InstagramPublicationState.FAILED, InstagramPublicationState.HOLD):
            job.resolved_at = datetime.now(timezone.utc)
        await session.flush()
        logger.info(
            "instagram_publication_job_transitioned",
            extra={"job_id": str(job.id), "idempotency_key": job.idempotency_key, "state": state.value, "attempt_count": job.attempt_count},
        )
        return job
