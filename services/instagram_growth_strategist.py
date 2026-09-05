"""INSTAGRAM GROWTH ENGINE v2, spec §36/§37/§38: Growth Strategist - a real structured advisory
layer (`InstagramGrowthStrategy`/`generate_growth_strategy()`), upgrading the previous foundation's
`propose_ideas_from_campaign_plan()` contract proof into something that actually combines
ContentOpportunity/Trend/Competitor/Audience/Series/evidence inputs.

CRITICAL (spec §37/§58): `apply_founder_directive_precedence()` is the ONE place a
StrategicDirective can override an already-resolved `product_mention_allowed` - a directive whose
structured `products`/`platforms` scope covers an opportunity's product always wins over whatever a
CampaignPlan/ClaimPolicy alone would have allowed (spec's own "Growth data says product mentions
perform well; Founder Directive says do not reveal NINJA AI yet; result: DO NOT reveal" example).
This reads the directive's STRUCTURED scope fields (database/models/strategic_directive.py -
already populated by the shared foundation's own LLM-parse-then-human-confirm flow), never
re-parses the free-text `instruction` itself - that would be exactly the "ad-hoc provider" spec §10
warns against for trend matching, and is even less appropriate for a safety-critical override.

CRITICAL (spec §95/§98): still never imports anything from services/telegram_*.py - shared truth,
independent execution."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from database.models.strategic_directive import DirectiveStatus, StrategicDirective
from services.campaign_planner import CampaignPlan
from services.instagram_competitor_intelligence import CompetitorGap
from services.instagram_content_opportunity import ContentOpportunity
from services.instagram_format_director import ContentFormat
from services.instagram_objective_selection import recommend_objective
from services.instagram_series import ContentSeries, is_recommendable_as_active


@dataclass(frozen=True)
class ContentIdea:
    """One idea the Growth Strategist proposes from a CampaignPlan - deliberately NOT required to
    match whatever a Telegram Strategy Director would independently choose for the same campaign
    (spec §95's own "Telegram Strategy Director may choose something completely different" example -
    shared truth, independent execution, never one plan rendered onto two platforms)."""

    format: ContentFormat
    concept: str
    campaign_id: str | None
    approved_claims: list[str] = field(default_factory=list)
    restricted_claims: list[str] = field(default_factory=list)


def propose_ideas_from_campaign_plan(plan: CampaignPlan) -> list[ContentIdea]:
    """Deterministic, structural derivation only (no LLM in this phase) - proves the CampaignPlan
    -> Instagram idea path is reachable and correctly propagates approved/restricted claims,
    never that this produces genuinely good creative ideas yet."""
    ideas: list[ContentIdea] = []
    if plan.phase in ("PRODUCT_TEASING", "FEATURE_REVEAL"):
        ideas.append(ContentIdea(
            format=ContentFormat.REEL, concept=f"show workflow for phase={plan.phase}",
            campaign_id=plan.campaign_id, approved_claims=list(plan.approved_claims),
            restricted_claims=list(plan.restricted_claims),
        ))
    if plan.key_messages:
        ideas.append(ContentIdea(
            format=ContentFormat.CAROUSEL, concept=f"educate on: {'; '.join(plan.key_messages)}",
            campaign_id=plan.campaign_id, approved_claims=list(plan.approved_claims),
            restricted_claims=list(plan.restricted_claims),
        ))
    return ideas


@dataclass(frozen=True)
class GrowthAutopsy:
    """Spec §93: evidence-based retrospective only - never storytelling without evidence."""

    subject: str
    what_happened: str
    what_was_expected: str
    what_differed: str
    supporting_evidence: list[str] = field(default_factory=list)
    next_test: str | None = None


@dataclass(frozen=True)
class OpportunityContext:
    """Pairs a ContentOpportunity with the product slug (StrategicDirective's own scoping unit,
    database/models/strategic_directive.py) needed to check Founder Directive precedence -
    `ContentOpportunity.product_id` alone is an opaque reference, never assumed to already be a
    slug."""

    opportunity: ContentOpportunity
    product_slug: str | None = None


def directive_blocks_product(
    directives: list[StrategicDirective], *, product_slug: str, platform: str = "instagram",
) -> list[StrategicDirective]:
    """A directive with an empty `products`/`platforms` scope is read as "applies to everything" -
    exactly as broad as a founder saying "all products, all platforms" (module docstring, spec
    §12/§14's own "as narrow or as broad as the founder actually said" instruction)."""
    matches = []
    for directive in directives:
        if directive.status != DirectiveStatus.ACTIVE:
            continue
        scoped_products = directive.products or []
        scoped_platforms = directive.platforms or []
        product_matches = not scoped_products or product_slug in scoped_products
        platform_matches = not scoped_platforms or platform in scoped_platforms
        if product_matches and platform_matches:
            matches.append(directive)
    return matches


def apply_founder_directive_precedence(
    contexts: list[OpportunityContext], directives: list[StrategicDirective], *, platform: str = "instagram",
) -> tuple[list[ContentOpportunity], list[str]]:
    """Spec §37/§58: Business truth outranks engagement optimization - returns opportunities with
    `product_mention_allowed` forced False wherever an active directive blocks that product,
    regardless of what the CampaignPlan alone resolved, plus the avoidance notes explaining why."""
    avoidance_notes: list[str] = []
    resolved: list[ContentOpportunity] = []
    for ctx in contexts:
        opportunity = ctx.opportunity
        if ctx.product_slug is not None and opportunity.product_mention_allowed:
            blocking = directive_blocks_product(directives, product_slug=ctx.product_slug, platform=platform)
            if blocking:
                opportunity = replace(opportunity, product_mention_allowed=False)
                avoidance_notes.append(
                    f"product_mention for product={ctx.product_slug!r} blocked by active founder "
                    f"directive: {blocking[0].instruction!r}"
                )
        resolved.append(opportunity)
    return resolved, avoidance_notes


@dataclass(frozen=True)
class InstagramGrowthStrategy:
    """Spec §36's own output shape - advisory only, never publication authority."""

    priority_opportunities: list[ContentOpportunity] = field(default_factory=list)
    objective_mix: dict[str, int] = field(default_factory=dict)
    campaign_support: list[str] = field(default_factory=list)
    content_gaps: list[str] = field(default_factory=list)
    trend_opportunities: list[str] = field(default_factory=list)
    series_recommendations: list[str] = field(default_factory=list)
    experiment_recommendations: list[str] = field(default_factory=list)
    avoidance_notes: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    confidence: float = 0.2


def generate_growth_strategy(
    *, opportunity_contexts: list[OpportunityContext], directives: list[StrategicDirective] | None = None,
    competitor_gaps: list[CompetitorGap] | None = None, series: list[ContentSeries] | None = None,
    trend_match_summaries: list[str] | None = None, platform: str = "instagram",
) -> InstagramGrowthStrategy:
    """Deterministic assembly (spec §60: no LLM call needed to combine already-resolved structured
    inputs) - the one function proving ContentOpportunity + StrategicDirective + CompetitorGap +
    Series all actually feed a single advisory output, never several disconnected contracts."""
    resolved_opportunities, avoidance_notes = apply_founder_directive_precedence(
        opportunity_contexts, directives or [], platform=platform,
    )

    priority_opportunities = sorted(
        resolved_opportunities,
        key=lambda o: (o.news_value + o.trend_relevance + o.campaign_relevance + o.audience_relevance),
        reverse=True,
    )

    objective_mix: dict[str, int] = {}
    campaign_support: set[str] = set()
    risks: list[str] = []
    for opportunity in priority_opportunities:
        recommendation = recommend_objective(opportunity=opportunity)
        objective_mix[recommendation.primary_objective.value] = objective_mix.get(recommendation.primary_objective.value, 0) + 1
        if opportunity.campaign_id:
            campaign_support.add(opportunity.campaign_id)
        if opportunity.embargo_constraints:
            risks.append(f"opportunity={opportunity.id} still under embargo: {opportunity.embargo_constraints}")

    content_gaps = [gap.description for gap in (competitor_gaps or [])]

    series_recommendations: list[str] = []
    for one_series in series or []:
        if not is_recommendable_as_active(one_series):
            continue
        series_recommendations.append(
            f"series={one_series.id} ({one_series.status.value}): continue testing, not yet a permanent franchise"
            if one_series.status.value == "series_testing"
            else f"series={one_series.id} ({one_series.status.value}): keep running with current cadence"
        )

    confidence = round(
        sum(o.confidence for o in priority_opportunities) / len(priority_opportunities), 3
    ) if priority_opportunities else 0.1

    return InstagramGrowthStrategy(
        priority_opportunities=priority_opportunities, objective_mix=objective_mix,
        campaign_support=sorted(campaign_support), content_gaps=content_gaps,
        trend_opportunities=trend_match_summaries or [], series_recommendations=series_recommendations,
        avoidance_notes=avoidance_notes, risks=risks, confidence=confidence,
    )


def suggest_amplification(*, winner_content_id: str, winner_format: ContentFormat) -> list[str]:
    """Spec §49: a winner may suggest a follow-up, never an automatic cross-platform duplicate
    (spec §50's own "Telegram and Instagram do NOT share format decisions" principle) - every
    suggestion here names a human decision to make, not an action this function takes."""
    suggestions = [f"consider a Stories amplification sequence for content_id={winner_content_id}"]
    if winner_format == ContentFormat.REEL:
        suggestions.append(f"consider a Carousel expansion of content_id={winner_content_id} for saves/reference value")
    elif winner_format == ContentFormat.CAROUSEL:
        suggestions.append(f"consider a Reel summarizing content_id={winner_content_id} if a real video asset becomes available")
    suggestions.append(
        f"a Telegram follow-up on the SAME underlying topic as content_id={winner_content_id} is a "
        "separate creative decision for the Telegram Director, never an automatic duplicate"
    )
    return suggestions
