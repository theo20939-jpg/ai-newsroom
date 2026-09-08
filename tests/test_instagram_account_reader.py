"""DIRECTOR-CONTROL-PLANE-1C §21: mocked-provider tests for the official read-only Instagram
adapter. Uses httpx.MockTransport - never a real credential, never a real network call (the
conftest egress guard additionally enforces this).
"""
from __future__ import annotations

import json
import logging

import httpx
import pytest
from pydantic import SecretStr

from core.config import settings
from services.instagram_account_reader import (
    DEFAULT_MEDIA_LIMIT,
    MAX_MEDIA_LIMIT,
    ConnectionOutcome,
    InstagramAccountReader,
    InstagramCapability,
    InstagramReaderConfig,
    InstagramReadError,
    InstagramReadErrorCode,
    is_configured,
    media_to_feed_context_row,
)

_IG_ID = "17841400000000000"


@pytest.fixture
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "instagram_access_token", SecretStr("LL-test-token-never-real"))
    monkeypatch.setattr(settings, "instagram_business_account_id", _IG_ID)
    monkeypatch.setattr(settings, "instagram_expected_username", "ninjapulse")


def _reader(handler, *, config: InstagramReaderConfig | None = None) -> InstagramAccountReader:
    cfg = config or InstagramReaderConfig.from_settings()
    assert cfg is not None
    return InstagramAccountReader(cfg, transport=httpx.MockTransport(handler))


def _profile_body(**overrides: object) -> dict:
    body = {
        "id": _IG_ID, "username": "ninjapulse", "name": "NINJA PULSE", "account_type": "BUSINESS",
        "biography": "AI news, fast.", "profile_picture_url": "https://cdn.example/pp.jpg",
        "followers_count": 0, "follows_count": 3, "media_count": 0,
    }
    body.update(overrides)
    return body


# --------------------------------------------------------------------------------------------------
# config gate
# --------------------------------------------------------------------------------------------------


def test_not_configured_when_secrets_absent() -> None:
    assert is_configured() is False
    assert InstagramReaderConfig.from_settings() is None


def test_configured_only_when_both_token_and_id_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "instagram_access_token", SecretStr("x"))
    assert is_configured() is False  # id still missing
    monkeypatch.setattr(settings, "instagram_business_account_id", _IG_ID)
    assert is_configured() is True


# --------------------------------------------------------------------------------------------------
# profile / connection
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_read_success_normalizes_every_field(_configured: None) -> None:
    reader = _reader(lambda req: httpx.Response(200, json=_profile_body(followers_count=1200, media_count=8)))
    profile = await reader.fetch_account_context()
    assert profile.ig_user_id == _IG_ID
    assert profile.username == "ninjapulse"
    assert profile.account_type == "BUSINESS"
    assert profile.biography == "AI news, fast."
    assert profile.followers_count == 1200
    assert profile.media_count == 8


@pytest.mark.asyncio
async def test_valid_professional_account_check_connection_is_connected(_configured: None) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/insights" in req.url.path:
            return httpx.Response(200, json={"data": [
                {"name": "reach", "total_value": {"value": 10}},
                {"name": "profile_views", "total_value": {"value": 4}},
            ]})
        return httpx.Response(200, json=_profile_body())

    result = await _reader(handler).check_connection()
    assert result.outcome is ConnectionOutcome.CONNECTED
    assert result.profile is not None and result.profile.username == "ninjapulse"
    assert result.capabilities.read_profile is InstagramCapability.AVAILABLE
    assert result.capabilities.read_media is InstagramCapability.AVAILABLE
    assert result.capabilities.read_insights is InstagramCapability.AVAILABLE


@pytest.mark.asyncio
async def test_missing_config_check_connection_is_not_configured() -> None:
    assert InstagramReaderConfig.from_settings() is None  # nothing configured


@pytest.mark.asyncio
async def test_invalid_token_is_error(_configured: None) -> None:
    body = {"error": {"message": "Invalid OAuth access token.", "type": "OAuthException", "code": 190}}
    result = await _reader(lambda req: httpx.Response(401, json=body)).check_connection()
    assert result.outcome is ConnectionOutcome.ERROR
    assert result.error_code == InstagramReadErrorCode.INVALID_TOKEN.value


@pytest.mark.asyncio
async def test_wrong_account_identity_is_identity_mismatch(_configured: None) -> None:
    """§9: the returned account is a real professional account but NOT the configured one."""
    wrong = _profile_body(id="17999999999999999", username="someone_elses_account")
    result = await _reader(lambda req: httpx.Response(200, json=wrong)).check_connection()
    assert result.outcome is ConnectionOutcome.IDENTITY_MISMATCH
    assert "does not match" in (result.error_detail or "")


