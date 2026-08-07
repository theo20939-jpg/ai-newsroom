"""Phase 19 M13: manually-invoked, NEVER auto-run vision-review harness (docs/phase19_m13_
vision_review.md). Mirrors scripts/phase19_m3_editorial_plan_comparison.py's own established
gating/structure exactly.

Reviews one already-selected, already-validated image candidate (from services.image_persistence.
get_editorial_image_candidates()) using the real, LLM-backed MediaVisionReviewCapability -
requires media_vision_review_mode != "off" to even start, and making a real provider call
requires its own, separate, explicit paid-call authorization (this script has NOT been executed
for real as part of this implementation).

Launch with:
    python -m scripts.phase19_m13_vision_review_manual <news_event_id>

No scheduler, cron, or automatic-execution path - this is the ONLY place in this codebase that
ever constructs a real image-bearing GenerateRequest.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capabilities.media_vision_review_capability import CAPABILITY_NAME, MediaVisionReviewCapability
from capabilities.registry import CapabilityRegistry
from core.config import settings
from core.logging import setup_logging
from database.models.editorial_task import TaskPriority
from database.models.news_event import NewsEvent
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import (
    BusinessContext,
    CapabilityContext,
    ExecutionContext,
    NewsEventSnapshot,
    RuntimeContext,
    WorkflowExecutionStateSnapshot,
)
from services.image_persistence import EditorialImageCandidate, get_editorial_image_candidates, read_candidate_bytes
from services.media_vision_review_persistence import persist_media_vision_review

logger = logging.getLogger(__name__)

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_MIME_BY_FORMAT = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif"}


class VisionReviewModeNotEnabledError(Exception):
    """Refuses to run unless media_vision_review_mode != 'off' - defense-in-depth against
    accidental invocation, independent of whatever gates the caller's own environment has."""


@dataclass(frozen=True)
class VisionReviewOutcome:
    event_id: UUID
    image_candidate_id: str | None
    review: dict | None
    generated_at: str


def _to_data_uri(candidate: EditorialImageCandidate) -> str | None:
    data = read_candidate_bytes(candidate)
    if data is None:
        return None
    mime = _MIME_BY_FORMAT.get((candidate.image_format or "").upper(), "image/jpeg")
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


async def run_vision_review_for_event(
    event_id: UUID,
    *,
    capability_registry: CapabilityRegistry | None = None,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
) -> VisionReviewOutcome:
    if settings.media_vision_review_mode == "off":
        raise VisionReviewModeNotEnabledError(
            "media_vision_review_mode must be explicitly set to 'shadow' to run this script - "
            "currently 'off'."
        )

    prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
    registry = capability_registry
    if registry is None:
        ai_layer = assemble_ai_integration_layer(settings, prompt_repository)
        registry = ai_layer.capability_registry

    async with session_factory() as session:
        news_event = await session.get(NewsEvent, event_id)
        if news_event is None:
            raise ValueError(f"No NewsEvent with id {event_id}")

        candidates = await get_editorial_image_candidates(session, news_event_id=event_id, limit=1)
        if not candidates:
            return VisionReviewOutcome(
                event_id=event_id, image_candidate_id=None, review=None,
                generated_at=datetime.now(timezone.utc).isoformat(),
            )
        candidate = candidates[0]

        data_uri = _to_data_uri(candidate)
        if data_uri is None:
            return VisionReviewOutcome(
                event_id=event_id, image_candidate_id=str(candidate.id), review=None,
                generated_at=datetime.now(timezone.utc).isoformat(),
            )

        _definition, capability = registry.resolve(CAPABILITY_NAME)
        assert isinstance(capability, MediaVisionReviewCapability)

        context = CapabilityContext(
            business=BusinessContext(
                news_event=NewsEventSnapshot(
                    id=news_event.id, title=news_event.title, summary=news_event.summary,
                    content=news_event.content, url=news_event.url, category=news_event.category.value,
                    published_at=news_event.published_at,
                ),
                workflow_state=WorkflowExecutionStateSnapshot(
                    workflow_name="content_generation", workflow_version=1, completed_steps=[],
                ),
                media_review_image_data_uri=data_uri, media_review_story_summary=news_event.title,
            ),
            runtime=RuntimeContext(
                task_id=news_event.id, event_id=news_event.id, capability_name=CAPABILITY_NAME,
                priority=TaskPriority.B, attempt=1, iteration_count=0,
            ),
            execution=ExecutionContext(),
        )
        result = await capability.execute(context)

        if result.structured_output is not None:
            await persist_media_vision_review(
                session, image_candidate_id=candidate.id, structured_output=result.structured_output,
            )
            await session.commit()
        else:
            await session.rollback()

        return VisionReviewOutcome(
            event_id=event_id, image_candidate_id=str(candidate.id), review=result.structured_output,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )


async def main() -> None:
    setup_logging()
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.phase19_m13_vision_review_manual <news_event_id>")
        sys.exit(1)
    event_id = UUID(sys.argv[1])

    outcome = await run_vision_review_for_event(event_id)
    print(json.dumps(asdict(outcome), indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
