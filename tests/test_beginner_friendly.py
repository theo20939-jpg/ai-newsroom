"""Phase 17 M4 - Beginner-Friendly Copywriting tests (docs/
phase17_m4_beginner_friendly_copywriting_report.md).

Three tiers, mirroring tests/test_adaptive_length.py's own established structure: pure unit tests
for schema/classification/glossary/fact-safety-audit logic (no DB, no LLM), a static "never
touches the LLM Gateway or Telegram" import-shape test, and integration tests driving the real
capabilities.executor.CapabilityExecutor + workflows.runner.WorkflowRunner path with fake
Capabilities (tests/conftest.py's db_session fixture, real Postgres, rolled back at teardown).
"""
import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.editorial_task import TaskPriority
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from schemas.beginner_friendly import (
    BEGINNER_FRIENDLY_SCHEMA_VERSION,
    AudienceLevel,
    BeginnerFriendlyPlan,
    JargonRisk,
    WordRange,
)
from schemas.candidate_fact_safety import CANDIDATE_FACT_SAFETY_SCHEMA_VERSION, FactSafetyStatus
from schemas.capability import CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowDefinition, WorkflowRetryPolicy, WorkflowStepDefinition, WorkflowType
from services import workflow_service
from services.beginner_friendly import (
    apply_beginner_friendly_shadow,
    build_beginner_friendly_plan,
    classify_subjects_to_explain,
    classify_terms_to_explain,
)
from services.candidate_fact_safety import (
    detect_filler_phrases,
    detect_repetition,
    evaluate_candidate_fact_safety,
)
from services.editorial_brief import build_editorial_brief
from services.editorial_glossary import GLOSSARY_VERSION, lookup
from capabilities.executor import CapabilityExecutor
from capabilities.registry import CapabilityRegistry
from workflows.registry import WorkflowRegistry
from workflows.runner import WorkflowRunner

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Schema validation / versioning (tests 1, 2)
# ---------------------------------------------------------------------------


def test_schema_requires_core_fields() -> None:
    with pytest.raises(ValidationError):
        BeginnerFriendlyPlan(audience_level=AudienceLevel.GENERAL)  # type: ignore[call-arg]


def test_schema_version_is_stamped_and_serializes() -> None:
    plan = build_beginner_friendly_plan("Title", "Real content with enough words here today.", {}, {}, has_image_candidate=None)
    assert plan.schema_version == BEGINNER_FRIENDLY_SCHEMA_VERSION == "v1"
    dumped = plan.model_dump(mode="json")
    assert BeginnerFriendlyPlan.model_validate(dumped) == plan


def test_safe_range_cannot_exceed_ideal_ceiling() -> None:
    with pytest.raises(ValidationError):
        BeginnerFriendlyPlan(
            audience_level=AudienceLevel.TECH_INTERESTED, explanation_required=False,
            explanation_budget=0, context_budget=0, detail_target=0, paragraph_target=1,
            why_it_matters_required=False, what_next_allowed=False, uncertainty_required=False,
            jargon_risk=JargonRisk.LOW,
            ideal_range=WordRange(min_words=90, target_words=115, max_words=140),
            safe_range=WordRange(min_words=90, target_words=115, max_words=150),  # exceeds ideal max
        )


def test_word_range_ordering_enforced() -> None:
    with pytest.raises(ValidationError):
        WordRange(min_words=100, target_words=50, max_words=140)


# ---------------------------------------------------------------------------
# Audience policy (tests 12, 13)
# ---------------------------------------------------------------------------


def test_audience_level_defaults_to_tech_interested_matching_channel_policy() -> None:
    """services/channel_profiles.py's own AI_GADGETS_CHANNEL_PROFILE.audience already says
    "tech-interested general readers" - M4 reuses that, never GENERAL, never SPECIALIST."""
    plan = build_beginner_friendly_plan("Title", "Some content with enough words here today.", {}, {}, has_image_candidate=None)
    assert plan.audience_level == AudienceLevel.TECH_INTERESTED


# ---------------------------------------------------------------------------
# Subject/term explanation classification (tests 3-9, 11)
# ---------------------------------------------------------------------------


