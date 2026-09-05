"""SOCIAL-INTELLIGENCE-OPS-1, spec §11-§20: StoryCampaignMatcher - the ONE shared, platform-agnostic
Story x Campaign relevance service. Neither Telegram nor Instagram implements its own copy of this
(spec §11's own explicit "do not implement separate Telegram and Instagram campaign matchers for
the same business truth" instruction) - both platforms call `match_story_to_campaign()`/
`match_story_to_campaign_with_semantics()` and derive their own platform-specific execution from
the SAME `StoryCampaignMatch` result.

CRITICAL (spec §16/§17): HIGH relevance never implies product mention is allowed - `campaign_value`
and `product_mention_allowed` are resolved completely independently. A Founder Directive
(services/founder_directive_policy.py::directive_blocks_product() - the SAME shared function
services/instagram_growth_strategist.py already uses) can force `product_mention_allowed=False`
even when every relevance dimension is high.

Semantic matching (spec §14/§15) reuses services/instagram_semantic_matching.py::
evaluate_semantic_relatedness() - that function's own logic is completely generic (compares two
plain-text subjects via the existing Gateway), it is simply not yet relocated out of its
instagram-prefixed module; documented here as a deliberate reuse-not-duplicate decision, with a
proper relocation left as a follow-up (see this phase's own final report)."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from database.models.claim_policy import ClaimPolicy, ClaimStatus
from database.models.strategic_directive import StrategicDirective
from integrations.llm_gateway.protocol import LLMGateway
from integrations.prompts.protocol import PromptRepository
from services.business_context_snapshot_service import BusinessContextSnapshot
from services.campaign_planner import CampaignPlan
from services.founder_directive_policy import directive_blocks_product
from services.instagram_content_opportunity import resolve_product_mention_permission
from services.instagram_semantic_matching import SemanticMatchResult, evaluate_semantic_relatedness

_STATUSES_BLOCKING_PRODUCT_MENTION = frozenset({"draft", "tentative", "cancelled"})


class StoryCampaignMatchType(str, enum.Enum):
    NONE = "none"
    WEAK = "weak"
    RELEVANT = "relevant"
    STRONG = "strong"


@dataclass(frozen=True)
class StoryInput:
    """Lightweight, DB-decoupled view of a Newsroom Story - mirrors services/instagram_trend_
    matching.py::StoryMatchInput's own established convention (never the ORM row itself, so this
    matcher stays unit-testable without a database session)."""

    story_id: str
    title: str
    entities: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StoryCampaignMatch:
    story_id: str
    campaign_id: str
    product_id: str

    topic_relevance: float
    entity_relevance: float
    semantic_relevance: float | None
    campaign_phase_relevance: float
    audience_relevance: float | None

    organic_value_reference: float
    campaign_value: float

    product_mention_allowed: bool
    approved_claims: list[str] = field(default_factory=list)
    restricted_claims: list[str] = field(default_factory=list)
    embargo_constraints: list[str] = field(default_factory=list)

    match_type: StoryCampaignMatchType = StoryCampaignMatchType.NONE
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.2


def _tokenize(*texts: str | None) -> set[str]:
    tokens: set[str] = set()
    for text in texts:
        if not text:
            continue
        tokens.update(word.strip(".,!?:;\"'()").lower() for word in text.split() if len(word) > 2)
    return tokens


def _overlap_ratio(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _claims_for_product(snapshot: BusinessContextSnapshot, product_id: str) -> tuple[list[ClaimPolicy], list[ClaimPolicy]]:
    approved = [c for c in snapshot.approved_claims if str(c.product_id) == product_id]
    restricted = [c for c in snapshot.restricted_claims if str(c.product_id) == product_id]
    return approved, restricted


def _embargo_constraints(restricted: list[ClaimPolicy], *, now: datetime) -> list[str]:
    return [
        f"embargoed until {c.embargoed_until.isoformat()}: {c.claim_text}"
        for c in restricted if c.status == ClaimStatus.EMBARGOED and c.embargoed_until is not None and c.embargoed_until > now
    ]


def _classify_match_type(*, topic_relevance: float, entity_relevance: float, semantic_relevance: float | None) -> StoryCampaignMatchType:
    semantic = semantic_relevance or 0.0
    if (topic_relevance >= 0.3 and entity_relevance >= 0.2) or semantic >= 0.75:
        return StoryCampaignMatchType.STRONG
    if topic_relevance >= 0.15 or entity_relevance >= 0.1 or semantic >= 0.5:
        return StoryCampaignMatchType.RELEVANT
    if topic_relevance > 0 or entity_relevance > 0 or semantic > 0.2:
        return StoryCampaignMatchType.WEAK
    return StoryCampaignMatchType.NONE


def match_story_to_campaign(
    story: StoryInput, campaign_plan: CampaignPlan, *, snapshot: BusinessContextSnapshot,
    directives: list[StrategicDirective] | None = None, product_slug: str | None = None,
    platform: str = "shared", now: datetime | None = None,
) -> StoryCampaignMatch:
    """Deterministic evidence FIRST, always computed regardless of whether semantic matching is
    ever attempted (spec §14's own "always compute deterministic evidence first" instruction)."""
    now = now or datetime.now(timezone.utc)
    story_tokens = _tokenize(story.title, *story.entities, *story.keywords)

    # No dedicated "campaign topic" field exists on CampaignPlan - key_messages is the closest real
    # signal already carried on it (services/campaign_planner.py::CampaignPlan.key_messages).
    campaign_tokens = _tokenize(*campaign_plan.key_messages, *campaign_plan.content_pillars)
    topic_relevance = round(_overlap_ratio(story_tokens, campaign_tokens), 3)
    entity_tokens = {e.lower() for e in story.entities}
    entity_relevance = round(_overlap_ratio(entity_tokens, campaign_tokens), 3)

    campaign_phase_relevance = 1.0 if campaign_plan.phase is not None else 0.0

    approved, restricted = _claims_for_product(snapshot, campaign_plan.product_id)
    embargo_constraints = _embargo_constraints(restricted, now=now)
    embargo_active = bool(embargo_constraints)

    campaign_permits = resolve_product_mention_permission(
        campaign_plan=campaign_plan, restricted_claims=[c.claim_text for c in restricted], embargo_active=embargo_active,
    )
    directive_blocked = bool(
        product_slug is not None and campaign_permits
        and directive_blocks_product(directives or [], product_slug=product_slug, platform=platform)
    )
    product_mention_allowed = campaign_permits and not directive_blocked

    match_type = _classify_match_type(topic_relevance=topic_relevance, entity_relevance=entity_relevance, semantic_relevance=None)
    campaign_value = round((topic_relevance + entity_relevance + campaign_phase_relevance) / 3, 3)

    evidence = [
        f"topic_relevance={topic_relevance:.2f}", f"entity_relevance={entity_relevance:.2f}",
        f"campaign.phase={campaign_plan.phase!r}", f"campaign.status={campaign_plan.status!r}",
    ]
    if directive_blocked:
        evidence.append("product mention blocked by an active Founder Directive")
    if embargo_active:
        evidence.append("product still under embargo")

    return StoryCampaignMatch(
        story_id=story.story_id, campaign_id=campaign_plan.campaign_id, product_id=campaign_plan.product_id,
        topic_relevance=topic_relevance, entity_relevance=entity_relevance, semantic_relevance=None,
        campaign_phase_relevance=campaign_phase_relevance, audience_relevance=None,
        organic_value_reference=round(max(topic_relevance, entity_relevance), 3), campaign_value=campaign_value,
        product_mention_allowed=product_mention_allowed, approved_claims=[c.claim_text for c in approved],
        restricted_claims=[c.claim_text for c in restricted], embargo_constraints=embargo_constraints,
        match_type=match_type, evidence=evidence, confidence=0.3,
    )


async def match_story_to_campaign_with_semantics(
    story: StoryInput, campaign_plan: CampaignPlan, *, snapshot: BusinessContextSnapshot,
    directives: list[StrategicDirective] | None = None, product_slug: str | None = None,
    platform: str = "shared", now: datetime | None = None, gateway: LLMGateway | None = None,
    prompt_repository: PromptRepository | None = None,
) -> StoryCampaignMatch:
    """Spec §14/§15: semantic matching only ever SUPPLEMENTS the deterministic result above - it
    can upgrade `match_type`/`confidence` when it finds real substance a lexical overlap missed,
    but it can never erase the deterministic evidence, and any Gateway failure degrades silently
    back to the deterministic-only result (never a fabricated semantic score, never a raised
    exception from an unavailable LLM)."""
    baseline = match_story_to_campaign(
        story, campaign_plan, snapshot=snapshot, directives=directives, product_slug=product_slug,
        platform=platform, now=now,
    )
    if gateway is None or prompt_repository is None:
        return baseline

    campaign_theme = "; ".join(campaign_plan.key_messages) or campaign_plan.phase or ""
    semantic: SemanticMatchResult = await evaluate_semantic_relatedness(
        gateway, prompt_repository, subject_a=story.title, subject_b=campaign_theme,
        context_a=", ".join([*story.entities, *story.keywords]), context_b=campaign_plan.phase or "",
    )
    if not semantic.available:
        return baseline

    match_type = _classify_match_type(
        topic_relevance=baseline.topic_relevance, entity_relevance=baseline.entity_relevance,
        semantic_relevance=semantic.relatedness,
    )
    evidence = [
        *baseline.evidence,
        f"semantic_relevance={semantic.relatedness:.2f}" if semantic.relatedness is not None else "semantic_relevance=unknown",
    ]
    confidence = baseline.confidence
    if match_type != baseline.match_type:
        confidence = round(min(0.6, confidence + 0.2), 3)

    return replace(
        baseline, semantic_relevance=semantic.relatedness, match_type=match_type, evidence=evidence, confidence=confidence,
    )
