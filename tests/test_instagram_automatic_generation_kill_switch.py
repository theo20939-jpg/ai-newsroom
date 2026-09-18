"""Founder cost-control master switch for automatic Instagram generation."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core.config import settings
from worker import content_cycle as cc


@pytest.mark.asyncio
async def test_master_off_news_lane_makes_zero_generation_calls(monkeypatch) -> None:
    monkeypatch.setattr(settings, "instagram_automatic_generation_enabled", False)
    with patch.object(cc, "evaluate_and_submit_instagram_candidate", new=AsyncMock()) as generate:
        report = await cc._run_instagram_automatic_trigger(
            AsyncMock(), AsyncMock(), [object()], gate_gateway=object(), gate_prompt_repository=object()
        )
    generate.assert_not_awaited()
    assert report.stories_evaluated == 0


@pytest.mark.asyncio
async def test_master_off_product_lane_makes_zero_generation_calls(monkeypatch) -> None:
    monkeypatch.setattr(settings, "instagram_automatic_generation_enabled", False)
    monkeypatch.setattr(settings, "instagram_product_lane_enabled", True)
    with (
        patch.object(cc, "run_instagram_growth_strategist", new=AsyncMock()) as rank,
        patch.object(cc, "evaluate_and_submit_instagram_opportunity", new=AsyncMock()) as generate,
    ):
        report = await cc._run_instagram_product_lane(
            AsyncMock(), AsyncMock(), gate_gateway=object(), gate_prompt_repository=object()
        )
    rank.assert_not_awaited()
    generate.assert_not_awaited()
    assert report.stories_evaluated == 0


@pytest.mark.asyncio
async def test_master_on_preserves_existing_news_lane_reachability(monkeypatch) -> None:
    monkeypatch.setattr(settings, "instagram_automatic_generation_enabled", True)
    @asynccontextmanager
    async def session_factory():
        yield object()

    with patch.object(
        cc, "_classify_event_for_router_treatment", new=AsyncMock(side_effect=RuntimeError("reached"))
    ) as classify:
        report = await cc._run_instagram_automatic_trigger(
            session_factory, AsyncMock(), [object()], gate_gateway=object(), gate_prompt_repository=object()
        )
    classify.assert_awaited_once()
    assert report.stories_evaluated == 0


def test_master_switch_safe_default_and_no_migration() -> None:
    assert settings.instagram_automatic_generation_enabled is False
    migration_text = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("database/migrations/versions").glob("*.py")
    )
    assert "instagram_automatic_generation_enabled" not in migration_text
