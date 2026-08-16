"""TELEGRAPH Checkpoint 1: deterministic article-topic candidate formation.

Answers exactly one question: "which already-analyzed Stories are strong enough to be proposed to
the operator as possible TELEGRAPH articles?" - and nothing past that. This module never writes an
article, never calls Deep Research/Copywriting, never calls any LLM Gateway, never fetches a URL,
and never sends anything to Telegram. Every input is already-persisted, deterministic data
(Story Memory links, NEWS_ANALYSIS step results, Article Acquisition status) - the only "new
computation" here is a pure, explainable scoring/eligibility function over that existing data.

Story-first, not event-first (the checkpoint's own core design principle): this module iterates
`Story` rows, never raw `NewsEvent` rows, and aggregates each Story's own linked events into one
compact `StoryEvidenceSummary` before a single eligibility/ranking decision is made for the whole
Story - a `SUPPORTING_SOURCE`-matched event never becomes its own separate candidate (it can only
ever strengthen the Story it is linked to), and a `SEMANTIC_DUPLICATE`/`UNCERTAIN_MATCH`-matched
event never inflates a Story's own signals (see `_CONTRIBUTING_MATCH_TYPES` below).

Reuses, never duplicates, the real aggregation work: `services/story_context.py::
build_story_timeline()` (bounded to 3 queries per Story, already joins NewsEventStoryLink +
NewsEvent + NewsSource) supplies every linked event's identity/source/match-type/timestamps; this
module adds only the two things that function does not already compute - each contributing event's
NEWS_ANALYSIS results (scoring/intelligence/engagement) and Article Acquisition evidence status -
via two additional batched (never per-event) queries.

Persistence decision (see the Checkpoint 1 report for the full reasoning): NO new table and NO
migration were required or created. `TelegraphTopicCandidate`/`TopicCandidateRejection` are plain,
transient `dataclass`es - this checkpoint's own explicit scope ends before any human decision,
approval, or publish state exists to persist (that is Checkpoint 2's territory). Reproposal
avoidance across shortlist windows is exposed as an `already_proposed_story_ids` parameter the
future durable layer can populate - this module does not need to know how that set was computed or
stored.
"""
from __future__ import annotations

from collections.abc import Collection, Set
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.news_event import EventCategory
from database.models.news_event_article_acquisition import (
    ACQUISITION_STATUS_FULL_TEXT,
    ACQUISITION_STATUS_SUBSTANTIAL_TEXT,
    NewsEventArticleAcquisition,
)
from database.models.story import Story
from schemas.workflow import WorkflowType
from services.story_context import StoryTimelineEntry, build_story_timeline
from services.story_memory import NEW_STORY, STORY_UPDATE, SUPPORTING_SOURCE

# Match types that count as this Story's own real substance - mirrors the same distinction
# services/triage_orchestrator.py itself already draws when deciding which outcomes bump
# Story.event_count (STORY_UPDATE/SUPPORTING_SOURCE/SEMANTIC_DUPLICATE), refined here for a
# different purpose: SEMANTIC_DUPLICATE ("a rehash from a different source, no new substance" -
# services/story_memory.py's own outcome docstring) and UNCERTAIN_MATCH (Story Memory's own "not
# confident enough" outcome) must never inflate a TELEGRAPH candidate's richness/diversity signals,
# even though both are still linked to the Story for observability. NEW_STORY is included - a
# single-event Story's own root event always carries this match_type (services/triage_
# orchestrator.py::_apply_story_memory() links every event, including a brand-new Story's first).
_CONTRIBUTING_MATCH_TYPES = frozenset({NEW_STORY, STORY_UPDATE, SUPPORTING_SOURCE})

