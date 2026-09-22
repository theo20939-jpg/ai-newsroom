"""INSTAGRAM-AUTOMATIC-EDITORIAL-TRIGGER-1: the real, automatic newsroom-to-Instagram-Telegram
pipeline - submits an ALREADY-COMPLETE, ALREADY-EVIDENCE-GROUNDED real story into the EXISTING
Instagram opportunity/package/QA/delivery chain, reusing every stage verbatim (§5's own explicit
"do NOT copy/paste the manual script into the worker" - this module IS the extracted, reusable
service boundary the manual canary scripts should have been all along).

Eligibility (§2/§3 - no new score invented): a story is submitted for Instagram evaluation ONLY
if `services.editorial_treatment.classify_editorial_treatment()` - the SAME real, already-reviewed
significance/evidence classifier `worker/content_cycle.py` already computes for every NEWS story
today (Phase 23.1H/23.1P) - returns `MAJOR`. This is not a new threshold: it is the existing
"deserves more than baseline editorial treatment" tier, reused as-is. `STANDARD`/`BRIEF`/`SKIP`
stories are never submitted - the majority of real NEWS stories are expected to fall here, exactly
matching the phase brief's own "do NOT interpret 10 NEWS drafts as 10 Instagram packages" warning.

INSTAGRAM PHASE A: the NEWS and PRODUCT worker call sites opt into one pre-generation editorial
decision on the existing general opportunity path. The decision sees brand/account/product truth,
Story Memory discussion signals and recent/in-flight Instagram history, chooses the angle and then
one already-executable format. Direct service callers retain the pre-Phase-A compatibility path
unless they explicitly opt in. A REEL remains gated by `settings.instagram_reel_execution_enabled`
and is never silently downgraded.

Idempotency (§7) remains the EXISTING `instagram_editorial_deliveries` partial-unique identity.
Phase A adds a pre-generation canonical-Story + structured-angle guard across formats; explicit
regeneration versions and explicit canary overrides remain separate and auditable.

The real Creative Director call reuses `gate_gateway`/`gate_prompt_repository` - the SAME real
`LLMGateway`/`PromptRepository` instances `worker/content_main.py` already constructs once at
startup and threads into `run_content_cycle()` for every other real capability call. No second
gateway is constructed anywhere in this module."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any
from uuid import UUID

from PIL import Image
from sqlalchemy import select

from core.config import settings
from database.models.news_event import NewsEvent
from database.models.social_launch_context import SocialLaunchPlatform
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from services.business_context_snapshot_service import get_business_context_snapshot
from services.editorial_treatment import MAJOR, EditorialTreatmentDecision
from services.image_persistence import (
    EditorialImageCandidate,
    get_editorial_image_candidates,
    read_candidate_bytes,
)
from services.instagram_art_validator import validate_instagram_art
from services.instagram_content_opportunity import (
    ContentOpportunity,
    OpportunitySourceType,
)
from services.instagram_content_package import build_instagram_content_package
from services.instagram_media_first import GENERATED_SUBJECT_KEY, MediaFirstContractError, UnsupportedClickbaitError
from services.instagram_meta_language_guard import MetaLanguageLeakError
from services.kage_voice import KageVoiceUnavailableError, load_kage_voice
from services.instagram_creative_director import (
    AudienceFacingCopyError,
    CAROUSEL_PROMPT_VERSION,
    MEDIA_FIRST_CAROUSEL_VERSIONS,
    CreativeContractError,
    CreativeDirectorInput,
    CreativeDirectorUnavailableError,
    CreativeFactSafetyError,
    CreativeLanguageError,
    InstagramEditorialDecisionInput,
    UngroundedEvidenceError,
    UngroundedTrendClaimError,
    generate_editorial_decision,
)
from services.instagram_b4_observability import build_b4_observability
from services.instagram_creative_media import (
    ResolvedSlideAsset,
    derive_image_identity,
    execute_instagram_creative_media,
)
from services.instagram_creative_plan_service import (
    build_carousel_fatigue_note,
    fetch_recent_carousel_fingerprints,
    record_creative_draft,
)
from services.instagram_recap_bundle import InstagramRecapBundle
from services.instagram_director_context import (
    load_instagram_director_context,
    render_account_context,
    render_product_truth,
)
from services.instagram_editorial_delivery_state import (
    InstagramEditorialDeliveryService,
    InstagramEditorialDuplicateDecision,
    check_instagram_editorial_duplicate,
    compute_package_identity,
    load_recent_instagram_editorial_history,
)
from services.instagram_editorial_gate import evaluate_instagram_editorial_gate
from services.instagram_editorial_package_snapshot import build_package_snapshot
from services.instagram_editorial_regeneration import build_default_regenerator
from services.instagram_format_director import (
    ContentFormat,
    FormatDecision,
    evaluate_format_shadow,
)
from services.instagram_objective_selection import recommend_objective
from services.instagram_platform_renderer import (
    render_instagram_carousel,
    render_instagram_feed_image,
    render_instagram_reel_cover,
    resolve_recap_story_assets,
)
from services.instagram_reel_script_readiness import compute_reel_script_readiness
from services.instagram_shadow_pipeline import ShadowPlanResult
from services.instagram_telegram_delivery import deliver_instagram_package
from services.instagram_telegram_package_presenter import (
    present_carousel,
    present_reel,
    present_single,
)
from services.instagram_trend_radar import (
    TrendSignal,
    TrendSignalProvenance,
    TrendSignalType,
)
from services.social_launch_context_service import get_current_context
from services.story_memory import (
    compute_entity_evidence,
    extract_story_signature,
    score_candidate,
)
from services.video_discovery_persistence import (
    get_video_candidates_for_event,
    select_best_video_candidate,
)

logger = logging.getLogger(__name__)

_ELIGIBLE_TREATMENTS = (MAJOR,)
"""§3: the ONLY selection criterion - the existing MAJOR tier, never a new invented cutoff."""


@dataclass(frozen=True)
class InstagramTriggerCandidateOutcome:
    event_id: str
    accepted: bool
    reason: str
    gate_decision: str | None = None
    delivery_sent: bool = False
    delivery_reason: str | None = None
    delivery_id: str | None = None
    opportunity_id: str | None = None
    opportunity_type: str | None = None
    trend_signal: str | None = None
    trend_signal_type: str | None = None
    trend_signal_provenance: str | None = None
    why_now: str | None = None
    audience_value: str | None = None
    angle: str | None = None
    chosen_format: str | None = None
    product_connection: str | None = None
    duplication_decision: str | None = None
    recent_history_inputs: list[str] = field(default_factory=list)
    output_language: str = "ru"


@dataclass(frozen=True)
class InstagramTriggerCycleReport:
    """§17 observability - every counter the phase brief names, nothing more (no secrets/prompt
    contents)."""

    stories_evaluated: int = 0
    opportunities_accepted: int = 0
    opportunities_rejected: int = 0
    packages_ready: int = 0
    packages_hold: int = 0
    packages_block: int = 0
    packages_delivered: int = 0
    duplicate_submissions_suppressed: int = 0
    duplicate_deliveries_suppressed: int = 0
    candidates: list[InstagramTriggerCandidateOutcome] = field(default_factory=list)

    def as_log_extra(self) -> dict[str, int]:
        return {
            "stories_evaluated": self.stories_evaluated, "opportunities_accepted": self.opportunities_accepted,
            "opportunities_rejected": self.opportunities_rejected, "packages_ready": self.packages_ready,
            "packages_hold": self.packages_hold, "packages_block": self.packages_block,
            "packages_delivered": self.packages_delivered,
            "duplicate_submissions_suppressed": self.duplicate_submissions_suppressed,
            "duplicate_deliveries_suppressed": self.duplicate_deliveries_suppressed,
        }



def _is_external_news(opportunity: ContentOpportunity) -> bool:
    return (
        opportunity.source_type is OpportunitySourceType.NEWS
        and opportunity.story_id is not None
        and opportunity.product_id is None
        and opportunity.campaign_id is None
    )


@dataclass(frozen=True)
class _PhaseAEditorialPlan:
    opportunity: ContentOpportunity
    format_decision: FormatDecision
    duplicate: InstagramEditorialDuplicateDecision
    brand_context: str
    account_context: str
    product_context: str
    recent_content_context: str


async def _resolve_canonical_story_id(session: Any, event_id: str) -> str:
    try:
        event_uuid = UUID(event_id)
    except ValueError:
        return event_id
    link = await session.get(NewsEventStoryLink, event_uuid)
    return str(link.story_id) if link is not None else event_id


_STORY_TREND_COHERENCE_FLOOR = 0.35
_STORY_TREND_CORROBORATING_TITLE_FLOOR = 0.55
_STORY_TREND_NON_IDENTITY_ENTITIES = {
    "what", "why", "how", "who", "where", "when",
    "что", "почему", "как", "кто", "где", "когда",
}


def _story_memory_titles_are_coherent(
    *, source_event: NewsEvent, story: Story, candidate_title: str,
) -> bool:
    """Reuse Story Memory's current identity score before treating a stored cluster as a trend.

    Historical Story links can outlive matcher calibration improvements. Re-scoring each row
    prevents a cluster joined only by generic headline grammar (for example, unrelated headlines
    beginning with "What" or "Why") from becoming Instagram trend evidence. The 0.35 floor is
    Story Memory's existing low-evidence boundary: appropriate for topic-level discussion
    coherence, while the stricter 0.65 boundary remains reserved for same-event identity. It must
    also carry a distinctive shared entity (excluding the closed question-word class that caused
    the observed false clusters) or Story Memory's existing 0.55 corroborating-title overlap, so
    category/topic bonuses and generic grammar can never carry the decision alone.
    """
    signature = extract_story_signature(
        source_event.title, source_event.category, aggressive_entities=True,
    )
    candidate_signature = extract_story_signature(
        candidate_title, source_event.category, aggressive_entities=True,
    )
    entity_evidence = compute_entity_evidence(
        signature.entities, candidate_signature.entities,
    )
    combined, _entity_overlap, title_overlap = score_candidate(
        source_event.title,
        signature,
        source_event.category,
        candidate_title,
        story,
    )
    shared_specific_entities = set(entity_evidence.shared_distinctive) - _STORY_TREND_NON_IDENTITY_ENTITIES
    has_specific_identity = bool(shared_specific_entities)
    has_corroborating_wording = title_overlap >= _STORY_TREND_CORROBORATING_TITLE_FLOOR
    return combined >= _STORY_TREND_COHERENCE_FLOOR and (
        has_specific_identity or has_corroborating_wording
    )


async def _story_memory_trend_signal(
    session: Any, *, canonical_story_id: str, source_event_id: str,
) -> TrendSignal | None:
    """Normalize the existing Story Memory cluster into bounded discussion momentum.

    The evidence gate (>=3 events and >=2 sources in 48h) is the same threshold used by the
    repository's previous autonomous trend canary. No crawler, table or parallel ranking service
    is introduced. Story Memory can currently prove a discussion/topic trend only; it cannot
    honestly claim a meme, audio or format trend.
    """
    try:
        story_uuid = UUID(canonical_story_id)
        event_uuid = UUID(source_event_id)
    except ValueError:
        return None
    source_event = await session.get(NewsEvent, event_uuid)
    story = await session.get(Story, story_uuid)
    if source_event is None or story is None:
        return None
    cutoff = datetime.now(UTC) - timedelta(hours=48)
    stmt = (
        select(NewsEvent.id, NewsEvent.source_id, NewsEvent.title, NewsEvent.collected_at)
        .join(NewsEventStoryLink, NewsEventStoryLink.news_event_id == NewsEvent.id)
        .where(NewsEventStoryLink.story_id == story_uuid, NewsEvent.collected_at >= cutoff)
        .order_by(NewsEvent.collected_at.desc())
        .limit(20)
    )
    rows = (await session.execute(stmt)).all()
    coherent_rows = [
        row for row in rows
        if row.id == event_uuid or _story_memory_titles_are_coherent(
            source_event=source_event, story=story, candidate_title=str(row.title),
        )
    ]
    distinct_sources = {str(row.source_id) for row in coherent_rows}
    if len(coherent_rows) < 3 or len(distinct_sources) < 2:
        return None
    evidence = [str(row.title) for row in coherent_rows[:5]]
    return TrendSignal(
        signal_type=TrendSignalType.DISCUSSION_MOMENTUM,
        provenance=TrendSignalProvenance.STORY_MEMORY,
        topic=story.title,
        evidence=evidence,
        freshness_hours=48,
        confidence=min(0.9, 0.5 + 0.05 * len(distinct_sources)),
        relevance=(
            f"coherent multi-source discussion; excluded_incoherent={len(rows) - len(coherent_rows)}"
        ),
        event_count=len(coherent_rows),
        source_count=len(distinct_sources),
    )


async def _story_memory_trend_context(
    session: Any, *, canonical_story_id: str, source_event_id: str,
) -> str:
    """Compatibility renderer for diagnostics; production uses the structured signal."""
    signal = await _story_memory_trend_signal(
        session, canonical_story_id=canonical_story_id, source_event_id=source_event_id,
    )
    return signal.to_director_context() if signal is not None else ""


def _recent_history_context(history: list[Any]) -> tuple[str, list[str]]:
    if not history:
        return "No recent or in-flight Instagram content.", []
    lines: list[str] = []
    compact: list[str] = []
    for item in history[:12]:
        angle = item.angle or item.caption[:180]
        line = (
            f"{item.created_at.date()} | {item.state} | {item.content_format} | "
            f"topic={item.topic or '(legacy unknown)'} | purpose={item.purpose or '(legacy unknown)'} | "
            f"origin={item.origin or '(legacy unknown)'} | angle={angle or '(unknown)'}"
        )
        lines.append(line)
        compact.append(f"{item.content_format}:{item.topic or angle[:60]}")
    return "\n".join(lines), compact


async def _build_phase_a_editorial_plan(
    session: Any, *, opportunity: ContentOpportunity, source_summary: str, trend_context: str,
    trend_signal: TrendSignal | None,
    gateway: Any, prompt_repository: Any, allow_duplicate_canary: bool,
) -> _PhaseAEditorialPlan:
    now = datetime.now(UTC)
    snapshot = await get_business_context_snapshot(session, now=now)
    launch_context = await get_current_context(session, SocialLaunchPlatform.INSTAGRAM)
    history = await load_recent_instagram_editorial_history(session, now=now)
    recent_note, _compact = _recent_history_context(history)
    brand_context = load_instagram_director_context()
    account_context = render_account_context(launch_context)
    product_context = render_product_truth(snapshot)
    decision, _call = await generate_editorial_decision(
        gateway,
        prompt_repository,
        decision_input=InstagramEditorialDecisionInput(
            source_type=opportunity.source_type.value,
            source_summary=source_summary,
            allowed_evidence=list(opportunity.evidence),
            brand_context=brand_context,
            account_context=account_context,
            product_context=product_context,
            trend_context=trend_context,
            trend_signal_type=trend_signal.signal_type.value if trend_signal else None,
            trend_signal_provenance=trend_signal.provenance.value if trend_signal else None,
            trend_signal_is_platform_native=trend_signal.is_platform_native if trend_signal else False,
            recent_content_context=recent_note,
        ),
    )
    if not opportunity.product_mention_allowed and decision.product_connection:
        raise CreativeFactSafetyError(
            "Director proposed a NINJA product connection where product_mention_allowed=False"
        )
    duplicate = await check_instagram_editorial_duplicate(
        session,
        source_story_id=opportunity.story_id,
        angle=decision.angle,
        angle_intent=decision.angle_intent,
        allow_duplicate_canary=allow_duplicate_canary,
        now=now,
    )
    decision_payload = decision.model_dump()
    decision_payload.update(
        {
            "trend_signal_type": trend_signal.signal_type.value if trend_signal else None,
            "trend_signal_provenance": trend_signal.provenance.value if trend_signal else None,
            "duplication_decision": "BLOCK" if duplicate.blocked else "ALLOW",
            "duplication_rationale": duplicate.reason,
            "recent_history_count": len(duplicate.recent_history),
            "canary_override_used": duplicate.canary_override_used,
            "output_language": "ru",
        }
    )
    planned_opportunity = replace(opportunity, editorial_decision=decision_payload)
    chosen_format = ContentFormat(decision.recommended_format)
    alternatives = [fmt for fmt in ContentFormat if fmt is not chosen_format]
    format_decision = FormatDecision(
        recommended_format=chosen_format,
        alternatives=alternatives,
        why=decision.format_reason,
        expected_role={
            ContentFormat.CAROUSEL: "education/reference",
            ContentFormat.REEL: "reach/reaction/storytelling",
            ContentFormat.SINGLE: "hero/breaking/statement",
        }[chosen_format],
        risk="medium" if chosen_format is ContentFormat.REEL else "low",
        confidence=max(0.5, opportunity.confidence),
        warnings=[],
    )
    return _PhaseAEditorialPlan(
        opportunity=planned_opportunity,
        format_decision=format_decision,
        duplicate=duplicate,
        brand_context=brand_context,
        account_context=account_context,
        product_context=product_context,
        recent_content_context=recent_note,
    )


def _decision_outcome(
    *, opportunity: ContentOpportunity, reason: str, trend_signal: str, duplicate: InstagramEditorialDuplicateDecision,
    accepted: bool, gate_decision: str | None = None, delivery_sent: bool = False,
    delivery_reason: str | None = None, delivery_id: str | None = None,
) -> InstagramTriggerCandidateOutcome:
    decision = opportunity.editorial_decision
    _note, compact_history = _recent_history_context(duplicate.recent_history)
    return InstagramTriggerCandidateOutcome(
        event_id=opportunity.id, accepted=accepted, reason=reason, gate_decision=gate_decision,
        delivery_sent=delivery_sent, delivery_reason=delivery_reason, delivery_id=delivery_id,
        opportunity_id=opportunity.id, opportunity_type=decision.get("opportunity_type"),
        trend_signal=trend_signal or None, why_now=decision.get("why_now"),
        trend_signal_type=decision.get("trend_signal_type"),
        trend_signal_provenance=decision.get("trend_signal_provenance"),
        audience_value=decision.get("audience_value"), angle=decision.get("angle"),
        chosen_format=decision.get("recommended_format"), product_connection=decision.get("product_connection"),
        duplication_decision=decision.get("duplication_rationale"), recent_history_inputs=compact_history,
        output_language="ru",
    )


async def _resolve_single_source_image(
    session: Any, story_id: str | None,
) -> tuple[Image.Image | None, EditorialImageCandidate | None, int, int]:
    if not story_id:
        return None, None, 0, 0
    try:
        event_id = UUID(story_id)
    except ValueError:
        return None, None, 0, 0
    candidates = await get_editorial_image_candidates(session, news_event_id=event_id, limit=10)
    for candidate in candidates:
        if candidate.is_expired:
            continue
        data = read_candidate_bytes(candidate)
        if not data:
            continue
        try:
            with Image.open(BytesIO(data)) as check:
                check.verify()
            with Image.open(BytesIO(data)) as decoded:
                if min(decoded.size) < 256:
                    continue
                source_image = decoded.convert("RGB")
        except (OSError, ValueError):
            logger.warning("instagram_source_image_decode_failed", extra={"media_candidate_id": str(candidate.id)})
            continue
        return source_image, candidate, len(candidates), len(data)
    return None, None, len(candidates), 0

_MEDIA_COMPOSITIONS = (None, "contained_media", "full_bleed_media", "collage", "screenshot_ui")


def _visual_dna_context() -> str:
    """Phase B.5.1: the ACTIVE Visual DNA is v2 (sample-by-sample family library + global invariants), loaded from
    docs/references/instagram/visual_dna/v2.json - analysed once, never re-sent as an image. v1 stays on disk for history only."""
    from services.instagram_visual_dna_v2 import load_visual_dna_v2, render_visual_dna_v2_context

    dna = load_visual_dna_v2()
    return render_visual_dna_v2_context(dna) if dna is not None else ""


def _visual_dna_version() -> str:
    from services.instagram_visual_dna_v2 import load_visual_dna_v2

    dna = load_visual_dna_v2()
    return dna.version if dna is not None else ""


_PHOTO_FUNCTIONS = ("hero", "detail", "evidence_photo", None, "none")
_NON_PHOTO_FUNCTIONS = ("ui_screenshot", "result", "before_after", "concept")


_GENERATED_OPTION_NOTE = (
    "GENERATED media is a first-class option for ANY slide: set media_source 'generated', write a concrete generation_brief (what the picture SHOWS) and let the layout use a "
    "media region with content_ref 'generated'. Every slide needs a meaningful visual: a suitable real subject, a GENERATED contextual visual, or a substantive graphic - "
    "never a plain surface with text."
)


def _carousel_source_images(*, source_image: Any, recap_bundle: InstagramRecapBundle | None) -> list[tuple[str, Any]]:
    """(subject key, decoded image) for every real source image of this post."""
    images: list[tuple[str, Any]] = []
    if recap_bundle is not None:
        for story in recap_bundle.stories:
            if story.image_bytes:
                try:
                    with Image.open(BytesIO(story.image_bytes)) as decoded:
                        images.append((story.key, decoded.copy()))
                except (OSError, ValueError):
                    continue
    elif source_image is not None:
        images.append(("source", source_image))
    return images


async def _vision_unsuitable_subjects(*, gateway: Any, prompt_repository: Any, source_image: Any,
                                      recap_bundle: InstagramRecapBundle | None) -> frozenset[str]:
    """Keys of source images that passed the deterministic flat-card test but that the narrow vision check
    (services.instagram_source_suitability) reads as a text / article / promo / interface card. Only this post's candidates for primary
    media are checked; an unknown verdict (error) keeps the deterministic one."""
    from services.instagram_asset_profile import profile_asset
    from services.instagram_source_suitability import check_primary_suitability

    candidates = []
    for key, image in _carousel_source_images(source_image=source_image, recap_bundle=recap_bundle):
        try:
            if profile_asset(image.convert("RGBA" if image.mode == "RGBA" else "RGB"), subject_key=key).suitable_for_final_visual:
                candidates.append((key, image))
        except (OSError, ValueError):
            continue
    verdicts = await check_primary_suitability(gateway, prompt_repository, candidates)
    return frozenset(k for k, v in verdicts.items() if v.suitable is False)


def _carousel_media_subjects(*, source_image: Any, recap_bundle: InstagramRecapBundle | None,
                             vision_unsuitable: frozenset[str] = frozenset()) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(listed real subject keys, the subset that is NOT suitable as a final visual). Deterministic, from the same asset profile the note
    uses, plus any key the narrow vision check found unsuitable."""
    from services.instagram_asset_profile import profile_asset

    available: list[str] = []
    unsuitable: list[str] = []

    def add(key: str, image: Any) -> None:
        available.append(key)
        if key in vision_unsuitable:
            unsuitable.append(key)
            return
        try:
            if not profile_asset(image.convert("RGBA" if image.mode == "RGBA" else "RGB"), subject_key=key).suitable_for_final_visual:
                unsuitable.append(key)
        except (OSError, ValueError):
            unsuitable.append(key)

    if recap_bundle is not None:
        for story in recap_bundle.stories:
            if story.image_bytes:
                try:
                    with Image.open(BytesIO(story.image_bytes)) as decoded:
                        add(story.key, decoded.copy())
                except (OSError, ValueError):
                    continue
    elif source_image is not None:
        add("source", source_image)
    return tuple(available), tuple(unsuitable)


