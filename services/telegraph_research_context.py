"""TELEGRAPH Checkpoint 3: deterministic article research context bundle.

Builds a compact, bounded, source-aware evidence bundle from already-persisted data for exactly
one `Story` - the input a Deep Research LLM call synthesizes from. Zero LLM/Gateway calls, zero
web/fetch calls anywhere in this module (see tests/test_telegraph_research_context.py's own
structural source-scan tests).

Reuses, never duplicates, `services/story_context.py::build_story_timeline()` for chronology -
exactly the reuse Checkpoint 1 (services/telegraph_topic_candidates.py) already established for
the same function. The per-contributing-event NEWS_ANALYSIS fetch below deliberately mirrors
that module's own private `_fetch_latest_news_analysis_workflows()` (same batched-query shape),
duplicated rather than imported per this codebase's own established per-module-private-helper
convention (that name is underscore-prefixed and belongs to that module only) - the one
difference is this module needs each contributing event's OWN facts/gaps/intelligence, not just
the Story-wide maxes Checkpoint 1's `StoryEvidenceSummary` computes.

Contributing match types (must stay in sync with Checkpoint 1's own `_CONTRIBUTING_MATCH_TYPES`,
per the Checkpoint 3 brief's explicit "maintain Checkpoint 1's established semantics, do not
regress this" requirement): NEW_STORY / STORY_UPDATE / SUPPORTING_SOURCE contribute chronology
and factual evidence. SEMANTIC_DUPLICATE is counted (a `dedup_duplicate_count` signal only - "may
inform dedup/history") but never becomes independent evidence. UNCERTAIN_MATCH is excluded
entirely - never presented to Deep Research as confirmed story evidence, not even as a count.
"""
from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.news_event import NewsEvent
from database.models.news_event_article_acquisition import NewsEventArticleAcquisition
from database.models.news_event_source_intelligence import NewsEventSourceIntelligence
from database.models.story import Story
from schemas.workflow import WorkflowType
from services.story_context import build_story_timeline
from services.story_memory import NEW_STORY, SEMANTIC_DUPLICATE, STORY_UPDATE, SUPPORTING_SOURCE

_CONTRIBUTING_MATCH_TYPES = frozenset({NEW_STORY, STORY_UPDATE, SUPPORTING_SOURCE})

# Bounding caps - the phase brief's own explicit "keep it bounded" requirement. Deduplication
# happens before truncation, so a Story with many corroborating-but-repetitive events still
# yields a compact, non-redundant bundle rather than merely a truncated one.
_MAX_FACTS = 40
_MAX_GAPS = 15
_MAX_SOURCES = 12
_MAX_TIMELINE_ENTRIES = 20
_MAX_BUNDLE_TEXT_CHARS = 12_000


@dataclass(frozen=True)
class ChronologyEntry:
    """One contributing event's place in the Story's timeline - references only, never full
    article text (news_event.content is deliberately excluded; only title/url/source, mirroring
    services/telegraph_topic_candidates.py's own "references and small metadata only" rule)."""

    event_id: UUID
    title: str
    source: str | None
    url: str | None
    published_at: str | None
    match_type: str
    delta: str
    is_anchor: bool


@dataclass(frozen=True)
class SourceEvidenceEntry:
    """One distinct contributing source, deduplicated by source name."""

    source: str
    event_count: int
    urls: list[str]
    best_acquisition_status: str | None
    reliability_score: float | None


@dataclass(frozen=True)
class ArticleResearchBundle:
    """The complete, bounded input Deep Research synthesizes from. Never article prose, never a
    full DB object, never Telegram presentation text - see module docstring."""

    story_id: UUID
    story_title: str
    story_category: str
    topic_bucket: str
    chronology: list[ChronologyEntry]
    confirmed_facts: list[str]
    known_gaps: list[str]
    representative_significance: float | None
    representative_angle: str | None
    representative_recommendation: str | None
    source_evidence: list[SourceEvidenceEntry]
    dedup_duplicate_count: int
    truncated: bool = field(default=False)


def _extract_step_result(workflow: dict[str, Any] | None, step_name: str) -> dict[str, Any] | None:
    """Mirrors services/telegraph_topic_candidates.py::_extract_step_result() /
    services/analysis_reuse.py::_extract_step_result() exactly - duplicated per this codebase's
    own established per-module-private-helper convention."""
    if not workflow:
        return None
    for step_result in workflow.get("step_results", []):
        if step_result.get("step_name") != step_name:
            continue
        if step_result.get("status") != "SUCCESS":
            return None
        result = step_result.get("result")
        return result if isinstance(result, dict) else None
    return None


