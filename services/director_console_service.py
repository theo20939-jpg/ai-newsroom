"""SOCIAL-INTELLIGENCE-INTEGRATION-1, spec §7-13/§17/§25-27: DirectorConsoleService - assembles
`/plan`, `/opportunities`, `/calendar`, `/performance` from already-implemented, real services.
Business logic lives HERE, never inside a Telegram handler (spec §13).

CRITICAL cost safety (spec §18): nothing in this module calls the AI Gateway. Instagram Growth
Strategy/Format Director/objective selection are all deterministic, free functions; Creative
Director generation is never invoked here.

CRITICAL (spec §9): a Telegram post is never fabricated in the calendar view - Telegram has no
persisted content-calendar model in this codebase, and that is stated explicitly rather than
silently omitted.

Every view carries `as_of`/`generated_at` (spec §25) so a caller can render data freshness."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_calendar_item import CalendarItemStatus, InstagramContentCalendarItem
from database.models.strategic_directive import StrategicDirective
from database.models.story import Story
from database.models.telegram_content_calendar_item import (
    TelegramCalendarItemStatus,
    TelegramContentCalendarItem,
)
from services.business_context_snapshot_service import BusinessContextSnapshot, get_business_context_snapshot
from services.campaign_planner import CampaignPhase, CampaignPlan, build_campaign_plan
from services.campaign_service import get_campaign
from services.instagram_calendar_service import list_calendar_items
from services.instagram_content_opportunity import (
    ContentOpportunity,
    OpportunitySourceType,
    build_content_opportunity,
)
from services.instagram_format_director import ContentFormat
from services.instagram_format_director_v2 import AssetConstraints, evaluate_format_v2
from services.instagram_growth_strategist import (
    InstagramGrowthStrategy,
    OpportunityContext,
    generate_growth_strategy,
)
from services.instagram_objective_selection import ObjectiveRecommendation, recommend_objective
from services.instagram_objectives import ContentObjective
from services.story_campaign_matcher import StoryCampaignMatchType, StoryInput, match_story_to_campaign
from services.telegram_calendar_service import list_calendar_items as list_telegram_calendar_items
from services.telegram_feed_state import compute_feed_state
from services.telegram_own_channel import owned_chat_id
from services.telegram_strategy_director import StrategyDirectorAdvisory, derive_strategy_advisory
from services.telegram_surface_registry import owned_surface_is_public_and_analytics_enabled

_PRODUCT_MENTION_ALLOWED_PHASES = frozenset({
    CampaignPhase.PRODUCT_TEASING, CampaignPhase.FEATURE_REVEAL, CampaignPhase.COUNTDOWN,
    CampaignPhase.LAUNCH, CampaignPhase.POST_LAUNCH,
})
_MAX_RECENT_STORIES = 10
_STORY_FRESHNESS_HALF_LIFE_HOURS = 12.0


# ---------------------------------------------------------------------------
# /plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanView:
    as_of: datetime
    business_context_version: str
    active_campaigns: list[CampaignPlan] = field(default_factory=list)
    active_directives: list[StrategicDirective] = field(default_factory=list)
    telegram_advisory: StrategyDirectorAdvisory | None = None
    telegram_note: str = ""
    instagram_strategy: InstagramGrowthStrategy | None = None
    instagram_note: str = ""


def _business_context_version(snapshot: BusinessContextSnapshot) -> str:
    """A cheap, deterministic fingerprint of the snapshot actually used - spec §26's own
    "future content must know which Business Context version it was planned against" applied to
    a live view instead of a stored calendar item: two views built from the identical underlying
    state always produce the identical fingerprint, any real change to campaigns/directives/claims
    changes it."""
    campaign_fingerprint = ",".join(sorted(f"{c.campaign_id}:{c.status}:{c.phase}" for c in snapshot.active_campaigns))
    directive_fingerprint = ",".join(sorted(str(d.id) for d in snapshot.active_directives))
    return f"campaigns[{campaign_fingerprint}]|directives[{directive_fingerprint}]"


def _restricted_claim_texts_for_product(snapshot: BusinessContextSnapshot, product_id: str) -> list[str]:
    """ClaimPolicy (spec-authoritative, per database/models/claim_policy.py's own docstring) is
    the real source of restricted claims - `LaunchCampaign.restricted_claims` is only a
    convenience cache that a caller may never have populated. Console views always read the
    resolved snapshot, never the cache column, so a real restriction is never silently missed."""
    return [c.claim_text for c in snapshot.restricted_claims if str(c.product_id) == product_id]


def _product_opportunities_from_campaigns(snapshot: BusinessContextSnapshot) -> list[OpportunityContext]:
    contexts: list[OpportunityContext] = []
    product_by_id = {str(s.product.id): s.product for s in snapshot.products}
    for plan in snapshot.active_campaigns:
        product = product_by_id.get(plan.product_id)
        opportunity = build_content_opportunity(
            id=f"campaign:{plan.campaign_id}", source_type=OpportunitySourceType.PRODUCT,
            product_id=plan.product_id, campaign_id=plan.campaign_id, campaign_plan=plan,
            recommended_objectives=[], evidence=[f"active campaign phase={plan.phase}"], confidence=0.4,
        )
        real_restricted = _restricted_claim_texts_for_product(snapshot, plan.product_id)
        if real_restricted:
            opportunity = replace(opportunity, restricted_claims=sorted(set(opportunity.restricted_claims) | set(real_restricted)))
        contexts.append(OpportunityContext(opportunity=opportunity, product_slug=product.slug if product else None))
    return contexts


async def build_plan_view(
    session: AsyncSession, *, now: datetime | None = None, platform: str | None = None,
) -> PlanView:
    now = now or datetime.now(timezone.utc)
    snapshot = await get_business_context_snapshot(session, now=now)
    version = _business_context_version(snapshot)

    telegram_advisory: StrategyDirectorAdvisory | None = None
    telegram_note = ""
    if platform in (None, "telegram"):
        feed_state = await compute_feed_state(session, now=now)
        if feed_state.posts_24h == 0 and not feed_state.topic_distribution:
            telegram_note = "недостаточно данных: нет истории постов канала"
        telegram_advisory = derive_strategy_advisory(feed_state, patterns=[])

    instagram_strategy: InstagramGrowthStrategy | None = None
    instagram_note = ""
    if platform in (None, "instagram"):
        contexts = _product_opportunities_from_campaigns(snapshot)
        if not contexts:
            instagram_note = "недостаточно данных: нет активных кампаний для стратегии"
        instagram_strategy = generate_growth_strategy(
            opportunity_contexts=contexts, directives=list(snapshot.active_directives),
        )

    return PlanView(
        as_of=now, business_context_version=version, active_campaigns=list(snapshot.active_campaigns),
        active_directives=list(snapshot.active_directives), telegram_advisory=telegram_advisory,
        telegram_note=telegram_note, instagram_strategy=instagram_strategy, instagram_note=instagram_note,
    )


# ---------------------------------------------------------------------------
# /opportunities
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OpportunityRow:
    source_type: str
    topic: str
    news_value: float | None
    campaign_relevance: float | None
    trend_relevance: float | None
    product_mention_allowed: bool
    restricted_claims: list[str]
    instagram_objective: ContentObjective | None
    instagram_format: ContentFormat | None
    telegram_note: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    embargo_constraints: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OpportunitiesView:
    as_of: datetime
    rows: list[OpportunityRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _story_freshness(story_updated_at: datetime, *, now: datetime) -> float:
    """A disclosed, deterministic recency heuristic (exponential decay, half-life
    `_STORY_FRESHNESS_HALF_LIFE_HOURS`) - used ONLY as one input dimension (news_value), never
    blended into a cross-platform magic score (spec §8's own explicit prohibition)."""
    age_hours = max((now - story_updated_at).total_seconds() / 3600.0, 0.0)
    return round(0.5 ** (age_hours / _STORY_FRESHNESS_HALF_LIFE_HOURS), 3)


def _telegram_mention_note(plan: CampaignPlan | None) -> str:
    if plan is None:
        return "нет привязанной кампании"
    if plan.phase in _PRODUCT_MENTION_ALLOWED_PHASES:
        return f"явное упоминание продукта допустимо на фазе {plan.phase}"
    return f"явное упоминание продукта НЕ допускается на фазе {plan.phase or 'неизвестна'}"


def _row_from_opportunity(opportunity: ContentOpportunity, *, topic: str, telegram_note: str) -> OpportunityRow:
    recommendation: ObjectiveRecommendation = recommend_objective(opportunity=opportunity)
    format_decision = evaluate_format_v2(objective=recommendation.primary_objective, assets=AssetConstraints(), opportunity=opportunity)
    return OpportunityRow(
        source_type=opportunity.source_type.value, topic=topic,
        news_value=opportunity.news_value or None, campaign_relevance=opportunity.campaign_relevance or None,
        trend_relevance=opportunity.trend_relevance or None, product_mention_allowed=opportunity.product_mention_allowed,
        restricted_claims=list(opportunity.restricted_claims), instagram_objective=recommendation.primary_objective,
        instagram_format=format_decision.recommended_format, telegram_note=telegram_note,
        confidence=opportunity.confidence, evidence=list(opportunity.evidence),
        embargo_constraints=list(opportunity.embargo_constraints),
    )


def _product_slug_for(snapshot: BusinessContextSnapshot, product_id: str) -> str | None:
    return next((s.product.slug for s in snapshot.products if str(s.product.id) == product_id), None)


async def build_opportunities_view(
    session: AsyncSession, *, now: datetime | None = None, platform: str | None = None,
) -> OpportunitiesView:
    now = now or datetime.now(timezone.utc)
    snapshot = await get_business_context_snapshot(session, now=now)
    rows: list[OpportunityRow] = []
    notes: list[str] = []

    stories = list((await session.execute(
        select(Story).order_by(Story.updated_at.desc()).limit(_MAX_RECENT_STORIES)
    )).scalars().all())

    # spec §19/§20: real HYBRID opportunities - one shared StoryCampaignMatcher call per
    # (Story, active campaign) pair, deterministic only (no Gateway call from a read command,
    # spec §68). matched_story_ids tracks which Stories already produced a HYBRID row so they are
    # never ALSO shown a second time as a plain NEWS row.
    matched_story_ids: set[str] = set()
    for plan in snapshot.active_campaigns:
        product_slug = _product_slug_for(snapshot, plan.product_id)
        best_match = None
        best_story = None
        for story in stories:
            story_input = StoryInput(story_id=str(story.id), title=story.title, entities=story.entities or [], keywords=story.keywords or [])
            match = match_story_to_campaign(
                story_input, plan, snapshot=snapshot, directives=list(snapshot.active_directives),
                product_slug=product_slug,
            )
            if match.match_type == StoryCampaignMatchType.NONE:
                continue
            if best_match is None or match.campaign_value > best_match.campaign_value:
                best_match, best_story = match, story

        if best_match is not None and best_story is not None:
            matched_story_ids.add(str(best_story.id))
            opportunity = build_content_opportunity(
                id=f"hybrid:{best_story.id}:{plan.campaign_id}", source_type=OpportunitySourceType.HYBRID,
                story_id=str(best_story.id), campaign_id=plan.campaign_id, product_id=plan.product_id,
                news_value=_story_freshness(best_story.updated_at, now=now), campaign_plan=plan,
                evidence=best_match.evidence, confidence=best_match.confidence,
            )
            opportunity = replace(
                opportunity, campaign_relevance=best_match.campaign_value,
                restricted_claims=best_match.restricted_claims, embargo_constraints=best_match.embargo_constraints,
                product_mention_allowed=best_match.product_mention_allowed,
            )
            rows.append(_row_from_opportunity(
                opportunity, topic=best_story.title,
                telegram_note=f"органический прогрев темы (совпадение: {best_match.match_type.value})",
            ))
        else:
            opportunity = build_content_opportunity(
                id=f"campaign:{plan.campaign_id}", source_type=OpportunitySourceType.PRODUCT,
                product_id=plan.product_id, campaign_id=plan.campaign_id, campaign_plan=plan,
                evidence=[f"active campaign phase={plan.phase}"], confidence=0.4,
            )
            real_restricted = _restricted_claim_texts_for_product(snapshot, plan.product_id)
            if real_restricted:
                opportunity = replace(opportunity, restricted_claims=sorted(set(opportunity.restricted_claims) | set(real_restricted)))
            rows.append(_row_from_opportunity(opportunity, topic=f"campaign:{plan.campaign_id}", telegram_note=_telegram_mention_note(plan)))

    for story in stories:
        if str(story.id) in matched_story_ids:
            continue
        news_value = _story_freshness(story.updated_at, now=now)
        opportunity = build_content_opportunity(
            id=f"story:{story.id}", source_type=OpportunitySourceType.NEWS, story_id=str(story.id),
            news_value=news_value, evidence=[f"story updated_at={story.updated_at.isoformat()}"], confidence=0.3,
        )
        rows.append(_row_from_opportunity(opportunity, topic=story.title, telegram_note="нет прямой оценки Channel Director вне рабочего цикла"))

    if not snapshot.active_campaigns:
        notes.append("нет активных кампаний - PRODUCT/HYBRID-возможности недоступны")
    if not stories:
        notes.append("нет свежих Story - NEWS/HYBRID-возможности недоступны")
    notes.append("TREND-возможности недоступны: живой сбор трендов не реализован")

    if platform is not None:
        # Platform filter only trims which recommendation columns are meaningful to show; the
        # underlying opportunity rows themselves are always cross-platform (spec §8).
        notes.append(f"фильтр платформы: {platform}")

    return OpportunitiesView(as_of=now, rows=rows, notes=notes)


# ---------------------------------------------------------------------------
# /calendar
# ---------------------------------------------------------------------------


_LIVE_TERMINAL_ITEM_STATUSES = frozenset({
    CalendarItemStatus.INVALIDATED, CalendarItemStatus.CANCELLED, CalendarItemStatus.DONE,
    CalendarItemStatus.RESCHEDULED,
})
_LIVE_TERMINAL_TELEGRAM_ITEM_STATUSES = frozenset({
    TelegramCalendarItemStatus.INVALIDATED, TelegramCalendarItemStatus.CANCELLED,
    TelegramCalendarItemStatus.DONE, TelegramCalendarItemStatus.RESCHEDULED,
})


@dataclass(frozen=True)
class CalendarRow:
    platform: str
    planned_at: datetime
    concept: str
    objective: str
    campaign_id: str | None
    status: str
    context_stale: bool = False


@dataclass(frozen=True)
class CalendarView:
    as_of: datetime
    rows: list[CalendarRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


async def _is_context_stale(session: AsyncSession, item: InstagramContentCalendarItem, *, now: datetime) -> bool:
    """Spec §26: a calendar item is STALE_CONTEXT when the Business Context has already moved on
    (status/phase changed, including the campaign having been cancelled entirely) since this item
    was planned, but the invalidation pipeline (services/instagram_calendar_service.py) has not
    yet caught up to mark it INVALIDATED/STALE itself - a display-time freshness check,
    independent of the item's own stored `status`. Reads the RAW campaign row (never the
    already-active-only-filtered snapshot list) so a campaign that dropped out of "active"
    entirely (e.g. cancelled) is still compared, not silently skipped."""
    if item.status in _LIVE_TERMINAL_ITEM_STATUSES:
        return False
    if item.campaign_id is None:
        return False
    campaign = await get_campaign(session, item.campaign_id)
    if campaign is None:
        return False
    live_plan = build_campaign_plan(campaign, now=now)
    if item.planned_against_campaign_status is not None and item.planned_against_campaign_status != live_plan.status:
        return True
    if item.planned_against_campaign_phase is not None and item.planned_against_campaign_phase != live_plan.phase:
        return True
    return False


async def _is_telegram_context_stale(
    session: AsyncSession, item: TelegramContentCalendarItem, *, now: datetime,
) -> bool:
    """Mirrors `_is_context_stale` exactly (spec §26/§28), against the separate Telegram calendar
    model - a display-time freshness check independent of `item.status` itself."""
    if item.status in _LIVE_TERMINAL_TELEGRAM_ITEM_STATUSES:
        return False
    if item.campaign_id is None:
        return False
    campaign = await get_campaign(session, item.campaign_id)
    if campaign is None:
        return False
    live_plan = build_campaign_plan(campaign, now=now)
    if item.planned_against_campaign_status is not None and item.planned_against_campaign_status != live_plan.status:
        return True
    if item.planned_against_campaign_phase is not None and item.planned_against_campaign_phase != live_plan.phase:
        return True
    return False


async def build_calendar_view(
    session: AsyncSession, *, now: datetime | None = None, platform: str | None = None,
) -> CalendarView:
    now = now or datetime.now(timezone.utc)
    rows: list[CalendarRow] = []
    notes: list[str] = []

    if platform in (None, "instagram"):
        ig_items: list[InstagramContentCalendarItem] = await list_calendar_items(session)
        for item in sorted(ig_items, key=lambda i: i.planned_at):
            rows.append(CalendarRow(
                platform="instagram", planned_at=item.planned_at,
                concept=item.opportunity_id or item.creative_concept_id or f"format={item.format}",
                objective=item.objective, campaign_id=str(item.campaign_id) if item.campaign_id else None,
                status=item.status.value, context_stale=await _is_context_stale(session, item, now=now),
            ))
        if not ig_items:
            notes.append("Instagram: нет запланированного контента")

    if platform in (None, "telegram"):
        tg_items: list[TelegramContentCalendarItem] = await list_telegram_calendar_items(session)
        for t_item in sorted(tg_items, key=lambda i: i.planned_at):
            rows.append(CalendarRow(
                platform="telegram", planned_at=t_item.planned_at,
                concept=t_item.presentation_hint or t_item.source_opportunity_id or f"role={t_item.content_role.value}",
                objective=t_item.objective, campaign_id=str(t_item.campaign_id) if t_item.campaign_id else None,
                status=t_item.status.value,
                context_stale=await _is_telegram_context_stale(session, t_item, now=now),
            ))
        if not tg_items:
            notes.append("Telegram: нет запланированного контента")

    return CalendarView(as_of=now, rows=rows, notes=notes)


# ---------------------------------------------------------------------------
# /performance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PerformanceEvidenceRow:
    description: str
    sample_size: int
    effect_size: float
    stage: str


@dataclass(frozen=True)
class PerformanceView:
    as_of: datetime
    telegram_status: str
    telegram_evidence: list[PerformanceEvidenceRow] = field(default_factory=list)
    instagram_status: str = "NO_FIRST_PARTY_DATA"


async def build_performance_view(
    session: AsyncSession, *, now: datetime | None = None, platform: str | None = None,
) -> PerformanceView:
    now = now or datetime.now(timezone.utc)
    telegram_status = "NOT_APPLICABLE"
    telegram_evidence: list[PerformanceEvidenceRow] = []

    if platform in (None, "telegram"):
        if owned_chat_id() is None:
            telegram_status = "PUBLIC_CHANNEL_NOT_CONFIGURED"
        elif not await owned_surface_is_public_and_analytics_enabled(session):
            telegram_status = "PUBLIC_CHANNEL_NOT_CONFIGURED"
        else:
            telegram_status = "NO_EVIDENCE_YET"

    instagram_status = "NO_FIRST_PARTY_DATA" if platform in (None, "instagram") else "NOT_APPLICABLE"

    return PerformanceView(
        as_of=now, telegram_status=telegram_status, telegram_evidence=telegram_evidence,
        instagram_status=instagram_status,
    )
