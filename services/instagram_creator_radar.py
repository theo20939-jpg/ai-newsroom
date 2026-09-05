"""INSTAGRAM GROWTH ENGINE v2, spec §27: Creator/Collab Radar - future-ready contracts only. No
outreach, no automatic contact, no pricing assumptions anywhere in this module (spec's own explicit
instructions) - `CreatorOpportunity` never carries a contact action, only a reasoned recommendation
for a human to act on."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CreatorProfile:
    handle: str
    platform: str
    niche: str = ""
    content_style: str = ""
    audience_fit: str = ""
    brand_fit: str = ""
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.2


@dataclass(frozen=True)
class CreatorOpportunity:
    creator_handle: str
    collab_type: str
    objective: str
    reason: str
    campaign_id: str | None = None
    risks: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.2