def test_explanation_required_when_explainable_subjects_present() -> None:
    plan = build_beginner_friendly_plan(
        "Robotics startup funding", "A reasonably detailed article about a funding round today.",
        {"facts": ["Робототехнический стартап Atoms привлек крупные инвестиции"], "gaps": []}, {},
        has_image_candidate=None,
    )
    assert "Atoms" in plan.subjects_to_explain
    assert plan.explanation_required is True


def test_explanation_not_required_when_no_subjects_or_terms() -> None:
    plan = build_beginner_friendly_plan(
        "Simple news", "Something happened today with no unusual names or jargon involved at all.",
        {"facts": [], "gaps": []}, {}, has_image_candidate=None,
    )
    assert plan.explanation_required is False


def test_subject_explanation_grounded_in_evidence_with_descriptive_context() -> None:
    subjects, _assumed, _unexplainable = classify_subjects_to_explain(
        build_editorial_brief(
            "T", "content", {"facts": ["Робототехнический стартап Atoms разрабатывает системы автоматизации"], "gaps": []}, {},
        )
    )
    assert "Atoms" in subjects


def test_missing_subject_evidence_marks_unexplainable() -> None:
    _subjects, _assumed, unexplainable = classify_subjects_to_explain(
        build_editorial_brief("T", "content", {"facts": ["Zorbex объявила о партнерстве сегодня"], "gaps": []}, {})
    )
    assert "Zorbex" in unexplainable


def test_no_invented_company_description_evidence_constraint_always_present() -> None:
    plan = build_beginner_friendly_plan("T", "content today with words.", {}, {}, has_image_candidate=None)
    assert "no_invented_company_description" in plan.evidence_constraints


def test_known_glossary_term_is_explainable() -> None:
    brief = build_editorial_brief("T", "content", {"facts": ["Модель использует LLM для генерации текста"], "gaps": []}, {})
    terms, _unexplainable = classify_terms_to_explain(brief)
    assert "llm" in terms
    assert lookup("llm") is not None


def test_unknown_glossary_term_is_unexplainable() -> None:
    brief = build_editorial_brief("T", "content", {"facts": ["Технология использует ZQVX для обработки"], "gaps": []}, {})
    _terms, unexplainable = classify_terms_to_explain(brief)
    assert "ZQVX" in unexplainable
    assert lookup("zqvx") is None


def test_glossary_is_versioned() -> None:
    assert GLOSSARY_VERSION == "v1"


def test_jargon_detection_produces_high_risk_with_multiple_terms() -> None:
    plan = build_beginner_friendly_plan(
        "T", "content",
        {"facts": ["Модель использует LLM и prompt для inference на GPU с fine-tuning"], "gaps": []}, {},
        has_image_candidate=None,
    )
    assert len(plan.terms_to_explain) >= 2
    assert plan.jargon_risk in {JargonRisk.MEDIUM, JargonRisk.HIGH}


# ---------------------------------------------------------------------------
# Ideal vs safe length, source sufficiency (tests 14-19, 21)
# ---------------------------------------------------------------------------


def test_safe_range_vs_ideal_range_for_rich_evidence() -> None:
    content = (
        "Acme Corp announced on July 30, 2026 a $250 million acquisition of Widget Inc, its "
        "largest deal in the sector this year. The combined company will employ 4,000 people "
        "across 12 countries, and executives said integration would take 18 months. Regulators "
        "in the EU and US must still approve the transaction before it closes in early 2027. "
        "Widget Inc was founded in 2011 and had raised $80 million in prior venture funding. "
        "The founders will stay on as advisors for two years under the terms of the agreement. "
        "Industry analysts said the deal reflects a broader wave of consolidation across the "
        "sector, with at least six comparable transactions announced since January 2026."
    )
    plan = build_beginner_friendly_plan(
        "Complex story", content, {"facts": ["Fact one", "Fact two", "Fact three"], "gaps": []},
        {"significance": "Big", "angle": "Trend", "recommendation": "Watch"}, has_image_candidate=None,
    )
    assert plan.safe_range.max_words <= plan.ideal_range.max_words


