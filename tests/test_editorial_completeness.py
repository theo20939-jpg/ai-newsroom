"""Phase 17 M5 - Editorial Completeness Gate tests (docs/
phase17_m5_editorial_completeness_gate_shadow_report.md).

Pure unit tests only (no DB, no LLM) - schema validation, individual completeness criteria,
headline-rewrite risk detection, and editorial_recommendation logic. Integration tests (shadow
mode, failure isolation, ContentDraft/Telegram non-mutation) live in
tests/test_phase17_m5_integration.py; Fact Safety calibration tests live in
tests/test_fact_safety_calibration.py.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas.adaptive_length import AdaptiveLengthPlan, Complexity, DeliveryMode, LengthConfidence
from schemas.beginner_friendly import AudienceLevel, BeginnerFriendlyPlan, JargonRisk, WordRange
from schemas.calibrated_fact_safety import CalibratedFactSafetyAssessment
from schemas.candidate_fact_safety import AuditSeverity, FactSafetyStatus
from schemas.editorial_brief import EditorialBrief, RecommendedFormat, SourceSufficiency, TargetWordRange
from schemas.editorial_completeness import (
    EDITORIAL_COMPLETENESS_SCHEMA_VERSION,
    CompletenessConfidence,
    CompletenessCriterionResult,
    CriterionStatus,
    DraftKind,
    EditorialCompletenessAssessment,
    EditorialRecommendation,
    HeadlineRewriteRisk,
    ParagraphStatus,
    SafeLengthStatus,
)
from services.editorial_completeness import (
    assess_headline_rewrite_risk,
    build_editorial_completeness_assessment,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _brief(**overrides) -> EditorialBrief:
    defaults = dict(
        headline_fact="Netflix paid $500 million for streaming rights.",
        event_details=["The deal covers six spinoffs.", "AMC+ shares the rights."],
        background_context=["The franchise has run for over a decade."],
        difference_or_change="Rights are now shared, not exclusive.",
        why_it_matters=["This shows streaming platforms competing for content."],
        what_next=["The next season airs in spring."],
        uncertainties=["The exact contract term is not disclosed."],
        recommended_format=RecommendedFormat.STANDARD_NEWS,
        target_word_range=TargetWordRange(min_words=60, max_words=120),
        source_sufficiency=SourceSufficiency.SUFFICIENT,
    )
    defaults.update(overrides)
    return EditorialBrief(**defaults)  # type: ignore[arg-type]


def _beginner_plan(**overrides) -> BeginnerFriendlyPlan:
    defaults = dict(
        audience_level=AudienceLevel.GENERAL,
        explanation_required=False,
        subjects_to_explain=[],
        terms_to_explain=[],
        assumed_knowledge=[],
        unexplainable_terms=[],
        explanation_budget=0,
        context_budget=0,
        detail_target=2,
        paragraph_target=2,
        why_it_matters_required=True,
        what_next_allowed=True,
        uncertainty_required=True,
        jargon_risk=JargonRisk.LOW,
        ideal_range=WordRange(min_words=80, target_words=100, max_words=120),
        safe_range=WordRange(min_words=60, target_words=80, max_words=100),
    )
    defaults.update(overrides)
    return BeginnerFriendlyPlan(**defaults)  # type: ignore[arg-type]


def _adaptive_plan(**overrides) -> AdaptiveLengthPlan:
    defaults = dict(
        recommended_format=RecommendedFormat.STANDARD_NEWS,
        complexity=Complexity.NORMAL,
        source_sufficiency=SourceSufficiency.SUFFICIENT,
        min_words=60, target_words=80, max_words=100,
        hard_character_limit=1024, delivery_mode=DeliveryMode.TEXT_MESSAGE,
        paragraph_target=2, detail_target=2,
        confidence=LengthConfidence.HIGH,
    )
    defaults.update(overrides)
    return AdaptiveLengthPlan(**defaults)  # type: ignore[arg-type]


def _calibrated(status: FactSafetyStatus = FactSafetyStatus.PASS) -> CalibratedFactSafetyAssessment:
    return CalibratedFactSafetyAssessment(
        raw_audit_status=status, calibrated_status=status, human_review_required=status != FactSafetyStatus.PASS,
    )


def _brief_ru(**overrides) -> EditorialBrief:
    """Same-language (Russian) EditorialBrief fixture, phrased to directly overlap `_GOOD_BODY`'s
    own wording - used only where the test needs every criterion to cleanly PASS/FAIL by design,
    without exercising the separate, disclosed EN-headline/RU-draft cross-language matching gap
    `_brief()` (English fields) is used to demonstrate elsewhere."""
    defaults = dict(
        headline_fact="Netflix paid $500 for the deal.",
        event_details=["шесть спин-оффов сериала", "совместно с AMC+"],
        background_context=["конкурируют за популярный контент"],
        difference_or_change="распределяются совместно с AMC+, а не эксклюзивно",
        why_it_matters=["конкурируют за популярный контент"],
        what_next=["Следующий сезон выйдет весной"],
        uncertainties=["Точный срок контракта не раскрыт"],
        recommended_format=RecommendedFormat.STANDARD_NEWS,
        target_word_range=TargetWordRange(min_words=60, max_words=120),
        source_sufficiency=SourceSufficiency.SUFFICIENT,
    )
    defaults.update(overrides)
    return EditorialBrief(**defaults)  # type: ignore[arg-type]


_GOOD_TITLE = "Netflix заплатила $500 млн за права на «Ходячих мертвецов»"
_GOOD_BODY = (
    "Netflix заплатила $500 миллионов за продление прав на «Ходячих мертвецов» и шесть спин-оффов. "
    "Права теперь распределяются совместно с AMC+, а не эксклюзивно.\n\n"
    "Это показывает, как платформы конкурируют за популярный контент. Точный срок контракта не раскрыт. "
    "Следующий сезон выйдет весной."
)


# ---------------------------------------------------------------------------
# SCHEMAS (1-5)
# ---------------------------------------------------------------------------


def test_completeness_criterion_result_validation() -> None:
    result = CompletenessCriterionResult(
        criterion="headline_fact_covered", status=CriterionStatus.PASS, score=1.0, required=True,
        evidence_available=True, confidence=CompletenessConfidence.HIGH,
    )
    assert result.status == CriterionStatus.PASS
    with pytest.raises(ValidationError):
        CompletenessCriterionResult(
            criterion="x", status=CriterionStatus.PASS, score=1.5, required=True,
            evidence_available=True, confidence=CompletenessConfidence.HIGH,
        )


def test_editorial_completeness_assessment_validation() -> None:
    assessment = build_editorial_completeness_assessment(
        draft_title="A title", draft_body=_GOOD_BODY, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, editorial_brief=_brief(),
        beginner_friendly_plan=_beginner_plan(), calibrated_fact_safety=_calibrated(),
    )
    assert assessment.schema_version == EDITORIAL_COMPLETENESS_SCHEMA_VERSION
    assert 0.0 <= assessment.completeness_score <= 1.0
    with pytest.raises(ValidationError):
        EditorialCompletenessAssessment(
            draft_kind=DraftKind.UNKNOWN, source_sufficiency=SourceSufficiency.UNKNOWN,
            required_criteria_count=-1, passed_required_count=0, partial_required_count=0,
            failed_required_count=0, completeness_score=0.5, confidence=CompletenessConfidence.LOW,
            headline_rewrite_risk=HeadlineRewriteRisk.NOT_APPLICABLE,
            safe_length_status=SafeLengthStatus.NOT_APPLICABLE, paragraph_status=ParagraphStatus.NOT_APPLICABLE,
            editorial_recommendation=EditorialRecommendation.REVIEW,
        )


def test_calibrated_fact_safety_assessment_validation() -> None:
    assessment = CalibratedFactSafetyAssessment(
        raw_audit_status=FactSafetyStatus.FAIL, calibrated_status=FactSafetyStatus.REVIEW,
        severity=AuditSeverity.MEDIUM, human_review_required=True,
    )
    assert assessment.calibrated_status == FactSafetyStatus.REVIEW
    with pytest.raises(ValidationError):
        CalibratedFactSafetyAssessment(
            raw_audit_status="not-a-status",  # type: ignore[arg-type]
            calibrated_status=FactSafetyStatus.PASS, human_review_required=False,
        )


def test_versioned_serialization() -> None:
    assessment = build_editorial_completeness_assessment(
        draft_title="A title", draft_body=_GOOD_BODY, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, editorial_brief=_brief(),
        beginner_friendly_plan=_beginner_plan(), calibrated_fact_safety=_calibrated(),
    )
    dumped = assessment.model_dump(mode="json")
    assert dumped["schema_version"] == "v1"
    assert dumped["policy_version"] == "v1"
    restored = EditorialCompletenessAssessment.model_validate(dumped)
    assert restored == assessment


def test_no_mutable_defaults() -> None:
    a = CompletenessCriterionResult(
        criterion="x", status=CriterionStatus.PASS, score=1.0, required=True,
        evidence_available=True, confidence=CompletenessConfidence.HIGH,
    )
    b = CompletenessCriterionResult(
        criterion="y", status=CriterionStatus.PASS, score=1.0, required=True,
        evidence_available=True, confidence=CompletenessConfidence.HIGH,
    )
    assert a.matched_evidence is not b.matched_evidence
    assert a.reason_codes is not b.reason_codes
    assessment_a = CalibratedFactSafetyAssessment(
        raw_audit_status=FactSafetyStatus.PASS, calibrated_status=FactSafetyStatus.PASS, human_review_required=False,
    )
    assessment_b = CalibratedFactSafetyAssessment(
        raw_audit_status=FactSafetyStatus.PASS, calibrated_status=FactSafetyStatus.PASS, human_review_required=False,
    )
    assert assessment_a.suppressed_false_positive_flags is not assessment_b.suppressed_false_positive_flags


# ---------------------------------------------------------------------------
# COMPLETENESS CRITERIA (6-35)
# ---------------------------------------------------------------------------


def test_headline_fact_covered() -> None:
    # A bare currency-anchored number ("$500", no translated magnitude word) is script-neutral -
    # it matches across the EditorialBrief's own English `headline_fact` and a Russian draft body
    # (a real, disclosed limitation: a *translated* magnitude word like "million"/"миллионов"
    # does not cross-match - see this milestone's own report, "known limitations").
    body = "Netflix заплатила $500 за продление прав на стриминг."
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=body, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT,
        editorial_brief=_brief(headline_fact="Netflix paid $500 for streaming rights."),
    )
    crit = next(c for c in a.criteria if c.criterion == "headline_fact_covered")
    assert crit.status in (CriterionStatus.PASS, CriterionStatus.PARTIAL)
    assert crit.required is True


def test_headline_fact_missing() -> None:
    body = "Совершенно не связанный текст про другое событие без чисел."
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=body, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT,
        editorial_brief=_brief(headline_fact="Netflix paid $500 million for streaming rights."),
    )
    crit = next(c for c in a.criteria if c.criterion == "headline_fact_covered")
    assert crit.status == CriterionStatus.FAIL


def test_event_details_fully_covered() -> None:
    body = "The deal covers six spinoffs. AMC+ shares the rights. Extra filler sentence here."
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=body, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, editorial_brief=_brief(headline_fact=None),
    )
    crit = next(c for c in a.criteria if c.criterion == "event_details_covered")
    assert crit.status == CriterionStatus.PASS


def test_event_details_partially_covered() -> None:
    body = "The deal covers six spinoffs. Nothing else relevant is mentioned here at all."
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=body, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, editorial_brief=_brief(headline_fact=None),
    )
    crit = next(c for c in a.criteria if c.criterion == "event_details_covered")
    assert crit.status == CriterionStatus.PARTIAL
    assert crit.missing_items


def test_subject_explanation_required_and_present() -> None:
    body = "Текст упоминает SOTA - state of the art, лучший из опубликованных результатов на сегодня."
    plan = _beginner_plan(explanation_required=True, terms_to_explain=["SOTA"])
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=body, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, beginner_friendly_plan=plan,
    )
    crit = next(c for c in a.criteria if c.criterion == "subject_explanation_covered")
    assert crit.status == CriterionStatus.PASS
    assert crit.required is True


def test_subject_explanation_required_and_missing() -> None:
    body = "Текст вообще не упоминает нужный термин."
    plan = _beginner_plan(explanation_required=True, terms_to_explain=["SOTA"])
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=body, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, beginner_friendly_plan=plan,
    )
    crit = next(c for c in a.criteria if c.criterion == "subject_explanation_covered")
    assert crit.status == CriterionStatus.FAIL


def test_subject_explanation_not_required() -> None:
    plan = _beginner_plan(explanation_required=False)
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=_GOOD_BODY, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, beginner_friendly_plan=plan,
    )
    crit = next(c for c in a.criteria if c.criterion == "subject_explanation_covered")
    assert crit.status == CriterionStatus.NOT_APPLICABLE
    assert crit.required is False


def test_context_required_and_present() -> None:
    body = "The franchise has run for over a decade, which explains the high price tag today."
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=body, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, editorial_brief=_brief(headline_fact=None),
    )
    crit = next(c for c in a.criteria if c.criterion == "background_context_covered")
    assert crit.status == CriterionStatus.PASS
    assert crit.required is True


def test_context_unavailable() -> None:
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=_GOOD_BODY, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, editorial_brief=_brief(background_context=[]),
    )
    crit = next(c for c in a.criteria if c.criterion == "background_context_covered")
    assert crit.status == CriterionStatus.NOT_APPLICABLE
    assert crit.required is False


def test_why_it_matters_present() -> None:
    body = "This shows streaming platforms competing for content in a crowded market this year."
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=body, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, editorial_brief=_brief(headline_fact=None),
        beginner_friendly_plan=_beginner_plan(why_it_matters_required=True),
    )
    crit = next(c for c in a.criteria if c.criterion == "why_it_matters_covered")
    assert crit.status == CriterionStatus.PASS


def test_why_it_matters_not_supported_by_evidence() -> None:
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=_GOOD_BODY, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, editorial_brief=_brief(why_it_matters=[]),
    )
    crit = next(c for c in a.criteria if c.criterion == "why_it_matters_covered")
    assert crit.status == CriterionStatus.NOT_APPLICABLE
    assert crit.required is False


def test_what_next_present() -> None:
    body = "The next season airs in spring, according to the studio's own announcement today."
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=body, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, editorial_brief=_brief(headline_fact=None),
        beginner_friendly_plan=_beginner_plan(what_next_allowed=True),
    )
    crit = next(c for c in a.criteria if c.criterion == "what_next_covered")
    assert crit.status == CriterionStatus.PASS


def test_what_next_not_applicable() -> None:
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=_GOOD_BODY, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, editorial_brief=_brief(what_next=["Something"]),
        beginner_friendly_plan=_beginner_plan(what_next_allowed=False),
    )
    crit = next(c for c in a.criteria if c.criterion == "what_next_covered")
    assert crit.status == CriterionStatus.NOT_APPLICABLE
    assert crit.required is False


def test_uncertainty_required_and_present() -> None:
    body = "Точный срок контракта не раскрыт, что оставляет неопределённость в деталях сделки."
    brief = _brief(headline_fact=None, uncertainties=["Точный срок контракта не раскрыт."])
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=body, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.PARTIAL, editorial_brief=brief,
    )
    crit = next(c for c in a.criteria if c.criterion == "uncertainty_covered")
    assert crit.status == CriterionStatus.PASS
    assert crit.required is True


def test_uncertainty_required_and_missing() -> None:
    body = "Полностью уверенный текст без единого упоминания неопределённости или пробелов."
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=body, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.PARTIAL, editorial_brief=_brief(uncertainties=[]),
    )
    crit = next(c for c in a.criteria if c.criterion == "uncertainty_covered")
    assert crit.status == CriterionStatus.FAIL
    assert crit.required is True


def test_safe_range_pass() -> None:
    body = " ".join(["word"] * 80)
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=body, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, beginner_friendly_plan=_beginner_plan(),
    )
    assert a.safe_length_status == SafeLengthStatus.WITHIN_RANGE


def test_safe_range_below() -> None:
    body = " ".join(["word"] * 10)
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=body, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, beginner_friendly_plan=_beginner_plan(),
    )
    assert a.safe_length_status == SafeLengthStatus.BELOW_RANGE


def test_safe_range_above() -> None:
    body = " ".join(["word"] * 200)
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=body, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, beginner_friendly_plan=_beginner_plan(),
    )
    assert a.safe_length_status == SafeLengthStatus.ABOVE_RANGE


def test_structure_adequate() -> None:
    body = "Para one sentence.\n\nPara two sentence."
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=body, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, beginner_friendly_plan=_beginner_plan(paragraph_target=2),
    )
    assert a.paragraph_status == ParagraphStatus.ADEQUATE


def test_structure_weak() -> None:
    body = "Only one single paragraph with no breaks at all in the whole text."
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=body, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, beginner_friendly_plan=_beginner_plan(paragraph_target=3),
    )
    assert a.paragraph_status == ParagraphStatus.WEAK


def test_headline_rewrite_positive() -> None:
    # draft_title/draft_body are always the SAME language in real usage (both the candidate's own
    # Russian text) - the title is never the raw English NewsEvent title (that lives in
    # EditorialBrief.headline_fact instead). A body that adds a genuinely new checkable fact
    # (a percentage the title never mentions) is LOW risk.
    title = "Netflix заплатила $500 млн за права на «Ходячих мертвецов»"
    body = "Netflix заплатила $500 млн за права на «Ходячих мертвецов». Выручка компании выросла на 12%."
    risk = assess_headline_rewrite_risk(title, body, SourceSufficiency.SUFFICIENT, _brief())
    assert risk == HeadlineRewriteRisk.LOW


def test_headline_rewrite_negative() -> None:
    title = "Netflix заплатила $500 млн за права на «Ходячих мертвецов»"
    body = "Netflix заплатила $500 млн за права на «Ходячих мертвецов», сообщает компания."
    risk = assess_headline_rewrite_risk(title, body, SourceSufficiency.SUFFICIENT, None)
    assert risk == HeadlineRewriteRisk.HIGH


def test_headline_only_source_handling() -> None:
    risk = assess_headline_rewrite_risk("Man seeks millions after swatting", "Man seeks millions after swatting.", SourceSufficiency.HEADLINE_ONLY, None)
    assert risk == HeadlineRewriteRisk.NOT_APPLICABLE
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body="Some honest short text. Не указано, сколько именно.",
        draft_kind=DraftKind.SHADOW_CANDIDATE, source_sufficiency=SourceSufficiency.HEADLINE_ONLY,
        calibrated_fact_safety=_calibrated(),
    )
    assert a.editorial_recommendation == EditorialRecommendation.INSUFFICIENT_SOURCE


def test_partial_source_handling() -> None:
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=_GOOD_BODY, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.PARTIAL, editorial_brief=_brief(source_sufficiency=SourceSufficiency.PARTIAL),
        beginner_friendly_plan=_beginner_plan(), calibrated_fact_safety=_calibrated(),
    )
    assert a.source_sufficiency == SourceSufficiency.PARTIAL


def test_sufficient_source_handling() -> None:
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=_GOOD_BODY, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, editorial_brief=_brief(),
        beginner_friendly_plan=_beginner_plan(), calibrated_fact_safety=_calibrated(),
    )
    assert a.source_sufficiency == SourceSufficiency.SUFFICIENT


def test_conflicting_source_handling() -> None:
    body = "Источники расходятся: часть данных не подтверждена и остаётся неясной."
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=body, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.CONFLICTING, editorial_brief=_brief(uncertainties=[]),
    )
    crit = next(c for c in a.criteria if c.criterion == "uncertainty_covered")
    assert crit.required is True
    assert crit.status == CriterionStatus.PASS


def test_empty_draft() -> None:
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body="", draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, editorial_brief=_brief(),
        calibrated_fact_safety=_calibrated(),
    )
    assert a.editorial_recommendation in (EditorialRecommendation.NOT_READY, EditorialRecommendation.REVIEW)
    filler_crit = next(c for c in a.criteria if c.criterion == "filler_absent")
    assert filler_crit.status == CriterionStatus.PASS  # no filler phrase in empty text either


def test_whitespace_only_draft() -> None:
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body="   \n\n  ", draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT, editorial_brief=_brief(),
    )
    assert a.paragraph_status in (ParagraphStatus.WEAK, ParagraphStatus.NOT_APPLICABLE)


def test_filler_detection_interaction() -> None:
    body = _GOOD_BODY + " Время покажет, как будут развиваться события."
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=body, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT,
    )
    crit = next(c for c in a.criteria if c.criterion == "filler_absent")
    assert crit.status == CriterionStatus.FAIL


def test_repetition_interaction() -> None:
    body = (
        "Netflix заплатила пятьсот миллионов долларов за права на сериал. "
        "Netflix заплатила пятьсот миллионов долларов за права на шоу."
    )
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body=body, draft_kind=DraftKind.SHADOW_CANDIDATE,
        source_sufficiency=SourceSufficiency.SUFFICIENT,
    )
    crit = next(c for c in a.criteria if c.criterion == "repetition_absent")
    assert crit.status == CriterionStatus.FAIL


# ---------------------------------------------------------------------------
# RECOMMENDATION (55-62)
# ---------------------------------------------------------------------------


def test_recommendation_ready() -> None:
    plan = _beginner_plan(paragraph_target=2, safe_range=WordRange(min_words=30, target_words=39, max_words=60))
    a = build_editorial_completeness_assessment(
        draft_title=_GOOD_TITLE, draft_body=_GOOD_BODY,
        draft_kind=DraftKind.SHADOW_CANDIDATE, source_sufficiency=SourceSufficiency.SUFFICIENT,
        editorial_brief=_brief_ru(), beginner_friendly_plan=plan,
        calibrated_fact_safety=_calibrated(FactSafetyStatus.PASS),
    )
    assert a.editorial_recommendation == EditorialRecommendation.READY


def test_recommendation_review() -> None:
    brief = _brief_ru(event_details=["шесть спин-оффов сериала", "Something totally unmentioned elsewhere."])
    a = build_editorial_completeness_assessment(
        draft_title=_GOOD_TITLE, draft_body=_GOOD_BODY,
        draft_kind=DraftKind.SHADOW_CANDIDATE, source_sufficiency=SourceSufficiency.SUFFICIENT,
        editorial_brief=brief, beginner_friendly_plan=_beginner_plan(paragraph_target=2),
        calibrated_fact_safety=_calibrated(FactSafetyStatus.REVIEW),
    )
    assert a.editorial_recommendation == EditorialRecommendation.REVIEW


def test_recommendation_not_ready() -> None:
    a = build_editorial_completeness_assessment(
        draft_title=_GOOD_TITLE,
        draft_body="Совершенно не связанный текст, не упоминающий главный факт вовсе.",
        draft_kind=DraftKind.SHADOW_CANDIDATE, source_sufficiency=SourceSufficiency.SUFFICIENT,
        editorial_brief=_brief_ru(), calibrated_fact_safety=_calibrated(FactSafetyStatus.PASS),
    )
    assert a.editorial_recommendation == EditorialRecommendation.NOT_READY


def test_recommendation_insufficient_source() -> None:
    a = build_editorial_completeness_assessment(
        draft_title="Man seeks millions after swatting",
        draft_body="Man seeks millions after swatting. Подробности неизвестны, детали не подтверждены.",
        draft_kind=DraftKind.SHADOW_CANDIDATE, source_sufficiency=SourceSufficiency.HEADLINE_ONLY,
        calibrated_fact_safety=_calibrated(FactSafetyStatus.PASS),
    )
    assert a.editorial_recommendation == EditorialRecommendation.INSUFFICIENT_SOURCE


def test_serious_fact_safety_flag_prevents_ready() -> None:
    a = build_editorial_completeness_assessment(
        draft_title=_GOOD_TITLE, draft_body=_GOOD_BODY,
        draft_kind=DraftKind.SHADOW_CANDIDATE, source_sufficiency=SourceSufficiency.SUFFICIENT,
        editorial_brief=_brief_ru(), beginner_friendly_plan=_beginner_plan(paragraph_target=2),
        calibrated_fact_safety=_calibrated(FactSafetyStatus.FAIL),
    )
    assert a.editorial_recommendation == EditorialRecommendation.NOT_READY


def test_insufficient_source_does_not_become_false_not_ready() -> None:
    a = build_editorial_completeness_assessment(
        draft_title="Man seeks millions after swatting",
        draft_body="Man seeks millions after swatting. Имя, сумма и дата не раскрыты источником.",
        draft_kind=DraftKind.SHADOW_CANDIDATE, source_sufficiency=SourceSufficiency.EMPTY,
        calibrated_fact_safety=_calibrated(FactSafetyStatus.PASS),
    )
    assert a.editorial_recommendation != EditorialRecommendation.NOT_READY


def test_missing_main_fact_prevents_ready() -> None:
    a = build_editorial_completeness_assessment(
        draft_title="t", draft_body="Абсолютно другой, не связанный текст без фактов из брифа.",
        draft_kind=DraftKind.SHADOW_CANDIDATE, source_sufficiency=SourceSufficiency.SUFFICIENT,
        editorial_brief=_brief_ru(), calibrated_fact_safety=_calibrated(FactSafetyStatus.PASS),
    )
    assert a.editorial_recommendation != EditorialRecommendation.READY


def test_partial_criteria_produce_review() -> None:
    brief = _brief_ru(event_details=["шесть спин-оффов сериала", "A totally separate unmentioned detail."])
    a = build_editorial_completeness_assessment(
        draft_title=_GOOD_TITLE, draft_body=_GOOD_BODY,
        draft_kind=DraftKind.SHADOW_CANDIDATE, source_sufficiency=SourceSufficiency.SUFFICIENT,
        editorial_brief=brief, beginner_friendly_plan=_beginner_plan(paragraph_target=2),
        calibrated_fact_safety=_calibrated(FactSafetyStatus.PASS),
    )
    event_details_crit = next(c for c in a.criteria if c.criterion == "event_details_covered")
    assert event_details_crit.status == CriterionStatus.PARTIAL
    assert a.editorial_recommendation == EditorialRecommendation.REVIEW
