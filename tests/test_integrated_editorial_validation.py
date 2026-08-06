"""Phase 17 M6 - Integrated Editorial Validation tests (docs/
phase17_m6_integrated_editorial_validation_report.md).

Pure unit tests only (no DB, no LLM, no Telegram send) - schema validation, delivery-feasibility
checks (reusing the real, unmodified bot/formatting.py renderer), and overall_decision logic.
"""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from schemas.article_relevance import ChannelFitAssessment, FitDecision, RelevanceConfidence
from schemas.calibrated_fact_safety import CalibratedFactSafetyAssessment
from schemas.candidate_fact_safety import FactSafetyStatus
from schemas.editorial_brief import SourceSufficiency
from schemas.editorial_completeness import (
    CompletenessConfidence,
    DraftKind,
    EditorialRecommendation,
    HeadlineRewriteRisk,
    ParagraphStatus,
    SafeLengthStatus,
)
from schemas.editorial_completeness import EditorialCompletenessAssessment
from schemas.integrated_editorial_validation import (
    INTEGRATED_EDITORIAL_VALIDATION_SCHEMA_VERSION,
    CandidateKind,
    DeliveryModeRecommendation,
    OverallDecision,
)
from services.integrated_editorial_validation import build_integrated_editorial_validation, validate_delivery


def _completeness(recommendation: EditorialRecommendation, source_sufficiency=SourceSufficiency.SUFFICIENT) -> EditorialCompletenessAssessment:
    return EditorialCompletenessAssessment(
        draft_kind=DraftKind.SHADOW_CANDIDATE, source_sufficiency=source_sufficiency, criteria=[],
        required_criteria_count=0, passed_required_count=0, partial_required_count=0, failed_required_count=0,
        completeness_score=1.0, confidence=CompletenessConfidence.HIGH,
        headline_rewrite_risk=HeadlineRewriteRisk.LOW, safe_length_status=SafeLengthStatus.WITHIN_RANGE,
        paragraph_status=ParagraphStatus.ADEQUATE, editorial_recommendation=recommendation,
    )


def _fact_safety(status: FactSafetyStatus) -> CalibratedFactSafetyAssessment:
    return CalibratedFactSafetyAssessment(
        raw_audit_status=status, calibrated_status=status, human_review_required=status != FactSafetyStatus.PASS,
    )


def _channel_fit(decision: FitDecision) -> ChannelFitAssessment:
    return ChannelFitAssessment(
        channel_profile_id="default", fit_decision=decision, fit_score=0.5,
        confidence=RelevanceConfidence.HIGH, human_review_required=decision == FitDecision.REVIEW,
    )


