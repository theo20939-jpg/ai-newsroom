"""Editorial Completeness Gate - Phase 17 M5 (docs/
phase17_m5_editorial_completeness_gate_shadow_report.md).

A deterministic, versioned, zero-new-LLM-call shadow assessment of whether a *finished* draft
(the real production baseline, or a saved M3/M4/M4.1 candidate) covers what its own upstream
plans (`EditorialBrief` M1, `AdaptiveLengthPlan` M3, `BeginnerFriendlyPlan` M4) said was available
and required. Never generates text, never blocks a task, never mutates `ContentDraft` - see
`apply_editorial_completeness_shadow()`'s own docstring for the full production-safety
discipline, matching M1-M4's identical shape exactly.

Architecture decision (recorded before implementation, per this milestone's own instruction):
kept entirely separate from `CandidateFactSafetyAudit`/`CalibratedFactSafetyAssessment` (a
different dimension - "is this claim supported" vs. "is this story covered") and from
`ChannelFitAssessment` (topic fit, not completeness) and from any style/readability judgment.
`editorial_recommendation` is the only cross-cutting field, and it is always derived transparently
from the `criteria` list plus a separately-computed `CalibratedFactSafetyAssessment` passed in by
the caller - never from hidden state, never re-deriving Fact Safety itself (M5's own explicit
"не смешивай" requirement, docs/phase17_m5_editorial_completeness_gate_shadow_report.md §6).

Anti-leakage discipline (M5's own explicit requirement): every criterion is graded against
evidence that could plausibly be verified independently of the very plan the draft may have been
generated from - `EditorialBrief`/`research_facts`/`news_event` text, never the *target* word
count or *recommended format* used as if it were proof the draft is good. A draft is never scored
COMPLETE merely because it falls inside the range the plan itself proposed; range compliance is
its own separate, narrow criterion (`safe_length_compliance`), never conflated with substantive
completeness.
"""
from __future__ import annotations

import re
from typing import Any

