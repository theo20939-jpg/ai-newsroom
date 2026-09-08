"""DIRECTOR-CONTROL-PLANE-1C §8/§9/§18/§20/§23: the connection/sync orchestration - real Postgres
(the owned-account row is persisted), mocked provider (httpx.MockTransport), never a real token.
"""
from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.instagram_account import InstagramAccount, InstagramConnectionState
from services.instagram_account_registry import get_owned_brand_account
from services.instagram_connection_readiness import InstagramReadinessState
from services.instagram_connection_service import (
    build_instagram_director_feed_inputs,
    sync_instagram_feed_context,
    run_instagram_connection_check,
)

_IG_ID = "17841400000000000"


@pytest.fixture
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "instagram_access_token", SecretStr("LL-conn-test-token"))
    monkeypatch.setattr(settings, "instagram_business_account_id", _IG_ID)
    monkeypatch.setattr(settings, "instagram_expected_username", "ninjapulse")


def _profile_body(**overrides: object) -> dict:
    body = {
        "id": _IG_ID, "username": "ninjapulse", "name": "NINJA PULSE", "account_type": "BUSINESS",
        "biography": "AI news, fast.", "profile_picture_url": "https://cdn.example/pp.jpg",
        "followers_count": 0, "follows_count": 2, "media_count": 0,
    }
    body.update(overrides)
    return body


def _media_row(mid: str, mtype: str, product: str = "FEED", ts: str = "2026-09-01T10:00:00+0000") -> dict:
    return {
        "id": mid, "media_type": mtype, "media_product_type": product, "caption": f"c{mid}",
        "timestamp": ts, "permalink": f"https://instagram.com/p/{mid}", "like_count": 5, "comments_count": 1,
    }


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


# --------------------------------------------------------------------------------------------------
# run_instagram_connection_check - §20
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_not_configured_returns_not_configured_and_persists_nothing(db_session: AsyncSession) -> None:
    report = await run_instagram_connection_check(db_session)
    assert report.readiness_state is InstagramReadinessState.NOT_CONFIGURED
    assert report.connected is False
    assert report.persisted is False
    assert (await get_owned_brand_account(db_session)) is None  # no row created


@pytest.mark.asyncio
async def test_connected_persists_only_non_secret_metadata(db_session: AsyncSession, _configured: None) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/insights" in req.url.path:
            return httpx.Response(200, json={"data": [{"name": "reach", "total_value": {"value": 3}}, {"name": "profile_views", "total_value": {"value": 1}}]})
        return httpx.Response(200, json=_profile_body(followers_count=42, media_count=0))

    report = await run_instagram_connection_check(db_session, transport=_transport(handler))
    assert report.readiness_state is InstagramReadinessState.CONNECTED
    assert report.connected is True
    assert report.username == "ninjapulse"
    assert report.capabilities == {"read_profile": "AVAILABLE", "read_media": "AVAILABLE", "read_insights": "AVAILABLE"}

    row = await get_owned_brand_account(db_session)
    assert row is not None
    assert row.connection_state is InstagramConnectionState.CONNECTED
    assert row.ig_user_id == _IG_ID
    assert row.username == "ninjapulse"
    assert row.biography == "AI news, fast."
    assert row.followers_count == 42
    assert row.last_successful_read_at is not None
    assert row.last_read_error is None
    assert row.capabilities == {"read_profile": "AVAILABLE", "read_media": "AVAILABLE", "read_insights": "AVAILABLE"}
    # §24: absolutely no token/secret column exists or is written
    assert not any("token" in c.name and "secret" in c.name for c in InstagramAccount.__table__.columns)
    dumped = {c.name: getattr(row, c.name) for c in InstagramAccount.__table__.columns}
    assert "LL-conn-test-token" not in str(dumped)


@pytest.mark.asyncio
async def test_invalid_token_persists_error_state(db_session: AsyncSession, _configured: None) -> None:
    report = await run_instagram_connection_check(
        db_session, transport=_transport(lambda req: httpx.Response(401, json={"error": {"code": 190}})),
    )
    assert report.readiness_state is InstagramReadinessState.ERROR
    row = await get_owned_brand_account(db_session)
    assert row is not None and row.connection_state is InstagramConnectionState.ERROR
    assert row.last_read_error and "invalid_token" in row.last_read_error


