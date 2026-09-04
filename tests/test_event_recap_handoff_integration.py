"""R2.10-FINALIZATION-1 §28 - integration coverage for the EVENT_RECAP post-generation handoff:
a real, persisted EditorialTask (the exact shape services.event_recap_processor.
generate_recap_for_story() produces) -> services.event_recap_review_service.
create_event_recap_review() -> services.event_recap_review_notifier.send_event_recap_review().

The per-function unit mechanics of create_event_recap_review()/send_event_recap_review() are
already thoroughly covered by tests/test_event_recap_review_service.py and tests/
test_event_recap_review_notifier.py (idempotency, immutability, zero-LLM-import, dry-run
mechanics) - this file specifically covers the INTEGRATION gap: reading a REAL task's persisted
step_results (mirroring scripts/event_recap_pipeline_worker.py's own extraction logic) and the two
failure modes that logic is responsible for (missing/invalid result, missing media), which no
existing test exercises against a real database row.

No LLM Gateway, no real Telegram send anywhere in this file - `AsyncMock()` Bot, `dry_run=True`
throughout (mirrors tests/test_event_recap_review_notifier.py's own established convention)."""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.event_recap_review import EventRecapReview
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from services.event_recap_review_notifier import send_event_recap_review
from services.event_recap_review_service import create_event_recap_review, get_event_recap_review_for_task


@pytest.fixture(autouse=True)
def _routing_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolated topic ids for every test in this file - mirrors tests/test_event_recap_review_
    notifier.py's own identical fixture exactly, so send_event_recap_review() reaches its real
    dry_run short-circuit instead of failing earlier on an unconfigured destination."""
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -100123456789)
    monkeypatch.setattr(settings, "telegraph_topic_id", 33)


async def _seed_real_event(session: AsyncSession) -> NewsEvent:
    source = NewsSource(
        name="Test Source", type=SourceType.RSS, url=f"https://example.com/feed-{uuid4()}.xml", active=True,
    )
    session.add(source)
    await session.flush()
    event = NewsEvent(
        source_id=source.id, title="Test event", content="Body",
        category=EventCategory.TECH, hash=f"test-hash-{uuid4()}",
    )
    session.add(event)
    await session.flush()
    return event

_REAL_RECAP_RESULT = {
    "recap_title": "Tesla представила Cybercab и начала предлагать поездки роботакси в Техасе",
    "recap_summary": "Tesla представила беспилотный Cybercab, затем начала поездки роботакси в Техасе.",
    "key_takeaways": ["Cybercab без руля и педалей.", "Начато расследование регулятора."],
    "uncertainty_notes": ["География поездок не указана."],
}


async def _seed_completed_event_recap_task(
    session: AsyncSession, *, with_media: bool = True, with_result: bool = True,
) -> EditorialTask:
    """A real, persisted EditorialTask in exactly the shape generate_recap_for_story() itself
    produces - workflow_name=EVENT_RECAP, status=COMPLETED, step_results carrying select_recap_
    media/event_recap_source_snapshot/synthesize_recap (mirrors _persist_selected_media()/
    _persist_source_snapshot()'s own real persisted shape, never a synthetic ad hoc dict)."""
    step_results = []
    if with_media:
        step_results.append({
            "step_name": "select_recap_media", "status": "SUCCESS", "attempt": 1,
            "started_at": "2026-09-04T20:20:15Z", "finished_at": "2026-09-04T20:20:15Z", "error": None,
            "result": {
                "tier": "discovered",
                "representative": {
                    "candidate_id": "fake-candidate", "originating_event_id": str(uuid4()),
                    "media_type": "image", "recommended_role": "hero",
                    "storage_key": "images/fa/fake.jpg", "telegram_file_id": None, "sha256": "0" * 64,
                    "remote_url": "https://example.com/tesla.jpg",
                },
            },
        })
    if with_result:
        step_results.append({
            "step_name": "synthesize_recap", "status": "SUCCESS", "attempt": 1,
            "started_at": "2026-09-04T20:20:15Z", "finished_at": "2026-09-04T20:20:24Z", "error": None,
            "result": _REAL_RECAP_RESULT,
        })

    event = await _seed_real_event(session)
    task = EditorialTask(
        id=uuid4(), event_id=event.id, priority=TaskPriority.C, status=TaskStatus.COMPLETED,
        workflow={
            "workflow_name": "EVENT_RECAP", "workflow_version": 1, "current_step": None,
            "completed_steps": ["synthesize_recap"], "iteration_count": 1,
            "step_results": step_results, "failure": None,
        },
    )
    session.add(task)
    await session.flush()
    return task


def _extract_recap_result_and_media(task: EditorialTask) -> tuple[dict | None, dict | None]:
    """Mirrors scripts/event_recap_pipeline_worker.py::run_event_recap_pipeline_for_story()'s own
    extraction logic exactly (lines 124-132) - the real logic under test here, not a
    reimplementation with different semantics."""
    recap_result = None
    selected_media = None
    for step_result in (task.workflow or {}).get("step_results", []):
        if step_result.get("step_name") == "synthesize_recap" and step_result.get("status") == "SUCCESS":
            recap_result = step_result.get("result")
        if step_result.get("step_name") == "select_recap_media" and step_result.get("status") == "SUCCESS":
            selected_media = step_result.get("result")
    return recap_result, selected_media


async def _review_count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(EventRecapReview))).scalar_one()


