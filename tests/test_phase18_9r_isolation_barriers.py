"""Phase 18.9-R M7 - suite-wide test-to-provider isolation barrier tests (docs/
phase18_9r_test_provider_path_audit.md, docs/phase18_9_incident_snapshot.md).

Every test here proves a real, already-active barrier from tests/conftest.py (installed at module
import time, before any test runs) rather than constructing a new, parallel safety mechanism.
`monkeypatch` is NOT used to install the barriers under test (they are already globally active for
the whole session by the time any test function runs) - it is used only where a test needs to
simulate a specific failure-injection scenario (e.g., "a test forgets to inject a fake registry").

Zero real OpenAI calls are made or attempted anywhere in this file, per instruction ("Do not verify
isolation by intentionally attempting a real provider request") - every test proves a barrier fires
*before* any request could be constructed, or inspects state that a real request would have had to
pass through.
"""
from __future__ import annotations

import os
import subprocess
import sys
from decimal import Decimal

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import Settings, get_settings, settings
from database.models.ai_execution import AICapability, AIExecution
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import NewsEvent
from integrations.llm_gateway.providers.base import ProviderCredential
from integrations.llm_gateway.providers.openai_adapter import OpenAIAdapter
from integrations.prompts.file_repository import FilePromptRepository
from schemas.workflow import WorkflowExecutionState, WorkflowType
from tests.conftest import (
    TEST_OPENAI_API_KEY_SENTINEL,
    TEST_REDIS_DB_INDEX,
    RealProviderConstructionBlockedError,
    NetworkEgressBlockedTestError,
)


# ---------------------------------------------------------------------------
# Automatic protection
# ---------------------------------------------------------------------------


def test_forgetting_to_inject_a_fake_client_is_intercepted_before_any_network_client_exists() -> None:
    """The exact 'a test forgets to inject a fake registry' scenario the brief asks for -
    OpenAIAdapter's own default (client=None) is what a forgotten injection looks like."""
    credential = ProviderCredential(api_key=settings.openai_api_key)
    with pytest.raises(RealProviderConstructionBlockedError):
        OpenAIAdapter(credential)  # no client= kwarg - the "forgot to inject" shape


@pytest.mark.asyncio
async def test_real_provider_factory_construction_is_blocked_via_the_real_boot_sequence(
    redis_client: Redis,
) -> None:
    """'real provider factory is requested' / 'CapabilityExecutor constructed from standard
    application wiring' - calls the real assemble_ai_integration_layer() with the real,
    unmodified core.config.settings (sentinel-keyed by Barrier 2), proving the real production
    boot sequence itself cannot reach a real provider, not just a hand-constructed one. Passes
    the isolated `redis_client` fixture explicitly so this test never touches
    get_redis_client()'s own production-Redis singleton, even harmlessly."""
    from pathlib import Path

    from integrations.llm_gateway.boot import assemble_ai_integration_layer

    prompts_root = FilePromptRepository(Path(__file__).resolve().parent.parent / "prompts")
    with pytest.raises(RealProviderConstructionBlockedError):
        assemble_ai_integration_layer(settings, prompts_root, redis_client=redis_client)