@pytest.mark.asyncio
async def test_identity_mismatch_never_adopts_the_wrong_identity(db_session: AsyncSession, _configured: None) -> None:
    wrong = _profile_body(id="17999999999999999", username="not_us")
    report = await run_instagram_connection_check(db_session, transport=_transport(lambda req: httpx.Response(200, json=wrong)))
    assert report.readiness_state is InstagramReadinessState.ERROR
    assert report.outcome == "IDENTITY_MISMATCH"
    row = await get_owned_brand_account(db_session)
    assert row is not None
    assert row.connection_state is InstagramConnectionState.ERROR
    assert row.ig_user_id != "17999999999999999"  # the wrong id was NOT persisted
    assert row.ig_user_id is None
    assert row.last_read_error and row.last_read_error.startswith("identity_mismatch")


@pytest.mark.asyncio
async def test_connection_test_api_call_budget_is_bounded(db_session: AsyncSession, _configured: None) -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if "/insights" in req.url.path:
            return httpx.Response(200, json={"data": [{"name": "reach", "total_value": {"value": 1}}, {"name": "profile_views", "total_value": {"value": 1}}]})
        return httpx.Response(200, json=_profile_body())

    report = await run_instagram_connection_check(db_session, transport=_transport(handler))
    assert report.api_calls == 2  # profile + insights probe, never more
    assert calls["n"] == 2


# --------------------------------------------------------------------------------------------------
# sync_instagram_feed_context - §10/§15/§18
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_not_configured_is_honest_empty_context(db_session: AsyncSession) -> None:
    result = await sync_instagram_feed_context(db_session)
    assert result.feed_context.posts == []
    assert result.feed_context.readiness_state is InstagramReadinessState.NOT_CONFIGURED
    assert result.profile is None
    assert result.api_calls == 0


@pytest.mark.asyncio
async def test_sync_connected_with_real_media_builds_a_real_context(db_session: AsyncSession, _configured: None) -> None:
    rows = [_media_row("p1", "IMAGE"), _media_row("r1", "VIDEO", product="REELS"), _media_row("c1", "CAROUSEL_ALBUM")]

    def handler(req: httpx.Request) -> httpx.Response:
        if "/media" in req.url.path:
            return httpx.Response(200, json={"data": rows})
        return httpx.Response(200, json=_profile_body(media_count=3))

    result = await sync_instagram_feed_context(db_session, transport=_transport(handler))
    assert result.readiness_state is InstagramReadinessState.CONNECTED
    assert len(result.feed_context.posts) == 3
    assert result.feed_context.media_type_distribution == {"IMAGE": 1, "REEL": 1, "CAROUSEL_ALBUM": 1}
    assert result.profile is not None and result.profile.username == "ninjapulse"
    assert result.api_calls == 2  # profile + media list


@pytest.mark.asyncio
async def test_sync_fetch_failure_degrades_to_empty_context_never_crashes(db_session: AsyncSession, _configured: None) -> None:
    result = await sync_instagram_feed_context(
        db_session, transport=_transport(lambda req: httpx.Response(500, text="down")),
    )
    assert result.feed_context.posts == []
    assert result.readiness_state is InstagramReadinessState.ERROR
    assert result.error_code in ("transient", "network", "malformed_payload")


@pytest.mark.asyncio
async def test_empty_connected_account_is_a_valid_prelaunch_state(db_session: AsyncSession, _configured: None) -> None:
    """§23: CONNECTED account + 0 publications -> feed=[], baseline NONE, not an error."""
    def handler(req: httpx.Request) -> httpx.Response:
        if "/media" in req.url.path:
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, json=_profile_body(media_count=0))

    result = await sync_instagram_feed_context(db_session, transport=_transport(handler))
    assert result.readiness_state is InstagramReadinessState.CONNECTED
    assert result.feed_context.posts == []
    assert result.feed_context.learning_eligible_posts == []


# --------------------------------------------------------------------------------------------------
# build_instagram_director_feed_inputs - §11
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_director_feed_inputs_empty_account_note_is_cold_start(db_session: AsyncSession, _configured: None) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/media" in req.url.path:
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, json=_profile_body(media_count=0))

    inputs = await build_instagram_director_feed_inputs(db_session, transport=_transport(handler))
    assert inputs.readiness_state is InstagramReadinessState.CONNECTED
    assert inputs.feed_context.posts == []
    assert "0 publications" in inputs.creative_feed_note or "cold start" in inputs.creative_feed_note.lower()


@pytest.mark.asyncio
async def test_director_feed_inputs_not_configured_note_is_honest(db_session: AsyncSession) -> None:
    inputs = await build_instagram_director_feed_inputs(db_session)
    assert inputs.readiness_state is InstagramReadinessState.NOT_CONFIGURED
    assert "no first-party Instagram feed evidence" in inputs.creative_feed_note