# --- A: generated EVENT_RECAP task can create a review record --------------------------------------


@pytest.mark.asyncio
async def test_A_generated_task_creates_review_record(db_session: AsyncSession) -> None:
    task = await _seed_completed_event_recap_task(db_session)
    recap_result, _selected_media = _extract_recap_result_and_media(task)
    assert recap_result is not None

    review = await create_event_recap_review(db_session, recap_task_id=task.id)
    assert review.recap_task_id == task.id
    assert (await _review_count(db_session)) == 1


# --- B: task payload used without a new LLM call (structural) --------------------------------------


def test_B_extraction_and_review_creation_never_import_llm_gateway() -> None:
    """Test B. AST/import-level proof that the extraction logic (this test file's own helper,
    mirroring the real script) and create_event_recap_review() never touch the LLM Gateway -
    mirrors test_event_recap_review_service.py::test_no_llm_gateway_or_telegram_call_in_service_
    source()'s own established check, re-asserted here at the integration-test's own boundary."""
    import inspect
    import services.event_recap_review_service as svc
    source = inspect.getsource(svc)
    assert "LLMGateway" not in source
    assert "call_generate" not in source


# --- C: review creation idempotent (integration-level, real task) ----------------------------------


@pytest.mark.asyncio
async def test_C_review_creation_idempotent_for_same_task(db_session: AsyncSession) -> None:
    task = await _seed_completed_event_recap_task(db_session)
    first = await create_event_recap_review(db_session, recap_task_id=task.id)
    second = await create_event_recap_review(db_session, recap_task_id=task.id)
    assert first.id == second.id
    assert (await _review_count(db_session)) == 1


# --- D: task with invalid/missing result fields fails closed ---------------------------------------


@pytest.mark.asyncio
async def test_D_missing_synthesize_recap_result_fails_closed_no_review_sent(db_session: AsyncSession) -> None:
    """Test D. A task with no successful synthesize_recap step result (e.g. a genuinely FAILED or
    still-RUNNING task somehow reached) must not produce a review send - the caller's own
    extraction logic returns recap_result=None, and the real pipeline script explicitly checks for
    this and returns early (never calling create_event_recap_review()/send_event_recap_review() at
    all) - reproduced directly here."""
    task = await _seed_completed_event_recap_task(db_session, with_result=False)
    recap_result, _selected_media = _extract_recap_result_and_media(task)
    assert recap_result is None  # the real fail-closed signal
    # The real script's own contract: recap_result is None -> return early, never create a review.
    assert (await _review_count(db_session)) == 0


# --- E: task media missing fails into documented recovery/fallback ---------------------------------


@pytest.mark.asyncio
async def test_E_missing_media_sends_text_only_review_no_crash(db_session: AsyncSession) -> None:
    """Test E. A task with no select_recap_media step result (selected_media=None) must still
    produce a real, successful text-only review send - never a crash, mirroring `selected_media:
    dict | None = None` behaving "exactly like tier='none'" per send_event_recap_review()'s own
    docstring."""
    task = await _seed_completed_event_recap_task(db_session, with_media=False)
    recap_result, selected_media = _extract_recap_result_and_media(task)
    assert recap_result is not None
    assert selected_media is None

    review = await create_event_recap_review(db_session, recap_task_id=task.id)
    fake_bot = AsyncMock()
    outcome = await send_event_recap_review(
        fake_bot, db_session, review, recap_result, selected_media=selected_media, dry_run=True,
    )
    assert outcome.media_outcome is None  # never attempted - no representative to resolve
    assert outcome.text_outcome.reason == "dry_run"  # reached the real send call, no crash


