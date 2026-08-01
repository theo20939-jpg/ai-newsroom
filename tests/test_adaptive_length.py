"""Phase 17 M3 - Adaptive Length tests (docs/phase17_m3_adaptive_length_shadow_comparison_report.md).

Three tiers, mirroring tests/test_editorial_brief.py's/tests/test_channel_relevance.py's own
established structure: pure unit tests for schema/classification logic (no DB, no LLM), a static
"never touches the LLM Gateway or Telegram" import-shape test, and integration tests driving the
real capabilities.executor.CapabilityExecutor + workflows.runner.WorkflowRunner path with fake
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
from schemas.adaptive_length import (
    ADAPTIVE_LENGTH_SCHEMA_VERSION,
    AdaptiveLengthPlan,
    Complexity,
    DeliveryMode,
)
from schemas.capability import CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowDefinition, WorkflowRetryPolicy, WorkflowStepDefinition, WorkflowType
from services import workflow_service
from services.adaptive_length import (
    apply_adaptive_length_shadow,
    build_adaptive_length_plan,
    determine_complexity,
    determine_delivery,
)
from services.editorial_brief import build_editorial_brief
from capabilities.executor import CapabilityExecutor
from capabilities.registry import CapabilityRegistry
from workflows.registry import WorkflowRegistry
from workflows.runner import WorkflowRunner

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Schema validation / versioned serialization (tests 1, 2, 19, 20)
# ---------------------------------------------------------------------------


def test_schema_requires_core_fields() -> None:
    with pytest.raises(ValidationError):
        AdaptiveLengthPlan(min_words=10, target_words=20, max_words=30)  # type: ignore[call-arg]


def test_schema_rejects_unknown_fields() -> None:
    plan = build_adaptive_length_plan("Title", "Content here is real.", {}, {}, has_image_candidate=None)
    with pytest.raises(ValidationError):
        AdaptiveLengthPlan(**{**plan.model_dump(), "not_a_real_field": "x"})


def test_word_range_ordering_is_enforced() -> None:
    with pytest.raises(ValidationError):
        AdaptiveLengthPlan(
            recommended_format="short_update", complexity=Complexity.SIMPLE,
            source_sufficiency="sufficient", min_words=100, target_words=50, max_words=140,
            hard_character_limit=1000, delivery_mode=DeliveryMode.UNKNOWN, paragraph_target=1,
            detail_target=0, confidence="high",
        )


def test_schema_version_is_stamped_and_serializes() -> None:
    plan = build_adaptive_length_plan("Title", "Real content with enough words in it.", {}, {}, has_image_candidate=None)
    assert plan.schema_version == ADAPTIVE_LENGTH_SCHEMA_VERSION == "v1"
    assert plan.policy_version == "v1"
    dumped = plan.model_dump(mode="json")
    assert AdaptiveLengthPlan.model_validate(dumped) == plan


def test_mutable_defaults_are_never_shared_between_instances() -> None:
    a = build_adaptive_length_plan("A", None, {}, {}, has_image_candidate=None)
    b = build_adaptive_length_plan("B", None, {}, {}, has_image_candidate=None)
    assert a.required_sections is not b.required_sections
    assert a.reason_codes is not b.reason_codes


# ---------------------------------------------------------------------------
# Complexity classification (tests 3, 4, 5, 6, 7, 14, 15, 16, 17, 18)
# ---------------------------------------------------------------------------


def test_simple_classification() -> None:
    content = (
        "A short thing happened today near downtown involving several local residents "
        "according to early reports circulating online this morning."
    )
    brief = build_editorial_brief("A short update", content, {"facts": ["A fact"]}, {})
    complexity, reasons = determine_complexity(brief)
    assert complexity == Complexity.SIMPLE
    assert "base_from_recommended_format=short_update" in reasons


def test_normal_classification_with_why_it_matters_and_what_next() -> None:
    content = "A reasonably detailed article with several sentences describing a real event. " * 2
    brief = build_editorial_brief(
        "Normal story", content, {"facts": ["Fact one", "Fact two", "Fact three"], "gaps": []},
        {"significance": "Notable", "angle": "Trend", "recommendation": "Watch closely"},
    )
    complexity, reasons = determine_complexity(brief)
    assert complexity in {Complexity.NORMAL, Complexity.COMPLEX}
    assert "why_it_matters_present" in reasons
    assert "what_next_present" in reasons


def test_complex_classification_from_explainer_format() -> None:
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
    brief = build_editorial_brief("Complex story", content, {"facts": ["Fact"], "gaps": []}, {})
    complexity, _reasons = determine_complexity(brief)
    assert complexity == Complexity.COMPLEX


def test_regulation_signal_can_upgrade_complexity() -> None:
    brief = build_editorial_brief(
        "Antitrust probe", "A short update on a case involving several companies and regulators today.",
        {"facts": ["Regulators opened an antitrust investigation", "A lawsuit was filed in court"], "gaps": []},
        {"significance": "Big", "angle": "Regulatory", "recommendation": "Follow the court case"},
    )
    complexity, reasons = determine_complexity(brief)
    assert "regulation_legal_signal" in reasons
    assert complexity in {Complexity.NORMAL, Complexity.SIMPLE}  # never downgraded below its format base


def test_technical_jargon_signal_present_in_reason_codes() -> None:
    brief = build_editorial_brief(
        "MLIP paper", "A new research paper describes a technical machine learning method published today.",
        {"facts": ["The MLIP model uses SOTA techniques on GPU hardware"], "gaps": []},
        {"significance": "x", "angle": "y", "recommendation": "z"},
    )
    _complexity, reasons = determine_complexity(brief)
    assert "technical_jargon_signal" in reasons


def test_follow_up_complexity_is_schema_valid_even_if_unreachable() -> None:
    """FOLLOW_UP is structurally unreachable in M3 (no storyline memory, mirrors
    RecommendedFormat.FOLLOW_UP's identical M1 limitation) - but must still be a valid,
    constructible schema value for forward compatibility."""
    plan = AdaptiveLengthPlan(
        recommended_format="follow_up", complexity=Complexity.FOLLOW_UP,
        source_sufficiency="sufficient", min_words=180, target_words=230, max_words=300,
        hard_character_limit=3000, delivery_mode=DeliveryMode.TEXT_MESSAGE, paragraph_target=2,
        detail_target=3, confidence="medium",
    )
    assert plan.complexity == Complexity.FOLLOW_UP


def test_insufficient_classification_from_empty_content() -> None:
    brief = build_editorial_brief("Just a headline", None, {}, {})
    complexity, reasons = determine_complexity(brief)
    assert complexity == Complexity.INSUFFICIENT
    assert reasons == ["thin_source_forces_insufficient"]


def test_fact_count_alone_does_not_force_complex() -> None:
    """M3's own explicit instruction: do not treat every AI story as complex automatically."""
    brief = build_editorial_brief(
        "AI news", "A short AI update.", {"facts": ["Fact " + str(i) for i in range(10)], "gaps": []}, {},
    )
    complexity, _reasons = determine_complexity(brief)
    assert complexity != Complexity.COMPLEX


# ---------------------------------------------------------------------------
# Source sufficiency handling (tests 8, 9, 10, 11, 12, 13, 21)
# ---------------------------------------------------------------------------


def test_sufficient_handling_allows_full_range() -> None:
    content = (
        "Acme Corp announced a $250 million acquisition of Widget Inc on July 30, 2026, "
        "the largest deal in the sector this year. The combined company will employ 4,000 "
        "people across 12 countries."
    )
    plan = build_adaptive_length_plan("Title", content, {"facts": ["A", "B"], "gaps": []}, {}, has_image_candidate=None)
    assert plan.source_sufficiency == "sufficient"
    assert "no_padding_partial_source" not in plan.safety_constraints


def test_partial_handling_lowers_target_without_changing_bounds() -> None:
    plan_partial = build_adaptive_length_plan("Title", "word " * 20, {}, {}, has_image_candidate=None)
    assert plan_partial.source_sufficiency == "partial"
    min_w, target_w, max_w = plan_partial.min_words, plan_partial.target_words, plan_partial.max_words
    assert min_w <= target_w <= max_w
    assert "no_padding_partial_source" in plan_partial.safety_constraints


def test_headline_only_never_has_artificial_minimum() -> None:
    plan = build_adaptive_length_plan("Same as content", "Same as content", {}, {}, has_image_candidate=None)
    assert plan.source_sufficiency == "headline_only"
    assert plan.complexity == Complexity.INSUFFICIENT
    assert plan.min_words < 90  # never forced up to the Simple band's own 90-word floor
    assert "no_fabrication_thin_source" in plan.safety_constraints
    assert "do_not_repeat_single_idea_to_reach_length" in plan.safety_constraints


def test_empty_handling_flags_skip_comparison_candidate() -> None:
    plan = build_adaptive_length_plan("Title", None, {}, {}, has_image_candidate=None)
    assert plan.source_sufficiency == "empty"
    assert plan.complexity == Complexity.INSUFFICIENT
    assert "empty_source_skip_comparison_candidate" in plan.safety_constraints


def test_conflicting_handling_never_amplifies() -> None:
    plan = build_adaptive_length_plan(
        "Title", "Some reasonably long content describing an event in detail here now.",
        {"facts": [], "gaps": ["Sources contradict each other on the exact amount"]}, {},
        has_image_candidate=None,
    )
    assert plan.source_sufficiency == "conflicting"
    assert plan.complexity == Complexity.INSUFFICIENT
    assert "do_not_amplify_conflicting_claims" in plan.safety_constraints


def test_unknown_sufficiency_is_conservative() -> None:
    plan = build_adaptive_length_plan("", "Some content.", {}, {}, has_image_candidate=None)
    assert plan.source_sufficiency == "unknown"
    assert plan.complexity == Complexity.INSUFFICIENT
    assert plan.max_words <= 90


# ---------------------------------------------------------------------------
# Telegram delivery / character budget (tests 22, 23, 24, 25)
# ---------------------------------------------------------------------------


def test_photo_caption_recommendation_when_target_fits() -> None:
    mode, limit, reasons = determine_delivery(target_words=60, max_words=90, has_image_candidate=True)
    assert mode == DeliveryMode.PHOTO_CAPTION
    assert "fits_photo_caption_at_target" in reasons
    from bot.image_preview_formatting import CAPTION_SAFE_LIMIT
    assert limit < CAPTION_SAFE_LIMIT


def test_text_message_recommendation_when_target_does_not_fit_caption() -> None:
    mode, limit, reasons = determine_delivery(target_words=270, max_words=320, has_image_candidate=True)
    assert mode == DeliveryMode.TEXT_MESSAGE
    assert "exceeds_photo_caption_recommend_text_over_truncation" in reasons
    from bot.formatting import SAFE_LIMIT
    assert limit < SAFE_LIMIT


def test_text_message_recommendation_when_no_image_candidate() -> None:
    mode, _limit, reasons = determine_delivery(target_words=100, max_words=140, has_image_candidate=False)
    assert mode == DeliveryMode.TEXT_MESSAGE
    assert "no_image_candidate" in reasons


def test_character_budget_reserves_room_for_title_and_hashtags() -> None:
    from bot.image_preview_formatting import CAPTION_SAFE_LIMIT

    _mode, limit, _reasons = determine_delivery(target_words=50, max_words=90, has_image_candidate=True)
    assert limit < CAPTION_SAFE_LIMIT  # never the raw Telegram limit itself - always reserve-adjusted
    assert limit > 0


def test_unknown_delivery_uses_conservative_smaller_budget() -> None:
    from bot.image_preview_formatting import CAPTION_SAFE_LIMIT
    from bot.formatting import SAFE_LIMIT

    mode, limit, reasons = determine_delivery(target_words=100, max_words=140, has_image_candidate=None)
    assert mode == DeliveryMode.UNKNOWN
    assert limit == CAPTION_SAFE_LIMIT - 360  # the conservative (smaller) budget, not the text one
    assert limit < SAFE_LIMIT
    assert "delivery_mode_unknown_conservative_budget" in reasons


# ---------------------------------------------------------------------------
# Backward compatibility / interaction with other milestones (tests 36, 37)
# ---------------------------------------------------------------------------


def test_backward_compatible_without_prior_editorial_brief_data() -> None:
    """No persisted EditorialBrief step_results (pre-M1 task shape) - the planner builds its own
    fresh brief internally (services/adaptive_length.py's own independence-from-other-flags
    design) and must not raise."""
    plan = build_adaptive_length_plan("Old task", "Old task content here.", {}, {}, has_image_candidate=None)
    assert isinstance(plan, AdaptiveLengthPlan)


def test_channel_relevance_payload_does_not_interfere() -> None:
    """A structured_output dict that already carries an unrelated "channel_relevance" key (M2's
    own payload, attached at a different step) must not confuse the merge."""
    monkeypatch_value = {"significance": "x", "channel_relevance": {"shadow_decision": {"decision": "ACCEPT"}}}
    from core.config import settings as real_settings
    original = real_settings.adaptive_length_mode
    real_settings.adaptive_length_mode = "shadow"
    try:
        result = apply_adaptive_length_shadow("Title", "Some content here.", {}, monkeypatch_value, None, monkeypatch_value)
    finally:
        real_settings.adaptive_length_mode = original
    assert result["channel_relevance"]["shadow_decision"]["decision"] == "ACCEPT"
    assert "adaptive_length_plan" in result


# ---------------------------------------------------------------------------
# apply_adaptive_length_shadow: mode gating, idempotency (tests 26, 27, 38)
# ---------------------------------------------------------------------------


def test_apply_adaptive_length_shadow_off_mode_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "adaptive_length_mode", "off")
    original = {"significance": "x"}
    result = apply_adaptive_length_shadow("Title", "Content", {}, {}, None, original)
    assert result is original
    assert "adaptive_length_plan" not in result


