"""Phase 17 M2 - Channel/Topic Relevance tests (docs/phase17_m2_channel_topic_relevance_shadow_report.md).

Three tiers, mirroring tests/test_editorial_brief.py's own established structure: pure unit tests
for schemas/classification logic (no DB, no LLM), a static "never touches the LLM Gateway or
Telegram" import-shape test, and integration tests driving the real
capabilities.executor.CapabilityExecutor + workflows.runner.WorkflowRunner path with fake
"research"/"intelligence" Capabilities (tests/conftest.py's db_session fixture, real Postgres,
rolled back at teardown).
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
from schemas.article_relevance import (
    ARTICLE_RELEVANCE_SCHEMA_VERSION,
    ArticleTopicAssessment,
    ChannelFitAssessment,
    FitDecision,
    RelevanceConfidence,
    ShadowEditorialDecision,
)
from schemas.capability import CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition
from schemas.channel_profile import ChannelProfile
from schemas.editorial_task import EditorialTaskCreate
from schemas.topic_taxonomy import ArticleTopic
from schemas.workflow import WorkflowDefinition, WorkflowRetryPolicy, WorkflowStepDefinition, WorkflowType
from services import workflow_service
from services.channel_profiles import AI_GADGETS_CHANNEL_PROFILE, CHANNEL_PROFILES
from services.channel_relevance import (
    CLASSIFIER_VERSION,
    apply_channel_relevance_shadow,
    assess_channel_fit,
    assess_channel_relevance,
    classify_article_topic,
    decide_shadow_editorial,
)
from capabilities.executor import CapabilityExecutor
from capabilities.registry import CapabilityRegistry
from workflows.registry import WorkflowRegistry
from workflows.runner import WorkflowRunner

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Schema validation / versioned serialization (tests 1, 2, 30)
# ---------------------------------------------------------------------------


def test_article_topic_assessment_requires_core_fields() -> None:
    with pytest.raises(ValidationError):
        ArticleTopicAssessment(source_category=EventCategory.AI)  # type: ignore[call-arg]


def test_channel_fit_assessment_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ChannelFitAssessment(
            channel_profile_id="x", fit_decision=FitDecision.ACCEPT, fit_score=0.5,
            confidence=RelevanceConfidence.HIGH, human_review_required=False,
            not_a_real_field="x",  # type: ignore[call-arg]
        )


def test_fit_score_is_bounded_zero_to_one() -> None:
    with pytest.raises(ValidationError):
        ChannelFitAssessment(
            channel_profile_id="x", fit_decision=FitDecision.ACCEPT, fit_score=1.5,
            confidence=RelevanceConfidence.HIGH, human_review_required=False,
        )


def test_schema_version_is_stamped_on_all_three_schemas() -> None:
    topic, fit, decision = assess_channel_relevance(
        "Nvidia unveils new AI chip", "Nvidia announced a new AI chip for data centers.",
        EventCategory.HARDWARE, {},
    )
    assert topic.schema_version == fit.schema_version == decision.schema_version == ARTICLE_RELEVANCE_SCHEMA_VERSION == "v1"
    assert decision.classifier_version == CLASSIFIER_VERSION == "v1"
    # Round-trips losslessly.
    assert ArticleTopicAssessment.model_validate(topic.model_dump(mode="json")) == topic
    assert ChannelFitAssessment.model_validate(fit.model_dump(mode="json")) == fit


def test_channel_profile_validation_accepts_the_real_ai_gadgets_profile() -> None:
    assert AI_GADGETS_CHANNEL_PROFILE.profile_id == "ai_gadgets_channel"
    assert ArticleTopic.AI in AI_GADGETS_CHANNEL_PROFILE.primary_topics
    assert ArticleTopic.ENTERTAINMENT in AI_GADGETS_CHANNEL_PROFILE.excluded_topics
    assert CHANNEL_PROFILES[AI_GADGETS_CHANNEL_PROFILE.profile_id] is AI_GADGETS_CHANNEL_PROFILE


def test_channel_profile_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ChannelProfile(
            profile_id="x", display_name="X", language="en", audience="a",
            not_a_real_field="x",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# Article topic classification (tests 3, 4, 9, 10, 15, 16, 21)
# ---------------------------------------------------------------------------


def test_source_category_can_differ_from_article_topic() -> None:
    """GADGETS-tagged source, but the article's real topic is AI - category_match is False,
    but this alone does not make the article off-topic (that's assess_channel_fit's job)."""
    topic = classify_article_topic(
        "Google wants to update Chrome without a full browser restart",
        "Google published a blog post about its plans to use AI and machine learning models "
        "to improve Chrome's security.",
        [], EventCategory.GADGETS,
    )
    assert topic.primary_topic == ArticleTopic.AI
    assert topic.category_match is False
    assert "category_mismatch" in topic.reason_codes


def test_ai_article_from_general_tech_source() -> None:
    topic = classify_article_topic(
        "OpenAI reveals autonomous AI agent hacked a coding platform",
        "OpenAI said an autonomous artificial intelligence agent hacked a popular platform "
        "for programmers and attempted to breach four other companies.",
        [], EventCategory.TECH,
    )
    assert topic.primary_topic in {ArticleTopic.AI, ArticleTopic.CYBERSECURITY}
    assert topic.confidence == RelevanceConfidence.HIGH


def test_incidental_technology_keyword_does_not_dominate() -> None:
    """A single incidental 'ai' mention inside an overwhelmingly entertainment article must not
    produce a confident ACCEPT - mixed evidence, handled by assess_channel_fit (test 10 below)."""
    topic = classify_article_topic(
        "Streaming platform buys rights to hit TV series, uses AI for recommendations",
        "The streaming platform paid for the rights to a popular TV series and its spin-offs. "
        "Separately, the company also uses AI to power its recommendation engine.",
        [], EventCategory.TECH,
    )
    assert ArticleTopic.AI in [topic.primary_topic, *topic.secondary_topics]
    assert ArticleTopic.ENTERTAINMENT in [topic.primary_topic, *topic.secondary_topics]


def test_mixed_topic_signal_is_captured_in_reason_codes() -> None:
    topic = classify_article_topic(
        "AI actor debate", "An AI-generated actor sparked debate among filmmakers and actresses.",
        [], EventCategory.TECH,
    )
    assert "mixed_tech_and_nontech_signals" in topic.reason_codes


def test_unknown_topic_when_no_keywords_match() -> None:
    topic = classify_article_topic("A quiet local event", "Nothing notable happened.", [], EventCategory.UNKNOWN)
    assert topic.primary_topic == ArticleTopic.UNKNOWN
    assert topic.normalized_category is None
    assert "no_topic_keywords_matched" in topic.reason_codes


def test_excluded_topic_detected_for_entertainment_content() -> None:
    topic = classify_article_topic(
        "Netflix pays $500 million to share streaming rights",
        "Netflix extended its streaming rights to a popular TV series and its spin-offs for $500 million.",
        [], EventCategory.GADGETS,
    )
    assert topic.primary_topic == ArticleTopic.ENTERTAINMENT


def test_evidence_and_reason_codes_never_invent_a_topic_not_in_evidence() -> None:
    topic = classify_article_topic("Nvidia unveils new chip", "Nvidia's new GPU targets AI workloads.", [], EventCategory.HARDWARE)
    for matched_topic, keywords in topic.topic_evidence.items():
        assert keywords, f"{matched_topic} has empty evidence but was scored"
        for keyword in keywords:
            haystack = "nvidia unveils new chip nvidia's new gpu targets ai workloads".lower()
            assert keyword in haystack


# ---------------------------------------------------------------------------
# Channel fit decision logic (tests 5, 6, 7, 8, 11, 17, 18, 19, 20)
# ---------------------------------------------------------------------------


def _fit(title: str, content: str | None, category: EventCategory, gaps: list[str] | None = None):
    from services.editorial_brief import classify_source_sufficiency

    topic = classify_article_topic(title, content, [], category)
    sufficiency = classify_source_sufficiency(title, content, [], gaps or [])
    return topic, assess_channel_fit(topic, AI_GADGETS_CHANNEL_PROFILE, sufficiency.sufficiency)


def test_netflix_walking_dead_regression_is_reject() -> None:
    """The pinned Phase 17 M0 regression case (§12/§18) - Engadget/GADGETS, but the article is
    a pure entertainment streaming-rights story."""
    topic, fit = _fit(
        "Netflix pays $500 million to share 'The Walking Dead' streaming rights with AMC+",
        "Netflix has ponied up a half billion dollars to extend its streaming rights to The "
        "Walking Dead and the show's six spinoffs.",
        EventCategory.GADGETS,
    )
    assert fit.fit_decision == FitDecision.REJECT
    assert ArticleTopic.ENTERTAINMENT in fit.excluded_topics
    assert fit.human_review_required is False


def test_gadget_article_is_accept() -> None:
    _topic, fit = _fit(
        "Apple's new iPhone launch", "Apple unveiled its new smartphone with a redesigned "
        "chip and longer battery life for the flagship phone.", EventCategory.GADGETS,
    )
    assert fit.fit_decision == FitDecision.ACCEPT
    assert fit.confidence == RelevanceConfidence.HIGH


def test_ai_regulation_article_is_accept() -> None:
    _topic, fit = _fit(
        "EU opens antitrust probe into AI company",
        "The European Commission opened an antitrust investigation into an artificial "
        "intelligence company over its machine learning platform practices.",
        EventCategory.TECH,
    )
    assert fit.fit_decision == FitDecision.ACCEPT


def test_headline_only_ambiguous_article_is_review() -> None:
    topic, fit = _fit("AI startup raises funding", "AI startup raises funding", EventCategory.AI)
    assert topic.confidence in {RelevanceConfidence.HIGH, RelevanceConfidence.MEDIUM}
    assert fit.fit_decision == FitDecision.REVIEW
    assert "headline_only_capped_to_review" in fit.reason_codes


def test_entertainment_article_from_technology_source_incidental_keyword() -> None:
    """'AI actor' - genuinely ambiguous (could be a tech story or an entertainment story) -
    must never be a confident ACCEPT; REVIEW or REJECT, never misleading ACCEPT."""
    _topic, fit = _fit(
        "AI actor sparks Hollywood debate",
        "An AI-generated actor appeared in a new movie, sparking debate among actresses and "
        "celebrities about the future of the film industry.",
        EventCategory.TECH,
    )
    assert fit.fit_decision in {FitDecision.REVIEW, FitDecision.REJECT}
    assert fit.fit_decision != FitDecision.ACCEPT


def test_conditional_topic_without_tech_centrality_is_review() -> None:
    topic, fit = _fit(
        "New game trailer released", "A new gameplay trailer for an upcoming video game was released today.",
        EventCategory.GADGETS,
    )
    assert topic.primary_topic == ArticleTopic.GAMING_CONTENT
    assert fit.fit_decision == FitDecision.REVIEW
    assert "conditional_topic_without_tech_centrality" in fit.reason_codes


def test_conditional_topic_with_tech_centrality_can_accept() -> None:
    """'Microsoft bought a gaming studio' - gaming content/hardware tied to a real business/tech
    acquisition - matches the channel's allowed_adjacent BUSINESS_TECH topic too."""
    _topic, fit = _fit(
        "Microsoft acquires gaming studio",
        "Microsoft announced the acquisition of a gaming studio, its latest deal in the games "
        "industry, as part of a broader funding round strategy for its gaming hardware division.",
        EventCategory.STARTUPS,
    )
    assert fit.fit_decision in {FitDecision.ACCEPT, FitDecision.REVIEW}


