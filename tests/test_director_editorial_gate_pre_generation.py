"""DIRECTOR-CONTROL-PLANE-1A §33-34: required pre-generation-gate + shadow-mode tests against the
REAL run_content_cycle() loop. Reuses tests/test_content_worker_cycle.py's own established real-
Postgres/fake-LLMGateway technique wholesale: `factory`, `test_source` (with its battle-hardened
child-table teardown - these tests run real content generation, which writes
news_event_article_acquisitions/stories/... rows a naive teardown would orphan) and
`_isolated_freshness_window` are IMPORTED from that module, not re-implemented, so this file can
never drift behind a newly-added FK-referencing table. Only `_gate_enabled` (specific to this
phase) is defined locally."""
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from database.models.director_editorial_decision import (
    DirectorEditorialDecision,
    EditorialGateReasonCode,
)
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from services.director_editorial_gate_budget import STAGE_2_DIRECTOR_VERSION_MARKER
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.test_content_worker_cycle import (
    _isolated_freshness_window,  # noqa: F401,F811 - a pytest fixture, reused as a parameter name below
    _make_completed_news_analysis_task,
    _make_event,
    _real_capability_registry,
    factory,  # noqa: F401,F811 - a pytest fixture, reused as a parameter name below
    test_source,  # noqa: F401,F811 - a pytest fixture, reused as a parameter name below
)
from worker.content_cycle import run_content_cycle

_PROMPTS_ROOT_PATH = Path("prompts")


def _stage2_response(decision: str, reason_codes: list[str], short_reason: str) -> GenerateResponse:
    return GenerateResponse(
        text=None,
        structured_output={
            "decision": decision, "reason_codes": reason_codes,
            "short_reason": short_reason, "confidence": 0.7,
        },
        finish_reason="stop", model_used="fake-gate-director-v1",
        usage=CapabilityUsage(input_tokens=200, output_tokens=40),
    )


@pytest_asyncio.fixture
async def _gate_enabled() -> AsyncIterator[None]:
    original = settings.telegram_editorial_gate_enabled
    settings.telegram_editorial_gate_enabled = True
    try:
        yield
    finally:
        settings.telegram_editorial_gate_enabled = original


async def _make_event_with_content(
    session: AsyncSession, source: NewsSource, *, published_at: datetime, content: str | None,
) -> NewsEvent:
    event = await _make_event(session, source, published_at=published_at)
    event.content = content
    await session.commit()
    return event


@pytest.mark.asyncio
async def test_gate_off_preserves_existing_pipeline_behavior_but_still_persists_decision(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None,  # noqa: F811
) -> None:
    """Spec §7/§34: OFF -> normal queue unchanged, but a real DirectorEditorialDecision is still
    persisted (shadow, never suppressed)."""
    assert settings.telegram_editorial_gate_enabled is False
    async with factory() as session:
        event = await _make_event_with_content(
            session, test_source, published_at=datetime.now(timezone.utc), content="Real story content with facts.",
        )
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.completed == 1
    assert result.gate_generation_suppressed == 0
    assert result.gate_total_stories == 1

    async with factory() as session:
        decision = (await session.execute(
            select(DirectorEditorialDecision).where(DirectorEditorialDecision.event_id == event.id)
        )).scalar_one()
    assert decision is not None


