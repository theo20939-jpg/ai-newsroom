from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from database.models.news_source import NewsSource, SourceType
from integrations.sources.base import SourceFetchContext
from integrations.sources.telegram_source import (
    TelegramAuthenticationError,
    TelegramSourceAdapter,
)
from services.adapter_registry import AdapterResolution
from services.collector import _process_source
from services.telegram_ingestion_checkpoint import (
    TelegramCheckpointError,
    TelegramCheckpointStore,
)

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


@dataclass
class _Message:
    id: int
    date: datetime = NOW
    text: str = "Telegram news item"
    action: object | None = None
    views: int | None = None
    forwards: int | None = None
    replies: object | None = None
    reactions: object | None = None
    grouped_id: int | None = None
    photo: object | None = None
    document: object | None = None


class _MemoryStore:
    def __init__(self) -> None:
        self.values: dict[uuid.UUID, int] = {}

    async def get(self, source_id: uuid.UUID) -> int | None:
        return self.values.get(source_id)

    async def initialize(self, source_id: uuid.UUID, head_message_id: int) -> int:
        return self.values.setdefault(source_id, head_message_id)

    async def advance(self, source_id: uuid.UUID, candidate_message_id: int) -> int:
        if source_id not in self.values:
            raise TelegramCheckpointError("absent")
        self.values[source_id] = max(self.values[source_id], candidate_message_id)
        return self.values[source_id]


class _Client:
    def __init__(self, messages: list[_Message], *, authorized: bool = True, failure: Exception | None = None):
        self.messages = messages
        self.authorized = authorized
        self.failure = failure
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def is_user_authorized(self) -> bool:
        return self.authorized

    async def iter_messages(self, channel: str, **kwargs: object):
        if self.failure is not None:
            raise self.failure
        minimum = int(kwargs.get("min_id", 0))
        limit = int(kwargs.get("limit", 50))
        reverse = bool(kwargs.get("reverse", False))
        candidates = [message for message in self.messages if message.id > minimum]
        candidates.sort(key=lambda message: message.id, reverse=not reverse)
        for message in candidates[:limit]:
            yield message


def _source(*, source_id: uuid.UUID | None = None, active: bool = True) -> NewsSource:
    return NewsSource(
        id=source_id or uuid.uuid4(),
        name="shadow-telegram",
        type=SourceType.TELEGRAM,
        url="https://t.me/shadow_telegram",
        active=active,
    )


def _adapter(store: _MemoryStore, client: _Client) -> TelegramSourceAdapter:
    adapter = TelegramSourceAdapter(checkpoint_store=store, now_factory=lambda: NOW)  # type: ignore[arg-type]
    adapter._build_client = lambda: client  # type: ignore[method-assign]
    return adapter


@pytest.mark.asyncio
async def test_initial_activation_100_through_150_creates_zero_and_sets_head() -> None:
    source = _source()
    store = _MemoryStore()
    adapter = _adapter(store, _Client([_Message(message_id) for message_id in range(100, 151)]))

    items = await adapter.fetch(source, SourceFetchContext(definition=None))

    assert items == []
    assert store.values[source.id] == 150


@pytest.mark.asyncio
async def test_fresh_repeat_restart_and_next_message_are_exactly_once() -> None:
    source = _source()
    store = _MemoryStore()
    store.values[source.id] = 150

    first = _adapter(store, _Client([_Message(151), _Message(152)]))
    items = await first.fetch(source, SourceFetchContext(definition=None))
    assert [item.external_id for item in items] == ["151", "152"]
    await first.acknowledge(source)
    assert store.values[source.id] == 152

    repeated = _adapter(store, _Client([_Message(151), _Message(152)]))
    assert await repeated.fetch(source, SourceFetchContext(definition=None)) == []
    await repeated.acknowledge(source)
    assert store.values[source.id] == 152

    restarted = _adapter(store, _Client([_Message(151), _Message(152), _Message(153)]))
    items = await restarted.fetch(source, SourceFetchContext(definition=None))
    assert [item.external_id for item in items] == ["153"]
    await restarted.acknowledge(source)
    assert store.values[source.id] == 153


@pytest.mark.asyncio
async def test_empty_cycle_keeps_checkpoint_stable() -> None:
    source = _source()
    store = _MemoryStore()
    store.values[source.id] = 152
    adapter = _adapter(store, _Client([]))
    assert await adapter.fetch(source, SourceFetchContext(definition=None)) == []
    await adapter.acknowledge(source)
    assert store.values[source.id] == 152


@pytest.mark.asyncio
async def test_telegram_failure_and_unauthorized_session_leave_checkpoint_unchanged() -> None:
    source = _source()
    store = _MemoryStore()
    store.values[source.id] = 150

    failing = _adapter(store, _Client([], failure=TimeoutError("telegram timeout")))
    with pytest.raises(TimeoutError):
        await failing.fetch(source, SourceFetchContext(definition=None))
    assert store.values[source.id] == 150

    unauthorized = _adapter(store, _Client([], authorized=False))
    with pytest.raises(TelegramAuthenticationError):
        await unauthorized.fetch(source, SourceFetchContext(definition=None))
    assert store.values[source.id] == 150


