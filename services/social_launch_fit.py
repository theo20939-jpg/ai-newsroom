"""SOCIAL-INTELLIGENCE-PRELAUNCH-1A §10/§11/§12: the ONE canonical launch-fit classification -
answers "is this Story/opportunity useful for the FIRST feed of a platform still in PRE_LAUNCH/
TRANSITION" for both Telegram (services/telegram_channel_director.py) and Instagram
(services/director_console_service.py's opportunities view). Deterministic, zero LLM calls -
mirrors services/telegram_channel_director.py::evaluate_channel_fit_shadow()'s own rule-based
shape exactly; a magic numeric launch score is deliberately NOT produced (spec §10's own explicit
instruction) - classification always carries its own reasons/dimensions instead."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field


class LaunchFitClassification(str, enum.Enum):
    GOOD_FOR_LAUNCH = "good_for_launch"
    SAVE_FOR_AFTER_LAUNCH = "save_for_after_launch"
    NOT_FIT_FOR_INITIAL_FEED = "not_fit_for_initial_feed"
    # spec §10's own optional addition: content that concerns the TRANSITION ITSELF (e.g. a
    # VPN-related announcement) rather than either the launch feed or a normal post-launch story -
    # a real third category, not a variant of the other two.
    TRANSITION_ONLY = "transition_only"


@dataclass(frozen=True)
class LaunchFitAssessment:
    classification: LaunchFitClassification
    reasons: list[str] = field(default_factory=list)
    # Named 0.0-1.0 signals this assessment actually weighed - spec §10's own "retain dimensions"
    # requirement, kept as a plain dict rather than a fixed dataclass so callers can see exactly
    # which inputs were real vs. absent (a key simply missing means that dimension had no signal).
    dimensions: dict[str, float] = field(default_factory=dict)


def assess_launch_fit(
    *, news_importance: float, timeliness: float, is_transition_related: bool,
    feed_topic_repetition: float = 0.0, campaign_relevance: float = 0.0,
    target_identity_match: bool = True,
) -> LaunchFitAssessment:
    """`is_transition_related` (spec §7/§13's own "should a VPN-related post be treated as
    transition content rather than normal PULSE editorial content" question) is decided by the
    CALLER from real signal (e.g. the Story mentions the old brand, or a founder-authored
    transition-communication draft) - this function never guesses it from text itself.

    `target_identity_match=False` (a Story that contradicts or actively conflicts with the target
    brand identity - e.g. promoting a since-abandoned product line) is the only hard
    NOT_FIT_FOR_INITIAL_FEED override; every other combination is a graded, reasoned judgment."""
    reasons: list[str] = []
    dimensions = {
        "news_importance": news_importance, "timeliness": timeliness,
        "feed_topic_repetition": feed_topic_repetition, "campaign_relevance": campaign_relevance,
    }

    if is_transition_related:
        reasons.append("concerns the brand transition itself, not ordinary PULSE editorial content")
        return LaunchFitAssessment(classification=LaunchFitClassification.TRANSITION_ONLY, reasons=reasons, dimensions=dimensions)

    if not target_identity_match:
        reasons.append("does not match the target brand identity")
        return LaunchFitAssessment(classification=LaunchFitClassification.NOT_FIT_FOR_INITIAL_FEED, reasons=reasons, dimensions=dimensions)

    if feed_topic_repetition >= 0.7:
        reasons.append(f"topic already over-represented in the launch sequence (repetition={feed_topic_repetition:.2f})")
        return LaunchFitAssessment(classification=LaunchFitClassification.SAVE_FOR_AFTER_LAUNCH, reasons=reasons, dimensions=dimensions)

    if news_importance >= 0.7 and timeliness >= 0.6:
        reasons.append("high importance and timely - strengthens the first-feed impression")
        if campaign_relevance > 0:
            reasons.append(f"campaign relevance={campaign_relevance:.2f}")
        return LaunchFitAssessment(classification=LaunchFitClassification.GOOD_FOR_LAUNCH, reasons=reasons, dimensions=dimensions)

    if news_importance >= 0.4:
        reasons.append("moderate importance - solid for launch breadth but not a headline candidate")
        return LaunchFitAssessment(classification=LaunchFitClassification.GOOD_FOR_LAUNCH, reasons=reasons, dimensions=dimensions)

    if timeliness < 0.3:
        reasons.append(f"low timeliness (timeliness={timeliness:.2f}) - better suited once the feed has more history to absorb it")
        return LaunchFitAssessment(classification=LaunchFitClassification.SAVE_FOR_AFTER_LAUNCH, reasons=reasons, dimensions=dimensions)

    reasons.append("low importance and low timeliness - would not strengthen an empty-looking launch feed")
    return LaunchFitAssessment(classification=LaunchFitClassification.NOT_FIT_FOR_INITIAL_FEED, reasons=reasons, dimensions=dimensions)
