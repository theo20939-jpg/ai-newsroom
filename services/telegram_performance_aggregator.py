"""SOCIAL-INTELLIGENCE-OPS-1, spec §35-§44: TelegramPerformanceAggregator - the real evidence
producer `/performance`, `services/telegram_growth_director.py::derive_growth_director_advisory()`
and `services/telegram_strategy_director.py::derive_strategy_advisory()` were all missing (all
three already existed as pure, tested consumers of `PerformancePattern` evidence, but were always
called with an empty/hardcoded list - this module is the first thing that actually produces that
evidence from real data).

CRITICAL (spec §36 gate): only ever reads TelegramChannelMemory/TelegramPostPerformanceSnapshot
rows when the owned Telegram surface is a real PUBLIC_* surface with analytics explicitly enabled
(services/telegram_surface_registry.py::owned_surface_is_public_and_analytics_enabled) - this
phase's data model has exactly one owned channel (services/telegram_own_channel.py), so the gate is
a single boolean check, not a per-row surface filter; internal/editorial chat activity must never
leak into audience performance learning.

CRITICAL (spec §37 comparable-baseline rule): only ever compares snapshots captured at the SAME
nominal window (services/telegram_performance_normalization.py::same_window_snapshots) - never a
24h post against a 15m one - and only ever uses the time-normalized velocity metric (views per
hour), never a raw count, so posts of different ages within the same window class stay comparable.

CRITICAL (spec §38 missing-denominator-never-zero rule): a post with no comparable-window snapshot
is EXCLUDED from every dimension, never defaulted to a 0 rate; a dimension value whose baseline
cannot be computed (zero considered posts) is never emitted as a pattern with a fabricated
effect_size.

Dimensions implemented: content_role (`category`), presentation_type, topic (each entry of
`topics`), entity (each entry of `entities`), source, objective (`content_objective`),
campaign_relation (linked to a campaign or not), publication_hour, publication_day, visual_family.
"hook family" (spec's own dimension list) has no persisted field anywhere in this codebase today -
deliberately omitted rather than fabricated; noted in this phase's final report."""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.telegram_channel_memory import TelegramChannelMemory
from database.models.telegram_post_performance import SnapshotWindow, TelegramPostPerformanceSnapshot
from services.telegram_performance_memory import EvidenceStage, PerformancePattern, advance_evidence_stage
from services.telegram_performance_normalization import same_window_snapshots, views_velocity_per_hour
from services.telegram_surface_registry import owned_surface_is_public_and_analytics_enabled

_MIN_POSTS_FOR_AGGREGATION = 3
_MAX_PATTERNS = 30
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramPerformanceAggregate:
    as_of: datetime
    status: str  # PUBLIC_CHANNEL_NOT_CONFIGURED | WAITING_FOR_DATA | INSUFFICIENT_EVIDENCE | OK
    window: str
    total_posts_considered: int = 0
    patterns: list[PerformancePattern] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _dimension_values(memory: TelegramChannelMemory) -> list[tuple[str, str]]:
    """Every (dimension, value) pair this one post contributes to - a post may contribute to
    several values of the same dimension (e.g. multiple topics)."""
    pairs: list[tuple[str, str]] = []
    if memory.category:
        pairs.append(("content_role", memory.category))
    if memory.presentation_type:
        pairs.append(("presentation_type", memory.presentation_type))
    for topic in memory.topics or []:
        pairs.append(("topic", str(topic)))
    for entity in memory.entities or []:
        pairs.append(("entity", str(entity)))
    if memory.source:
        pairs.append(("source", memory.source))
    if memory.content_objective:
        pairs.append(("objective", memory.content_objective))
    pairs.append(("campaign_relation", "campaign" if memory.campaign_id is not None else "organic"))
    pairs.append(("publication_hour", str(memory.published_at.hour)))
    pairs.append(("publication_day", memory.published_at.strftime("%A")))
    if memory.visual_family:
        pairs.append(("visual_family", memory.visual_family))
    return pairs


async def _latest_comparable_snapshot_per_post(
    session: AsyncSession, memory_ids: list[UUID], *, window: SnapshotWindow,
) -> dict[UUID, TelegramPostPerformanceSnapshot]:
    if not memory_ids:
        return {}
    rows = list((await session.execute(
        select(TelegramPostPerformanceSnapshot).where(TelegramPostPerformanceSnapshot.channel_memory_id.in_(memory_ids))
    )).scalars().all())
    comparable = same_window_snapshots(rows, window=window.value)
    latest: dict[UUID, TelegramPostPerformanceSnapshot] = {}
    for snapshot in comparable:
        if snapshot.channel_memory_id is None:
            continue
        existing = latest.get(snapshot.channel_memory_id)
        if existing is None or snapshot.captured_at > existing.captured_at:
            latest[snapshot.channel_memory_id] = snapshot
    return latest