def _carousel_media_note(*, source_image: Any, recap_bundle: InstagramRecapBundle | None, media_first: bool = False,
                         vision_unsuitable: frozenset[str] = frozenset()) -> str:
    """Real media availability, told to the Creative Director so it plans against what exists. Phase B.5.1: every real image
    carries a deterministic PROFILE (calm text zones per crop, uniform-ground object suitability) so the model can only plan
    visual families the media honestly supports."""
    from services.instagram_asset_profile import profile_asset, render_profile_lines

    if recap_bundle is not None:
        with_image = [s for s in recap_bundle.stories if s.image_bytes]
        lines = []
        for story in recap_bundle.stories:
            if not story.image_bytes:
                lines.append(
                    f"{story.key}: SOURCE_AVAILABLE: no. Plan a GENERATED contextual visual for this story (media_subject '{story.key}', media_source 'generated')."
                    if media_first else
                    f"{story.key}: NO image for this story - use a graphic story card (dark_type_number_statement, interface_cards or light_utility_editorial)"
                )
                continue
            try:
                with Image.open(BytesIO(story.image_bytes)) as decoded:
                    profile = profile_asset(decoded.convert("RGBA" if decoded.mode == "RGBA" else "RGB"), subject_key=story.key)
                lines.append(render_profile_lines(profile, pool_size=len(with_image), allowed_functions="hero, detail, evidence_photo", include_suitability=media_first,
                                                  suitable_override=False if story.key in vision_unsuitable else None))
            except (OSError, ValueError):
                lines.append(f"{story.key}: image could not be profiled - treat as NO usable image")
        return "\n".join(lines + ([_GENERATED_OPTION_NOTE] if media_first else []))
    if source_image is not None:
        return (
            render_profile_lines(profile_asset(source_image, subject_key="source"), pool_size=1, allowed_functions="hero, detail, evidence_photo", include_suitability=media_first,
                                 suitable_override=False if "source" in vision_unsuitable else None)
            + ("\n" + _GENERATED_OPTION_NOTE if media_first else "")
            + "\nThe image may be used on several slides or several times on one slide with different crops. It is NOT a screenshot, a result image, "
              "a before/after or a concept visual: plan graphics for those."
        )
    if media_first:
        return "SOURCE_AVAILABLE: no - no real image is available for this post. " + _GENERATED_OPTION_NOTE
    return ("no real image is available for this post: plan with the media-free families (dark_type_number_statement, interface_cards, "
            "light_utility_editorial); media regions cannot be used and no image may be assumed.")


