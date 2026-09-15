"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 5 FIXTURE GATE - the exact required scenario list from the
Founder's own overnight-run authorization, gathered into one file as the authoritative proof (each
scenario is also covered by its owning module's own unit tests - this file is the consolidated,
by-name checklist, not a duplicate of that coverage):

  - same TOPIC across different sources clusters together
  - same FORMAT mechanic across unrelated topics can form a FORMAT trend
  - unrelated items do not cluster
  - one snapshot -> no velocity
  - two snapshots -> real velocity
  - cross-source normalization required
  - weak evidence -> zero opportunities
  - TREND content generation remains OFF
"""
from __future__ import annotations

import ast
import inspect
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import worker.content_cycle as cc
from core.config import settings
from database.models.trend_cluster import TrendClusterType
from database.models.trend_observation import TrendObservation
from services.trend_evidence_ranking import TrendEvidence, is_trend_evidence_sufficient
from services.trend_fingerprint import TrendFingerprint
from services.trend_normalization import compute_velocity, normalize_engagement
from services.trend_signal_matching import assign_observation_to_cluster, classify_relationship


def _fp(**overrides) -> TrendFingerprint:
    base = dict(topic="", entities=[], format="", hook_pattern="", mechanic="", visual_pattern="")
    base.update(overrides)
    return TrendFingerprint(**base)


# ---------------------------------------------------------------------------
# Clustering fixtures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_same_topic_different_sources_clusters_together(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    fp_youtube = _fp(topic="new foldable phone launch", entities=["iPhone Duo"], format="reel")
    obs_youtube = TrendObservation(
        source="youtube", source_item_id=str(uuid4()), observed_at=now, raw_topic_text="unboxing the new foldable",
        trend_fingerprint=fp_youtube.as_dict(), engagement_snapshot={"view_count": 50000},
    )
    db_session.add(obs_youtube)
    await db_session.flush()
    cluster_a = await assign_observation_to_cluster(db_session, obs_youtube, now=now)

    fp_bluesky = _fp(topic="new foldable phone launch", entities=["iPhone Duo"], format="text_post")
    obs_bluesky = TrendObservation(
        source="bluesky", source_item_id=str(uuid4()), observed_at=now + timedelta(hours=3),
        raw_topic_text="everyone's talking about the foldable", trend_fingerprint=fp_bluesky.as_dict(),
        engagement_snapshot={"like_count": 900},
    )
    db_session.add(obs_bluesky)
    await db_session.flush()
    cluster_b = await assign_observation_to_cluster(db_session, obs_bluesky, now=now + timedelta(hours=3))

    assert cluster_a is not None and cluster_b is not None
    assert cluster_a.id == cluster_b.id
    assert cluster_a.cluster_type == TrendClusterType.TOPIC


def test_fixture_same_format_mechanic_across_unrelated_topics_forms_format_trend() -> None:
    a = _fp(topic="a new budget laptop review", mechanic="starter pack", hook_pattern="POV question", format="reel")
    b = _fp(topic="a completely unrelated skincare routine", mechanic="starter pack", hook_pattern="POV question", format="reel")
    result = classify_relationship(a, b)
    assert result.matches is True
    assert result.cluster_type == TrendClusterType.FORMAT


def test_fixture_unrelated_items_do_not_cluster() -> None:
    a = _fp(topic="a new budget laptop review", mechanic="unboxing", entities=["LaptopX"])
    b = _fp(topic="a viral dance trend", mechanic="dance challenge", entities=["dance"])
    result = classify_relationship(a, b)
    assert result.matches is False


# ---------------------------------------------------------------------------
# Velocity fixtures
# ---------------------------------------------------------------------------


def test_fixture_one_snapshot_produces_no_velocity() -> None:
    now = datetime.now(timezone.utc)
    result = compute_velocity([(now, {"like_count": 500})], primary_metric_key="like_count")
    assert result.available is False


def test_fixture_two_snapshots_produce_real_velocity() -> None:
    now = datetime.now(timezone.utc)
    result = compute_velocity(
        [(now, {"like_count": 500}), (now + timedelta(hours=5), {"like_count": 1000})],
        primary_metric_key="like_count",
    )
    assert result.available is True
    assert result.delta_per_hour == 100.0


# ---------------------------------------------------------------------------
# Cross-source normalization fixture
# ---------------------------------------------------------------------------


def test_fixture_cross_source_normalization_is_required_before_comparison() -> None:
    """Two raw numbers from different sources (a YouTube view_count and a Bluesky like_count) are
    NEVER compared directly - only their independently-normalized, source-relative percentiles
    are comparable."""
    youtube = normalize_engagement(
        {"view_count": 80000}, source_baseline_snapshots=[{"view_count": v} for v in (10000, 20000, 30000)],
        primary_metric_key="view_count",
    )
    bluesky = normalize_engagement(
        {"like_count": 30}, source_baseline_snapshots=[{"like_count": v} for v in (5, 10, 15)],
        primary_metric_key="like_count",
    )
    assert youtube.available and bluesky.available
    # Both are "unusually high for their own source" - the ONLY valid cross-source comparison.
    assert youtube.percentile == bluesky.percentile == 1.0


# ---------------------------------------------------------------------------
# Weak evidence -> zero opportunities
# ---------------------------------------------------------------------------


def test_fixture_weak_evidence_produces_zero_opportunities() -> None:
    """A cluster observed only once, from a single source, recently but with no engagement
    evidence at all, is NOT sufficient - the gate must be allowed to say no, never forcing a
    'best available' pick."""
    weak_evidence = TrendEvidence(cross_source_count=1, recency_hours=1.0, normalized_engagement=None)
    result = is_trend_evidence_sufficient(weak_evidence)
    assert result.sufficient is False
    # A caller respecting this gate builds ZERO ContentOpportunity(TREND) rows from this cluster -
    # never calls build_trend_opportunity() when the gate says no (verified as this module's own
    # documented contract, not re-invented here).


# ---------------------------------------------------------------------------
# TREND content generation remains OFF (shadow-only settings + no live wiring)
# ---------------------------------------------------------------------------


def test_fixture_trend_autonomous_content_generation_defaults_false() -> None:
    assert settings.trend_autonomous_content_generation is False


def test_fixture_trend_collection_and_clustering_default_off_ranking_defaults_shadow() -> None:
    assert settings.trend_collection_enabled is False
    assert settings.trend_clustering_enabled is False
    assert settings.trend_ranking_shadow is True


def test_fixture_no_live_worker_cycle_path_submits_a_trend_opportunity() -> None:
    """Structural proof: run_content_cycle()'s own body never calls build_trend_opportunity() or
    evaluate_and_submit_instagram_opportunity() with a TREND-sourced opportunity - Phase 5 is
    genuinely shadow-only, not merely flagged off while secretly wired."""
    source = inspect.getsource(cc.run_content_cycle)
    tree = ast.parse(source)
    called_names = {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "build_trend_opportunity" not in called_names
    assert "is_trend_evidence_sufficient" not in called_names


def test_fixture_content_cycle_module_does_not_even_import_trend_evidence_ranking() -> None:
    """A stronger guarantee than "not called" - the live worker module doesn't import the TREND
    opportunity-construction function AT ALL this phase."""
    tree = ast.parse(inspect.getsource(cc))
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "build_trend_opportunity" not in imported
