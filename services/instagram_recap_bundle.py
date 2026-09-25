"""Phase B.4.2: the smallest bridge from the EXISTING Newsroom recap selection to an Instagram
NEWS_RECAP bundle. It never ranks or selects stories itself - `services/weekly_recap_selection.py::
select_weekly_recap_stories()` (or any other existing selection layer) supplies the already-chosen
`WeeklyRecapCandidate`s; this module only attaches, per story, its own evidence and its own stored
media (existing `get_editorial_image_candidates`/`read_candidate_bytes`, filled when needed by the existing
image discovery for the story's OWN premise-relevant events). No new crawler, no new storage, no scheduling.
A story with no usable image simply has no asset - the executor then gives THAT slide a deliberate graphic
fallback; another story's image is never substituted."""
from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

MIN_RECAP_STORIES = 4
MAX_RECAP_STORIES = 8  # the weekly editor's product contract is 5-8 stories; a carousel carries hook + 8 stories + closing = 10 slides
_MIN_IMAGE_SIDE = 256
MIN_HERO_SIDE = 400  # a story photo that carries a slide; smaller images stay a fallback only
MAX_MEDIA_DISCOVERY_EVENTS = 4  # per story: image discovery for at most this many of its own events without stored candidates


@dataclass(frozen=True)
class RecapStory:
    key: str
    story_id: str
    event_id: str
    title: str
    evidence: list[str]
    image_bytes: bytes | None = None
    source_ref: str | None = None
    # KAGE recap story preservation contract: what Phase A and the Creative Director must carry for this story
    premise: str = ""
    category: str = ""
    evidence_quality: str = ""
    evidence_sources: tuple[str, ...] = ()  # provenance per evidence item (parallel to `evidence`): title / news_analysis / source URL


@dataclass(frozen=True)
class RecapEvidence:
    """One recap evidence item: the story it belongs to and its provenance are metadata; `exact_text` is the only grounding string."""

    story_key: str
    source: str
    exact_text: str
    display_preview: str = ""


@dataclass(frozen=True)
class InstagramRecapBundle:
    stories: tuple[RecapStory, ...] = field(default_factory=tuple)

    @property
    def subjects(self) -> list[str]:
        return [story.key for story in self.stories]

    @property
    def evidence_items(self) -> list[RecapEvidence]:
        items, seen = [], set()
        for story in self.stories:
            for i, text in enumerate(story.evidence):
                if text in seen:  # one exact text belongs to the first story that carries it
                    continue
                seen.add(text)
                source = story.evidence_sources[i] if i < len(story.evidence_sources) else ""
                items.append(RecapEvidence(story_key=story.key, source=source, exact_text=text,
                                           display_preview=text if len(text) <= 160 else text[:159].rstrip() + "…"))
        return items

    @property
    def evidence(self) -> list[str]:
        """The EXACT evidence texts (the grounding set) - story identity is `evidence_story_keys`, never a label on the text."""
        return [item.exact_text for item in self.evidence_items]

    @property
    def evidence_story_keys(self) -> dict[str, str]:
        return {item.exact_text: item.story_key for item in self.evidence_items}

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


def _final_visual(data: bytes) -> bool:
    """The deterministic SOURCE_SUITABLE_FOR_FINAL_VISUAL profile (a photo / object, not a flat article or headline card)."""
    from services.instagram_asset_profile import profile_asset

    try:
        with Image.open(BytesIO(data)) as decoded:
            return profile_asset(decoded.convert("RGBA" if decoded.mode == "RGBA" else "RGB"), subject_key="probe").suitable_for_final_visual
    except (OSError, ValueError):
        return False


async def _stored_media(session: Any, event_id: UUID) -> list[tuple[bytes, str]]:
    found: list[tuple[bytes, str]] = []
    for candidate in await get_editorial_image_candidates(session, news_event_id=event_id, limit=10):
        if candidate.is_expired:
            continue
        data = read_candidate_bytes(candidate)
        if data and _decodable(data):
            found.append((data, candidate.candidate_id))
    return found


