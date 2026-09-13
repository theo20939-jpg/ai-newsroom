"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-FINAL-HARDENING-1: the real, central media subject-match
authority the Founder review's HIGH finding demanded.

Founder finding (verbatim): "Media truthfulness is not actually enforced at the unified runtime
call site. The taxonomy exists, but a wrong-subject photo may still be accepted." Confirmed root
cause (`artifacts/unified_pipeline_founder_review_bundle_1/07_MEDIA_TRUTHFULNESS_AUDIT.md`):
`services/editorial_pipeline/telegram_integration.py` injected NO `subject_match_classifier` into
`MediaResearchService.research()` - the real, already-built, already-tested scoring/exclusion
machinery in `services/media_candidate_scoring.py` (`EXACT_SUBJECT` dominance, `MISMATCH` hard
exclusion) never received a real classification to act on, so every candidate defaulted to
`GENERIC_CONTEXT` and - being the only candidate offered - was always selected regardless of
whether it was actually right or wrong.

This module is that classifier - the ONE, central authority `MediaResearchService.research()`
calls (via the `subject_match_classifier` parameter that has existed, unused, since
UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1). It is NOT a second, competing classifier:
`services/media_candidate_scoring.py`'s own dominance/exclusion policy (EXACT_SUBJECT always beats
any non-exact combination; MISMATCH is hard-excluded, never merely low-scored) is completely
unmodified and remains the SOLE ranking/selection authority - this module only ever produces the
`SubjectMatchValidation` verdict that policy already knows how to act on correctly.

Deliberately generic, never overfit to any one product/brand (Founder review §10's own explicit
instruction): every comparison is driven entirely by the CALLER-supplied `MediaIntent`'s own
structured identity fields (`model_name`, `must_show`, `must_not_imply`, `product_name`, `company`,
`person`, `event`, `location`) against the CANDIDATE's own available descriptive text
(`ResolvedMediaCandidate.provenance.caption_or_alt`) - no brand name, product name, or keyword of
any kind is hardcoded anywhere in this file.

Deterministic and evidence-based, never a vision/LLM call (Founder review §6's own "no fabricated
image semantics", §2's own "do not create a second parallel classifier" alongside the real,
existing `capabilities/media_subject_match_capability.py`, which remains the correct home for any
FUTURE real vision-based classification - this module does not compete with it, it fills the gap
that exists TODAY, where no caller wires any classifier in at all). Two-tier identity model:

- REQUIRED terms (`intent.model_name` + `intent.must_show`) - the specific qualifier(s) that make
  this story's subject distinct from its own broader category. ALL must be textually confirmed for
  `EXACT_SUBJECT` - matches the Founder's own "SAME PRODUCT FAMILY != SAME VERSION" invariant.
- CATEGORY terms (`intent.product_name`, `intent.company`, `intent.person`, `intent.event`,
  `intent.location`) - broad-category signals. A category-only match is `STRONG_CONTEXT` at best,
  NEVER `EXACT_SUBJECT` - matches "SAME BRAND != SAME PRODUCT"/"SAME PERSON CATEGORY != SAME
  PERSON"/"RELATED EVENT != EXACT EVENT".
