"""Phase 18 final acceptance - Stage E: DB-backed integration tests against a real PostgreSQL
connection (docs/phase18_final_acceptance_db_integration_report.md).

Two groups:
1. `MemeCandidateService` full lifecycle (create/fetch/cost-accumulation/decision-recording/
   idempotency/missing-row/feedback-summary/FK-enforcement) against real transactions.
2. `_attach_meme_opportunity`/`_attach_meme_safety_originality` executor-hook integration,
   mirroring `tests/test_phase17_m5_integration.py`'s exact proven shape (real
   `CapabilityExecutor` + `WorkflowRunner`, `tests/conftest.py`'s `db_session` fixture - real
   Postgres, rolled back at teardown via savepoints, so nothing here is ever actually persisted).

These were not runnable in the M0-M9 development session (no reachable Postgres/Redis) - this
file is the acceptance-time closure of that disclosed gap.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.executor import CapabilityExecutor
from capabilities.registry import CapabilityRegistry
from core.config import settings
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.meme_candidate import MemeCandidate, MemeCandidateStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from schemas.capability import CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition
from schemas.editorial_task import EditorialTaskCreate
from schemas.meme_concept import MemeConcept, MemeFormat
from schemas.meme_feedback import MemeRejectionReason
from schemas.workflow import WorkflowDefinition, WorkflowRetryPolicy, WorkflowStepDefinition, WorkflowType
from services import workflow_service
from services.meme_candidate_service import MemeCandidateService
from workflows.registry import WorkflowRegistry
from workflows.runner import WorkflowRunner

_VALID_CONCEPT_OUTPUT = {
    "premise": "An AI company insists AI won't take jobs.",
    "setup": "The CEO reassures workers during a keynote.",
    "punchline": "Meanwhile the CEO's own job is the one AI can't replace.",
    "humor_mechanism": "self_referential_irony",
    "visual_scene": "A CEO on stage pointing at a slide reading 'Jobs are safe'.",
    "characters_objects": ["CEO", "presentation slide"],
    "text_overlay_intent": "Contrast reassurance with public skepticism.",
    "source_fact_links": ["The CEO publicly stated AI is not destroying jobs."],
    "forbidden_interpretations": [],
    "meme_format": "classic_top_bottom",
}


async def _event_with_content(
    session: AsyncSession, content: str | None, title: str = "Nvidia CEO insists AI is not destroying jobs",
    category: EventCategory = EventCategory.AI,
) -> NewsEvent:
    source = NewsSource(name="Test", type=SourceType.RSS, url="https://example.com/feed", active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        source_id=source.id, title=title, content=content, url="https://example.com/article",
        category=category, hash=f"hash-{uuid.uuid4()}",
    )
    session.add(event)
    await session.flush()
    return event


# ---------------------------------------------------------------------------
# MemeCandidateService - full lifecycle against real Postgres
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_meme_candidate_full_lifecycle(db_session: AsyncSession) -> None:
    event = await _event_with_content(db_session, "Real content describing the event.")
    task = EditorialTask(event_id=event.id, priority=TaskPriority.B, status=TaskStatus.RUNNING)
    db_session.add(task)
    await db_session.flush()

    concept = MemeConcept(
        premise="p", setup="s", punchline="pl", humor_mechanism="irony", visual_scene="scene",
        characters_objects=["a"], text_overlay_intent="intent", source_fact_links=["fact"],
        forbidden_interpretations=[], meme_format=MemeFormat.CLASSIC_TOP_BOTTOM,
    )
    service = MemeCandidateService(db_session)

    candidate = await service.create_from_concept(news_event_id=event.id, editorial_task_id=task.id, concept=concept)
    assert candidate.status == MemeCandidateStatus.CONCEPT_GENERATED

    fetched = await service.get_by_id(candidate.id)
    assert fetched is not None
    assert fetched.concept_data["premise"] == "p"

    await service.add_cost(candidate.id, Decimal("0.0012"))
    await service.add_cost(candidate.id, Decimal("0.0008"))
    after_cost = await service.get_by_id(candidate.id)
    assert after_cost is not None
    assert after_cost.cumulative_cost_usd == Decimal("0.002000")

    with pytest.raises(ValueError):
        await service.add_cost(candidate.id, Decimal("-1"))

    decided = await service.record_editor_decision(
        candidate.id, "rejected", reasons=[MemeRejectionReason.STALE], notes="Too old by the time reviewed.",
    )
    assert decided is not None
    assert decided.status == MemeCandidateStatus.REJECTED
    assert decided.editor_decision_reasons == ["stale"]
    assert decided.editor_decision_notes == "Too old by the time reviewed."

    # Idempotent re-decision - no error, no duplicate row.
    decided_again = await service.record_editor_decision(candidate.id, "rejected", reasons=[MemeRejectionReason.STALE])
    assert decided_again is not None
    assert decided_again.id == candidate.id

    summary = await service.build_feedback_summary(candidate.id)
    assert summary is not None
    assert summary.editor_decision_reasons == ["stale"]
    assert summary.published is False
    assert summary.cumulative_cost_usd == "0.002000"


@pytest.mark.asyncio
async def test_record_editor_decision_missing_candidate_returns_none(db_session: AsyncSession) -> None:
    service = MemeCandidateService(db_session)
    result = await service.record_editor_decision(uuid.uuid4(), "approved")
    assert result is None


@pytest.mark.asyncio
async def test_add_cost_missing_candidate_returns_none(db_session: AsyncSession) -> None:
    service = MemeCandidateService(db_session)
    result = await service.add_cost(uuid.uuid4(), Decimal("1"))
    assert result is None


@pytest.mark.asyncio
async def test_get_by_id_missing_candidate_returns_none(db_session: AsyncSession) -> None:
    service = MemeCandidateService(db_session)
    result = await service.get_by_id(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_build_feedback_summary_missing_candidate_returns_none(db_session: AsyncSession) -> None:
    service = MemeCandidateService(db_session)
    result = await service.build_feedback_summary(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_invalid_news_event_id_is_rejected_by_foreign_key(db_session: AsyncSession) -> None:
    """Real FK enforcement, not merely a Python-level check - proves the migration's declared
    foreign key is actually enforced by Postgres, not just present in the model."""
    candidate = MemeCandidate(
        news_event_id=uuid.uuid4(), status=MemeCandidateStatus.CONCEPT_GENERATED,
        concept_schema_version="v1", concept_data={"premise": "p"},
    )
    db_session.add(candidate)
    with pytest.raises(Exception):
        await db_session.flush()


@pytest.mark.asyncio
async def test_repeated_decision_without_notes_overwrites_prior_notes(db_session: AsyncSession) -> None:
    """Documents real, observed behavior found during acceptance testing (not a bug fix - matches
    record_editor_decision()'s own documented 'overwrites the prior decision fields' contract):
    a second record_editor_decision() call that omits `notes` clears any notes recorded by an
    earlier call, rather than preserving them. No production caller passes partial updates today
    (docs/phase18_final_acceptance_db_integration_report.md), but a future caller must supply the
    full desired reasons/notes on every call, not just deltas."""
    event = await _event_with_content(db_session, "Content.")
    service = MemeCandidateService(db_session)
    concept = MemeConcept(
        premise="p", setup="s", punchline="pl", humor_mechanism="irony", visual_scene="scene",
        characters_objects=[], text_overlay_intent="intent", source_fact_links=["fact"],
        forbidden_interpretations=[], meme_format=MemeFormat.CLASSIC_TOP_BOTTOM,
    )
    candidate = await service.create_from_concept(news_event_id=event.id, editorial_task_id=None, concept=concept)  # type: ignore[arg-type]

    await service.record_editor_decision(candidate.id, "rejected", notes="Original note.")
    second = await service.record_editor_decision(candidate.id, "rejected")
    assert second is not None
    assert second.editor_decision_notes is None


# ---------------------------------------------------------------------------
# _attach_meme_opportunity - executor hook integration (mirrors
# tests/test_phase17_m5_integration.py's exact proven shape)
# ---------------------------------------------------------------------------


class _FakeQualityCapability:
    async def execute(self, context):
        now = datetime.now(timezone.utc)
        return CapabilityResult(status="SUCCESS", structured_output={"passed": True, "issues": []}, calls=[], started_at=now, finished_at=now, duration_seconds=0.0)


def _single_step_workflow_registry(workflow_type: WorkflowType, capability_name: str) -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(
        WorkflowDefinition(
            name=workflow_type, version=1,
            steps=[WorkflowStepDefinition(name=capability_name, capability=capability_name, timeout_seconds=10)],
            max_iterations=3, retry_policy=WorkflowRetryPolicy(max_attempts=3, retryable_error_types=["StepExecutionError"]),
            timeout_seconds=60, required_input=["event_id"], expected_output=["result"],
        )
    )
    registry.seal()
    return registry


def _single_capability_registry(capability_name: str, capability) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(
        CapabilityDefinition(
            name=capability_name, version=1, config=CapabilityConfig(timeout_seconds=10),
            required_context=["news_event"], expected_output_keys=["ok"],
        ),
        capability,
    )
    registry.seal()
    return registry


async def _run_single_step_workflow(
    db_session: AsyncSession, event: NewsEvent, workflow_type: WorkflowType, capability_name: str, capability,
):
    workflow_registry = _single_step_workflow_registry(workflow_type, capability_name)
    command = EditorialTaskCreate(event_id=event.id, workflow_type=workflow_type, priority=TaskPriority.B)
    task = await workflow_service.create_task(db_session, command, registry=workflow_registry)
    capability_registry = _single_capability_registry(capability_name, capability)
    executor = CapabilityExecutor(db_session, task.id, capability_registry)
    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)
    return result.step_results, task


@pytest.mark.asyncio
async def test_meme_opportunity_mode_off_writes_nothing(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    monkeypatch.setattr(settings, "meme_opportunity_mode", "off")
    event = await _event_with_content(db_session, "Some real content describing an event today.")
    step_results, _ = await _run_single_step_workflow(
        db_session, event, WorkflowType.CONTENT_GENERATION, "quality", _FakeQualityCapability(),
    )
    assert "meme_opportunity" not in step_results[0].result


@pytest.mark.asyncio
async def test_meme_opportunity_shadow_attaches_and_persists(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    monkeypatch.setattr(settings, "meme_opportunity_mode", "shadow")
    event = await _event_with_content(
        db_session, "The CEO publicly insists artificial intelligence is not destroying jobs, "
        "addressing growing anxiety among workers.",
    )
    step_results, task = await _run_single_step_workflow(
        db_session, event, WorkflowType.CONTENT_GENERATION, "quality", _FakeQualityCapability(),
    )
    assessment = step_results[0].result["meme_opportunity"]
    assert assessment["schema_version"] == "v1"
    assert assessment["decision"] in ("MEME_READY", "REVIEW", "NOT_SUITABLE", "SENSITIVE_BLOCK", "INSUFFICIENT_SOURCE")

    # Persisted into the durable EditorialTask.workflow JSON, not just the in-memory result.
    persisted = await db_session.get(EditorialTask, task.id)
    assert persisted is not None
    assert persisted.workflow["step_results"][0]["result"]["meme_opportunity"]["schema_version"] == "v1"


@pytest.mark.asyncio
async def test_meme_opportunity_hook_failure_does_not_fail_parent_step(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession,
) -> None:
    monkeypatch.setattr(settings, "meme_opportunity_mode", "shadow")

    def _broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("capabilities.executor.apply_meme_opportunity_shadow", _broken)
    event = await _event_with_content(db_session, "Content for the failure-isolation check.")
    step_results, _ = await _run_single_step_workflow(
        db_session, event, WorkflowType.CONTENT_GENERATION, "quality", _FakeQualityCapability(),
    )
    result = step_results[0]
    assert result.status == "SUCCESS"
    assert "meme_opportunity" not in result.result
    assert result.result["passed"] is True


@pytest.mark.asyncio
async def test_meme_opportunity_sensitive_content_blocked_end_to_end(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession,
) -> None:
    monkeypatch.setattr(settings, "meme_opportunity_mode", "shadow")
    event = await _event_with_content(
        db_session, "A man was shot by police deputies during a swatting incident and is now suing.",
        title="Man seeks millions after being shot by police in game-related swatting incident",
    )
    step_results, _ = await _run_single_step_workflow(
        db_session, event, WorkflowType.CONTENT_GENERATION, "quality", _FakeQualityCapability(),
    )
    assessment = step_results[0].result["meme_opportunity"]
    assert assessment["decision"] == "SENSITIVE_BLOCK"


# ---------------------------------------------------------------------------
# _attach_meme_safety_originality - executor hook integration
# ---------------------------------------------------------------------------


class _FakeMemeConceptCapability:
    async def execute(self, context):
        now = datetime.now(timezone.utc)
        return CapabilityResult(status="SUCCESS", structured_output=dict(_VALID_CONCEPT_OUTPUT), calls=[], started_at=now, finished_at=now, duration_seconds=0.0)


@pytest.mark.asyncio
async def test_meme_safety_gate_mode_off_writes_nothing(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    monkeypatch.setattr(settings, "meme_safety_gate_mode", "off")
    event = await _event_with_content(db_session, "Some content.")
    step_results, _ = await _run_single_step_workflow(
        db_session, event, WorkflowType.MEME_GENERATION, "meme_concept", _FakeMemeConceptCapability(),
    )
    assert "meme_safety_originality" not in step_results[0].result


@pytest.mark.asyncio
async def test_meme_safety_gate_shadow_attaches_and_persists(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    monkeypatch.setattr(settings, "meme_safety_gate_mode", "shadow")
    event = await _event_with_content(db_session, "Some content.")
    step_results, task = await _run_single_step_workflow(
        db_session, event, WorkflowType.MEME_GENERATION, "meme_concept", _FakeMemeConceptCapability(),
    )
    assessment = step_results[0].result["meme_safety_originality"]
    assert assessment["schema_version"] == "v1"
    assert assessment["gate_decision"] in ("PASS", "REVIEW", "BLOCK")

    persisted = await db_session.get(EditorialTask, task.id)
    assert persisted is not None
    assert persisted.workflow["step_results"][0]["result"]["meme_safety_originality"]["schema_version"] == "v1"


@pytest.mark.asyncio
async def test_meme_safety_gate_hook_failure_does_not_fail_parent_step(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession,
) -> None:
    monkeypatch.setattr(settings, "meme_safety_gate_mode", "shadow")

    def _broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("capabilities.executor.apply_meme_safety_originality_shadow", _broken)
    event = await _event_with_content(db_session, "Content for the failure-isolation check.")
    step_results, _ = await _run_single_step_workflow(
        db_session, event, WorkflowType.MEME_GENERATION, "meme_concept", _FakeMemeConceptCapability(),
    )
    result = step_results[0]
    assert result.status == "SUCCESS"
    assert "meme_safety_originality" not in result.result
    # The real MemeConceptCapability's own output fields must survive untouched.
    assert result.result["premise"] == _VALID_CONCEPT_OUTPUT["premise"]


@pytest.mark.asyncio
async def test_no_ai_execution_rows_written_by_deterministic_hooks(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession,
) -> None:
    """Both M1's and M3's hooks are zero-LLM-call by design - proves no AIExecution row is
    created merely by running them (the fake capabilities used here also record no calls, so
    this proves the hooks themselves add none on top)."""
    from sqlalchemy import func, select

    from database.models.ai_execution import AIExecution

    monkeypatch.setattr(settings, "meme_opportunity_mode", "shadow")
    monkeypatch.setattr(settings, "meme_safety_gate_mode", "shadow")
    event = await _event_with_content(db_session, "Content for the zero-AIExecution check.")
    await _run_single_step_workflow(db_session, event, WorkflowType.CONTENT_GENERATION, "quality", _FakeQualityCapability())
    await _run_single_step_workflow(db_session, event, WorkflowType.MEME_GENERATION, "meme_concept", _FakeMemeConceptCapability())

    count = (await db_session.execute(select(func.count()).select_from(AIExecution))).scalar_one()
    assert count == 0