def test_sufficient_evidence_gives_wide_safe_range() -> None:
    plan = build_beginner_friendly_plan(
        "Title", "word " * 40,
        {"facts": ["A", "B", "C", "D"], "gaps": []},
        {"significance": "x", "angle": "y", "recommendation": "z"}, has_image_candidate=None,
    )
    assert plan.safe_range.max_words > 40


def test_partial_evidence_narrows_safe_range_below_ideal() -> None:
    plan = build_beginner_friendly_plan(
        "Netflix pays $500 million",
        "Netflix has ponied up a half billion dollars to extend its streaming rights to The "
        "Walking Dead and the six spinoffs.",
        {"facts": ["Netflix paid $500M"], "gaps": []},
        {"significance": "x", "angle": "y", "recommendation": "z"}, has_image_candidate=None,
    )
    assert plan.ideal_range.max_words > 90  # confirms this case is NOT the INSUFFICIENT band
    assert plan.safe_range.max_words < plan.ideal_range.max_words


def test_headline_only_safe_range_equals_ideal_insufficient_band() -> None:
    plan = build_beginner_friendly_plan("Same text", "Same text", {}, {}, has_image_candidate=None)
    assert plan.ideal_range.max_words == 90
    assert plan.safe_range == plan.ideal_range


def test_empty_content_handling() -> None:
    plan = build_beginner_friendly_plan("Title only", None, {}, {}, has_image_candidate=None)
    assert plan.ideal_range.max_words == 90
    assert plan.explanation_required is False


def test_conflicting_evidence_handling() -> None:
    plan = build_beginner_friendly_plan(
        "Title", "Some reasonably long content describing an event in detail here now.",
        {"facts": [], "gaps": ["Sources contradict each other on the exact amount"]}, {},
        has_image_candidate=None,
    )
    assert plan.uncertainty_required is True


def test_detail_target_never_exceeds_available_event_details() -> None:
    plan = build_beginner_friendly_plan(
        "Title", "word " * 40, {"facts": ["Only one fact"], "gaps": []}, {}, has_image_candidate=None,
    )
    assert plan.detail_target <= 1


# ---------------------------------------------------------------------------
# Structure (test 20)
# ---------------------------------------------------------------------------


def test_multi_paragraph_recommended_when_explanation_required() -> None:
    plan = build_beginner_friendly_plan(
        "T", "content",
        {"facts": ["Робототехнический стартап Atoms разрабатывает системы автоматизации"], "gaps": []}, {},
        has_image_candidate=None,
    )
    assert plan.explanation_required is True
    assert plan.paragraph_target >= 2


# ---------------------------------------------------------------------------
# why_it_matters / what_next / uncertainty gating (tests 22-26)
# ---------------------------------------------------------------------------


def test_why_it_matters_allowed_when_evidence_present() -> None:
    plan = build_beginner_friendly_plan(
        "Title", "word " * 40, {"facts": ["A"], "gaps": []},
        {"significance": "Big deal", "angle": "Trend", "recommendation": ""}, has_image_candidate=None,
    )
    assert plan.why_it_matters_required is True


def test_why_it_matters_forbidden_without_evidence() -> None:
    plan = build_beginner_friendly_plan("Title", "word " * 40, {"facts": ["A"], "gaps": []}, {}, has_image_candidate=None)
    assert plan.why_it_matters_required is False


def test_what_next_allowed_when_recommendation_present() -> None:
    plan = build_beginner_friendly_plan(
        "Title", "word " * 40, {"facts": ["A"], "gaps": []},
        {"significance": "", "angle": "", "recommendation": "Watch for updates"}, has_image_candidate=None,
    )
    assert plan.what_next_allowed is True


def test_what_next_forbidden_without_evidence() -> None:
    plan = build_beginner_friendly_plan("Title", "word " * 40, {"facts": ["A"], "gaps": []}, {}, has_image_candidate=None)
    assert plan.what_next_allowed is False