@pytest.mark.asyncio
async def test_wrong_username_same_id_is_identity_mismatch(_configured: None) -> None:
    result = await _reader(lambda req: httpx.Response(200, json=_profile_body(username="not_ninjapulse"))).check_connection()
    assert result.outcome is ConnectionOutcome.IDENTITY_MISMATCH


@pytest.mark.asyncio
async def test_insights_permission_missing_marks_read_insights_unavailable(_configured: None) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/insights" in req.url.path:
            return httpx.Response(403, json={"error": {"code": 10, "message": "requires manage_insights"}})
        return httpx.Response(200, json=_profile_body())

    result = await _reader(handler).check_connection()
    assert result.outcome is ConnectionOutcome.CONNECTED  # profile/media still work
    assert result.capabilities.read_insights is InstagramCapability.UNAVAILABLE


# --------------------------------------------------------------------------------------------------
# media
# --------------------------------------------------------------------------------------------------


def _media_row(media_id: str, media_type: str, product: str = "FEED", **extra: object) -> dict:
    row = {
        "id": media_id, "media_type": media_type, "media_product_type": product,
        "caption": f"caption {media_id}", "timestamp": "2026-09-01T10:00:00+0000",
        "permalink": f"https://instagram.com/p/{media_id}", "media_url": "https://cdn.example/m.jpg",
        "like_count": 12, "comments_count": 3,
    }
    row.update(extra)
    return row


@pytest.mark.asyncio
async def test_recent_media_covers_post_reel_and_carousel(_configured: None) -> None:
    rows = [
        _media_row("p1", "IMAGE"),
        _media_row("r1", "VIDEO", product="REELS"),
        _media_row("c1", "CAROUSEL_ALBUM"),
    ]
    media = await _reader(lambda req: httpx.Response(200, json={"data": rows})).fetch_recent_media()
    assert [m.media_id for m in media] == ["p1", "r1", "c1"]
    assert media[0].media_type == "IMAGE"
    assert media[1].media_product_type == "REELS"
    assert media[2].media_type == "CAROUSEL_ALBUM"
    # the coarse feed-context bucket surfaces Reels distinctly
    assert media_to_feed_context_row(media[1])["media_type"] == "REEL"
    assert media_to_feed_context_row(media[0])["media_type"] == "IMAGE"
    assert media_to_feed_context_row(media[2])["media_type"] == "CAROUSEL_ALBUM"


@pytest.mark.asyncio
async def test_pagination_is_bounded_and_never_loops(_configured: None) -> None:
    """A provider that always returns a next cursor must NOT cause an unbounded fetch."""
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        page = [_media_row(f"m{calls['n']}_{i}", "IMAGE") for i in range(25)]
        return httpx.Response(200, json={"data": page, "paging": {"cursors": {"after": f"cursor{calls['n']}"}}})

    media = await _reader(handler).fetch_recent_media(limit=MAX_MEDIA_LIMIT)
    assert len(media) == MAX_MEDIA_LIMIT  # capped
    assert calls["n"] <= 2  # at most 2 pages, then a hard stop - never an infinite loop


@pytest.mark.asyncio
async def test_media_limit_is_clamped_to_the_ceiling(_configured: None) -> None:
    rows = [_media_row(f"m{i}", "IMAGE") for i in range(50)]
    media = await _reader(lambda req: httpx.Response(200, json={"data": rows})).fetch_recent_media(limit=999)
    assert len(media) == MAX_MEDIA_LIMIT
    assert DEFAULT_MEDIA_LIMIT <= MAX_MEDIA_LIMIT


# --------------------------------------------------------------------------------------------------
# insights - available / partial / never fabricated
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_media_insights_available(_configured: None) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [
            {"name": "reach", "total_value": {"value": 500}},
            {"name": "likes", "total_value": {"value": 40}},
            {"name": "comments", "total_value": {"value": 5}},
            {"name": "saved", "total_value": {"value": 8}},
            {"name": "shares", "total_value": {"value": 2}},
            {"name": "total_interactions", "total_value": {"value": 55}},
            {"name": "views", "total_value": {"value": 900}},
        ]})

    result = await _reader(handler).fetch_media_insights(["p1"])
    assert result["p1"].status == "available"
    assert result["p1"].metrics["reach"] == 500.0