# Evidence tiers for THIS checkpoint's own decision only - deliberately not services/editorial_
# treatment.py's _WEAK_COMPLETENESS_STATUSES (SKIP/BRIEF/STANDARD/MAJOR is a different domain
# decision with different tolerances) and not services/evidence_package.py's
# TRUSTED_FULL_ARTICLE_STATUSES (a staleness-detection concern, not an article-worthiness one) -
# each existing tier in this codebase is already purpose-specific, never a single shared "is this
# evidence good" boolean (confirmed: PARTIAL_TEXT is "trusted" for evidence_package's reuse check
# but "weak" for editorial_treatment's SKIP gate - the two were never meant to agree).
EVIDENCE_STRONG = "strong"
EVIDENCE_MODERATE = "moderate"
EVIDENCE_WEAK = "weak"

_STRONG_EVIDENCE_STATUSES = frozenset({ACQUISITION_STATUS_FULL_TEXT, ACQUISITION_STATUS_SUBSTANTIAL_TEXT})
_MODERATE_EVIDENCE_STATUSES = frozenset({"PARTIAL_TEXT"})

# 2026-08-16 TELEGRAPH Checkpoint 1: the same explicit-veto phrase list services/editorial_
# treatment.py::_NEGATIVE_RECOMMENDATION_MARKERS already maintains, duplicated here rather than
# imported - a private, underscore-prefixed name belongs to that module only (this codebase's own
# established convention, e.g. _extract_scoring_result's own docstring on why capabilities/
# analysis-extraction helpers are duplicated per module rather than shared). This is reuse of the
# *normalization pattern* (the phrase-detection logic), never reuse of NEWS Treatment's own SKIP/
# BRIEF/STANDARD/MAJOR domain decision - TELEGRAPH's semantics differ (see module docstring) and
# must not be coupled to it. Keep this list in sync with editorial_treatment.py's own by hand; both
# lists exist specifically so each domain's calibration can diverge later without touching the
# other.
_NEGATIVE_RECOMMENDATION_MARKERS: tuple[str, ...] = (
    "не публиковать", "не выпускать", "не рекомендуется публиковать",
    "do not publish", "not publish", "do not release",
    "не продвигать", "не использовать как самостоятельную", "не использовать как полноценную",
    "не выделять как самостоятельную", "не выносить в основную новостную повестку",
)

# 2026-08-16 correctness review: a topic_bucket -> score bonus (security_incident/legal_regulatory
# weighted highest) was implemented in the first pass of this checkpoint and then REMOVED after
# review found no pre-existing, pre-Checkpoint-1 codebase/docs precedent for that specific
# weighting hierarchy. `Story.topic_bucket` itself is real, deterministic, already-persisted data
# (services/story_memory.py::_classify_topic()) - but services/story_memory.py's own `_TOPIC_BONUS`
# uses it only to reinforce STORY-MATCHING confidence ("is this the same story"), never as an
# editorial-importance signal, and no other module ranks legal_regulatory/security_incident above
# product/corporate/financial for article-worthiness. Inventing that hierarchy here would have been
# exactly the "silently invent a new editorial preference hierarchy" this checkpoint must avoid -
# `topic_bucket` stays on `StoryEvidenceSummary` and in `rationale` for observability/future use,
# but contributes nothing to `topic_score`. See the Checkpoint 1 correctness-review report for the
# full analysis (Part B).

# Reasoned starting points (this checkpoint's own first calibration, no real shortlist-outcome data
# exists yet to fit against - matches services/story_memory.py's own disclosed-reasoning
# convention for every one of its thresholds). Significance floor sits at editorial_treatment.py's
# own "medium significance" tier lower bound (5.0/10) - TELEGRAPH's bar for "worth a deep dive" is
# deliberately at least as high as NEWS's own "a valid but minor story" tier, never lower.
_MIN_SIGNIFICANCE_FOR_CANDIDATE = 5.0
_NEGATIVE_RECOMMENDATION_PENALTY = 35
_STORY_SCAN_SAFETY_CAP = 500


