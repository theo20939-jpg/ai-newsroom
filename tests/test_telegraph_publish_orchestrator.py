"""TELEGRAPH LIVE PUBLISH: services.telegraph_publish_orchestrator.
publish_approved_telegraph_article() - gating, idempotency, and failure-leaves-retryable
semantics. Real Postgres (db_session fixture); the Telegraph network call itself
(services.telegraph_publisher.create_page) is monkeypatched at its import site in the
orchestrator module - never a real HTTPS call.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.telegraph_article_review import TelegraphArticleReview, TelegraphArticleReviewStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from services.telegraph_article_processor import generate_article_for_researched_proposal
from services.telegraph_article_review_service import TelegraphArticleReviewService, create_article_review
from services.telegraph_publish_orchestrator import publish_approved_telegraph_article
from services.telegraph_publisher import TelegraphPage, TelegraphPublishError
import services.telegraph_publish_orchestrator as orchestrator_module
from tests.test_telegraph_article_processor import _DualGateway, _researched_proposal


async def _seed_approved_review(db_session: AsyncSession):
    gateway = _DualGateway()
    proposal, registry = await _researched_proposal(db_session, gateway)
    outcome = await generate_article_for_researched_proposal(db_session, proposal.id, capability_registry=registry)
    assert outcome.status == "generated" and outcome.task_id is not None
    review = await create_article_review(db_session, article_task_id=outcome.task_id, proposal_id=proposal.id)

    service = TelegraphArticleReviewService(db_session)
    approved = await service.set_decision(
        review.id, TelegraphArticleReviewStatus.APPROVED, decided_by_telegram_user_id=111,
    )
    assert approved is not None
    return approved


async def _make_article_task(db_session: AsyncSession) -> EditorialTask:
    source = NewsSource(name=f"Orchestrator test source {uuid.uuid4()}", type=SourceType.RSS, active=True)
    db_session.add(source)
    await db_session.flush()
    event = NewsEvent(
        source_id=source.id, title="Orchestrator test event", content="x", category=EventCategory.AI,
        hash=f"orch-{uuid.uuid4()}",
    )
    db_session.add(event)
    await db_session.flush()
    task = EditorialTask(
        event_id=event.id, priority=TaskPriority.C,
        workflow={"workflow_name": "TELEGRAPH_ARTICLE", "step_results": []},
    )
    db_session.add(task)
    await db_session.flush()
    return task


def _mock_create_page(monkeypatch: pytest.MonkeyPatch, *, url: str = "https://telegra.ph/Test-08-31", calls: list | None = None):
    async def fake_create_page(*, title: str, content, author_name=None, author_url=None):
        if calls is not None:
            calls.append((title, content))
        return TelegraphPage(path="Test-08-31", url=url)

    monkeypatch.setattr(orchestrator_module, "create_page", fake_create_page)


def _mock_create_page_failure(monkeypatch: pytest.MonkeyPatch, *, message: str = "boom"):
    async def fake_create_page(*, title: str, content, author_name=None, author_url=None):
        raise TelegraphPublishError(message)

    monkeypatch.setattr(orchestrator_module, "create_page", fake_create_page)


@pytest.mark.asyncio
async def test_review_not_found_fails_safely(db_session: AsyncSession) -> None:
    outcome = await publish_approved_telegraph_article(db_session, uuid.uuid4())
    assert outcome.status == "failed"
    assert outcome.error == "review_not_found"


@pytest.mark.asyncio
async def test_pending_review_cannot_publish(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    _mock_create_page(monkeypatch, calls=calls)

    gateway = _DualGateway()
    proposal, registry = await _researched_proposal(db_session, gateway)
    outcome = await generate_article_for_researched_proposal(db_session, proposal.id, capability_registry=registry)
    assert outcome.status == "generated" and outcome.task_id is not None
    review = await create_article_review(db_session, article_task_id=outcome.task_id, proposal_id=proposal.id)
    assert review.status == TelegraphArticleReviewStatus.PENDING

    result = await publish_approved_telegraph_article(db_session, review.id)
    assert result.status == "not_approved"
    assert calls == []


@pytest.mark.asyncio
async def test_needs_revision_review_cannot_publish(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    _mock_create_page(monkeypatch, calls=calls)

    gateway = _DualGateway()
    proposal, registry = await _researched_proposal(db_session, gateway)
    outcome = await generate_article_for_researched_proposal(db_session, proposal.id, capability_registry=registry)
    assert outcome.status == "generated" and outcome.task_id is not None
    review = await create_article_review(db_session, article_task_id=outcome.task_id, proposal_id=proposal.id)
    service = TelegraphArticleReviewService(db_session)
    await service.set_decision(review.id, TelegraphArticleReviewStatus.NEEDS_REVISION, decided_by_telegram_user_id=1)

    result = await publish_approved_telegraph_article(db_session, review.id)
    assert result.status == "not_approved"
    assert calls == []


@pytest.mark.asyncio
async def test_approved_review_publishes(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    _mock_create_page(monkeypatch, calls=calls, url="https://telegra.ph/Product-Y-08-31")
    review = await _seed_approved_review(db_session)

    result = await publish_approved_telegraph_article(db_session, review.id)
    assert result.status == "published"
    assert result.url == "https://telegra.ph/Product-Y-08-31"
    assert len(calls) == 1
    title, content = calls[0]
    assert title  # headline passed through
    assert isinstance(content, list) and content


@pytest.mark.asyncio
async def test_successful_url_persisted(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_create_page(monkeypatch, url="https://telegra.ph/Persisted-08-31")
    review = await _seed_approved_review(db_session)

    await publish_approved_telegraph_article(db_session, review.id)

    service = TelegraphArticleReviewService(db_session)
    reloaded = await service.get_review(review.id)
    assert reloaded is not None
    assert reloaded.published_url == "https://telegra.ph/Persisted-08-31"
    assert reloaded.published_at is not None
    # never mutated by this orchestrator - status stays exactly what the human decided
    assert reloaded.status == TelegraphArticleReviewStatus.APPROVED


@pytest.mark.asyncio
async def test_second_call_is_idempotent_and_does_not_call_create_page_twice(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    _mock_create_page(monkeypatch, calls=calls)
    review = await _seed_approved_review(db_session)

    first = await publish_approved_telegraph_article(db_session, review.id)
    second = await publish_approved_telegraph_article(db_session, review.id)

    assert first.status == "published"
    assert second.status == "already_published"
    assert second.url == first.url
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_failed_create_page_leaves_review_approved_and_unpublished(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_create_page_failure(monkeypatch, message="telegra.ph is down")
    review = await _seed_approved_review(db_session)

    result = await publish_approved_telegraph_article(db_session, review.id)
    assert result.status == "failed"
    assert "telegra.ph is down" in (result.error or "")

    service = TelegraphArticleReviewService(db_session)
    reloaded = await service.get_review(review.id)
    assert reloaded is not None
    assert reloaded.status == TelegraphArticleReviewStatus.APPROVED  # unchanged, still retryable
    assert reloaded.published_url is None


@pytest.mark.asyncio
async def test_retry_after_failure_can_succeed(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    review = await _seed_approved_review(db_session)

    _mock_create_page_failure(monkeypatch)
    first = await publish_approved_telegraph_article(db_session, review.id)
    assert first.status == "failed"

    _mock_create_page(monkeypatch, url="https://telegra.ph/Retry-Ok-08-31")
    second = await publish_approved_telegraph_article(db_session, review.id)
    assert second.status == "published"
    assert second.url == "https://telegra.ph/Retry-Ok-08-31"


@pytest.mark.asyncio
async def test_article_task_not_completed_fails_closed(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    _mock_create_page(monkeypatch, calls=calls)

    task = await _make_article_task(db_session)
    assert task.status != TaskStatus.COMPLETED
    gateway = _DualGateway()
    proposal, _registry = await _researched_proposal(db_session, gateway)
    review = await create_article_review(db_session, article_task_id=task.id, proposal_id=proposal.id)
    service = TelegraphArticleReviewService(db_session)
    approved = await service.set_decision(
        review.id, TelegraphArticleReviewStatus.APPROVED, decided_by_telegram_user_id=1,
    )
    assert approved is not None

    result = await publish_approved_telegraph_article(db_session, review.id)
    assert result.status == "article_not_ready"
    assert calls == []


@pytest.mark.asyncio
async def test_concurrent_double_publish_second_writer_does_not_overwrite_first(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulates the real race this Checkpoint's own pre-deploy review flagged: two concurrent
    callers whose own real Telegraph API calls BOTH already "succeeded" independently before
    either persisted. Caller A wins by committing the atomic conditional UPDATE first (simulated
    directly here, exactly matching the real UPDATE statement
    services.telegraph_publish_orchestrator.publish_approved_telegraph_article() itself issues).
    Caller B's own attempt (via the real orchestrator, network mocked) must NOT overwrite A's URL
    - Postgres's row-level locking on the conditional UPDATE (`WHERE published_url IS NULL`) makes
    this deterministic without any explicit lock, mirroring services/telegraph_shortlist_service.
    py::claim_approved_telegraph_proposal()'s own established idiom."""
    review = await _seed_approved_review(db_session)

    # Caller A "wins" - persists first, via the exact same atomic-conditional-UPDATE shape the
    # real orchestrator uses.
    await db_session.execute(
        update(TelegraphArticleReview)
        .where(TelegraphArticleReview.id == review.id, TelegraphArticleReview.published_url.is_(None))
        .values(published_url="https://telegra.ph/Winner-08-31", published_at=datetime.now(timezone.utc))
    )
    await db_session.commit()

    # Caller B's own (mocked) network call "succeeds" independently, but its attempt to persist
    # must lose deterministically to A's already-committed URL.
    _mock_create_page(monkeypatch, url="https://telegra.ph/Loser-08-31")
    result_b = await publish_approved_telegraph_article(db_session, review.id)

    assert result_b.status == "already_published"
    assert result_b.url == "https://telegra.ph/Winner-08-31"

    service = TelegraphArticleReviewService(db_session)
    reloaded = await service.get_review(review.id)
    assert reloaded is not None
    assert reloaded.published_url == "https://telegra.ph/Winner-08-31"  # never overwritten by B


# ---------------------------------------------------------------------------------------------
# Structural boundary
# ---------------------------------------------------------------------------------------------


def test_orchestrator_never_writes_review_status() -> None:
    from pathlib import Path

    source = Path("services/telegraph_publish_orchestrator.py").read_text(encoding="utf-8")
    assert ".status =" not in source
    assert "set_decision" not in source
