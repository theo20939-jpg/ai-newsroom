"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 5: the deterministic evidence-sufficiency gate a trend
cluster must clear BEFORE it may ever become a `ContentOpportunity(TREND)` - "no strong trend" is
a legitimate, expected outcome (never a forced "best available" pick). Uses only REAL/DERIVED
signals the plan's own Trend Signal Model actually defines - no opaque composite "TrendScore".

SHADOW ONLY this phase (`settings.trend_autonomous_content_generation` stays False) -
`build_trend_opportunity()` exists and is fully tested, but nothing in this phase calls it to
submit a real opportunity into the live automatic trigger; that wiring is explicit future work,
gated on Founder-approved thresholds observed against real Phase 6 data."""
from __future__ import annotations

from dataclasses import dataclass, field

from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.trend_normalization import EngagementVelocity, NormalizedEngagement

_DEFAULT_MIN_CROSS_SOURCE_COUNT = 2
_DEFAULT_MAX_RECENCY_HOURS = 72.0
_DEFAULT_MIN_ENGAGEMENT_PERCENTILE = 0.7


@dataclass(frozen=True)
class TrendEvidence:
    """Every REAL/DERIVED signal the plan's own Trend Signal Model table names - deliberately no
    single opaque score field."""

    cross_source_count: int
    recency_hours: float
    cross_account_count: int | None = None  # REAL where the source's own API exposes it (None where it doesn't, e.g. Instagram hashtag media)
    normalized_engagement: NormalizedEngagement | None = None
    velocity: EngagementVelocity | None = None
    cluster_size: int = 1


@dataclass(frozen=True)
class EvidenceSufficiencyResult:
    sufficient: bool
    reasons: list[str] = field(default_factory=list)


def is_trend_evidence_sufficient(
    evidence: TrendEvidence, *, min_cross_source_count: int = _DEFAULT_MIN_CROSS_SOURCE_COUNT,
    max_recency_hours: float = _DEFAULT_MAX_RECENCY_HOURS,
    min_engagement_percentile: float = _DEFAULT_MIN_ENGAGEMENT_PERCENTILE,
) -> EvidenceSufficiencyResult:
    """Passes only when cross-source spread clears the bar AND (the cluster is still recent OR its
    normalized engagement is unusually high for its own source) - exactly the plan's own §6
    formula. Thresholds are disclosed parameters, not hardcoded blind guesses - tune against real
    observed data once Phase 6 adapters are live, never invented from nothing."""
    reasons: list[str] = []
    cross_source_ok = evidence.cross_source_count >= min_cross_source_count
    if not cross_source_ok:
        reasons.append(f"cross_source_count={evidence.cross_source_count} < required {min_cross_source_count}")

    is_recent = evidence.recency_hours <= max_recency_hours
    is_high_engagement = bool(
        evidence.normalized_engagement is not None and evidence.normalized_engagement.available
        and evidence.normalized_engagement.percentile is not None
        and evidence.normalized_engagement.percentile >= min_engagement_percentile
    )
    if not (is_recent or is_high_engagement):
        reasons.append(
            f"not recent enough (recency_hours={evidence.recency_hours} > {max_recency_hours}) and no "
            "unusually high engagement for its own source"
        )

    return EvidenceSufficiencyResult(sufficient=cross_source_ok and (is_recent or is_high_engagement), reasons=reasons)


def build_trend_opportunity(
    cluster_id: str, evidence: TrendEvidence, *, representative_text: str,
) -> ContentOpportunity:
    """Only ever meant to be called AFTER `is_trend_evidence_sufficient()` returns
    `sufficient=True` - never called blind (callers are expected to check the gate first;
    this function itself does not re-check it, matching `build_content_opportunity()`'s own
    "deterministic assembly of already-resolved inputs" convention). Confidence is derived from
    the SAME real evidence fields, never an opaque model score."""
    confidence = 0.3
    if evidence.cross_source_count >= 3:
        confidence += 0.1
    if (
        evidence.normalized_engagement is not None and evidence.normalized_engagement.available
        and (evidence.normalized_engagement.percentile or 0.0) >= 0.8
    ):
        confidence += 0.2
    confidence = min(confidence, 1.0)

    evidence_lines = [
        f"cross_source_count={evidence.cross_source_count}", f"recency_hours={evidence.recency_hours:.1f}",
    ]
    if evidence.normalized_engagement is not None and evidence.normalized_engagement.available:
        evidence_lines.append(f"engagement_percentile_within_source={evidence.normalized_engagement.percentile:.2f}")
    if evidence.velocity is not None and evidence.velocity.available:
        evidence_lines.append(f"velocity_per_hour={evidence.velocity.delta_per_hour:.2f}")
    else:
        evidence_lines.append("velocity=UNAVAILABLE (fewer than 2 real observations)")

    return ContentOpportunity(
        id=f"trend:{cluster_id}", source_type=OpportunitySourceType.TREND, trend_id=cluster_id,
        trend_relevance=confidence, product_mention_allowed=False,
        evidence=[f"trend cluster: {representative_text}"] + evidence_lines, confidence=confidence,
    )
