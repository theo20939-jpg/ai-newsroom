"""NINJA Social Intelligence Foundation, Telegram Directors Phase 2 §9-11: real Channel Director
shadow orchestration - assembles the REAL production-shaped input contract (FeedState, Channel
Memory-derived EditorialNeed, BusinessContextSnapshot, active CampaignPlan) and calls the existing
services/telegram_channel_director.py::evaluate_channel_fit_shadow() unchanged.

CRITICAL (spec §9/§111): this module has NO write path to ranking/routing/publication/task status/
Presentation Director decision - `run_channel_director_shadow()` only returns a `ChannelDirectorResult`
and logs it. worker/content_cycle.py's own call site wraps this in try/except so a bug here can
never affect the real publish path (mirrors services/event_recap_scheduler.py's own established
wiring-into-worker/cycle.py precedent)."""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.social_launch_context import SocialLaunchPlatform
from services.business_context_snapshot_service import get_business_context_snapshot
from services.campaign_planner import CampaignPhase, CampaignPlan
from services.social_launch_context_service import get_current_context
from services.telegram_channel_director import ChannelDirectorResult, evaluate_channel_fit_shadow
from services.telegram_editorial_need import derive_editorial_need
from services.telegram_feed_state import compute_feed_state

logger = logging.getLogger(__name__)

# Phases where the campaign has already revealed the product/feature - explicit product mention is
# a defensible editorial choice; earlier phases (AWARENESS/PROBLEM_FRAMING/CATEGORY_EDUCATION) are
# deliberately pre-reveal, so mention is never allowed there regardless of feed state (spec §43's
# own "must NOT rewrite it into an advertisement unless the Campaign Plan explicitly allows product
# mention" - this is that explicit allowance, derived from the plan's own phase, never guessed).
_PRODUCT_MENTION_ALLOWED_PHASES = frozenset({
    CampaignPhase.PRODUCT_TEASING, CampaignPhase.FEATURE_REVEAL, CampaignPhase.COUNTDOWN,
    CampaignPhase.LAUNCH, CampaignPhase.POST_LAUNCH,
})


def _select_campaign_plan(active_campaigns: list[CampaignPlan]) -> CampaignPlan | None:
    """No Story<->Campaign linkage field exists anywhere in this codebase yet (forensic finding) -
    so the most advanced-phase active campaign is surfaced for advisory visibility only. This is
    NEVER treated as proof the current Story relates to that campaign; `evaluate_channel_fit_shadow`
    only uses it to decide whether business_campaign_relevance/explicit-mention warnings apply at
    all, and that decision is itself advisory-only (spec §111)."""
    if not active_campaigns:
        return None
    return active_campaigns[0]


async def run_channel_director_shadow(
    session: AsyncSession, *, news_importance: float, now: datetime,
    timeliness: float = 0.7, is_transition_related_story: bool = False,
) -> ChannelDirectorResult | None:
    """Returns None (no-op) when `telegram_channel_director_shadow_enabled` is False - the default.
    Never raises past this point in a way that could reach the real publish path; the caller in
    worker/content_cycle.py additionally wraps this call in its own try/except as defense in depth.

    SOCIAL-INTELLIGENCE-PRELAUNCH-1A §4/§25: fetches the current Telegram SocialLaunchContext
    (None if never configured) and passes it straight through to evaluate_channel_fit_shadow() -
    cold-start reasoning is driven entirely by feed_state.is_cold_start there, so a live channel's
    own behavior is unaffected by this fetch existing. `is_transition_related_story` stays the
    caller's own responsibility to supply from real signal (this function never infers it) -
    worker/content_cycle.py's own real call site does not yet pass a non-default value, which is a
    documented, deliberate scope boundary for this phase (see this phase's own final report)."""
    if not settings.telegram_channel_director_shadow_enabled:
        return None

    launch_context = await get_current_context(session, SocialLaunchPlatform.TELEGRAM)
    feed_state = await compute_feed_state(session, now=now, launch_context=launch_context)
    editorial_need = derive_editorial_need(feed_state)
    business_context = await get_business_context_snapshot(session, now=now)
    campaign_plan = _select_campaign_plan(business_context.active_campaigns)
    mention_allowed = campaign_plan is not None and campaign_plan.phase in _PRODUCT_MENTION_ALLOWED_PHASES

    result = evaluate_channel_fit_shadow(
        news_importance=news_importance, feed_state=feed_state, editorial_need=editorial_need,
        campaign_plan=campaign_plan, campaign_mention_explicitly_allowed=mention_allowed,
        launch_context=launch_context, timeliness=timeliness, is_transition_related_story=is_transition_related_story,
    )
    logger.info(
        "telegram_channel_director_shadow decision=%s priority=%d organic=%.2f campaign=%.2f "
        "reasons=%s warnings=%s (shadow only - no runtime effect)",
        result.decision.value, result.priority, result.organic_relevance,
        result.business_campaign_relevance, result.reasons, result.warnings,
    )
    return result