async def _discover(session: Any, event_id: UUID) -> None:
    """The EXISTING image discovery (services.image_intelligence.run_shadow_discovery) for one of the story's own events - only when image
    intelligence is on; its finalists land in the same candidate store `_stored_media` reads. Never raises."""
    from core.config import settings
    from database.models.news_source import NewsSource
    from services.image_intelligence import run_shadow_discovery

    if settings.image_intelligence_mode != "shadow":
        return
    try:
        event = await session.get(NewsEvent, event_id)
        source = await session.get(NewsSource, event.source_id) if event is not None else None
        if event is None or source is None:
            return
        await run_shadow_discovery(event_id=event.id, source_type=source.type, content=event.content, article_url=event.url, mode="shadow",
                                   event_title=event.title, source_name=source.name, session=session)
    except Exception:  # noqa: BLE001 - media is optional: a story without a found image gets its graphic card
        logger.warning("instagram_recap_media_discovery_failed", extra={"event_id": str(event_id)})


async def _story_media(session: Any, event_ids: Sequence[UUID]) -> tuple[bytes | None, str | None]:
    """The story's image: a photo / object image (never a flat text card when a real one exists) from the story's OWN events - the
    representative first, then the confirmed member events whose bodies the recap sanitizer kept as about this story's premise. Stored
    candidates first; image discovery runs only for the events still needed, bounded by MAX_MEDIA_DISCOVERY_EVENTS."""
    fallback: tuple[bytes | None, str | None] = (None, None)
    discovered = 0
    for event_id in event_ids:
        found = await _stored_media(session, event_id)
        if not found and discovered < MAX_MEDIA_DISCOVERY_EVENTS:
            discovered += 1
            await _discover(session, event_id)
            found = await _stored_media(session, event_id)
        for data, ref in found:
            if min(Image.open(BytesIO(data)).size) >= MIN_HERO_SIDE and _final_visual(data):
                return data, ref
            if fallback[0] is None:
                fallback = (data, ref)
    return fallback


def _kept_event_ids(premise: str, headlines: list[str], bodies: list[tuple[str, str]], representative_id: Any) -> list[UUID]:
    """The story's own events whose bodies talk about its premise (the same sanitizer the evidence uses) - a polluted Story member's
    image is never this story's picture."""
    from services.instagram_evidence_package import plain_text, sanitize_recap_bodies

    kept, _excluded = sanitize_recap_bodies(premise, headlines, [(ref, plain_text(body)) for ref, body in bodies])
    ids: list[UUID] = []
    for ref, _body in kept:
        parts = ref.split(":")
        if len(parts) >= 2 and parts[0] == "event":
            try:
                event_id = UUID(parts[1])
            except ValueError:
                continue
            if event_id != representative_id and event_id not in ids:
                ids.append(event_id)
    return ids


_MAX_STORY_BODY_EVENTS = 12


async def _story_bodies(session: Any, story_id: Any, representative: Any) -> tuple[list[str], list[tuple[str, str]]]:
    """(headlines, (ref, body)) of the story's CONFIRMED members (origin + update / supporting / semantic-duplicate links - never an
    observability-only link): stored bodies and trusted acquired article text, cleaned on the fly. The recap package then keeps only
    the bodies that talk about the selected premise - the same Story id is not evidence of relevance."""
    from database.models.story_link import NewsEventStoryLink
    from services.article_acquisition import get_effective_acquisition
    from services.evidence_package import TRUSTED_FULL_ARTICLE_STATUSES
    from services.instagram_evidence_package import clean_body
    from services.instagram_feed_planner import CONFIRMED_MATCH_TYPES

    events = [representative]
    if story_id is not None and story_id != representative.id:
        events += list((await session.execute(
            select(NewsEvent).join(NewsEventStoryLink, NewsEventStoryLink.news_event_id == NewsEvent.id)
            .where(NewsEventStoryLink.story_id == story_id, NewsEventStoryLink.match_type.in_(CONFIRMED_MATCH_TYPES),
                   NewsEvent.id != representative.id)
            .limit(_MAX_STORY_BODY_EVENTS)
        )).scalars().all())
    headlines = [e.title for e in events if e.title]
    bodies: list[tuple[str, str]] = []
    for e in events:
        if e.content:
            bodies.append((f"event:{e.id}:body", e.content))
        acquisition = await get_effective_acquisition(session, e.id)
        if acquisition is not None and acquisition.acquisition_status in TRUSTED_FULL_ARTICLE_STATUSES and acquisition.raw_extracted_text:
            bodies.append((f"event:{e.id}:article", clean_body(acquisition.raw_extracted_text, e.title)))
    return headlines, bodies