@pytest.mark.asyncio
async def test_mid_batch_failure_before_acknowledge_cannot_lose_152() -> None:
    source = _source()
    store = _MemoryStore()
    store.values[source.id] = 150
    messages = [_Message(151), _Message(152)]

    interrupted = _adapter(store, _Client(messages))
    assert [item.external_id for item in await interrupted.fetch(source, SourceFetchContext(None))] == ["151", "152"]
    # Simulated processing failure/crash: collector never calls acknowledge.
    assert store.values[source.id] == 150

    retried = _adapter(store, _Client(messages))
    assert [item.external_id for item in await retried.fetch(source, SourceFetchContext(None))] == ["151", "152"]


@pytest.mark.asyncio
async def test_source_isolation_and_deactivate_reactivate_retains_cursor() -> None:
    store = _MemoryStore()
    source_a = _source()
    source_b = _source()
    store.values[source_a.id] = 150
    store.values[source_b.id] = 900

    adapter_a = _adapter(store, _Client([_Message(151)]))
    await adapter_a.fetch(source_a, SourceFetchContext(None))
    await adapter_a.acknowledge(source_a)
    assert store.values == {source_a.id: 151, source_b.id: 900}

    source_a.active = False
    source_a.active = True
    reactivated = _adapter(store, _Client([_Message(150), _Message(151), _Message(152)]))
    assert [item.external_id for item in await reactivated.fetch(source_a, SourceFetchContext(None))] == ["152"]


@pytest.mark.asyncio
async def test_six_hour_freshness_failsafe_blocks_old_messages() -> None:
    source = _source()
    store = _MemoryStore()
    store.values[source.id] = 100
    old = _Message(101, date=NOW - timedelta(hours=7))
    fresh = _Message(102, date=NOW - timedelta(minutes=5))
    adapter = _adapter(store, _Client([old, fresh]))

    items = await adapter.fetch(source, SourceFetchContext(None))
    assert [item.external_id for item in items] == ["102"]
    await adapter.acknowledge(source)
    assert store.values[source.id] == 102


class _CommitSession:
    def __init__(self, *, fail: bool) -> None:
        self.fail = fail

    async def commit(self) -> None:
        if self.fail:
            raise RuntimeError("commit failed")


class _AcknowledgingAdapter:
    def __init__(self) -> None:
        self.acknowledgements = 0

    async def fetch(self, source: NewsSource, context: SourceFetchContext):
        return []

    async def acknowledge(self, source: NewsSource) -> None:
        self.acknowledgements += 1


class _Resolver:
    def __init__(self, adapter: _AcknowledgingAdapter) -> None:
        self.adapter = adapter

    def resolve(self, source: NewsSource) -> AdapterResolution:
        return AdapterResolution(adapter=self.adapter, definition=None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_collector_acknowledges_only_after_successful_commit() -> None:
    source = _source()
    adapter = _AcknowledgingAdapter()
    with pytest.raises(RuntimeError, match="commit failed"):
        await _process_source(_CommitSession(fail=True), source, _Resolver(adapter), object())  # type: ignore[arg-type]
    assert adapter.acknowledgements == 0

    await _process_source(_CommitSession(fail=False), source, _Resolver(adapter), object())  # type: ignore[arg-type]
    assert adapter.acknowledgements == 1


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, *, nx: bool = False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script: str, numkeys: int, key: str, candidate: str):
        if key not in self.values:
            return -1
        try:
            current = int(self.values[key])
            proposed = int(candidate)
        except ValueError:
            return -2
        self.values[key] = str(max(current, proposed))
        return max(current, proposed)


@pytest.mark.asyncio
async def test_checkpoint_store_is_monotonic_and_fails_closed_on_malformed_state() -> None:
    redis = _FakeRedis()
    store = TelegramCheckpointStore(redis)  # type: ignore[arg-type]
    source_id = uuid.uuid4()
    assert await store.initialize(source_id, 150) == 150
    assert await store.advance(source_id, 152) == 152
    assert await store.advance(source_id, 151) == 152

    redis.values[store.key_for(source_id)] = "not-an-integer"
    with pytest.raises(TelegramCheckpointError):
        await store.get(source_id)


@pytest.mark.asyncio
async def test_checkpoint_store_atomic_operations_against_isolated_redis(redis_client) -> None:
    store = TelegramCheckpointStore(redis_client)
    source_id = uuid.uuid4()
    key = store.key_for(source_id)
    try:
        assert await store.initialize(source_id, 150) == 150
        assert await store.initialize(source_id, 149) == 150
        assert await store.advance(source_id, 152) == 152
        assert await store.advance(source_id, 151) == 152
        assert await store.get(source_id) == 152
    finally:
        await redis_client.delete(key)
