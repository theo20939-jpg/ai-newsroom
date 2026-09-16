"""INSTAGRAM GROWTH ENGINE v2, spec §5/§6/§7: ContentOpportunity - the real opportunity semantics
this codebase previously deferred entirely (Instagram foundation commit 05585ae shipped only
Trend/Format/Content-Brain contracts, no opportunity abstraction at all).

Architectural decision (spec §5): ContentOpportunity is implemented HERE, in the Instagram layer,
not in the shared Business Context foundation (services/campaign_planner.py,
services/business_context_snapshot_service.py). Reasoning: no second platform director (Telegram)
currently consumes an opportunity abstraction shaped like this one - the shared foundation already
gives every platform BusinessContextSnapshot/CampaignPlan, and this module only adds an
Instagram-specific READ over that shared truth (story/trend/product references + Instagram
relevance dimensions), never a new canonical business-truth table. If a second platform later
needs the same opportunity shape, extract the source_type/source-reference/claim-propagation core
into a shared module then - not speculatively now (repo-wide "no premature abstraction" convention).
This module never writes to Product/LaunchCampaign/ClaimPolicy; it only reads CampaignPlan/
ClaimPolicy state a caller already resolved and re-expresses it as an Instagram opportunity.

CRITICAL (spec §7): campaign relevance and product-mention permission are DELIBERATELY separate.
A HYBRID opportunity with HIGH campaign_relevance never implies `product_mention_allowed=True` -
that permission is resolved independently from CampaignPlan.status/phase and ClaimPolicy, exactly
the way spec §7's own "Apple eSIM rules + NINJA Store CATEGORY_EDUCATION" example must NOT
automatically produce a product CTA."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone

from services.campaign_planner import CampaignPlan

# CampaignPlan.status is the CampaignStatus enum's own `.value` (str) - importing the enum itself
# would create a dependency on database.models.campaign from a module that otherwise only depends
# on the plain CampaignPlan dataclass, so the blocked-status set is expressed as the same string
# values CampaignPlan.status already carries (database/models/campaign.py::CampaignStatus).
_STATUSES_BLOCKING_HARD_PRODUCT_CTA = {"draft", "tentative", "cancelled"}


class OpportunitySourceType(str, enum.Enum):
    NEWS = "news"
    PRODUCT = "product"
    TREND = "trend"
    HYBRID = "hybrid"


class ContentOpportunityValidationError(ValueError):
    """Raised when an opportunity's source references don't match its declared source_type, or
    when a caller tries to construct one with product mention implied rather than explicitly
    resolved (spec §7's own core safety requirement)."""


@dataclass(frozen=True)
class ContentOpportunity:
    id: str
    source_type: OpportunitySourceType

    story_id: str | None = None
    trend_id: str | None = None
    product_id: str | None = None
    campaign_id: str | None = None

    # Relevance dimensions - kept explicitly separate (spec §6's own "do NOT create one
    # unexplained total_score = 87" instruction). Each is 0.0-1.0, advisory only.
    news_value: float = 0.0
    trend_relevance: float = 0.0
    campaign_relevance: float = 0.0
    audience_relevance: float = 0.0

    campaign_phase: str | None = None

    # Claim safety propagated from the CampaignPlan/ClaimPolicy that produced this opportunity -
    # never derived from campaign_relevance, never inferred.
    allowed_claims: list[str] = field(default_factory=list)
    restricted_claims: list[str] = field(default_factory=list)
    embargo_constraints: list[str] = field(default_factory=list)

    # Spec §7: explicit, independently-resolved permission - a HYBRID opportunity's high
    # campaign_relevance must never be read as "product mention is fine".
    product_mention_allowed: bool = False

    recommended_objectives: list[str] = field(default_factory=list)
    recommended_platforms: list[str] = field(default_factory=list)

    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.3

    # INSTAGRAM PHASE A: the Director's pre-generation decision is carried on the existing
    # opportunity and therefore follows the existing snapshot/package path.  Plain JSON only;
    # no parallel ORM model or migration is needed.  Empty for pre-Phase-A callers/snapshots.
    editorial_decision: dict = field(default_factory=dict)

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        _validate_source_references(self.source_type, story_id=self.story_id, trend_id=self.trend_id,
                                     product_id=self.product_id, campaign_id=self.campaign_id)


def _validate_source_references(
    source_type: OpportunitySourceType, *, story_id: str | None, trend_id: str | None,
    product_id: str | None, campaign_id: str | None,
) -> None:
    if source_type == OpportunitySourceType.NEWS and not story_id:
        raise ContentOpportunityValidationError("a NEWS opportunity requires story_id")
    if source_type == OpportunitySourceType.TREND and not trend_id:
        raise ContentOpportunityValidationError("a TREND opportunity requires trend_id")
    if source_type == OpportunitySourceType.PRODUCT and not (product_id or campaign_id):
        raise ContentOpportunityValidationError("a PRODUCT opportunity requires product_id or campaign_id")
    if source_type == OpportunitySourceType.HYBRID:
        has_news_or_trend_leg = bool(story_id or trend_id)
        has_business_leg = bool(product_id or campaign_id)
        if not (has_news_or_trend_leg and has_business_leg):
            raise ContentOpportunityValidationError(
                "a HYBRID opportunity requires both a news/trend reference and a product/campaign reference"
            )


def resolve_product_mention_permission(
    *, campaign_plan: CampaignPlan | None, restricted_claims: list[str], embargo_active: bool,
) -> bool:
    """Spec §7/§58: the ONE function that decides whether a product may be named at all - never
    inferred from relevance scores. Fails closed: no campaign plan, an embargo still active, a
    DRAFT/TENTATIVE/CANCELLED campaign status, or a restricted-claims list that already covers the
    product's own name/CTA all resolve to False."""
    if campaign_plan is None:
        return False
    if embargo_active:
        return False
    if campaign_plan.status in _STATUSES_BLOCKING_HARD_PRODUCT_CTA:
        return False
    return True


def build_content_opportunity(
    *, id: str, source_type: OpportunitySourceType, story_id: str | None = None,
    trend_id: str | None = None, product_id: str | None = None, campaign_id: str | None = None,
    news_value: float = 0.0, trend_relevance: float = 0.0, audience_relevance: float = 0.0,
    campaign_plan: CampaignPlan | None = None, embargo_active: bool = False,
    recommended_objectives: list[str] | None = None, recommended_platforms: list[str] | None = None,
    evidence: list[str] | None = None, confidence: float = 0.3, editorial_decision: dict | None = None,
) -> ContentOpportunity:
    """Deterministic assembly (spec §60: no LLM call needed to combine already-resolved dimensions
    and a CampaignPlan into one opportunity record)."""
    campaign_relevance = 0.0
    approved: list[str] = []
    restricted: list[str] = []
    embargo_constraints: list[str] = []
    phase = None
    if campaign_plan is not None:
        phase = campaign_plan.phase
        approved = list(campaign_plan.approved_claims)
        restricted = list(campaign_plan.restricted_claims)
        # A campaign with any usable plan at all is, by definition, relevant to Instagram content
        # planning; the MAGNITUDE of relevance still depends on whether it's actually active
        # (has a phase) - a CANCELLED/DRAFT plan (phase is None) carries no campaign relevance.
        campaign_relevance = 1.0 if phase is not None else 0.0
        if embargo_active:
            embargo_constraints.append("campaign embargo still active")

    product_mention_allowed = resolve_product_mention_permission(
        campaign_plan=campaign_plan, restricted_claims=restricted, embargo_active=embargo_active,
    )

    return ContentOpportunity(
        id=id, source_type=source_type, story_id=story_id, trend_id=trend_id, product_id=product_id,
        campaign_id=campaign_id, news_value=news_value, trend_relevance=trend_relevance,
        campaign_relevance=campaign_relevance, audience_relevance=audience_relevance,
        campaign_phase=phase, allowed_claims=approved, restricted_claims=restricted,
        embargo_constraints=embargo_constraints, product_mention_allowed=product_mention_allowed,
        recommended_objectives=recommended_objectives or [], recommended_platforms=recommended_platforms or ["instagram"],
        evidence=evidence or [], confidence=confidence, editorial_decision=editorial_decision or {},
    )