def _layout_media_refs(slide: Any) -> list[str]:
    layout = getattr(slide, "layout", None)
    return [r.content_ref for r in layout.regions if r.kind == "media" and r.content_ref] if layout is not None else []


def _resolve_carousel_slide_assets(
    carousel: Any, *, recap_bundle: InstagramRecapBundle | None, source_image: Any, source_ref: str | None,
) -> tuple[dict[int, ResolvedSlideAsset], list[str], Any, dict[str, tuple[Any, str]]]:
    """Resolver-owned media. Returns (per-slide primary assets, deliberate-fallback subjects, carousel,
    subject_assets). `subject_assets` maps each LISTED subject key to (image, content identity): NEWS_RECAP
    story keys, or the post's single real 'source' asset. A declarative media region can only consume a
    listed key; a slide whose function is a screenshot/result/before-after/concept never receives the
    'source' photo (graphic instead). Nothing is ever a shared unrelated image or a fabricated identity."""
    slides = carousel.slides
    assets: dict[int, ResolvedSlideAsset] = {}
    subject_assets: dict[str, tuple[Any, str]] = {}
    story_images: dict[str, Any] = {}
    story_refs: dict[str, str] = {}
    if recap_bundle is not None:
        story_images, identities = resolve_recap_story_assets(
            {i: story.key for i, story in enumerate(recap_bundle.stories)}, recap_bundle.available_assets,
        )
        for i, story in enumerate(recap_bundle.stories):
            if i in story_images:
                subject_assets[story.key] = (story_images[i], identities[i])
                story_refs[story.key] = recap_bundle.refs.get(story.key, story.key)
    elif source_image is not None:
        subject_assets["source"] = (source_image, derive_image_identity(source_image))
        story_refs["source"] = source_ref or "source"

    for i, sl in enumerate(slides):
        if getattr(sl, "layout", None) is not None:
            usable = [
                ref for ref in _layout_media_refs(sl)
                if ref in subject_assets and not (ref == "source" and sl.media_function in _NON_PHOTO_FUNCTIONS)
            ]
            if usable:
                image, identity = subject_assets[usable[0]]
                assets[i] = ResolvedSlideAsset(image, story_refs.get(usable[0], usable[0]), identity)
        elif recap_bundle is not None:
            key = sl.media_subject
            if key in subject_assets:
                image, identity = subject_assets[key]
                assets[i] = ResolvedSlideAsset(image, story_refs.get(key, key), identity)
        elif source_image is not None and sl.composition in _MEDIA_COMPOSITIONS and (sl.media_subject or "source") == "source":
            image, identity = subject_assets["source"]
            assets[i] = ResolvedSlideAsset(image, story_refs["source"], identity)

    unmatched = [i for i, sl in enumerate(slides) if sl.must_match_story and i not in assets]
    fallback: list[str] = []
    if unmatched:
        fallback = sorted({slides[i].media_subject or f"slide_{i}" for i in unmatched})
        carousel = carousel.model_copy(update={"slides": [
            sl.model_copy(update={"must_match_story": False}) if i in unmatched else sl
            for i, sl in enumerate(slides)
        ]})
    return assets, fallback, carousel, subject_assets


