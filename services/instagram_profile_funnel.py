"""INSTAGRAM GROWTH ENGINE v2, spec §51: Profile/funnel intelligence - future-ready contract only.
No Instagram account mutation, no bio editing, no highlight editing anywhere in this module (spec's
own explicit instructions)."""
from __future__ import annotations

import enum
from dataclasses import dataclass


class ProfileFunnelStep(str, enum.Enum):
    CONTENT_VIEW = "content_view"
    PROFILE_VISIT = "profile_visit"
    FOLLOW = "follow"
    LINK_OR_PRODUCT_ACTION = "link_or_product_action"


@dataclass(frozen=True)
class ProfileFunnelObservation:
    content_id: str
    step: ProfileFunnelStep
    count: float | None = None
    source: str = "unknown"
    confidence: float = 0.1