def _normalize_significance(raw: float | int | None) -> float | None:
    """Duplicated verbatim from services/editorial_treatment.py::_normalize_significance() - same
    ambiguous-scale problem (prompts/intelligence/v2.yaml declares only `type: number`), same fix.
    See that function's own docstring for the full reasoning; kept as a separate copy for the same
    per-module-duplication reason `_NEGATIVE_RECOMMENDATION_MARKERS` above is."""
    if raw is None:
        return None
    value = float(raw)
    if value <= 1.0:
        value *= 10.0
    return max(0.0, min(10.0, value))


def _has_negative_recommendation(recommendation: str | None) -> bool:
    if not recommendation:
        return False
    normalized = recommendation.strip().casefold()
    return any(marker in normalized for marker in _NEGATIVE_RECOMMENDATION_MARKERS)


def _extract_step_result(workflow: dict[str, Any] | None, step_name: str) -> dict[str, Any] | None:
    """Mirrors services/analysis_reuse.py::_extract_step_result() and worker/content_cycle.py::
    _extract_scoring_result()/_extract_intelligence_result() exactly - the same established
    step_results-scan-for-SUCCESS pattern, duplicated per this codebase's own convention rather
    than imported from either (both are module-private elsewhere)."""
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


def _classify_evidence(best_status: str | None, source_diversity_proxy: int) -> str:
    """Pure. `best_status` is the strongest `effective_completeness_status` found among the
    Story's own contributing events' Article Acquisition rows (`None` if none exist at all - the
    common case, since acquisition only ever runs for an event already selected for CONTENT_
    GENERATION, never the mass NEWS_ANALYSIS population - services/article_acquisition.py's own
    module docstring). Several independent corroborating sources can compensate for missing/weak
    acquired text (the phase brief's own explicit "do not require FULL_TEXT in every case if
    several strong independent events/sources form the Story"); a single weakly-evidenced event
    cannot compensate for itself."""
    if best_status in _STRONG_EVIDENCE_STATUSES:
        return EVIDENCE_STRONG
    if best_status in _MODERATE_EVIDENCE_STATUSES:
        return EVIDENCE_STRONG if source_diversity_proxy >= 2 else EVIDENCE_MODERATE
    # best_status is None (no acquisition anywhere) or an explicit weak/failure status
    # (HEADLINE_ONLY/REDIRECT_UNRESOLVED/FETCH_FAILED/PAYWALLED/UNSUPPORTED_CONTENT_TYPE).
    if source_diversity_proxy >= 3:
        return EVIDENCE_MODERATE
    return EVIDENCE_WEAK


@dataclass(frozen=True)
class StoryEvidenceSummary:
    """The compact, deterministic Story-level aggregate `evaluate_story_topic_candidate()` scores
    - references and small metadata only, never full research/article text (the phase brief's own
    explicit "do NOT copy full research outputs into the candidate... prefer references + compact
    deterministic metadata")."""

    story_id: UUID
    story_title: str
    story_category: EventCategory
    topic_bucket: str
    event_count: int
    total_linked_event_count: int
    latest_event_at: datetime
    source_diversity_proxy: int
    match_type_counts: dict[str, int]
    max_score: int | None
    max_significance: float | None
    representative_recommendation: str | None
    has_negative_recommendation: bool
    max_engagement_potential_score: float | None
    best_evidence_status: str | None
    events_with_full_text: int
    events_with_any_acquisition: int
    analyzed_event_count: int


@dataclass(frozen=True)
class TopicCandidateSignals:
    """Every deterministic component that fed `topic_score`, plus the evidence tier the
    eligibility decision itself used - exposed so a caller/operator can see WHY, never a black
    box (mirrors services/editorial_treatment.py::EditorialTreatmentDecision.reason's own
    always-explain convention, one level more granular)."""

    significance_component: int
    score_component: int
    evidence_component: int
    diversity_component: int
    engagement_component: int
    negative_recommendation_penalty: int
    evidence_tier: str
    normalized_significance: float | None


@dataclass(frozen=True)
class TelegraphTopicCandidate:
    story_id: UUID
    story_title: str
    topic_score: int
    rationale: str
    signals: TopicCandidateSignals
    summary: StoryEvidenceSummary


