"""INSTAGRAM GROWTH ENGINE v2, spec §16: ReferenceDeconstruction - decomposing a reference piece
of content into reusable MECHANICS, never its expression. This module never stores or reproduces a
reference's actual copy/footage/audio - only structural observations about how it works, paired
with an explicit originality constraint so a downstream creative pass never treats "learn the
mechanic" as license to "recreate the piece"."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ReferenceDeconstruction:
    reference_description: str  # a human-readable pointer/description, never the reference's own copy

    hook_mechanics: str = ""
    pacing: str = ""
    scene_structure: str = ""
    narrative_progression: str = ""
    typography_behavior: str = ""
    visual_rhythm: str = ""
    editing_rhythm: str = ""
    cta_mechanics: str = ""
    interaction_pattern: str = ""

    what_appears_effective: list[str] = field(default_factory=list)
    why_hypothesis_only: str = (
        "observed from a single reference with no controlled comparison - a mechanic that appears "
        "effective here is a hypothesis, not a proven driver of performance"
    )
    must_not_copy: list[str] = field(default_factory=list)
    originality_constraints: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.must_not_copy:
            raise ValueError(
                "must_not_copy cannot be empty - every ReferenceDeconstruction must name at least "
                "one element (exact copy/footage/audio/verbatim line, etc.) that is off-limits"
            )
