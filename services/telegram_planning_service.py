"""SOCIAL-INTELLIGENCE-OPS-1, spec §24-§26: TelegramPlanningService - the ONLY place a Telegram
calendar entry is ever proposed from real evidence (spec §24's own "do NOT automatically create
calendar entries from every story" instruction). `propose_calendar_entries()` is a pure function -
it NEVER writes to the database itself; persisting a proposal is a deliberate, separate call to
services/telegram_calendar_service.py::create_calendar_item() (SHADOW/ADVISORY only this phase,
spec §24's own explicit scope limit - nothing in this codebase calls create_calendar_item()
automatically from this service's output).

CRITICAL (spec §25): understands campaign phases (PROBLEM_FRAMING..POST_LAUNCH) only to decide
content role / exact-date dependence - never a hardcoded "N posts per phase" cadence. The
CampaignPlan itself remains the sole authority on timing/cadence.

CRITICAL (spec §26): feed quality is never overridden by campaign priority - a topically relevant
Story is still proposed, but with an explicit saturation warning and a pushed-back suggested time
when the feed is already saturated with the same topic/entity, never silently suppressed either
(a human/future scheduler makes the final call, this service only ever advises)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from database.models.telegram_content_calendar_item import TelegramContentRole
from services.campaign_planner import CampaignPhase, CampaignPlan
from services.story_campaign_matcher import StoryCampaignMatch, StoryCampaignMatchType
from services.telegram_feed_state import FeedState

_EXACT_DATE_DEPENDENT_PHASES = frozenset({
    CampaignPhase.PRODUCT_TEASING, CampaignPhase.FEATURE_REVEAL, CampaignPhase.COUNTDOWN, CampaignPhase.LAUNCH,
})
_MIN_MATCH_TYPE_FOR_PROPOSAL = {StoryCampaignMatchType.WEAK, StoryCampaignMatchType.RELEVANT, StoryCampaignMatchType.STRONG}
_SATURATION_STREAK_THRESHOLD = 3
_SATURATION_DELAY = timedelta(hours=6)


@dataclass(frozen=True)
class ProposedTelegramCalendarEntry:
    story_id: str | None
    campaign_id: str | None
    product_id: str | None
    content_role: TelegramContentRole
    objective: str
    planned_at: datetime
    depends_on_campaign_phase: str | None
    reasoning: list[str] = field(default_factory=list)
    feed_saturation_warning: str | None = None
    confidence: float = 0.2


def _content_role_for_match(match: StoryCampaignMatch, campaign_plan: CampaignPlan) -> TelegramContentRole:
    if match.product_mention_allowed and campaign_plan.phase in _EXACT_DATE_DEPENDENT_PHASES:
        return TelegramContentRole.CAMPAIGN
    return TelegramContentRole.NEWS


def _objective_for_match(match: StoryCampaignMatch) -> str:
    if match.product_mention_allowed:
        return "product_click"
    return "reach"


def _feed_saturation_warning(feed_state: FeedState) -> str | None:
    """Spec §26's own example: "campaign needs AI warming but last 5 channel posts are already
    AI" - `topic_streak` is exactly this signal (services/telegram_feed_state.py's own "longest
    current run of consecutive posts sharing the same topic")."""
    if feed_state.topic_streak >= _SATURATION_STREAK_THRESHOLD:
        return f"тема уже встречалась {feed_state.topic_streak} раз подряд в ленте - рекомендуется отложить"
    return None


def propose_calendar_entries(
    *, campaign_plan: CampaignPlan, feed_state: FeedState, story_campaign_matches: list[StoryCampaignMatch],
    now: datetime,
) -> list[ProposedTelegramCalendarEntry]:
    proposals: list[ProposedTelegramCalendarEntry] = []
    saturation_warning = _feed_saturation_warning(feed_state)

    for match in story_campaign_matches:
        if match.match_type not in _MIN_MATCH_TYPE_FOR_PROPOSAL:
            continue

        reasoning = [
            f"match_type={match.match_type.value}", f"topic_relevance={match.topic_relevance:.2f}",
            f"entity_relevance={match.entity_relevance:.2f}", f"campaign_value={match.campaign_value:.2f}",
            f"campaign.phase={campaign_plan.phase!r}",
        ]
        planned_at = now + _SATURATION_DELAY if saturation_warning else now
        depends_on_campaign_phase = (
            campaign_plan.phase
            if campaign_plan.phase in _EXACT_DATE_DEPENDENT_PHASES and match.product_mention_allowed
            else None
        )

        proposals.append(ProposedTelegramCalendarEntry(
            story_id=match.story_id, campaign_id=match.campaign_id, product_id=match.product_id,
            content_role=_content_role_for_match(match, campaign_plan), objective=_objective_for_match(match),
            planned_at=planned_at, depends_on_campaign_phase=depends_on_campaign_phase, reasoning=reasoning,
            feed_saturation_warning=saturation_warning, confidence=match.confidence,
        ))

    return proposals
