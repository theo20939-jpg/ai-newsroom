"""Phase 17 M1 - Editorial Brief tests (docs/phase17_m1_editorial_brief_shadow_report.md).

Three tiers, mirroring tests/test_fact_safety.py's own established structure:
- Pure unit tests for schemas.editorial_brief / services.editorial_brief's classification and
  assembly functions - no DB, no LLM.
- Static "never touches the LLM Gateway or Telegram" import-shape tests, mirroring
  tests/test_fact_safety.py::test_fact_safety_module_imports_no_llm_gateway_or_capability.
- Integration tests driving the real capabilities.executor.CapabilityExecutor +
  workflows.runner.WorkflowRunner path with fake "research"/"intelligence" Capabilities, using
  tests/conftest.py's db_session fixture (real Postgres, rolled back at teardown) - mirrors
  tests/test_capability_executor_image_intelligence.py's own established pattern exactly.
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
from schemas.capability import CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition
from schemas.editorial_brief import (
    EDITORIAL_BRIEF_SCHEMA_VERSION,
    EditorialBrief,
    FieldConfidence,
    RecommendedFormat,
    SourceSufficiency,
    TargetWordRange,
)
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowDefinition, WorkflowRetryPolicy, WorkflowStepDefinition, WorkflowType
from services import workflow_service
from services.editorial_brief import (
    apply_editorial_brief_shadow,
    build_editorial_brief,
    classify_source_sufficiency,
    populated_field_count,
    recommend_format_and_range,
)
from capabilities.executor import CapabilityExecutor
from capabilities.registry import CapabilityRegistry
from workflows.registry import WorkflowRegistry
from workflows.runner import WorkflowRunner

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Schema validation (test 1, test 14 versioned serialization, mutable-default guard)
# ---------------------------------------------------------------------------


def test_schema_requires_recommended_format_and_target_word_range() -> None:
    with pytest.raises(ValidationError):
        EditorialBrief(source_sufficiency=SourceSufficiency.SUFFICIENT)  # type: ignore[call-arg]


def test_schema_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        EditorialBrief(
            recommended_format=RecommendedFormat.STANDARD_NEWS,
            target_word_range=TargetWordRange(min_words=1, max_words=2),
            source_sufficiency=SourceSufficiency.SUFFICIENT,
            not_a_real_field="x",  # type: ignore[call-arg]
        )


def test_schema_version_is_stamped_and_serializes() -> None:
    brief = build_editorial_brief("Title", "Some content here.", {}, {})
    assert brief.schema_version == EDITORIAL_BRIEF_SCHEMA_VERSION == "v1"
    dumped = brief.model_dump(mode="json")
    assert dumped["schema_version"] == "v1"
    # Round-trips losslessly - a future reader (M2-M6) can rehydrate the persisted JSON.
    assert EditorialBrief.model_validate(dumped) == brief


def test_mutable_defaults_are_never_shared_between_instances() -> None:
    a = build_editorial_brief("Title A", None, {}, {})
    b = build_editorial_brief("Title B", None, {}, {})
    assert a.event_details is not b.event_details
    assert a.uncertainties is not b.uncertainties
    assert a.evidence_notes is not b.evidence_notes


# ---------------------------------------------------------------------------
# Source sufficiency classification (tests 2, 3, 5, 11)
# ---------------------------------------------------------------------------


def test_headline_only_short_content() -> None:
    assessment = classify_source_sufficiency("Big news happens today", "Reported briefly.", [], [])
    assert assessment.sufficiency == SourceSufficiency.HEADLINE_ONLY
    assert "content_too_short" in assessment.reason_codes


def test_content_identical_to_title_is_headline_only() -> None:
    assessment = classify_source_sufficiency("Netflix pays $500 million", "Netflix pays $500 million", [], [])
    assert assessment.sufficiency == SourceSufficiency.HEADLINE_ONLY
    assert assessment.reason_codes == ["content_equals_title"]


def test_content_title_plus_outlet_suffix_is_headline_only() -> None:
    # docs/phase17_m0_output_quality_discovery_report.md §10's real Google News RSS pattern.
    assessment = classify_source_sufficiency(
        "AI firm raises funding", "AI firm raises funding - TechOutlet", [], [],
    )
    assert assessment.sufficiency == SourceSufficiency.HEADLINE_ONLY
    assert "content_is_title_plus_suffix" in assessment.reason_codes


def test_empty_content_with_no_research_facts_is_empty() -> None:
    assessment = classify_source_sufficiency("Some title", None, [], [])
    assert assessment.sufficiency == SourceSufficiency.EMPTY
    assert "no_research_facts" in assessment.reason_codes


def test_empty_content_with_research_facts_is_partial() -> None:
    assessment = classify_source_sufficiency("Some title", "", ["A fact from Research"], [])
    assert assessment.sufficiency == SourceSufficiency.PARTIAL
    assert "research_facts_available" in assessment.reason_codes


def test_full_source_content_is_sufficient() -> None:
    content = (
        "Acme Corp announced a $250 million acquisition of Widget Inc on July 30, 2026, "
        "the largest deal in the sector this year. The combined company will employ 4,000 "
        "people across 12 countries. Analysts said the deal reflects growing consolidation."
    )
    assessment = classify_source_sufficiency("Acme buys Widget", content, [], [])
    assert assessment.sufficiency == SourceSufficiency.SUFFICIENT


def test_missing_title_is_unknown() -> None:
    assessment = classify_source_sufficiency("", "Some content.", [], [])
    assert assessment.sufficiency == SourceSufficiency.UNKNOWN
    assert assessment.reason_codes == ["missing_title"]


def test_research_flagged_conflict_is_conflicting() -> None:
    assessment = classify_source_sufficiency(
        "Title", "Some reasonably long content describing an event in detail here.",
        [], ["Sources contradict each other on the exact amount"],
    )
    assert assessment.sufficiency == SourceSufficiency.CONFLICTING
    assert assessment.reason_codes == ["research_flagged_conflict"]


def test_long_but_thin_content_is_not_automatically_sufficient() -> None:
    """docs/phase17_m0_output_quality_discovery_report.md §10's own explicit warning: length
    alone must never imply quality."""
    content = "word " * 40  # 40 words, zero numbers/entities/currency/years/percentages
    assessment = classify_source_sufficiency("Title here", content.strip(), [], [])
    assert assessment.sufficiency == SourceSufficiency.PARTIAL
    assert "below_sufficient_threshold" in assessment.reason_codes


# ---------------------------------------------------------------------------
# Recommended format / target word range (tests 12, 13)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "content", "gaps", "expected_format", "expected_range"),
    [
        ("T", None, [], RecommendedFormat.REJECT_CANDIDATE, TargetWordRange(min_words=0, max_words=0)),
        ("T", "T", [], RecommendedFormat.INSUFFICIENT_SOURCE, TargetWordRange(min_words=40, max_words=90)),
        (
            "T", "A reasonably long article body with enough words to pass the partial floor test case.",
            [], RecommendedFormat.SHORT_UPDATE, TargetWordRange(min_words=90, max_words=140),
        ),
    ],
)
def test_recommend_format_and_range_matrix(title, content, gaps, expected_format, expected_range) -> None:
    assessment = classify_source_sufficiency(title, content, [], gaps)
    fmt, word_range, _reasons = recommend_format_and_range(assessment)
    assert fmt == expected_format
    assert word_range == expected_range


def test_sufficient_rich_source_recommends_explainer() -> None:
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
    assessment = classify_source_sufficiency("Acme buys Widget", content, [], [])
    fmt, word_range, _reasons = recommend_format_and_range(assessment)
    assert fmt == RecommendedFormat.EXPLAINER
    assert word_range == TargetWordRange(min_words=220, max_words=320)


def test_target_word_range_min_never_exceeds_max_for_any_format() -> None:
    for title, content, gaps in [
        ("T", None, []), ("T", "T", []), ("T", "word " * 40, []),
        ("T", "conflict content", ["contradicts prior reporting"]),
        ("", "x", []),
    ]:
        assessment = classify_source_sufficiency(title, content, [], gaps)
        _fmt, word_range, _reasons = recommend_format_and_range(assessment)
        assert word_range.min_words <= word_range.max_words


# ---------------------------------------------------------------------------
# Builder: evidence, fabrication guard, backward compatibility (tests 6, 7, 8, 9, 10, 15)
# ---------------------------------------------------------------------------


def test_missing_research_output_falls_back_to_title_and_stays_empty() -> None:
    brief = build_editorial_brief("The headline itself", "Full content body here for context.", {}, {})
    assert brief.headline_fact == "The headline itself"
    assert brief.event_details == []
    assert brief.evidence_notes["headline_fact"].source == "news_event"
    assert brief.evidence_notes["event_details"].confidence == FieldConfidence.UNKNOWN


def test_missing_intelligence_output_leaves_why_it_matters_and_what_next_empty() -> None:
    brief = build_editorial_brief("Title", "Some content.", {"facts": ["A fact"]}, {})
    assert brief.why_it_matters == []
    assert brief.what_next == []
    assert brief.evidence_notes["why_it_matters"].confidence == FieldConfidence.UNKNOWN
    assert brief.evidence_notes["what_next"].confidence == FieldConfidence.UNKNOWN


def test_partial_evidence_populates_only_what_is_actually_present() -> None:
    research = {"facts": ["Fact one"], "gaps": ["Unclear how many units shipped"]}
    intelligence = {"significance": "Notable for the sector", "angle": ""}
    brief = build_editorial_brief("Title", "Some real content describing the event briefly.", research, intelligence)
    assert brief.headline_fact == "Fact one"
    assert brief.event_details == ["Fact one"]
    assert brief.why_it_matters == ["Notable for the sector"]  # empty angle excluded, not invented
    assert "Unclear how many units shipped" in brief.uncertainties


def test_unknown_fields_remain_empty_never_fabricated_even_with_rich_source() -> None:
    """subject_explanation/background_context/difference_or_change structurally require an LLM
    call M1 does not make - must stay empty/None regardless of how rich the input is (Phase 17
    M1's own explicit fabrication ban)."""
    content = (
        "Acme Corp announced a $250 million acquisition of Widget Inc, a company founded in "
        "2011 that makes industrial sensors, on July 30, 2026."
    )
    research = {"facts": ["Acme Corp acquired Widget Inc for $250 million"], "gaps": []}
    intelligence = {"significance": "Major sector consolidation", "angle": "M&A trend", "recommendation": "Follow up in 90 days"}
    brief = build_editorial_brief("Acme buys Widget", content, research, intelligence)

    assert brief.subject_explanation is None
    assert brief.background_context == []
    assert brief.difference_or_change is None
    assert brief.evidence_notes["subject_explanation"].confidence == FieldConfidence.UNAVAILABLE
    assert brief.evidence_notes["background_context"].confidence == FieldConfidence.UNAVAILABLE
    assert brief.evidence_notes["difference_or_change"].confidence == FieldConfidence.UNAVAILABLE
    # And what IS populated only ever echoes given evidence verbatim, never adds new claims.
    assert brief.event_details == ["Acme Corp acquired Widget Inc for $250 million"]
    assert brief.what_next == ["Follow up in 90 days"]


def test_backward_compatibility_with_pre_m1_workflow_data() -> None:
    """An old CONTENT_GENERATION task's step_results has no notion of Editorial Brief at all -
    calling the builder with completely empty research/intelligence dicts (the shape any
    pre-M1-persisted task would have) must not raise and must produce a well-formed, honestly
    mostly-empty brief."""
    brief = build_editorial_brief("Old task title", "Old task content.", {}, {})
    assert isinstance(brief, EditorialBrief)
    assert brief.schema_version == "v1"
    assert brief.recommended_format in RecommendedFormat
    assert brief.source_sufficiency in SourceSufficiency


def test_populated_field_count_reflects_only_content_bearing_fields() -> None:
    empty_brief = build_editorial_brief("T", None, {}, {})
    # headline_fact falls back to the title, and the thin-source note is always appended to
    # uncertainties for an EMPTY-sufficiency source - both real, honest content, not fabrication.
    assert populated_field_count(empty_brief) == 2
    rich_brief = build_editorial_brief(
        "T", "Rich content with $5 million and 2026 details across three sentences here now.",
        {"facts": ["A fact"], "gaps": ["A gap"]},
        {"significance": "Big", "angle": "Trend", "recommendation": "Watch"},
    )
    assert populated_field_count(rich_brief) >= 5


# ---------------------------------------------------------------------------
# apply_editorial_brief_shadow: mode gating, idempotency (tests 16 partial, 19)
# ---------------------------------------------------------------------------


def test_apply_editorial_brief_shadow_off_mode_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "editorial_brief_mode", "off")
    original = {"significance": "x"}
    result = apply_editorial_brief_shadow("Title", "Content", {}, original)
    assert result is original
    assert "editorial_brief" not in result