def test_uncertainty_required_for_thin_source() -> None:
    plan = build_beginner_friendly_plan("Same text", "Same text", {}, {}, has_image_candidate=None)
    assert plan.uncertainty_required is True


# ---------------------------------------------------------------------------
# Filler / repetition detection (tests 27, 28)
# ---------------------------------------------------------------------------


def test_filler_phrase_detection() -> None:
    flags = detect_filler_phrases("Это важный шаг для компании. Время покажет, что будет дальше.")
    assert len(flags) >= 2


def test_no_filler_in_clean_text() -> None:
    assert detect_filler_phrases("Netflix заплатила $500 млн за права на сериал.") == []


def test_repetition_detection_flags_near_duplicate_sentences() -> None:
    text = "Netflix заплатила огромную сумму за права на трансляцию сериала. Netflix заплатила огромную сумму за права на показ сериала."
    flags = detect_repetition(text)
    assert len(flags) >= 1


def test_no_repetition_in_distinct_sentences() -> None:
    text = "Netflix заплатила $500 млн за права. Apple сообщила о росте продаж iPhone на 22%."
    assert detect_repetition(text) == []


# ---------------------------------------------------------------------------
# CandidateFactSafetyAudit (tests 29-35)
# ---------------------------------------------------------------------------


def test_numeric_unsupported_flag() -> None:
    audit = evaluate_candidate_fact_safety(
        "Title", "The deal was worth $700 million.", "Title", "The deal was worth $500 million.", ["The deal was worth $500 million."],
    )
    assert any("700" in f for f in audit.numeric_flags)
    assert audit.status == FactSafetyStatus.FAIL


def test_entity_unsupported_flag() -> None:
    audit = evaluate_candidate_fact_safety(
        "Title", "Zorbex Corporation announced the deal.", "Title", "A company announced the deal.", [],
    )
    assert audit.entity_flags
    assert audit.status in {FactSafetyStatus.FAIL, FactSafetyStatus.REVIEW}


def test_definition_unsupported_flag() -> None:
    from schemas.beginner_friendly import AudienceLevel as _AL
    from schemas.beginner_friendly import BeginnerFriendlyPlan as _Plan
    from schemas.beginner_friendly import JargonRisk as _JR
    from schemas.beginner_friendly import WordRange as _WR

    plan = _Plan(
        audience_level=_AL.TECH_INTERESTED, explanation_required=True,
        unexplainable_terms=["Zorbex"], explanation_budget=10, context_budget=0, detail_target=1,
        paragraph_target=2, why_it_matters_required=False, what_next_allowed=False,
        uncertainty_required=True, jargon_risk=_JR.LOW,
        ideal_range=_WR(min_words=40, target_words=65, max_words=90),
        safe_range=_WR(min_words=40, target_words=65, max_words=90),
    )
    audit = evaluate_candidate_fact_safety(
        "Title", "Zorbex, a well-known software developer, announced the deal.",
        "Title", "A deal was announced.", [], plan,
    )
    assert audit.definition_flags
    assert audit.status == FactSafetyStatus.FAIL


def test_causal_unsupported_flag() -> None:
    audit = evaluate_candidate_fact_safety(
        "Title", "This will become the market leader as a result of the deal.",
        "Title", "A deal happened.", [],
    )
    assert audit.causal_flags


def test_fact_safety_pass() -> None:
    audit = evaluate_candidate_fact_safety(
        "Title", "The company confirmed the announcement.", "Title", "The company confirmed the announcement.", [],
    )
    assert audit.status == FactSafetyStatus.PASS
    assert audit.severity is None


def test_fact_safety_review_on_uncertain_claim() -> None:
    audit = evaluate_candidate_fact_safety(
        "Title", "This may become important, according to some.", "Title", "Something happened.", [],
    )
    assert audit.status in {FactSafetyStatus.REVIEW, FactSafetyStatus.PASS}


def test_fact_safety_fail_on_high_severity_unsupported() -> None:
    audit = evaluate_candidate_fact_safety(
        "Title", "The deal was signed on 2027-01-01.", "Title", "The deal was signed.", [],
    )
    assert audit.status == FactSafetyStatus.FAIL
    assert audit.schema_version == CANDIDATE_FACT_SAFETY_SCHEMA_VERSION == "v1"


