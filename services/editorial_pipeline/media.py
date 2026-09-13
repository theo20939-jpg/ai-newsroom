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
    where no richer, hand-built MediaIntent exists yet: `subject_type=CONCEPT` (S11's own "no
    single concrete real-world subject" category - the safe default absent a real entity extractor
    wired here) and `desired_visual_type=PRODUCT_PHOTO` only when the title's own token shape
    suggests a named product (reuses the same bounded heuristic content.py uses for DATA subjects,
    not a second competing one)."""
    from services.editorial_pipeline.content import _extract_subject_from_title  # bounded, shared heuristic

    subject = _extract_subject_from_title(title)
    return MediaIntent(
        subject_type=MediaSubjectType.PRODUCT if subject else MediaSubjectType.CONCEPT,
        primary_entity=subject or title[:200],
        product_name=subject,
        desired_visual_type=DesiredVisualType.PRODUCT_PHOTO if subject else DesiredVisualType.GRAPHIC_LAYOUT,
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
