"""NINJA Social Intelligence Foundation, Part III §55/§56: Strategy Director + Platform Director.
Contract only in this phase - neither has real generation/publication logic wired anywhere
(telegram_strategy_director_enabled=False, core/config.py). Never publishes directly (spec §55)."""
from __future__ import annotations

from dataclasses import dataclass, field

from services.telegram_performance_memory import TELEGRAM_PLATFORM_CAPABILITIES, PlatformCapability


@dataclass(frozen=True)
class StrategyDirectorAdvisory:
    """Spec §55's own output shape. Left entirely empty-list/None in this phase's own contract-
    only implementation - a future phase supplies the real derivation from Channel Memory/Feed
    State history/Performance Memory/Business Context/Campaign Plans/news-topic mix."""

    priority_themes: list[str] = field(default_factory=list)
    content_balance_notes: list[str] = field(default_factory=list)
    campaign_support_notes: list[str] = field(default_factory=list)
    series_opportunities: list[str] = field(default_factory=list)
    avoidance_fatigue_notes: list[str] = field(default_factory=list)
    experiment_suggestions: list[str] = field(default_factory=list)
    content_gaps: list[str] = field(default_factory=list)


def get_platform_capability(name: str) -> PlatformCapability | None:
    """Spec §56: capability truth must be explicit, never hallucinated. Reuses the SAME registry
    services/telegram_performance_memory.py already established (never a second, competing
    capabilities list) - this function exists only as the Platform Director's own read-only
    accessor."""
    return TELEGRAM_PLATFORM_CAPABILITIES.get(name)