async def build_instagram_recap_bundle(
    session: Any, *, selected: Sequence[WeeklyRecapCandidate],
) -> InstagramRecapBundle | None:
    """`None` when fewer than MIN_RECAP_STORIES stories are supplied (a recap needs a real set)."""
    pool = list(selected)
    if len(pool) > MAX_RECAP_STORIES:
        # never a silent slice: an accepted pick is never discarded downstream - a selection outside the contract gets no recap
        logger.error("instagram_recap_bundle_over_contract", extra={"selected": len(pool), "max": MAX_RECAP_STORIES})
        return None
    if len(pool) < MIN_RECAP_STORIES:
        return None
    resolved: list[tuple[WeeklyRecapCandidate, Any]] = []
    for candidate in pool:
        event = await session.get(NewsEvent, candidate.representative_event_id)
        if event is None:
            logger.error("instagram_recap_story_event_missing", extra={"story_id": str(candidate.story_id)})
            continue
        resolved.append((candidate, event))
    # Editorial order is the selection layer's alone. Media availability never re-ranks: a story with
    # no usable image simply gets its own graphic fallback later.
    stories: list[RecapStory] = []
    for index, (candidate, event) in enumerate(resolved, start=1):
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
        research = _research_facts(task.workflow if task else None)
        evidence = [event.title] + list(research)
        sources = ["event_title"] + ["news_analysis"] * len(research)
        # KAGE evidence package: a few verbatim lines from the story's own bodies, only those about its premise (never polluted bodies)
        from services.instagram_evidence_package import RECAP_EXCERPTS_PER_STORY, build_recap_story_package

        try:
            headlines, bodies = await _story_bodies(session, candidate.story_id, event)
        except Exception:  # enrichment is optional: without it the story keeps its headline + stored facts, never a polluted body
            logger.warning("instagram_recap_story_bodies_unavailable", extra={"story_id": str(candidate.story_id)})
            headlines, bodies = [event.title or ""], []
        package = await build_recap_story_package(post_id=key, premise=event.title or "", headlines=headlines, bodies=bodies)
        # visual-first recap: the story's picture may come from any of its own premise-relevant events, not only the representative
        data, ref = await _story_media(session, [event.id, *_kept_event_ids(event.title or "", headlines, bodies, event.id)])
        excerpts = package.facts[:RECAP_EXCERPTS_PER_STORY]
        evidence += [item.exact_text for item in excerpts]
        sources += [item.source_url or item.source_type for item in excerpts]
        premise = str(getattr(candidate, "reason", "") or "").split(" - ", 1)[0].strip() or (event.title or "")
        tier = str(getattr(candidate, "relevance_tier", "") or "")
        stories.append(RecapStory(
            key=key, story_id=str(candidate.story_id), event_id=str(event.id), title=event.title,
            evidence=evidence, evidence_sources=tuple(sources), image_bytes=data, source_ref=ref, premise=premise,
            category=tier.removeprefix("INSTAGRAM_WEEKLY_") if tier.startswith("INSTAGRAM_WEEKLY_") else "",
            evidence_quality=package.quality,
        ))
    if len(stories) < MIN_RECAP_STORIES:
        return None
    return InstagramRecapBundle(stories=tuple(stories))