@pytest.mark.asyncio
async def test_media_insights_partial_when_provider_omits_some_metrics(_configured: None) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [
            {"name": "reach", "total_value": {"value": 100}},
            {"name": "likes", "total_value": {"value": 7}},
        ]})

    result = await _reader(handler).fetch_media_insights(["p1"])
    assert result["p1"].status == "partial"
    assert set(result["p1"].metrics) == {"reach", "likes"}
    # §3: the omitted metrics are ABSENT, never 0
    assert "saved" not in result["p1"].metrics
    assert "views" not in result["p1"].metrics


@pytest.mark.asyncio
async def test_unsupported_metric_is_never_fabricated(_configured: None) -> None:
    """The provider returns an entry with no usable value - it must not appear as 0."""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [
            {"name": "reach", "total_value": {"value": 12}},
            {"name": "ig_reels_avg_watch_time"},  # present in the list but no value at all
        ]})

    result = await _reader(handler).fetch_media_insights(["r1"])
    assert "ig_reels_avg_watch_time" not in result["r1"].metrics
    assert result["r1"].metrics == {"reach": 12.0}


@pytest.mark.asyncio
async def test_account_insights_permission_error_is_unavailable_not_zero(_configured: None) -> None:
    result = await _reader(
        lambda req: httpx.Response(403, json={"error": {"code": 10}})
    ).fetch_account_insights()
    assert result.status == "unavailable"
    assert result.metrics == {}


# --------------------------------------------------------------------------------------------------
# HTTP failure handling - §15
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limited_maps_to_rate_limited(_configured: None) -> None:
    with pytest.raises(InstagramReadError) as exc:
        await _reader(lambda req: httpx.Response(429, json={"error": {"code": 4}})).fetch_account_context()
    assert exc.value.code is InstagramReadErrorCode.RATE_LIMITED


@pytest.mark.asyncio
async def test_server_error_maps_to_transient(_configured: None) -> None:
    with pytest.raises(InstagramReadError) as exc:
        await _reader(lambda req: httpx.Response(503, text="upstream down")).fetch_account_context()
    assert exc.value.code is InstagramReadErrorCode.TRANSIENT


@pytest.mark.asyncio
async def test_timeout_maps_to_timeout(_configured: None) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(InstagramReadError) as exc:
        await _reader(handler).fetch_account_context()
    assert exc.value.code is InstagramReadErrorCode.TIMEOUT


@pytest.mark.asyncio
async def test_malformed_payload_maps_to_malformed(_configured: None) -> None:
    with pytest.raises(InstagramReadError) as exc:
        await _reader(lambda req: httpx.Response(200, text="<html>not json</html>")).fetch_account_context()
    assert exc.value.code is InstagramReadErrorCode.MALFORMED_PAYLOAD


@pytest.mark.asyncio
async def test_check_connection_never_raises_on_any_failure(_configured: None) -> None:
    for status in (401, 403, 404, 429, 500, 503):
        result = await _reader(lambda req, s=status: httpx.Response(s, json={"error": {"code": 1}})).check_connection()
        assert result.outcome is ConnectionOutcome.ERROR  # structured, never an exception


# --------------------------------------------------------------------------------------------------
# secret safety - §24
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_never_appears_in_logs_or_errors(_configured: None, caplog: pytest.LogCaptureFixture) -> None:
    token_value = "LL-test-token-never-real"
    caplog.set_level(logging.DEBUG)

    def handler(req: httpx.Request) -> httpx.Response:
        # the token IS sent to the provider - but ONLY in the Authorization header, never the URL,
        # so it can never leak through httpx's own request logging.
        assert token_value not in str(req.url)
        assert req.headers.get("Authorization") == f"Bearer {token_value}"
        return httpx.Response(401, json={"error": {"code": 190, "message": f"token {token_value} rejected"}})

    with pytest.raises(InstagramReadError) as exc:
        await _reader(handler).fetch_account_context()

    assert token_value not in str(exc.value)
    assert token_value not in repr(exc.value)
    assert token_value not in caplog.text


@pytest.mark.asyncio
async def test_provider_error_message_is_not_echoed(_configured: None) -> None:
    """The Meta error `message` can embed a signed URL / token - only the numeric code is kept."""
    secret_in_message = "https://scontent.cdninstagram.com/v/t51/SECRET_SIGNATURE?token=abc"
    body = {"error": {"code": 190, "message": secret_in_message}}
    with pytest.raises(InstagramReadError) as exc:
        await _reader(lambda req: httpx.Response(401, json=body)).fetch_account_context()
    assert "SECRET_SIGNATURE" not in str(exc.value)
    assert json.dumps(body["error"]["message"]) not in str(exc.value)
