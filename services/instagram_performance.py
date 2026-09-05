"""INSTAGRAM GROWTH ENGINE v2, spec §42/§43: InstagramPerformanceObservation - the future-ready
performance input contract. No Instagram account is connected anywhere in this codebase
(services/instagram_platform_capabilities.py's own forensic-sweep evidence) - every metric here is
nullable, and `__post_init__` REFUSES a non-null metric whose underlying read capability is not
AVAILABLE (today, none are - spec §42's own "unavailable metric: null/unavailable, NOT 0"
instruction enforced structurally, not just by convention)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from services.instagram_platform_capabilities import CapabilityStatus, get_capability

# Which capability gates which metric - a metric may only be non-null once its capability is
# genuinely AVAILABLE (spec §42/§53).
_METRIC_CAPABILITY: dict[str, str] = {
    "reach": "read_post_insights", "impressions": "read_post_insights", "plays": "read_reel_insights",
    "watch_time_seconds": "read_reel_insights", "likes": "read_post_insights", "comments": "read_comments",
    "shares": "read_post_insights", "saves": "read_post_insights", "profile_visits": "read_profile_metrics",
    "follows": "read_profile_metrics", "link_clicks": "read_post_insights",
}


class UnavailableMetricError(ValueError):
    """Raised when a metric is set to a non-null value while its gating capability is not
    AVAILABLE - refuses to let a caller silently fabricate a metric this codebase cannot observe."""


@dataclass(frozen=True)
class InstagramPerformanceObservation:
    content_id: str
    format: str
    objective: str
    observed_at: datetime

    reach: float | None = None
    impressions: float | None = None
    plays: float | None = None
    watch_time_seconds: float | None = None
    likes: float | None = None
    comments: float | None = None
    shares: float | None = None
    saves: float | None = None
    profile_visits: float | None = None
    follows: float | None = None
    link_clicks: float | None = None

    def __post_init__(self) -> None:
        for metric_name, capability_name in _METRIC_CAPABILITY.items():
            value = getattr(self, metric_name)
            if value is None:
                continue
            capability = get_capability(capability_name)
            if capability is None or capability.status != CapabilityStatus.AVAILABLE:
                status_label = capability.status.value if capability is not None else "unregistered"
                raise UnavailableMetricError(
                    f"{metric_name}={value!r} was set but capability {capability_name!r} is not "
                    f"AVAILABLE (status={status_label!r}) - an unobserved metric must stay None, "
                    "never a fabricated value"
                )

    def has_any_metric(self) -> bool:
        return any(getattr(self, name) is not None for name in _METRIC_CAPABILITY)