async def _fetch_latest_news_analysis_workflows(
    session: AsyncSession, event_ids: Collection[UUID],
) -> dict[UUID, dict[str, Any]]:
    """One batched query for every event_id - mirrors services/telegraph_topic_candidates.py's
    own private helper of the same name/shape exactly."""
    if not event_ids:
        return {}
    stmt = select(EditorialTask.event_id, EditorialTask.workflow, EditorialTask.updated_at).where(
        EditorialTask.event_id.in_(event_ids),
        EditorialTask.status == TaskStatus.COMPLETED,
        EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
    )
    rows = (await session.execute(stmt)).all()
    latest_at: dict[UUID, Any] = {}
    latest_workflow: dict[UUID, dict[str, Any]] = {}
    for event_id, workflow, updated_at in rows:
        if event_id not in latest_at or updated_at > latest_at[event_id]:
            latest_at[event_id] = updated_at
            latest_workflow[event_id] = workflow
    return latest_workflow


async def _fetch_acquisitions(
    session: AsyncSession, event_ids: Collection[UUID],
) -> dict[UUID, NewsEventArticleAcquisition]:
    if not event_ids:
        return {}
    rows = (
        await session.execute(
            select(NewsEventArticleAcquisition).where(
                NewsEventArticleAcquisition.news_event_id.in_(event_ids)
            )
        )
    ).scalars().all()
    return {row.news_event_id: row for row in rows}


async def _fetch_source_intelligence(
    session: AsyncSession, event_ids: Collection[UUID],
) -> dict[UUID, NewsEventSourceIntelligence]:
    if not event_ids:
        return {}
    rows = (
        await session.execute(
            select(NewsEventSourceIntelligence).where(
                NewsEventSourceIntelligence.news_event_id.in_(event_ids)
            )
        )
    ).scalars().all()
    return {row.news_event_id: row for row in rows}


async def build_article_research_bundle(session: AsyncSession, story: Story) -> ArticleResearchBundle:
    """Bounded, read-only, zero LLM/Gateway/network calls. Reuses build_story_timeline()'s own 3
    queries, plus 3 more batched lookups (NEWS_ANALYSIS workflows, Article Acquisition, Source
    Intelligence) - 6 total regardless of Story size, never N+1."""
    timeline = await build_story_timeline(session, story.id)
    event_ids = [entry.event_id for entry in timeline]

    events_by_id: dict[UUID, NewsEvent] = {}
    if event_ids:
        rows = (await session.execute(select(NewsEvent).where(NewsEvent.id.in_(event_ids)))).scalars().all()
        events_by_id = {row.id: row for row in rows}

    workflows_by_event = await _fetch_latest_news_analysis_workflows(session, event_ids)
    acquisitions_by_event = await _fetch_acquisitions(session, event_ids)
    source_intel_by_event = await _fetch_source_intelligence(session, event_ids)

    contributing = [e for e in timeline if e.match_type in _CONTRIBUTING_MATCH_TYPES]
    dedup_duplicate_count = sum(1 for e in timeline if e.match_type == SEMANTIC_DUPLICATE)

    chronology: list[ChronologyEntry] = []
    facts: list[str] = []
    gaps: list[str] = []
    representative_significance: float | None = None
    representative_angle: str | None = None
    representative_recommendation: str | None = None
    source_agg: dict[str, dict[str, Any]] = {}

    for entry in contributing:
        news_event = events_by_id.get(entry.event_id)
        chronology.append(
            ChronologyEntry(
                event_id=entry.event_id,
                title=news_event.title if news_event is not None else "(unknown)",
                source=entry.source,
                url=news_event.url if news_event is not None else None,
                published_at=entry.published_at.isoformat() if entry.published_at else None,
                match_type=entry.match_type,
                delta=entry.delta,
                is_anchor=entry.event_id == story.first_event_id,
            )
        )

        workflow = workflows_by_event.get(entry.event_id)
        research = _extract_step_result(workflow, "research")
        intelligence = _extract_step_result(workflow, "intelligence")

        if research is not None:
            for fact in research.get("facts") or []:
                if isinstance(fact, str) and fact not in facts:
                    facts.append(fact)
            for gap in research.get("gaps") or []:
                if isinstance(gap, str) and gap not in gaps:
                    gaps.append(gap)

        if intelligence is not None:
            significance = intelligence.get("significance")
            if isinstance(significance, (int, float)):
                # "Representative" = the highest-significance contributing event, mirroring
                # Checkpoint 1's own build_story_evidence_summary()'s identical "max wins"
                # representativeness rule for the Story's own aggregate signals.
                if representative_significance is None or float(significance) > representative_significance:
                    representative_significance = float(significance)
                    representative_angle = intelligence.get("angle")
                    representative_recommendation = intelligence.get("recommendation")

        if entry.source is not None:
            agg = source_agg.setdefault(
                entry.source, {"event_count": 0, "urls": [], "best_status": None, "reliability": None}
            )
            agg["event_count"] += 1
            if news_event is not None and news_event.url and news_event.url not in agg["urls"]:
                agg["urls"].append(news_event.url)
            acquisition = acquisitions_by_event.get(entry.event_id)
            if acquisition is not None:
                agg["best_status"] = acquisition.effective_completeness_status
            source_intel = source_intel_by_event.get(entry.event_id)
            if source_intel is not None and source_intel.reliability_score is not None:
                if agg["reliability"] is None or source_intel.reliability_score > agg["reliability"]:
                    agg["reliability"] = source_intel.reliability_score

    chronology.sort(key=lambda c: c.published_at or "")
    truncated = (
        len(chronology) > _MAX_TIMELINE_ENTRIES or len(facts) > _MAX_FACTS
        or len(gaps) > _MAX_GAPS or len(source_agg) > _MAX_SOURCES
    )

    source_evidence = [
        SourceEvidenceEntry(
            source=name, event_count=data["event_count"], urls=data["urls"][:3],
            best_acquisition_status=data["best_status"], reliability_score=data["reliability"],
        )
        for name, data in source_agg.items()
    ]
    source_evidence.sort(key=lambda s: -s.event_count)

    return ArticleResearchBundle(
        story_id=story.id, story_title=story.title, story_category=story.category.value,
        topic_bucket=story.topic_bucket,
        chronology=chronology[:_MAX_TIMELINE_ENTRIES],
        confirmed_facts=facts[:_MAX_FACTS],
        known_gaps=gaps[:_MAX_GAPS],
        representative_significance=representative_significance,
        representative_angle=representative_angle,
        representative_recommendation=representative_recommendation,
        source_evidence=source_evidence[:_MAX_SOURCES],
        dedup_duplicate_count=dedup_duplicate_count,
        truncated=truncated,
    )


