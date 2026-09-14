"""UNIFIED-EDITORIAL-PIPELINE-VISION-GATE-CLOSURE-1: wires the real, existing
`capabilities/media_subject_match_capability.py` into the unified media subject-verification path
- the one Founder HIGH left open by RUNTIME-CLOSURE-1
(`ACTUAL_IMAGE_VERIFICATION_WIRED = false`).

Not a second, competing classifier: `services.editorial_pipeline.subject_match.classify_subject_
match()` (the deterministic, text-evidence classifier) remains first, cheap, and authoritative for
every case it can actually decide. This module wraps it with a SECOND-TIER, bounded, fail-soft
escalation to the real vision capability, used ONLY when all three of the phase's own required
conditions hold:

    1. metadata/text evidence is insufficient (the deterministic verdict is GENERIC_CONTEXT - no
       evidence either confirms or rules out the claimed subject);
    2. the visual intent actually requires an exact/narrow subject depiction (`intent.model_name`
       or `intent.must_show` is non-empty - reuses `subject_match._required_terms()`, never a
       second, competing definition of "requires exact subject");
    3. (implied by 1) the candidate would otherwise remain GENERIC_CONTEXT and potentially
       selectable - is_selectable() already treats GENERIC_CONTEXT as selectable (services/
       media_candidate_scoring.py, unmodified).

Policy (all required by the phase brief, enforced here structurally, not by convention):

    - MISMATCH from deterministic evidence is NEVER escalated - already rejected, vision cannot
      make a rejected candidate more rejected, and re-running a classifier gains nothing.
    - EXACT_SUBJECT from deterministic evidence is NEVER escalated - "clearly supported EXACT may
      avoid unnecessary vision" (bounded cost, S13's own spirit extended to this second tier).
    - STRONG_CONTEXT is NEVER escalated either - it already carries real category evidence; only a
      genuinely AMBIGUOUS (GENERIC_CONTEXT) verdict on an exact-subject-requiring intent escalates.
    - A vision MISMATCH verdict overrides the candidate to MISMATCH (rejected).
    - A vision EXACT_SUBJECT/STRONG_CONTEXT verdict upgrades the candidate accordingly.
    - A vision GENERIC_CONTEXT verdict (vision genuinely ran but still found nothing conclusive)
      leaves the deterministic GENERIC_CONTEXT verdict unchanged - never invents confidence.
    - Vision unavailable/erroring/timing out NEVER upgrades to EXACT (or anything else) - the
      deterministic GENERIC_CONTEXT verdict is returned unchanged, fail-soft, always logged.

Bounded by construction: one `asyncio.wait_for()`-wrapped call per candidate, no retry loop, no
recursive search, results cached by content hash (`candidate.sha256` if already known, else a hash
computed once from the resolved bytes) so the SAME media identity is never vision-checked twice
within one cache's lifetime (a fresh cache is used per pipeline run by default - see `telegram_
integration.py`'s own call site - so no cross-request state leaks between unrelated events)."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from typing import Awaitable, Callable, Protocol
from uuid import uuid4

from database.models.editorial_task import TaskPriority
from schemas.capability import (
    BusinessContext,
    CapabilityContext,
    CapabilityResult,
    ExecutionContext,
    NewsEventSnapshot,
    RuntimeContext,
    WorkflowExecutionStateSnapshot,
)
from schemas.media_intent import MediaIntent
from schemas.media_subject_match import ResolvedMediaCandidate, SubjectMatchClassification, SubjectMatchValidation
from services.editorial_pipeline.subject_match import _required_terms, classify_subject_match

logger = logging.getLogger(__name__)

DEFAULT_VISION_TIMEOUT_SECONDS = 8.0
"""Bounded ceiling on the one real Gateway call this module ever makes per candidate - generous
enough for a real vision-LLM round trip, never unbounded (S13's own spirit, applied to this
second, narrower tier)."""

_MIME_BY_FORMAT_HINT = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


class VisionSubjectMatchCapability(Protocol):
    """The exact shape `capabilities.media_subject_match_capability.MediaSubjectMatchCapability`
    already implements (`Capability` Protocol) - typed narrowly here so this module never imports
    the Capability Framework's heavier machinery (`CapabilityRegistry`, Gateway wiring) directly,
    and so a test can inject a trivial fake with zero real network/LLM dependency (S35's own
    "no real external network dependency in tests")."""

    async def execute(self, context: CapabilityContext) -> CapabilityResult: ...


def _to_data_uri(image_bytes: bytes, *, mime_type: str | None) -> str:
    mime = _MIME_BY_FORMAT_HINT.get((mime_type or "").split("/")[-1].lower(), mime_type or "image/jpeg")
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _intent_summary(intent: MediaIntent, candidate: ResolvedMediaCandidate) -> str:
    """Mirrors `scripts._cross_platform_media_research_canary_1._intent_summary()`'s own real,
    already-reviewed shape (never invents a new prompt-construction convention) - every field is
    either directly off `intent` or off `candidate.provenance`, nothing fabricated."""
    parts = [f"subject_type={intent.subject_type.value}", f"primary_entity={intent.primary_entity}"]
    for label, value in (
        ("company", intent.company), ("person", intent.person), ("product_name", intent.product_name),
        ("model_name", intent.model_name), ("event", intent.event),
    ):
        if value:
            parts.append(f"{label}={value}")
    if intent.must_show:
        parts.append(f"must_show={intent.must_show}")
    if intent.must_not_imply:
        parts.append(f"must_not_imply={intent.must_not_imply}")
    parts.append("--- real corroborating evidence for THIS specific candidate ---")
    if candidate.provenance.caption_or_alt:
        parts.append(f"candidate's own caption/alt text: {candidate.provenance.caption_or_alt!r}")
    if candidate.provenance.publisher_domain:
        parts.append(f"publisher domain: {candidate.provenance.publisher_domain}")
    parts.append(f"origin page: {candidate.provenance.origin_url}")
    return "\n".join(parts)


def _should_escalate_to_vision(deterministic: SubjectMatchValidation, intent: MediaIntent) -> bool:
    """The phase's own three required conditions, checked together: (1) metadata insufficient ==
    GENERIC_CONTEXT; (2) intent requires an exact/narrow depiction == real required_terms exist;
    (3) is implied by (1) - a GENERIC_CONTEXT candidate is exactly the "would otherwise remain
    GENERIC/UNKNOWN and potentially selectable" case (services/media_candidate_scoring.py's own
    is_selectable() already treats GENERIC_CONTEXT as selectable, never excluded by rights/mismatch
    logic alone). MISMATCH/EXACT_SUBJECT/STRONG_CONTEXT never escalate - see module docstring."""
    if deterministic.subject_match is not SubjectMatchClassification.GENERIC_CONTEXT:
        return False
    return _intent_requires_exact_narrow_subject(intent)


def _intent_requires_exact_narrow_subject(intent: MediaIntent) -> bool:
    """"Requires an exact/narrow subject depiction" (condition 2) - `subject_match.py`'s own
    `_required_terms()` (model_name/must_show) is the right test for a PRODUCT-shaped intent
    ("same brand != same version"), but a `person` identity is, by its own nature, already
    maximally narrow (there is no broader "family" of one specific named person the way there is a
    broader product family) - a named-person story therefore always requires an exact/narrow
    depiction too, even with no `model_name`/`must_show` set. Never broadened further than this:
    a bare `company`/`event`/`location` category hint alone still does NOT trigger escalation
    (those genuinely describe a category, not one exact, narrow subject)."""
    return bool(_required_terms(intent)) or bool(intent.person)


async def _call_vision_capability(
    capability: VisionSubjectMatchCapability, *, image_bytes: bytes, mime_type: str | None,
    intent: MediaIntent, candidate: ResolvedMediaCandidate,
) -> SubjectMatchValidation:
    """One bounded Gateway call, real `CapabilityContext` construction mirroring the one other
    real, reviewed call site this repo has ever built for this capability
    (`scripts/_cross_platform_media_research_canary_1.py`) - never a second, divergent context-
    building convention. `NewsEventSnapshot`/`WorkflowExecutionStateSnapshot` here are minimal and
    purely structural (`RuntimeContext`/`BusinessContext` require them); the actual judgment the
    model makes comes entirely from the image bytes and `_intent_summary()`'s real text, nothing
    invented in these snapshot fields is ever shown to the model as claimed evidence."""
    context = CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=uuid4(), title=intent.primary_entity, summary=None, content=None, url=None,
                category=intent.subject_type.value, published_at=None,
            ),
            workflow_state=WorkflowExecutionStateSnapshot(workflow_name="content_generation", workflow_version=1, completed_steps=[]),
            media_subject_match_image_data_uri=_to_data_uri(image_bytes, mime_type=mime_type),
            media_subject_match_intent_summary=_intent_summary(intent, candidate),
        ),
        runtime=RuntimeContext(
            task_id=uuid4(), event_id=uuid4(), capability_name="media_subject_match",
            priority=TaskPriority.B, attempt=1, iteration_count=0,
        ),
        execution=ExecutionContext(),
    )
    result = await capability.execute(context)
    if result.status != "SUCCESS" or result.structured_output is None:
        raise RuntimeError(f"vision subject-match capability returned status={result.status!r}")
    return SubjectMatchValidation(**result.structured_output)


def _combine(deterministic: SubjectMatchValidation, vision: SubjectMatchValidation) -> SubjectMatchValidation:
    """Vision may only move the verdict to something MORE conclusive, never less - and unknown
    (GENERIC_CONTEXT) from vision changes nothing (§ policy: "never accept unknown simply because
    vision failed" extended to "a genuinely-ran-but-inconclusive vision call is not a failure, but
    it also does not invent confidence")."""
    if vision.subject_match is SubjectMatchClassification.GENERIC_CONTEXT:
        return deterministic
    return vision


def build_vision_gate_subject_match_classifier(
    *, vision_capability: VisionSubjectMatchCapability,
    image_bytes_provider: Callable[[ResolvedMediaCandidate], bytes | None],
    timeout_seconds: float = DEFAULT_VISION_TIMEOUT_SECONDS,
    cache: dict[str, SubjectMatchValidation] | None = None,
) -> Callable[[ResolvedMediaCandidate, MediaIntent], Awaitable[SubjectMatchValidation]]:
    """Returns a real `SubjectMatchClassifier` (services.media_research_selection.
    SubjectMatchClassifier's exact shape) - a drop-in replacement for the plain `classify_subject_
    match` at the one real call site (`telegram_integration.run_unified_telegram_delivery`).
    `cache` defaults to a fresh dict per call to this factory - `telegram_integration.py` builds
    one fresh cache per `run_unified_telegram_delivery()` invocation (one event), so no state
    leaks across unrelated events/requests; a caller wanting cross-call dedup may pass its own."""
    local_cache: dict[str, SubjectMatchValidation] = cache if cache is not None else {}

    async def _classify(candidate: ResolvedMediaCandidate, intent: MediaIntent) -> SubjectMatchValidation:
        deterministic = await classify_subject_match(candidate, intent)
        if not _should_escalate_to_vision(deterministic, intent):
            return deterministic

        try:
            image_bytes = image_bytes_provider(candidate)
        except Exception as exc:  # noqa: BLE001 - a bytes-provider failure (e.g. a storage lookup
            # error) must never discard the deterministic verdict already computed above, and must
            # never propagate out of this classifier - `research_and_select_media()`'s own
            # try/except around each classifier call would otherwise catch it too, but at the cost
            # of losing the deterministic result this function already has in hand.
            logger.warning(
                "vision_subject_match_image_bytes_provider_failed",
                extra={"candidate_id": candidate.candidate_id, "error": type(exc).__name__},
            )
            return deterministic
        if image_bytes is None:
            logger.info(
                "vision_subject_match_skipped_no_bytes",
                extra={"candidate_id": candidate.candidate_id, "reason": "no resolvable image bytes for vision escalation"},
            )
            return deterministic

        cache_key = candidate.sha256 or hashlib.sha256(image_bytes).hexdigest()
        cached = local_cache.get(cache_key)
        if cached is not None:
            logger.info("vision_subject_match_cache_hit", extra={"candidate_id": candidate.candidate_id, "cache_key": cache_key})
            return _combine(deterministic, cached)

        logger.info(
            "vision_subject_match_called",
            extra={"candidate_id": candidate.candidate_id, "cache_key": cache_key, "timeout_seconds": timeout_seconds},
        )
        try:
            vision_result = await asyncio.wait_for(
                _call_vision_capability(
                    vision_capability, image_bytes=image_bytes,
                    mime_type=None,  # ResolvedMediaCandidate carries no mime field of its own -
                    # _to_data_uri() defaults to image/jpeg, matching this codebase's own
                    # established default elsewhere (e.g. bot/image_preview_media.py)
                    intent=intent, candidate=candidate,
                ),
                timeout=timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - S: fail-soft, never upgrade, never raise past this
            # boundary (timeout, gateway error, malformed structured_output - all treated the same:
            # vision could not confirm anything, so the deterministic verdict stands unchanged).
            logger.warning(
                "vision_subject_match_failed_soft",
                extra={"candidate_id": candidate.candidate_id, "error": type(exc).__name__},
            )
            return deterministic

        local_cache[cache_key] = vision_result
        combined = _combine(deterministic, vision_result)
        logger.info(
            "vision_subject_match_result",
            extra={
                "candidate_id": candidate.candidate_id, "deterministic": deterministic.subject_match.value,
                "vision": vision_result.subject_match.value, "combined": combined.subject_match.value,
            },
        )
        return combined

    return _classify