@pytest.mark.asyncio
async def test_gate_on_hold_prevents_content_generation(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None,  # noqa: F811
    _gate_enabled: None,
) -> None:
    """Spec §33: HOLD -> content generator NOT CALLED. An event that IS eligible (has a completed
    NEWS_ANALYSIS task, so _select_eligible_events() surfaces it) but has no content at all and no
    article acquisition row has has_sufficient_facts=False -> HOLD, deterministically."""
    async with factory() as session:
        event = await _make_event_with_content(session, test_source, published_at=datetime.now(timezone.utc), content=None)
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    with patch(
        "worker.content_cycle.run_content_generation_for_event",
        new=AsyncMock(side_effect=AssertionError("content generator must not be called for a HOLD decision")),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.completed == 0
    assert result.gate_hold == 1
    assert result.gate_generation_suppressed == 1


@pytest.mark.asyncio
async def test_gate_on_send_to_editor_continues_normal_generation(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None,  # noqa: F811
    _gate_enabled: None,
) -> None:
    """Spec §33: SEND_TO_EDITOR -> normal generation continues."""
    async with factory() as session:
        event = await _make_event_with_content(
            session, test_source, published_at=datetime.now(timezone.utc), content="Substantial real article content about AI.",
        )
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.completed == 1
    assert result.gate_generation_suppressed == 0
    assert result.gate_send_to_editor + result.gate_priority + result.gate_breaking == 1


@pytest.mark.asyncio
async def test_gate_llm_unavailable_does_not_collapse_the_pipeline(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None,  # noqa: F811
    _gate_enabled: None,
) -> None:
    """Spec §6/§33: a gate evaluation failure (simulated here as build_gate_input_for_event raising)
    fails OPEN - generation proceeds unsuppressed rather than the whole cycle collapsing."""
    async with factory() as session:
        event = await _make_event_with_content(
            session, test_source, published_at=datetime.now(timezone.utc), content="Some content.",
        )
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    with patch(
        "worker.content_cycle.run_pre_generation_gate", new=AsyncMock(side_effect=RuntimeError("gate unavailable")),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.completed == 1  # generation still happened - fail-open, queue never collapsed


# --------------------------------------------------------------------------------------------------
# DIRECTOR-CONTROL-PLANE-1B §2-4/§14: bounded, real, fail-soft Stage 2 Director judgment
# --------------------------------------------------------------------------------------------------


@pytest_asyncio.fixture
async def _gate_llm_budget_zero() -> AsyncIterator[None]:
    original = settings.director_editorial_gate_max_llm_reviews_per_day
    settings.director_editorial_gate_max_llm_reviews_per_day = 0
    try:
        yield
    finally:
        settings.director_editorial_gate_max_llm_reviews_per_day = original


async def _seed_escalation_worthy_event(session: AsyncSession, source: NewsSource) -> NewsEvent:
    """An eligible event with a completed NEWS_ANALYSIS task and real content. Against an empty
    feed its category is absent from the feed topic distribution -> Stage 1 attaches FEED_GAP_FILL
    -> is_escalation_worthy() is True, so Stage 2 is actually reached."""
    event = await _make_event_with_content(
        session, source, published_at=datetime.now(timezone.utc),
        content="Substantial real article content about a genuinely ambiguous AI industry development.",
    )
    await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)
    return event


@pytest.mark.asyncio
async def test_stage2_real_director_judgment_is_applied_and_marked(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None,  # noqa: F811
) -> None:
    """Spec §2/§14: when a real gateway is threaded through and the candidate is escalation-worthy,
    the persisted decision is the Director LLM's, and its row is marked v1-llm so the daily budget
    counts it."""
    async with factory() as session:
        event = await _seed_escalation_worthy_event(session, test_source)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()
    gate_gateway = FakeLLMGateway(generate_response=_stage2_response(
        "priority", ["campaign_relevant", "major_industry_event"], "Genuinely strategic - prioritize.",
    ))

    result = await run_content_cycle(
        registry, fake_bot, session_factory=factory,
        gate_gateway=gate_gateway, gate_prompt_repository=FilePromptRepository(_PROMPTS_ROOT_PATH),
    )

    assert result.gate_stage2_llm_used == 1
    assert result.gate_stage2_fell_back == 0
    assert len(gate_gateway.received_requests) == 1  # exactly one paid call, not one per raw item

    async with factory() as session:
        decision = (await session.execute(
            select(DirectorEditorialDecision).where(DirectorEditorialDecision.event_id == event.id)
        )).scalar_one()
    assert decision.director_version == STAGE_2_DIRECTOR_VERSION_MARKER
    assert decision.decision.value == "priority"


@pytest.mark.asyncio
async def test_stage2_provider_failure_falls_soft_back_to_stage1(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None,  # noqa: F811
) -> None:
    """Spec §4: a Gateway failure -> deterministic Stage 1 outcome, pipeline continues, and the
    row records the fallback provenance. Never DROP-everything."""
    async with factory() as session:
        event = await _seed_escalation_worthy_event(session, test_source)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()
    gate_gateway = FakeLLMGateway(generate_error=RuntimeError("simulated provider outage"))

    result = await run_content_cycle(
        registry, fake_bot, session_factory=factory,
        gate_gateway=gate_gateway, gate_prompt_repository=FilePromptRepository(_PROMPTS_ROOT_PATH),
    )

    assert result.completed == 1  # pipeline did not collapse
    assert result.gate_stage2_fell_back == 1
    assert result.gate_stage2_llm_used == 0
    assert result.gate_send_to_editor + result.gate_priority + result.gate_breaking == 1  # Stage 1 still reached the editor

    async with factory() as session:
        decision = (await session.execute(
            select(DirectorEditorialDecision).where(DirectorEditorialDecision.event_id == event.id)
        )).scalar_one()
    assert decision.director_version == STAGE_2_DIRECTOR_VERSION_MARKER  # an attempt was made - counts against the bound
    assert EditorialGateReasonCode.LLM_UNAVAILABLE_FALLBACK.value in decision.reason_codes


@pytest.mark.asyncio
async def test_stage2_daily_budget_exhausted_uses_stage1_without_a_paid_call(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None,  # noqa: F811
    _gate_llm_budget_zero: None,
) -> None:
    """Spec §3: budget exhausted -> Stage 1 result, and no Gateway call is even attempted."""
    async with factory() as session:
        event = await _seed_escalation_worthy_event(session, test_source)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()
    gate_gateway = FakeLLMGateway(generate_error=AssertionError("no paid call may be made when the daily budget is exhausted"))

    result = await run_content_cycle(
        registry, fake_bot, session_factory=factory,
        gate_gateway=gate_gateway, gate_prompt_repository=FilePromptRepository(_PROMPTS_ROOT_PATH),
    )

    assert result.completed == 1
    assert result.gate_stage2_budget_exhausted == 1
    assert result.gate_stage2_llm_used == 0
    assert gate_gateway.received_requests == []

    async with factory() as session:
        decision = (await session.execute(
            select(DirectorEditorialDecision).where(DirectorEditorialDecision.event_id == event.id)
        )).scalar_one()
    assert decision.director_version == "v1"  # never marked as an LLM review - budget protected it
