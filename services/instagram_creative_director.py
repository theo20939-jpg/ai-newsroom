"""INSTAGRAM-GROWTH-3, item 4/5/6/7: Instagram Creative Director SHADOW pipeline - turns a
ContentOpportunity + Growth Strategy + ObjectiveRecommendation + AudienceSegment + FormatDecision +
Hook + Series + evidence into a production-useful creative brief via the existing AI Gateway.

Architecture note (mirrors services/instagram_semantic_matching.py's own, and ultimately
services/business_context_command_parser.py's original precedent): a one-shot
`capabilities/gateway_call.py::call_generate()` call with a synthetic `RuntimeContext` - Instagram
creative shadow-planning has no EditorialTask/Story to bind to, so the full Capability+
CapabilityExecutor+WorkflowRunner machinery would be a disproportionate graft. Unlike semantic
matching (item 1), a Gateway failure here has no sensible deterministic fallback - there is no
simpler algorithm that "generates a creative concept" - so failure is a raised, typed error
(`CreativeDirectorUnavailableError`), never fabricated placeholder content.

CRITICAL fact-safety contract (item 5): Newsroom owns external factual truth, Business Context
owns NINJA product truth - the Creative Director may transform PRESENTATION, it may never invent a
Story fact, invent product functionality, violate a restricted claim, reveal embargoed information,
or override a Founder Directive. Enforced in THREE deterministic, testable ways, all applied
AFTER generation (never trusted to prompt discipline alone):
  1. `assert_evidence_grounded()` - every string in the model's own `evidence_used` output must be
     a member of the caller-supplied `allowed_evidence` list, exact match. A model that asserts a
     "fact" not in that list is rejected outright.
  2. `services.instagram_format_director.validate_package_claims()` (the SAME accepted enforcement
     point every SinglePostPackage/CarouselPackage/ReelPackage already runs through) is re-run
     against every generated text field and `restricted_claims`.
  3. When `product_mention_allowed=False`, `product_name` (if supplied) is folded into the
     restricted-claims check too - a Founder-Directive-blocked or not-yet-public product can never
     be named, exactly as if it were itself a restricted claim.

SOCIAL-INTELLIGENCE-PRELAUNCH-1A §7: `CreativeDirectorInput.launch_context_note` (optional, empty
by default so every existing call site keeps its exact prior prompt text) is the ONLY zero-to-one
wiring this module needs - a plain text briefing line (e.g. "first Instagram post ever; account is
transitioning from X to Y; introduce the new identity, assume zero follower familiarity") that the
caller derives from the real SocialLaunchContext. This module still performs NO Meta publication
and generates NO new video beyond the existing Reel/Carousel/Single contract - it only gets an
honest extra sentence of context for the very first pieces of content."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from capabilities.gateway_call import call_generate
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import (
    ContentPart,
    GenerateRequest,
    LLMGateway,
    Message,
)
from integrations.prompts.protocol import PromptRepository
from schemas.capability import CapabilityCall, RuntimeContext
from schemas.instagram_creative import (
    InstagramCarouselCreative,
    InstagramEditorialDecision,
    InstagramReelCreative,
    InstagramSingleCreative,
)
from services.instagram_format_director import (
    ClaimViolationError,
    validate_package_claims,
)

SINGLE_PROMPT_NAME = "instagram_creative_director_single"
CAROUSEL_PROMPT_NAME = "instagram_creative_director_carousel"
REEL_PROMPT_NAME = "instagram_creative_director_reel"
EDITORIAL_DECISION_PROMPT_NAME = "instagram_editorial_decision"
# INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2/3 ROLLOUT CLOSURE HOTFIX: a real bounded Reel canary
# against the live production OpenAI endpoint surfaced the exact same structured-output contract
# bug the business_context_parser hotfix already diagnosed and fixed - OpenAI's strict
# response_format="json_schema" mode requires every key in `properties` to also appear in
# `required` (an "optional" field is expressed via a nullable type union, never omission). All
# three v1 prompts here had this bug (SINGLE: missing `cta`; CAROUSEL: missing `final_cta`/
# `slides[].source_evidence`; REEL v2: missing nearly every optional field) - confirmed live, not
# guessed, before any of these were bumped.
#
# INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2/3 MINIMAL FIXES: a second real bounded Reel canary (after
# the hotfix above) proved a DIFFERENT prompt<->Pydantic contract mismatch - `objective` passed the
# (undeclared) prompt schema but failed schemas/instagram_creative.py's own `max_length=50`
# Pydantic constraint. Every other undeclared length/numeric constraint across all three schemas
# was proactively fixed in the same pass (see each vN.yaml's own header for the full list) rather
# than surfacing one at a time via repeated failed live canaries. Also added a state-aware
# "confirmed feature:"/"planned feature:" evidence-wording rule to all three (Phase 2/3 PLANNED-
# fact eligibility, services/director_execution_service.py).
#
# Each version bump is its own independently-versioned, schema-shape-only fix; every previous
# version file is left untouched/unused, matching this codebase's own established "never edit a
# shipped prompt version in place" convention.
_SINGLE_PROMPT_VERSION = "6"
_CAROUSEL_PROMPT_VERSION = "6"  # Phase B.4.1: v6 adds the bounded structured art-direction fields
CAROUSEL_PROMPT_VERSION = _CAROUSEL_PROMPT_VERSION
# to the REAL output_schema - v5 stays published/unused, never silently edited in place.
_REEL_PROMPT_VERSION = "7"
_EDITORIAL_DECISION_PROMPT_VERSION = "1"


class CreativeDirectorUnavailableError(Exception):
    """Raised when the Gateway call itself fails - no deterministic fallback exists for creative
    generation; callers must handle this explicitly (e.g. leave the shadow plan without a filled-in
    creative brief), never fabricate placeholder content in its place."""


class UngroundedEvidenceError(ValueError):
    """Raised when the model's own `evidence_used` names something not in the caller's supplied
    evidence set - the Creative Director may transform presentation, it may never invent a fact."""


class CreativeFactSafetyError(Exception):
    """Wraps a ClaimViolationError or product-mention violation raised while validating generated
    creative text - the draft is REJECTED, never silently sanitized."""


class CreativeLanguageError(ValueError):
    """Raised when final audience/editor-facing output is clearly not Russian for a RU account."""


class AudienceFacingCopyError(ValueError):
    """Raised when final copy leaks an internal/service label into audience-facing text."""


class UngroundedTrendClaimError(ValueError):
    """Raised when non-platform evidence is presented as an Instagram-native trend."""


@dataclass(frozen=True)
class InstagramEditorialDecisionInput:
    source_type: str
    source_summary: str
    allowed_evidence: list[str] = field(default_factory=list)
    brand_context: str = ""
    account_context: str = ""
    product_context: str = ""
    trend_context: str = ""
    trend_signal_type: str | None = None
    trend_signal_provenance: str | None = None
    trend_signal_is_platform_native: bool = False
    recent_content_context: str = ""
    executable_formats: list[str] = field(default_factory=lambda: ["single", "carousel", "reel"])
    locale: str = "ru"


@dataclass(frozen=True)
class CreativeDirectorInput:
    objective: str
    format: str
    opportunity_summary: str
    allowed_evidence: list[str] = field(default_factory=list)
    audience_summary: str = ""
    hook_family: str | None = None
    campaign_theme: str = ""
    series_context: str = ""
    fatigue_note: str = ""
    approved_claims: list[str] = field(default_factory=list)
    restricted_claims: list[str] = field(default_factory=list)
    product_mention_allowed: bool = False
    # External NEWS names are independent of permission to reveal an internal NINJA product.
    external_news_entities_allowed: bool = False
    product_name: str | None = None
    launch_context_note: str = ""
    # DIRECTOR-CONTROL-PLANE-1A §13: mirrors `launch_context_note`'s own established zero-to-one
    # wiring - a plain caller-derived text line from the real InstagramFeedContext (services/
    # instagram_feed_context.py), e.g. "account not yet connected; no first-party feed evidence" or
    # "recent feed dominated by Reels; a Carousel may stand out." Empty by default so every
    # pre-existing call site keeps its exact prior prompt text.
    feed_context_note: str = ""
    # INSTAGRAM-CONTENT-STRATEGY-V2 Phase 3: TREND-origin Reels only - `None` by default so every
    # pre-existing call site (SINGLE/CAROUSEL, and every existing REEL caller) keeps its exact
    # prior prompt text. `trend_mechanic` names the detected spreading format/mechanic (e.g. "POV
    # starter pack"); `trend_spread_reason` is why it's spreading - both feed the REEL prompt's own
    # instruction to produce an ORIGINAL NINJA adaptation, never a copy.
    trend_mechanic: str | None = None
    trend_spread_reason: str | None = None
    # INSTAGRAM PHASE A: explicit locale and the Director decision/context that preceded format-
    # specific generation. Defaults preserve every stored/pre-existing call site.
    locale: str = ""
    brand_context: str = ""
    account_context: str = ""
    product_context: str = ""
    recent_content_context: str = ""
    editorial_decision: str = ""
    # Phase B.4.2: NEWS_RECAP bundle. `recap_subjects` are the resolver-known story keys the model
    # must use verbatim as a slide's `media_subject`; empty (default) for every non-recap call, so
    # every pre-existing prompt text stays byte-identical.
    is_recap_bundle: bool = False
    recap_subjects: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CreativeGenerationOutcome:
    """Wraps a validated schema instance with the raw Gateway call, so a caller can persist both
    the content (services/instagram_creative_plan_service.py) and the cost accounting
    (services/instagram_ai_cost.py) without re-deriving either."""

    single: InstagramSingleCreative | None = None
    carousel: InstagramCarouselCreative | None = None
    reel: InstagramReelCreative | None = None
    call: CapabilityCall | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _without_prompt_bullet(value: str) -> str:
    """Remove only the presentation marker added by our own evidence prompt."""
    return value.removeprefix("- ")


def assert_evidence_grounded(claimed_evidence: list[str], allowed_evidence: list[str]) -> None:
    ungrounded = [
        claim for claim in claimed_evidence
        if _without_prompt_bullet(claim) not in allowed_evidence
    ]
    if ungrounded:
        raise UngroundedEvidenceError(
            f"Creative Director cited evidence not in the allowed set (possible invented fact): {ungrounded!r}"
        )


def _effective_restricted_claims(director_input: CreativeDirectorInput) -> list[str]:
    restricted = list(director_input.restricted_claims)
    if not director_input.product_mention_allowed and director_input.product_name:
        restricted.append(director_input.product_name)
    return restricted


def _build_user_text(director_input: CreativeDirectorInput) -> str:
    evidence_block = "\n".join(f"- {item}" for item in director_input.allowed_evidence) or "(no evidence provided)"
    return (
        f"OBJECTIVE: {director_input.objective}\n"
        f"OPPORTUNITY: {director_input.opportunity_summary}\n"
        f"AUDIENCE: {director_input.audience_summary}\n"
        f"HOOK FAMILY: {director_input.hook_family or '(none selected)'}\n"
        f"CAMPAIGN THEME: {director_input.campaign_theme}\n"
        f"SERIES CONTEXT: {director_input.series_context}\n"
        f"CREATIVE FATIGUE NOTE: {director_input.fatigue_note}\n"
        f"APPROVED CLAIMS: {director_input.approved_claims}\n"
        f"RESTRICTED CLAIMS (never use): {director_input.restricted_claims}\n"
        f"PRODUCT_MENTION_ALLOWED: {director_input.product_mention_allowed}\n"
        f"EXTERNAL_NEWS_ENTITIES_ALLOWED: {director_input.external_news_entities_allowed}\n"
        f"LAUNCH CONTEXT: {director_input.launch_context_note or '(established account - no launch context)'}\n"
        f"FEED CONTEXT: {director_input.feed_context_note or '(no real feed context available)'}\n"
        f"TREND MECHANIC: {director_input.trend_mechanic or '(not a trend-origin piece)'}\n"
        f"WHY THIS MECHANIC IS SPREADING: {director_input.trend_spread_reason or '(n/a)'}\n"
        f"OUTPUT LOCALE: {director_input.locale}\n"
        f"BRAND/ACCOUNT POLICY:\n{director_input.brand_context or '(not supplied)'}\n"
        f"ACCOUNT STATE:\n{director_input.account_context or '(not supplied)'}\n"
        f"CURRENT PRODUCT TRUTH:\n{director_input.product_context or '(not supplied)'}\n"
        f"RECENT/IN-FLIGHT CONTENT:\n{director_input.recent_content_context or '(none)'}\n"
        f"APPROVED EDITORIAL DECISION:\n{director_input.editorial_decision or '(legacy call: not supplied)'}\n"
        f"EVIDENCE BULLETS (use ONLY these for any factual claim):\n{evidence_block}"
        + (
            "\nRECAP STORY KEYS (a slide about one story must set media_subject to exactly that key and "
            "must_match_story=true; never reuse one story's key for another): "
            + ", ".join(director_input.recap_subjects)
            if director_input.recap_subjects else ""
        )
    )


def _build_decision_user_text(decision_input: InstagramEditorialDecisionInput) -> str:
    evidence = "\n".join(f"- {item}" for item in decision_input.allowed_evidence) or "(none)"
    return (
        f"SOURCE TYPE: {decision_input.source_type}\n"
        f"SOURCE SUMMARY: {decision_input.source_summary}\n"
        f"OUTPUT LOCALE: {decision_input.locale}\n"
        f"EXECUTABLE FORMATS: {decision_input.executable_formats}\n"
        f"BRAND/ACCOUNT POLICY:\n{decision_input.brand_context}\n"
        f"ACCOUNT STATE:\n{decision_input.account_context}\n"
        f"CURRENT PRODUCT TRUTH:\n{decision_input.product_context}\n"
        f"TREND SIGNAL TYPE: {decision_input.trend_signal_type or '(none)'}\n"
        f"TREND SIGNAL PROVENANCE: {decision_input.trend_signal_provenance or '(none)'}\n"
        f"INSTAGRAM-NATIVE SIGNAL: {str(decision_input.trend_signal_is_platform_native).lower()}\n"
        f"TREND/MOMENTUM EVIDENCE (may be absent or a bad fit):\n{decision_input.trend_context or '(none)'}\n"
        f"RECENT/IN-FLIGHT INSTAGRAM CONTENT:\n{decision_input.recent_content_context or '(none)'}\n"
        f"EVIDENCE BULLETS:\n{evidence}"
    )


_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
_VISIBLE_SERVICE_LABEL_RE = re.compile(r"(?im)^\s*(?:CTA|CALL\s+TO\s+ACTION|HOOK|CAPTION|EDITOR\s+NOTE|ANGLE)\s*:")
_UNSUPPORTED_PLATFORM_TREND_CLAIM_RE = re.compile(
    r"(?i)(?:(?:instagram|reels).{0,40}(?:тренд|вирус|viral|audio|аудио|формат)|"
    r"(?:тренд|вирус|viral|audio|аудио|формат).{0,40}(?:instagram|reels))"
)


def assert_trend_rationale_grounded(
    rationale: str | None, *, signal_type: str | None, provenance: str | None,
    is_platform_native: bool,
) -> None:
    if not rationale or is_platform_native:
        return
    unsupported: list[str] = []
    for match in _UNSUPPORTED_PLATFORM_TREND_CLAIM_RE.finditer(rationale):
        prefix = rationale[max(0, match.start() - 60):match.start()].casefold()
        explicitly_disclaimed = re.search(
            r"(?:нет\s+доказательств|без\s+доказательств|"
            r"не\s+(?:подтверждает|доказывает|является|означает))[^.!?]{0,40}$",
            prefix,
        )
        if explicitly_disclaimed is None:
            unsupported.append(match.group(0))
    if unsupported:
        raise UngroundedTrendClaimError(
            "Director claimed an Instagram-native trend without platform-native evidence: "
            f"{unsupported!r}; signal_type={signal_type!r}; provenance={provenance!r}"
        )


def assert_russian_final_text(text_fields: list[str], *, locale: str = "ru") -> None:
    """Reject clearly English final output without penalizing normal Russian with Latin names.

    The check is intentionally asymmetric and conservative: it catches an English paragraph or
    complete English script, but a short official name such as ``NINJA AI``/``OpenAI`` is allowed.
    """
    if locale.lower() not in ("ru", "ru-ru"):
        return
    meaningful = [text.strip() for text in text_fields if text and text.strip()]
    for text in meaningful:
        latin_words = _LATIN_WORD_RE.findall(text)
        cyrillic_letters = len(_CYRILLIC_RE.findall(text))
        if len(latin_words) >= 6 and cyrillic_letters < 3:
            raise CreativeLanguageError("clearly English audience-facing field for locale=ru")
    combined = " ".join(meaningful)
    if len(_LATIN_WORD_RE.findall(combined)) >= 8 and len(_CYRILLIC_RE.findall(combined)) < 10:
        raise CreativeLanguageError("clearly English final output for locale=ru")


def assert_audience_facing_copy(text_fields: list[str]) -> None:
    for text in text_fields:
        if text and _VISIBLE_SERVICE_LABEL_RE.search(text):
            raise AudienceFacingCopyError("visible service label in audience-facing copy")


def _enforce_output_policy(text_fields: list[str], *, locale: str) -> None:
    assert_russian_final_text(text_fields, locale=locale)
    assert_audience_facing_copy(text_fields)


async def generate_editorial_decision(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, decision_input: InstagramEditorialDecisionInput,
) -> tuple[InstagramEditorialDecision, CapabilityCall]:
    try:
        prompt = prompt_repository.resolve(EDITORIAL_DECISION_PROMPT_NAME, _EDITORIAL_DECISION_PROMPT_VERSION)
    except Exception as exc:
        raise CreativeDirectorUnavailableError(f"prompt unavailable: {exc}") from exc
    request = GenerateRequest(
        messages=[
            Message(
                role="system",
                content=[ContentPart(type="text", text=prompt.system + "\n\nRULES:\n" + "\n".join(f"- {r}" for r in prompt.rules))],
            ),
            Message(role="user", content=[ContentPart(type="text", text=_build_decision_user_text(decision_input))]),
        ],
        response_mode="json_schema",
        response_schema=prompt.output_schema,
    )
    runtime = RuntimeContext(
        task_id=uuid4(), event_id=uuid4(), capability_name=EDITORIAL_DECISION_PROMPT_NAME,
        priority=TaskPriority.S, attempt=1, iteration_count=0,
    )
    try:
        outcome = await call_generate(gateway, request, runtime=runtime, sequence=0)
    except Exception as exc:
        raise CreativeDirectorUnavailableError(f"gateway call failed: {exc}") from exc
    if outcome.error is not None:
        raise CreativeDirectorUnavailableError(str(outcome.error))
    if outcome.response is None or outcome.response.structured_output is None:
        raise CreativeDirectorUnavailableError("no structured output returned")
    decision = InstagramEditorialDecision.model_validate(outcome.response.structured_output)
    assert_evidence_grounded(decision.evidence_used, decision_input.allowed_evidence)
    assert_trend_rationale_grounded(
        decision.trend_rationale,
        signal_type=decision_input.trend_signal_type,
        provenance=decision_input.trend_signal_provenance,
        is_platform_native=decision_input.trend_signal_is_platform_native,
    )
    _enforce_output_policy(
        [
            decision.why_now, decision.audience_value, decision.angle, decision.format_reason,
            decision.creative_direction, decision.product_connection or "", decision.trend_rationale or "",
            decision.supplementary_story_idea or "",
        ],
        locale=decision_input.locale,
    )
    return decision, outcome.call


async def _call_creative_director(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, prompt_name: str, director_input: CreativeDirectorInput,
    prompt_version: str,
) -> tuple[dict, CapabilityCall]:
    try:
        prompt = prompt_repository.resolve(prompt_name, prompt_version)
    except Exception as exc:
        raise CreativeDirectorUnavailableError(f"prompt unavailable: {exc}") from exc

    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    request = GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(role="user", content=[ContentPart(type="text", text=_build_user_text(director_input))]),
        ],
        response_mode="json_schema", response_schema=prompt.output_schema,
    )
    runtime = RuntimeContext(
        task_id=uuid4(), event_id=uuid4(), capability_name=prompt_name, priority=TaskPriority.S,
        attempt=1, iteration_count=0,
    )

    try:
        outcome = await call_generate(gateway, request, runtime=runtime, sequence=0)
    except Exception as exc:
        raise CreativeDirectorUnavailableError(f"gateway call failed: {exc}") from exc
    if outcome.error is not None:
        raise CreativeDirectorUnavailableError(str(outcome.error))

    response = outcome.response
    assert response is not None
    if response.structured_output is None:
        raise CreativeDirectorUnavailableError("no structured output returned")
    return response.structured_output, outcome.call


def _enforce_fact_safety(*, text_fields: list[str], evidence_used: list[str], director_input: CreativeDirectorInput) -> None:
    assert_evidence_grounded(evidence_used, director_input.allowed_evidence)
    try:
        validate_package_claims(text_fields=text_fields, restricted_claims=_effective_restricted_claims(director_input))
    except ClaimViolationError as exc:
        raise CreativeFactSafetyError(str(exc)) from exc


async def generate_single_creative(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, director_input: CreativeDirectorInput,
) -> CreativeGenerationOutcome:
    output, call = await _call_creative_director(
        gateway, prompt_repository, prompt_name=SINGLE_PROMPT_NAME, director_input=director_input,
        prompt_version=_SINGLE_PROMPT_VERSION,
    )
    creative = InstagramSingleCreative.model_validate(output)
    plan = creative.creative_execution_plan
    _enforce_fact_safety(
        text_fields=[creative.creative_angle, creative.visual_concept, creative.on_image_copy, creative.caption_direction,
                     creative.final_caption or "", creative.source_subject or "", creative.cta or "",
                     *(str(value or "") for value in (plan.model_dump().values() if plan is not None else []))],
        evidence_used=creative.evidence_used, director_input=director_input,
    )
    _enforce_output_policy(
        [creative.on_image_copy, creative.final_caption or "", creative.cta or ""],
        locale=director_input.locale,
    )
    return CreativeGenerationOutcome(single=creative, call=call)


def derive_content_archetype(
    decision: InstagramEditorialDecision | None, *, is_recap_bundle: bool = False,
) -> str | None:
    """Phase B.4.1 section 3: the REAL archetype decision owner. Reuses the EXISTING upstream
    `InstagramEditorialDecision` (already produced by this same module's own editorial-decision
    call, before a Creative Director call ever runs) as the evidence source - no new parallel
    classifier, no LLM call added. This function's result OVERRIDES whatever the carousel prompt
    itself may have emitted for `content_archetype` (v6.yaml's own field is advisory only - a
    model-declared label is not a trustworthy decision the way a deterministic function driven by
    the real upstream editorial context is).

    `is_recap_bundle` is the one signal this function cannot derive from a single opportunity's
    own decision: NEWS_RECAP is a multi-opportunity BUNDLING choice a future calendar/planning
    layer makes before any single Creative Director call - supplied explicitly by that caller,
    never guessed here. No such bundling layer exists in this repository yet (disclosed gap, not
    fabricated)."""
    if is_recap_bundle:
        return "news_recap"
    if decision is None:
        return None
    if decision.angle_intent == "HOW_TO" or decision.opportunity_type in ("PRODUCT", "EVERGREEN"):
        return "ai_hack"
    if decision.opportunity_type in ("NEWS_X_TREND", "PRODUCT_X_TREND") or decision.origin == "TREND":
        return "trend_generative"
    return "news_insight"


def _parse_editorial_decision(raw: str) -> InstagramEditorialDecision | None:
    if not raw:
        return None
    try:
        # The live trigger stores the decision plus extra bookkeeping keys (duplication_decision,
        # recent_history_count, ...); the strict model forbids extras, so keep only its own fields.
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        known = InstagramEditorialDecision.model_fields
        return InstagramEditorialDecision.model_validate({k: v for k, v in data.items() if k in known})
    except Exception:
        return None  # best-effort context only - never blocks generation over a parse failure


async def generate_carousel_creative(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, director_input: CreativeDirectorInput,
    is_recap_bundle: bool = False,
) -> CreativeGenerationOutcome:
    output, call = await _call_creative_director(
        gateway, prompt_repository, prompt_name=CAROUSEL_PROMPT_NAME, director_input=director_input,
        prompt_version=_CAROUSEL_PROMPT_VERSION,
    )
    creative = InstagramCarouselCreative.model_validate(output)
    decision = _parse_editorial_decision(director_input.editorial_decision)
    archetype = derive_content_archetype(
        decision, is_recap_bundle=is_recap_bundle or director_input.is_recap_bundle,
    )
    if archetype is not None:
        creative = creative.model_copy(update={"content_archetype": archetype})
    plan = creative.creative_execution_plan
    text_fields = [slide.slide_copy for slide in creative.slides] + [
        creative.final_cta or "", creative.final_caption or "",
        *(str(value or "") for value in (plan.model_dump().values() if plan is not None else [])),
    ]
    _enforce_fact_safety(text_fields=text_fields, evidence_used=creative.evidence_used, director_input=director_input)
    _enforce_output_policy(
        [*(slide.slide_copy for slide in creative.slides), creative.final_cta or "", creative.final_caption or ""],
        locale=director_input.locale,
    )
    return CreativeGenerationOutcome(carousel=creative, call=call)


async def generate_reel_creative(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, director_input: CreativeDirectorInput,
) -> CreativeGenerationOutcome:
    output, call = await _call_creative_director(
        gateway, prompt_repository, prompt_name=REEL_PROMPT_NAME, director_input=director_input,
        prompt_version=_REEL_PROMPT_VERSION,
    )
    creative = InstagramReelCreative.model_validate(output)
    plan = creative.creative_execution_plan
    text_fields = [
        creative.hook, creative.caption_direction, creative.final_caption or "", creative.source_subject or "",
        creative.voiceover_script or "",
        *creative.on_screen_text, creative.cta or "", creative.loop_ending_concept or "",
        creative.visual_direction or "", creative.adaptation_notes or "",
        *(scene.spoken_line for scene in creative.scenes),
        *(scene.on_screen_text or "" for scene in creative.scenes),
        *(str(value or "") for value in (plan.model_dump().values() if plan is not None else [])),
    ]
    _enforce_fact_safety(text_fields=text_fields, evidence_used=creative.evidence_used, director_input=director_input)
    _enforce_output_policy(
        [
            creative.hook, creative.voiceover_script or "", *creative.on_screen_text,
            creative.cta or "", creative.final_caption or "",
            *(scene.spoken_line for scene in creative.scenes),
            *(scene.on_screen_text or "" for scene in creative.scenes),
        ],
        locale=director_input.locale,
    )
    return CreativeGenerationOutcome(reel=creative, call=call)