@dataclass(frozen=True)
class TopicCandidateRejection:
    """Why a Story did NOT become a candidate - never raised as an error, never required by a
    caller that only wants the accepted list, but always computable for observability/debugging."""

    story_id: UUID
    story_title: str
    reason: str


def evaluate_story_topic_candidate(
    summary: StoryEvidenceSummary,
    *,
    now: datetime,
    recency_cutoff_hours: float,
    already_proposed_story_ids: Set[UUID] = frozenset(),
) -> TelegraphTopicCandidate | TopicCandidateRejection:
    """Pure, deterministic, no I/O, no wall-clock dependence beyond the explicit `now` passed in -
    the phase brief's own required shape. Every eligibility gate below returns immediately with an
    explained rejection; only a Story clearing every gate reaches scoring.

    Article-worthiness is deliberately NOT `if score >= threshold` (the phase brief's own explicit
    anti-pattern) - `max_score` (NEWS Scoring) only ever contributes a bounded slice of
    `topic_score`, never gates eligibility on its own; significance and evidence quality are the
    two genuine gates."""
    if summary.story_id in already_proposed_story_ids:
        return TopicCandidateRejection(
            summary.story_id, summary.story_title,
            "already proposed as a TELEGRAPH candidate recently - not re-proposed",
        )

    cutoff = now - timedelta(hours=recency_cutoff_hours)
    if summary.latest_event_at < cutoff:
        return TopicCandidateRejection(
            summary.story_id, summary.story_title,
            f"stale - latest linked event at {summary.latest_event_at.isoformat()} is older than "
            f"the {recency_cutoff_hours:.0f}h TELEGRAPH recency window (cutoff {cutoff.isoformat()})",
        )

    if summary.analyzed_event_count < 1:
        return TopicCandidateRejection(
            summary.story_id, summary.story_title,
            "insufficient data - no contributing linked event has a completed NEWS_ANALYSIS result",
        )

    # summary.max_significance is already normalized to the 0-10 scale by _summarize_story() (via
    # _normalize_significance()) - re-normalizing here would double-scale any value that itself
    # ends up <= 1.0 after the first pass (e.g. a genuinely low significance of 0.5/10 would be
    # multiplied by 10 again, to 5.0). Used as-is.
    normalized_significance = summary.max_significance
    if normalized_significance is None or normalized_significance < _MIN_SIGNIFICANCE_FOR_CANDIDATE:
        return TopicCandidateRejection(
            summary.story_id, summary.story_title,
            f"low significance ({normalized_significance}) - below the "
            f"{_MIN_SIGNIFICANCE_FOR_CANDIDATE:.1f}/10 TELEGRAPH candidate floor",
        )

    evidence_tier = _classify_evidence(summary.best_evidence_status, summary.source_diversity_proxy)
    if evidence_tier == EVIDENCE_WEAK:
        return TopicCandidateRejection(
            summary.story_id, summary.story_title,
            f"weak evidence (best_status={summary.best_evidence_status}, "
            f"source_diversity_proxy={summary.source_diversity_proxy}) - a high NEWS score cannot "
            f"compensate for evidence quality",
        )

    if summary.has_negative_recommendation and evidence_tier != EVIDENCE_STRONG:
        return TopicCandidateRejection(
            summary.story_id, summary.story_title,
            f"explicit negative Intelligence recommendation combined with {evidence_tier} evidence "
            f"- excluded rather than merely penalized",
        )

    significance_component = round(normalized_significance / 10.0 * 40)
    score_component = round((summary.max_score or 0) / 100.0 * 25) if summary.max_score is not None else 0
    evidence_component = {EVIDENCE_STRONG: 20, EVIDENCE_MODERATE: 12, EVIDENCE_WEAK: 0}[evidence_tier]
    diversity_component = round(min((summary.source_diversity_proxy - 1) * 2.5, 10))
    engagement_raw = summary.max_engagement_potential_score
    engagement_component = round((engagement_raw or 0) / 100.0 * 5) if engagement_raw is not None else 0
    negative_recommendation_penalty = (
        _NEGATIVE_RECOMMENDATION_PENALTY if summary.has_negative_recommendation else 0
    )

    # No topic_bucket contribution - see the module-level comment above _MIN_SIGNIFICANCE_FOR_
    # CANDIDATE for why a topic_bucket -> score bonus was removed after correctness review.
    raw_total = (
        significance_component + score_component + evidence_component + diversity_component
        + engagement_component - negative_recommendation_penalty
    )
    topic_score = max(0, min(100, round(raw_total)))

    signals = TopicCandidateSignals(
        significance_component=significance_component,
        score_component=score_component,
        evidence_component=evidence_component,
        diversity_component=diversity_component,
        engagement_component=engagement_component,
        negative_recommendation_penalty=negative_recommendation_penalty,
        evidence_tier=evidence_tier,
        normalized_significance=normalized_significance,
    )
    rationale = (
        f"significance={normalized_significance:.1f}/10 (+{significance_component}), "
        f"news_score={summary.max_score} (+{score_component}), "
        f"evidence={evidence_tier} (+{evidence_component}), "
        f"source_diversity_proxy={summary.source_diversity_proxy} (+{diversity_component}), "
        f"engagement={engagement_raw} (+{engagement_component}), "
        f"topic_bucket={summary.topic_bucket} (informational only, no score contribution)"
        + (
            f", negative_recommendation (-{negative_recommendation_penalty})"
            if summary.has_negative_recommendation else ""
        )
    )
    return TelegraphTopicCandidate(
        story_id=summary.story_id, story_title=summary.story_title, topic_score=topic_score,
        rationale=rationale, signals=signals, summary=summary,
    )


