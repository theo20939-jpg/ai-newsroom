"""NINJA PULSE RECAP - Phase R1: offline WEEKLY_RECAP Story selection.

Pure/manual callable only - `select_weekly_recap_stories()` is never invoked by any worker loop,
scheduler, or Telegram handler in R1 (spec §14/§4's explicit "no content_main.py cadence
integration in R1"). No writes, no LLM, no network - reads Story/EditorialTask/NewsEvent rows only.

Reuses, never reimplements: `services/news_editorial_relevance.py::classify_editorial_relevance()`
for CORE/ADJACENT/PERIPHERAL/OUT_OF_SCOPE tiering (hard-excludes OUT_OF_SCOPE, respects
`major_impact_override`); the same `workflow["step_results"]` scoring-extraction shape
`worker/content_cycle.py::_extract_scoring_result()`/`_extract_intelligence_result()` already
established (duplicated locally per this codebase's own convention - see those functions' own
docstrings for why a shared cross-module import is deliberately avoided).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.editorial_task import EditorialTask
from database.models.news_event import NewsEvent
from database.models.story import Story
from services.news_editorial_relevance import ADJACENT, CORE, OUT_OF_SCOPE, PERIPHERAL, classify_editorial_relevance


@dataclass(frozen=True)
class WeeklyRecapCandidate:
    story_id: UUID
    representative_event_id: UUID
    relevance_tier: str
    score: int | None
    significance: float | int | None
    major_impact_override: bool
    # Best-effort diversity key only - see `_company_key()`'s own docstring. None means "no entity
    # extracted, ambiguous" - explicitly never guessed, and never capped against other None-keyed
    # candidates (spec §12's own "if company attribution is ambiguous, do not guess").
    company_key: str | None
    entities: list[str]
    updated_at: datetime
    reason: str
    rank_score: float


# ---------------------------------------------------------------------------
# Locally-duplicated workflow-signal extraction - mirrors worker/content_cycle.py's own
# _extract_scoring_result()/_extract_intelligence_result() shape exactly, intentionally not
# cross-imported from worker/ (that module's own docstring convention: a small, differently-scoped
# duplicate per caller, not a shared abstraction for one caller each).
# ---------------------------------------------------------------------------


def _extract_scoring_result(workflow: dict[str, Any] | None) -> int | None:
    if not workflow:
        return None
    for step_result in workflow.get("step_results", []):
        if step_result.get("step_name") == "scoring" and step_result.get("status") == "SUCCESS":
            result = step_result.get("result")
            if isinstance(result, dict):
                score = result.get("score")
                if isinstance(score, int):
                    return score
    return None


def _extract_significance(workflow: dict[str, Any] | None) -> float | int | None:
    if not workflow:
        return None
    for step_result in workflow.get("step_results", []):
        if step_result.get("step_name") == "intelligence" and step_result.get("status") == "SUCCESS":
            result = step_result.get("result")
            if isinstance(result, dict):
                return result.get("significance")
    return None


def _company_key(entities: list[str]) -> str | None:
    """Best-effort diversity grouping only - the first already-extracted `Story.entities` token,
    lowercased. NOT a real company/organization classifier (spec §12's own explicit "do not make
    entity extraction smarter this checkpoint" instruction) - `Story.entities` mixes companies,
    products, and people indiscriminately (services/story_memory.py::_extract_entities()'s own
    capitalized-run heuristic), so this key may just as easily be a product or person name. Used
    only to avoid trivially obvious over-concentration (many weekly items about the literal same
    entity string); never presented as a verified company attribution."""
    return entities[0].lower() if entities else None


# ---------------------------------------------------------------------------
# Pure quality-eligibility floor + ranking + diversity (no I/O) - the part fixture tests exercise
# directly. Order is load-bearing (Phase R1.1 correction): eligibility MUST run before ranking and
# diversity - "quality > count" means a Story that fails this floor can never occupy a slot, even
# an otherwise-empty one, and the diversity fallback (which relaxes the company cap) must never be
# able to reach back past this floor either.
# ---------------------------------------------------------------------------


def _is_eligible(candidate: WeeklyRecapCandidate) -> bool:
    """Deterministic quality floor - spec's own explicit "reuse existing Editorial Relevance...
    do not invent another 0-100 editorial model" instruction. CORE is always eligible. ADJACENT is
    eligible only when an existing score/significance signal clears its own configured threshold
    (`weekly_recap_adjacent_min_score`/`weekly_recap_adjacent_min_significance`) - neither signal
    present means "not verifiably sufficient," fails closed. PERIPHERAL is eligible only via the
    existing `major_impact_override` signal `classify_editorial_relevance()` already computes -
    never via these score/significance thresholds (a PERIPHERAL story with a merely high score is
    still routine noise, not major-impact). OUT_OF_SCOPE is never eligible (already hard-excluded
    upstream in `_build_candidate()`, re-checked here defensively for the pure function's own
    callers, e.g. tests, that may pass tier="OUT_OF_SCOPE" directly)."""
    if candidate.relevance_tier == CORE:
        return True
    if candidate.relevance_tier == ADJACENT:
        score_sufficient = candidate.score is not None and candidate.score >= settings.weekly_recap_adjacent_min_score
        significance_sufficient = (
            candidate.significance is not None
            and candidate.significance >= settings.weekly_recap_adjacent_min_significance
        )
        return score_sufficient or significance_sufficient
    if candidate.relevance_tier == PERIPHERAL:
        return candidate.major_impact_override
    return False  # OUT_OF_SCOPE, or any unrecognized tier - never eligible


def _rank_key(candidate: WeeklyRecapCandidate) -> tuple[float, datetime]:
    # Composite key mirrors worker/content_cycle.py::_select_eligible_events()'s own
    # `score + rank_adjustment` pattern; ties broken by recency (most-recently-updated Story wins),
    # deterministic and never random.
    return candidate.rank_score, candidate.updated_at


def select_weekly_recap_stories_from_candidates(
    candidates: list[WeeklyRecapCandidate],
) -> tuple[list[WeeklyRecapCandidate], list[WeeklyRecapCandidate]]:
    """Pure. Pipeline order (Phase R1.1, load-bearing): quality eligibility floor -> ranking ->
    diversity cap -> selection.

    Step 1 (`_is_eligible()`): candidates that fail the quality floor are dropped before ranking
    ever sees them - they can NEVER be selected, not even as filler for an under-full result.
    Step 2: the surviving eligible candidates are ranked (highest `_rank_key()` first).
    Step 3/4: the per-company diversity cap (`settings.weekly_recap_max_per_company`) applies in
    two passes exactly as before -

    Pass 1 (strict): walk the ranked (eligible-only) list, admit a candidate unless its
    `company_key` has already reached the cap.
    Pass 2 (fallback): spec §12's own "should not reduce the result below a useful minimum when
    insufficient alternatives exist" - if Pass 1 selected fewer than `settings.weekly_recap_
    target_min` candidates AND capped-out (still-eligible) candidates remain, admit additional
    candidates in rank order (ignoring the cap) until either the target_min is reached or eligible
    candidates are exhausted. The fallback ONLY ever draws from the already-eligible pool - it
    relaxes the diversity cap, never the quality floor. If fewer than `target_min` eligible
    candidates exist at all, the result is legitimately shorter than 5 - never padded with an
    ineligible Story.

    Returns `(selected, excluded)` - `excluded` is every input candidate not selected (whether
    dropped by the quality floor or the diversity cap), in ranked order where applicable."""
    eligible = [c for c in candidates if _is_eligible(c)]
    ranked = sorted(eligible, key=_rank_key, reverse=True)

    company_counts: dict[str, int] = {}
    selected: list[WeeklyRecapCandidate] = []
    capped_out: list[WeeklyRecapCandidate] = []

    for candidate in ranked:
        if len(selected) >= settings.weekly_recap_target_max:
            break
        key = candidate.company_key
        if key is not None and company_counts.get(key, 0) >= settings.weekly_recap_max_per_company:
            capped_out.append(candidate)
            continue
        selected.append(candidate)
        if key is not None:
            company_counts[key] = company_counts.get(key, 0) + 1

    if len(selected) < settings.weekly_recap_target_min and capped_out:
        for candidate in capped_out:
            if len(selected) >= settings.weekly_recap_target_max:
                break
            if len(selected) >= settings.weekly_recap_target_min:
                break
            selected.append(candidate)

    selected_ids = {c.story_id for c in selected}
    excluded = [c for c in candidates if c.story_id not in selected_ids]
    return selected, excluded


# ---------------------------------------------------------------------------
# Orchestration (async, read-only)
# ---------------------------------------------------------------------------


async def _build_candidate(session: AsyncSession, story: Story) -> WeeklyRecapCandidate | None:
    """None if the representative event has no EditorialTask, or its relevance tier is
    OUT_OF_SCOPE (hard-excluded, spec §10's own explicit reuse of existing editorial relevance
    logic) - never silently included with a fabricated score."""
    event = await session.get(NewsEvent, story.first_event_id)
    if event is None:
        return None

    task = await session.scalar(
        select(EditorialTask)
        .where(EditorialTask.event_id == story.first_event_id)
        .order_by(EditorialTask.updated_at.desc())
        .limit(1)
    )
    workflow = task.workflow if task is not None else None
    score = _extract_scoring_result(workflow)
    significance = _extract_significance(workflow)

    relevance = classify_editorial_relevance(event.title, event.content)
    if relevance.tier == OUT_OF_SCOPE:
        return None

    entities = list(story.entities or [])
    # Composite rank: base editorial score (0 if the scoring step never ran - never defaulted to
    # "pass"/excluded outright, since a Story can still be weekly-recap-worthy on relevance alone)
    # plus the same relevance rank_adjustment worker/content_cycle.py's own selection already
    # applies. `classify_editorial_relevance()` itself already folds the major-impact-override
    # boost into `rank_adjustment` (_MAJOR_IMPACT_OVERRIDE_RANK_ADJUSTMENT=5, applied whenever
    # major_impact_override=True) - not re-added here, which would double-count it (spec §13's own
    # "major-impact override behavior... should remain respected", not amplified further).
    rank_score = float(score or 0) + relevance.rank_adjustment

    return WeeklyRecapCandidate(
        story_id=story.id, representative_event_id=story.first_event_id, relevance_tier=relevance.tier,
        score=score, significance=significance, major_impact_override=relevance.major_impact_override,
        company_key=_company_key(entities), entities=entities, updated_at=story.updated_at,
        reason=relevance.reason, rank_score=rank_score,
    )


async def select_weekly_recap_stories(
    session: AsyncSession, *, now: datetime | None = None,
) -> tuple[list[WeeklyRecapCandidate], list[WeeklyRecapCandidate]]:
    """The pure/manual WEEKLY_RECAP entry point (spec §14). One Story contributes at most one
    weekly item by construction (`candidates` is already Story-level - one `WeeklyRecapCandidate`
    per `Story` row, never per `NewsEvent`). No scheduling, no worker integration, no Telegram, no
    DB writes."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=settings.weekly_recap_window_days)
    stories = list((await session.execute(select(Story).where(Story.updated_at >= cutoff))).scalars().all())

    candidates: list[WeeklyRecapCandidate] = []
    for story in stories:
        candidate = await _build_candidate(session, story)
        if candidate is not None:
            candidates.append(candidate)

    return select_weekly_recap_stories_from_candidates(candidates)