def test_apply_adaptive_length_shadow_mode_is_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "adaptive_length_mode", "shadow")
    result = apply_adaptive_length_shadow("Title", "Some real content here today.", {}, {}, True, {})
    assert "adaptive_length_plan" in result


def test_apply_adaptive_length_shadow_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "adaptive_length_mode", "shadow")
    first = apply_adaptive_length_shadow("Title", "Content here.", {"facts": ["A"]}, {}, True, {})
    second = apply_adaptive_length_shadow("Title", "Content here.", {"facts": ["A"]}, {}, True, {})
    assert first["adaptive_length_plan"] == second["adaptive_length_plan"]


# ---------------------------------------------------------------------------
# Static import-shape test (mirrors M1/M2's own "no LLM Gateway/Telegram" check)
# ---------------------------------------------------------------------------


def test_adaptive_length_module_imports_no_llm_gateway_or_telegram_send() -> None:
    import services.adaptive_length as module

    source_names = {getattr(obj, "__module__", "") for obj in vars(module).values()}
    forbidden_substrings = ("llm_gateway", "telegram", "bot.handlers", "bot.main")
    for name in source_names:
        for forbidden in forbidden_substrings:
            assert forbidden not in name.lower(), f"unexpected import touching {forbidden!r}: {name}"


# ---------------------------------------------------------------------------
# Integration: real CapabilityExecutor + WorkflowRunner (tests 31, 32, 33, 34, 39, 40)
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
    monkeypatch.setattr(settings, "adaptive_length_mode", "off")
    event = await _event_with_content(db_session, "Some real content describing an event today.")

    step_results = await _run_workflow(
        db_session, event, "research", "intelligence", "copywriting",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
        copywriting=_FakeCopywritingCapability(),
    )
    assert "adaptive_length_plan" not in step_results[2].result


