"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 (S10-S14): the shared MediaResearchService, used by both
Telegram and Instagram platform adapters - it does not live inside either renderer (S10's own
explicit rule).

This is a thin orchestration wrapper, not a reimplementation: `services.media_research_selection.
research_and_select_media()` (from the reconciled CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1
lineage) already implements the tier ladder (S10), subject classification (S12), provenance (S13),
and bounded external discovery (S14) - real, tested, and reused verbatim. This module adds:

- `MediaResearchService`, a class shape the orchestrator can hold one instance of and inject
  platform-specific pieces (tier1 candidates, a web discovery client, a subject-match classifier)
  into per call, rather than every call site re-assembling `research_and_select_media()`'s own
  keyword arguments.
- `build_visual_intent_from_evidence()`, a bounded helper that derives a `MediaIntent` from a
  NewsEvent's title/category/EvidencePack when a caller has not already built a more specific one
  (an Instagram carousel's own per-slide planner is expected to build its own, richer MediaIntent
  directly - S15 - this helper exists for the simpler Telegram NEWS/BREAKING/DATA/QUOTE case).

Production-safety posture, unchanged from the reused module's own documented default (S14's own
"do not implement unbounded scraping"): `web_discovery_client` defaults to `NullWebDiscoveryClient`
(zero network calls) unless a caller explicitly supplies one - this module does not change that
default, and the orchestrator (S25/S26) does not supply a real one while `unified_editorial_
pipeline_enabled` is False.

Real, concrete gap found and fixed HERE (S14: "network failure must fail soft into the next tier"):
the reused `services.media_web_discovery.discover_web_candidates()` has no exception handling of
its own around `client.search()`/`client.resolve_page_image()` - a real network failure there would
propagate straight out of `research_and_select_media()` uncaught, crashing the whole selection
rather than falling back to whatever Tier 1 candidates already exist. `MediaResearchService.
research()` below is the fail-soft boundary: a web-discovery failure is caught, logged, and the
selection proceeds on Tier 1 candidates alone - never a crash, and never silently pretending
discovery ran cleanly when it did not (the failure is genuinely logged, not swallowed unlabeled).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from schemas.media_intent import DesiredVisualType, MediaIntent, MediaSubjectType, OrientationPreference
from schemas.media_subject_match import MediaSelectionResult, ResolvedMediaCandidate
from services.editorial_pipeline.contracts import EvidencePack
from services.media_research_selection import SubjectMatchClassifier, research_and_select_media
from services.media_web_discovery import NullWebDiscoveryClient, WebDiscoveryClient

logger = logging.getLogger(__name__)


def build_visual_intent_from_evidence(
    *, title: str, category: str | None, evidence: EvidencePack, platform: str = "generic",
) -> MediaIntent:
    """A deliberately conservative default intent for the common NEWS/BREAKING/DATA/QUOTE case,
    where no richer, hand-built MediaIntent exists yet.

    RUNTIME-CLOSURE-1 (S9): subject identity now comes from `services.editorial_pipeline.
    subject_extraction.extract_media_subject()` - a real, generic, deterministic extractor built
    for THIS purpose (media-subject-identity, not DATA-metric-label construction; deliberately not
    the old `content._extract_subject_from_title()`, which stays untouched for DATA - see that
    module's own docstring). Closes the Founder audit finding that the old single "capitalized-
    word-plus-digit" regex could not recognize "iPhone 17", "GPT-6", "Dario Amodei", "OpenAI", or
    "foldable iPhone" - real production title shapes, not just idealized test fixtures (S32)."""
    from services.editorial_pipeline.subject_extraction import extract_media_subject

    extracted = extract_media_subject(title)
    if extracted is None:
        return MediaIntent(
            subject_type=MediaSubjectType.CONCEPT, primary_entity=title[:200],
            desired_visual_type=DesiredVisualType.GRAPHIC_LAYOUT,
            orientation_preference=OrientationPreference.ANY,
            platform=platform if platform in ("instagram", "telegram") else "generic",  # type: ignore[arg-type]
            context_summary=(evidence.research_facts[0] if evidence.research_facts else None),
        )

    # The most specific real identity string this extraction found, in specificity order - the
    # single anchor `primary_entity` (MediaIntent's own "the exact thing the image must depict"
    # field) uses. `model_name` is set ONLY for a genuinely versioned subject (S9's own two-tier
    # required/category model - see subject_match.py) - never fabricated for a bare brand/person.
    primary_entity = extracted.versioned_form or extracted.proper_noun_run or extracted.brand_form or title[:200]
    product_name = extracted.brand_form  # a category-level signal for either tier
    return MediaIntent(
        subject_type=MediaSubjectType.PRODUCT if (extracted.versioned_form or extracted.brand_form) else MediaSubjectType.PERSON,
        primary_entity=primary_entity[:200],
        product_name=product_name,
        model_name=extracted.versioned_form,
        # A 2-3 word proper-noun run with no product/brand token alongside it is, in ordinary news
        # prose, far more often a person's full name than anything else (S9's own disclosed,
        # non-hardcoded heuristic - never a specific name list). When a brand/versioned token is
        # ALSO present, the run is left as `person=None` rather than guessing.
        person=extracted.proper_noun_run if (extracted.proper_noun_run and not extracted.brand_form and not extracted.versioned_form) else None,
        desired_visual_type=DesiredVisualType.PRODUCT_PHOTO if (extracted.versioned_form or extracted.brand_form) else DesiredVisualType.PORTRAIT,
        orientation_preference=OrientationPreference.ANY,
        platform=platform if platform in ("instagram", "telegram") else "generic",  # type: ignore[arg-type]
        context_summary=(evidence.research_facts[0] if evidence.research_facts else None),
    )


@dataclass
class MediaResearchService:
    """One instance per orchestrator run (S10) - holds nothing platform-specific itself; every
    platform-specific piece is passed into `research()` per call, so the SAME instance is safely
    reused across a Telegram NEWS post and an Instagram carousel slide in the same process."""

    official_domains: frozenset[str] = frozenset()
    max_web_candidates_to_classify: int = 8

    async def research(
        self, intent: MediaIntent, *,
        tier1_candidates: list[ResolvedMediaCandidate] | None = None,
        web_discovery_client: WebDiscoveryClient | None = None,
        subject_match_classifier: SubjectMatchClassifier | None = None,
        fallback_candidate: ResolvedMediaCandidate | None = None,
    ) -> MediaSelectionResult:
        client = web_discovery_client or NullWebDiscoveryClient()
        try:
            return await research_and_select_media(
                intent,
                tier1_candidates=tier1_candidates,
                web_discovery_client=client,
                subject_match_classifier=subject_match_classifier,
                fallback_candidate=fallback_candidate,
                official_domains=self.official_domains,
                max_web_candidates_to_classify=self.max_web_candidates_to_classify,
            )
        except Exception as exc:  # noqa: BLE001 - S14: a web-discovery failure must fail soft, never crash selection
            logger.warning("media_web_discovery_failed_soft", extra={"primary_entity": intent.primary_entity, "error": type(exc).__name__})
            return await research_and_select_media(
                intent,
                tier1_candidates=tier1_candidates,
                web_discovery_client=NullWebDiscoveryClient(),  # retry on Tier 1 only - never re-attempt the failing client
                subject_match_classifier=subject_match_classifier,
                fallback_candidate=fallback_candidate,
                official_domains=self.official_domains,
                max_web_candidates_to_classify=self.max_web_candidates_to_classify,
            )