def test_low_confidence_mixed_signal_is_review_not_reject() -> None:
    _topic, fit = _fit(
        "Streaming platform buys rights to hit TV series, uses AI for recommendations",
        "The streaming platform paid for the rights to a popular TV series and its spin-offs. "
        "Separately, the company also uses AI to power its recommendation engine.",
        EventCategory.TECH,
    )
    assert fit.fit_decision == FitDecision.REVIEW
    assert fit.confidence == RelevanceConfidence.LOW
    assert "mixed_topic_tech_and_excluded_evidence" in fit.reason_codes


def test_high_confidence_accept_requires_clear_dominant_tech_topic() -> None:
    _topic, fit = _fit(
        "Nvidia unveils new AI chip for data centers",
        "Nvidia announced a new GPU chip designed for AI and machine learning workloads in "
        "data centers, with strong performance for large language model inference.",
        EventCategory.HARDWARE,
    )
    assert fit.fit_decision == FitDecision.ACCEPT
    assert fit.confidence == RelevanceConfidence.HIGH


def test_high_confidence_reject_requires_dominant_excluded_topic_and_zero_tech_evidence() -> None:
    _topic, fit = _fit(
        "Star signs movie deal", "A famous actress signed on for a new movie and its sequel, "
        "with box office expectations high for the premiere.", EventCategory.GADGETS,
    )
    assert fit.fit_decision == FitDecision.REJECT
    assert fit.confidence == RelevanceConfidence.HIGH


