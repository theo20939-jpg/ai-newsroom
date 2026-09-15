"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 5: lightweight semantic clustering over NORMALIZED trend
fingerprints (never raw text - see services/trend_fingerprint.py for why). Reuses
services/text_normalization.py's own pure `symmetric_token_overlap()` primitive with a
trend-specific comparison SHAPE (topic+entities vs format+hook_pattern+mechanic, instead of
story_memory.py's whole-headline/EventCategory-threaded comparison) - `services/story_memory.py`
itself is never imported or edited; this is "extend by composition", not a fork, and definitely
not a second clustering pipeline.

Cluster type classification (Founder-specified, exactly three): TOPIC (same real-world subject
across observations), FORMAT (same spreading mechanic/editing pattern across DIFFERENT topics),
HYBRID (both topic and format/mechanic are spreading together)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.trend_cluster import TrendCluster, TrendClusterStatus, TrendClusterType
from database.models.trend_observation import TrendObservation
from services.text_normalization import symmetric_token_overlap
from services.trend_fingerprint import TrendFingerprint

_TOPIC_OVERLAP_THRESHOLD = 0.35
_FORMAT_OVERLAP_THRESHOLD = 0.35
_DEFAULT_CLUSTER_LOOKBACK = timedelta(days=14)


def _topic_text(fp: TrendFingerprint) -> str:
    return f"{fp.topic} {' '.join(fp.entities)}"


def _format_text(fp: TrendFingerprint) -> str:
    return f"{fp.format} {fp.hook_pattern} {fp.mechanic}"


def topic_similarity(a: TrendFingerprint, b: TrendFingerprint) -> float:
    return symmetric_token_overlap(_topic_text(a), _topic_text(b))


def format_similarity(a: TrendFingerprint, b: TrendFingerprint) -> float:
    return symmetric_token_overlap(_format_text(a), _format_text(b))


@dataclass(frozen=True)
class ClusterMatchResult:
    matches: bool
    cluster_type: TrendClusterType | None
    topic_similarity: float
    format_similarity: float


def classify_relationship(
    a: TrendFingerprint, b: TrendFingerprint, *,
    topic_threshold: float = _TOPIC_OVERLAP_THRESHOLD, format_threshold: float = _FORMAT_OVERLAP_THRESHOLD,
) -> ClusterMatchResult:
    """The pure decision core: do two fingerprints belong in the same cluster, and if so, is that
    cluster a TOPIC match, a FORMAT match, or HYBRID (both)? Never a fourth outcome."""
    topic_sim = topic_similarity(a, b)
    format_sim = format_similarity(a, b)
    topic_match = topic_sim >= topic_threshold
    format_match = format_sim >= format_threshold

    if topic_match and format_match:
        cluster_type: TrendClusterType | None = TrendClusterType.HYBRID
    elif topic_match:
        cluster_type = TrendClusterType.TOPIC
    elif format_match:
        cluster_type = TrendClusterType.FORMAT
    else:
        cluster_type = None

    return ClusterMatchResult(
        matches=cluster_type is not None, cluster_type=cluster_type, topic_similarity=topic_sim, format_similarity=format_sim,
    )


@dataclass(frozen=True)
class BestClusterMatch:
    cluster_id: UUID
    result: ClusterMatchResult


def find_best_cluster_match(
    new_fingerprint: TrendFingerprint, candidates: list[tuple[UUID, TrendFingerprint]], *,
    topic_threshold: float = _TOPIC_OVERLAP_THRESHOLD, format_threshold: float = _FORMAT_OVERLAP_THRESHOLD,
) -> BestClusterMatch | None:
    """Picks the single best-matching existing cluster (by combined topic+format similarity),
    among every candidate that actually matches - never the "closest" candidate when NONE of them
    clears either threshold (unrelated items correctly form no match, per the fixture gate's own
    'unrelated items do not cluster' requirement)."""
    best: BestClusterMatch | None = None
    for cluster_id, candidate_fp in candidates:
        result = classify_relationship(new_fingerprint, candidate_fp, topic_threshold=topic_threshold, format_threshold=format_threshold)
        if not result.matches:
            continue
        combined = result.topic_similarity + result.format_similarity
        if best is None or combined > (best.result.topic_similarity + best.result.format_similarity):
            best = BestClusterMatch(cluster_id=cluster_id, result=result)
    return best


async def assign_observation_to_cluster(
    session: AsyncSession, observation: TrendObservation, *, now: datetime | None = None,
    lookback: timedelta = _DEFAULT_CLUSTER_LOOKBACK,
) -> TrendCluster | None:
    """Assigns ONE observation to an existing cluster (updating `last_observed_at`) or founds a
    NEW one - `None` only when `observation.trend_fingerprint` itself is absent (a fingerprint
    call that failed fail-soft - the observation is still recorded, per services/
    trend_fingerprint.py's own contract, just not yet clusterable; a later backfill pass, not
    built this phase, could retry it)."""
    if not observation.trend_fingerprint:
        return None
    now = now or datetime.now(timezone.utc)
    new_fp = TrendFingerprint.from_dict(observation.trend_fingerprint)

    cutoff = now - lookback
    stmt = select(TrendCluster).where(
        TrendCluster.status == TrendClusterStatus.ACTIVE, TrendCluster.last_observed_at >= cutoff,
    )
    active_clusters = list((await session.execute(stmt)).scalars().all())
    candidates = [(c.id, TrendFingerprint.from_dict(c.trend_fingerprint)) for c in active_clusters]

    best = find_best_cluster_match(new_fp, candidates)
    if best is not None:
        cluster = next(c for c in active_clusters if c.id == best.cluster_id)
        cluster.last_observed_at = max(cluster.last_observed_at, observation.observed_at)
        observation.cluster_id = cluster.id
        await session.commit()
        return cluster

    cluster = TrendCluster(
        representative_text=observation.raw_topic_text, cluster_type=TrendClusterType.TOPIC,
        trend_fingerprint=observation.trend_fingerprint, first_observed_at=observation.observed_at,
        last_observed_at=observation.observed_at, status=TrendClusterStatus.ACTIVE,
    )
    session.add(cluster)
    await session.flush()
    observation.cluster_id = cluster.id
    await session.commit()
    await session.refresh(cluster)
    return cluster
