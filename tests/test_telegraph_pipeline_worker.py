"""TELEGRAPH EDITORIAL DELIVERY - RETRY/RECOVERY FIX: scripts.telegraph_pipeline_worker.
run_telegraph_pipeline_for_proposal(). Real Postgres (db_session fixture), FakeLLMGateway (zero
network/cost) via the same `_DualGateway`/`_full_registry` this checkpoint's own
tests/test_telegraph_article_processor.py already established, and a real aiogram `Bot` bound to
a fake in-memory `BaseSession` (no real Telegram API call ever) - mirrors
tests/test_telegraph_article_review_notifier.py's own established fake-session shape.

Root cause under test: a first run that generates the article but only DRY-RUNS (or fails) the
Telegram send left a `TelegraphArticleReview` row with `telegram_message_id=NULL`. A rerun of the
same proposal correctly found `generate_article_for_researched_proposal()` returning
status="already_exists" (no new paid call - the exactly-once-per-Story guard), but the worker's
own early-return guard then treated that as a stop condition and exited BEFORE ever resolving the
existing review or sending it - the pending review was silently stuck forever. These tests prove
the fix's 5 cases (A-E, per the fix's own module docstring) without ever making a real LLM or
Telegram call.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import Chat, Message as AiogramMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.telegraph_article_review import TelegraphArticleReview
from database.models.telegraph_shortlist import TelegraphProposalStatus
from scripts.telegraph_pipeline_worker import run_telegraph_pipeline_for_proposal
from services.telegraph_article_processor import generate_article_for_researched_proposal
from services.telegraph_article_review_service import create_article_review, get_review_for_article_task
from services.telegraph_research_processor import process_approved_telegraph_proposal
from tests.test_telegraph_article_processor import _DualGateway, _full_registry
from tests.test_telegraph_research_processor import _seed_claimable_proposal

_CHAT_ID = -1004297182444
_TOPIC_ID = 39


class _FakeBotSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[TelegramMethod] = []
        self._next_message_id = 1000

    async def close(self) -> None:
        pass

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None) -> object:
        self.sent.append(method)
        message_id = self._next_message_id
        self._next_message_id += 1
        chat_id = getattr(method, "chat_id", _CHAT_ID)
        return AiogramMessage(message_id=message_id, date=datetime.now(timezone.utc), chat=Chat(id=chat_id, type="supergroup"))

    async def stream_content(self, *args: object, **kwargs: object) -> object:
        raise NotImplementedError


def _bot() -> tuple[Bot, _FakeBotSession]:
    session = _FakeBotSession()
    return Bot(token="123456:FAKE-TEST-TOKEN-AAAAAAAAAAAAAAAAAAAAAAAAAAAA", session=session), session


def _fake_session_factory(db_session: AsyncSession):
    """Byte-for-byte the same technique tests/test_telegraph_article_review_handler.py's own
    `_fake_session_factory()` already established: `run_telegraph_pipeline_for_proposal()` opens
    its OWN top-level session via `database.session.async_session_factory()` (correct for a real
    standalone script - it owns its own transaction), which is bound to a different engine/event-
    loop lifecycle than the `db_session` fixture's own dedicated NullPool test engine (conftest.py's
    own documented reason `database.session.engine` is never usable directly in a test). Swapping
    the worker's imported `async_session_factory` name for a fake context manager that just yields
    the test's own `db_session` lets these tests see (and write into) the exact same transaction
    without ever touching the real engine."""
    class _CM:
        async def __aenter__(self) -> AsyncSession:
            return db_session

        async def __aexit__(self, *exc: object) -> bool:
            return False

    return lambda: _CM()


@pytest.fixture(autouse=True)
def _routing_configured(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _CHAT_ID)
    monkeypatch.setattr(settings, "telegraph_topic_id", _TOPIC_ID)
    monkeypatch.setattr(settings, "telegraph_pipeline_enabled", True)
    monkeypatch.setattr(
        "scripts.telegraph_pipeline_worker.async_session_factory", _fake_session_factory(db_session),
    )


async def _run_research_and_article(db_session: AsyncSession, gateway: _DualGateway):
    """Sets up CASE B/D preconditions directly (bypassing the worker) - a proposal with a real,
    COMPLETED research task and a real, COMPLETED article task already in the database, exactly
    what a first worker run's own stages 1-2 would have produced."""
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    registry = _full_registry(gateway)
    research_outcome = await process_approved_telegraph_proposal(db_session, proposal.id, capability_registry=registry)
    assert research_outcome.run_result is not None and research_outcome.run_result.status == "COMPLETED"
    article_outcome = await generate_article_for_researched_proposal(db_session, proposal.id, capability_registry=registry)
    assert article_outcome.status == "generated"
    assert article_outcome.run_result is not None and article_outcome.run_result.status == "COMPLETED"
    return proposal, registry, article_outcome.task_id


