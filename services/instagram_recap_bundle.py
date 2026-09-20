"""Phase B.4.2: the smallest bridge from the EXISTING Newsroom recap selection to an Instagram
NEWS_RECAP bundle. It never ranks or selects stories itself - `services/weekly_recap_selection.py::
select_weekly_recap_stories()` (or any other existing selection layer) supplies the already-chosen
`WeeklyRecapCandidate`s; this module only attaches, per story, its own evidence and its own stored
media (existing `get_editorial_image_candidates`/`read_candidate_bytes`). No crawler, no new storage,
no scheduling. A story with no usable stored image simply has no asset - the executor then gives
THAT slide a deliberate graphic fallback; another story's image is never substituted."""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Sequence
from uuid import UUID

from PIL import Image
from sqlalchemy import select

from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.news_event import NewsEvent
from schemas.workflow import WorkflowType
from services.image_persistence import get_editorial_image_candidates, read_candidate_bytes
from services.weekly_recap_selection import WeeklyRecapCandidate

MIN_RECAP_STORIES = 4
MAX_RECAP_STORIES = 6
_MIN_IMAGE_SIDE = 256


@dataclass(frozen=True)
class RecapStory:
    key: str
    story_id: str
    event_id: str
    title: str
    evidence: list[str]
    image_bytes: bytes | None = None
    source_ref: str | None = None


@dataclass(frozen=True)
class InstagramRecapBundle:
    stories: tuple[RecapStory, ...] = field(default_factory=tuple)

    @property
    def subjects(self) -> list[str]:
        return [story.key for story in self.stories]

    @property
    def evidence(self) -> list[str]:
        return [line for story in self.stories for line in story.evidence]

    @property
    def available_assets(self) -> dict[str, bytes]:
        return {story.key: story.image_bytes for story in self.stories if story.image_bytes}

    @property
    def refs(self) -> dict[str, str]:
        return {story.key: story.source_ref for story in self.stories if story.source_ref}


def _research_facts(workflow: dict[str, Any] | None) -> list[str]:
    if not workflow:
        return []
    for step in workflow.get("step_results", []):
        if step.get("step_name") == "research" and step.get("status") == "SUCCESS":
            result = step.get("result")
            if isinstance(result, dict) and isinstance(result.get("facts"), list):
                return [f for f in result["facts"] if isinstance(f, str)][:3]
    return []


def _decodable(data: bytes) -> bool:
    try:
        with Image.open(BytesIO(data)) as check:
            check.verify()
        with Image.open(BytesIO(data)) as decoded:
            return min(decoded.size) >= _MIN_IMAGE_SIDE
    except (OSError, ValueError):
        return False


async def _story_media(session: Any, event_id: UUID) -> tuple[bytes | None, str | None]:
    for candidate in await get_editorial_image_candidates(session, news_event_id=event_id, limit=10):
        if candidate.is_expired:
            continue
        data = read_candidate_bytes(candidate)
        if data and _decodable(data):
            return data, candidate.candidate_id
    return None, None


async def build_instagram_recap_bundle(
    session: Any, *, selected: Sequence[WeeklyRecapCandidate],
) -> InstagramRecapBundle | None:
    """`None` when fewer than MIN_RECAP_STORIES stories are supplied (a recap needs a real set)."""
    chosen = list(selected)[:MAX_RECAP_STORIES]
    if len(chosen) < MIN_RECAP_STORIES:
        return None
    stories: list[RecapStory] = []
    for index, candidate in enumerate(chosen, start=1):
        event = await session.get(NewsEvent, candidate.representative_event_id)
        if event is None:
            continue
        key = f"story_{index}"
        task = await session.scalar(
            select(EditorialTask)
            .where(
                EditorialTask.event_id == event.id,
                EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
                EditorialTask.status == TaskStatus.COMPLETED,
            )
            .order_by(EditorialTask.updated_at.desc()).limit(1)
        )
        evidence = [f"[{key}] {event.title}"] + [f"[{key}] {fact}" for fact in _research_facts(task.workflow if task else None)]
        data, ref = await _story_media(session, event.id)
        stories.append(RecapStory(
            key=key, story_id=str(candidate.story_id), event_id=str(event.id), title=event.title,
            evidence=evidence, image_bytes=data, source_ref=ref,
        ))
    if len(stories) < MIN_RECAP_STORIES:
        return None
    return InstagramRecapBundle(stories=tuple(stories))