async def evaluate_and_submit_instagram_candidate(
    session: Any, bot: Any, *, event_id: str, event_title: str, treatment: EditorialTreatmentDecision,
    research_facts: list[str], gateway: Any, prompt_repository: Any, source_url: str | None = None,
    phase_a_enabled: bool = False,
) -> InstagramTriggerCandidateOutcome:
    """The one entry point per story. Never raises - a Creative Director failure (rate limit,
    ungrounded evidence, provider error) degrades to a rejected/failed outcome for THIS story only,
    never crashing the caller's cycle (§8 crash safety - a per-story failure must not take down the
    whole scan)."""
    if treatment.treatment not in _ELIGIBLE_TREATMENTS:
        return InstagramTriggerCandidateOutcome(event_id=event_id, accepted=False, reason=f"treatment={treatment.treatment}")

    canonical_story_id = await _resolve_canonical_story_id(session, event_id) if phase_a_enabled else event_id
    normalized_trend_signal = (
        await _story_memory_trend_signal(
            session, canonical_story_id=canonical_story_id, source_event_id=event_id,
        )
        if phase_a_enabled else None
    )
    trend_context = normalized_trend_signal.to_director_context() if normalized_trend_signal else ""
    opportunity = ContentOpportunity(
        id=event_id, source_type=OpportunitySourceType.NEWS, story_id=canonical_story_id,
        news_value=1.0, audience_relevance=0.5, product_mention_allowed=False,
        evidence=list(research_facts), confidence=0.5,
    )
    return await evaluate_and_submit_instagram_opportunity(
        session, bot, opportunity=opportunity, opportunity_summary=event_title,
        gateway=gateway, prompt_repository=prompt_repository, source_url=source_url,
        source_event_id=event_id, trend_context=trend_context, trend_signal=normalized_trend_signal,
        phase_a_enabled=phase_a_enabled,
    )