def render_bundle_text(bundle: ArticleResearchBundle) -> str:
    """Deterministic, bounded plain-text rendering - the exact text a Deep Research prompt reads
    (capabilities/research_capability.py's own deep-research branch). Never article prose, never
    a raw JSON/repr dump of the dataclass - a structured but readable brief."""
    lines: list[str] = [
        f"Story: {bundle.story_title}",
        f"Category: {bundle.story_category} | Topic bucket: {bundle.topic_bucket}",
        "",
        "CHRONOLOGY (contributing events only, oldest first):",
    ]
    for entry in bundle.chronology:
        marker = " [ANCHOR]" if entry.is_anchor else ""
        lines.append(
            f"- {entry.published_at or 'unknown time'} | {entry.source or 'unknown source'} | "
            f"{entry.match_type}{marker}: {entry.title}"
            + (f" ({entry.url})" if entry.url else "")
        )

    lines.append("")
    lines.append("CONFIRMED FACTS (from prior NEWS Research, already extracted from source text):")
    if bundle.confirmed_facts:
        lines.extend(f"- {fact}" for fact in bundle.confirmed_facts)
    else:
        lines.append("- (none recorded)")

    lines.append("")
    lines.append("KNOWN GAPS / UNCERTAINTIES (from prior NEWS Research):")
    if bundle.known_gaps:
        lines.extend(f"- {gap}" for gap in bundle.known_gaps)
    else:
        lines.append("- (none recorded)")

    lines.append("")
    lines.append("EDITORIAL SIGNAL (from the most significant contributing event's Intelligence result):")
    lines.append(f"- significance: {bundle.representative_significance}")
    lines.append(f"- angle: {bundle.representative_angle or '(none)'}")
    lines.append(f"- recommendation: {bundle.representative_recommendation or '(none)'}")

    lines.append("")
    lines.append("SOURCES (deduplicated by source name):")
    for source in bundle.source_evidence:
        lines.append(
            f"- {source.source} (events: {source.event_count}, "
            f"acquisition: {source.best_acquisition_status or 'unknown'}, "
            f"reliability: {source.reliability_score if source.reliability_score is not None else 'unknown'})"
            + (f" - {', '.join(source.urls)}" if source.urls else "")
        )

    if bundle.dedup_duplicate_count:
        lines.append("")
        lines.append(
            f"NOTE: {bundle.dedup_duplicate_count} additional near-identical/rehash source(s) were "
            "seen for this story (deduplicated - not counted as independent evidence above)."
        )

    text = "\n".join(lines)
    if len(text) > _MAX_BUNDLE_TEXT_CHARS:
        text = text[:_MAX_BUNDLE_TEXT_CHARS] + "\n[... bundle truncated at bounded length ...]"
    return text
