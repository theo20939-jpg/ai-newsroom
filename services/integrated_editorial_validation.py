"""Integrated Editorial Validation - Phase 17 M6 (docs/
phase17_m6_integrated_editorial_validation_report.md).

Combines Channel/Topic Relevance (M2), Editorial Completeness + calibrated Fact Safety (M5), and
deterministic Telegram delivery feasibility into one explainable `IntegratedEditorialValidation`.
Read-only, zero new LLM calls: delivery validation reuses `bot/formatting.py`'s own unmodified
`render_editorial_card()`/`EditorialInboxCard` - the exact same renderer the real Telegram send
path uses - never a re-implementation, never a live send. This module never enforces anything;
it only assesses and returns a schema instance.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from bot.formatting import SAFE_LIMIT, CardTooLongError, render_editorial_card
from bot.image_preview_formatting import CAPTION_SAFE_LIMIT
from schemas.article_relevance import ChannelFitAssessment, FitDecision
from schemas.calibrated_fact_safety import CalibratedFactSafetyAssessment
from schemas.candidate_fact_safety import FactSafetyStatus
from schemas.editorial_brief import SourceSufficiency
from schemas.editorial_completeness import EditorialCompletenessAssessment, EditorialRecommendation
from schemas.editorial_inbox import EditorialInboxCard
from schemas.integrated_editorial_validation import (
    CandidateKind,
    DeliveryModeRecommendation,
    DeliveryValidation,
    ImageContext,
    IntegratedEditorialValidation,
    OverallDecision,
    ValidationConfidence,
)


def validate_delivery(
    *,
    draft_id: UUID,
    draft_title: str | None,
    draft_body: str | None,
    hashtags: list[str] | None,
    news_title: str,
    news_category: str,
    news_url: str | None,
    has_image_candidate: bool | None,
) -> DeliveryValidation:
    """Pure (no network, no Bot). Renders the same `EditorialInboxCard` twice - once at the real
    text-message limit, once at the real photo-caption limit (`include_url=False`, matching
    `bot/handlers/image_preview.py`'s own established call convention exactly) - and reports
    whether each fits without invoking `CardTooLongError`'s terminal fallback."""
    card = EditorialInboxCard(
        draft_id=draft_id, draft_title=draft_title, draft_body=draft_body, hashtags=hashtags,
        draft_created_at=datetime.now(timezone.utc), news_title=news_title,
        news_category=news_category, news_url=news_url, news_published_at=None,
    )
    reason_codes: list[str] = []

    try:
        text_rendered = render_editorial_card(card, limit=SAFE_LIMIT, include_url=True)
        fits_text_message = True
    except CardTooLongError:
        text_rendered = ""
        fits_text_message = False
        reason_codes.append("exceeds_text_message_limit_even_after_truncation")

    fits_photo_caption: bool | None = None
    if has_image_candidate is not None:
        try:
            render_editorial_card(card, limit=CAPTION_SAFE_LIMIT, include_url=False)
            fits_photo_caption = True
        except CardTooLongError:
            fits_photo_caption = False
            reason_codes.append("exceeds_photo_caption_limit_even_after_truncation")
    else:
        reason_codes.append("image_state_unknown_caption_fit_not_evaluated")

    plain_char_count = len(draft_body or "")
    formatted_length = len(text_rendered.encode("utf-16-le")) // 2 if text_rendered else 0
    url_exposed = bool(news_url) and news_url in (draft_body or "") if news_url else False
    if url_exposed:
        reason_codes.append("raw_url_present_in_draft_body")

    untruncated_fits = plain_char_count == 0 or formatted_length <= SAFE_LIMIT
    silently_truncated = fits_text_message and not untruncated_fits

    if has_image_candidate:
        recommended = DeliveryModeRecommendation.PHOTO_CAPTION if fits_photo_caption else DeliveryModeRecommendation.TEXT_MESSAGE
    elif has_image_candidate is False:
        recommended = DeliveryModeRecommendation.TEXT_MESSAGE
    else:
        recommended = DeliveryModeRecommendation.UNKNOWN

    return DeliveryValidation(
        plain_char_count=plain_char_count, formatted_utf16_length=formatted_length,
        fits_text_message=fits_text_message, fits_photo_caption=fits_photo_caption,
        url_exposed_in_body=url_exposed, silently_truncated=silently_truncated,
        recommended_delivery_mode=recommended, reason_codes=reason_codes,
    )


def _confidence(
    completeness: EditorialCompletenessAssessment | None, fact_safety: CalibratedFactSafetyAssessment | None,
) -> ValidationConfidence:
    if completeness is None or fact_safety is None:
        return ValidationConfidence.LOW
    if completeness.confidence.value == "low":
        return ValidationConfidence.LOW
    if completeness.confidence.value == "medium":
        return ValidationConfidence.MEDIUM
    return ValidationConfidence.HIGH


def build_integrated_editorial_validation(
    *,
    event_id: UUID,
    candidate_kind: CandidateKind,
    draft_title: str | None,
    draft_body: str | None,
    channel_fit: ChannelFitAssessment | None,
    completeness: EditorialCompletenessAssessment | None,
    fact_safety: CalibratedFactSafetyAssessment | None,
    delivery: DeliveryValidation | None,
    has_image_candidate: bool | None,
) -> IntegratedEditorialValidation:
    """Pure. No I/O, no LLM call. Combines four already-computed, independent assessments into
    one explainable `overall_decision` - never re-derives any of the four itself (an integration
    function only, matching this milestone's own "one integrated system" objective without
    duplicating M2/M5's own logic)."""
    blocking: list[str] = []
    review: list[str] = []
    warnings: list[str] = []

    source_sufficiency = completeness.source_sufficiency if completeness is not None else SourceSufficiency.UNKNOWN
    image_context = ImageContext(
        has_image_candidate=has_image_candidate, source="known" if has_image_candidate is not None else "unknown",
    )

    is_empty_draft = not (draft_title or "").strip() or not (draft_body or "").strip()
    if is_empty_draft:
        blocking.append("empty_or_missing_draft_text")
        return IntegratedEditorialValidation(
            event_id=event_id, candidate_kind=candidate_kind, channel_fit_decision=channel_fit.fit_decision if channel_fit else None,
            source_sufficiency=source_sufficiency, completeness=completeness, fact_safety=fact_safety,
            delivery=delivery, image_context=image_context, overall_decision=OverallDecision.TECHNICAL_BLOCKER,
            blocking_reasons=blocking, review_reasons=review, warnings=warnings, confidence=ValidationConfidence.HIGH,
        )

    if completeness is None or fact_safety is None or delivery is None:
        blocking.append("missing_required_upstream_assessment")
        return IntegratedEditorialValidation(
            event_id=event_id, candidate_kind=candidate_kind, channel_fit_decision=channel_fit.fit_decision if channel_fit else None,
            source_sufficiency=source_sufficiency, completeness=completeness, fact_safety=fact_safety,
            delivery=delivery, image_context=image_context, overall_decision=OverallDecision.TECHNICAL_BLOCKER,
            blocking_reasons=blocking, review_reasons=review, warnings=warnings, confidence=ValidationConfidence.LOW,
        )

    if not delivery.fits_text_message:
        blocking.append("does_not_fit_text_message_even_truncated")
        return IntegratedEditorialValidation(
            event_id=event_id, candidate_kind=candidate_kind, channel_fit_decision=channel_fit.fit_decision if channel_fit else None,
            source_sufficiency=source_sufficiency, completeness=completeness, fact_safety=fact_safety,
            delivery=delivery, image_context=image_context, overall_decision=OverallDecision.TECHNICAL_BLOCKER,
            blocking_reasons=blocking, review_reasons=review, warnings=warnings, confidence=ValidationConfidence.HIGH,
        )

    if completeness.editorial_recommendation == EditorialRecommendation.INSUFFICIENT_SOURCE:
        return IntegratedEditorialValidation(
            event_id=event_id, candidate_kind=candidate_kind, channel_fit_decision=channel_fit.fit_decision if channel_fit else None,
            source_sufficiency=source_sufficiency, completeness=completeness, fact_safety=fact_safety,
            delivery=delivery, image_context=image_context, overall_decision=OverallDecision.INSUFFICIENT_SOURCE,
            blocking_reasons=blocking, review_reasons=["insufficient_source_honestly_handled"], warnings=warnings,
            confidence=_confidence(completeness, fact_safety),
        )

    if channel_fit is not None and channel_fit.fit_decision == FitDecision.REJECT:
        blocking.append("channel_relevance_reject")
        return IntegratedEditorialValidation(
            event_id=event_id, candidate_kind=candidate_kind, channel_fit_decision=channel_fit.fit_decision,
            source_sufficiency=source_sufficiency, completeness=completeness, fact_safety=fact_safety,
            delivery=delivery, image_context=image_context, overall_decision=OverallDecision.REJECT_RECOMMENDED,
            blocking_reasons=blocking, review_reasons=review, warnings=warnings, confidence=_confidence(completeness, fact_safety),
        )

    if fact_safety.calibrated_status == FactSafetyStatus.FAIL:
        blocking.append("serious_unresolved_fact_safety_flag")
    if completeness.editorial_recommendation == EditorialRecommendation.NOT_READY:
        blocking.append("completeness_not_ready")
    if delivery.url_exposed_in_body:
        blocking.append("url_exposed_in_body")
    if delivery.silently_truncated:
        blocking.append("silent_truncation_detected")

    if blocking:
        return IntegratedEditorialValidation(
            event_id=event_id, candidate_kind=candidate_kind, channel_fit_decision=channel_fit.fit_decision if channel_fit else None,
            source_sufficiency=source_sufficiency, completeness=completeness, fact_safety=fact_safety,
            delivery=delivery, image_context=image_context, overall_decision=OverallDecision.REVIEW_REQUIRED,
            blocking_reasons=blocking, review_reasons=review, warnings=warnings, confidence=_confidence(completeness, fact_safety),
        )

    if channel_fit is not None and channel_fit.fit_decision == FitDecision.REVIEW:
        review.append("channel_relevance_review")
    if fact_safety.calibrated_status == FactSafetyStatus.REVIEW:
        review.append("fact_safety_review")
    if completeness.editorial_recommendation == EditorialRecommendation.REVIEW:
        review.append("completeness_review")
    if delivery.recommended_delivery_mode == DeliveryModeRecommendation.UNKNOWN:
        warnings.append("delivery_mode_unknown_image_state")
    if channel_fit is None:
        warnings.append("channel_relevance_unavailable")

    overall = (
        OverallDecision.READY_FOR_EDITOR
        if not review and completeness.editorial_recommendation == EditorialRecommendation.READY
        else OverallDecision.REVIEW_REQUIRED
    )
    if overall == OverallDecision.REVIEW_REQUIRED and not review:
        review.append("conservative_default_pending_full_ready_criteria")

    return IntegratedEditorialValidation(
        event_id=event_id, candidate_kind=candidate_kind, channel_fit_decision=channel_fit.fit_decision if channel_fit else None,
        source_sufficiency=source_sufficiency, completeness=completeness, fact_safety=fact_safety,
        delivery=delivery, image_context=image_context, overall_decision=overall,
        blocking_reasons=blocking, review_reasons=review, warnings=warnings, confidence=_confidence(completeness, fact_safety),
    )