# ---------------------------------------------------------------------------
# INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2: the general entrypoint - PRODUCT (this phase) and, in
# later phases, NEWS_DIGEST/TREND all flow through HERE via `generate_growth_strategy()`'s already-
# ranked output, instead of each lane hand-rolling its own Creative Director call the way the NEWS
# path above still does. `evaluate_and_submit_instagram_candidate()` above is left completely
# untouched (byte-identical behavior, zero risk to the live NEWS lane or its 14+3 existing tests) -
# this is a NEW, general SIBLING, not a replacement, matching the run brief's own "generalize the
# existing trigger... do NOT build another trigger" instruction (this module remains the one and
# only Instagram automatic-trigger service; a second entrypoint inside it is not a second trigger).
# ---------------------------------------------------------------------------


async def evaluate_and_submit_instagram_opportunity(
    session: Any, bot: Any, *, opportunity: ContentOpportunity, opportunity_summary: str,
    gateway: Any, prompt_repository: Any, source_url: str | None = None,
    source_event_id: str | None = None, trend_context: str = "",
    trend_signal: TrendSignal | None = None, allow_duplicate_canary: bool = False,
    phase_a_enabled: bool = False, recap_bundle: InstagramRecapBundle | None = None,
) -> InstagramTriggerCandidateOutcome:
    """Takes an ALREADY-BUILT, ALREADY-RANKED `ContentOpportunity` (any `source_type` - selection/
    ranking is `generate_growth_strategy()`'s job, called by whichever lane constructs the
    opportunity, never this function's) and runs it through the SAME real format/creative/render/
    QA/delivery chain the NEWS path uses - `opportunity.evidence`/`.product_mention_allowed`/
    `.allowed_claims`/`.restricted_claims` (already real, resolved fields on `ContentOpportunity`)
    are read directly, never a parallel `research_facts`-style parameter - one canonical evidence
    source per opportunity, regardless of lane. Never raises (mirrors
    `evaluate_and_submit_instagram_candidate()`'s own crash-safety contract exactly)."""
    if recap_bundle is not None:
        # Phase B.4.2: NEWS_RECAP - evidence is the bundle's own per-story evidence.
        opportunity = replace(opportunity, evidence=recap_bundle.evidence)
    has_multi_step_narrative = len(opportunity.evidence) > 1
    has_video_asset = False
    if _is_external_news(opportunity) and (source_event_id or opportunity.story_id):
        try:
            video_candidates = await get_video_candidates_for_event(
                session, UUID(source_event_id or opportunity.story_id or "")
            )
            has_video_asset = select_best_video_candidate(video_candidates) is not None
        except ValueError:
            pass
    recommendation = recommend_objective(opportunity=opportunity, has_multi_step_narrative=has_multi_step_narrative)
    if phase_a_enabled:
        try:
            phase_a_plan = await _build_phase_a_editorial_plan(
                session, opportunity=opportunity, source_summary=opportunity_summary,
                trend_context=trend_context, trend_signal=trend_signal,
                gateway=gateway, prompt_repository=prompt_repository,
                allow_duplicate_canary=allow_duplicate_canary,
            )
        except (
            CreativeDirectorUnavailableError, UngroundedEvidenceError, CreativeFactSafetyError,
            CreativeLanguageError, AudienceFacingCopyError, UngroundedTrendClaimError,
        ) as exc:
            logger.warning(
                "instagram_editorial_decision_failed",
                extra={"opportunity_id": opportunity.id, "error": type(exc).__name__},
            )
            return InstagramTriggerCandidateOutcome(
                event_id=opportunity.id, accepted=False, reason=f"editorial_decision_failed:{type(exc).__name__}",
            )
    else:
        legacy_format = evaluate_format_shadow(
            objective=recommendation.primary_objective, has_video_asset=has_video_asset,
            has_multi_step_narrative=has_multi_step_narrative,
        )
        phase_a_plan = _PhaseAEditorialPlan(
            opportunity=opportunity,
            format_decision=legacy_format,
            duplicate=InstagramEditorialDuplicateDecision(False, "legacy compatibility path"),
            brand_context="",
            account_context="",
            product_context="",
            recent_content_context="",
        )

    opportunity = phase_a_plan.opportunity
    format_decision = phase_a_plan.format_decision
    if recap_bundle is not None and format_decision.recommended_format is not ContentFormat.CAROUSEL:
        format_decision = replace(format_decision, recommended_format=ContentFormat.CAROUSEL)
    if phase_a_plan.duplicate.blocked:
        return _decision_outcome(
            opportunity=opportunity, reason="duplicate_angle_blocked", trend_signal=trend_context,
            duplicate=phase_a_plan.duplicate, accepted=False,
        )

    identity = compute_package_identity(source_key=opportunity.id, content_format=format_decision.recommended_format.value)
    delivery_service = InstagramEditorialDeliveryService()
    existing = await delivery_service.find_current(session, package_identity=identity)
    if existing is not None:
        return _decision_outcome(
            opportunity=opportunity, reason="already_submitted", trend_signal=trend_context,
            duplicate=phase_a_plan.duplicate, accepted=True, delivery_id=str(existing.id),
        )

    # CONTROLLED ROLLOUT: a REEL decision is deferred - never silently downgraded to SINGLE -
    # while settings.instagram_reel_execution_enabled (default False) is off. A bounded canary
    # invocation may pass a locally-true settings override for this one call only; persistent
    # production config is never touched by this check.
    if format_decision.recommended_format is ContentFormat.REEL and not settings.instagram_reel_execution_enabled:
        logger.info(
            "instagram_product_lane_reel_execution_disabled",
            extra={"opportunity_id": opportunity.id, "source_type": opportunity.source_type.value},
        )
        return _decision_outcome(
            opportunity=opportunity, reason="reel_execution_disabled", trend_signal=trend_context,
            duplicate=phase_a_plan.duplicate, accepted=True,
        )

    if recap_bundle is not None:
        # Each recap slide consumes only its own story's asset; there is no shared source image.
        source_image, image_candidate, image_count, read_length = None, None, 0, 0
    else:
        source_image, image_candidate, image_count, read_length = await _resolve_single_source_image(
            session, source_event_id or opportunity.story_id
        )
    if source_image is not None and image_candidate is not None:
        logger.info("instagram_source_image_selected", extra={
            "opportunity_id": opportunity.id, "image_candidate_count": image_count,
            "media_candidate_id": str(image_candidate.id), "read_byte_length": read_length,
        })

    fatigue_note = ""
    if format_decision.recommended_format is ContentFormat.CAROUSEL:
        try:
            fatigue_note = build_carousel_fatigue_note(await fetch_recent_carousel_fingerprints(session))
        except Exception:
            logger.warning("instagram_fatigue_history_unavailable", extra={"opportunity_id": opportunity.id})

    media_first = format_decision.recommended_format is ContentFormat.CAROUSEL and CAROUSEL_PROMPT_VERSION in MEDIA_FIRST_CAROUSEL_VERSIONS
    vision_unsuitable: frozenset[str] = frozenset()
    if media_first:
        vision_unsuitable = await _vision_unsuitable_subjects(gateway=gateway, prompt_repository=prompt_repository,
                                                              source_image=source_image, recap_bundle=recap_bundle)
    media_subjects = (
        _carousel_media_subjects(source_image=source_image, recap_bundle=recap_bundle, vision_unsuitable=vision_unsuitable)
        if format_decision.recommended_format is ContentFormat.CAROUSEL else ((), ())
    )
    director_input = CreativeDirectorInput(
        fatigue_note=fatigue_note,
        is_recap_bundle=recap_bundle is not None,
        recap_subjects=recap_bundle.subjects if recap_bundle is not None else [],
        objective=recommendation.primary_objective.value, format=format_decision.recommended_format.value,
        opportunity_summary=opportunity_summary, allowed_evidence=list(opportunity.evidence),
        approved_claims=list(opportunity.allowed_claims), restricted_claims=list(opportunity.restricted_claims),
        product_mention_allowed=opportunity.product_mention_allowed,
        external_news_entities_allowed=_is_external_news(opportunity),
        locale="ru" if phase_a_enabled else "", brand_context=phase_a_plan.brand_context,
        account_context=phase_a_plan.account_context, product_context=phase_a_plan.product_context,
        recent_content_context=phase_a_plan.recent_content_context,
        editorial_decision=json.dumps(opportunity.editorial_decision, ensure_ascii=False, sort_keys=True),
        visual_dna_context=_visual_dna_context() if format_decision.recommended_format is ContentFormat.CAROUSEL else "",
        visual_dna_version=_visual_dna_version() if format_decision.recommended_format is ContentFormat.CAROUSEL else "",
        media_note=(
            _carousel_media_note(source_image=source_image, recap_bundle=recap_bundle, media_first=media_first, vision_unsuitable=vision_unsuitable)
            if format_decision.recommended_format is ContentFormat.CAROUSEL else ""
        ),
        media_first=media_first,
        kage_voice_context=load_kage_voice().render_context() if media_first else "",
        available_media_subjects=media_subjects[0],
        unsuitable_media_subjects=media_subjects[1],
    )

    try:
        regenerator = build_default_regenerator(gateway, prompt_repository)
        try:
            creative_outcome = await regenerator(director_input, format_decision.recommended_format)
        except MediaFirstContractError as exc:
            # A recoverable STRUCTURAL miss (e.g. a generated slide that forgot its source_evidence handle) killed the whole post in a
            # real run. The contract itself is unchanged - the model simply gets one more attempt, told exactly what it broke. Fact-safety
            # errors (ungrounded evidence, unsupported claims, clickbait, language) are never retried: those must fail.
            logger.info("instagram_media_first_contract_retry", extra={"opportunity_id": opportunity.id, "error": str(exc)[:200]})
            creative_outcome = await regenerator(
                replace(director_input, contract_retry_note=f"Your previous attempt was rejected: {exc}. Fix exactly that and keep everything else."),
                format_decision.recommended_format,
            )
    except (
        CreativeDirectorUnavailableError, UngroundedEvidenceError, CreativeFactSafetyError,
        CreativeLanguageError, AudienceFacingCopyError, CreativeContractError, MetaLanguageLeakError,
        MediaFirstContractError, UnsupportedClickbaitError, KageVoiceUnavailableError,
    ) as exc:
        logger.warning(
            "instagram_automatic_trigger_creative_director_failed",
            extra={"opportunity_id": opportunity.id, "source_type": opportunity.source_type.value, "error": type(exc).__name__},
        )
        return InstagramTriggerCandidateOutcome(event_id=opportunity.id, accepted=True, reason=f"creative_director_failed:{type(exc).__name__}")
    except Exception:
        logger.exception(
            "instagram_automatic_trigger_unexpected_creative_director_error",
            extra={"opportunity_id": opportunity.id, "source_type": opportunity.source_type.value},
        )
        return InstagramTriggerCandidateOutcome(event_id=opportunity.id, accepted=True, reason="creative_director_failed:unexpected_error")

    single, carousel, reel = creative_outcome.single, creative_outcome.carousel, creative_outcome.reel
    creative = single or carousel or reel
    if creative is None:
        return InstagramTriggerCandidateOutcome(
            event_id=opportunity.id, accepted=True, reason="creative_director_returned_no_creative",
        )
    slide_assets: dict[int, ResolvedSlideAsset] | None = None
    subject_assets: dict[str, Any] = {}
    deliberate_fallback: list[str] = []
    if carousel is not None:
        slide_assets, deliberate_fallback, carousel, subject_assets = _resolve_carousel_slide_assets(
            carousel, recap_bundle=recap_bundle, source_image=source_image,
            source_ref=image_candidate.candidate_id if image_candidate else None,
        )
        creative = carousel
        creative_outcome = replace(creative_outcome, carousel=carousel)
    try:
        creative_media = await execute_instagram_creative_media(
            slide_assets=slide_assets,
            creative=creative,
            source_image=source_image,
            source_ref=image_candidate.candidate_id if image_candidate else None,
            opportunity_summary=opportunity_summary,
            evidence=list(opportunity.evidence),
            content_format=format_decision.recommended_format.value,
            creative_id=identity,
            opportunity_id=opportunity.id,
        )
    except Exception as exc:
        logger.exception("instagram_creative_media_failed", extra={
            "opportunity_id": opportunity.id, "error": type(exc).__name__,
        })
        return InstagramTriggerCandidateOutcome(
            event_id=opportunity.id, accepted=True, reason=f"creative_media_failed:{type(exc).__name__}",
        )
    if creative_media.status not in {
        "source_media", "generated_media", "typographic", "graphic", "media_plan_ready",
    }:
        return InstagramTriggerCandidateOutcome(
            event_id=opportunity.id, accepted=True, reason=creative_media.status,
        )
    concept_summary = (
        single.creative_angle if single is not None
        else reel.hook if reel is not None
        else carousel.hook_slide.slide_copy if carousel is not None else None
    )
    # Script readiness is independent of video-file availability. Unknown/undecided required facts
    # would still make this a concept; this lane supplies only grounded evidence and the generated
    # Reel has already passed the structured hook/scene/script schema. An external mp4 remains an
    # optional, separately disclosed package field and is never fabricated here.
    reel_script_readiness = (
        compute_reel_script_readiness(unresolved_facts=[])
        if format_decision.recommended_format is ContentFormat.REEL else None
    )
    shadow_plan = ShadowPlanResult(
        campaign_name=None, campaign_phase=opportunity.campaign_phase, opportunity_description=opportunity_summary,
        primary_objective=recommendation.primary_objective.value, audience_description="",
        recommended_format=format_decision.recommended_format.value, hook_family=None,
        creative_concept_summary=concept_summary, alternative_format=None,
        alternative_objective=None, product_mention_allowed=opportunity.product_mention_allowed,
        evidence=list(opportunity.evidence), confidence=opportunity.confidence,
    )
    pkg = build_instagram_content_package(
        opportunity=opportunity, format_decision=format_decision, shadow_plan=shadow_plan,
        creative_outcome=creative_outcome, account_key="default", reel_script_readiness=reel_script_readiness,
        source_image_ref=creative_media.media_ref,
        media_candidate_id=(
            str(image_candidate.id)
            if image_candidate and any(
                asset.source_asset_ref is not None for asset in creative_media.assets
            ) else None
        ),
    )
    pkg = replace(pkg, media_plan={
        **pkg.media_plan,
        "media_execution": creative_media.execution_metadata(),
    })
    creative_image = creative_media.image

    try:
        if format_decision.recommended_format is ContentFormat.CAROUSEL:
            renders = render_instagram_carousel(
                pkg, slide_images=creative_media.slide_images(),
                asset_identities=creative_media.slide_asset_identities(),
                subject_assets=subject_assets,
                slide_subject_assets={
                    int(a.asset_key): {GENERATED_SUBJECT_KEY: (a.image, a.asset_identity or derive_image_identity(a.image))}
                    for a in creative_media.assets
                    if a.media_mode.value == "GENERATED" and a.image is not None and a.asset_key.isdigit()
                },
            )
            presentation = present_carousel(pkg, renders, version=1)
        elif format_decision.recommended_format is ContentFormat.REEL:
            renders = [render_instagram_reel_cover(pkg, source_image=creative_image)]
            presentation = present_reel(pkg, renders[0], version=1)
        else:
            renders = [render_instagram_feed_image(pkg, source_image=creative_image)]
            logger.info("instagram_single_creative_media_rendered", extra={
                "opportunity_id": opportunity.id,
                "media_candidate_id": str(image_candidate.id) if image_candidate else None,
                "rendered_byte_length": len(renders[0].image_bytes),
                "source_image_treatment": renders[0].evidence.source_image_treatment,
                "media_strategy": creative_media.media_strategy,
            })
            presentation = present_single(pkg, renders[0], version=1)

    except Exception:
        logger.exception("instagram_opportunity_render_failed", extra={"opportunity_id": opportunity.id})
        return InstagramTriggerCandidateOutcome(event_id=opportunity.id, accepted=True, reason="render_failed")
    art = validate_instagram_art(pkg, renders)
    if carousel is not None:
        observability = build_b4_observability(
            carousel=carousel, prompt_version=CAROUSEL_PROMPT_VERSION, renders=renders, art=art,
            slide_identities=creative_media.slide_asset_identities(),
            deliberate_fallback_subjects=deliberate_fallback,
            model_emitted_archetype=creative_outcome.model_emitted_archetype,
            archetype_correction_required=creative_outcome.archetype_correction_required,
            weak_hook_patterns=list(creative_outcome.weak_hook_patterns),
        )
        pkg = replace(pkg, media_plan={**pkg.media_plan, "b4_observability": observability})
        logger.info("instagram_b4_carousel_observability", extra={
            "opportunity_id": opportunity.id, "content_archetype": observability["content_archetype"],
            "prompt_version": observability["prompt_version"], "slide_count": observability["slide_count"],
            "structured_composition_present": observability["structured_composition_present"],
            "structured_composition_executed": observability["structured_composition_executed"],
            "role_fallback_used": observability["role_fallback_used"],
            "art_validation_passed": observability["art_validation_passed"],
        })
        try:
            await record_creative_draft(
                session, content_opportunity_id=opportunity.id, objective=recommendation.primary_objective.value,
                format="carousel", payload=carousel.model_dump(mode="json"),
                evidence_used=list(carousel.evidence_used),
                ai_capability="instagram_creative_director_carousel",
            )
        except Exception:
            logger.warning("instagram_creative_draft_record_failed", extra={"opportunity_id": opportunity.id})
    gate = evaluate_instagram_editorial_gate(pkg, art)
    snapshot = build_package_snapshot(
        package=pkg, opportunity=opportunity, format_decision=format_decision, shadow_plan=shadow_plan,
        director_input=director_input, previous_creative=(single or carousel or reel), source_url=source_url,
    )

    delivery_outcome = await deliver_instagram_package(
        bot, session, presentation=presentation, gate_decision=gate.decision, package_identity=identity,
        source_story_id=opportunity.story_id, content_format=format_decision.recommended_format.value,
        package_snapshot=snapshot, source_url=source_url, hold_or_block_reason=gate.short_reason or None,
    )
    return _decision_outcome(
        opportunity=opportunity, reason="submitted", trend_signal=trend_context,
        duplicate=phase_a_plan.duplicate, accepted=True, gate_decision=gate.decision.value,
        delivery_sent=delivery_outcome.sent, delivery_reason=delivery_outcome.reason,
        delivery_id=delivery_outcome.delivery_id,
    )