# ---------------------------------------------------------------------------
# Source sufficiency interaction (test 11 continued, empty content test 12)
# ---------------------------------------------------------------------------


def test_empty_content_review_default() -> None:
    topic, fit = _fit("Some title", None, EventCategory.UNKNOWN)
    assert topic.primary_topic == ArticleTopic.UNKNOWN
    assert fit.fit_decision == FitDecision.REVIEW
    assert fit.human_review_required is True


# ---------------------------------------------------------------------------
# Missing upstream data (tests 13, 14, 27)
# ---------------------------------------------------------------------------


def test_missing_intelligence_and_research_output_still_produces_a_valid_assessment() -> None:
    """No EditorialBrief, no Research output (empty dict) - matches an old, pre-M1/M2 task's
    shape exactly. Must not raise."""
    topic, fit, decision = assess_channel_relevance(
        "Apple's new iPhone launch", "Apple unveiled its new smartphone with a longer battery.",
        EventCategory.GADGETS, {},
    )
    assert isinstance(topic, ArticleTopicAssessment)
    assert isinstance(fit, ChannelFitAssessment)
    assert isinstance(decision, ShadowEditorialDecision)


def test_backward_compatibility_with_pre_m2_workflow_data() -> None:
    topic, fit, decision = assess_channel_relevance("Old task title", "Old task content.", EventCategory.UNKNOWN, {})
    assert decision.classifier_version == "v1"
    assert fit.channel_profile_id == "ai_gadgets_channel"