def _pattern_for_group(
    *, dimension: str, value: str, rates: list[float], last_observed_at: datetime,
    baseline_mean: float, baseline_sample_size: int, now: datetime,
) -> PerformancePattern:
    group_mean = sum(rates) / len(rates)
    effect_size = (group_mean - baseline_mean) / baseline_mean
    recency_days = max((now - last_observed_at).days, 0)
    draft = PerformancePattern(
        description=(
            f"{dimension}={value}: скорость просмотров {group_mean:.1f}/ч против базовой "
            f"{baseline_mean:.1f}/ч ({effect_size:+.0%})"
        ),
        stage=EvidenceStage.ANOMALY, sample_size=len(rates), effect_size=effect_size,
        confidence=min(0.9, 0.2 + 0.05 * len(rates)), repeatability=len(rates), baseline=baseline_mean,
        recency_days=recency_days, dimension=dimension, dimension_value=value,
        baseline_sample_size=baseline_sample_size, last_observed_at=last_observed_at,
    )
    stage = advance_evidence_stage(draft)
    if stage == draft.stage:
        return draft
    return PerformancePattern(
        description=draft.description, stage=stage, sample_size=draft.sample_size,
        effect_size=draft.effect_size, confidence=draft.confidence, repeatability=draft.repeatability,
        baseline=draft.baseline, recency_days=draft.recency_days, dimension=draft.dimension,
        dimension_value=draft.dimension_value, baseline_sample_size=draft.baseline_sample_size,
        last_observed_at=draft.last_observed_at,
    )


async def compute_telegram_performance_aggregate(
    session: AsyncSession, *, now: datetime | None = None, window: SnapshotWindow = SnapshotWindow.H24,
) -> TelegramPerformanceAggregate:
    now = now or datetime.now(timezone.utc)

    if not await owned_surface_is_public_and_analytics_enabled(session):
        return TelegramPerformanceAggregate(
            as_of=now, status="PUBLIC_CHANNEL_NOT_CONFIGURED", window=window.value,
            notes=["публичный аналитический канал не настроен - агрегация не выполняется"],
        )

    memories = list((await session.execute(select(TelegramChannelMemory))).scalars().all())
    if not memories:
        return TelegramPerformanceAggregate(
            as_of=now, status="WAITING_FOR_DATA", window=window.value,
            notes=["нет ни одного зафиксированного поста в telegram_channel_memory"],
        )

    snapshots_by_memory = await _latest_comparable_snapshot_per_post(
        session, [m.id for m in memories], window=window,
    )
    if not snapshots_by_memory:
        return TelegramPerformanceAggregate(
            as_of=now, status="WAITING_FOR_DATA", window=window.value,
            notes=[f"посты есть, но нет снапшотов эффективности для окна {window.value}"],
        )

    rate_by_memory_id: dict[UUID, float] = {}
    memory_by_id = {m.id: m for m in memories}
    last_observed_by_key: dict[tuple[str, str], datetime] = {}
    group_rates: dict[tuple[str, str], list[float]] = defaultdict(list)

    for memory_id, snapshot in snapshots_by_memory.items():
        rate = views_velocity_per_hour(snapshot)
        if rate is None:
            continue  # missing-denominator-never-zero: excluded, never defaulted to 0.0
        rate_by_memory_id[memory_id] = rate
        memory = memory_by_id[memory_id]
        for dimension, value in _dimension_values(memory):
            key = (dimension, value)
            group_rates[key].append(rate)
            if key not in last_observed_by_key or memory.published_at > last_observed_by_key[key]:
                last_observed_by_key[key] = memory.published_at

    total_considered = len(rate_by_memory_id)
    if total_considered < _MIN_POSTS_FOR_AGGREGATION:
        return TelegramPerformanceAggregate(
            as_of=now, status="INSUFFICIENT_EVIDENCE", window=window.value, total_posts_considered=total_considered,
            notes=[
                f"только {total_considered} пост(ов) с сопоставимым окном {window.value} - "
                f"нужно минимум {_MIN_POSTS_FOR_AGGREGATION}"
            ],
        )

    baseline_mean = sum(rate_by_memory_id.values()) / total_considered
    if baseline_mean <= 0:
        return TelegramPerformanceAggregate(
            as_of=now, status="INSUFFICIENT_EVIDENCE", window=window.value, total_posts_considered=total_considered,
            notes=["базовая скорость просмотров равна нулю - эффект посчитать невозможно"],
        )

    patterns: list[PerformancePattern] = []
    for (dimension, value), rates in group_rates.items():
        patterns.append(_pattern_for_group(
            dimension=dimension, value=value, rates=rates, last_observed_at=last_observed_by_key[(dimension, value)],
            baseline_mean=baseline_mean, baseline_sample_size=total_considered, now=now,
        ))
    patterns.sort(key=lambda p: p.effect_size, reverse=True)

    notes: list[str] = []
    if len(patterns) > _MAX_PATTERNS:
        notes.append(f"показаны {_MAX_PATTERNS} из {len(patterns)} паттернов")
        patterns = patterns[:_MAX_PATTERNS]

    logger.info(
        "telegram_performance_aggregated",
        extra={"window": window.value, "total_posts_considered": total_considered, "pattern_count": len(patterns)},
    )
    return TelegramPerformanceAggregate(
        as_of=now, status="OK", window=window.value, total_posts_considered=total_considered,
        patterns=patterns, notes=notes,
    )
