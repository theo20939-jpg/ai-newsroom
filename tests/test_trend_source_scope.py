"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 5: services/trend_source_scope.py - trend discovery scope
combines 5 inputs, Product/Campaign is never the sole gate ("Founder Plan Review" constraint #2)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.trend_cluster import TrendCluster, TrendClusterStatus, TrendClusterType
from services.business_context_snapshot_service import get_business_context_snapshot
from services.campaign_service import create_campaign
from services.product_context_service import create_product, create_product_context_version
from services.strategic_directive_service import create_directive
from services.trend_source_scope import (
    NINJA_EDITORIAL_VERTICALS,
    build_trend_discovery_scope,
    recurring_terms_from_clusters,
)


def test_ninja_editorial_verticals_are_always_present() -> None:
    """Discovery never depends solely on Product/Campaign - the fixed verticals are always there."""
    scope_terms = list(NINJA_EDITORIAL_VERTICALS)
    for vertical in ("AI", "gadgets", "consumer tech", "gaming", "internet culture", "digital lifestyle"):
        assert vertical in scope_terms


def test_all_terms_deduplicates_case_insensitively_preserving_order() -> None:
    from services.trend_source_scope import TrendDiscoveryScope

    scope = TrendDiscoveryScope(
        ninja_verticals=["AI", "Gaming"], directive_topics=["ai"], monitored_entities=["gaming", "NINJA VPN"],
        product_terms=["NINJA VPN"], temporary_expansion_terms=[],
    )
    assert scope.all_terms == ["AI", "Gaming", "NINJA VPN"]


def test_recurring_terms_pure_gate_requires_min_recurrence() -> None:
    fingerprints = [
        {"topic": "starter pack trend", "entities": ["NINJA"]},
        {"topic": "starter pack trend", "entities": ["other"]},
        {"topic": "one-off topic", "entities": ["once"]},
    ]
    recurring = recurring_terms_from_clusters(fingerprints, min_recurrence=2)
    assert "starter pack trend" in recurring
    assert "one-off topic" not in recurring
    assert "once" not in recurring  # appeared only once


@pytest.mark.asyncio
async def test_discovery_scope_is_never_product_only(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Even with zero products/campaigns/directives, discovery still has real terms to query -
    the NINJA verticals alone are always sufficient scope."""
    monkeypatch.setattr(settings, "trend_monitored_entities", [])
    now = datetime.now(timezone.utc)
    scope = await build_trend_discovery_scope(db_session, now=now, snapshot=None)
    assert len(scope.all_terms) > 0
    assert scope.product_terms == []


@pytest.mark.asyncio
async def test_product_context_contributes_terms_but_is_not_the_only_source(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="scope1", name="Scope Test Product")
    await create_product_context_version(
        db_session, product_id=product.id, raw_instruction="x",
        structured_context={"core_value_propositions": ["private browsing"]}, confirmed_by=1,
    )
    now = datetime.now(timezone.utc)
    snapshot = await get_business_context_snapshot(db_session, now=now)
    scope = await build_trend_discovery_scope(db_session, now=now, snapshot=snapshot)
    assert "private browsing" in scope.product_terms
    assert len(scope.ninja_verticals) > 0  # verticals are STILL present alongside product terms


@pytest.mark.asyncio
async def test_active_campaign_key_messages_contribute_terms(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="scope2", name="Scope Test Product 2")
    now = datetime.now(timezone.utc)
    await create_campaign(
        db_session, product_id=product.id, name="Scope 2 launch",
        structured_context={
            "status": "confirmed", "planned_launch_date": (now.date() + timedelta(days=2)).isoformat(),
            "date_confidence": "exact", "key_messages": ["fastest VPN ever"],
        },
    )
    snapshot = await get_business_context_snapshot(db_session, now=now)
    scope = await build_trend_discovery_scope(db_session, now=now, snapshot=snapshot)
    assert "fastest VPN ever" in scope.product_terms


@pytest.mark.asyncio
async def test_active_directive_scope_contributes_topics(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    await create_directive(db_session, instruction="focus on AI gadget trends this week", valid_from=now, created_by=1, scope="ai_gadgets")
    scope = await build_trend_discovery_scope(db_session, now=now)
    assert "ai_gadgets" in scope.directive_topics


@pytest.mark.asyncio
async def test_monitored_entities_setting_contributes_terms(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "trend_monitored_entities", ["@some_watched_account"])
    now = datetime.now(timezone.utc)
    scope = await build_trend_discovery_scope(db_session, now=now)
    assert "@some_watched_account" in scope.monitored_entities


@pytest.mark.asyncio
async def test_temporary_expansion_only_includes_recent_recurring_entities(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    for i in range(2):
        cluster = TrendCluster(
            representative_text=f"c{i}", cluster_type=TrendClusterType.TOPIC,
            trend_fingerprint={"topic": "recurring gadget topic", "entities": ["NewGadgetX"]},
            first_observed_at=now, last_observed_at=now, status=TrendClusterStatus.ACTIVE,
        )
        db_session.add(cluster)
    stale_cluster = TrendCluster(
        representative_text="stale", cluster_type=TrendClusterType.TOPIC,
        trend_fingerprint={"topic": "old topic", "entities": ["OldThing"]},
        first_observed_at=now - timedelta(days=30), last_observed_at=now - timedelta(days=30),
        status=TrendClusterStatus.ACTIVE,
    )
    db_session.add(stale_cluster)
    await db_session.flush()

    scope = await build_trend_discovery_scope(db_session, now=now)
    assert "NewGadgetX" in scope.temporary_expansion_terms
    assert "OldThing" not in scope.temporary_expansion_terms  # outside the expansion window
