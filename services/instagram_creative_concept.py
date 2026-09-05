"""INSTAGRAM GROWTH ENGINE v2, spec §32: CreativeConcept - the structured hand-off between Growth
Strategy and a Production Package (services/instagram_format_director.py). Claims are enforced the
SAME way a production package already enforces them (services/instagram_format_director.py::
validate_package_claims) - a CreativeConcept must never assert a restricted claim in its own
narrative/angle text either, since a copywriter working from this concept has no other safety net
until the final package's own constructor re-checks it."""
from __future__ import annotations

from dataclasses import dataclass, field

from services.instagram_format_director import ContentFormat, validate_package_claims
from services.instagram_hook_intelligence import Hook
from services.instagram_objectives import ContentObjective


@dataclass(frozen=True)
class CreativeConcept:
    id: str
    objective: ContentObjective
    target_audience: str
    core_insight: str
    angle: str
    hook: Hook
    format: ContentFormat

    narrative: str = ""
    visual_direction: str = ""

    story_id: str | None = None
    trend_id: str | None = None
    campaign_id: str | None = None
    series_id: str | None = None

    approved_claims: list[str] = field(default_factory=list)
    restricted_claims: list[str] = field(default_factory=list)

    cta: str | None = None
    asset_requirements: list[str] = field(default_factory=list)

    originality_notes: str = ""
    production_complexity: str = "medium"
    risks: list[str] = field(default_factory=list)
    confidence: float = 0.2

    def __post_init__(self) -> None:
        validate_package_claims(
            text_fields=[self.core_insight, self.angle, self.narrative, self.cta or ""],
            restricted_claims=self.restricted_claims,
        )
