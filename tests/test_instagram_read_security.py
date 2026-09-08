"""DIRECTOR-CONTROL-PLANE-1C §24: the Instagram access token must never appear in a Director
prompt, a DirectorRun row, a PlatformAccountContext serialization, `/accounts` output, a log line,
or an exception - and must never be persisted in DB plaintext.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from bot.accounts_formatting import render_accounts_status, render_instagram_connection_report
from core.config import settings
from database.models.instagram_account import InstagramAccount
from services.instagram_connection_service import (
    build_instagram_director_feed_inputs,
    run_instagram_connection_check,
    sync_instagram_feed_context,
)
from services.platform_account_context import build_instagram_account_context, build_telegram_account_context

_TOKEN = "LL-super-secret-token-DO-NOT-LEAK-42"
_IG_ID = "17841400000000000"


@pytest.fixture
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "instagram_access_token", SecretStr(_TOKEN))
    monkeypatch.setattr(settings, "instagram_business_account_id", _IG_ID)
    monkeypatch.setattr(settings, "instagram_expected_username", "ninjapulse")


def _profile_body() -> dict:
    return {
        "id": _IG_ID, "username": "ninjapulse", "name": "NINJA PULSE", "account_type": "BUSINESS",
        "biography": "AI news", "profile_picture_url": "https://cdn.example/pp.jpg",
        "followers_count": 10, "follows_count": 2, "media_count": 1,
    }


def _handler(req: httpx.Request) -> httpx.Response:
    if "/insights" in req.url.path:
        return httpx.Response(200, json={"data": [{"name": "reach", "total_value": {"value": 1}}, {"name": "profile_views", "total_value": {"value": 1}}]})
    if "/media" in req.url.path:
        return httpx.Response(200, json={"data": [{
            "id": "p1", "media_type": "IMAGE", "media_product_type": "FEED", "caption": "c",
            "timestamp": "2026-09-01T10:00:00+0000", "permalink": "https://instagram.com/p/p1",
            "like_count": 1, "comments_count": 0,
        }]})
    return httpx.Response(200, json=_profile_body())


def _transport() -> httpx.MockTransport:
    return httpx.MockTransport(_handler)


@pytest.mark.asyncio
async def test_token_never_in_connection_report_or_accounts_ui(db_session: AsyncSession, _configured: None) -> None:
    report = await run_instagram_connection_check(db_session, transport=_transport())
    assert _TOKEN not in str(report)
    assert _TOKEN not in str(asdict(report))
    assert _TOKEN not in render_instagram_connection_report(report)

    tg = await build_telegram_account_context(db_session, now=datetime.now(timezone.utc))
    ig = await build_instagram_account_context(db_session, now=datetime.now(timezone.utc))
    accounts_text = render_accounts_status(tg, ig)
    assert _TOKEN not in accounts_text


@pytest.mark.asyncio
async def test_token_never_in_platform_account_context_serialization(db_session: AsyncSession, _configured: None) -> None:
    await run_instagram_connection_check(db_session, transport=_transport())
    ctx = await build_instagram_account_context(db_session, now=datetime.now(timezone.utc))
    # every common serialization form
    assert _TOKEN not in str(ctx)
    assert _TOKEN not in repr(ctx)
    assert _TOKEN not in str(asdict(ctx))


@pytest.mark.asyncio
async def test_token_never_persisted_in_db_plaintext(db_session: AsyncSession, _configured: None) -> None:
    await run_instagram_connection_check(db_session, transport=_transport())
    await db_session.flush()
    row = (await db_session.execute(_all_instagram_accounts())).scalars().one()
    dumped = {c.name: getattr(row, c.name) for c in InstagramAccount.__table__.columns}
    assert _TOKEN not in str(dumped)
    # structural: there is no column whose name suggests it could hold a secret
    for col in InstagramAccount.__table__.columns:
        assert "access_token" not in col.name or col.name in ("access_token_status", "access_token_expires_at")
        assert "app_secret" not in col.name
        assert "client_secret" not in col.name


@pytest.mark.asyncio
async def test_token_never_in_director_feed_inputs_or_creative_note(db_session: AsyncSession, _configured: None) -> None:
    inputs = await build_instagram_director_feed_inputs(db_session, transport=_transport())
    assert _TOKEN not in str(inputs)
    assert _TOKEN not in inputs.creative_feed_note
    sync = await sync_instagram_feed_context(db_session, transport=_transport())
    assert _TOKEN not in str(sync.feed_context)
    assert _TOKEN not in str(sync.profile)


@pytest.mark.asyncio
async def test_token_never_in_logs(db_session: AsyncSession, _configured: None, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    await run_instagram_connection_check(db_session, transport=_transport())
    await sync_instagram_feed_context(db_session, transport=_transport())
    await build_instagram_director_feed_inputs(db_session, transport=_transport())
    assert _TOKEN not in caplog.text


@pytest.mark.asyncio
async def test_token_never_in_exception_on_failure(db_session: AsyncSession, _configured: None) -> None:
    def failing(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"code": 190, "message": f"the token {_TOKEN} is invalid"}})

    # run_instagram_connection_check catches everything -> ERROR report, no exception, no token
    report = await run_instagram_connection_check(db_session, transport=httpx.MockTransport(failing))
    assert _TOKEN not in str(report)
    assert _TOKEN not in str(report.error_detail or "")
    row = (await db_session.execute(_all_instagram_accounts())).scalars().one()
    assert _TOKEN not in str(row.last_read_error or "")


def _all_instagram_accounts():
    from sqlalchemy import select

    return select(InstagramAccount)
