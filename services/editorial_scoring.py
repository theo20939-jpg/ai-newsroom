"""Editorial Score V2 (Phase 15 M4): a deterministic, explainable combination of the existing
LLM editorial judgment with signals already available in the current architecture - freshness,
persisted real engagement (Phase 15 M3), source reliability (reused from Triage), and a
documented novelty fallback (no real novelty signal exists yet anywhere in this codebase).

Zero new LLM/provider calls: `legacy_llm_score` is the *existing* ScoringCapability output,
already produced once per NEWS_ANALYSIS run - this module never calls an LLM itself.

Split into a pure calculator (`compute_editorial_score_v2`, no I/O, fully unit-testable - mirrors
services/freshness.py and services/triage.py's own established pure-function convention) and one
thin async orchestration function (`apply_editorial_scoring_v2`) that does the two extra,
cheap, indexed DB reads V2 needs and is the only piece capabilities/executor.py calls.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from services.freshness import compute_freshness
from services.triage import DEFAULT_RELIABILITY_SCORE

logger = logging.getLogger(__name__)

SCORING_VERSION = "v2"

# The five components' equal-footing neutral value - literally the same "fixed neutral value,
# the midpoint of the configured [0, 1] range" convention services/triage.py's own
# DEFAULT_RELIABILITY_SCORE already established (0.5 there too; kept as a separate named
# constant here since it applies to engagement/novelty, not reliability specifically).
NEUTRAL_COMPONENT_VALUE = 0.5

# A same-source baseline needs at least this many recent, engagement-bearing NewsEvent rows
# before it is trusted for a percentile comparison - below this, one or two data points could
# swing the result arbitrarily. Below the minimum, engagement falls back to neutral and
# `coverage.source_baseline_available` is reported False, never silently computed anyway.
MIN_ENGAGEMENT_BASELINE_SAMPLE = 3
# Bounded rolling window (Contract-style "PRODUCT CONFIGURATION", not architecture) - recent
# same-source events only, not the source's entire history, so the baseline tracks a channel's
# *current* typical performance rather than being diluted by very old posts.
ENGAGEMENT_BASELINE_WINDOW = 20

# Default weights - see core/config.py's own docstring for the reasoning and the settings that
# make these tunable at runtime without a code change. Kept here too as the pure calculator's
# own default and as the single source every test asserts sums to 1.0 against.
DEFAULT_WEIGHTS: dict[str, float] = {
    "semantic_editorial": 0.40,
    "freshness": 0.20,
    "engagement": 0.20,
    "source_reliability": 0.10,
    "novelty": 0.10,
}

_COMPONENT_KEYS: tuple[str, ...] = (
    "semantic_editorial", "freshness", "engagement", "source_reliability", "novelty",
)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _engagement_magnitude(metrics: dict[str, int | None]) -> int:
    """Sum of whichever engagement metrics are actually observed (non-None). A metric that is
    None (unsupported by this source/message) is excluded from the sum entirely - never treated
    as 0 - so a source with three unsupported metrics and one real 0 is not penalized relative
    to a source that happens to report all four. Deliberately unweighted (views/forwards/
    replies/reactions summed at face value): a documented simplification, not a new engagement
    taxonomy - M4 is scoring-only, see docs/phase15_m4_editorial_scoring_v2_report.md §5."""
    return sum(value for value in metrics.values() if value is not None)


def _compute_engagement_component(
    metrics: dict[str, int | None], baseline_samples: list[int]
) -> tuple[float, bool, bool]:
    """Returns (component_value, engagement_available, source_baseline_available).

    Percentile rank of this event's engagement magnitude within its own source's recent
    baseline sample - bounded [0, 1] by construction, so it is naturally robust to both
    cross-source scale differences (a 1M-audience channel is only ever compared against its own
    baseline, never against a small channel's raw counts) and to a single extreme outlier in the
    baseline (percentile rank does not blow up the way a raw ratio would).
    """
    observed = [value for value in metrics.values() if value is not None]
    engagement_available = len(observed) > 0
    if not engagement_available:
        return NEUTRAL_COMPONENT_VALUE, False, False

    if len(baseline_samples) < MIN_ENGAGEMENT_BASELINE_SAMPLE:
        return NEUTRAL_COMPONENT_VALUE, True, False

    current = sum(observed)
    at_or_below = sum(1 for sample in baseline_samples if sample <= current)
    percentile = at_or_below / len(baseline_samples)
    return _clamp01(percentile), True, True


def _band(value: float) -> str:
    if value >= 0.66:
        return "high"
    if value >= 0.33:
        return "medium"
    return "low"


def _build_reason(components: dict[str, float], coverage: dict[str, bool]) -> str:
    """Deterministic, band-derived explanation - never an LLM call (M4.6). Produces sentences of
    the shape "High semantic relevance, very fresh, above-normal engagement for this source,
    medium source reliability." - the exact worked example from the M4 task."""
    parts: list[str] = [f"{_band(components['semantic_editorial'])} semantic relevance"]

    fresh_word = {
        "high": "very fresh", "medium": "moderately fresh", "low": "stale",
    }[_band(components["freshness"])]
    parts.append(fresh_word)

    if coverage["engagement_available"] and coverage["source_baseline_available"]:
        eng_word = {
            "high": "above-normal engagement for this source",
            "medium": "typical engagement for this source",
            "low": "below-normal engagement for this source",
        }[_band(components["engagement"])]
        parts.append(eng_word)
    else:
        parts.append("engagement data unavailable")

    rel_word = f"{_band(components['source_reliability'])} source reliability"
    parts.append(rel_word)

    sentence = ", ".join(parts)
    return sentence[0].upper() + sentence[1:] + "."


def compute_editorial_score_v2(
    *,
    legacy_llm_score: int,
    published_at: datetime | None,
    collected_at: datetime,
    reference_now: datetime,
    reliability_score: float | None,
    event_metrics: dict[str, int | None],
    baseline_samples: list[int],
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Pure. No I/O, no LLM call, no system-clock read (reference_now is always an explicit
    argument - mirrors services/freshness.py's own contract). Deterministic: identical inputs
    always produce an identical output dict.

    `event_metrics` is the four M3-persisted fields keyed by name (views_count/forwards_count/
    replies_count/reactions_count) - None means unavailable, exactly as persisted.
    """
    active_weights = DEFAULT_WEIGHTS if weights is None else weights

    semantic = _clamp01(legacy_llm_score / 100.0)
    freshness = compute_freshness(published_at, collected_at, reference_now).weight

    reliability_available = reliability_score is not None
    reliability = DEFAULT_RELIABILITY_SCORE if reliability_score is None else reliability_score

    engagement, engagement_available, baseline_available = _compute_engagement_component(
        event_metrics, baseline_samples
    )

    # Novelty: no reliable signal exists anywhere in the current architecture (confirmed:
    # services/deduplication.py is an exact-hash gate at collection time, not a similarity
    # measure, and no Research/Intelligence/Engagement Capability output carries a
    # novelty/duplicate field - docs/phase15_m4_editorial_scoring_v2_report.md §7). A precise
    # novelty score is never fabricated; this is a permanent, honestly-labeled fallback for M4,
    # not a placeholder awaiting silent replacement.
    novelty = NEUTRAL_COMPONENT_VALUE
    novelty_available = False

    components = {
        "semantic_editorial": semantic,
        "freshness": freshness,
        "engagement": engagement,
        "source_reliability": reliability,
        "novelty": novelty,
    }

    weighted_sum = sum(components[key] * active_weights[key] for key in _COMPONENT_KEYS)
    score = round(_clamp01(weighted_sum) * 100)

    coverage = {
        "engagement_available": engagement_available,
        "source_baseline_available": baseline_available,
        "source_reliability_available": reliability_available,
        "novelty_available": novelty_available,
    }

    return {
        "score": score,
        "version": SCORING_VERSION,
        "components": components,
        "coverage": coverage,
        "reason": _build_reason(components, coverage),
        "legacy_llm_score": legacy_llm_score,
        "weights": dict(active_weights),
    }


async def fetch_engagement_baseline(
    session: AsyncSession, source_id: UUID, exclude_event_id: UUID, *, window: int = ENGAGEMENT_BASELINE_WINDOW
) -> list[int]:
    """Recent, engagement-bearing NewsEvent rows from the same source (excluding the event being
    scored), most-recent-first, capped at `window` - a bounded rolling sample, never the
    source's full history. Uses the existing ix_news_events_source_id index; no new index/
    migration required."""
    stmt = (
        select(
            NewsEvent.views_count, NewsEvent.forwards_count, NewsEvent.replies_count, NewsEvent.reactions_count
        )
        .where(
            NewsEvent.source_id == source_id,
            NewsEvent.id != exclude_event_id,
            or_(
                NewsEvent.views_count.is_not(None),
                NewsEvent.forwards_count.is_not(None),
                NewsEvent.replies_count.is_not(None),
                NewsEvent.reactions_count.is_not(None),
            ),
        )
        .order_by(NewsEvent.collected_at.desc())
        .limit(window)
    )
    rows = (await session.execute(stmt)).all()
    return [
        _engagement_magnitude(
            {"views_count": views, "forwards_count": forwards, "replies_count": replies, "reactions_count": reactions}
        )
        for views, forwards, replies, reactions in rows
    ]


def _settings_weights() -> dict[str, float]:
    return {
        "semantic_editorial": settings.editorial_scoring_weight_semantic,
        "freshness": settings.editorial_scoring_weight_freshness,
        "engagement": settings.editorial_scoring_weight_engagement,
        "source_reliability": settings.editorial_scoring_weight_source_reliability,
        "novelty": settings.editorial_scoring_weight_novelty,
    }


async def apply_editorial_scoring_v2(
    session: AsyncSession, news_event: NewsEvent, structured_output: dict[str, Any], *, task_id: UUID
) -> dict[str, Any]:
    """Called only from capabilities/executor.py, only for the "scoring" step, only after
    ScoringCapability's own LLM call already succeeded. Returns `structured_output` completely
    unchanged - zero DB queries - when `editorial_scoring_version` is not "v2" (the rollback
    path costs nothing).

    On "v2", the original `structured_output` (including its own "rationale" key, preserved
    verbatim for anything that might still read it) is merged with the V2 contract - the V2
    "score" key deliberately overwrites the LLM-only score at this same top-level key, which is
    the one and only thing worker/content_cycle.py's _extract_scoring_result() reads, so no
    downstream consumer needs to change.
    """
    if settings.editorial_scoring_version != "v2":
        return structured_output

    legacy_score = structured_output.get("score")
    if not isinstance(legacy_score, int) or isinstance(legacy_score, bool):
        # Defensive only: ScoringCapability's own floor-validation already guarantees an int
        # here in practice. V2 must never fabricate a semantic component from a missing/
        # malformed LLM score - fall back to the unmodified v1 output rather than guess.
        logger.warning(
            "editorial_score_v2_skipped_malformed_legacy_score",
            extra={"task_id": str(task_id), "event_id": str(news_event.id)},
        )
        return structured_output

    source = await session.get(NewsSource, news_event.source_id)
    reliability_score = source.reliability_score if source is not None else None

    baseline_samples = await fetch_engagement_baseline(session, news_event.source_id, news_event.id)

    result = compute_editorial_score_v2(
        legacy_llm_score=legacy_score,
        published_at=news_event.published_at,
        collected_at=news_event.collected_at,
        reference_now=datetime.now(timezone.utc),
        reliability_score=reliability_score,
        event_metrics={
            "views_count": news_event.views_count,
            "forwards_count": news_event.forwards_count,
            "replies_count": news_event.replies_count,
            "reactions_count": news_event.reactions_count,
        },
        baseline_samples=baseline_samples,
        weights=_settings_weights(),
    )

    logger.info(
        "editorial_score_v2_computed",
        extra={
            "event_id": str(news_event.id),
            "task_id": str(task_id),
            "score": result["score"],
            "version": result["version"],
            "components": result["components"],
            "coverage": result["coverage"],
        },
    )

    return {**structured_output, **result}
