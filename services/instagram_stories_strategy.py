"""INSTAGRAM GROWTH ENGINE v2, spec §29: Stories amplification - structured planning only, no
publication (services/instagram_platform_capabilities.py::INSTAGRAM_PLATFORM_CAPABILITIES already
records "stories_publishing" as UNAVAILABLE; this module never assumes otherwise)."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime


class StoryRole(str, enum.Enum):
    TEASER = "teaser"
    POLL = "poll"
    RESHARE = "reshare"
    QUESTION = "question"
    FOLLOW_UP = "follow_up"
    SOCIAL_PROOF = "social_proof"
    COUNTDOWN = "countdown"
    PRODUCT_REMINDER = "product_reminder"
    FAQ = "faq"


@dataclass(frozen=True)
class StorySlide:
    role: StoryRole
    content: str
    interactive_element: str | None = None


@dataclass(frozen=True)
class StoryAmplificationPlan:
    objective: str
    sequence: list[StorySlide]
    source_content_id: str | None = None
    campaign_phase: str | None = None
    cta: str | None = None
    asset_requirements: list[str] = field(default_factory=list)
    expires_at: datetime | None = None
    restrictions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.sequence:
            raise ValueError("a StoryAmplificationPlan must have at least one slide")