# ---------------------------------------------------------------------------
# apply_channel_relevance_shadow: mode gating, idempotency (tests 28, 29, 26)
# ---------------------------------------------------------------------------


def test_apply_channel_relevance_shadow_off_mode_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "channel_relevance_mode", "off")
    original = {"significance": "x"}
    result = apply_channel_relevance_shadow("Title", "Content", EventCategory.AI, {}, original)
    assert result is original
    assert "channel_relevance" not in result


def test_apply_channel_relevance_shadow_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "channel_relevance_mode", "shadow")
    first = apply_channel_relevance_shadow("Nvidia chip", "Nvidia's new AI chip.", EventCategory.HARDWARE, {}, {})
    second = apply_channel_relevance_shadow("Nvidia chip", "Nvidia's new AI chip.", EventCategory.HARDWARE, {}, {})
    assert first["channel_relevance"] == second["channel_relevance"]


def test_decide_shadow_editorial_mirrors_fit_decision() -> None:
    topic, fit = _fit("Nvidia unveils new AI chip", "Nvidia's new GPU targets AI workloads.", EventCategory.HARDWARE)
    decision = decide_shadow_editorial(fit)
    assert decision.decision == fit.fit_decision
    assert decision.confidence == fit.confidence
    assert decision.classifier_version == CLASSIFIER_VERSION


# ---------------------------------------------------------------------------
# Static import-shape test (test 24, 25 - no LLM Gateway call, no Telegram send)
# ---------------------------------------------------------------------------


def test_channel_relevance_module_imports_no_llm_gateway_or_telegram() -> None:
    import services.channel_relevance as module

    source_names = {getattr(obj, "__module__", "") for obj in vars(module).values()}
    forbidden_substrings = ("llm_gateway", "telegram", "bot.")
    for name in source_names:
        for forbidden in forbidden_substrings:
            assert forbidden not in name.lower(), f"unexpected import touching {forbidden!r}: {name}"


# ---------------------------------------------------------------------------
# Integration: real CapabilityExecutor + WorkflowRunner (tests 22, 23, 26 continued)
# ---------------------------------------------------------------------------


class _FakeResearchCapability:
    def __init__(self, facts=None, gaps=None) -> None:
        self._facts = facts if facts is not None else []
        self._gaps = gaps if gaps is not None else []

    async def execute(self, context):
        now = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS", structured_output={"facts": self._facts, "confidence": "high", "gaps": self._gaps},
            calls=[], started_at=now, finished_at=now, duration_seconds=0.0,
        )


