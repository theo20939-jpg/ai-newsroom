"""DIRECTOR-CONTROL-PLANE-1C §22/§23: prove a mocked official Instagram API response flows through
REAL orchestration into all three Instagram Directors - the Growth Strategist (also via the live
`run_instagram_growth_strategist` execution path), the Format Director, and the Creative Director.

httpx.MockTransport only - no real credential, no real network (the conftest egress guard also
enforces this). The `_patch_httpx_client` seam (mirrors tests/test_github_source.py's own
established pattern) lets the un-parameterised `run_instagram_growth_strategist` reach the mock.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from services.director_execution_service import run_instagram_growth_strategist
from services.instagram_connection_readiness import InstagramReadinessState
from services.instagram_connection_service import build_instagram_director_feed_inputs
from services.instagram_creative_director import CreativeDirectorInput
from services.instagram_format_director import evaluate_format_shadow
from services.instagram_growth_strategist import generate_growth_strategy
from services.instagram_objectives import ContentObjective

_IG_ID = "17841400000000000"


@pytest.fixture
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "instagram_access_token", SecretStr("LL-integration-token"))
    monkeypatch.setattr(settings, "instagram_business_account_id", _IG_ID)
    monkeypatch.setattr(settings, "instagram_expected_username", "ninjapulse")


def _profile_body(**overrides: object) -> dict:
    body = {
        "id": _IG_ID, "username": "ninjapulse", "name": "NINJA PULSE", "account_type": "BUSINESS",
        "biography": "AI news, fast.", "profile_picture_url": "https://cdn.example/pp.jpg",
        "followers_count": 130, "follows_count": 4, "media_count": 5,
    }
    body.update(overrides)
    return body


def _reels_heavy_feed() -> list[dict]:
    rows = []
    for i in range(4):
        rows.append({
            "id": f"r{i}", "media_type": "VIDEO", "media_product_type": "REELS",
            "caption": f"reel {i}", "timestamp": f"2026-09-0{i + 1}T09:00:00+0000",
            "permalink": f"https://instagram.com/reel/r{i}", "like_count": 30, "comments_count": 4,
        })
    rows.append({
        "id": "p0", "media_type": "IMAGE", "media_product_type": "FEED", "caption": "an image",
        "timestamp": "2026-09-05T09:00:00+0000", "permalink": "https://instagram.com/p/p0",
        "like_count": 20, "comments_count": 2,
    })
    return rows


def _mock_handler(*, feed: list[dict], profile: dict | None = None):
    def handler(req: httpx.Request) -> httpx.Response:
        if "/media" in req.url.path:
            return httpx.Response(200, json={"data": feed})
        if "/insights" in req.url.path:
            return httpx.Response(200, json={"data": [
                {"name": "reach", "total_value": {"value": 200}},
                {"name": "profile_views", "total_value": {"value": 9}},
            ]})
        return httpx.Response(200, json=profile or _profile_body())
    return handler


def _patch_httpx_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self: httpx.AsyncClient, *args, **kwargs) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


# --------------------------------------------------------------------------------------------------
# §22 - the same normalized feed context reaches all three Directors
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mocked_api_feed_reaches_growth_format_and_creative_directors(
    db_session: AsyncSession, _configured: None,
) -> None:
    inputs = await build_instagram_director_feed_inputs(
        db_session, now=datetime(2026, 9, 8, tzinfo=timezone.utc),
        transport=httpx.MockTransport(_mock_handler(feed=_reels_heavy_feed())),
    )
    assert inputs.readiness_state is InstagramReadinessState.CONNECTED
    assert len(inputs.feed_context.posts) == 5
    assert inputs.feed_context.media_type_distribution.get("REEL") == 4

    # --- Growth Strategist: receives the real feed_context --------------------------------------
    strategy = generate_growth_strategy(opportunity_contexts=[], feed_context=inputs.feed_context)
    assert any("real Instagram feed context" in note for note in strategy.content_gaps)

    # --- Format Director: receives the same real feed_context; flags the Reels domination ------
    decision = evaluate_format_shadow(
        objective=ContentObjective.SAVES, has_video_asset=False, has_multi_step_narrative=True,
        feed_context=inputs.feed_context,
    )
    assert any("dominated by media_type='REEL'" in w for w in decision.warnings)

    # --- Creative Director: receives the derived, token-free note ------------------------------
    creative_input = CreativeDirectorInput(
        objective="saves", format="carousel", opportunity_summary="x",
        feed_context_note=inputs.creative_feed_note,
    )
    assert "@ninjapulse" in creative_input.feed_context_note
    assert "5 recent posts" in creative_input.feed_context_note
    assert "LL-integration-token" not in creative_input.feed_context_note


@pytest.mark.asyncio
async def test_run_instagram_growth_strategist_uses_the_real_reader_end_to_end(
    db_session: AsyncSession, _configured: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live execution path (services/director_execution_service.py::run_instagram_growth_
    strategist) - not a signature test - pulls the real feed through the official reader."""
    _patch_httpx_client(monkeypatch, _mock_handler(feed=_reels_heavy_feed()))

    result = await run_instagram_growth_strategist(db_session, now=datetime(2026, 9, 8, tzinfo=timezone.utc))
    assert any("real Instagram feed context" in note for note in result.strategy.content_gaps)


@pytest.mark.asyncio
async def test_not_configured_live_path_still_produces_an_honest_strategy(
    db_session: AsyncSession,
) -> None:
    """No credentials -> the live path still runs, with an honestly-empty prelaunch feed context."""
    result = await run_instagram_growth_strategist(db_session, now=datetime(2026, 9, 8, tzinfo=timezone.utc))
    assert any("readiness=NOT_CONFIGURED" in note for note in result.strategy.content_gaps)


@pytest.mark.asyncio
async def test_empty_connected_account_gives_cold_start_reasoning_not_invented_performance(
    db_session: AsyncSession, _configured: None,
) -> None:
    """§23: CONNECTED + 0 posts -> feed=[], baseline NONE, PRE_LAUNCH reasoning, nothing invented."""
    inputs = await build_instagram_director_feed_inputs(
        db_session,
        transport=httpx.MockTransport(_mock_handler(feed=[], profile=_profile_body(media_count=0, followers_count=0))),
    )
    assert inputs.readiness_state is InstagramReadinessState.CONNECTED
    assert inputs.feed_context.posts == []
    assert inputs.feed_context.learning_eligible_posts == []
    assert "0 publications" in inputs.creative_feed_note

    strategy = generate_growth_strategy(opportunity_contexts=[], feed_context=inputs.feed_context)
    # A CONNECTED-but-empty feed adds NO fabricated performance note - the honest absence of
    # evidence, exactly as §23 requires.
    assert not any("performance" in note.lower() and "%" in note for note in strategy.content_gaps)
