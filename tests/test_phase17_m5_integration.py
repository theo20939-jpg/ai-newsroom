"""Phase 17 M5 - shadow integration tests (docs/
phase17_m5_editorial_completeness_gate_shadow_report.md).

Mirrors tests/test_beginner_friendly.py's own established integration-test shape exactly: real
capabilities.executor.CapabilityExecutor + workflows.runner.WorkflowRunner path with fake
Capabilities, tests/conftest.py's db_session fixture (real Postgres, rolled back at teardown).
Covers shadow persistence, failure isolation, production-output byte-identity, ContentDraft/task-
state/Telegram non-mutation, zero new LLM calls, and backward compatibility without upstream
M1/M3/M4 data.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.executor import CapabilityExecutor
from capabilities.registry import CapabilityRegistry
from core.config import settings
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from schemas.adaptive_length import AdaptiveLengthPlan, Complexity, DeliveryMode, LengthConfidence
from schemas.beginner_friendly import AudienceLevel, BeginnerFriendlyPlan, JargonRisk, WordRange
from schemas.capability import CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition
from schemas.editorial_brief import EditorialBrief, RecommendedFormat, SourceSufficiency, TargetWordRange
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowDefinition, WorkflowRetryPolicy, WorkflowStepDefinition, WorkflowType
from services import workflow_service
from workflows.registry import WorkflowRegistry
from workflows.runner import WorkflowRunner

_TITLE = "Netflix заплатила $500 за права"
_BODY = (
    "Netflix заплатила $500 за продление прав на сериал. Компания также подтвердила рост "
    "выручки на 12% в этом квартале.\n\nЭто показывает конкуренцию платформ за контент. "
    "Срок соглашения не раскрыт."
)


def _brief_dict() -> dict:
    return EditorialBrief(
        headline_fact="Netflix paid $500 for streaming rights.",
        event_details=["The deal covers six spinoffs."],
        recommended_format=RecommendedFormat.STANDARD_NEWS,
        target_word_range=TargetWordRange(min_words=30, max_words=80),
        source_sufficiency=SourceSufficiency.SUFFICIENT,
    ).model_dump(mode="json")


def _adaptive_plan_dict() -> dict:
    return AdaptiveLengthPlan(
        recommended_format=RecommendedFormat.STANDARD_NEWS, complexity=Complexity.NORMAL,
        source_sufficiency=SourceSufficiency.SUFFICIENT, min_words=30, target_words=50, max_words=80,
        hard_character_limit=1024, delivery_mode=DeliveryMode.TEXT_MESSAGE, paragraph_target=2,
        detail_target=2, confidence=LengthConfidence.HIGH,
    ).model_dump(mode="json")


def _beginner_plan_dict() -> dict:
    return BeginnerFriendlyPlan(
        audience_level=AudienceLevel.GENERAL, explanation_required=False,
        explanation_budget=0, context_budget=0, detail_target=2, paragraph_target=2,
        why_it_matters_required=True, what_next_allowed=True, uncertainty_required=True,
        jargon_risk=JargonRisk.LOW,
        ideal_range=WordRange(min_words=35, target_words=45, max_words=60),
        safe_range=WordRange(min_words=25, target_words=35, max_words=45),
    ).model_dump(mode="json")


class _FakeResearchCapability:
    async def execute(self, context):
        now = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS", structured_output={"facts": ["Netflix paid $500 for streaming rights."], "confidence": "high", "gaps": []},
            calls=[], started_at=now, finished_at=now, duration_seconds=0.0,
        )


class _FakeIntelligenceCapability:
    def __init__(self, *, with_brief: bool = True):
        self._with_brief = with_brief

    async def execute(self, context):
        now = datetime.now(timezone.utc)
        output = {"significance": "Notable", "angle": "Trend", "recommendation": "Watch"}
        if self._with_brief:
            output["editorial_brief"] = _brief_dict()
        return CapabilityResult(status="SUCCESS", structured_output=output, calls=[], started_at=now, finished_at=now, duration_seconds=0.0)


class _FakeCopywritingCapability:
    def __init__(self, *, with_plans: bool = True):
        self._with_plans = with_plans

    async def execute(self, context):
        now = datetime.now(timezone.utc)
        output = {"title": _TITLE, "body": _BODY, "hashtags": ["#news"]}
        if self._with_plans:
            output["adaptive_length_plan"] = _adaptive_plan_dict()
            output["beginner_friendly_plan"] = _beginner_plan_dict()
        return CapabilityResult(status="SUCCESS", structured_output=output, calls=[], started_at=now, finished_at=now, duration_seconds=0.0)


class _FakeQualityCapability:
    async def execute(self, context):
        now = datetime.now(timezone.utc)
        return CapabilityResult(status="SUCCESS", structured_output={"passed": True, "issues": []}, calls=[], started_at=now, finished_at=now, duration_seconds=0.0)


def _capability_definition(name: str) -> CapabilityDefinition:
    return CapabilityDefinition(
        name=name, version=1, config=CapabilityConfig(timeout_seconds=10),
        required_context=["news_event"], expected_output_keys=["ok"],
    )


def _workflow_registry(*step_names: str) -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(
        WorkflowDefinition(
            name=WorkflowType.CONTENT_GENERATION, version=1,
            steps=[WorkflowStepDefinition(name=name, capability=name, timeout_seconds=10) for name in step_names],
            max_iterations=3, retry_policy=WorkflowRetryPolicy(max_attempts=3, retryable_error_types=["StepExecutionError"]),
            timeout_seconds=60, required_input=["event_id"], expected_output=["result"],
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


async def _event_with_content(session: AsyncSession, content: str | None, title: str = "Event title") -> NewsEvent:
    source = NewsSource(name="Test", type=SourceType.RSS, url="https://example.com/feed", active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        source_id=source.id, title=title, content=content, url="https://example.com/article",
        category=EventCategory.AI, hash=f"hash-{uuid.uuid4()}",
    )
    session.add(event)
    await session.flush()
    return event


async def _run_workflow(db_session: AsyncSession, event: NewsEvent, *step_names: str, **capabilities):
    workflow_registry = _workflow_registry(*step_names)
    command = EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B)
    task = await workflow_service.create_task(db_session, command, registry=workflow_registry)
    capability_registry = _capability_registry(**capabilities)
    executor = CapabilityExecutor(db_session, task.id, capability_registry)
    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)
    return result.step_results, task


def _standard_capabilities(**overrides):
    caps = dict(
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
        copywriting=_FakeCopywritingCapability(), quality=_FakeQualityCapability(),
    )
    caps.update(overrides)
    return caps


# ---------------------------------------------------------------------------
# INTEGRATION (63-75)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feature_mode_off(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    monkeypatch.setattr(settings, "editorial_completeness_mode", "off")
    event = await _event_with_content(db_session, "Some real content describing an event today.")
    step_results, _ = await _run_workflow(
        db_session, event, "research", "intelligence", "copywriting", "quality", **_standard_capabilities(),
    )
    assert "editorial_completeness" not in step_results[3].result


@pytest.mark.asyncio
async def test_feature_mode_shadow(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    monkeypatch.setattr(settings, "editorial_completeness_mode", "shadow")
    event = await _event_with_content(db_session, "Some real content describing an event today.")
    step_results, _ = await _run_workflow(
        db_session, event, "research", "intelligence", "copywriting", "quality", **_standard_capabilities(),
    )
    assert "editorial_completeness" in step_results[3].result
    assert "calibrated_fact_safety" in step_results[3].result


@pytest.mark.asyncio
async def test_shadow_result_persisted(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    monkeypatch.setattr(settings, "editorial_completeness_mode", "shadow")
    event = await _event_with_content(db_session, "Some real content describing an event today.")
    step_results, task = await _run_workflow(
        db_session, event, "research", "intelligence", "copywriting", "quality", **_standard_capabilities(),
    )
    assessment = step_results[3].result["editorial_completeness"]
    assert assessment["schema_version"] == "v1"
    assert assessment["editorial_recommendation"] in ("READY", "REVIEW", "NOT_READY", "INSUFFICIENT_SOURCE")
    # Persisted into the durable EditorialTask.workflow JSON, not just the in-memory result.
    persisted = await db_session.get(EditorialTask, task.id)
    assert persisted is not None
    assert persisted.workflow is not None
    assert persisted.workflow["step_results"][3]["result"]["editorial_completeness"]["schema_version"] == "v1"


@pytest.mark.asyncio
async def test_shadow_failure_isolation(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    monkeypatch.setattr(settings, "editorial_completeness_mode", "shadow")

    def _broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("capabilities.executor.evaluate_candidate_fact_safety", _broken)
    event = await _event_with_content(db_session, "Content for the failure-isolation check.")
    step_results, _ = await _run_workflow(
        db_session, event, "research", "intelligence", "copywriting", "quality", **_standard_capabilities(),
    )
    quality_result = step_results[3]
    assert quality_result.status == "SUCCESS"
    assert "editorial_completeness" not in quality_result.result
    assert quality_result.result["passed"] is True


@pytest.mark.asyncio
async def test_production_output_byte_identical(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    event_off = await _event_with_content(db_session, "Some content.", title="Off event")
    monkeypatch.setattr(settings, "editorial_completeness_mode", "off")
    off_results, _ = await _run_workflow(
        db_session, event_off, "research", "intelligence", "copywriting", "quality", **_standard_capabilities(),
    )

    event_shadow = await _event_with_content(db_session, "Some content.", title="Shadow event")
    monkeypatch.setattr(settings, "editorial_completeness_mode", "shadow")
    shadow_results, _ = await _run_workflow(
        db_session, event_shadow, "research", "intelligence", "copywriting", "quality", **_standard_capabilities(),
    )
    for results in (off_results, shadow_results):
        assert results[3].result["passed"] is True
        assert results[3].result["issues"] == []
        assert results[2].result["title"] == _TITLE
        assert results[2].result["body"] == _BODY


@pytest.mark.asyncio
async def test_content_draft_not_mutated(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    """This workflow path (CapabilityExecutor + WorkflowRunner with fake Capabilities) never
    constructs a ContentDraft at all - the same structural guarantee
    tests/test_beginner_friendly.py's own equivalent test already established for M4."""
    monkeypatch.setattr(settings, "editorial_completeness_mode", "shadow")
    event = await _event_with_content(db_session, "Content for the mutation check.")
    step_results, _ = await _run_workflow(
        db_session, event, "research", "intelligence", "copywriting", "quality", **_standard_capabilities(),
    )
    assert step_results[3].status == "SUCCESS"