@pytest.mark.asyncio
async def test_case_a_fresh_proposal_generates_review_and_sends(db_session: AsyncSession) -> None:
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    gateway = _DualGateway()
    registry = _full_registry(gateway)
    bot, session = _bot()

    await run_telegraph_pipeline_for_proposal(
        proposal.id, live=True, capability_registry=registry, bot=bot,
    )

    reviews = (await db_session.execute(select(TelegraphArticleReview).where(TelegraphArticleReview.proposal_id == proposal.id))).scalars().all()
    assert len(reviews) == 1
    review = reviews[0]
    assert review.telegram_message_id is not None
    assert review.telegram_chat_id == _CHAT_ID
    assert review.telegram_thread_id == _TOPIC_ID

    sends = [m for m in session.sent if isinstance(m, SendMessage)]
    assert len(sends) >= 3  # header + at least one body chunk + footer
    assert len(gateway.received_requests) == 2  # exactly one research call + one article call


@pytest.mark.asyncio
async def test_case_b_existing_undelivered_review_is_recovered_and_sent(db_session: AsyncSession) -> None:
    gateway = _DualGateway()
    proposal, registry, article_task_id = await _run_research_and_article(db_session, gateway)
    existing_review = await create_article_review(db_session, article_task_id=article_task_id, proposal_id=proposal.id)
    assert existing_review.telegram_message_id is None
    calls_before_worker = len(gateway.received_requests)
    bot, session = _bot()

    await run_telegraph_pipeline_for_proposal(
        proposal.id, live=True, capability_registry=registry, bot=bot,
    )

    # Zero new research/article LLM calls - the whole point of the fix.
    assert len(gateway.received_requests) == calls_before_worker

    reviews = (await db_session.execute(select(TelegraphArticleReview).where(TelegraphArticleReview.proposal_id == proposal.id))).scalars().all()
    assert len(reviews) == 1  # never a duplicate row
    recovered = reviews[0]
    assert recovered.id == existing_review.id  # the SAME review, not a new one
    assert recovered.telegram_message_id is not None  # delivery anchor persisted
    sends = [m for m in session.sent if isinstance(m, SendMessage)]
    assert len(sends) >= 3


@pytest.mark.asyncio
async def test_case_d_article_exists_no_review_creates_exactly_one_and_sends(db_session: AsyncSession) -> None:
    gateway = _DualGateway()
    proposal, registry, article_task_id = await _run_research_and_article(db_session, gateway)
    assert await get_review_for_article_task(db_session, article_task_id) is None  # precondition: no review yet
    bot, session = _bot()

    await run_telegraph_pipeline_for_proposal(
        proposal.id, live=True, capability_registry=registry, bot=bot,
    )

    reviews = (await db_session.execute(select(TelegraphArticleReview).where(TelegraphArticleReview.proposal_id == proposal.id))).scalars().all()
    assert len(reviews) == 1  # exactly one - never a duplicate
    assert reviews[0].telegram_message_id is not None
    sends = [m for m in session.sent if isinstance(m, SendMessage)]
    assert len(sends) >= 3


