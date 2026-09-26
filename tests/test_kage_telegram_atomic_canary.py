from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest


def test_canary_refuses_to_reuse_production_redis(monkeypatch) -> None:
    import scripts._kage_telegram_atomic_natural_canary as canary

    monkeypatch.setattr(canary.settings, "redis_host", "production-redis")
    monkeypatch.delenv("KAGE_CANARY_REDIS_HOST", raising=False)
    with pytest.raises(RuntimeError, match="isolated Redis host"):
        canary._configure_isolated_canary_redis()


@pytest.mark.asyncio
async def test_atomic_canary_hands_off_the_single_top_event_without_reselection(monkeypatch) -> None:
    import scripts._kage_telegram_atomic_natural_canary as canary

    event_id = uuid4()
    selection = {
        "event_id": str(event_id), "valid": True,
        "selector_selected_at": datetime.now(timezone.utc).isoformat(),
        "content_generation_tasks": 0, "delivery_records": 0, "analysis_fresh": True,
    }

    class Controller:
        def __init__(self) -> None:
            self.select_calls = 0
            self.claimed: list[str] = []
            self.rechecked: list[str] = []
            self.closed = False

        async def select_top(self):
            self.select_calls += 1
            return selection

        async def claim(self, selected_id):
            self.claimed.append(str(selected_id))
            return True

        async def recheck_same_event(self, selected_id):
            self.rechecked.append(str(selected_id))
            return {"valid": True}

        async def close(self):
            self.closed = True

    class RedisClient:
        async def ping(self):
            return True

        async def dbsize(self):
            return 0

        async def aclose(self):
            return None

    class FakeRedis:
        urls: list[str] = []

        @staticmethod
        def from_url(url, **_kwargs):
            FakeRedis.urls.append(url)
            return RedisClient()

    class PromptRepository:
        def __init__(self, _root):
            pass

        def resolve(self, _name, version):
            return SimpleNamespace(version=version)

    class Bot:
        class Session:
            async def close(self):
                return None

        session = Session()

    controller = Controller()
    handed_off: list[str] = []

    async def run_claimed(selected_id, *_args):
        handed_off.append(str(selected_id))
        return {"provider_calls": 0}

    monkeypatch.setattr(canary, "setup_logging", lambda: None)
    monkeypatch.setattr(canary.settings, "redis_host", "production-redis")
    monkeypatch.setenv("KAGE_CANARY_REDIS_HOST", "disposable-canary-redis")
    monkeypatch.setattr(canary, "_configure_frozen_canary_settings", lambda: None)
    monkeypatch.setattr(canary, "resolve_route", lambda _destination: canary.EXPECTED_ROUTE)
    monkeypatch.setattr(canary, "maximum_canary_cost", lambda: canary.MAX_COST)
    monkeypatch.setattr(canary, "validate_request_envelope_contracts", lambda: {"research": (1400, 1400)})
    monkeypatch.setattr(canary, "FilePromptRepository", PromptRepository)
    monkeypatch.setattr(canary, "Redis", FakeRedis)
    monkeypatch.setattr(canary, "assemble_ai_integration_layer", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(canary, "create_bot", lambda: Bot())
    monkeypatch.setattr(canary, "ModelRegistryPricingCatalog", lambda *_args: object())
    monkeypatch.setattr(canary, "build_model_registry", lambda: object())
    monkeypatch.setattr(canary, "AtomicNaturalCanary", lambda: controller)
    monkeypatch.setattr(canary, "_run_claimed", run_claimed)

    await canary.main()

    assert controller.select_calls == 1
    assert controller.claimed == [str(event_id)]
    assert controller.rechecked == [str(event_id)]
    assert handed_off == [str(event_id)]
    assert controller.closed
    assert FakeRedis.urls == ["redis://disposable-canary-redis:6379/0"]
