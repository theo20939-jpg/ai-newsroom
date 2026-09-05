"""INSTAGRAM GROWTH ENGINE v2, spec §13/§14/§15: Competitor Intelligence - persistence for
CompetitorAccount/CompetitorContentObservation (database/models/competitor.py) plus
CompetitorPattern/CompetitorGap derivation. Mirrors services/claim_policy_service.py's own
create/query shape for the persistence half.

CRITICAL evidence discipline (spec §14): OBSERVATION -> PATTERN -> HYPOTHESIS -> STABLE_INSIGHT
are kept distinct. "Three competitor Reels used motion hooks" is a pattern; it is NEVER promoted
to "motion hooks guarantee reach" anywhere in this module - `CompetitorPattern`/`CompetitorGap`
only ever carry a `content_hypothesis` (explicitly framed as untested) and a `recommended_test`,
never a causal claim."""
from __future__ import annotations

import enum
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.competitor import CompetitorAccount, CompetitorContentObservation, ObservationSource

_MIN_OBSERVATIONS_FOR_PATTERN = 3
_MIN_OBSERVATIONS_FOR_GAP = 2


async def create_competitor_account(
    session: AsyncSession, *, platform: str, handle: str, display_name: str | None = None,
    niche: str | None = None, notes: str | None = None,
) -> CompetitorAccount:
    account = CompetitorAccount(platform=platform, handle=handle, display_name=display_name, niche=niche, notes=notes)
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def record_observation(
    session: AsyncSession, *, competitor_id: UUID, observed_at: datetime, format: str, topic: str,
    published_at: datetime | None = None, objective_inference: str | None = None, hook_family: str | None = None,
    creative_family: str | None = None, series: str | None = None, observable_metrics: dict | None = None,
    observation_source: ObservationSource = ObservationSource.MANUAL, confidence: float = 0.3,
) -> CompetitorContentObservation:
    """Never fabricates `observable_metrics` - a caller with no genuinely observed metric must
    pass `observable_metrics=None`, not a guessed 0 (spec §13/§65 "private/unavailable metrics not
    fabricated")."""
    observation = CompetitorContentObservation(
        competitor_id=competitor_id, observed_at=observed_at, published_at=published_at, format=format,
        topic=topic, objective_inference=objective_inference, hook_family=hook_family,
        creative_family=creative_family, series=series, observable_metrics=observable_metrics,
        observation_source=observation_source, confidence=confidence,
    )
    session.add(observation)
    await session.commit()
    await session.refresh(observation)
    return observation


async def list_observations(
    session: AsyncSession, *, competitor_id: UUID | None = None,
) -> list[CompetitorContentObservation]:
    stmt = select(CompetitorContentObservation)
    if competitor_id is not None:
        stmt = stmt.where(CompetitorContentObservation.competitor_id == competitor_id)
    return list((await session.execute(stmt)).scalars().all())


class EvidenceStage(str, enum.Enum):
    """Spec §14: identical shape/intent to services/instagram_content_brain.py::EvidenceStage but
    scoped to competitor observations - a single observation is always OBSERVATION, never
    a PATTERN by itself."""

    OBSERVATION = "observation"
    PATTERN = "pattern"
    HYPOTHESIS = "hypothesis"
    STABLE_INSIGHT = "stable_insight"


@dataclass(frozen=True)
class CompetitorPattern:
    dimension: str  # e.g. "hook_family", "format", "topic"
    value: str
    sample_size: int
    supporting_observation_ids: list[str] = field(default_factory=list)
    evidence_stage: EvidenceStage = EvidenceStage.OBSERVATION
    confidence: float = 0.2