from core.config import settings
from schemas.adaptive_length import AdaptiveLengthPlan
from schemas.beginner_friendly import BeginnerFriendlyPlan
from schemas.calibrated_fact_safety import CalibratedFactSafetyAssessment
from schemas.candidate_fact_safety import FactSafetyStatus
from schemas.editorial_brief import EditorialBrief, SourceSufficiency
from schemas.editorial_completeness import (
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
from services.candidate_fact_safety import detect_filler_phrases, detect_repetition
from services.fact_safety import extract_claims
from services.text_normalization import (
    count_paragraphs,
    fuzzy_phrase_contains,
    token_overlap_ratio,
)

EDITORIAL_COMPLETENESS_POLICY_VERSION = "v1"

_THIN_SOURCE = frozenset({SourceSufficiency.HEADLINE_ONLY, SourceSufficiency.EMPTY})
_UNCERTAINTY_REQUIRED_SUFFICIENCY = frozenset({
    SourceSufficiency.PARTIAL, SourceSufficiency.HEADLINE_ONLY, SourceSufficiency.CONFLICTING,
})

# A fixed, explicit list of Russian/English uncertainty/gap-disclosure markers - the same
# disclosed, narrow-phrase-list discipline `services/candidate_fact_safety.py`'s own
# `detect_filler_phrases()` already established (never a general hedging classifier).
_UNCERTAINTY_MARKER_RE = re.compile(
    r"\b(неизвестно|не указан\w*|не уточня\w*|не подтвержд\w*|не раскры\w*|не сообщ\w*|"
    r"остаются? неподтвержд\w*|требуется? проверк\w*|предположительно|пока нельзя|нельзя утвержда\w*|"
    r"unclear|unknown|not confirmed|not disclosed|has not been confirmed|remains unclear|"
    r"unverified|yet to be confirmed)\b",
    re.IGNORECASE,
)
_WHY_IT_MATTERS_MARKER_RE = re.compile(
    r"\b(это важно|подчёркивает|указывает на|отражает|significant|matters because|underscores|highlights)\b",
    re.IGNORECASE,
)
_WHAT_NEXT_MARKER_RE = re.compile(
    r"\b(в дальнейшем|ожида\w*|планиру\w*|следующим шагом|will next|is expected to|plans to|next step)\b",
    re.IGNORECASE,
)
_EXPLANATION_WINDOW_RE_TEMPLATE = r"(.{{0,60}}\b{term}\b.{{0,60}})"


def _text_claims(text: str) -> list[str]:
    """Flattens `extract_claims()`'s per-type dict into one list of raw claim substrings - used
    only for coverage counting, never for support/severity classification (that stays exactly
    `services/fact_safety.py`'s own job)."""
    claims = extract_claims(text)
    return [c for values in claims.values() for c in values]


def _coverage_ratio(items: list[str], body: str) -> tuple[float, list[str], list[str]]:
    matched: list[str] = []
    missing: list[str] = []
    for item in items:
        item_claims = _text_claims(item)
        covered = (
            any(fuzzy_phrase_contains(c, body) for c in item_claims)
            or token_overlap_ratio(item, body) >= 0.4
        )
        (matched if covered else missing).append(item)
    ratio = len(matched) / len(items) if items else 0.0
    return ratio, matched, missing


def _status_from_ratio(ratio: float, *, has_items: bool) -> CriterionStatus:
    if not has_items:
        return CriterionStatus.NOT_APPLICABLE
    if ratio >= 0.7:
        return CriterionStatus.PASS
    if ratio > 0.0:
        return CriterionStatus.PARTIAL
    return CriterionStatus.FAIL


def _list_criterion(
    name: str, items: list[str], body: str, *, required: bool,
) -> CompletenessCriterionResult:
    evidence_available = bool(items)
    if not evidence_available:
        return CompletenessCriterionResult(
            criterion=name, status=CriterionStatus.NOT_APPLICABLE, score=1.0, required=False,
            evidence_available=False, confidence=CompletenessConfidence.HIGH,
            reason_codes=[f"{name}_no_evidence_available"],
        )
    ratio, matched, missing = _coverage_ratio(items, body)
    status = _status_from_ratio(ratio, has_items=True)
    return CompletenessCriterionResult(
        criterion=name, status=status, score=ratio, required=required, evidence_available=True,
        matched_evidence=matched, missing_items=missing,
        confidence=CompletenessConfidence.HIGH if len(items) >= 2 else CompletenessConfidence.MEDIUM,
        reason_codes=[f"{name}_{status.value}"],
    )


def _headline_fact_criterion(brief: EditorialBrief | None, body: str) -> CompletenessCriterionResult:
    headline_fact = brief.headline_fact if brief is not None else None
    if not headline_fact:
        return CompletenessCriterionResult(
            criterion="headline_fact_covered", status=CriterionStatus.NOT_APPLICABLE, score=1.0,
            required=False, evidence_available=False, confidence=CompletenessConfidence.HIGH,
            reason_codes=["headline_fact_no_evidence_available"],
        )
    ratio, matched, missing = _coverage_ratio([headline_fact], body)
    status = _status_from_ratio(ratio, has_items=True)
    return CompletenessCriterionResult(
        criterion="headline_fact_covered", status=status, score=ratio, required=True,
        evidence_available=True, matched_evidence=matched, missing_items=missing,
        confidence=CompletenessConfidence.HIGH, reason_codes=[f"headline_fact_{status.value}"],
    )


def _subject_explanation_criterion(
    plan: BeginnerFriendlyPlan | None, title: str, body: str,
) -> CompletenessCriterionResult:
    terms = list((plan.subjects_to_explain if plan else []) or []) + list(
        (plan.terms_to_explain if plan else []) or []
    )
    required = bool(plan and plan.explanation_required and terms)
    if not required:
        return CompletenessCriterionResult(
            criterion="subject_explanation_covered", status=CriterionStatus.NOT_APPLICABLE,
            score=1.0, required=False, evidence_available=bool(terms),
            confidence=CompletenessConfidence.HIGH,
            reason_codes=["subject_explanation_not_required"],
        )
    text = f"{title} {body}"
    matched: list[str] = []
    missing: list[str] = []
    for term in terms:
        pattern = re.compile(_EXPLANATION_WINDOW_RE_TEMPLATE.format(term=re.escape(term)), re.IGNORECASE)
        match = pattern.search(text)
        explained = bool(match and len(match.group(1).split()) >= 4 and term.lower() in match.group(1).lower())
        present = fuzzy_phrase_contains(term, text)
        (matched if (present and explained) else missing).append(term)
    ratio = len(matched) / len(terms) if terms else 0.0
    status = _status_from_ratio(ratio, has_items=True)
    return CompletenessCriterionResult(
        criterion="subject_explanation_covered", status=status, score=ratio, required=True,
        evidence_available=True, matched_evidence=matched, missing_items=missing,
        confidence=CompletenessConfidence.MEDIUM, reason_codes=[f"subject_explanation_{status.value}"],
    )


def _uncertainty_criterion(
    brief: EditorialBrief | None, source_sufficiency: SourceSufficiency, body: str,
) -> CompletenessCriterionResult:
    uncertainties = list(brief.uncertainties) if brief else []
    required = bool(uncertainties) or source_sufficiency in _UNCERTAINTY_REQUIRED_SUFFICIENCY
    has_marker = bool(_UNCERTAINTY_MARKER_RE.search(body))
    if uncertainties:
        ratio, matched, missing = _coverage_ratio(uncertainties, body)
        if has_marker and ratio < 1.0:
            ratio = max(ratio, 0.5)
        status = _status_from_ratio(ratio, has_items=True)
    elif required:
        status = CriterionStatus.PASS if has_marker else CriterionStatus.FAIL
        ratio = 1.0 if has_marker else 0.0
        matched, missing = ([body] if has_marker else []), ([] if has_marker else ["uncertainty_marker"])
    else:
        return CompletenessCriterionResult(
            criterion="uncertainty_covered", status=CriterionStatus.NOT_APPLICABLE, score=1.0,
            required=False, evidence_available=False, confidence=CompletenessConfidence.HIGH,
            reason_codes=["uncertainty_no_evidence_available"],
        )
    return CompletenessCriterionResult(
        criterion="uncertainty_covered", status=status, score=ratio, required=required,
        evidence_available=True, matched_evidence=matched, missing_items=missing,
        confidence=CompletenessConfidence.MEDIUM, reason_codes=[f"uncertainty_{status.value}"],
    )


def _why_it_matters_criterion(
    brief: EditorialBrief | None, plan: BeginnerFriendlyPlan | None, body: str,
) -> CompletenessCriterionResult:
    why_items = list(brief.why_it_matters) if brief else []
    required = bool(why_items) and (plan is None or plan.why_it_matters_required)
    if not why_items:
        return CompletenessCriterionResult(
            criterion="why_it_matters_covered", status=CriterionStatus.NOT_APPLICABLE, score=1.0,
            required=False, evidence_available=False, confidence=CompletenessConfidence.HIGH,
            reason_codes=["why_it_matters_no_evidence_available"],
        )
    ratio, matched, missing = _coverage_ratio(why_items, body)
    if _WHY_IT_MATTERS_MARKER_RE.search(body) and ratio < 1.0:
        ratio = max(ratio, 0.5)
        matched = matched or ["why_it_matters_marker"]
    status = _status_from_ratio(ratio, has_items=True)
    return CompletenessCriterionResult(
        criterion="why_it_matters_covered", status=status, score=ratio, required=required,
        evidence_available=True, matched_evidence=matched, missing_items=missing,
        confidence=CompletenessConfidence.MEDIUM, reason_codes=[f"why_it_matters_{status.value}"],
    )


def _what_next_criterion(
    brief: EditorialBrief | None, plan: BeginnerFriendlyPlan | None, body: str,
) -> CompletenessCriterionResult:
    what_next = list(brief.what_next) if brief else []
    allowed = plan is None or plan.what_next_allowed
    required = bool(what_next) and allowed
    if not what_next or not allowed:
        return CompletenessCriterionResult(
            criterion="what_next_covered", status=CriterionStatus.NOT_APPLICABLE, score=1.0,
            required=False, evidence_available=bool(what_next),
            confidence=CompletenessConfidence.HIGH,
            reason_codes=["what_next_not_applicable"],
        )
    ratio, matched, missing = _coverage_ratio(what_next, body)
    if _WHAT_NEXT_MARKER_RE.search(body) and ratio < 1.0:
        ratio = max(ratio, 0.5)
    status = _status_from_ratio(ratio, has_items=True)
    return CompletenessCriterionResult(
        criterion="what_next_covered", status=status, score=ratio, required=required,
        evidence_available=True, matched_evidence=matched, missing_items=missing,
        confidence=CompletenessConfidence.MEDIUM, reason_codes=[f"what_next_{status.value}"],
    )


def assess_headline_rewrite_risk(
    title: str, body: str, source_sufficiency: SourceSufficiency, brief: EditorialBrief | None,
) -> HeadlineRewriteRisk:
    """Fixes M0's own disclosed, measured gap (docs/phase17_m0_output_quality_discovery_report.md
    §6): the old vocabulary-overlap-only proxy measured 0.0% (0/269) against a real manual-audit
    rate of 18.75-21.9% - "a genuine rewrite can swap most of its words while adding zero new
    information; word-overlap alone cannot distinguish the same fact in different words from the
    same fact plus something new." This function instead counts genuinely NEW claims the body
    adds beyond the title (reusing `services.fact_safety.extract_claims`'s own deterministic
    numeric/date/entity extraction - never a new parser) and editorial-framing signals
    (uncertainty/why-it-matters/what-next markers) - a body with neither is flagged HIGH; a body
    with framing but no new checkable fact is MEDIUM; any new fact is LOW.

    Per this milestone's own explicit instruction, a `HEADLINE_ONLY`/`EMPTY` source is never
    penalized for lacking new facts it structurally cannot have - real M4.1 evidence
    (`docs/phase17_m4_1_reasoning_budget_fix_report.md` §11, cases `d9c0b32c`/`073437a9`) showed
    the deciding factor for those sources is not source thinness but whether the body still adds
    honest uncertainty/gap-disclosure framing; `NOT_APPLICABLE` is returned here and the framing
    check is instead folded into `uncertainty_covered`/the overall `editorial_recommendation`
    (INSUFFICIENT_SOURCE), never into a rewrite-risk verdict."""
    if source_sufficiency in _THIN_SOURCE:
        return HeadlineRewriteRisk.NOT_APPLICABLE
    if not body.strip():
        return HeadlineRewriteRisk.NOT_APPLICABLE

    title_claims = _text_claims(title)
    body_claims = _text_claims(body)
    new_claims = [c for c in body_claims if not any(fuzzy_phrase_contains(c, title) for c in [c])]
    # A body claim only counts as "new" if it is not already trivially present in the title text.
    new_claims = [c for c in body_claims if not fuzzy_phrase_contains(c, title)]
    # Title's own claims never count as "new" even if repeated verbatim in the body.
    new_claims = [c for c in new_claims if not any(fuzzy_phrase_contains(tc, c) for tc in title_claims)]

    has_framing = bool(
        _UNCERTAINTY_MARKER_RE.search(body)
        or _WHY_IT_MATTERS_MARKER_RE.search(body)
        or _WHAT_NEXT_MARKER_RE.search(body)
    )
    if brief is not None and (brief.why_it_matters or brief.uncertainties or brief.what_next):
        evidence_items = [*brief.why_it_matters, *brief.uncertainties, *brief.what_next]
        if any(fuzzy_phrase_contains(item, body) for item in evidence_items if item):
            has_framing = True

    overlap = token_overlap_ratio(title, body)

    if new_claims:
        return HeadlineRewriteRisk.LOW
    if has_framing:
        return HeadlineRewriteRisk.MEDIUM
    if overlap >= 0.5:
        return HeadlineRewriteRisk.HIGH
    return HeadlineRewriteRisk.MEDIUM


def _safe_length_status(
    word_count: int, plan: BeginnerFriendlyPlan | None, adaptive_plan: AdaptiveLengthPlan | None,
) -> SafeLengthStatus:
    if plan is not None:
        rng = plan.safe_range
        min_w, max_w = rng.min_words, rng.max_words
    elif adaptive_plan is not None:
        min_w, max_w = adaptive_plan.min_words, adaptive_plan.max_words
    else:
        return SafeLengthStatus.NOT_APPLICABLE
    if word_count < min_w:
        return SafeLengthStatus.BELOW_RANGE
    if word_count > max_w:
        return SafeLengthStatus.ABOVE_RANGE
    return SafeLengthStatus.WITHIN_RANGE


def _safe_length_criterion(
    status: SafeLengthStatus, source_sufficiency: SourceSufficiency,
) -> CompletenessCriterionResult:
    if status == SafeLengthStatus.NOT_APPLICABLE:
        return CompletenessCriterionResult(
            criterion="safe_length_compliance", status=CriterionStatus.NOT_APPLICABLE, score=1.0,
            required=False, evidence_available=False, confidence=CompletenessConfidence.HIGH,
            reason_codes=["safe_length_no_plan_available"],
        )
    if status == SafeLengthStatus.WITHIN_RANGE:
        crit_status, score = CriterionStatus.PASS, 1.0
    elif source_sufficiency in _THIN_SOURCE:
        # An explainable deviation - a thin source's own safe_range floor may simply be
        # unreachable; never penalized to FAIL for this alone (M5's own explicit instruction).
        crit_status, score = CriterionStatus.PARTIAL, 0.5
    else:
        crit_status, score = CriterionStatus.PARTIAL, 0.4
    return CompletenessCriterionResult(
        criterion="safe_length_compliance", status=crit_status, score=score, required=True,
        evidence_available=True, confidence=CompletenessConfidence.HIGH,
        reason_codes=[f"safe_length_{status.value}"],
    )


def _paragraph_criterion(
    body: str, plan: BeginnerFriendlyPlan | None, adaptive_plan: AdaptiveLengthPlan | None,
) -> tuple[ParagraphStatus, CompletenessCriterionResult]:
    target = (plan.paragraph_target if plan else None) or (
        adaptive_plan.paragraph_target if adaptive_plan else None
    )
    actual = count_paragraphs(body)
    if target is None:
        return ParagraphStatus.NOT_APPLICABLE, CompletenessCriterionResult(
            criterion="structure_adequate", status=CriterionStatus.NOT_APPLICABLE, score=1.0,
            required=False, evidence_available=False, confidence=CompletenessConfidence.HIGH,
            reason_codes=["structure_no_plan_available"],
        )
    if actual >= target:
        para_status, crit_status, score = ParagraphStatus.ADEQUATE, CriterionStatus.PASS, 1.0
    elif actual == target - 1:
        para_status, crit_status, score = ParagraphStatus.ADEQUATE, CriterionStatus.PARTIAL, 0.6
    else:
        para_status, crit_status, score = ParagraphStatus.WEAK, CriterionStatus.FAIL, 0.0
    return para_status, CompletenessCriterionResult(
        criterion="structure_adequate", status=crit_status, score=score, required=True,
        evidence_available=True, confidence=CompletenessConfidence.HIGH,
        reason_codes=[f"structure_actual_{actual}_target_{target}"],
    )


def _headline_rewrite_criterion(risk: HeadlineRewriteRisk) -> CompletenessCriterionResult:
    if risk == HeadlineRewriteRisk.NOT_APPLICABLE:
        return CompletenessCriterionResult(
            criterion="headline_rewrite_avoided", status=CriterionStatus.NOT_APPLICABLE, score=1.0,
            required=False, evidence_available=False, confidence=CompletenessConfidence.HIGH,
            reason_codes=["headline_rewrite_not_applicable_thin_source"],
        )
    mapping = {
        HeadlineRewriteRisk.LOW: (CriterionStatus.PASS, 1.0),
        HeadlineRewriteRisk.MEDIUM: (CriterionStatus.PARTIAL, 0.5),
        HeadlineRewriteRisk.HIGH: (CriterionStatus.FAIL, 0.0),
    }
    status, score = mapping[risk]
    return CompletenessCriterionResult(
        criterion="headline_rewrite_avoided", status=status, score=score, required=True,
        evidence_available=True, confidence=CompletenessConfidence.MEDIUM,
        reason_codes=[f"headline_rewrite_risk_{risk.value}"],
    )


def _fact_safety_criterion(calibrated: CalibratedFactSafetyAssessment | None) -> CompletenessCriterionResult:
    if calibrated is None:
        return CompletenessCriterionResult(
            criterion="unsupported_claims_absent", status=CriterionStatus.UNKNOWN, score=0.5,
            required=True, evidence_available=False, confidence=CompletenessConfidence.LOW,
            reason_codes=["fact_safety_not_available"],
        )
    mapping = {
        FactSafetyStatus.PASS: (CriterionStatus.PASS, 1.0),
        FactSafetyStatus.REVIEW: (CriterionStatus.PARTIAL, 0.5),
        FactSafetyStatus.FAIL: (CriterionStatus.FAIL, 0.0),
    }
    status, score = mapping[calibrated.calibrated_status]
    return CompletenessCriterionResult(
        criterion="unsupported_claims_absent", status=status, score=score, required=True,
        evidence_available=True, confidence=CompletenessConfidence.HIGH,
        reason_codes=[f"calibrated_fact_safety_{calibrated.calibrated_status.value}"],
    )


def _filler_criterion(body: str) -> CompletenessCriterionResult:
    flags = detect_filler_phrases(body)
    status = CriterionStatus.PASS if not flags else CriterionStatus.FAIL
    return CompletenessCriterionResult(
        criterion="filler_absent", status=status, score=1.0 if not flags else 0.0, required=True,
        evidence_available=True, matched_evidence=[], missing_items=flags,
        confidence=CompletenessConfidence.HIGH, reason_codes=[f"filler_{status.value}"],
    )


def _repetition_criterion(body: str) -> CompletenessCriterionResult:
    flags = detect_repetition(body)
    status = CriterionStatus.PASS if not flags else CriterionStatus.FAIL
    return CompletenessCriterionResult(
        criterion="repetition_absent", status=status, score=1.0 if not flags else 0.0, required=True,
        evidence_available=True, matched_evidence=[], missing_items=flags,
        confidence=CompletenessConfidence.HIGH, reason_codes=[f"repetition_{status.value}"],
    )


def _recommendation(
    criteria: list[CompletenessCriterionResult],
    source_sufficiency: SourceSufficiency,
    headline_rewrite_risk: HeadlineRewriteRisk,
    calibrated: CalibratedFactSafetyAssessment | None,
) -> tuple[EditorialRecommendation, list[str]]:
    by_name = {c.criterion: c for c in criteria}
    reasons: list[str] = []
    fact_safety_fail = calibrated is not None and calibrated.calibrated_status == FactSafetyStatus.FAIL
    fact_safety_review = calibrated is not None and calibrated.calibrated_status == FactSafetyStatus.REVIEW

    headline_fact = by_name.get("headline_fact_covered")
    event_details = by_name.get("event_details_covered")
    filler = by_name.get("filler_absent")
    repetition = by_name.get("repetition_absent")

    if source_sufficiency in _THIN_SOURCE and not fact_safety_fail and headline_rewrite_risk != HeadlineRewriteRisk.HIGH:
        reasons.append("insufficient_source_honestly_handled")
        return EditorialRecommendation.INSUFFICIENT_SOURCE, reasons

    if fact_safety_fail:
        reasons.append("serious_unresolved_fact_safety_flag")
        return EditorialRecommendation.NOT_READY, reasons

    if headline_fact is not None and headline_fact.required and headline_fact.status == CriterionStatus.FAIL:
        reasons.append("main_fact_not_covered")
        return EditorialRecommendation.NOT_READY, reasons

    if event_details is not None and event_details.required and event_details.status == CriterionStatus.FAIL:
        reasons.append("available_event_details_missing")
        return EditorialRecommendation.NOT_READY, reasons

    if headline_rewrite_risk == HeadlineRewriteRisk.HIGH:
        reasons.append("headline_rewrite_with_richer_evidence_available")
        return EditorialRecommendation.NOT_READY, reasons

    if (filler is not None and filler.status == CriterionStatus.FAIL) or (
        repetition is not None and repetition.status == CriterionStatus.FAIL
    ):
        reasons.append("filler_or_repetition_present")
        return EditorialRecommendation.NOT_READY, reasons

    failed_required = [c for c in criteria if c.required and c.status == CriterionStatus.FAIL]
    partial_required = [c for c in criteria if c.required and c.status == CriterionStatus.PARTIAL]

    if failed_required:
        reasons.append("other_required_criteria_failed")
        return EditorialRecommendation.REVIEW, reasons

    if partial_required or fact_safety_review or source_sufficiency == SourceSufficiency.PARTIAL:
        reasons.append("partial_coverage_or_minor_fact_safety_review")
        return EditorialRecommendation.REVIEW, reasons

    reasons.append("all_required_criteria_covered")
    return EditorialRecommendation.READY, reasons


def build_editorial_completeness_assessment(
    *,
    draft_title: str,
    draft_body: str,
    draft_kind: DraftKind,
    source_sufficiency: SourceSufficiency,
    editorial_brief: EditorialBrief | None = None,
    adaptive_length_plan: AdaptiveLengthPlan | None = None,
    beginner_friendly_plan: BeginnerFriendlyPlan | None = None,
    calibrated_fact_safety: CalibratedFactSafetyAssessment | None = None,
) -> EditorialCompletenessAssessment:
    """Pure. No I/O, no LLM call, deterministic: identical inputs always produce an identical
    output. Every criterion is graded only against `editorial_brief`/evidence already independent
    of any word-count target - never against the plan's own recommended range as if it were proof
    of quality (anti-leakage discipline, module docstring)."""
    body = draft_body or ""
    title = draft_title or ""

    criteria = [
        _headline_fact_criterion(editorial_brief, body),
        _list_criterion(
            "event_details_covered", list(editorial_brief.event_details) if editorial_brief else [], body,
            required=bool(editorial_brief and editorial_brief.event_details),
        ),
        _subject_explanation_criterion(beginner_friendly_plan, title, body),
        _list_criterion(
            "background_context_covered",
            list(editorial_brief.background_context) if editorial_brief else [], body,
            required=bool(editorial_brief and editorial_brief.background_context),
        ),
        _list_criterion(
            "difference_or_change_covered",
            [editorial_brief.difference_or_change] if editorial_brief and editorial_brief.difference_or_change else [],
            body, required=bool(editorial_brief and editorial_brief.difference_or_change),
        ),
        _why_it_matters_criterion(editorial_brief, beginner_friendly_plan, body),
        _what_next_criterion(editorial_brief, beginner_friendly_plan, body),
        _uncertainty_criterion(editorial_brief, source_sufficiency, body),
    ]

    word_count = len((body or "").split())
    length_status = _safe_length_status(word_count, beginner_friendly_plan, adaptive_length_plan)
    criteria.append(_safe_length_criterion(length_status, source_sufficiency))

    paragraph_status, structure_criterion = _paragraph_criterion(body, beginner_friendly_plan, adaptive_length_plan)
    criteria.append(structure_criterion)

    rewrite_risk = assess_headline_rewrite_risk(title, body, source_sufficiency, editorial_brief)
    criteria.append(_headline_rewrite_criterion(rewrite_risk))

    criteria.append(_fact_safety_criterion(calibrated_fact_safety))
    criteria.append(_filler_criterion(body))
    criteria.append(_repetition_criterion(body))

    required_criteria = [c for c in criteria if c.required]
    passed_required = sum(1 for c in required_criteria if c.status == CriterionStatus.PASS)
    partial_required = sum(1 for c in required_criteria if c.status == CriterionStatus.PARTIAL)
    failed_required = sum(1 for c in required_criteria if c.status == CriterionStatus.FAIL)

    if required_criteria:
        completeness_score = (passed_required + 0.5 * partial_required) / len(required_criteria)
    else:
        scoreable = [c for c in criteria if c.status not in (CriterionStatus.NOT_APPLICABLE, CriterionStatus.UNKNOWN)]
        completeness_score = (sum(c.score for c in scoreable) / len(scoreable)) if scoreable else 1.0

    low_confidence_count = sum(1 for c in criteria if c.confidence == CompletenessConfidence.LOW)
    if not body.strip():
        confidence = CompletenessConfidence.HIGH  # an empty draft is unambiguous
    elif low_confidence_count >= 2 or source_sufficiency == SourceSufficiency.UNKNOWN:
        confidence = CompletenessConfidence.LOW
    elif source_sufficiency in (SourceSufficiency.PARTIAL, SourceSufficiency.CONFLICTING):
        confidence = CompletenessConfidence.MEDIUM
    else:
        confidence = CompletenessConfidence.HIGH

    recommendation, recommendation_reasons = _recommendation(
        criteria, source_sufficiency, rewrite_risk, calibrated_fact_safety,
    )

    return EditorialCompletenessAssessment(
        draft_kind=draft_kind,
        source_sufficiency=source_sufficiency,
        criteria=criteria,
        required_criteria_count=len(required_criteria),
        passed_required_count=passed_required,
        partial_required_count=partial_required,
        failed_required_count=failed_required,
        completeness_score=round(completeness_score, 4),
        confidence=confidence,
        headline_rewrite_risk=rewrite_risk,
        safe_length_status=length_status,
        paragraph_status=paragraph_status,
        editorial_recommendation=recommendation,
        reason_codes=recommendation_reasons,
    )


def apply_editorial_completeness_shadow(
    intelligence_output: dict[str, Any],
    copywriting_output: dict[str, Any],
    calibrated_fact_safety: CalibratedFactSafetyAssessment | None,
    structured_output: dict[str, Any],
) -> dict[str, Any]:
    """Called only from `capabilities/executor.py`, only for the "quality" step (after
    `apply_fact_safety()`'s own baseline check, same step), only when `editorial_completeness_mode
    == "shadow"`. Returns `structured_output` completely unchanged when `"off"` (the default,
    byte-identical-to-pre-M5 rollback path) - mirrors `apply_adaptive_length_shadow()`'s/
    `apply_beginner_friendly_shadow()`'s own established convention exactly, including being
    safe to call directly (e.g. from a backtest script or a test) without depending on the
    executor's own gate.

    `structured_output` here is `QualityCapability`'s own output (`{"passed", "issues"}`, already
    possibly merged with `"fact_safety"` by `apply_fact_safety()`) - the base dict this merges
    into, exactly like that function's own established convention. `intelligence_output` and
    `copywriting_output` are `step_results["intelligence"]`/`step_results["copywriting"]` - already
    on `CapabilityContext` at zero extra cost, the same source `apply_fact_safety()` already reads
    `copywriting_output` from. Reads the already-attached `editorial_brief` (M1, at "intelligence")
    and `adaptive_length_plan`/`beginner_friendly_plan` (M3/M4, at "copywriting") - never
    recomputes any of them, M5 must never duplicate M1/M3/M4's own logic."""
    if settings.editorial_completeness_mode == "off":
        return structured_output

    title = copywriting_output.get("title")
    body = copywriting_output.get("body")
    if not isinstance(title, str) or not isinstance(body, str):
        return structured_output

    brief_data = intelligence_output.get("editorial_brief")
    brief = EditorialBrief.model_validate(brief_data) if isinstance(brief_data, dict) else None

    adaptive_data = copywriting_output.get("adaptive_length_plan")
    adaptive_plan = AdaptiveLengthPlan.model_validate(adaptive_data) if isinstance(adaptive_data, dict) else None

    beginner_data = copywriting_output.get("beginner_friendly_plan")
    beginner_plan = BeginnerFriendlyPlan.model_validate(beginner_data) if isinstance(beginner_data, dict) else None

    source_sufficiency = (
        brief.source_sufficiency if brief is not None
        else adaptive_plan.source_sufficiency if adaptive_plan is not None
        else SourceSufficiency.UNKNOWN
    )

    assessment = build_editorial_completeness_assessment(
        draft_title=title, draft_body=body, draft_kind=DraftKind.PRODUCTION_BASELINE,
        source_sufficiency=source_sufficiency, editorial_brief=brief,
        adaptive_length_plan=adaptive_plan, beginner_friendly_plan=beginner_plan,
        calibrated_fact_safety=calibrated_fact_safety,
    )
    return {**structured_output, "editorial_completeness": assessment.model_dump(mode="json")}