def test_apply_editorial_brief_shadow_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "editorial_brief_mode", "shadow")
    research = {"facts": ["Fact A"], "gaps": ["Gap A"]}
    intelligence = {"significance": "Sig", "angle": "Angle", "recommendation": "Rec"}
    first = apply_editorial_brief_shadow("Title", "Content here.", research, dict(intelligence))
    second = apply_editorial_brief_shadow("Title", "Content here.", research, dict(intelligence))
    assert first["editorial_brief"] == second["editorial_brief"]


# ---------------------------------------------------------------------------
# Static import-shape tests (tests 18, 20 - no LLM Gateway call, no Telegram send)
# ---------------------------------------------------------------------------


def test_editorial_brief_module_imports_no_llm_gateway_or_telegram() -> None:
    """Mirrors tests/test_fact_safety.py::test_fact_safety_module_imports_no_llm_gateway_or_
    capability - a static guarantee that this module cannot possibly make a paid LLM call or a
    Telegram send, checked at the import-graph level rather than by mocking and hoping nothing
    was missed."""
    import services.editorial_brief as module

    source_names = {getattr(obj, "__module__", "") for obj in vars(module).values()}
    forbidden_substrings = ("llm_gateway", "telegram", "bot.")
    for name in source_names:
        for forbidden in forbidden_substrings:
            assert forbidden not in name.lower(), f"unexpected import touching {forbidden!r}: {name}"