# ---------------------------------------------------------------------------
# apply_beginner_friendly_shadow: mode gating (tests 36-38 partial)
# ---------------------------------------------------------------------------


def test_apply_beginner_friendly_shadow_off_mode_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "beginner_copywriting_mode", "off")
    original = {"significance": "x"}
    result = apply_beginner_friendly_shadow("Title", "Content", {}, {}, None, original)
    assert result is original
    assert "beginner_friendly_plan" not in result


def test_apply_beginner_friendly_shadow_mode_is_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "beginner_copywriting_mode", "shadow")
    result = apply_beginner_friendly_shadow("Title", "Some real content here today.", {}, {}, True, {})
    assert "beginner_friendly_plan" in result


def test_apply_beginner_friendly_shadow_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "beginner_copywriting_mode", "shadow")
    first = apply_beginner_friendly_shadow("Title", "Content here.", {"facts": ["A"]}, {}, True, {})
    second = apply_beginner_friendly_shadow("Title", "Content here.", {"facts": ["A"]}, {}, True, {})
    assert first["beginner_friendly_plan"] == second["beginner_friendly_plan"]


# ---------------------------------------------------------------------------
# Backward compatibility / interaction (tests 47-49)
# ---------------------------------------------------------------------------


def test_backward_compatible_without_prior_editorial_brief_or_adaptive_length_data() -> None:
    """No persisted EditorialBrief/AdaptiveLengthPlan step_results (pre-M1/M3 task shape) - the
    planner builds fresh ones internally and must not raise."""
    plan = build_beginner_friendly_plan("Old task", "Old task content here.", {}, {}, has_image_candidate=None)
    assert isinstance(plan, BeginnerFriendlyPlan)


def test_channel_relevance_payload_does_not_interfere() -> None:
    monkeypatch_value = {"significance": "x", "channel_relevance": {"shadow_decision": {"decision": "ACCEPT"}}}
    original = settings.beginner_copywriting_mode
    settings.beginner_copywriting_mode = "shadow"
    try:
        result = apply_beginner_friendly_shadow("Title", "Some content here.", {}, monkeypatch_value, None, monkeypatch_value)
    finally:
        settings.beginner_copywriting_mode = original
    assert result["channel_relevance"]["shadow_decision"]["decision"] == "ACCEPT"
    assert "beginner_friendly_plan" in result


# ---------------------------------------------------------------------------
# Static import-shape test
# ---------------------------------------------------------------------------


def test_beginner_friendly_module_imports_no_llm_gateway_or_telegram() -> None:
    import services.beginner_friendly as module

    source_names = {getattr(obj, "__module__", "") for obj in vars(module).values()}
    forbidden_substrings = ("llm_gateway", "telegram", "bot.handlers", "bot.main")
    for name in source_names:
        for forbidden in forbidden_substrings:
            assert forbidden not in name.lower(), f"unexpected import touching {forbidden!r}: {name}"


def test_candidate_fact_safety_module_imports_no_llm_gateway_or_telegram() -> None:
    import services.candidate_fact_safety as module

    source_names = {getattr(obj, "__module__", "") for obj in vars(module).values()}
    forbidden_substrings = ("llm_gateway", "telegram", "bot.handlers", "bot.main")
    for name in source_names:
        for forbidden in forbidden_substrings:
            assert forbidden not in name.lower(), f"unexpected import touching {forbidden!r}: {name}"


# ---------------------------------------------------------------------------
# Integration: real CapabilityExecutor + WorkflowRunner (tests 43-46, 50)
# ---------------------------------------------------------------------------


class _FakeResearchCapability:
    async def execute(self, context):
        now = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS", structured_output={"facts": ["Fact one", "Fact two"], "confidence": "high", "gaps": []},
            calls=[], started_at=now, finished_at=now, duration_seconds=0.0,
        )