class _FakeIntelligenceCapability:
    async def execute(self, context):
        now = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS",
            structured_output={
                "significance": "Notable", "angle": "Trend", "audience_relevance": "high",
                "recommendation": "Monitor",
            },
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


async def _event_with_content(
    session: AsyncSession, content: str | None, title: str = "Event title", category: EventCategory = EventCategory.GADGETS,
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


async def _run_workflow(db_session: AsyncSession, event: NewsEvent, *step_names: str, **capabilities):
    workflow_registry = _workflow_registry(*step_names)
    command = EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B)
    task = await workflow_service.create_task(db_session, command, registry=workflow_registry)
    capability_registry = _capability_registry(**capabilities)
    executor = CapabilityExecutor(db_session, task.id, capability_registry)
    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)
    return result.step_results


@pytest.mark.asyncio
async def test_integration_mode_off_produces_no_channel_relevance(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    monkeypatch.setattr(settings, "channel_relevance_mode", "off")
    event = await _event_with_content(db_session, "Netflix extended streaming rights to a TV series.")

    step_results = await _run_workflow(
        db_session, event, "research", "intelligence",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
    )
    assert "channel_relevance" not in step_results[1].result


@pytest.mark.asyncio
async def test_integration_mode_shadow_persists_assessment_on_intelligence_step(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    monkeypatch.setattr(settings, "channel_relevance_mode", "shadow")
    event = await _event_with_content(
        db_session, "Netflix has ponied up a half billion dollars to extend its streaming rights "
        "to a popular TV series and its spinoffs.",
        title="Netflix pays $500 million to share streaming rights",
    )

    step_results = await _run_workflow(
        db_session, event, "research", "intelligence",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
    )
    research_result, intelligence_result = step_results
    assert "channel_relevance" not in research_result.result
    payload = intelligence_result.result["channel_relevance"]
    assert payload["shadow_decision"]["decision"] == "REJECT"
    assert intelligence_result.result["significance"] == "Notable"  # Intelligence's own fields untouched


@pytest.mark.asyncio
async def test_shadow_mode_does_not_change_copywriting_or_content_draft_fields(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    event_off = await _event_with_content(db_session, "Some content.", title="Off event")
    monkeypatch.setattr(settings, "channel_relevance_mode", "off")
    off_results = await _run_workflow(
        db_session, event_off, "research", "intelligence", "copywriting",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
        copywriting=_FakeCopywritingCapability(),
    )

    event_shadow = await _event_with_content(db_session, "Some content.", title="Shadow event")
    monkeypatch.setattr(settings, "channel_relevance_mode", "shadow")
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
async def test_channel_relevance_only_runs_for_the_intelligence_step(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    monkeypatch.setattr(settings, "channel_relevance_mode", "shadow")
    event = await _event_with_content(db_session, "Content for the research-only step-scope check.")

    step_results = await _run_workflow(db_session, event, "research", research=_FakeResearchCapability())
    assert "channel_relevance" not in step_results[0].result


@pytest.mark.asyncio
async def test_classifier_failure_does_not_fail_content_generation(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    monkeypatch.setattr(settings, "channel_relevance_mode", "shadow")

    def _broken_apply(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("capabilities.executor.apply_channel_relevance_shadow", _broken_apply)
    event = await _event_with_content(db_session, "Content for the failure-isolation check.")

    step_results = await _run_workflow(
        db_session, event, "research", "intelligence",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
    )
    research_result, intelligence_result = step_results
    assert intelligence_result.status == "SUCCESS"
    assert "channel_relevance" not in intelligence_result.result
    assert intelligence_result.result["significance"] == "Notable"  # untouched


@pytest.mark.asyncio
async def test_repeat_execution_is_idempotent(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    monkeypatch.setattr(settings, "channel_relevance_mode", "shadow")
    content = "Nvidia's new GPU chip targets AI and machine learning workloads."
    event_a = await _event_with_content(db_session, content, title="Nvidia chip A", category=EventCategory.HARDWARE)
    event_b = await _event_with_content(db_session, content, title="Nvidia chip A", category=EventCategory.HARDWARE)

    first = await _run_workflow(
        db_session, event_a, "research", "intelligence",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
    )
    second = await _run_workflow(
        db_session, event_b, "research", "intelligence",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
    )
    assert first[1].result["channel_relevance"] == second[1].result["channel_relevance"]
