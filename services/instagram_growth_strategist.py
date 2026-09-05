"""NINJA Social Intelligence Foundation, Part IV §95/§87/§93: Growth Strategist Business Context
consumption + Dynamic Calendar item state + Growth Autopsy. Contract-level only (spec §110's own
P2 classification for the deeper trend/competitor/audience work - this module proves the shared-
truth-independent-execution boundary, not a real generation pipeline).

CRITICAL (spec §95/§98): consumes `BusinessContextSnapshot`/`CampaignPlan` from the SHARED
foundation (services/business_context_snapshot_service.py, services/campaign_planner.py) - never
imports anything from services/telegram_*.py. Shared truth, independent execution."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field

from services.campaign_planner import CampaignPlan
from services.instagram_format_director import ContentFormat


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


class CalendarItemStatus(str, enum.Enum):
    """Spec §87: future posts may become stale/invalidated when business context changes (e.g. a
    launch delay invalidates countdown posts but preserves generic awareness content)."""

    ACTIVE = "active"
    STALE = "stale"
    INVALIDATED = "invalidated"
    RESCHEDULED = "rescheduled"


@dataclass(frozen=True)
class GrowthAutopsy:
    """Spec §93: evidence-based retrospective only - never storytelling without evidence."""

    subject: str
    what_happened: str
    what_was_expected: str
    what_differed: str
    supporting_evidence: list[str] = field(default_factory=list)
    next_test: str | None = None
