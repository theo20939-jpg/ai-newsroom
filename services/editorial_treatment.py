"""Phase 23.1G - deterministic editorial output policy for NEWS (docs/
phase23_1g_editorial_importance_source_quality_report.md).

Root cause this addresses: Phase 23.1F's own live canary found the pipeline treats every
threshold-passing event identically - a thin, single-source, "do not publish"-recommended story
receives the same full-length editorial treatment as a well-evidenced, high-significance one. This
module composes signals that are **already computed, before any Copywriting call**, into one of
four treatments (`SKIP`/`BRIEF`/`STANDARD`/`MAJOR`) - a pure function, no new LLM call, no new
parallel scoring system.

Signals used (investigated directly against the real Phase 23.1F data, not assumed):
- `Scoring.score` (0-100 int, `capabilities/scoring_capability.py`'s own real output) - already
  gates `CONTENT_GENERATION` eligibility (`content_generation_min_score`); reused here as a
  secondary signal only, since Phase 23.1F's own real data showed it does NOT reliably distinguish
  substantiated from thin stories (both real "not suitable" stories scored 78-88/100).
- `Intelligence.significance` - the schema (`prompts/intelligence/v2.yaml`) declares only
  `type: number`, with no documented scale; real, live output is consistently a 0-10-ish integer
  (3, 3, 7, 7, 8 across the Phase 23.1F batch) - `_normalize_significance()` defensively handles
  both that convention and a possible 0-1 fractional one (some earlier test fixtures in this
  codebase used `0.7`-style values) rather than assuming either.
- `Intelligence.recommendation` - free text; `_is_negative_recommendation()` is a small, fixed
  keyword check (not a generative classifier) for an explicit "do not publish" style verdict -
  confirmed present, verbatim, in both of the two real Phase 23.1F stories this module is
  designed to catch.
- `NewsEventArticleAcquisition.effective_completeness_status` (`HEADLINE_ONLY`/`PARTIAL_TEXT`/
  `FULL_TEXT`/`FETCH_FAILED`, or no row at all for Telegram-sourced events which skip acquisition
  entirely) - confirmed, directly against the real Phase 23.1F database rows, to correlate exactly
  with which of the 5 real posts an independent editorial read rated unsuitable: both `HEADLINE_
  ONLY` events were the two "C" (not suitable) posts; the `FULL_TEXT` event was the strongest "B".
  This is `article_acquisition_mode`'s own existing `shadow` output (already active in the real
  environment) - not a new signal, not a new computation.
- `NewsSource.reliability_score` (0.0-1.0 float, `database/models/news_source.py`, populated for
  82/247 real sources) - used only as a FALLBACK when no acquisition row exists (i.e. Telegram
  sources), never as the primary evidence-quality signal - investigated and confirmed coarse/
  aggregator-level for RSS/NEWS_API feeds (both real Phase 23.1F "C" stories arrived via the same
  "Google News RU" feed source row and therefore share one identical reliability_score despite
  being about entirely different, independently-thin original articles) - a disclosed limitation,
  not silently relied upon as if it were article-specific.

Deliberately NOT used this phase: Fact Safety's own status. Fact Safety only ever runs *after*
Copywriting has already been called (`capabilities/executor.py`'s "quality" step) - using it as a
SKIP input would require re-ordering the real pipeline (out of scope, a genuine architecture
change) or accepting that the paid Copywriting call already happened before SKIP could apply,
defeating the purpose. `services/editorial_content_type.py` (Phase 20.7) was also investigated -
all 5 real Phase 23.1F stories classified as the same neutral `NEWS` type, giving no discriminating
signal in this sample; not incorporated this phase, not ruled out for a future one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Plain string constants, matching this codebase's own established convention for small closed
# vocabularies (services/story_memory.py's own NEW_STORY/UNCERTAIN_MATCH/etc., never an enum
# class) - project convention, per the phase brief's own "exact naming should follow project
# conventions" instruction.
SKIP = "SKIP"
BRIEF = "BRIEF"
STANDARD = "STANDARD"
MAJOR = "MAJOR"

# Deliberately excludes FETCH_FAILED (an attempted *upgrade* to the full article failing does not
# mean the original NewsEvent content/excerpt itself is thin - confirmed against real Phase 23.1F
# data: the one real FETCH_FAILED event (Amazon/Gilroy) was independently rated the single
# strongest post of the batch, because its own RSS excerpt was already substantial; treating
# FETCH_FAILED as weak evidence downgraded a genuinely strong story to BRIEF for no real reason -
# caught and corrected before this module's first use, not left in).
# REDIRECT_UNRESOLVED (NEWS Output Stability Fix, Case A in docs/news_output_stability_forensic_
# report.md's numbering, added alongside services/article_acquisition.py's new Google-News-
# redirect-shell detection) IS included, unlike FETCH_FAILED - it means acquisition successfully
# fetched *something* and positively confirmed it was a redirect shell, not the real article
# (never "the original RSS excerpt might still be substantial," FETCH_FAILED's own distinguishing
# case) - always at least as weak as HEADLINE_ONLY, no exception needed.
_WEAK_COMPLETENESS_STATUSES = frozenset({"HEADLINE_ONLY", "PARTIAL_TEXT", "REDIRECT_UNRESOLVED"})
_WEAK_SOURCE_RELIABILITY_MAX = 0.7
_FETCH_FAILED_STATUS = "FETCH_FAILED"

# Significance-tier boundaries (0-10 scale, per _normalize_significance()'s own docstring) -
# starting points reasoned from the one real batch of live data available (Phase 23.1F: 3, 3, 7,
# 7, 8), matching this codebase's own established "reasoned default, refine from real data"
# precedent (e.g. services/story_memory.py's own original 0.35/0.65 threshold comments) - NOT
# claimed as calibrated against a large dataset.
_VERY_LOW_SIGNIFICANCE_MAX = 3.0
_LOW_SIGNIFICANCE_MAX = 5.0
_MEDIUM_SIGNIFICANCE_MAX = 7.0
_HIGH_SIGNIFICANCE_MIN = 8.0

# A very high Scoring result is treated as one possible "strong compensating signal" (phase brief
# §6's own conceptual example: "very low Intelligence + strong score/source/engagement -> BRIEF +
# review flag") - deliberately high/conservative, so this only ever pulls a very-low-significance
# story back from SKIP to BRIEF+review, never all the way to STANDARD/MAJOR on Scoring alone.
_STRONG_COMPENSATING_SCORE_MIN = 85

_NEGATIVE_RECOMMENDATION_MARKERS: tuple[str, ...] = (
    "не публиковать", "не выпускать", "не рекомендуется публиковать",
    "do not publish", "not publish", "do not release",
)


def _normalize_significance(raw: float | int | None) -> float | None:
    """Defensive, not a guess presented as fact: `prompts/intelligence/v2.yaml`'s own schema
    declares only `type: number` - no documented scale. Real, live Phase 23.1F output is
    consistently a 0-10-ish integer; some earlier synthetic test fixtures elsewhere in this
    codebase instead used a 0-1 fractional convention. A value `<= 1.0` is scaled onto 0-10 by
    multiplying by 10 (treating it as that fractional convention); any larger value is assumed
    already on a 0-10-like scale and only clamped, never rescaled - so a real 0-10 output is never
    silently misinterpreted."""
    if raw is None:
        return None
    value = float(raw)
    if value <= 1.0:
        value *= 10.0
    return max(0.0, min(10.0, value))


def _is_negative_recommendation(recommendation: str | None) -> bool:
    if not recommendation:
        return False
    normalized = recommendation.strip().casefold()
    return any(marker in normalized for marker in _NEGATIVE_RECOMMENDATION_MARKERS)


def _fetch_failed_content_is_thin(event_title: str | None, event_content: str | None) -> bool:
    """Phase 23.1P root-cause fix (docs/phase23_1p_story_memory_quotes_gate_report.md): the
    FETCH_FAILED exclusion above assumes the original NewsEvent excerpt is usually still
    substantial when the full-article upgrade fails - true for the Amazon/Gilroy case this module
    was built around, but NOT universal, and never actually checked. Real counter-example (the
    Terraria mod story, Phase 23.1O): FETCH_FAILED, `news_event.content` = only a 59-character bare
    quote fragment - shorter than the event's own 122-character title, i.e. carrying zero real
    information beyond the headline - yet treated as "not weak," letting a story Intelligence
    explicitly recommended against publishing slip past the SKIP gate.

    Self-relative, not an arbitrary absolute character count: content that is no longer than the
    event's own title contributes nothing a reader doesn't already have from the headline alone -
    already-available data (title, content), zero new signal, zero new field. A FETCH_FAILED event
    whose content genuinely exceeds its title (the Amazon/Gilroy shape) is left exactly as before -
    not weak."""
    if not event_content or not event_title:
        return True
    return len(event_content.strip()) <= len(event_title.strip())


def _is_weak_evidence(
    evidence_completeness: str | None, source_reliability: float | None,
    *, event_title: str | None = None, event_content: str | None = None,
) -> bool:
    """`evidence_completeness` (article-level, when available) is authoritative; `source_
    reliability` (often aggregator-level, per this module's own docstring) is consulted only when
    no acquisition row exists at all - never overrides a known-good `FULL_TEXT` status.

    Phase 23.1P: FETCH_FAILED is a narrow third case - excluded from `_WEAK_COMPLETENESS_STATUSES`
    by design (see that constant's own comment), but no longer an unconditional "not weak" - see
    `_fetch_failed_content_is_thin()`'s own docstring for the real regression this closes."""
    if evidence_completeness is not None:
        if evidence_completeness == _FETCH_FAILED_STATUS:
            return _fetch_failed_content_is_thin(event_title, event_content)
        return evidence_completeness in _WEAK_COMPLETENESS_STATUSES
    return source_reliability is not None and source_reliability < _WEAK_SOURCE_RELIABILITY_MAX


@dataclass(frozen=True)
class EditorialTreatmentDecision:
    """Carries the treatment plus its own audit trail - `reason` is required so a `SKIP` (phase
    brief §3: "log/persist reason for audit") is never a bare, unexplained drop, and
    `human_review_required` implements §6's own "BRIEF + review flag" outcome without making the
    flag itself a blocking gate (it is metadata only this phase - nothing reads it to block
    anything, matching the phase's own explicit "do not implement a blocking gate")."""

    treatment: str
    human_review_required: bool
    reason: str


def classify_editorial_treatment(
    *,
    significance: float | int | None,
    recommendation: str | None,
    scoring_score: int | None = None,
    source_reliability: float | None = None,
    evidence_completeness: str | None = None,
    event_title: str | None = None,
    event_content: str | None = None,
) -> EditorialTreatmentDecision:
    """Pure, deterministic. Identical inputs always produce an identical decision - see the
    module's own docstring for exactly which real signals feed this and why each was chosen.

    `event_title`/`event_content` (Phase 23.1P, both optional, both already available to every
    caller from the same `NewsEvent` row `evidence_completeness`/`source_reliability` are derived
    from) feed only `_is_weak_evidence()`'s own narrow FETCH_FAILED check - see that function's
    docstring. Omitting them defaults `_fetch_failed_content_is_thin()` to "thin" (the
    conservative, fail-toward-caution direction, matching this function's own established
    "no Intelligence significance available - conservative default" precedent) rather than
    silently reproducing the old FETCH_FAILED-is-never-weak behavior for a caller that has not
    been updated to pass them.
    """
    sig = _normalize_significance(significance)
    negative_rec = _is_negative_recommendation(recommendation)
    weak_evidence = _is_weak_evidence(
        evidence_completeness, source_reliability, event_title=event_title, event_content=event_content,
    )
    strong_compensating = scoring_score is not None and scoring_score >= _STRONG_COMPENSATING_SCORE_MIN

    # Independent, unconditional SKIP trigger (phase brief §7's own product rule): evidence too
    # weak to trust AND Intelligence has already said so in words - regardless of the numeric
    # significance tier, this combination is the exact "most of the article would have to explain
    # why it can't verify the story" pattern that should not become a Telegram post at all.
    if weak_evidence and negative_rec:
        return EditorialTreatmentDecision(
            SKIP, human_review_required=False,
            reason=f"weak evidence ({evidence_completeness or 'low source reliability'}) + "
                   f"explicit negative Intelligence recommendation",
        )

    if sig is None:
        return EditorialTreatmentDecision(
            BRIEF, human_review_required=True,
            reason="no Intelligence significance available - conservative default, never MAJOR/STANDARD blind",
        )

    if sig <= _VERY_LOW_SIGNIFICANCE_MAX:
        if weak_evidence:
            if strong_compensating:
                return EditorialTreatmentDecision(
                    BRIEF, human_review_required=True,
                    reason=f"very low significance ({sig}) + weak evidence, but a strong compensating "
                           f"Scoring result ({scoring_score}) - kept as a flagged brief, not skipped",
                )
            return EditorialTreatmentDecision(
                SKIP, human_review_required=False,
                reason=f"very low significance ({sig}) + weak evidence ({evidence_completeness or 'low source reliability'})",
            )
        return EditorialTreatmentDecision(
            BRIEF, human_review_required=negative_rec,
            reason=f"very low significance ({sig}), evidence not independently weak",
        )

    if sig <= _LOW_SIGNIFICANCE_MAX:
        return EditorialTreatmentDecision(
            BRIEF, human_review_required=negative_rec,
            reason=f"low significance ({sig}) - a valid but minor story",
        )

    if sig <= _MEDIUM_SIGNIFICANCE_MAX:
        treatment = BRIEF if weak_evidence else STANDARD
        return EditorialTreatmentDecision(
            treatment, human_review_required=negative_rec,
            reason=f"medium significance ({sig}){' with weak evidence' if weak_evidence else ''}",
        )

    if sig < _HIGH_SIGNIFICANCE_MIN:
        return EditorialTreatmentDecision(
            STANDARD, human_review_required=negative_rec,
            reason=f"medium-high significance ({sig})",
        )

    if weak_evidence:
        return EditorialTreatmentDecision(
            STANDARD, human_review_required=True,
            reason=f"high significance ({sig}) but weak evidence - downgraded from MAJOR",
        )
    return EditorialTreatmentDecision(
        MAJOR, human_review_required=False,
        reason=f"high significance ({sig}), evidence not weak",
    )


def treatment_from_intelligence_and_evidence(
    intelligence_output: dict[str, Any] | None,
    scoring_output: dict[str, Any] | None,
    *,
    source_reliability: float | None = None,
    evidence_completeness: str | None = None,
    event_title: str | None = None,
    event_content: str | None = None,
) -> EditorialTreatmentDecision:
    """Convenience wrapper reading straight from the real, persisted step-result dict shapes
    (`intelligence_output` from the "intelligence" step, `scoring_output` from the "scoring"
    step) - avoids every caller re-deriving `.get("significance")`/`.get("score")` itself.

    `event_title`/`event_content` (Phase 23.1P): passed straight through to
    `classify_editorial_treatment()` - see its own docstring."""
    significance = intelligence_output.get("significance") if intelligence_output else None
    recommendation = intelligence_output.get("recommendation") if intelligence_output else None
    scoring_score = scoring_output.get("score") if scoring_output else None
    return classify_editorial_treatment(
        significance=significance, recommendation=recommendation, scoring_score=scoring_score,
        source_reliability=source_reliability, evidence_completeness=evidence_completeness,
        event_title=event_title, event_content=event_content,
    )