def _delivery(**overrides):
    from schemas.integrated_editorial_validation import DeliveryValidation
    defaults = dict(
        plain_char_count=50, formatted_utf16_length=100, fits_text_message=True, fits_photo_caption=True,
        url_exposed_in_body=False, silently_truncated=False, recommended_delivery_mode=DeliveryModeRecommendation.TEXT_MESSAGE,
    )
    defaults.update(overrides)
    return DeliveryValidation(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_schema_version() -> None:
    validation = build_integrated_editorial_validation(
        event_id=uuid.uuid4(), candidate_kind=CandidateKind.M4_CANDIDATE, draft_title="T", draft_body="Body text",
        channel_fit=_channel_fit(FitDecision.ACCEPT), completeness=_completeness(EditorialRecommendation.READY),
        fact_safety=_fact_safety(FactSafetyStatus.PASS), delivery=_delivery(), has_image_candidate=True,
    )
    assert validation.schema_version == INTEGRATED_EDITORIAL_VALIDATION_SCHEMA_VERSION


def test_invalid_overall_decision_rejected() -> None:
    with pytest.raises(ValidationError):
        from schemas.integrated_editorial_validation import IntegratedEditorialValidation, ImageContext, ValidationConfidence
        IntegratedEditorialValidation(
            event_id=uuid.uuid4(), candidate_kind=CandidateKind.UNKNOWN, channel_fit_decision=None,
            source_sufficiency=SourceSufficiency.UNKNOWN, completeness=None, fact_safety=None, delivery=None,
            image_context=ImageContext(has_image_candidate=None, source="unknown"),
            overall_decision="NOT_A_REAL_DECISION", confidence=ValidationConfidence.LOW,  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Delivery validation (reuses real bot/formatting.py)
# ---------------------------------------------------------------------------


def test_short_draft_fits_both_text_and_caption() -> None:
    dv = validate_delivery(
        draft_id=uuid.uuid4(), draft_title="Title", draft_body="Short body.", hashtags=["#news"],
        news_title="Event", news_category="AI", news_url="https://example.com/a", has_image_candidate=True,
    )
    assert dv.fits_text_message is True
    assert dv.fits_photo_caption is True
    assert dv.recommended_delivery_mode == DeliveryModeRecommendation.PHOTO_CAPTION


def test_long_draft_still_fits_photo_caption_via_truncation() -> None:
    """`render_editorial_card()` truncates the body to fit (bot/formatting.py's own established
    algorithm) rather than failing outright - a long body still "fits" post-truncation; the real
    signal worth checking is that the untruncated content is far longer than the caption limit."""
    dv = validate_delivery(
        draft_id=uuid.uuid4(), draft_title="Title", draft_body="Word " * 400, hashtags=None,
        news_title="Event", news_category="AI", news_url=None, has_image_candidate=True,
    )
    assert dv.fits_text_message is True
    assert dv.fits_photo_caption is True  # truncation, not failure
    assert dv.formatted_utf16_length > 1024  # the untruncated text-message render exceeds the caption limit


def test_image_state_unknown_caption_fit_none() -> None:
    dv = validate_delivery(
        draft_id=uuid.uuid4(), draft_title="Title", draft_body="Body.", hashtags=None,
        news_title="Event", news_category="AI", news_url=None, has_image_candidate=None,
    )
    assert dv.fits_photo_caption is None
    assert dv.recommended_delivery_mode == DeliveryModeRecommendation.UNKNOWN
    assert "image_state_unknown_caption_fit_not_evaluated" in dv.reason_codes


def test_url_exposed_in_body_detected() -> None:
    dv = validate_delivery(
        draft_id=uuid.uuid4(), draft_title="Title", draft_body="See https://example.com/full-article for more.",
        hashtags=None, news_title="Event", news_category="AI", news_url="https://example.com/full-article",
        has_image_candidate=False,
    )
    assert dv.url_exposed_in_body is True


def test_url_not_exposed_when_absent_from_body() -> None:
    dv = validate_delivery(
        draft_id=uuid.uuid4(), draft_title="Title", draft_body="No link mentioned here at all.",
        hashtags=None, news_title="Event", news_category="AI", news_url="https://example.com/full-article",
        has_image_candidate=False,
    )
    assert dv.url_exposed_in_body is False


def test_html_tags_valid_no_crash_on_special_chars() -> None:
    dv = validate_delivery(
        draft_id=uuid.uuid4(), draft_title="Title <script>", draft_body="Body & <b>tags</b> here.",
        hashtags=["#a&b"], news_title="Event", news_category="AI", news_url=None, has_image_candidate=False,
    )
    assert dv.fits_text_message is True


def test_hashtags_parameter_no_longer_affects_formatted_length() -> None:
    """Phase 18.10 M4: bot/formatting.py no longer renders a hashtag block at all, so a legacy
    `hashtags` value (still accepted for backward compatibility with historical draft rows) has
    no effect on the rendered length anymore - a behavior change from this test's pre-M4 name/
    assertion, which this rewrite documents explicitly rather than silently deleting."""
    without_tags = validate_delivery(
        draft_id=uuid.uuid4(), draft_title="Title", draft_body="Body text.", hashtags=None,
        news_title="Event", news_category="AI", news_url=None, has_image_candidate=False,
    )
    with_tags = validate_delivery(
        draft_id=uuid.uuid4(), draft_title="Title", draft_body="Body text.", hashtags=["#one", "#two", "#three"],
        news_title="Event", news_category="AI", news_url=None, has_image_candidate=False,
    )
    assert with_tags.formatted_utf16_length == without_tags.formatted_utf16_length


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------


def test_empty_draft_is_technical_blocker() -> None:
    v = build_integrated_editorial_validation(
        event_id=uuid.uuid4(), candidate_kind=CandidateKind.M4_CANDIDATE, draft_title="", draft_body="",
        channel_fit=_channel_fit(FitDecision.ACCEPT), completeness=_completeness(EditorialRecommendation.READY),
        fact_safety=_fact_safety(FactSafetyStatus.PASS), delivery=_delivery(), has_image_candidate=None,
    )
    assert v.overall_decision == OverallDecision.TECHNICAL_BLOCKER
    assert "empty_or_missing_draft_text" in v.blocking_reasons


def test_missing_upstream_assessment_is_technical_blocker() -> None:
    v = build_integrated_editorial_validation(
        event_id=uuid.uuid4(), candidate_kind=CandidateKind.M4_CANDIDATE, draft_title="T", draft_body="Body",
        channel_fit=None, completeness=None, fact_safety=None, delivery=None, has_image_candidate=None,
    )
    assert v.overall_decision == OverallDecision.TECHNICAL_BLOCKER


def test_does_not_fit_text_message_is_technical_blocker() -> None:
    v = build_integrated_editorial_validation(
        event_id=uuid.uuid4(), candidate_kind=CandidateKind.M4_CANDIDATE, draft_title="T", draft_body="Body",
        channel_fit=_channel_fit(FitDecision.ACCEPT), completeness=_completeness(EditorialRecommendation.READY),
        fact_safety=_fact_safety(FactSafetyStatus.PASS), delivery=_delivery(fits_text_message=False),
        has_image_candidate=None,
    )
    assert v.overall_decision == OverallDecision.TECHNICAL_BLOCKER


def test_insufficient_source_propagated() -> None:
    v = build_integrated_editorial_validation(
        event_id=uuid.uuid4(), candidate_kind=CandidateKind.M4_CANDIDATE, draft_title="T", draft_body="Body",
        channel_fit=_channel_fit(FitDecision.ACCEPT),
        completeness=_completeness(EditorialRecommendation.INSUFFICIENT_SOURCE, SourceSufficiency.HEADLINE_ONLY),
        fact_safety=_fact_safety(FactSafetyStatus.PASS), delivery=_delivery(), has_image_candidate=None,
    )
    assert v.overall_decision == OverallDecision.INSUFFICIENT_SOURCE


def test_channel_reject_is_reject_recommended() -> None:
    """The Netflix/Walking Dead regression case: quality can be GOOD, but a REJECT-decision
    channel fit must still route to REJECT_RECOMMENDED, never READY_FOR_EDITOR."""
    v = build_integrated_editorial_validation(
        event_id=uuid.uuid4(), candidate_kind=CandidateKind.M4_CANDIDATE, draft_title="T", draft_body="Body",
        channel_fit=_channel_fit(FitDecision.REJECT), completeness=_completeness(EditorialRecommendation.READY),
        fact_safety=_fact_safety(FactSafetyStatus.PASS), delivery=_delivery(), has_image_candidate=None,
    )
    assert v.overall_decision == OverallDecision.REJECT_RECOMMENDED
    assert "channel_relevance_reject" in v.blocking_reasons


def test_serious_fact_safety_flag_forces_review_required() -> None:
    v = build_integrated_editorial_validation(
        event_id=uuid.uuid4(), candidate_kind=CandidateKind.M4_CANDIDATE, draft_title="T", draft_body="Body",
        channel_fit=_channel_fit(FitDecision.ACCEPT), completeness=_completeness(EditorialRecommendation.READY),
        fact_safety=_fact_safety(FactSafetyStatus.FAIL), delivery=_delivery(), has_image_candidate=None,
    )
    assert v.overall_decision == OverallDecision.REVIEW_REQUIRED
    assert "serious_unresolved_fact_safety_flag" in v.blocking_reasons


def test_completeness_not_ready_forces_review_required() -> None:
    v = build_integrated_editorial_validation(
        event_id=uuid.uuid4(), candidate_kind=CandidateKind.M4_CANDIDATE, draft_title="T", draft_body="Body",
        channel_fit=_channel_fit(FitDecision.ACCEPT), completeness=_completeness(EditorialRecommendation.NOT_READY),
        fact_safety=_fact_safety(FactSafetyStatus.PASS), delivery=_delivery(), has_image_candidate=None,
    )
    assert v.overall_decision == OverallDecision.REVIEW_REQUIRED
    assert "completeness_not_ready" in v.blocking_reasons


def test_url_exposed_forces_review_required() -> None:
    v = build_integrated_editorial_validation(
        event_id=uuid.uuid4(), candidate_kind=CandidateKind.M4_CANDIDATE, draft_title="T", draft_body="Body",
        channel_fit=_channel_fit(FitDecision.ACCEPT), completeness=_completeness(EditorialRecommendation.READY),
        fact_safety=_fact_safety(FactSafetyStatus.PASS), delivery=_delivery(url_exposed_in_body=True),
        has_image_candidate=None,
    )
    assert v.overall_decision == OverallDecision.REVIEW_REQUIRED
    assert "url_exposed_in_body" in v.blocking_reasons


def test_silent_truncation_forces_review_required() -> None:
    v = build_integrated_editorial_validation(
        event_id=uuid.uuid4(), candidate_kind=CandidateKind.M4_CANDIDATE, draft_title="T", draft_body="Body",
        channel_fit=_channel_fit(FitDecision.ACCEPT), completeness=_completeness(EditorialRecommendation.READY),
        fact_safety=_fact_safety(FactSafetyStatus.PASS), delivery=_delivery(silently_truncated=True),
        has_image_candidate=None,
    )
    assert v.overall_decision == OverallDecision.REVIEW_REQUIRED
    assert "silent_truncation_detected" in v.blocking_reasons


def test_all_clean_ready_for_editor() -> None:
    v = build_integrated_editorial_validation(
        event_id=uuid.uuid4(), candidate_kind=CandidateKind.M4_CANDIDATE, draft_title="T", draft_body="Body",
        channel_fit=_channel_fit(FitDecision.ACCEPT), completeness=_completeness(EditorialRecommendation.READY),
        fact_safety=_fact_safety(FactSafetyStatus.PASS), delivery=_delivery(), has_image_candidate=True,
    )
    assert v.overall_decision == OverallDecision.READY_FOR_EDITOR
    assert not v.blocking_reasons
    assert not v.review_reasons


def test_completeness_review_yields_review_required() -> None:
    v = build_integrated_editorial_validation(
        event_id=uuid.uuid4(), candidate_kind=CandidateKind.M4_CANDIDATE, draft_title="T", draft_body="Body",
        channel_fit=_channel_fit(FitDecision.ACCEPT), completeness=_completeness(EditorialRecommendation.REVIEW),
        fact_safety=_fact_safety(FactSafetyStatus.PASS), delivery=_delivery(), has_image_candidate=True,
    )
    assert v.overall_decision == OverallDecision.REVIEW_REQUIRED
    assert "completeness_review" in v.review_reasons


def test_channel_fit_unavailable_is_a_warning_not_a_blocker() -> None:
    v = build_integrated_editorial_validation(
        event_id=uuid.uuid4(), candidate_kind=CandidateKind.M4_CANDIDATE, draft_title="T", draft_body="Body",
        channel_fit=None, completeness=_completeness(EditorialRecommendation.READY),
        fact_safety=_fact_safety(FactSafetyStatus.PASS), delivery=_delivery(), has_image_candidate=True,
    )
    assert v.overall_decision != OverallDecision.TECHNICAL_BLOCKER
    assert "channel_relevance_unavailable" in v.warnings


def test_no_llm_or_telegram_import() -> None:
    import services.integrated_editorial_validation as module

    source_names = {getattr(obj, "__module__", "") for obj in vars(module).values()}
    forbidden = ("llm_gateway", "bot.handlers", "bot.main", "aiogram")
    for name in source_names:
        for f in forbidden:
            assert f not in name.lower(), f"unexpected import touching {f!r}: {name}"