@pytest.mark.asyncio
async def test_case_c_already_delivered_review_is_never_resent(db_session: AsyncSession) -> None:
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    gateway = _DualGateway()
    registry = _full_registry(gateway)
    bot, session = _bot()

    await run_telegraph_pipeline_for_proposal(proposal.id, live=True, capability_registry=registry, bot=bot)
    sends_after_first = len(session.sent)
    assert sends_after_first > 0
    calls_after_first = len(gateway.received_requests)

    reviews = (await db_session.execute(select(TelegraphArticleReview).where(TelegraphArticleReview.proposal_id == proposal.id))).scalars().all()
    assert len(reviews) == 1
    delivered_message_id = reviews[0].telegram_message_id
    assert delivered_message_id is not None

    # Retry the exact same proposal - simulates re-invoking the worker after a successful delivery.
    await run_telegraph_pipeline_for_proposal(proposal.id, live=True, capability_registry=registry, bot=bot)

    assert len(session.sent) == sends_after_first  # zero NEW Telegram sends - no duplicate sequence
    assert len(gateway.received_requests) == calls_after_first  # zero new LLM calls either
    reviews_after_retry = (await db_session.execute(select(TelegraphArticleReview).where(TelegraphArticleReview.proposal_id == proposal.id))).scalars().all()
    assert len(reviews_after_retry) == 1  # still no duplicate row
    assert reviews_after_retry[0].telegram_message_id == delivered_message_id  # unchanged anchor


@pytest.mark.asyncio
async def test_case_e_no_research_fails_closed_creates_no_review(db_session: AsyncSession) -> None:
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.PENDING)
    # PENDING (never approved) - claim_approved_telegraph_proposal() itself only claims APPROVED
    # proposals, so research never runs; a completely usable "no research at all" CASE E setup.
    gateway = _DualGateway()
    registry = _full_registry(gateway)
    bot, session = _bot()

    await run_telegraph_pipeline_for_proposal(proposal.id, live=True, capability_registry=registry, bot=bot)

    assert len(gateway.received_requests) == 0  # never invents/recomputes unrelated work
    assert session.sent == []
    reviews = (await db_session.execute(select(TelegraphArticleReview).where(TelegraphArticleReview.proposal_id == proposal.id))).scalars().all()
    assert reviews == []


@pytest.mark.asyncio
async def test_dry_run_never_sends_even_when_article_already_exists(db_session: AsyncSession) -> None:
    """dry_run/live semantics are unchanged by this fix: `live=False` (the CLI default) must still
    never actually deliver to Telegram, in either the fresh (CASE A) or recovered (CASE B) path."""
    gateway = _DualGateway()
    proposal, registry, article_task_id = await _run_research_and_article(db_session, gateway)
    await create_article_review(db_session, article_task_id=article_task_id, proposal_id=proposal.id)
    bot, session = _bot()

    await run_telegraph_pipeline_for_proposal(proposal.id, live=False, capability_registry=registry, bot=bot)

    assert session.sent == []  # dry_run - zero real Telegram calls, even in the recovery path
    review = await get_review_for_article_task(db_session, article_task_id)
    assert review is not None
    assert review.telegram_message_id is None  # never anchored on a dry run


@pytest.mark.asyncio
async def test_live_flag_alone_without_pipeline_enabled_stays_dry_run(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """The double-confirmation contract (module docstring) is unchanged: `--live` alone, without
    `settings.telegraph_pipeline_enabled=True`, must still dry-run."""
    monkeypatch.setattr(settings, "telegraph_pipeline_enabled", False)
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    gateway = _DualGateway()
    registry = _full_registry(gateway)
    bot, session = _bot()

    await run_telegraph_pipeline_for_proposal(proposal.id, live=True, capability_registry=registry, bot=bot)

    assert session.sent == []
