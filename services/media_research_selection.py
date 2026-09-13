"""CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1 section 2: the one orchestration entrypoint tying
every tier together - `content need -> media intent -> local/source candidates -> external
discovery if needed -> provenance extraction -> candidate normalization -> relevance/safety
validation -> ranking -> deduplication -> selected media package` (section 2's own conceptual flow,
literally this function's own body, in order).

Deliberately platform-neutral: nothing here is Instagram- or Telegram-specific, and nothing here
constructs a Gateway/Capability/DB session itself - `subject_match_classifier` and `tier1_
candidates` are both injected by the caller, so this module stays fully unit-testable without a
real LLM call or a real database, exactly like `services/telegraph_visual_research.py`'s own
"aggregates already-persisted rows, computes nothing new itself" discipline for Tier 1, extended
here to also aggregate Tier 2-5."""
from __future__ import annotations

import logging
from collections import Counter
from typing import Awaitable, Callable

from schemas.media_intent import MediaIntent
from schemas.media_subject_match import (
    MediaSelectionResult,
    MediaUsageClassification,
    ResolvedMediaCandidate,
    SubjectMatchClassification,
    SubjectMatchValidation,
)
from services.media_candidate_scoring import is_selectable, score_candidate
from services.media_web_discovery import NullWebDiscoveryClient, WebDiscoveryClient, discover_web_candidates

logger = logging.getLogger(__name__)

SubjectMatchClassifier = Callable[[ResolvedMediaCandidate, MediaIntent], Awaitable[SubjectMatchValidation]]


async def research_and_select_media(
    intent: MediaIntent, *,
    tier1_candidates: list[ResolvedMediaCandidate] | None = None,
    web_discovery_client: WebDiscoveryClient | None = None,
    subject_match_classifier: SubjectMatchClassifier | None = None,
    fallback_candidate: ResolvedMediaCandidate | None = None,
    official_domains: frozenset[str] = frozenset(),
    max_web_candidates_to_classify: int = 8,
) -> MediaSelectionResult:
    """`tier1_candidates` - already-normalized Tier 1 candidates (section 5) a caller built from
    the EXISTING, real Phase 16 `image_candidates` pool (read-only reuse, never re-discovered
    here). `web_discovery_client` defaults to `NullWebDiscoveryClient()` (production-safe no-op -
    section 25). `subject_match_classifier` is optional: without one, every candidate stays
    unclassified and scoring falls back to its own conservative GENERIC_CONTEXT default (services/
    media_candidate_scoring.py) - never assumed EXACT. `fallback_candidate` (section 11/14) is the
    caller's own safe-fallback asset (a graphic layout, a brand asset) - this module never invents
    one; it only decides WHETHER a fallback is needed and reports that decision truthfully."""
    client = web_discovery_client or NullWebDiscoveryClient()
    all_candidates: list[ResolvedMediaCandidate] = list(tier1_candidates or [])
    all_candidates.extend(await discover_web_candidates(intent, client, official_domains=official_domains))

    rejection_reasons: list[str] = []
    notes: list[str] = []

    if subject_match_classifier is not None:
        classified: list[ResolvedMediaCandidate] = []
        for i, candidate in enumerate(all_candidates):
            if candidate.subject_match is not None:
                classified.append(candidate)
                continue
            if i >= max_web_candidates_to_classify:
                notes.append(
                    f"candidate {candidate.candidate_id} left unclassified - "
                    f"max_web_candidates_to_classify={max_web_candidates_to_classify} reached"
                )
                classified.append(candidate)
                continue
            try:
                verdict = await subject_match_classifier(candidate, intent)
            except Exception as exc:  # never let one candidate's classification failure abort the
                # whole selection - logged, the candidate stays unclassified (conservative default)
                logger.warning(
                    "media_subject_match_classification_failed",
                    extra={"candidate_id": candidate.candidate_id, "error": type(exc).__name__},
                )
                classified.append(candidate)
                continue
            classified.append(candidate.model_copy(update={"subject_match": verdict}))
        all_candidates = classified

    classification_counts: Counter[str] = Counter()
    for candidate in all_candidates:
        label = candidate.subject_match.subject_match.value if candidate.subject_match else "unclassified"
        classification_counts[label] += 1
        if candidate.usage_classification is MediaUsageClassification.NOT_USABLE:
            rejection_reasons.append(f"{candidate.candidate_id}: usage_classification=not_usable")
        elif candidate.subject_match is not None and candidate.subject_match.subject_match is SubjectMatchClassification.MISMATCH:
            rejection_reasons.append(f"{candidate.candidate_id}: subject_match=mismatch ({candidate.subject_match.reason})")

    scored = [(c, score_candidate(c, intent)) for c in all_candidates if is_selectable(c)]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    if scored:
        best, best_score = scored[0]
        exact_found = best.subject_match is not None and best.subject_match.subject_match is SubjectMatchClassification.EXACT_SUBJECT
        return MediaSelectionResult(
            intent_primary_entity=intent.primary_entity,
            selected=best, selected_score=best_score,
            exact_subject_media_not_found=not exact_found,
            fallback_used=False,
            candidates_considered=len(all_candidates),
            candidates_by_classification=dict(classification_counts),
            rejection_reasons=rejection_reasons, notes=notes,
        )

    # Nothing selectable - section 11's "no verified real photograph exists" path.
    notes.append("no selectable candidate found - every candidate was either NOT_USABLE, MISMATCH, or no candidate was discovered at all")
    return MediaSelectionResult(
        intent_primary_entity=intent.primary_entity,
        selected=fallback_candidate, selected_score=None,
        exact_subject_media_not_found=True,
        fallback_used=fallback_candidate is not None,
        candidates_considered=len(all_candidates),
        candidates_by_classification=dict(classification_counts),
        rejection_reasons=rejection_reasons, notes=notes,
    )