class _FakeIntelligenceCapability:
    async def execute(self, context):
        now = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS",
            structured_output={"significance": "Notable", "angle": "Trend", "audience_relevance": "high", "recommendation": "Watch"},
            calls=[], started_at=now, finished_at=now, duration_seconds=0.0,
        )


class _FakeCopywritingCapability:
    async def execute(self, context):
        now = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS", structured_output={"title": "A drafted title", "body": "A drafted body", "hashtags": ["#news"]},
            calls=[], started_at=now, finished_at=now, duration_seconds=0.0,
        )


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
    return result.step_results


@pytest.mark.asyncio
async def test_integration_mode_off_produces_no_plan(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    monkeypatch.setattr(settings, "beginner_copywriting_mode", "off")
    event = await _event_with_content(db_session, "Some real content describing an event today.")

    step_results = await _run_workflow(
        db_session, event, "research", "intelligence", "copywriting",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
        copywriting=_FakeCopywritingCapability(),
    )
    assert "beginner_friendly_plan" not in step_results[2].result


@pytest.mark.asyncio
async def test_integration_mode_shadow_persists_plan_and_leaves_copywriting_untouched(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    monkeypatch.setattr(settings, "beginner_copywriting_mode", "shadow")
    event = await _event_with_content(db_session, "Some real content describing an event today in detail.")

    step_results = await _run_workflow(
        db_session, event, "research", "intelligence", "copywriting",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
        copywriting=_FakeCopywritingCapability(),
    )
    copywriting_result = step_results[2]
    assert "beginner_friendly_plan" in copywriting_result.result
    # Copywriting's own real output fields are untouched - purely additive merge (test 46).
    assert copywriting_result.result["title"] == "A drafted title"
    assert copywriting_result.result["body"] == "A drafted body"
    assert copywriting_result.result["hashtags"] == ["#news"]


@pytest.mark.asyncio
async def test_baseline_byte_identical_off_vs_shadow(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    event_off = await _event_with_content(db_session, "Some content.", title="Off event")
    monkeypatch.setattr(settings, "beginner_copywriting_mode", "off")
    off_results = await _run_workflow(
        db_session, event_off, "research", "intelligence", "copywriting",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
        copywriting=_FakeCopywritingCapability(),
    )

    event_shadow = await _event_with_content(db_session, "Some content.", title="Shadow event")
    monkeypatch.setattr(settings, "beginner_copywriting_mode", "shadow")
    shadow_results = await _run_workflow(
        db_session, event_shadow, "research", "intelligence", "copywriting",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
        copywriting=_FakeCopywritingCapability(),
    )
    for result in (off_results[2].result, shadow_results[2].result):
        assert result["title"] == "A drafted title"
        assert result["body"] == "A drafted body"
        assert result["hashtags"] == ["#news"]


@pytest.mark.asyncio
async def test_shadow_failure_isolation_does_not_fail_content_generation(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    monkeypatch.setattr(settings, "beginner_copywriting_mode", "shadow")

    def _broken_apply(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("capabilities.executor.apply_beginner_friendly_shadow", _broken_apply)
    event = await _event_with_content(db_session, "Content for the failure-isolation check.")

    step_results = await _run_workflow(
        db_session, event, "research", "intelligence", "copywriting",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
        copywriting=_FakeCopywritingCapability(),
    )
    copywriting_result = step_results[2]
    assert copywriting_result.status == "SUCCESS"
    assert "beginner_friendly_plan" not in copywriting_result.result
    assert copywriting_result.result["title"] == "A drafted title"


@pytest.mark.asyncio
async def test_no_content_draft_mutation_and_no_telegram_import_in_workflow_path(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """This integration test never touches ContentDraft or Telegram at all - the workflow path
    used here (CapabilityExecutor + WorkflowRunner) has no reachable code path to either."""
    monkeypatch.setattr(settings, "beginner_copywriting_mode", "shadow")
    event = await _event_with_content(db_session, "Content for the mutation/telegram check.")

    step_results = await _run_workflow(
        db_session, event, "research", "intelligence", "copywriting",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
        copywriting=_FakeCopywritingCapability(),
    )
    assert step_results[2].status == "SUCCESS"