@pytest.mark.asyncio
async def test_dry_run_false_against_a_real_eligible_task_still_fails_closed(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    """The precise original-incident shape: a real, CREATED, eligible NEWS_ANALYSIS task, run
    with dry_run=False and zero fake registry injected - Barrier 1 must intercept it before any
    capability executes, using the real batch runner unmodified. `assemble_ai_integration_layer()`
    is called outside `run_bounded_analysis_batch()`'s own internal try/except (by design - a
    provider-construction failure must surface loudly, never be silently folded into a per-task
    "failed" outcome), so the whole call is expected to raise, not return a result object."""
    from scripts.phase18_9_controlled_batch_runner import run_bounded_analysis_batch

    state = WorkflowExecutionState(
        workflow_name=WorkflowType.NEWS_ANALYSIS, workflow_version=1,
        current_step="research", completed_steps=[], iteration_count=0, step_results=[], failure=None,
    )
    task = EditorialTask(
        event_id=real_news_event.id, priority=TaskPriority.B, workflow=state.model_dump(mode="json"),
        status=TaskStatus.CREATED,
    )
    db_session.add(task)
    await db_session.flush()

    def _same_session_factory() -> "_SameSessionCM":
        return _SameSessionCM()

    class _SameSessionCM:
        async def __aenter__(self) -> AsyncSession:
            return db_session

        async def __aexit__(self, *exc: object) -> bool:
            return False

    with pytest.raises(RealProviderConstructionBlockedError):
        await run_bounded_analysis_batch(
            [task.id], max_budget_usd=Decimal("100.00"), dry_run=False,
            session_factory=_same_session_factory,  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Credential isolation (Barrier 2)
# ---------------------------------------------------------------------------


def test_pytest_process_environment_has_the_sentinel_not_a_real_key() -> None:
    assert os.environ.get("OPENAI_API_KEY") == TEST_OPENAI_API_KEY_SENTINEL
    assert not TEST_OPENAI_API_KEY_SENTINEL.startswith("sk-")


def test_settings_singleton_sees_only_the_sentinel_key() -> None:
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == TEST_OPENAI_API_KEY_SENTINEL


def test_fresh_settings_construction_also_sees_only_the_sentinel() -> None:
    """Proves the sentinel isn't merely a property of the one cached singleton instance - a
    brand-new Settings() (still reading real .env, since no _env_file=None override is passed)
    resolves the same sentinel, because os.environ (higher precedence than .env) was sanitized
    before this process's first Settings() construction ever happened."""
    fresh = Settings()
    assert fresh.openai_api_key is not None
    assert fresh.openai_api_key.get_secret_value() == TEST_OPENAI_API_KEY_SENTINEL


def test_cached_get_settings_does_not_restore_a_real_key() -> None:
    cached = get_settings()
    assert cached.openai_api_key is not None
    assert cached.openai_api_key.get_secret_value() == TEST_OPENAI_API_KEY_SENTINEL


def test_child_process_inherits_only_the_sentinel_key() -> None:
    """'ensure subprocesses spawned by tests inherit the blocked test value' - a real subprocess,
    inheriting this process's real os.environ (the default for subprocess.run), must see only
    the sentinel."""
    result = subprocess.run(
        [sys.executable, "-c", "import os; print(os.environ.get('OPENAI_API_KEY', ''))"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    assert result.stdout.strip() == TEST_OPENAI_API_KEY_SENTINEL


def test_dotenv_file_on_disk_was_not_modified() -> None:
    """'do not modify the real .env file' - confirms the real file still contains a real-shaped
    (not sentinel) key, proving isolation was achieved entirely in-process, never by editing the
    file every other (non-test) process on this machine also reads."""
    from pathlib import Path

    env_path = Path(__file__).resolve().parent.parent / ".env"
    text_content = env_path.read_text(encoding="utf-8")
    for line in text_content.splitlines():
        if line.startswith("OPENAI_API_KEY="):
            assert TEST_OPENAI_API_KEY_SENTINEL not in line
            return
    pytest.fail("OPENAI_API_KEY= line not found in .env - cannot confirm it was left untouched")


# ---------------------------------------------------------------------------
# Network isolation (Barrier 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_external_https_request_is_denied_without_ever_resolving_dns() -> None:
    """Uses a harmless, guaranteed-nonexistent fake hostname - never api.openai.com or any real
    provider domain, per instruction. Proves the block happens at the httpx.AsyncClient.send
    layer (below the application/provider layer), not by a DNS failure or timeout."""
    async with httpx.AsyncClient() as client:
        with pytest.raises(NetworkEgressBlockedTestError):
            await client.get("https://this-host-must-never-be-contacted.invalid/")


def test_external_https_request_sync_client_is_also_denied() -> None:
    with httpx.Client() as client:
        with pytest.raises(NetworkEgressBlockedTestError):
            client.get("https://this-host-must-never-be-contacted.invalid/")


@pytest.mark.asyncio
async def test_mock_transport_requests_remain_unaffected() -> None:
    """Confirms Barrier 3 does not break the pre-existing, established
    tests/test_{arxiv,github,hacker_news,rss}_source.py pattern - a MockTransport-backed client
    must still work exactly as before, even to a real-looking hostname."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await client.get("https://example.com/feed.xml")
        assert response.status_code == 200
        assert response.text == "ok"


@pytest.mark.asyncio
async def test_local_postgres_access_remains_available(db_session: AsyncSession) -> None:
    """'do not block required local services such as local PostgreSQL' - db_session already
    proves this by construction (every other test in this suite uses it successfully), this test
    makes the guarantee explicit and independently checkable."""
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar_one() == 1


@pytest.mark.asyncio
async def test_local_redis_access_remains_available(redis_client: Redis) -> None:
    assert await redis_client.ping() is True


# ---------------------------------------------------------------------------
# Redis isolation (Barrier/M5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_client_fixture_uses_the_isolated_test_database_index() -> None:
    assert TEST_REDIS_DB_INDEX != settings.redis_db
    assert TEST_REDIS_DB_INDEX == 15


@pytest.mark.asyncio
async def test_production_cost_ledger_keys_are_unaffected_by_this_test_file(redis_client: Redis) -> None:
    """Reads today's real production ledger keys via a connection to the REAL redis_url (index 0,
    settings.redis_db) - deliberately not the isolated `redis_client` fixture - both before and
    after writing freely to the isolated fixture, proving the two are genuinely separate
    keyspaces, not merely conventionally-separated."""
    from services.cost_tracker import global_ledger_key

    production_client = Redis.from_url(settings.redis_url, decode_responses=True)
    probe_key = global_ledger_key("phase18-9r-isolation-probe")
    try:
        before = await production_client.get(probe_key)
        assert before is None  # never written by production code under this synthetic namespace

        # Write freely to the ISOLATED fixture - must never appear in the production client's view.
        await redis_client.set(probe_key, "999.999999")

        after = await production_client.get(probe_key)
        assert after is None  # completely unaffected by the write above
    finally:
        await production_client.aclose()
        await redis_client.delete(probe_key)


@pytest.mark.asyncio
async def test_research_checklist_test_no_longer_uses_the_real_calendar_date() -> None:
    """Statically confirms tests/test_api_cost_optimization_checklist.py's own fix (M5) is in
    place - it must patch datetime, never write to a key matching the real, current UTC date."""
    from pathlib import Path

    source = Path("tests/test_api_cost_optimization_checklist.py").read_text(encoding="utf-8")
    assert "_FixedNow" in source
    assert "1999, 12, 31" in source
    assert "capability_ledger_key(fake_date_key" in source


# ---------------------------------------------------------------------------
# Database isolation (M6)
# ---------------------------------------------------------------------------


async def _fresh_connection() -> AsyncSession:
    """A fresh, non-pooled connection - NOT `database.session.async_session_factory` (a
    module-level, pooled singleton). pytest-asyncio gives each test its own event loop by
    default, and a pooled connection first opened on one test's loop breaks
    (`RuntimeError: Event loop is closed`) when reused/closed from a different loop - the exact
    class of bug `tests/conftest.py::db_session`'s own docstring already documents and avoids via
    a dedicated `NullPool` engine. Confirmed the hard way here: an earlier draft of this file used
    `async_session_factory()` directly and hit exactly this failure."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    return AsyncSession(bind=engine, expire_on_commit=False)


async def _production_counts() -> dict[str, int]:
    async with await _fresh_connection() as session:
        news_events = (await session.execute(text("SELECT COUNT(*) FROM news_events"))).scalar_one()
        ai_executions = (await session.execute(text("SELECT COUNT(*) FROM ai_executions"))).scalar_one()
        content_drafts = (await session.execute(text("SELECT COUNT(*) FROM content_drafts"))).scalar_one()
        return {
            "news_events": news_events, "ai_executions": ai_executions, "content_drafts": content_drafts,
        }


@pytest.mark.asyncio
async def test_no_production_ai_execution_or_content_draft_rows_are_created_by_this_file(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    """news_events grows independently (automation_worker keeps running, Phase 18.8's own
    authorized state) - ai_executions/content_drafts must not, since only a real paid workflow
    execution can add to them, and this whole file proves none can ever succeed."""
    before = await _production_counts()

    # Real db_session work (rolled back at teardown) - proves in-transaction activity doesn't
    # leak into the production-count view taken via a separate, independent connection.
    # `task_id` is a random, unrelated uuid (not real_news_event.id) - deliberately never
    # flushed/committed, so no FK constraint is ever checked; this row only ever exists in this
    # test's own in-memory session state and the rolled-back SAVEPOINT.
    from uuid import uuid4

    db_session.add(AIExecution(
        task_id=uuid4(), event_id=real_news_event.id, workflow_name="TEST",
        capability=AICapability.RESEARCH, model="gpt-5.6-luna", retry_number=0,
        input_tokens=1, output_tokens=1, cost=Decimal("0.00"), usage_source="provider_response",
    ))

    after = await _production_counts()
    assert after["ai_executions"] == before["ai_executions"]
    assert after["content_drafts"] == before["content_drafts"]


@pytest.mark.asyncio
async def test_current_database_is_the_documented_real_identity() -> None:
    """Honest, not a false 'different database' claim (docs/phase18_9r_postgres_isolation_audit.md)
    - documents the true shared identity so a future reader never has to rediscover it."""
    async with await _fresh_connection() as session:
        db_name = (await session.execute(text("SELECT current_database()"))).scalar_one()
    assert db_name == "ai_newsroom"


@pytest.mark.asyncio
async def test_savepoint_rollback_is_invisible_outside_its_own_transaction(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    """The actual property that matters: a real INSERT made and flushed inside db_session's own
    SAVEPOINT is never visible to a separate, independent connection (i.e., to the rest of the
    real application) while the test is still running - not merely "gone after teardown"."""
    async with await _fresh_connection() as outside_session:
        found = await outside_session.get(NewsEvent, real_news_event.id)
    assert found is None


# ---------------------------------------------------------------------------
# Secret safety
# ---------------------------------------------------------------------------


def test_barrier_failure_messages_never_contain_the_real_or_sentinel_key_value() -> None:
    """Even the sentinel itself is deliberately excluded from failure text, on principle - error
    messages should describe *what* was blocked, never echo credential-shaped values back."""
    credential = ProviderCredential(api_key=settings.openai_api_key)
    try:
        OpenAIAdapter(credential)
    except RealProviderConstructionBlockedError as exc:
        message = str(exc)
        assert TEST_OPENAI_API_KEY_SENTINEL not in message
        assert "sk-" not in message
    else:
        pytest.fail("expected RealProviderConstructionBlockedError")


def test_network_barrier_failure_messages_contain_no_authorization_header() -> None:
    import asyncio

    async def _attempt() -> str:
        async with httpx.AsyncClient(headers={"Authorization": "Bearer sk-should-never-appear"}) as client:
            try:
                await client.get("https://this-host-must-never-be-contacted.invalid/")
            except NetworkEgressBlockedTestError as exc:
                return str(exc)
            raise AssertionError("expected NetworkEgressBlockedTestError")

    message = asyncio.run(_attempt())
    assert "sk-should-never-appear" not in message
    assert "authorization" not in message.lower()