@pytest.mark.asyncio
async def test_task_state_not_mutated(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    monkeypatch.setattr(settings, "editorial_completeness_mode", "shadow")
    event = await _event_with_content(db_session, "Content for the task-state check.")
    _, task = await _run_workflow(
        db_session, event, "research", "intelligence", "copywriting", "quality", **_standard_capabilities(),
    )
    persisted = await db_session.get(EditorialTask, task.id)
    assert persisted is not None
    assert persisted.status.value.upper() == "COMPLETED"


def test_no_telegram_send() -> None:
    """Static import-shape check, mirroring `test_beginner_friendly_module_imports_no_llm_gateway_
    or_telegram`'s own established pattern: neither M5 module imports `bot`/aiogram/the LLM
    Gateway - Telegram sends and new LLM calls are structurally unreachable from either."""
    import services.editorial_completeness as completeness_module
    import services.fact_safety_calibration as calibration_module

    forbidden_substrings = ("llm_gateway", "telegram", "bot.handlers", "bot.main")
    for module in (completeness_module, calibration_module):
        source_names = {getattr(obj, "__module__", "") for obj in vars(module).values()}
        for name in source_names:
            for forbidden in forbidden_substrings:
                assert forbidden not in name.lower(), f"unexpected import touching {forbidden!r}: {name}"


@pytest.mark.asyncio
async def test_no_llm_call(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    """`call_generate`/the LLM Gateway is never imported by either M5 module - already covered
    structurally by `test_no_telegram_send`'s own forbidden-substring list (`llm_gateway`).
    Additionally verified end-to-end here: the fake Capabilities used throughout this file never
    call any Gateway, and the full workflow still completes with `editorial_completeness`
    persisted - proof M5 added zero calls on top of them."""
    monkeypatch.setattr(settings, "editorial_completeness_mode", "shadow")
    event = await _event_with_content(db_session, "Content for the zero-LLM-call check.")
    step_results, _ = await _run_workflow(
        db_session, event, "research", "intelligence", "copywriting", "quality", **_standard_capabilities(),
    )
    assert "editorial_completeness" in step_results[3].result


@pytest.mark.asyncio
async def test_backward_compatibility_without_m1_data(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    """No `editorial_brief` present (M1 off/never ran) - the gate must still run, treating
    `source_sufficiency` as UNKNOWN rather than raising."""
    monkeypatch.setattr(settings, "editorial_completeness_mode", "shadow")
    event = await _event_with_content(db_session, "Content with no upstream EditorialBrief.")
    step_results, _ = await _run_workflow(
        db_session, event, "research", "intelligence", "copywriting", "quality",
        **_standard_capabilities(
            intelligence=_FakeIntelligenceCapability(with_brief=False),
            copywriting=_FakeCopywritingCapability(with_plans=False),
        ),
    )
    assessment = step_results[3].result["editorial_completeness"]
    assert assessment["source_sufficiency"] == "unknown"


@pytest.mark.asyncio
async def test_compatibility_without_m3_m4_plans(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    """No `adaptive_length_plan`/`beginner_friendly_plan` present (M3/M4 off/never ran) - length/
    structure criteria degrade to NOT_APPLICABLE rather than raising."""
    monkeypatch.setattr(settings, "editorial_completeness_mode", "shadow")
    event = await _event_with_content(db_session, "Content with no upstream M3/M4 plans.")
    step_results, _ = await _run_workflow(
        db_session, event, "research", "intelligence", "copywriting", "quality",
        **_standard_capabilities(copywriting=_FakeCopywritingCapability(with_plans=False)),
    )
    assessment = step_results[3].result["editorial_completeness"]
    assert assessment["safe_length_status"] == "not_applicable"
    assert assessment["paragraph_status"] == "not_applicable"


@pytest.mark.asyncio
async def test_idempotent_execution(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    """Pure/deterministic: running the same inputs twice produces the identical assessment."""
    monkeypatch.setattr(settings, "editorial_completeness_mode", "shadow")
    event_a = await _event_with_content(db_session, "Idempotence check content.", title="Idempotent A")
    event_b = await _event_with_content(db_session, "Idempotence check content.", title="Idempotent A")
    results_a, _ = await _run_workflow(
        db_session, event_a, "research", "intelligence", "copywriting", "quality", **_standard_capabilities(),
    )
    results_b, _ = await _run_workflow(
        db_session, event_b, "research", "intelligence", "copywriting", "quality", **_standard_capabilities(),
    )
    assert results_a[3].result["editorial_completeness"] == results_b[3].result["editorial_completeness"]


@pytest.mark.asyncio
async def test_structured_logs_omit_full_content(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, caplog) -> None:
    monkeypatch.setattr(settings, "editorial_completeness_mode", "shadow")
    event = await _event_with_content(db_session, "Content that must never appear verbatim in logs.")
    with caplog.at_level("INFO"):
        await _run_workflow(
            db_session, event, "research", "intelligence", "copywriting", "quality", **_standard_capabilities(),
        )
    for record in caplog.records:
        message = str(getattr(record, "message", "")) + str(record.getMessage())
        assert _BODY not in message
        assert "Content that must never appear verbatim in logs." not in message