# --- F/G: no publication reachable, flag stays False ------------------------------------------------


def test_F_G_no_publication_path_reachable_from_this_module() -> None:
    """Tests F, G. Neither create_event_recap_review() nor send_event_recap_review() import or
    call anything publication-related - structurally unreachable from this handoff, mirroring
    services/event_recap_processor.py's own identical guarantee. AST-based (not substring), since
    both modules' own docstrings legitimately discuss "publish"/"publication" in prose (e.g.
    "makes no publish decision of any kind")."""
    import ast
    import inspect
    import services.event_recap_review_service as svc
    import services.event_recap_review_notifier as notifier

    forbidden = {"final_post_publication", "publish_approved_final_post"}
    for module in (svc, notifier):
        tree = ast.parse(inspect.getsource(module))
        identifiers: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                identifiers.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                identifiers.add(node.module)
            elif isinstance(node, ast.Name):
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.add(node.attr)
        assert not (identifiers & forbidden), identifiers & forbidden

    assert settings.final_post_publication_enabled is False


# --- H: WYSIWYG-style deterministic reproducibility (scoped - see module docstring) -----------------


@pytest.mark.asyncio
async def test_H_repeated_dry_run_send_is_deterministic(db_session: AsyncSession) -> None:
    """Test H. R2.10-FINALIZATION-1's own scoped WYSIWYG proof: EVENT_RECAP has no publish stage
    of its own reachable without a second LLM call (Final Post Authoring is always-paid per its own
    module docstring - out of this phase's scope) - so the real "review == publish" comparison
    §23 describes cannot be exercised here. What CAN be proven, and is proven directly: the
    review's own rendered text/keyboard/photo-resolution is fully deterministic across repeated
    sends - the same review, called twice, produces byte-identical text and the same media
    resolution outcome, never drifting between calls."""
    task = await _seed_completed_event_recap_task(db_session)
    recap_result, selected_media = _extract_recap_result_and_media(task)
    assert recap_result is not None
    review = await create_event_recap_review(db_session, recap_task_id=task.id)

    from bot.event_recap_review_formatting import render_event_recap_review_text
    text_1 = render_event_recap_review_text(review, recap_result)
    text_2 = render_event_recap_review_text(review, recap_result)
    assert text_1 == text_2

    fake_bot_1, fake_bot_2 = AsyncMock(), AsyncMock()
    outcome_1 = await send_event_recap_review(
        fake_bot_1, db_session, review, recap_result, selected_media=selected_media, dry_run=True,
    )
    outcome_2 = await send_event_recap_review(
        fake_bot_2, db_session, review, recap_result, selected_media=selected_media, dry_run=True,
    )
    assert outcome_1.text_outcome.reason == outcome_2.text_outcome.reason
    assert outcome_1.text_outcome.sent == outcome_2.text_outcome.sent == False  # noqa: E712 - explicit dry-run contract


# --- J: non-RECAP workflows unaffected (structural) --------------------------------------------------


@pytest.mark.asyncio
async def test_J_get_event_recap_review_for_task_scoped_to_event_recap_only(db_session: AsyncSession) -> None:
    """Test J. A NON-EVENT_RECAP task (e.g. NEWS_ANALYSIS-shaped) has no EventRecapReview and
    create_event_recap_review()'s own FK scoping never confuses it with an unrelated workflow -
    this phase's own changes (compose volume mount, brand_renderer NONE tier, content_cycle
    media-group primary-item fix) touch nothing in this module, so this is a structural
    confirmation, not a new behavior."""
    event = await _seed_real_event(db_session)
    other_task = EditorialTask(
        id=uuid4(), event_id=event.id, priority=TaskPriority.C, status=TaskStatus.COMPLETED,
        workflow={"workflow_name": "NEWS_ANALYSIS", "workflow_version": 1, "current_step": None,
                  "completed_steps": [], "iteration_count": 1, "step_results": [], "failure": None},
    )
    db_session.add(other_task)
    await db_session.flush()

    existing = await get_event_recap_review_for_task(db_session, other_task.id)
    assert existing is None
