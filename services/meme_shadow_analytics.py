"""Meme Shadow Analytics (Phase 18.5 M1/M2): read-only collection + metrics over the existing,
unmodified `services.meme_opportunity.assess_meme_opportunity()` classifier, run directly against
already-persisted `NewsEvent` data (docs/phase18_5_meme_shadow_validation_discovery.md).

Adds ZERO new business logic for meme opportunity detection itself - every decision, score, and
reason code here comes straight from the existing, already-shipped (Phase 18 M1) classifier.
This module only normalizes that classifier's own output into a compact, storable record and
computes aggregate statistics over a batch of them. No LLM call, no network call, no database
write, no Telegram call, no `CapabilityExecutor`/`WorkflowRunner` involvement anywhere in this
module - `evaluate_event_shadow()` calls `assess_meme_opportunity()` directly, exactly as
`capabilities.executor.CapabilityExecutor._attach_meme_opportunity()` does, but from a completely
separate, read-only code path that never touches a workflow or task.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from database.models.news_event import EventCategory
from schemas.meme_opportunity import MemeOpportunityAssessment, MemeOpportunityDecision
from schemas.meme_shadow_analytics import MemeOpportunityLabel, MemeShadowRecord
from services.meme_opportunity import assess_meme_opportunity

logger = logging.getLogger(__name__)

# The single source of truth for the brief's own "HIGH/MEDIUM/LOW/BLOCKED" reporting vocabulary -
# never duplicated, never re-derived independently elsewhere in this phase.
LABEL_BY_DECISION: dict[MemeOpportunityDecision, MemeOpportunityLabel] = {
    MemeOpportunityDecision.MEME_READY: MemeOpportunityLabel.HIGH,
    MemeOpportunityDecision.REVIEW: MemeOpportunityLabel.MEDIUM,
    MemeOpportunityDecision.NOT_SUITABLE: MemeOpportunityLabel.LOW,
    MemeOpportunityDecision.INSUFFICIENT_SOURCE: MemeOpportunityLabel.LOW,
    MemeOpportunityDecision.SENSITIVE_BLOCK: MemeOpportunityLabel.BLOCKED,
}


def label_for_decision(decision: MemeOpportunityDecision) -> MemeOpportunityLabel:
    return LABEL_BY_DECISION[decision]


def build_shadow_record(
    event_id: UUID,
    category: EventCategory,
    source_name: str | None,
    assessment: MemeOpportunityAssessment,
    *,
    now: datetime | None = None,
) -> MemeShadowRecord:
    """Pure - normalizes an already-computed `MemeOpportunityAssessment` into a storable record.
    Never includes the event's own title/content text (module docstring's own "no raw content"
    discipline) - only `assessment`'s own already-redacted evidence phrases (`services.
    meme_opportunity.detect_sensitive_categories()`'s own evidence-only convention, unchanged
    here)."""
    return MemeShadowRecord(
        event_id=str(event_id),
        category=category.value,
        source_name=source_name,
        opportunity_decision=assessment.decision.value,
        opportunity_label=label_for_decision(assessment.decision),
        composite_score=assessment.signals.composite_score,
        reason_codes=list(assessment.reason_codes),
        sensitivity_categories=list(assessment.sensitivity_categories),
        evidence_patterns=list(assessment.evidence),
        source_sufficiency=assessment.source_sufficiency,
        collected_at=now or datetime.now(timezone.utc),
    )


def evaluate_event_shadow(
    event_id: UUID,
    title: str,
    content: str | None,
    category: EventCategory,
    published_at: datetime | None,
    source_name: str | None,
    *,
    research_output: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> MemeShadowRecord | None:
    """Failure-isolated wrapper around `assess_meme_opportunity()` + `build_shadow_record()` - a
    malformed/unexpected event (e.g. a title that trips an unrelated bug) is logged and skipped
    (`None`), never allowed to abort an entire batch collection run. Mirrors
    `capabilities.executor.CapabilityExecutor._attach_meme_opportunity()`'s own "a classifier
    failure must never propagate" discipline, applied here to a batch context instead of a single
    workflow step."""
    try:
        assessment = assess_meme_opportunity(
            title, content, category, published_at, research_output or {"facts": [], "gaps": []}, now=now,
        )
        return build_shadow_record(event_id, category, source_name, assessment, now=now)
    except Exception:
        logger.warning("meme_shadow_evaluation_failed", extra={"event_id": str(event_id)})
        return None


# ---------------------------------------------------------------------------
# M2: aggregate metrics over a batch of already-collected records.
# ---------------------------------------------------------------------------


def opportunity_rate(records: list[MemeShadowRecord]) -> float:
    """Brief's own formula: potential memes / all analyzed news. "Potential meme" = HIGH or
    MEDIUM label (mirrors M7's own "PROCEED" grouping precedent from the Phase 18 M1 report's own
    gold-set backtest - MEME_READY and REVIEW both mean "a human would see this")."""
    if not records:
        return 0.0
    potential = sum(1 for r in records if r.opportunity_label in (MemeOpportunityLabel.HIGH, MemeOpportunityLabel.MEDIUM))
    return potential / len(records)


def category_distribution(records: list[MemeShadowRecord]) -> dict[str, float]:
    """Share of HIGH/MEDIUM ("potential meme") records attributable to each category - answers
    "which categories give the most meme potential," not merely "how many events per category
    exist" (that is a separate, simpler count computed directly from raw NewsEvent rows in the
    collection script, not this function)."""
    potential = [r for r in records if r.opportunity_label in (MemeOpportunityLabel.HIGH, MemeOpportunityLabel.MEDIUM)]
    if not potential:
        return {}
    counts: dict[str, int] = {}
    for r in potential:
        counts[r.category] = counts.get(r.category, 0) + 1
    total = len(potential)
    return {category: count / total for category, count in sorted(counts.items(), key=lambda kv: -kv[1])}


def safety_block_rate(records: list[MemeShadowRecord]) -> float:
    """Share of ALL analyzed records that were hard-blocked for safety - a distinct denominator
    from `opportunity_rate()`'s own "potential memes" numerator, deliberately: this answers "how
    often does the safety net trigger at all," not "how often does it trigger among good
    candidates."""
    if not records:
        return 0.0
    blocked = sum(1 for r in records if r.opportunity_label == MemeOpportunityLabel.BLOCKED)
    return blocked / len(records)


# Maps each reason/evidence code the classifier can emit to the brief's own named pattern
# categories (irony, contradiction, absurdity, controversy, emotional contrast, unexpected
# result) - a reporting-layer relabeling only, never a second scoring pass. Built directly from
# `services/meme_opportunity.py`'s own real evidence-code vocabulary (`hype_without_substance`,
# `self_referential_reassurance`, `contrast_connector`, `explicit_irony_marker`,
# `statistic_about_people`), not invented independently of it.
_PATTERN_NAME_BY_EVIDENCE_PREFIX: dict[str, str] = {
    "contrast_connector": "contradiction",
    "hype_without_substance": "unexpected_result",
    "self_referential_reassurance": "irony",
    "explicit_irony_marker": "irony",
    "statistic_about_people": "emotional_contrast",
    "relatability_keyword": "emotional_contrast",
}


def pattern_performance(records: list[MemeShadowRecord]) -> dict[str, int]:
    """Counts how often each named pattern's own evidence code appears among HIGH/MEDIUM
    ("potential meme") records - answers the brief's own "какие признаки работают" question using
    real evidence codes the classifier actually emitted, never a hypothetical list."""
    potential = [r for r in records if r.opportunity_label in (MemeOpportunityLabel.HIGH, MemeOpportunityLabel.MEDIUM)]
    counts: dict[str, int] = {}
    for record in potential:
        for evidence in record.evidence_patterns:
            for prefix, pattern_name in _PATTERN_NAME_BY_EVIDENCE_PREFIX.items():
                if evidence.startswith(prefix):
                    counts[pattern_name] = counts.get(pattern_name, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def decision_counts(records: list[MemeShadowRecord]) -> dict[str, int]:
    """Raw counts per `MemeOpportunityLabel` - the M0 audit's own "сколько получает
    HIGH/MEDIUM/LOW/BLOCKED" question, answered directly."""
    counts: dict[str, int] = {label.value: 0 for label in MemeOpportunityLabel}
    for record in records:
        counts[record.opportunity_label.value] += 1
    return counts
