"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 6 FIXTURE GATE - structural proof that the YouTube +
Bluesky Trend Radar source adapters are genuinely shadow-only this phase (code/tests/config
readiness, per the approved recovery scope), not merely flagged off while secretly wired:

  - neither adapter is imported anywhere in worker/content_cycle.py
  - both adapters raise TrendSourceNotConfigured (never fabricate) without real credentials
  - trend_collection_enabled still defaults False (Phase 5's own flag, unchanged by Phase 6)
"""
from __future__ import annotations

import ast
import inspect

import pytest

import worker.content_cycle as cc
from core.config import settings
from integrations.sources.bluesky_source import BlueskyTrendSourceAdapter
from integrations.sources.youtube_source import YouTubeTrendSourceAdapter
from services.trend_fingerprint import TrendSourceNotConfigured
from services.trend_source_scope import TrendDiscoveryScope


def test_content_cycle_module_does_not_import_either_trend_source_adapter() -> None:
    tree = ast.parse(inspect.getsource(cc))
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "YouTubeTrendSourceAdapter" not in imported
    assert "BlueskyTrendSourceAdapter" not in imported


@pytest.mark.asyncio
async def test_youtube_adapter_without_credentials_raises_never_fabricates() -> None:
    with pytest.raises(TrendSourceNotConfigured):
        await YouTubeTrendSourceAdapter().fetch_candidates(TrendDiscoveryScope())


@pytest.mark.asyncio
async def test_bluesky_adapter_without_credentials_raises_never_fabricates() -> None:
    with pytest.raises(TrendSourceNotConfigured):
        await BlueskyTrendSourceAdapter().fetch_candidates(TrendDiscoveryScope())


def test_trend_collection_still_defaults_off() -> None:
    assert settings.trend_collection_enabled is False
    assert settings.trend_autonomous_content_generation is False
