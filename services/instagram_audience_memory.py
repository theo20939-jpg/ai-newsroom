"""INSTAGRAM-GROWTH-3, item 2/3/13: Audience Intelligence persistence. `create_audience_insight()`
enforces the SAME rule the accepted dataclass (services/instagram_audience_intelligence.py::
AudienceInsight) already enforces in-memory: a non-HYPOTHESIS source requires at least one real
evidence item up front - a source without evidence is indistinguishable from an unsupported claim.
`add_audience_evidence()` is the mechanism spec item 13 asks for ("allow confidence/evidence to
evolve as more observations arrive") - each call appends evidence, increments observation_count,
and re-derives evidence_stage/confidence, never lets a caller hand-set either."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_audience_memory import AudienceEvidenceSource, InstagramAudienceInsight
from services.instagram_content_brain import advance_intelligence_evidence_stage


class UnsupportedAudienceInsightError(ValueError):
    """Raised when a non-HYPOTHESIS insight is created with no evidence at all."""


def _confidence_for(observation_count: int, *, is_hypothesis: bool) -> float:
    if is_hypothesis:
        return 0.15
    return round(min(0.2 + 0.1 * observation_count, 0.85), 3)


async def create_audience_insight(
    session: AsyncSession, *, segment_name: str, need: str, source: AudienceEvidenceSource,
    funnel_stage: str | None = None, problem: str | None = None, interest: str | None = None,
    objection: str | None = None, content_job: str | None = None,
    format_preference_hypothesis: str | None = None, initial_evidence: str | None = None,
) -> InstagramAudienceInsight:
    is_hypothesis = source == AudienceEvidenceSource.HYPOTHESIS
    if not is_hypothesis and not initial_evidence:
        raise UnsupportedAudienceInsightError(
            f"source={source.value!r} requires initial_evidence - a non-HYPOTHESIS insight can "
            "never be created without at least one supporting observation"
        )

    evidence = [initial_evidence] if initial_evidence else []
    observation_count = 0 if is_hypothesis else 1
    stage = advance_intelligence_evidence_stage(observation_count=observation_count, is_hypothesis_only=is_hypothesis)

    insight = InstagramAudienceInsight(
        segment_name=segment_name, funnel_stage=funnel_stage, need=need, problem=problem, interest=interest,
        objection=objection, content_job=content_job, format_preference_hypothesis=format_preference_hypothesis,
        source=source, evidence=evidence, observation_count=observation_count,
        evidence_stage=stage, confidence=_confidence_for(observation_count, is_hypothesis=is_hypothesis),
    )
    session.add(insight)
    await session.commit()
    await session.refresh(insight)
    return insight


async def add_audience_evidence(
    session: AsyncSession, insight_id: UUID, *, evidence_text: str,
) -> InstagramAudienceInsight:
    """Spec item 13: evidence/confidence evolve as more observations arrive - a HYPOTHESIS-sourced
    insight receiving its first real evidence graduates out of pure-HYPOTHESIS territory (its
    `source` column is left as the original provenance record, but `evidence_stage` now reflects
    the accumulated observation count like any other insight)."""
    insight = await session.get(InstagramAudienceInsight, insight_id)
    if insight is None:
        raise ValueError(f"no InstagramAudienceInsight with id={insight_id}")

    insight.evidence = [*(insight.evidence or []), evidence_text]
    insight.observation_count += 1
    insight.evidence_stage = advance_intelligence_evidence_stage(observation_count=insight.observation_count, is_hypothesis_only=False)
    insight.confidence = _confidence_for(insight.observation_count, is_hypothesis=False)

    await session.commit()
    await session.refresh(insight)
    return insight


async def list_audience_insights(
    session: AsyncSession, *, segment_name: str | None = None,
) -> list[InstagramAudienceInsight]:
    stmt = select(InstagramAudienceInsight)
    if segment_name is not None:
        stmt = stmt.where(InstagramAudienceInsight.segment_name == segment_name)
    return list((await session.execute(stmt)).scalars().all())