@pytest.mark.asyncio
async def test_integration_mode_shadow_persists_plan_on_copywriting_step(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    monkeypatch.setattr(settings, "adaptive_length_mode", "shadow")
    event = await _event_with_content(db_session, "Some real content describing an event today in detail.")

    step_results = await _run_workflow(
        db_session, event, "research", "intelligence", "copywriting",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
        copywriting=_FakeCopywritingCapability(),
    )
    research_result, intelligence_result, copywriting_result = step_results
    assert "adaptive_length_plan" not in intelligence_result.result  # only ever on "copywriting"
    assert "adaptive_length_plan" in copywriting_result.result
    # Copywriting's own real output fields are untouched - purely additive merge (test 40).
    assert copywriting_result.result["title"] == "A drafted title"
    assert copywriting_result.result["body"] == "A drafted body"
    assert copywriting_result.result["hashtags"] == ["#news"]


@pytest.mark.asyncio
async def test_shadow_mode_does_not_change_copywriting_output_off_vs_shadow(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    event_off = await _event_with_content(db_session, "Some content.", title="Off event")
    monkeypatch.setattr(settings, "adaptive_length_mode", "off")
    off_results = await _run_workflow(
        db_session, event_off, "research", "intelligence", "copywriting",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
        copywriting=_FakeCopywritingCapability(),
    )

    event_shadow = await _event_with_content(db_session, "Some content.", title="Shadow event")
    monkeypatch.setattr(settings, "adaptive_length_mode", "shadow")
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
async def test_plan_builder_failure_does_not_fail_content_generation(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    monkeypatch.setattr(settings, "adaptive_length_mode", "shadow")

    def _broken_apply(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("capabilities.executor.apply_adaptive_length_shadow", _broken_apply)
    event = await _event_with_content(db_session, "Content for the failure-isolation check.")

    step_results = await _run_workflow(
        db_session, event, "research", "intelligence", "copywriting",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
        copywriting=_FakeCopywritingCapability(),
    )
    copywriting_result = step_results[2]
    assert copywriting_result.status == "SUCCESS"
    assert "adaptive_length_plan" not in copywriting_result.result
    assert copywriting_result.result["title"] == "A drafted title"  # untouched


@pytest.mark.asyncio
async def test_adaptive_length_only_runs_for_the_copywriting_step(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    monkeypatch.setattr(settings, "adaptive_length_mode", "shadow")
    event = await _event_with_content(db_session, "Content for the step-scope check.")

    step_results = await _run_workflow(
        db_session, event, "research", "intelligence",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
    )
    assert "adaptive_length_plan" not in step_results[0].result
    assert "adaptive_length_plan" not in step_results[1].result
