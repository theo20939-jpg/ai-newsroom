"""INSTAGRAM GROWTH ENGINE v2, spec §17/§18/§19: Audience Intelligence. `AudienceSegment` carries
NO demographic fields (age/gender/location/income) at all by design - spec §18's own "do not
fabricate demographics unless actually provided by data" instruction is enforced structurally
(nothing to fabricate into) rather than left to convention; a caller with genuine first-party
demographic data can still attach it via `AudienceInsight.evidence`, always paired with a real
`source`, never as a bare unsourced field.

CRITICAL (spec §18): every `AudienceInsight` REQUIRES a `source` (`AudienceEvidenceSource`) - there
is no default. A `HYPOTHESIS`-sourced insight is a real, useful thing to record, but
`is_hypothesis` makes it structurally distinguishable from an evidence-backed one, so nothing
downstream can accidentally treat a hypothesis as confirmed."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field


class FunnelStage(str, enum.Enum):
    """Spec §19."""

    UNAWARE = "unaware"
    PROBLEM_AWARE = "problem_aware"
    SOLUTION_AWARE = "solution_aware"
    PRODUCT_AWARE = "product_aware"
    CONSIDERING = "considering"
    USER = "user"


class AudienceEvidenceSource(str, enum.Enum):
    """Spec §18."""

    FIRST_PARTY_PERFORMANCE = "first_party_performance"
    COMMENTS = "comments"
    PRODUCT_DATA = "product_data"
    MANUAL_RESEARCH = "manual_research"
    COMPETITOR_OBSERVATION = "competitor_observation"
    FOUNDER_INPUT = "founder_input"
    HYPOTHESIS = "hypothesis"


@dataclass(frozen=True)
class AudienceSegment:
    name: str
    description: str
    funnel_stage: FunnelStage
    product_relationship: str = ""


@dataclass(frozen=True)
class AudienceInsight:
    segment_name: str
    need: str
    source: AudienceEvidenceSource
    problem: str = ""
    interest: str = ""
    objection: str = ""
    content_job: str = ""
    format_preference_hypothesis: str | None = None
    conversion_stage: FunnelStage | None = None
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.3

    def __post_init__(self) -> None:
        if self.source != AudienceEvidenceSource.HYPOTHESIS and not self.evidence:
            raise ValueError(
                "a non-HYPOTHESIS AudienceInsight requires at least one evidence item - a source "
                "without evidence is indistinguishable from an unsupported claim"
            )

    @property
    def is_hypothesis(self) -> bool:
        return self.source == AudienceEvidenceSource.HYPOTHESIS