# ---------------------------------------------------------------------------------------------
# Async orchestration: bounded, read-only, zero LLM/Gateway/network calls.
# ---------------------------------------------------------------------------------------------


async def _fetch_recent_stories(session: AsyncSession, *, cutoff: datetime) -> list[Story]:
    """Bounded, indexed fetch (Story.updated_at has an index - database/migrations/versions/
    3f37cf34109d_add_stories_updated_at_index.py, per that column's own model comment) - mirrors
    services/story_memory.py::_fetch_candidate_stories()'s own "bounded window, scored in Python"
    shape, never an unbounded table scan.

    2026-08-16 correctness review (Part A): proves `Story.updated_at` cannot hide a genuinely
    fresh, CONTRIBUTING (see `_CONTRIBUTING_MATCH_TYPES`) linked event from this coarse SQL
    prefilter - the only failure mode that would matter, since the pure `evaluate_story_topic_
    candidate()` gate downstream is the authoritative, contributing-only recency decision and can
    freely reject anything this prefilter over-includes.

    Cited evidence, `services/triage_orchestrator.py::_apply_story_memory()`:
    - NEW_STORY: a brand-new `Story` row is inserted in the SAME transaction as the event's own
      `NewsEventStoryLink` (`created_at`/`updated_at` both `server_default=func.now()`) - always
      fresh at the moment of creation.
    - STORY_UPDATE / SUPPORTING_SOURCE (the two remaining contributing outcomes that attach to an
      EXISTING Story): `matched_story.event_count += 1` always executes in that same branch,
      which SQLAlchemy flushes as an UPDATE on the Story row; `Story.updated_at`'s own
      `onupdate=func.now()` fires for ANY update to that row (not conditioned on which column
      changed - standard SQLAlchemy column-default semantics), in the SAME transaction as the
      `NewsEventStoryLink` insert (the function's own docstring: "committed atomically together
      with create_task()'s own EditorialTask insert, in the same transaction"). So `Story.
      updated_at` is bumped at essentially the same instant a contributing link is created - it
      can never be staler than the true "most recent contributing link" moment.
    - SEMANTIC_DUPLICATE also bumps `event_count` (hence `updated_at`) despite NOT being a
      contributing outcome for this module's own purposes - harmless here: it can only make this
      prefilter MORE inclusive than strictly necessary (a Story fetched here for a duplicate-only
      reason is still correctly rejected downstream by the contributing-only `latest_event_at`
      computed in `_summarize_story()`), never less.
    - UNCERTAIN_MATCH (the one outcome that attaches without bumping `event_count`) is also not a
      contributing outcome here - its omission from the `updated_at` bump cannot hide a
      contributing signal, since it never contributes one.

    Empirically verified (not merely argued): tests/test_telegraph_topic_candidates.py::
    test_story_updated_at_is_bumped_when_a_contributing_event_is_linked reproduces the exact
    STORY_UPDATE write-path mutation against the real schema and asserts `Story.updated_at`
    actually changes.
    """
    stmt = (
        select(Story)
        .where(Story.updated_at >= cutoff)
        .order_by(Story.updated_at.desc())
        .limit(_STORY_SCAN_SAFETY_CAP)
    )
    return list((await session.execute(stmt)).scalars().all())


