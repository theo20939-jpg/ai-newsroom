"""SOCIAL-INTELLIGENCE-PRELAUNCH-1 §7/§8/§9: the ONE canonical learning-boundary filter.

CRITICAL: this is the single function anything that ever counts a post toward first-party
performance evidence must call - services/telegram_performance_aggregator.py,
services/telegram_channel_memory_writer.py, and any future Growth Director evidence builder. A
post failing this check may still be displayed as history (spec §7: legacy VPN posts answer "what
does the channel look like today", "what pinned content needs replacing") but must NEVER increase
a PULSE performance sample_size, NEVER seed a PerformancePattern, and NEVER be attributed to
NINJA PULSE hook/topic/visual performance - old VPN metrics must not contaminate PULSE
intelligence (spec §7's own explicit list).

The boundary is always `launch_context.learning_start_at` - a single authoritative timestamp,
never re-derived per-caller. `historical_content_policy` governs whether ANYTHING before that
boundary may even be considered as context at all (IGNORE excludes it outright; LEGACY_CONTEXT_ONLY
still permits `published_at < learning_start_at` posts to be treated as legacy context elsewhere,
but never as learning evidence via this function; INCLUDE_IN_LEARNING is reserved for a platform
with no meaningful pre-launch/post-launch distinction at all, e.g. a channel with no rebrand)."""
from __future__ import annotations

from datetime import datetime

from database.models.social_launch_context import HistoricalContentPolicy, SocialLaunchContext


def is_eligible_for_first_party_learning(
    *, published_at: datetime, launch_context: SocialLaunchContext | None,
) -> bool:
    """`platform`/`surface` are implicit in `launch_context` itself (a context row is always
    platform-scoped) - callers pass the SocialLaunchContext they already resolved for the relevant
    platform, never a bare platform string, so this function can never be called against the wrong
    platform's boundary by accident.

    No launch context configured yet = no boundary has ever been established = every post is
    ineligible (fail-safe, never fail-open to "everything counts")."""
    if launch_context is None:
        return False
    if launch_context.historical_content_policy == HistoricalContentPolicy.INCLUDE_IN_LEARNING:
        return True
    if launch_context.learning_start_at is None:
        return False
    return published_at >= launch_context.learning_start_at
