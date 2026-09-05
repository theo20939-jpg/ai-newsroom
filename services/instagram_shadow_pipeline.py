"""INSTAGRAM-GROWTH-3, item 7/16: the real shadow planning chain -
ContentOpportunity -> Growth Strategy -> ObjectiveRecommendation -> FormatDecision -> Creative
Director - wired together into ONE deterministic assembly function, `build_shadow_plan()`, that
retains a reference to every upstream step's own evidence (item 7's own explicit requirement).
`render_shadow_plan_text()` produces the renderable text shape item 16 specifies - no Telegram UI
wiring in this phase, just a structured, human-readable result ready to display later.

CRITICAL: this module never calls the AI Gateway itself - Creative Director generation
(services/instagram_creative_director.py) is optional and, if the caller already ran it, is folded
in via `creative_outcome`; `build_shadow_plan()` itself is pure, deterministic assembly (spec §60's
own cost-control discipline: no LLM call to combine already-resolved structured data)."""
from __future__ import annotations

from dataclasses import dataclass, field

from services.instagram_content_opportunity import ContentOpportunity
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_format_director import FormatDecision
from services.instagram_growth_strategist import InstagramGrowthStrategy
from services.instagram_hook_intelligence import Hook
from services.instagram_objective_selection import ObjectiveRecommendation


@dataclass(frozen=True)
class ShadowPlanResult:
    campaign_name: str | None
    campaign_phase: str | None
    opportunity_description: str
    primary_objective: str
    audience_description: str
    recommended_format: str
    hook_family: str | None
    creative_concept_summary: str | None
    alternative_format: str | None
    alternative_objective: str | None
    product_mention_allowed: bool
    restricted_claims: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.0


def _creative_concept_summary(creative_outcome: CreativeGenerationOutcome | None) -> str | None:
    if creative_outcome is None:
        return None
    if creative_outcome.single is not None:
        return creative_outcome.single.creative_angle
    if creative_outcome.carousel is not None:
        return f"{len(creative_outcome.carousel.slides)}-slide carousel: {creative_outcome.carousel.hook_slide.slide_copy}"
    if creative_outcome.reel is not None:
        return creative_outcome.reel.hook
    return None


def build_shadow_plan(
    *, opportunity: ContentOpportunity, campaign_name: str | None, objective_recommendation: ObjectiveRecommendation,
    format_decision: FormatDecision, audience_description: str = "", hook: Hook | None = None,
    growth_strategy: InstagramGrowthStrategy | None = None, creative_outcome: CreativeGenerationOutcome | None = None,
) -> ShadowPlanResult:
    evidence: list[str] = [*opportunity.evidence, *objective_recommendation.evidence]
    if format_decision.why:
        evidence.append(f"format_director: {format_decision.why}")
    if growth_strategy is not None:
        evidence.extend(growth_strategy.risks)
        evidence.extend(growth_strategy.avoidance_notes)

    confidence_inputs = [opportunity.confidence, objective_recommendation.confidence, format_decision.confidence]
    if growth_strategy is not None:
        confidence_inputs.append(growth_strategy.confidence)
    confidence = round(sum(confidence_inputs) / len(confidence_inputs), 3)

    alternative_format = format_decision.alternatives[0].value if format_decision.alternatives else None

    return ShadowPlanResult(
        campaign_name=campaign_name, campaign_phase=opportunity.campaign_phase,
        opportunity_description=f"{opportunity.source_type.value.upper()} opportunity (id={opportunity.id})",
        primary_objective=objective_recommendation.primary_objective.value, audience_description=audience_description,
        recommended_format=format_decision.recommended_format.value, hook_family=hook.family.value if hook else None,
        creative_concept_summary=_creative_concept_summary(creative_outcome), alternative_format=alternative_format,
        alternative_objective=(objective_recommendation.secondary_objectives[0].value if objective_recommendation.secondary_objectives else None),
        product_mention_allowed=opportunity.product_mention_allowed, restricted_claims=list(opportunity.restricted_claims),
        evidence=evidence, confidence=confidence,
    )


def render_shadow_plan_text(plan: ShadowPlanResult) -> str:
    """Item 16's own required renderable shape - plain text, no markup, ready for a future NINJA
    General display step (not wired in this phase)."""
    lines = ["INSTAGRAM PLAN", ""]
    if plan.campaign_name:
        lines += ["Campaign:", plan.campaign_name, ""]
    if plan.campaign_phase:
        lines += ["Phase:", plan.campaign_phase, ""]
    lines += ["Opportunity:", plan.opportunity_description, ""]
    lines += ["Primary objective:", plan.primary_objective.upper(), ""]
    if plan.audience_description:
        lines += ["Audience:", plan.audience_description, ""]
    lines += ["Recommended format:", plan.recommended_format.upper(), ""]
    if plan.hook_family:
        lines += ["Hook:", plan.hook_family.upper(), ""]
    if plan.creative_concept_summary:
        lines += ["Creative concept:", plan.creative_concept_summary, ""]
    if plan.alternative_format or plan.alternative_objective:
        alt = " / ".join(filter(None, [
            plan.alternative_format.upper() if plan.alternative_format else None,
            plan.alternative_objective.upper() if plan.alternative_objective else None,
        ]))
        lines += ["Alternative:", alt, ""]
    lines += ["Product mention:", "ALLOWED" if plan.product_mention_allowed else "NOT ALLOWED", ""]
    if plan.restricted_claims:
        lines += ["Restricted claims:", ", ".join(plan.restricted_claims), ""]
    if plan.evidence:
        lines += ["Evidence:", "; ".join(plan.evidence), ""]
    lines += ["Confidence:", str(plan.confidence)]
    return "\n".join(lines)