async def _fetch_latest_news_analysis_workflows(
    session: AsyncSession, event_ids: Collection[UUID],
) -> dict[UUID, dict[str, Any]]:
    """One query for every event_id at once (never one query per event) - reduces to "latest
    COMPLETED NEWS_ANALYSIS workflow per event_id" in Python, mirroring worker/content_cycle.py's
    own established "SQL bounded, Python-side reduction" convention."""
    if not event_ids:
        return {}
    stmt = select(EditorialTask.event_id, EditorialTask.workflow, EditorialTask.updated_at).where(
        EditorialTask.event_id.in_(event_ids),
        EditorialTask.status == TaskStatus.COMPLETED,
        EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
    )
    rows = (await session.execute(stmt)).all()
    latest_at: dict[UUID, datetime] = {}
    latest_workflow: dict[UUID, dict[str, Any]] = {}
    for event_id, workflow, updated_at in rows:
        if event_id not in latest_at or updated_at > latest_at[event_id]:
            latest_at[event_id] = updated_at
            latest_workflow[event_id] = workflow
    return latest_workflow


async def _fetch_acquisition_statuses(
    session: AsyncSession, event_ids: Collection[UUID],
) -> dict[UUID, str]:
    """Reads only already-persisted `NewsEventArticleAcquisition` rows - never triggers a new
    fetch (unlike services/article_acquisition.py::get_or_acquire(), this module never calls it).
    Resolves the one-hop `reused_from_news_event_id` pointer batched (a second bounded query, only
    when at least one reuse row exists), mirroring services/article_acquisition.py::
    get_effective_acquisition()'s own exact one-hop-only resolution and its same defensive
    "a second hop is treated as absent" fallback."""
    if not event_ids:
        return {}
    rows = (
        await session.execute(
            select(NewsEventArticleAcquisition).where(
                NewsEventArticleAcquisition.news_event_id.in_(event_ids)
            )
        )
    ).scalars().all()
    by_event = {row.news_event_id: row for row in rows}

    reuse_targets = {
        row.reused_from_news_event_id for row in rows if row.reused_from_news_event_id is not None
    }
    target_by_id: dict[UUID, NewsEventArticleAcquisition] = {}
    if reuse_targets:
        target_rows = (
            await session.execute(
                select(NewsEventArticleAcquisition).where(
                    NewsEventArticleAcquisition.news_event_id.in_(reuse_targets)
                )
            )
        ).scalars().all()
        target_by_id = {row.news_event_id: row for row in target_rows}

    statuses: dict[UUID, str] = {}
    for event_id, row in by_event.items():
        effective = row
        if row.reused_from_news_event_id is not None:
            target = target_by_id.get(row.reused_from_news_event_id)
            if target is None or target.reused_from_news_event_id is not None:
                continue  # unresolved or a >1-hop chain (should be structurally impossible) - skip
            effective = target
        statuses[event_id] = effective.effective_completeness_status
    return statuses


