"""NINJA Social Intelligence Foundation, Part III §42/§43: Telegram Channel Director - SHADOW /
ADVISORY ONLY (spec §42, §111). No automatic delay/deprioritization/publication control exists
anywhere that calls this module - it is not wired into worker/content_cycle.py's real publish
path in this phase. Deterministic, rule-based (no LLM) - a genuinely calibrated, learning-based
director is explicitly future work; this phase's own job is to prove the STRUCTURED CONTRACT
(decision/priority/reasons/...) is reachable, testable, and correctly separates organic news
value from campaign relevance (spec §43's own critical requirement).

SOCIAL-INTELLIGENCE-PRELAUNCH-1A §4: `launch_context` (optional, None-default so every existing
call site keeps its exact prior behavior) lets this director reason about a real cold-start/
transition feed instead of pretending a normal live feed exists - `feed_state.is_cold_start`
(services/telegram_feed_state.py) is the truthful signal it checks, never a re-derivation from raw
counts. When cold-start, `launch_fit` (services/social_launch_fit.py - the SAME canonical
classification /opportunities uses) answers "does this belong in the first PULSE feed", and a
`is_transition_content` flag distinguishes real transition communication (e.g. a NINJA VPN
rebrand announcement) from ordinary editorial content that merely happens to arrive during the
transition window."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field

from database.models.social_launch_context import SocialLaunchContext
from services.campaign_planner import CampaignPlan
from services.social_launch_fit import LaunchFitAssessment, assess_launch_fit
from services.telegram_editorial_need import EditorialNeed
from services.telegram_feed_state import FeedState
from services.telegram_feed_window import TelegramFeedWindow


class ChannelDirectorDecision(str, enum.Enum):
    PUBLISH_NOW = "publish_now"
    PUBLISH_SOON = "publish_soon"
    DELAY = "delay"
    DEPRIORITIZE = "deprioritize"
    HUMAN_REVIEW = "human_review"


@dataclass(frozen=True)
class ChannelDirectorResult:
    decision: ChannelDirectorDecision
    priority: int
    channel_fit: float  # 0.0-1.0, advisory only
    feed_role: str
    timing: str
    balance_effect: str
    organic_relevance: float  # spec §43: kept explicitly separate from campaign_relevance
    business_campaign_relevance: float
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    next_feed_need: str | None = None
    confidence: float = 0.5
    # SOCIAL-INTELLIGENCE-PRELAUNCH-1A §4: None on every existing (non-cold-start) call - only
    # populated when feed_state.is_cold_start is True, so a live-channel caller's own result shape
    # is completely unaffected by this field existing.
    launch_fit: LaunchFitAssessment | None = None
    is_transition_content: bool = False


def evaluate_channel_fit_shadow(
    *, news_importance: float, feed_state: FeedState, editorial_need: EditorialNeed,
    campaign_plan: CampaignPlan | None = None, campaign_mention_explicitly_allowed: bool = False,
    launch_context: SocialLaunchContext | None = None, timeliness: float = 0.7,
    is_transition_related_story: bool = False, feed_window: TelegramFeedWindow | None = None,
) -> ChannelDirectorResult:
    """`campaign_mention_explicitly_allowed` must come from the real CampaignPlan (§43's own
    "Channel Director may identify high campaign adjacency but must NOT rewrite it into an
    advertisement unless the Campaign Plan explicitly allows product mention" rule) - this
    function never infers permission from `news_importance` or `feed_state` alone.

    SOCIAL-INTELLIGENCE-PRELAUNCH-1A §4: `launch_context`/`is_transition_related_story` are
    optional and default to the exact prior (non-cold-start) behavior. `feed_state.is_cold_start`
    (not `launch_context` alone) is the actual trigger for cold-start reasoning - a launch_context
    that exists but is already LIVE with real feed history behaves exactly like the pre-PRELAUNCH-1A
    code path. `is_transition_related_story` must come from the caller's own real signal (e.g. the
    Story concerns the NINJA VPN rebrand itself) - never guessed here from news_importance/topic."""
    reasons: list[str] = []
    warnings: list[str] = []

    organic_relevance = min(1.0, max(0.0, news_importance))
    business_campaign_relevance = 0.0
    if campaign_plan is not None and campaign_plan.phase is not None:
        business_campaign_relevance = 0.5
        reasons.append(f"active campaign phase={campaign_plan.phase}")
        if not campaign_mention_explicitly_allowed:
            warnings.append("campaign relevance detected but Campaign Plan does not allow product mention here")

    saturation_notes = [n for n in editorial_need.notes]
    if editorial_need.feed_too_commercial:
        warnings.append("feed is already commercial-heavy - avoid stacking another campaign-linked post")

    if organic_relevance >= 0.8 and not saturation_notes:
        decision = ChannelDirectorDecision.PUBLISH_NOW
        priority = 10
    elif organic_relevance >= 0.5:
        decision = ChannelDirectorDecision.PUBLISH_SOON
        priority = 50
    elif saturation_notes:
        decision = ChannelDirectorDecision.DEPRIORITIZE
        priority = 80
        reasons.extend(saturation_notes)
    else:
        decision = ChannelDirectorDecision.PUBLISH_SOON
        priority = 60

    launch_fit: LaunchFitAssessment | None = None
    feed_role = "advisory_only"
    if feed_state.is_cold_start:
        # spec §4: an empty/cold-start feed re-purposes the SAME decision vocabulary for "belongs
        # in the first feed" rather than "publish this instant" - no publication authority exists
        # either way, so the enum's own advisory-only meaning is unaffected.
        if launch_context is not None:
            reasons.append(
                f"cold-start: {launch_context.current_identity or 'no current identity'} -> "
                f"{launch_context.target_identity} ({launch_context.launch_state.value})"
            )
            if launch_context.planned_launch_at is not None:
                reasons.append(
                    f"planned launch: {launch_context.planned_launch_at.date().isoformat()} "
                    f"({launch_context.launch_date_status.value})"
                )
        launch_fit = assess_launch_fit(
            news_importance=organic_relevance, timeliness=timeliness,
            is_transition_related=is_transition_related_story,
            feed_topic_repetition=feed_state.topic_saturation, campaign_relevance=business_campaign_relevance,
        )
        reasons.extend(f"launch-fit: {r}" for r in launch_fit.reasons)
        feed_role = f"cold_start_feed_candidate:{launch_fit.classification.value}"
        if is_transition_related_story:
            decision = ChannelDirectorDecision.HUMAN_REVIEW
            priority = 20
        elif launch_fit.classification.value == "good_for_launch":
            decision = ChannelDirectorDecision.PUBLISH_NOW
            priority = 15
        elif launch_fit.classification.value == "save_for_after_launch":
            decision = ChannelDirectorDecision.DELAY
            priority = 70
        else:
            decision = ChannelDirectorDecision.DEPRIORITIZE
            priority = 90

    # DIRECTOR-CONTROL-PLANE-1A §13: real recent-feed context, purely additive - never changes
    # `decision`/`priority` above (computed before this block), only enriches `reasons`/`warnings`
    # with what the director can actually see about the real channel. `feed_window=None` (every
    # pre-existing call site) leaves this Director's own output byte-identical to before.
    if feed_window is not None and feed_window.surface_registered:
        legacy_count = len(feed_window.legacy_posts)
        eligible_count = len(feed_window.learning_eligible_posts)
        reasons.append(
            f"real feed window: {len(feed_window.posts)} recent posts "
            f"({legacy_count} legacy/context-only, {eligible_count} performance-learning-eligible)"
        )
        if feed_window.media_type_distribution:
            dominant_type, dominant_count = max(feed_window.media_type_distribution.items(), key=lambda kv: kv[1])
            if dominant_count >= max(3, len(feed_window.posts) // 2):
                warnings.append(f"recent feed dominated by media_type={dominant_type!r} ({dominant_count} posts) - consider visual variety")

    return ChannelDirectorResult(
        decision=decision, priority=priority, channel_fit=organic_relevance, feed_role=feed_role,
        timing="shadow - no automatic timing effect", balance_effect="shadow - no automatic balance effect",
        organic_relevance=organic_relevance, business_campaign_relevance=business_campaign_relevance,
        reasons=reasons, warnings=warnings,
        next_feed_need=editorial_need.saturated_topic or editorial_need.saturated_entity, confidence=0.4,
        launch_fit=launch_fit, is_transition_content=is_transition_related_story,
    )
