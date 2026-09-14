"""INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §7: the ONE authorized way Instagram media selection
happens - a thin, honest wrapper around the SAME `services.editorial_pipeline.media.
MediaResearchService` Telegram already uses (deliberately platform-neutral by its own docstring:
"used by both Telegram and Instagram platform adapters - it does not live inside either renderer").

This module invents NO new authority (§7's own explicit "do not create a second competing media
authority"). It exists only because, before this phase, nothing in the Instagram code path ever
called `MediaResearchService` at all - `InstagramContentPackage.source_image_ref` was populated
only by a manually-invoked canary script (see `docs/instagram_production_rollout_1_report.md` §G).

Wiring this in gets Instagram the SAME structural guarantees Telegram already has, for free, with
zero new exclusion logic written here:

- `is_selectable()` (services/media_candidate_scoring.py, unmodified) already refuses to let
  MISMATCH or EDITORIAL_REVIEW_REQUIRED candidates become `MediaSelectionResult.selected` - so a
  package built from this module's own result can never carry either as its selected candidate.
- `classify_subject_match()` (services/editorial_pipeline/subject_match.py, unmodified) is the
  same deterministic text-evidence classifier Telegram uses.
- The vision gate (`services/editorial_pipeline/subject_match_vision_gate.py`, unmodified) may
  optionally be layered in exactly the same way Telegram's own call site does, via the same
  `capability_registry` parameter - never a second, Instagram-specific vision integration.
"""
from __future__ import annotations

from schemas.media_intent import MediaIntent
from schemas.media_subject_match import MediaSelectionResult, ResolvedMediaCandidate
from services.editorial_pipeline.media import MediaResearchService
from services.editorial_pipeline.subject_match import classify_subject_match
from services.editorial_pipeline.subject_match_vision_gate import (
    VisionSubjectMatchCapability,
    build_vision_gate_subject_match_classifier,
)
from services.media_web_discovery import WebDiscoveryClient


async def resolve_instagram_media(
    intent: MediaIntent, *,
    tier1_candidates: list[ResolvedMediaCandidate] | None = None,
    web_discovery_client: WebDiscoveryClient | None = None,
    vision_capability: VisionSubjectMatchCapability | None = None,
    image_bytes_provider=None,
    media_research_service: MediaResearchService | None = None,
) -> MediaSelectionResult:
    """The one function any live Instagram package-building path must call before recording a
    selected image. `vision_capability`/`image_bytes_provider` mirror `telegram_integration.py`'s
    own optional escalation wiring exactly - when both are supplied, ambiguous (GENERIC_CONTEXT +
    exact-subject-required) candidates get the same bounded, fail-soft vision escalation Telegram's
    live path already has; when either is omitted (the default), the plain deterministic classifier
    runs alone, identical in spirit to Telegram's own "capability_registry=None -> deterministic
    only" fallback."""
    classifier = classify_subject_match
    if vision_capability is not None and image_bytes_provider is not None:
        classifier = build_vision_gate_subject_match_classifier(
            vision_capability=vision_capability, image_bytes_provider=image_bytes_provider,
        )
    service = media_research_service or MediaResearchService()
    return await service.research(
        intent, tier1_candidates=tier1_candidates, web_discovery_client=web_discovery_client,
        subject_match_classifier=classifier,
    )