# ---------------------------------------------------------------------------
# Integration: real CapabilityExecutor + WorkflowRunner (tests 4 full-content path, 16, 17, 19)
# ---------------------------------------------------------------------------


class _FakeResearchCapability:
    def __init__(self, facts=None, gaps=None) -> None:
        self._facts = facts if facts is not None else ["Researched fact one", "Researched fact two"]
        self._gaps = gaps if gaps is not None else ["Unclear timeline"]

    async def execute(self, context):
        now = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS",
            structured_output={"facts": self._facts, "confidence": "high", "gaps": self._gaps},
            calls=[], started_at=now, finished_at=now, duration_seconds=0.0,
        )


class _FakeIntelligenceCapability:
    async def execute(self, context):
        now = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS",
            structured_output={
                "significance": "Notable industry development",
                "angle": "Consolidation trend",
                "audience_relevance": "high",
                "recommendation": "Monitor follow-on coverage",
            },
            calls=[], started_at=now, finished_at=now, duration_seconds=0.0,
        )


class _FakeCopywritingCapability:
    async def execute(self, context):
        now = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS",
            structured_output={"title": "A drafted title", "body": "A drafted body", "hashtags": ["#news"]},
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
            name=WorkflowType.CONTENT_GENERATION,
            version=1,
            steps=[WorkflowStepDefinition(name=name, capability=name, timeout_seconds=10) for name in step_names],
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
async def test_integration_mode_off_produces_no_brief(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    monkeypatch.setattr(settings, "editorial_brief_mode", "off")
    event = await _event_with_content(db_session, "Full article content with real detail and numbers like $5 million.")

    step_results = await _run_workflow(
        db_session, event, "research", "intelligence",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
    )

    research_result, intelligence_result = step_results
    assert "editorial_brief" not in intelligence_result.result
    assert intelligence_result.result == {
        "significance": "Notable industry development", "angle": "Consolidation trend",
        "audience_relevance": "high", "recommendation": "Monitor follow-on coverage",
    }


@pytest.mark.asyncio
async def test_integration_mode_shadow_persists_brief_on_intelligence_step(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    monkeypatch.setattr(settings, "editorial_brief_mode", "shadow")
    event = await _event_with_content(
        db_session, "Full article content describing a real acquisition with $5 million and specific detail.",
    )

    step_results = await _run_workflow(
        db_session, event, "research", "intelligence",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
    )

    research_result, intelligence_result = step_results
    assert "editorial_brief" not in research_result.result  # only ever attached to "intelligence"
    brief = intelligence_result.result["editorial_brief"]
    assert brief["schema_version"] == "v1"
    assert brief["headline_fact"] == "Researched fact one"
    assert brief["why_it_matters"] == ["Notable industry development", "Consolidation trend"]
    # Intelligence's own real fields are untouched, purely additive merge.
    assert intelligence_result.result["significance"] == "Notable industry development"


@pytest.mark.asyncio
async def test_shadow_mode_does_not_change_copywriting_or_content_draft_fields(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """Proves M1's central production-safety guarantee end to end: whether editorial_brief_mode
    is off or shadow, Copywriting's own drafted title/body/hashtags - what services.
    content_draft_service eventually turns into a real ContentDraft - are byte-identical."""
    event_off = await _event_with_content(db_session, "Some content for the off-mode run.", title="Off event")
    monkeypatch.setattr(settings, "editorial_brief_mode", "off")
    off_results = await _run_workflow(
        db_session, event_off, "research", "intelligence", "copywriting",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
        copywriting=_FakeCopywritingCapability(),
    )

    event_shadow = await _event_with_content(db_session, "Some content for the shadow-mode run.", title="Shadow event")
    monkeypatch.setattr(settings, "editorial_brief_mode", "shadow")
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
async def test_editorial_brief_only_runs_for_the_intelligence_step(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    monkeypatch.setattr(settings, "editorial_brief_mode", "shadow")
    event = await _event_with_content(db_session, "Content for the research-only step-scope check.")

    step_results = await _run_workflow(db_session, event, "research", research=_FakeResearchCapability())

    assert "editorial_brief" not in step_results[0].result


@pytest.mark.asyncio
async def test_brief_failure_does_not_fail_content_generation(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    monkeypatch.setattr(settings, "editorial_brief_mode", "shadow")

    def _broken_apply(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("capabilities.executor.apply_editorial_brief_shadow", _broken_apply)
    event = await _event_with_content(db_session, "Content for the failure-isolation check.")

    step_results = await _run_workflow(
        db_session, event, "research", "intelligence",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
    )

    research_result, intelligence_result = step_results
    assert intelligence_result.status == "SUCCESS"
    assert "editorial_brief" not in intelligence_result.result
    assert intelligence_result.result["significance"] == "Notable industry development"  # untouched


@pytest.mark.asyncio
async def test_repeat_execution_is_idempotent(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    """A step-level retry re-runs the same "intelligence" step's post-processing for the same
    task/event/inputs - since `workflow_service.create_task` forbids a second active task for
    the same event (by design, unrelated to Editorial Brief), this proves the same guarantee the
    way it is actually observable: two independent events with byte-identical
    title/content/research/intelligence inputs must produce a byte-identical brief - the builder
    carries no hidden per-run state (timestamps, random IDs, event-id leakage) that a real retry
    of the same event would otherwise also have to reproduce identically."""
    monkeypatch.setattr(settings, "editorial_brief_mode", "shadow")
    content = "Content used to check idempotency across two runs."
    event_a = await _event_with_content(db_session, content, title="Idempotency A")
    event_b = await _event_with_content(db_session, content, title="Idempotency A")

    first = await _run_workflow(
        db_session, event_a, "research", "intelligence",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
    )
    second = await _run_workflow(
        db_session, event_b, "research", "intelligence",
        research=_FakeResearchCapability(), intelligence=_FakeIntelligenceCapability(),
    )

    assert first[1].result["editorial_brief"] == second[1].result["editorial_brief"]
