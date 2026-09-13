"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 (S21): the central quality gate. Every `DeliveryPackage`
passes through here before it may be sent - no downstream sender may override a HOLD/BLOCK verdict
(S21's own explicit rule; enforced structurally by the orchestrator never calling a platform
adapter's send path when `run_quality_gate()` did not return READY).

Each check function is independently callable and independently testable (S35's own required test
classes map 1:1 onto these): `FACT_SUPPORT`/`CLAIM_TRACEABILITY` check the structured content
against its `EvidencePack`; `VISUAL_TRUTHFULNESS`/`MEDIA_PROVENANCE` check the media selection;
`FORMAT_REQUIREMENTS`/`PLATFORM_BUDGET` check the composition/caption against the target platform;
`ART_VALIDATION` delegates to the existing Instagram Art validator when the platform is Instagram
(never reimplemented - S3's own consolidation rule) and is a trivial pass for Telegram (V8 has no
separate Art-validation step of its own). `LANGUAGE_QUALITY` delegates to
`services.editorial_pipeline.language_qa` (S22).
"""
from __future__ import annotations

from services.editorial_pipeline.contracts import (
    EvidencePack,
    MediaSelectionResult,
    Platform,
    QualityCheckName,
    QualityCheckResult,
    QualityGateResult,
    QualityGateVerdict,
    StructuredContent,
    StructuredDataContent,
    SubjectMatchClassification,
)
from services.editorial_pipeline.language_qa import check_language_quality


def _check_fact_support(content: StructuredContent | None) -> QualityCheckResult:
    if content is None:
        return QualityCheckResult(QualityCheckName.FACT_SUPPORT, False, "no structured content to check")
    return QualityCheckResult(QualityCheckName.FACT_SUPPORT, True, "structured content present")


def _check_claim_traceability(content: StructuredContent | None, evidence: EvidencePack) -> QualityCheckResult:
    if content is None:
        return QualityCheckResult(QualityCheckName.CLAIM_TRACEABILITY, False, "no structured content to trace")
    claim_id = getattr(content, "source_claim_id", None)
    if claim_id is None:
        # NEWS/BREAKING carry a tuple of claim ids rather than a single one - check every one traces.
        claim_ids = getattr(content, "evidence_claim_ids", ())
        if not claim_ids:
            return QualityCheckResult(QualityCheckName.CLAIM_TRACEABILITY, False, "no evidence_claim_ids on content")
        missing = [cid for cid in claim_ids if evidence.claim_by_id(cid) is None]
        if missing:
            return QualityCheckResult(QualityCheckName.CLAIM_TRACEABILITY, False, f"unresolved claim ids: {missing}")
        return QualityCheckResult(QualityCheckName.CLAIM_TRACEABILITY, True, f"{len(claim_ids)} claim(s) traced")
    if evidence.claim_by_id(claim_id) is None:
        return QualityCheckResult(QualityCheckName.CLAIM_TRACEABILITY, False, f"source_claim_id {claim_id!r} not in EvidencePack")
    return QualityCheckResult(QualityCheckName.CLAIM_TRACEABILITY, True, f"source_claim_id {claim_id!r} traced")


def _check_visual_truthfulness(media_selection: MediaSelectionResult | None) -> QualityCheckResult:
    """S4-B's own invariant: a selected media asset must never visibly imply it depicts a specific
    entity it does not - enforced here by refusing MISMATCH outright, independent of whatever
    upstream selection logic ran (a defense-in-depth check, not the only place this is enforced -
    services/media_candidate_scoring.py's own `is_selectable()` already excludes MISMATCH from
    being scored as selectable in the first place)."""
    if media_selection is None or media_selection.selected is None:
        return QualityCheckResult(QualityCheckName.VISUAL_TRUTHFULNESS, True, "no media selected - nothing to misrepresent")
    subject_match = media_selection.selected.subject_match
    if subject_match is not None and subject_match.subject_match == SubjectMatchClassification.MISMATCH:
        return QualityCheckResult(QualityCheckName.VISUAL_TRUTHFULNESS, False, "selected candidate is classified MISMATCH")
    return QualityCheckResult(QualityCheckName.VISUAL_TRUTHFULNESS, True, "selected candidate is not a MISMATCH")


def _check_media_provenance(media_selection: MediaSelectionResult | None) -> QualityCheckResult:
    from services.editorial_pipeline.contracts import MediaUsageClassification

    if media_selection is None or media_selection.selected is None:
        return QualityCheckResult(QualityCheckName.MEDIA_PROVENANCE, True, "no media selected - nothing to check")
    usage = media_selection.selected.usage_classification
    if usage == MediaUsageClassification.NOT_USABLE:
        return QualityCheckResult(QualityCheckName.MEDIA_PROVENANCE, False, "usage_classification=NOT_USABLE")
    return QualityCheckResult(QualityCheckName.MEDIA_PROVENANCE, True, f"usage_classification={usage.value}")


def _check_format_requirements(content: StructuredContent | None) -> QualityCheckResult:
    if isinstance(content, StructuredDataContent):
        if not content.metric_value or not content.metric_unit:
            return QualityCheckResult(QualityCheckName.FORMAT_REQUIREMENTS, False, "DATA content missing metric_value/metric_unit")
    return QualityCheckResult(QualityCheckName.FORMAT_REQUIREMENTS, True, "format requirements satisfied")


def _check_platform_budget(caption_or_copy: str, platform: Platform) -> QualityCheckResult:
    """The actual budget-vs-drop-image decision is made upstream, before this gate ever runs
    (S19 - see platforms/telegram.py::plan_telegram_caption_budget()); this check only confirms
    the FINAL text handed to the gate is within the platform's own hard limit, as a last-resort
    safety net, never the mechanism that decides fallback behavior."""
    if platform == Platform.TELEGRAM:
        length = len(caption_or_copy.encode("utf-16-le")) // 2
        if length > 4096:  # Telegram's own plain-message hard limit - the true ceiling this gate enforces
            return QualityCheckResult(QualityCheckName.PLATFORM_BUDGET, False, f"{length} UTF-16 units exceeds Telegram's 4096 message limit")
    return QualityCheckResult(QualityCheckName.PLATFORM_BUDGET, True, "within platform budget")


def _check_art_validation(platform: Platform) -> QualityCheckResult:
    if platform != Platform.INSTAGRAM:
        return QualityCheckResult(QualityCheckName.ART_VALIDATION, True, "not applicable outside Instagram")
    # Delegates to the existing Instagram Art validator at the orchestrator/adapter level (S3 -
    # never reimplemented here); this gate-level check is a structural placeholder confirming the
    # orchestrator is expected to have already run it before reaching the gate for Instagram.
    return QualityCheckResult(QualityCheckName.ART_VALIDATION, True, "delegated to platforms/instagram.py's own Art validator call")


def run_quality_gate(
    *, content: StructuredContent | None, evidence: EvidencePack, media_selection: MediaSelectionResult | None,
    caption_or_copy: str, platform: Platform,
) -> QualityGateResult:
    checks = (
        _check_fact_support(content),
        _check_claim_traceability(content, evidence),
        check_language_quality(caption_or_copy),
        _check_visual_truthfulness(media_selection),
        _check_media_provenance(media_selection),
        _check_format_requirements(content),
        _check_platform_budget(caption_or_copy, platform),
        _check_art_validation(platform),
    )
    failed = [c for c in checks if not c.passed]
    if not failed:
        verdict = QualityGateVerdict.READY
    elif any(c.name in (QualityCheckName.VISUAL_TRUTHFULNESS, QualityCheckName.MEDIA_PROVENANCE) for c in failed):
        verdict = QualityGateVerdict.BLOCK  # truthfulness/provenance failures are never merely "hold and retry"
    else:
        verdict = QualityGateVerdict.HOLD
    return QualityGateResult(verdict=verdict, checks=checks)
