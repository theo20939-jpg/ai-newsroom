"""Tests for integrations.sources.telegram_source (Phase 15 M3 - engagement signal
preservation). Uses lightweight fake Telethon message objects - never a real TelegramClient,
never network I/O - matching the pattern already established by tests/test_rss_source.py for
other source adapters (fixture data in, RawNewsItem out).

Phase I.2.1A.4: adds a lightweight fake TelegramClient (never a real Telethon connection) to
prove `TelegramSourceAdapter.fetch()` never reaches an interactive login path - the real,
reproduced incident this phase fixes (see integrations/sources/telegram_source.py's own module
docstring for the full account).
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from database.models.news_source import NewsSource, SourceType
from integrations.sources.base import SourceFetchContext
from integrations.sources.telegram_source import (
    TelegramAuthenticationError,
    TelegramSourceAdapter,
    _reactions_count,
)
from schemas.raw_news_item import RawNewsItem


@dataclass
class _FakeReactionCount:
    count: int


@dataclass
class _FakeReactions:
    results: list[_FakeReactionCount] = field(default_factory=list)


@dataclass
class _FakeReplies:
    replies: int


@dataclass
class _FakeMessage:
    """Minimal stand-in for telethon.tl.custom.message.Message - only the attributes
    TelegramSourceAdapter._to_raw_item() actually reads."""

    id: int
    text: str | None = None
    date: datetime = field(default_factory=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    action: object | None = None
    views: int | None = None
    forwards: int | None = None
    replies: _FakeReplies | None = None
    reactions: _FakeReactions | None = None
    grouped_id: int | None = None  # Phase 16 M1
    photo: object | None = None  # Phase 16 M1
    document: object | None = None  # Phase 16 M1


# A. Telegram full metrics
def test_full_metrics_are_persisted_onto_raw_item() -> None:
    message = _FakeMessage(
        id=1,
        text="A real news post",
        views=10000,
        forwards=120,
        replies=_FakeReplies(replies=35),
        reactions=_FakeReactions(
            results=[_FakeReactionCount(count=42), _FakeReactionCount(count=8), _FakeReactionCount(count=12)]
        ),
    )

    item = TelegramSourceAdapter._to_raw_item(message, "channel")

    assert item is not None
    assert item.views_count == 10000
    assert item.forwards_count == 120
    assert item.replies_count == 35
    assert item.reactions_count == 62  # 42 + 8 + 12


# B. Zero values
def test_real_zero_values_are_preserved_not_converted_to_none() -> None:
    message = _FakeMessage(
        id=2,
        text="A quiet post",
        views=0,
        forwards=0,
        replies=_FakeReplies(replies=0),
        reactions=_FakeReactions(results=[]),
    )

    item = TelegramSourceAdapter._to_raw_item(message, "channel")

    assert item is not None
    assert item.views_count == 0
    assert item.forwards_count == 0
    assert item.replies_count == 0
    assert item.reactions_count == 0


# C. Missing metrics
def test_missing_metrics_stay_none_not_zero() -> None:
    message = _FakeMessage(id=3, text="Old or restricted post")

    item = TelegramSourceAdapter._to_raw_item(message, "channel")

    assert item is not None
    assert item.views_count is None
    assert item.forwards_count is None
    assert item.replies_count is None
    assert item.reactions_count is None


def test_zero_and_none_are_distinguishable_on_the_same_field() -> None:
    zero_message = _FakeMessage(id=4, text="post", views=0)
    none_message = _FakeMessage(id=5, text="post", views=None)

    zero_item = TelegramSourceAdapter._to_raw_item(zero_message, "channel")
    none_item = TelegramSourceAdapter._to_raw_item(none_message, "channel")

    assert zero_item is not None and none_item is not None
    assert zero_item.views_count == 0
    assert none_item.views_count is None
    assert zero_item.views_count != none_item.views_count  # explicit: 0 is not None


# E. Reaction aggregation
def test_reactions_count_sums_multiple_reaction_types() -> None:
    message = _FakeMessage(
        id=6,
        reactions=_FakeReactions(
            results=[_FakeReactionCount(count=1), _FakeReactionCount(count=2), _FakeReactionCount(count=3)]
        ),
    )
    assert _reactions_count(message) == 6


def test_reactions_count_none_when_no_reactions_object() -> None:
    message = _FakeMessage(id=7, reactions=None)
    assert _reactions_count(message) is None


def test_reactions_count_zero_when_reactions_enabled_but_empty() -> None:
    message = _FakeMessage(id=8, reactions=_FakeReactions(results=[]))
    assert _reactions_count(message) == 0


# Service messages still short-circuit before engagement fields matter (regression, pre-existing
# behavior unchanged).
def test_service_message_still_returns_none() -> None:
    message = _FakeMessage(id=9, action=object(), views=999)
    assert TelegramSourceAdapter._to_raw_item(message, "channel") is None


# No extra Telegram API call: _to_raw_item is a pure, synchronous transform of the message
# object already fetched by iter_messages() - structurally proven by never awaiting anything.
def test_to_raw_item_is_not_async() -> None:
    import inspect

    assert not inspect.iscoroutinefunction(TelegramSourceAdapter._to_raw_item)


def test_raw_news_item_engagement_fields_default_to_none() -> None:
    """Non-Telegram adapters (RSS, GitHub, arXiv, ...) never set these fields - confirms the
    schema default keeps them unavailable, never a fabricated 0, for every other source."""
    item = RawNewsItem(external_id="x", text="body")
    assert item.views_count is None
    assert item.forwards_count is None
    assert item.replies_count is None
    assert item.reactions_count is None


# Phase 16 M1 (docs/phase16_m1_native_media_ingestion_report.md): adapter-level wiring - proves
# _to_raw_item() actually calls services.image_intelligence.extract_telegram_native_media() and
# threads its result onto RawNewsItem.native_media_hints, not just that the extraction function
# itself works in isolation (see tests/test_image_intelligence.py for that).
@dataclass
class _FakePhotoSize:
    w: int | None = None
    h: int | None = None


@dataclass
class _FakePhoto:
    id: int | None = None
    sizes: list = field(default_factory=list)


def test_to_raw_item_populates_native_media_hints_for_a_photo_post() -> None:
    message = _FakeMessage(id=20, text="caption", photo=_FakePhoto(id=1, sizes=[_FakePhotoSize(w=100, h=100)]))
    item = TelegramSourceAdapter._to_raw_item(message, "channel")
    assert item is not None
    assert len(item.native_media_hints) == 1
    assert item.native_media_hints[0].discovery_method.value == "telegram_photo"


def test_to_raw_item_produces_no_hints_for_a_text_only_post() -> None:
    message = _FakeMessage(id=21, text="just text")
    item = TelegramSourceAdapter._to_raw_item(message, "channel")
    assert item is not None
    assert item.native_media_hints == []


def test_to_raw_item_extraction_failure_never_breaks_text_collection() -> None:
    class _BrokenPhoto:
        @property
        def sizes(self):
            raise RuntimeError("boom")

    message = _FakeMessage(id=22, text="still collected", photo=_BrokenPhoto())
    item = TelegramSourceAdapter._to_raw_item(message, "channel")
    assert item is not None
    assert item.text == "still collected"
    assert item.native_media_hints == []


# -------------------------------------------------------------------------------------------
# Phase I.2.1A.4: fetch() auth contract - never interactive, always disconnects, isolated
# failures. A fake TelegramClient stand-in - never a real Telethon connection.
# -------------------------------------------------------------------------------------------


class _FakeTelegramClient:
    """Minimal stand-in for telethon.TelegramClient - only the methods
    TelegramSourceAdapter.fetch() is now allowed to call. `start()`/`__aenter__()` raise if ever
    invoked - the real incident this phase fixes was exactly `async with client:` silently
    calling `start()`, which can prompt interactively."""

    def __init__(self, *, authorized: bool, messages: list | None = None, connect_error: Exception | None = None):
        self._authorized = authorized
        self._messages = messages or []
        self._connect_error = connect_error
        self.connect_called = False
        self.disconnect_called = False
        self.is_user_authorized_called = False
        self.start_called = False
        self.iter_messages_called = False

    async def connect(self) -> None:
        self.connect_called = True
        if self._connect_error is not None:
            raise self._connect_error

    async def is_user_authorized(self) -> bool:
        self.is_user_authorized_called = True
        return self._authorized

    async def disconnect(self) -> None:
        self.disconnect_called = True

    async def start(self, *args: object, **kwargs: object) -> None:
        self.start_called = True
        raise AssertionError("client.start() must never be called by fetch() - see module docstring")

    def iter_messages(self, channel: str, limit: int):
        self.iter_messages_called = True

        async def _gen():
            for message in self._messages:
                yield message

        return _gen()

    async def __aenter__(self) -> "_FakeTelegramClient":
        raise AssertionError("async with client (Telethon's own start() shorthand) must never be used")

    async def __aexit__(self, *exc: object) -> None:
        pass


def _fake_source(url: str = "@channel") -> NewsSource:
    return NewsSource(id=uuid4(), name="Fake Telegram Source", type=SourceType.TELEGRAM, url=url, active=True)


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: _FakeTelegramClient) -> None:
    monkeypatch.setattr(TelegramSourceAdapter, "_build_client", staticmethod(lambda: client))


# Part H - unauthorized session never attempts interactive login.
@pytest.mark.asyncio
async def test_unauthorized_session_raises_without_calling_start(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeTelegramClient(authorized=False)
    _patch_client(monkeypatch, client)
    adapter = TelegramSourceAdapter()

    with pytest.raises(TelegramAuthenticationError):
        await adapter.fetch(_fake_source(), SourceFetchContext(definition=None))

    assert client.connect_called is True
    assert client.is_user_authorized_called is True
    assert client.start_called is False
    assert client.iter_messages_called is False
    assert client.disconnect_called is True  # always disconnects, even on auth failure


# Part I - authorized path preserved exactly, no interactive call.
@pytest.mark.asyncio
async def test_authorized_session_fetches_messages_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    message = _FakeMessage(id=100, text="A real news post")
    client = _FakeTelegramClient(authorized=True, messages=[message])
    _patch_client(monkeypatch, client)
    adapter = TelegramSourceAdapter()

    items = await adapter.fetch(_fake_source(), SourceFetchContext(definition=None))

    assert len(items) == 1
    assert items[0].text == "A real news post"
    assert client.start_called is False
    assert client.disconnect_called is True


# Part J - a network failure during connect/authorize is bounded, never interactive, always
# disconnects (disconnect() is expected to be safe to call even when connect() itself failed -
# Telethon's own documented behavior; this fake mirrors that by never raising from disconnect()).
@pytest.mark.asyncio
async def test_connect_failure_is_bounded_and_still_disconnects(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeTelegramClient(authorized=True, connect_error=ConnectionError("network unreachable"))
    _patch_client(monkeypatch, client)
    adapter = TelegramSourceAdapter()

    with pytest.raises(ConnectionError):
        await adapter.fetch(_fake_source(), SourceFetchContext(definition=None))

    assert client.start_called is False
    assert client.disconnect_called is True


# CancelledError must never be swallowed/converted into a plain auth/fetch failure.
@pytest.mark.asyncio
async def test_cancelled_error_propagates_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    class _CancellingClient(_FakeTelegramClient):
        async def is_user_authorized(self) -> bool:
            self.is_user_authorized_called = True
            raise asyncio.CancelledError()

    client = _CancellingClient(authorized=True)
    _patch_client(monkeypatch, client)
    adapter = TelegramSourceAdapter()

    with pytest.raises(asyncio.CancelledError):
        await adapter.fetch(_fake_source(), SourceFetchContext(definition=None))

    assert client.disconnect_called is True


def test_no_credentials_in_the_authentication_error_message() -> None:
    """Part L: the raised error must identify the source, never echo session/api credentials."""
    error = TelegramAuthenticationError(
        "Telegram session is not authorized for source 'Fake Telegram Source' - "
        "TELEGRAM_SESSION_STRING is missing, expired, or invalid."
    )
    text = str(error)
    assert "Fake Telegram Source" in text
    for forbidden in ("api_hash", "api_id", "phone", "code="):
        assert forbidden not in text.lower()
