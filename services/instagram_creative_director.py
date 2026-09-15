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

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from capabilities.gateway_call import call_generate
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository
from schemas.capability import CapabilityCall, RuntimeContext
from schemas.instagram_creative import InstagramCarouselCreative, InstagramReelCreative, InstagramSingleCreative
from services.instagram_format_director import ClaimViolationError, validate_package_claims

SINGLE_PROMPT_NAME = "instagram_creative_director_single"
CAROUSEL_PROMPT_NAME = "instagram_creative_director_carousel"
REEL_PROMPT_NAME = "instagram_creative_director_reel"
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
_SINGLE_PROMPT_VERSION = "3"
_CAROUSEL_PROMPT_VERSION = "3"
_REEL_PROMPT_VERSION = "4"


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


def assert_evidence_grounded(claimed_evidence: list[str], allowed_evidence: list[str]) -> None:
    ungrounded = [claim for claim in claimed_evidence if claim not in allowed_evidence]
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
        f"LAUNCH CONTEXT: {director_input.launch_context_note or '(established account - no launch context)'}\n"
        f"FEED CONTEXT: {director_input.feed_context_note or '(no real feed context available)'}\n"
        f"TREND MECHANIC: {director_input.trend_mechanic or '(not a trend-origin piece)'}\n"
        f"WHY THIS MECHANIC IS SPREADING: {director_input.trend_spread_reason or '(n/a)'}\n"
        f"EVIDENCE BULLETS (use ONLY these for any factual claim):\n{evidence_block}"
    )


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
    _enforce_fact_safety(
        text_fields=[creative.creative_angle, creative.visual_concept, creative.on_image_copy, creative.caption_direction, creative.cta or ""],
        evidence_used=creative.evidence_used, director_input=director_input,
    )
    return CreativeGenerationOutcome(single=creative, call=call)


async def generate_carousel_creative(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, director_input: CreativeDirectorInput,
) -> CreativeGenerationOutcome:
    output, call = await _call_creative_director(
        gateway, prompt_repository, prompt_name=CAROUSEL_PROMPT_NAME, director_input=director_input,
        prompt_version=_CAROUSEL_PROMPT_VERSION,
    )
    creative = InstagramCarouselCreative.model_validate(output)
    text_fields = [slide.slide_copy for slide in creative.slides] + [creative.final_cta or ""]
    _enforce_fact_safety(text_fields=text_fields, evidence_used=creative.evidence_used, director_input=director_input)
    return CreativeGenerationOutcome(carousel=creative, call=call)


async def generate_reel_creative(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, director_input: CreativeDirectorInput,
) -> CreativeGenerationOutcome:
    output, call = await _call_creative_director(
        gateway, prompt_repository, prompt_name=REEL_PROMPT_NAME, director_input=director_input,
        prompt_version=_REEL_PROMPT_VERSION,
    )
    creative = InstagramReelCreative.model_validate(output)
    text_fields = [
        creative.hook, creative.caption_direction, creative.voiceover_script or "",
        *creative.on_screen_text, creative.cta or "", creative.loop_ending_concept or "",
        creative.visual_direction or "", creative.adaptation_notes or "",
    ]
    _enforce_fact_safety(text_fields=text_fields, evidence_used=creative.evidence_used, director_input=director_input)
    return CreativeGenerationOutcome(reel=creative, call=call)
