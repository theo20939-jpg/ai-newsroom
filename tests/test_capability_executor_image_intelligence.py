"""Tests for capabilities.executor.CapabilityExecutor's Phase 16 M1 Image Intelligence hook
(docs/phase16_m1_native_media_ingestion_report.md). Real Postgres, transaction rolled back per
test (tests/conftest.py's db_session fixture) - mirrors tests/test_capability_executor.py's own
established pattern exactly, using fake Capability implementations, never a real LLMGateway.
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.editorial_task import TaskPriority
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from schemas.capability import CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowDefinition, WorkflowRetryPolicy, WorkflowStepDefinition, WorkflowType
from services import workflow_service
from capabilities.executor import CapabilityExecutor
from capabilities.registry import CapabilityRegistry
from workflows.registry import WorkflowRegistry
from workflows.runner import WorkflowRunner


class _FakeCopywritingCapability:
    """Production-shaped copywriting output - title/body/hashtags, exactly what
    services/content_draft_service.py reads."""

    async def execute(self, context):
        now = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS",
            structured_output={"title": "A drafted title", "body": "A drafted body", "hashtags": ["#news"]},
            calls=[],
            started_at=now,
            finished_at=now,
            duration_seconds=0.0,
        )


class _FakeQualityCapability:
    async def execute(self, context):
        now = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS", structured_output={"approved": True}, calls=[], started_at=now, finished_at=now,
            duration_seconds=0.0,
        )


class _AlwaysRaisesDuringExecute:
    async def execute(self, context):
        raise RuntimeError("should never reach here - only used to prove the hook itself is isolated")


def _capability_definition(name: str) -> CapabilityDefinition:
    return CapabilityDefinition(
        name=name, version=1, config=CapabilityConfig(timeout_seconds=10),
        required_context=["news_event"], expected_output_keys=["ok"],
    )


def _workflow_registry(*step_names: str) -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(
        WorkflowDefinition(
            name=WorkflowType.CONTENT_GENERATION,
            version=1,
            steps=[
                WorkflowStepDefinition(name=name, capability=name, timeout_seconds=10) for name in step_names
            ],
            max_iterations=3,
            retry_policy=WorkflowRetryPolicy(max_attempts=3, retryable_error_types=["StepExecutionError"]),
            timeout_seconds=60,
            required_input=["event_id"],
            expected_output=["result"],
        )
    )
    registry.seal()
    return registry


def _capability_registry(**capabilities) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for name, capability in capabilities.items():
        registry.register(_capability_definition(name), capability)
    registry.seal()
    return registry


async def _event_with_content(session: AsyncSession, content: str, source_type: SourceType = SourceType.RSS) -> NewsEvent:
    source = NewsSource(name="Test", type=source_type, url="https://example.com/feed", active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        source_id=source.id, title="Event", content=content, url="https://example.com/article",
        category=EventCategory.AI, hash=f"hash-{uuid.uuid4()}",
    )
    session.add(event)
    await session.flush()
    return event


async def _run_copywriting(
    db_session: AsyncSession, event: NewsEvent, capability=None
) -> "list":
    workflow_registry = _workflow_registry("copywriting")
    command = EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B)
    task = await workflow_service.create_task(db_session, command, registry=workflow_registry)
    capability_registry = _capability_registry(copywriting=capability or _FakeCopywritingCapability())
    executor = CapabilityExecutor(db_session, task.id, capability_registry)
    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)
    return result.step_results


@pytest.mark.asyncio
async def test_mode_off_preserves_previous_workflow_behavior(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    monkeypatch.setattr(settings, "image_intelligence_mode", "off")
    event = await _event_with_content(db_session, "<img src='https://x/y.jpg'>")

    step_results = await _run_copywriting(db_session, event)

    assert "image_intelligence" not in step_results[0].result
    assert step_results[0].result == {"title": "A drafted title", "body": "A drafted body", "hashtags": ["#news"]}


@pytest.mark.asyncio
async def test_mode_shadow_records_candidates(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    monkeypatch.setattr(settings, "image_intelligence_mode", "shadow")
    event = await _event_with_content(db_session, '<p>Body <img src="https://cdn.example.com/real.jpg"/></p>')

    step_results = await _run_copywriting(db_session, event)

    assert "image_intelligence" in step_results[0].result
    payload = step_results[0].result["image_intelligence"]
    assert payload["mode"] == "shadow"
    assert payload["candidates_discovered"] == 1
    assert payload["candidates"][0]["remote_url"] == "https://cdn.example.com/real.jpg"


@pytest.mark.asyncio
async def test_shadow_mode_does_not_change_drafted_text_fields(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    monkeypatch.setattr(settings, "image_intelligence_mode", "shadow")
    event = await _event_with_content(db_session, '<img src="https://cdn.example.com/a.jpg"/>')

    step_results = await _run_copywriting(db_session, event)

    assert step_results[0].result["title"] == "A drafted title"
    assert step_results[0].result["body"] == "A drafted body"
    assert step_results[0].result["hashtags"] == ["#news"]


@pytest.mark.asyncio
async def test_events_with_no_media_metadata_remain_compatible(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """Telegram (and any pre-Phase-16-collected) events have no HTML in `content` - the workflow
    must complete normally with zero candidates, not fail or behave differently."""
    monkeypatch.setattr(settings, "image_intelligence_mode", "shadow")
    event = await _event_with_content(db_session, "Just plain text, no HTML at all.", source_type=SourceType.TELEGRAM)

    step_results = await _run_copywriting(db_session, event)

    assert step_results[0].status == "SUCCESS"
    assert step_results[0].result["image_intelligence"]["candidates_discovered"] == 0


@pytest.mark.asyncio
async def test_image_intelligence_attach_failure_does_not_fail_the_step(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    monkeypatch.setattr(settings, "image_intelligence_mode", "shadow")
    monkeypatch.setattr(
        "capabilities.executor.reconstruct_hints_from_content",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    event = await _event_with_content(db_session, '<img src="https://cdn.example.com/a.jpg"/>')

    step_results = await _run_copywriting(db_session, event)

    assert step_results[0].status == "SUCCESS"
    assert step_results[0].result["title"] == "A drafted title"  # copywriting's own output intact
    assert "image_intelligence" not in step_results[0].result  # attach failed, swallowed


@pytest.mark.asyncio
async def test_image_intelligence_only_runs_for_the_copywriting_step(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """Proves the "quality"/"scoring" steps (Fact Safety / Editorial Scoring V2's own hooks) are
    structurally untouched - the image_intelligence hook only ever fires on `step.capability ==
    "copywriting"`."""
    monkeypatch.setattr(settings, "image_intelligence_mode", "shadow")
    event = await _event_with_content(db_session, '<img src="https://cdn.example.com/a.jpg"/>')

    workflow_registry = _workflow_registry("copywriting", "quality")
    command = EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B)
    task = await workflow_service.create_task(db_session, command, registry=workflow_registry)
    capability_registry = _capability_registry(copywriting=_FakeCopywritingCapability(), quality=_FakeQualityCapability())
    executor = CapabilityExecutor(db_session, task.id, capability_registry)
    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    copywriting_result, quality_result = result.step_results
    assert "image_intelligence" in copywriting_result.result
    assert "image_intelligence" not in quality_result.result