def derive_patterns(
    observations: list[CompetitorContentObservation], *, dimension: str,
) -> list[CompetitorPattern]:
    """Groups observations by one dimension (hook_family/format/creative_family/topic) - a single
    observation NEVER becomes a `PATTERN` (spec §65's own required test); at least
    `_MIN_OBSERVATIONS_FOR_PATTERN` observations sharing a value are required."""
    buckets: dict[str, list[CompetitorContentObservation]] = {}
    for obs in observations:
        value = getattr(obs, dimension, None)
        if not value:
            continue
        buckets.setdefault(value, []).append(obs)

    patterns: list[CompetitorPattern] = []
    for value, matches in buckets.items():
        sample_size = len(matches)
        if sample_size == 1:
            stage = EvidenceStage.OBSERVATION
        elif sample_size < _MIN_OBSERVATIONS_FOR_PATTERN:
            stage = EvidenceStage.HYPOTHESIS
        else:
            stage = EvidenceStage.PATTERN
        patterns.append(CompetitorPattern(
            dimension=dimension, value=value, sample_size=sample_size,
            supporting_observation_ids=[str(o.id) for o in matches], evidence_stage=stage,
            confidence=min(0.2 + 0.1 * sample_size, 0.7),
        ))
    return patterns


class GapType(str, enum.Enum):
    TOPIC_GAP = "topic_gap"
    FORMAT_GAP = "format_gap"
    OBJECTIVE_GAP = "objective_gap"
    AUDIENCE_PROBLEM_GAP = "audience_problem_gap"
    SERIES_GAP = "series_gap"
    QUALITY_GAP = "quality_gap"
    ORIGINALITY_GAP = "originality_gap"
    CAMPAIGN_GAP = "campaign_gap"


@dataclass(frozen=True)
class CompetitorGap:
    gap_type: GapType
    description: str
    supporting_observation_ids: list[str] = field(default_factory=list)
    sample_size: int = 0
    confidence: float = 0.2
    content_hypothesis: str = ""
    recommended_test: str = ""


def find_topic_gaps(
    observations: list[CompetitorContentObservation], *, own_covered_topics: list[str],
) -> list[CompetitorGap]:
    """Spec §15 TOPIC_GAP: a topic multiple competitors cover repeatedly that this codebase's own
    content has never covered (`own_covered_topics`, supplied by the caller from real published
    content - never guessed here)."""
    own_lower = {t.lower() for t in own_covered_topics}
    topic_counts = Counter(obs.topic.lower() for obs in observations)
    gaps: list[CompetitorGap] = []
    for topic, count in topic_counts.items():
        if count < _MIN_OBSERVATIONS_FOR_GAP or topic in own_lower:
            continue
        supporting = [str(o.id) for o in observations if o.topic.lower() == topic]
        gaps.append(CompetitorGap(
            gap_type=GapType.TOPIC_GAP,
            description=f"{count} competitor observations cover {topic!r}; no own content covers it",
            supporting_observation_ids=supporting, sample_size=count,
            confidence=min(0.2 + 0.1 * count, 0.6),
            content_hypothesis=f"content about {topic!r} may fill an audience need this account doesn't yet address",
            recommended_test=f"test one piece of content on {topic!r} against a comparable baseline objective",
        ))
    return gaps


def find_format_gaps(
    observations: list[CompetitorContentObservation], *, own_used_formats: list[str],
) -> list[CompetitorGap]:
    own_lower = {f.lower() for f in own_used_formats}
    format_counts = Counter(obs.format.lower() for obs in observations)
    gaps: list[CompetitorGap] = []
    for fmt, count in format_counts.items():
        if count < _MIN_OBSERVATIONS_FOR_GAP or fmt in own_lower:
            continue
        supporting = [str(o.id) for o in observations if o.format.lower() == fmt]
        gaps.append(CompetitorGap(
            gap_type=GapType.FORMAT_GAP,
            description=f"{count} competitor observations use format {fmt!r}; this account has not used it",
            supporting_observation_ids=supporting, sample_size=count,
            confidence=min(0.2 + 0.1 * count, 0.6),
            content_hypothesis=f"format {fmt!r} may be an untested lever for this account",
            recommended_test=f"run one {fmt!r} experiment on a low-risk topic before broader adoption",
        ))
    return gaps
