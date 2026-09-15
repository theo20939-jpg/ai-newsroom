"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 5: trend discovery scope. "Founder Plan Review" constraint
#2 - trend_source_scope must NOT derive discovery only from Product/LaunchCampaign; Product/
Campaign relevance is a RANKING signal, never the discovery GATE. Combines five inputs, all
reusing existing Business Context/config structures - no new CMS:

1. NINJA editorial verticals - a small, fixed, explicitly-named list.
2. Founder/editorial directives - the EXISTING StrategicDirective.scope (already captured via
   /directive or the plain-text Director path).
3. Monitored entities/accounts/hashtags - a Founder-curated flat config list
   (settings.trend_monitored_entities), same class of setting as business_context_role_map.
4. Product/LaunchCampaign context - ONE input among five, never the sole gate.
5. Bounded temporary expansion from recently recurring trend fingerprints - DERIVED and
   recomputed every call, never a persisted watchlist table of its own.

Discovery therefore remains capable of finding a strong GENERAL social trend before any product
maps to it - narrowing to Product/Campaign-derived terms alone would make the radar blind to
exactly the trends it exists to find."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.strategic_directive import StrategicDirective
from database.models.trend_cluster import TrendCluster, TrendClusterStatus
from services.business_context_snapshot_service import BusinessContextSnapshot
from services.strategic_directive_service import list_active_directives

# 1. NINJA editorial verticals - matches the product decision's own named scope exactly. Plain
# config, the same class of thing story_memory.py's own fixed topic lexicon already is elsewhere
# in this codebase - never a database table.
NINJA_EDITORIAL_VERTICALS: tuple[str, ...] = (
    "AI", "gadgets", "consumer tech", "gaming", "internet culture", "digital lifestyle",
)

_TEMPORARY_EXPANSION_WINDOW = timedelta(days=3)
_TEMPORARY_EXPANSION_MIN_RECURRENCE = 2


@dataclass(frozen=True)
class TrendDiscoveryScope:
    ninja_verticals: list[str] = field(default_factory=list)
    directive_topics: list[str] = field(default_factory=list)
    monitored_entities: list[str] = field(default_factory=list)
    product_terms: list[str] = field(default_factory=list)
    temporary_expansion_terms: list[str] = field(default_factory=list)

    @property
    def all_terms(self) -> list[str]:
        """Deduplicated (case-insensitive), order-preserving union of every input - the actual
        seed query list a source adapter polls with."""
        seen: set[str] = set()
        ordered: list[str] = []
        for term in (
            self.ninja_verticals + self.directive_topics + self.monitored_entities
            + self.product_terms + self.temporary_expansion_terms
        ):
            normalized = term.strip()
            key = normalized.lower()
            if not normalized or key in seen:
                continue
            seen.add(key)
            ordered.append(normalized)
        return ordered


def _directive_topics(directives: list[StrategicDirective]) -> list[str]:
    return [directive.scope for directive in directives if directive.scope]


def _monitored_entities() -> list[str]:
    return list(settings.trend_monitored_entities)


def _product_terms(snapshot: BusinessContextSnapshot | None) -> list[str]:
    if snapshot is None:
        return []
    terms: list[str] = []
    for summary in snapshot.products:
        terms.append(summary.product.name)
        terms.extend(summary.product.core_value_propositions or [])
    for plan in snapshot.active_campaigns:
        terms.extend(plan.key_messages)
    return terms


async def _temporary_expansion_terms(
    session: AsyncSession, *, now: datetime, window: timedelta = _TEMPORARY_EXPANSION_WINDOW,
    min_recurrence: int = _TEMPORARY_EXPANSION_MIN_RECURRENCE,
) -> list[str]:
    cutoff = now - window
    stmt = select(TrendCluster).where(
        TrendCluster.status == TrendClusterStatus.ACTIVE, TrendCluster.last_observed_at >= cutoff,
    )
    clusters = list((await session.execute(stmt)).scalars().all())
    return recurring_terms_from_clusters(
        [c.trend_fingerprint or {} for c in clusters], min_recurrence=min_recurrence,
    )


def recurring_terms_from_clusters(fingerprints: list[dict], *, min_recurrence: int = _TEMPORARY_EXPANSION_MIN_RECURRENCE) -> list[str]:
    """The pure decision core of temporary expansion - split out for deterministic unit testing,
    independent of any database session."""
    counts: Counter[str] = Counter()
    for fp in fingerprints:
        for entity in fp.get("entities") or []:
            counts[entity] += 1
        topic = fp.get("topic")
        if topic:
            counts[topic] += 1
    return [term for term, count in counts.items() if count >= min_recurrence]


async def build_trend_discovery_scope(
    session: AsyncSession, *, now: datetime, snapshot: BusinessContextSnapshot | None = None,
) -> TrendDiscoveryScope:
    directives = await list_active_directives(session, now=now)
    expansion = await _temporary_expansion_terms(session, now=now)
    return TrendDiscoveryScope(
        ninja_verticals=list(NINJA_EDITORIAL_VERTICALS), directive_topics=_directive_topics(directives),
        monitored_entities=_monitored_entities(), product_terms=_product_terms(snapshot),
        temporary_expansion_terms=expansion,
    )