- FORBIDDEN terms (`intent.must_not_imply`) - specific, story-authored false impressions. A
  positive textual match is a hard `MISMATCH`, regardless of any other signal, resolution, crop, or
  source reputation (Founder review §5's own "must still lose if it is MISMATCH").
- No evidence at all (empty/missing candidate text) -> `GENERIC_CONTEXT`, never `EXACT_SUBJECT` and
  never `MISMATCH` (Founder review §6's own "fail toward... depending on available evidence" - an
  absence of evidence is never treated as either kind of certainty).
"""
from __future__ import annotations

from schemas.media_intent import MediaIntent
from schemas.media_subject_match import ResolvedMediaCandidate, SubjectMatchClassification, SubjectMatchValidation


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _term_present(term: str, haystack: str) -> bool:
    normalized_term = _normalize(term)
    return bool(normalized_term) and normalized_term in haystack


def _required_terms(intent: MediaIntent) -> list[str]:
    """The specific, distinguishing qualifier(s) - `model_name` (a single exact-version identifier)
    plus every `must_show` entry (a story-specific list of required visual elements/qualifiers,
    e.g. "foldable design", "hinge visible" - see `MediaIntent.must_show`'s own docstring). Both
    fields exist for exactly this purpose already; this module invents no new ones."""
    terms = list(intent.must_show)
    if intent.model_name:
        terms.append(intent.model_name)
    return [t for t in terms if t and t.strip()]


def _category_terms(intent: MediaIntent) -> list[str]:
    """Broad-category identity signals - real, but never sufficient alone for EXACT_SUBJECT."""
    candidates = [intent.product_name, intent.company, intent.person, intent.event, intent.location]
    return [t for t in candidates if t and t.strip()]


async def classify_subject_match(
    candidate: ResolvedMediaCandidate, intent: MediaIntent,
) -> SubjectMatchValidation:
    """The real `SubjectMatchClassifier` (`services.media_research_selection.SubjectMatchClassifier`
    Protocol shape - `Callable[[ResolvedMediaCandidate, MediaIntent], Awaitable[SubjectMatchValidation]]`)
    this phase wires into `MediaResearchService.research()`. `async def` to match that Protocol
    exactly (`research_and_select_media()` always `await`s it) even though the logic itself is pure
    and synchronous - no I/O, no network call, no LLM call, fully deterministic."""
    raw_text = candidate.provenance.caption_or_alt or ""
    text = _normalize(raw_text)

    required_terms = _required_terms(intent)
    category_terms = _category_terms(intent)
    forbidden_terms = [t for t in intent.must_not_imply if t and t.strip()]

    if not text:
        return SubjectMatchValidation(
            depicted_subject_description="no descriptive text available for this candidate",
            subject_match=SubjectMatchClassification.GENERIC_CONTEXT,
            must_not_imply_violated=False,
            violated_statements=[],
            confidence="low",
            reason=(
                "no caption/alt/description text was available for this candidate - there is not "
                "enough evidence to assert EXACT_SUBJECT or MISMATCH, so this defaults to the "
                "conservative GENERIC_CONTEXT classification rather than fabricating a verdict."
            ),
        )

    matched_forbidden = [t for t in forbidden_terms if _term_present(t, text)]
    if matched_forbidden:
        return SubjectMatchValidation(
            depicted_subject_description=raw_text[:500],
            subject_match=SubjectMatchClassification.MISMATCH,
            must_not_imply_violated=True,
            violated_statements=matched_forbidden[:10],
            confidence="high",
            reason=(
                f"candidate text matches a disallowed implication this intent explicitly rules "
                f"out: {matched_forbidden[0]!r} - never selectable regardless of resolution, crop, "
                f"or source reputation."
            ),
        )

    matched_required = [t for t in required_terms if _term_present(t, text)]
    if required_terms and len(matched_required) == len(required_terms):
        return SubjectMatchValidation(
            depicted_subject_description=raw_text[:500],
            subject_match=SubjectMatchClassification.EXACT_SUBJECT,
            must_not_imply_violated=False,
            violated_statements=[],
            confidence="high",
            reason=f"candidate text explicitly confirms every required identity term: {matched_required}.",
        )

    matched_category = [t for t in category_terms if _term_present(t, text)]
    if matched_category:
        if required_terms and not matched_required:
            reason = (
                f"candidate text confirms only the broader category ({matched_category}) - the "
                f"more specific, required identity term(s) {required_terms} are not confirmed, so "
                f"this is treated as context only, never assumed to be the exact subject."
            )
        else:
            reason = (
                f"candidate text confirms a category match ({matched_category}); no more specific "
                f"identity requirement was set for this intent."
            )
        return SubjectMatchValidation(
            depicted_subject_description=raw_text[:500],
            subject_match=SubjectMatchClassification.STRONG_CONTEXT,
            must_not_imply_violated=False,
            violated_statements=[],
            confidence="medium",
            reason=reason,
        )

    return SubjectMatchValidation(
        depicted_subject_description=raw_text[:500],
        subject_match=SubjectMatchClassification.GENERIC_CONTEXT,
        must_not_imply_violated=False,
        violated_statements=[],
        confidence="low",
        reason=(
            "candidate text does not confirm any required or category identity term for this "
            "intent - topically unconfirmed, defaulting to the conservative GENERIC_CONTEXT "
            "classification rather than fabricating a stronger verdict."
        ),
    )