def _summarize_story(
    story: Story,
    timeline: list[StoryTimelineEntry],
    workflows_by_event: dict[UUID, dict[str, Any]],
    acquisition_status_by_event: dict[UUID, str],
) -> StoryEvidenceSummary:
    """Pure. Combines the already-fetched timeline + batched lookups into one compact summary -
    see _CONTRIBUTING_MATCH_TYPES's own module-level comment for which entries count toward
    richness/diversity signals."""
    match_type_counts: dict[str, int] = {}
    for entry in timeline:
        match_type_counts[entry.match_type] = match_type_counts.get(entry.match_type, 0) + 1

    contributing = [entry for entry in timeline if entry.match_type in _CONTRIBUTING_MATCH_TYPES]
    contributing_sources = {entry.source for entry in contributing if entry.source is not None}

    # 2026-08-16 correctness review (Part A): computed from `contributing` only, never the full
    # `timeline` - a fresh SEMANTIC_DUPLICATE/UNCERTAIN_MATCH link must never make an otherwise-
    # stale Story look current merely because Story Memory still linked it for observability (see
    # _CONTRIBUTING_MATCH_TYPES's own docstring on why those two outcomes carry no substance). The
    # SQL-level recency prefilter in `_fetch_recent_stories()` may still be looser (bounded by
    # `Story.updated_at`, which - see that function's own docstring - can never be staler than this
    # value for a genuinely contributing link, but CAN be fresher due to a non-contributing one) -
    # this is the one, authoritative, contributing-only recency signal the pure eligibility check
    # in `evaluate_story_topic_candidate()` actually gates on.
    latest_event_at = max(
        (entry.published_at or entry.collected_at for entry in contributing),
        default=story.created_at,
    )

    max_score: int | None = None
    max_significance: float | None = None
    representative_recommendation: str | None = None
    has_negative_recommendation = False
    max_engagement: float | None = None
    best_evidence_status: str | None = None
    events_with_full_text = 0
    events_with_any_acquisition = 0
    analyzed_event_count = 0

    for entry in contributing:
        workflow = workflows_by_event.get(entry.event_id)
        scoring = _extract_step_result(workflow, "scoring")
        intelligence = _extract_step_result(workflow, "intelligence")
        engagement = _extract_step_result(workflow, "engagement_analysis")
        if scoring is not None or intelligence is not None or engagement is not None:
            analyzed_event_count += 1

        if scoring is not None:
            score = scoring.get("score")
            if isinstance(score, int) and (max_score is None or score > max_score):
                max_score = score

        if intelligence is not None:
            significance = intelligence.get("significance")
            recommendation = intelligence.get("recommendation")
            normalized = _normalize_significance(significance) if significance is not None else None
            if normalized is not None and (max_significance is None or normalized > max_significance):
                max_significance = normalized
                representative_recommendation = recommendation
            if _has_negative_recommendation(recommendation):
                has_negative_recommendation = True

        if engagement is not None:
            potential = engagement.get("engagement_potential_score")
            if isinstance(potential, (int, float)) and (max_engagement is None or potential > max_engagement):
                max_engagement = float(potential)

        acquisition_status = acquisition_status_by_event.get(entry.event_id)
        if acquisition_status is not None:
            events_with_any_acquisition += 1
            if acquisition_status in _STRONG_EVIDENCE_STATUSES:
                events_with_full_text += 1
            if best_evidence_status is None or _evidence_rank(acquisition_status) > _evidence_rank(best_evidence_status):
                best_evidence_status = acquisition_status

    return StoryEvidenceSummary(
        story_id=story.id, story_title=story.title, story_category=story.category,
        topic_bucket=story.topic_bucket, event_count=len(contributing),
        total_linked_event_count=len(timeline), latest_event_at=latest_event_at,
        source_diversity_proxy=len(contributing_sources), match_type_counts=match_type_counts,
        max_score=max_score, max_significance=max_significance,
        representative_recommendation=representative_recommendation,
        has_negative_recommendation=has_negative_recommendation,
        max_engagement_potential_score=max_engagement, best_evidence_status=best_evidence_status,
        events_with_full_text=events_with_full_text,
        events_with_any_acquisition=events_with_any_acquisition,
        analyzed_event_count=analyzed_event_count,
    )


_EVIDENCE_STATUS_RANK: dict[str, int] = {
    "FETCH_FAILED": 0, "UNSUPPORTED_CONTENT_TYPE": 0, "PAYWALLED": 1, "REDIRECT_UNRESOLVED": 1,
    "HEADLINE_ONLY": 2, "PARTIAL_TEXT": 3, "SUBSTANTIAL_TEXT": 4, "FULL_TEXT": 5,
}


def _evidence_rank(status: str) -> int:
    """Pure. Orders acquisition statuses from weakest to strongest evidence, purely so
    `_summarize_story()` can pick the SINGLE strongest status across a Story's contributing events
    without hardcoding a second copy of the ordering inline. An unrecognized status ranks below
    every known one (never above) - conservative by construction."""
    return _EVIDENCE_STATUS_RANK.get(status, -1)


async def build_story_evidence_summary(session: AsyncSession, story: Story) -> StoryEvidenceSummary:
    """Bounded: `build_story_timeline()`'s own 3 queries, plus one batched NEWS_ANALYSIS fetch and
    one batched (usually zero-extra-query) Article Acquisition fetch - 5 queries total regardless
    of how many events are linked to this Story, never N+1."""
    timeline = await build_story_timeline(session, story.id)
    event_ids = [entry.event_id for entry in timeline]
    workflows_by_event = await _fetch_latest_news_analysis_workflows(session, event_ids)
    acquisition_status_by_event = await _fetch_acquisition_statuses(session, event_ids)
    return _summarize_story(story, timeline, workflows_by_event, acquisition_status_by_event)


async def build_telegraph_topic_candidates(
    session: AsyncSession,
    *,
    limit: int,
    now: datetime | None = None,
    recency_cutoff_hours: float | None = None,
    already_proposed_story_ids: Set[UUID] | None = None,
) -> list[TelegraphTopicCandidate]:
    """The one callable API Checkpoint 2 consumes. Bounded, read-only, zero LLM/Gateway/network
    calls anywhere in this call graph. Returns 0..`limit` candidates, ranked (topic_score DESC,
    freshness DESC, story_id ASC for a fully deterministic tie-break) - NEVER padded with
    sub-threshold Stories to reach `limit` (quality over quota is structural here, not a policy
    note - a Story that fails any eligibility gate in `evaluate_story_topic_candidate()` is simply
    absent from the returned list).

    `limit` is a caller-supplied cap only, never baked into the ranking/eligibility logic itself -
    calling with `limit=5` legitimately returns anywhere from 0 to 5 candidates depending on real
    Story quality that window.
    """
    reference_now = now if now is not None else datetime.now(timezone.utc)
    cutoff_hours = (
        recency_cutoff_hours if recency_cutoff_hours is not None
        else settings.telegraph_candidate_recency_hours
    )
    proposed = already_proposed_story_ids if already_proposed_story_ids is not None else frozenset()

    cutoff = reference_now - timedelta(hours=cutoff_hours)
    stories = await _fetch_recent_stories(session, cutoff=cutoff)

    candidates: list[TelegraphTopicCandidate] = []
    for story in stories:
        summary = await build_story_evidence_summary(session, story)
        decision = evaluate_story_topic_candidate(
            summary, now=reference_now, recency_cutoff_hours=cutoff_hours,
            already_proposed_story_ids=proposed,
        )
        if isinstance(decision, TelegraphTopicCandidate):
            candidates.append(decision)

    candidates.sort(key=lambda c: (-c.topic_score, -c.summary.latest_event_at.timestamp(), str(c.story_id)))
    return candidates[:limit]
