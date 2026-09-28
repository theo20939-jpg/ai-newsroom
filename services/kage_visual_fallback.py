"""KAGE Telegram NEWS visual fallback: generated editorial image -> KAGE typography card -> hold.

Reached only when the accepted source-photo path (Tier 1) produced no usable visual. Tier 2 is ONE
evidence-grounded OpenAI gpt-image-2.5-flare text-to-image dispatch, reserved and accounted inside the same per-story
envelope as every other paid call (services/kage_telegram_canary_envelope.py). Tier 3 is a local,
deterministic KAGE typography cover (headline + KAGE mark + NEWS treatment) - $0 provider cost.
Anything else is VISUAL_HOLD. No retries, no loops, no web discovery.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageFont, ImageStat, UnidentifiedImageError

from core.config import settings

logger = logging.getLogger(__name__)

TIER_SOURCE = "source_photo"
TIER_GENERATED = "generated_image"
TIER_TYPOGRAPHY = "typography_card"
TIER_HOLD = "visual_hold"
HOLD_REASON_VISUAL_FALLBACK_EXHAUSTED = "visual_fallback_exhausted"

GENERATION_MODEL = "gpt-image-2.5-flare"
GENERATION_QUALITY, GENERATION_SIZE = "high", "1536x1024"  # landscape hero for the KAGE NEWS renderer
GENERATION_MAX_DISPATCHES = 1

SCENE_PHYSICAL_INFRASTRUCTURE = "PHYSICAL_INFRASTRUCTURE"
SCENE_PHYSICAL_PRODUCT = "PHYSICAL_PRODUCT"
SCENE_ENVIRONMENTAL_EDITORIAL = "ENVIRONMENTAL_EDITORIAL"
SCENE_HUMAN_ACTIVITY_ANONYMOUS = "HUMAN_ACTIVITY_ANONYMOUS"
SCENE_ABSTRACT_PHYSICAL_METAPHOR = "ABSTRACT_PHYSICAL_METAPHOR"
NO_DISPLAY_SURFACES = "NO_DISPLAY_SURFACES"

_SOFTWARE_STORY = re.compile(
    r"\b(?:ai|artificial intelligence|software|algorithm|cybersecurity|online service|cloud|"
    r"website|model|agent)\b|(?:\bии\b|нейросет|модел|агент|алгоритм|кибер|онлайн|программ|сайт)",
    re.IGNORECASE,
)
_PHYSICAL_PRODUCT = re.compile(
    r"\b(?:smartphone|phone|laptop|tablet|handset|physical product)\b|"
    r"смартфон|телефон|ноутбук|планшет|физическ\w+ продукт",
    re.IGNORECASE,
)
_PRODUCT_IS_SUBJECT = re.compile(
    r"\b(?:launch|unveil|release|review|sales|ships?)\b|представ|анонс|выпуст|обзор|продаж|поставк",
    re.IGNORECASE,
)
_ENVIRONMENTAL_STORY = re.compile(
    r"climate|weather|energy|environment|construction|city|архитект|климат|погод|энерг|эколог|строител",
    re.IGNORECASE,
)
_HUMAN_ACTIVITY_STORY = re.compile(
    r"factory|laboratory|maintenance|manufactur|workshop|лаборатор|производ|ремонт|мастерск",
    re.IGNORECASE,
)
_PAUSED_ACTIVITY = re.compile(r"pause|paused|halt|stop|interrupt|приостанов|пауз|останов|прерван", re.IGNORECASE)
_DISPLAY_OBJECT_TERMS = frozenset({
    "laptop", "monitor", "phone", "tablet", "screen", "display", "browser", "dashboard",
    "interface", "television", "terminal", "projected", "hud",
})


@dataclass(frozen=True)
class GeneratedVisualScenePolicy:
    family: str
    capabilities: tuple[str, ...]
    allowed_objects: tuple[str, ...]
    positive_scene_description: str
    physical_state_metaphor: str

    def audit(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "capabilities": list(self.capabilities),
            "allowed_objects": list(self.allowed_objects),
            "positive_scene_description": self.positive_scene_description,
            "physical_state_metaphor": self.physical_state_metaphor,
        }


def select_generated_visual_scene_policy(
    *, title: str, facts: list[str], research: Mapping[str, Any], intelligence: Mapping[str, Any],
) -> GeneratedVisualScenePolicy:
    """Choose one small, deterministic positive scene grammar from supported story material."""
    metadata = " ".join(
        str(value) for payload in (research, intelligence)
        for key in ("topic", "category", "domain", "angle")
        if (value := payload.get(key)) is not None
    )
    context = " ".join((title, *facts, metadata))
    physical_product_subject = bool(_PHYSICAL_PRODUCT.search(context) and _PRODUCT_IS_SUBJECT.search(context))
    if physical_product_subject:
        return GeneratedVisualScenePolicy(
            SCENE_PHYSICAL_PRODUCT, (),
            ("generic physical product body", "neutral casing", "physical controls", "connectors",
             "unbranded tabletop", "practical lights"),
            "A restrained product photograph built only from the supported physical object and neutral materials.",
            "Use physical placement and practical lighting to express the reported state.",
        )
    if _SOFTWARE_STORY.search(context):
        state = (
            "Express paused or interrupted activity only through a dimmed inactive section of the infrastructure "
            "and reduced practical lighting."
            if _PAUSED_ACTIVITY.search(context)
            else "Express software activity only through physical infrastructure state and practical lighting."
        )
        return GeneratedVisualScenePolicy(
            SCENE_PHYSICAL_INFRASTRUCTURE, (NO_DISPLAY_SURFACES,),
            ("server racks", "cables", "cooling ducts", "generic compute hardware",
             "data-center architecture", "practical lights"),
            "A realistic data-center aisle made only from physical compute infrastructure and architecture.",
            state,
        )
    if _ENVIRONMENTAL_STORY.search(context):
        return GeneratedVisualScenePolicy(
            SCENE_ENVIRONMENTAL_EDITORIAL, (),
            ("architectural environment", "landscape materials", "weather conditions", "practical lights"),
            "A realistic environmental editorial scene made from architecture, landscape and natural conditions.",
            "Express the reported state through physical conditions and lighting.",
        )
    if _HUMAN_ACTIVITY_STORY.search(context):
        return GeneratedVisualScenePolicy(
            SCENE_HUMAN_ACTIVITY_ANONYMOUS, (),
            ("anonymous hands", "physical tools", "work surfaces", "materials", "practical lights"),
            "A realistic physical work scene with anonymous activity and no visible identity.",
            "Express the reported activity through tools, materials and physical action.",
        )
    return GeneratedVisualScenePolicy(
        SCENE_ABSTRACT_PHYSICAL_METAPHOR, (),
        ("unbranded geometric objects", "physical materials", "shadows", "architectural space", "practical lights"),
        "A restrained photographic metaphor made only from real physical materials and architectural space.",
        "Express the reported state through physical arrangement, shadow and light.",
    )


def validate_scene_policy(policy: GeneratedVisualScenePolicy) -> None:
    """Fail before dispatch when a screenless positive grammar names a display-bearing object."""
    if NO_DISPLAY_SURFACES not in policy.capabilities:
        return
    positive_fields = " ".join((policy.positive_scene_description, policy.physical_state_metaphor,
                                *policy.allowed_objects)).lower()
    conflicts = sorted(term for term in _DISPLAY_OBJECT_TERMS if re.search(rf"\b{re.escape(term)}\b", positive_fields))
    if conflicts:
        raise ValueError(f"screenless_scene_object_conflict:{','.join(conflicts)}")

# --- generation brief ------------------------------------------------------------------------------

# Deterministic named-person detection: a capitalized first name from this list followed by a
# capitalized word (Latin or Cyrillic). Deliberately conservative; the brief ALSO forbids any
# identifiable person or lookalike for every story, so a missed name still cannot produce a likeness.
_FIRST_NAMES = frozenset("""
Сэм Илон Марк Билл Джефф Тим Сундар Сатья Дарио Демис Дженсен Лиза Мира Грег Илья Ян Ник Джон Джордж
Дональд Джо Камала Владимир Эммануэль Олаф Си Нарендра Сергей Алексей Андрей Дмитрий Михаил Павел Иван
Анна Мария Елена Ольга Наталья Кевин Шон Майкл Дэвид Джеймс Роберт Уильям Ричард Томас Крис Эндрю
Sam Elon Mark Bill Jeff Tim Sundar Satya Dario Demis Jensen Lisa Mira Greg Ilya Jan Nick John George
Donald Joe Kamala Vladimir Emmanuel Olaf Xi Narendra Kevin Sean Michael David James Robert William
Richard Thomas Chris Andrew Mustafa Reid Brad Larry Sergey Jack Evan Pavel Masayoshi Arvind Alexandr
""".split())
_NAME_PAIR = re.compile(r"\b([A-ZА-ЯЁ][a-zа-яё]+)\s+([A-ZА-ЯЁ][a-zа-яё]+(?:-[A-ZА-ЯЁ][a-zа-яё]+)?)")
# Conservative visual-only projection. Mixed-case/all-caps Latin marks and multi-token Latin
# proper names are semantic context in the caption, not instructions to reproduce their branding.
_LATIN_ENTITY_SURFACE = re.compile(
    r"\b(?:[A-Z]{2,}(?:\s+[A-Z][A-Za-z0-9.&+-]+)*|"
    r"[A-Z][a-z]+(?:[A-Z][A-Za-z0-9]+)+|"
    r"[A-Z][A-Za-z0-9.&+-]+(?:\s+[A-Z][A-Za-z0-9.&+-]+)+)\b"
)

_STYLE_AND_SAFETY = (
    "Create ONE realistic, cinematic editorial news photograph (16:9) that conveys the story's concept "
    "visually. Polished magazine-grade lighting and composition. The Telegram caption carries the "
    "journalism; the image carries only the visual concept.",
    "Use ONLY the verified facts above. Do not add products, numbers, places, events or details that "
    "are not stated there.",
    "No text, letters, numbers, captions, logos, watermarks or signage anywhere in the image.",
    "Never depict screenshots, app or product interfaces, web pages, documents, charts, graphs, "
    "quotes, news tickers or breaking-news graphics.",
    "Never depict a real, identifiable person or a lookalike of one. If people are needed, show only "
    "anonymous hands or silhouettes with faces not visible; prefer objects, devices, environments and "
    "abstract editorial scenes.",
    "Show devices and products as generic and unbranded; never invent product details.",
    "No decorative sci-fi imagery, no dense infographic, no collage.",
)


def mask_person_names(text: str) -> tuple[str, bool]:
    found = False

    def _replace(match: re.Match[str]) -> str:
        nonlocal found
        if match.group(1) in _FIRST_NAMES:
            found = True
            return "a person"
        return match.group(0)

    return _NAME_PAIR.sub(_replace, text), found


def _structured_entity_surfaces(*payloads: Mapping[str, Any]) -> tuple[str, ...]:
    """Read only explicit entity metadata when upstream provides it; never infer new facts."""
    found: list[str] = []
    for payload in payloads:
        for key in ("entities", "named_entities", "organizations", "companies", "products"):
            values = payload.get(key, [])
            if isinstance(values, (str, Mapping)):
                values = [values]
            if not isinstance(values, list):
                continue
            for value in values:
                candidate = value if isinstance(value, str) else next(
                    (value.get(field) for field in ("name", "text", "label")
                     if isinstance(value, Mapping) and isinstance(value.get(field), str)), None,
                )
                if isinstance(candidate, str) and candidate.strip() and candidate.strip() not in found:
                    found.append(candidate.strip())
    return tuple(found)


def safe_visual_projection(
    text: str, *, structured_entities: tuple[str, ...] = (),
) -> tuple[str, tuple[str, ...]]:
    """Remove brand/proper-name surface forms from the pixel prompt without changing journalism.

    The exact caption remains untouched. This bounded projection only turns recognizable Latin
    organization/product/source names into a generic role before image generation.
    """
    masked: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        surface = match.group(0)
        if surface not in masked:
            masked.append(surface)
        return "an unnamed organization"

    projected = text
    for surface in sorted(structured_entities, key=len, reverse=True):
        if surface in projected:
            projected = projected.replace(surface, "an unnamed organization or product")
            if surface not in masked:
                masked.append(surface)
    return _LATIN_ENTITY_SURFACE.sub(_replace, projected), tuple(masked)


def build_generation_brief(
    *, title: str, body: str, research: Mapping[str, Any], intelligence: Mapping[str, Any],
    source_headline: str = "",
) -> dict[str, Any]:
    """Brief from the verified story contract and the final copy only: headline, CORE facts, and the
    selected optional facts the final body actually communicates. Never the raw source text."""
    from services.kage_editorial_usefulness import communicated_fact_ids
    from services.kage_evidence_first import _GAP_OR_META, minimum_story_contract, select_evidence_cards

    story = minimum_story_contract(research, intelligence, source_headline=source_headline)
    cards, _, _ = select_evidence_cards(research, intelligence, source_headline=source_headline)
    substantive = [card for card in cards if not _GAP_OR_META.search(card["fact"])]
    core_ids = [item["id"] for item in story["core_facts"]]
    used_optional = [card_id for card_id in communicated_fact_ids(body, substantive) if card_id not in core_ids]
    fact_ids = [*core_ids, *used_optional]
    by_id = {card["id"]: card["fact"] for card in cards}
    structured_entities = _structured_entity_surfaces(research, intelligence)
    headline, person_in_title = mask_person_names(title.strip())
    headline, headline_entities = safe_visual_projection(headline, structured_entities=structured_entities)
    facts, person_flags = [], [person_in_title]
    protected_entities = list(headline_entities)
    for fact_id in fact_ids:
        masked, flagged = mask_person_names(by_id[fact_id])
        projected, entities = safe_visual_projection(masked, structured_entities=structured_entities)
        facts.append(projected)
        protected_entities.extend(entity for entity in entities if entity not in protected_entities)
        person_flags.append(flagged)
    named_person = any(person_flags)
    scene_policy = select_generated_visual_scene_policy(
        title=headline, facts=facts, research=research, intelligence=intelligence,
    )
    validate_scene_policy(scene_policy)
    lines = [
        "KAGE EDITORIAL NEWS IMAGE",
        "SUPPORTED STORY CONTEXT (journalism only; do not copy its literal nouns into the scene):",
        f"Story headline: {headline}",
        "Verified facts:",
    ]
    lines += [f"- {fact}" for fact in facts]
    lines += [
        "MANDATORY POSITIVE SCENE GRAMMAR:",
        f"Scene family: {scene_policy.family}",
        "The image must be made ONLY from these allowed physical ingredients:",
        *[f"- {item}" for item in scene_policy.allowed_objects],
        f"Scene construction: {scene_policy.positive_scene_description}",
        f"Physical state: {scene_policy.physical_state_metaphor}",
        "Do not introduce any object that is not in the positive allowlist.",
    ]
    if NO_DISPLAY_SURFACES in scene_policy.capabilities:
        lines += [
            "STRICT CAPABILITY: NO_DISPLAY_SURFACES.",
            "No object whose primary purpose is displaying content may exist anywhere in the image.",
            "Forbidden objects: laptops, desktop monitors, phones, tablets, televisions, control-room "
            "displays, digital dashboards, projected interfaces, HUDs, screens, browser windows, "
            "terminal windows and visible display panels.",
            "Use only generic physical infrastructure; never invent product details or branded hardware.",
        ]
    lines += [rule for rule in _STYLE_AND_SAFETY if not (
        NO_DISPLAY_SURFACES in scene_policy.capabilities
        and (rule.startswith("Show devices") or rule.startswith("Never depict a real"))
    )]
    if NO_DISPLAY_SURFACES in scene_policy.capabilities:
        lines.append("Never depict a real, identifiable person or a lookalike of one. "
                     "For this scene show no people or body parts at all.")
    if named_person:
        lines.append("This story names a real person: show no person at all - depict objects, "
                     "devices or an environment connected to the facts.")
    lines.append("Any named organization, product or source in the journalism is semantic context only. "
                 "Depict only generic, unbranded objects and environments; never reproduce a brand identity.")
    concept = "\n".join([f"Story concept: {headline}", *[f"Supported fact: {fact}" for fact in facts]])
    return {
        "prompt": "\n".join(lines), "safe_visual_concept": concept, "fact_ids": fact_ids,
        "named_person_detected": named_person, "masked_entity_surfaces": protected_entities,
        "scene_policy": scene_policy.audit(),
    }


# --- generated output validation ------------------------------------------------------------------------

@dataclass(frozen=True)
class ImageCheck:
    ok: bool
    reason: str


def validate_generated_image(data: bytes | None) -> ImageCheck:
    if not data:
        return ImageCheck(False, "empty")
    if len(data) > 10 * 1024 * 1024:
        return ImageCheck(False, "too_large_for_telegram_photo")
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = (im.format or "").upper()
            im.load()
            width, height = im.size
            stddev = max(ImageStat.Stat(im.convert("L")).stddev)
    except (UnidentifiedImageError, OSError):
        return ImageCheck(False, "undecodable")
    if fmt not in {"PNG", "JPEG"}:
        return ImageCheck(False, f"unsupported_format:{fmt}")
    if min(width, height) < 600:
        return ImageCheck(False, "resolution_too_low")
    if not 1.2 <= width / height <= 2.1:
        return ImageCheck(False, "not_landscape_editorial")
    if stddev < 8:
        return ImageCheck(False, "blank_or_uniform")
    return ImageCheck(True, "ok")


# --- Tier 3: deterministic KAGE typography card ---------------------------------------------------------

CARD_W, CARD_H = 1280, 720
_CARD_MARGIN = 96
_CARD_MAX_LINES = 4
_CARD_FONT_SIZES = (76, 72, 68, 64, 60, 56, 52, 48)  # bounded ladder; 48 px is the readability floor
_CARD_BG = (12, 12, 14)
_CARD_TEXT = (0xFF, 0xFF, 0xFF)
_CARD_ACCENT = (0xED, 0x1C, 0x24)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: int) -> list[str] | None:
    lines: list[str] = []
    current = ""
    for word in text.split():
        if draw.textlength(word, font=font) > max_width:
            return None  # a single word wider than the line: never split mid-word
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fit_headline(title: str) -> tuple[list[str], int] | None:
    """Largest ladder size at which the whole headline wraps into <= 4 lines. None = does not fit
    (the caller holds); never an ellipsis, never an unbounded shrink."""
    from services.brand_renderer import _data_font

    text = " ".join(title.split())
    if not text:
        return None
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for size in _CARD_FONT_SIZES:
        font = _data_font(size, "black")
        lines = _wrap(probe, text, font, CARD_W - 2 * _CARD_MARGIN)
        if lines is not None and len(lines) <= _CARD_MAX_LINES:
            line_h = round(size * 1.12)
            if 150 + len(lines) * line_h <= CARD_H - 150:
                return lines, size
    return None


def render_typography_card(title: str) -> bytes | None:
    """Intentional KAGE editorial cover: NEWS label + red accent, the headline, the KAGE mark.
    Deterministic PNG (bundled font). None when the headline cannot fit under the rules."""
    from services.brand_renderer import _data_font, _paste_logo

    fitted = fit_headline(title)
    if fitted is None:
        return None
    lines, size = fitted
    canvas = Image.new("RGBA", (CARD_W, CARD_H), _CARD_BG + (255,))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((_CARD_MARGIN, 96, _CARD_MARGIN + 88, 104), fill=_CARD_ACCENT)
    draw.text((_CARD_MARGIN, 116), "NEWS", font=_data_font(26, "bold"), fill=_CARD_ACCENT)
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont = _data_font(size, "black")
    line_h = round(size * 1.12)
    y = 180
    for line in lines:
        draw.text((_CARD_MARGIN, y), line, font=font, fill=_CARD_TEXT)
        y += line_h
    _paste_logo(canvas, target_width=150, margin=56)
    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG", optimize=False)
    return out.getvalue()


# --- Tier 2: one generated image inside the per-story envelope ------------------------------------------

async def generate_editorial_image(prompt: str, *, gateway: Any | None = None) -> tuple[bytes | None, str]:
    """ONE OpenAI gpt-image-2.5-flare text-to-image dispatch. Reserved in the active per-story envelope before dispatch;
    the provider-accounted cost is recorded after it (unknown cost fails closed downstream).
    Never raises: (image_bytes or None, reason)."""
    from integrations.llm_gateway.image_protocol import ImageGenerationOperation, ImageGenerationRequest
    from services.kage_telegram_canary_envelope import (
        VISUAL_GENERATION_STAGE, CanaryPreDispatchSafetyRejection, current_telegram_canary_envelope,
        visual_generation_worst_case,
    )

    request = ImageGenerationRequest(prompt=prompt, operation=ImageGenerationOperation.TEXT_TO_IMAGE,
                                     target_aspect_ratio="16:9")
    adapter = gateway
    if adapter is None:
        api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        if not api_key:
            return None, "openai_api_key_absent"
        from integrations.llm_gateway.providers.openai_image_adapter import OpenAIImageAdapter
        from services.budgeted_image_execution import BudgetedImageGateway, build_budgeted_image_executor
        from services.image_pricing import ImageExecutionProfile

        prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        adapter = BudgetedImageGateway(
            gateway=OpenAIImageAdapter(
                api_key=api_key, model_id=GENERATION_MODEL, quality=GENERATION_QUALITY,
                text_to_image_size=GENERATION_SIZE, output_format="jpeg", output_compression=90,
                max_retries=0, timeout_seconds=120,
            ),
            executor=build_budgeted_image_executor(),
            profile=ImageExecutionProfile(provider="openai", model=GENERATION_MODEL, quality=GENERATION_QUALITY,
                                          size=GENERATION_SIZE,
                                          operation=ImageGenerationOperation.TEXT_TO_IMAGE),
            mode="live", purpose="news_generated_image", execution_id=f"news-generated:{prompt_sha}",
            creative_id=f"news-generated:{prompt_sha}", package_id=prompt_sha, max_attempts=GENERATION_MAX_DISPATCHES,
        )

    envelope = current_telegram_canary_envelope()
    if envelope is not None:
        try:
            envelope.authorize_visual_dispatch(stage=VISUAL_GENERATION_STAGE, model_id=GENERATION_MODEL,
                                               reserved_usd=visual_generation_worst_case())
        except CanaryPreDispatchSafetyRejection as exc:
            return None, f"cost_envelope_refused:{exc}"

    def _record(
        cost: object, usage: Any = None, request_id: str | None = None,
        provider_status_code: int | None = None,
    ) -> None:
        if envelope is None:
            return
        value = None if cost is None else Decimal(str(cost))
        envelope.record_visual_result(stage=VISUAL_GENERATION_STAGE, actual_cost_usd=value,
                                      status="SUCCEEDED" if value is not None else "COST_UNKNOWN",
                                      input_tokens=getattr(usage, "input_tokens", None),
                                      output_tokens=getattr(usage, "output_tokens", None),
                                      text_input_tokens=getattr(usage, "text_input_tokens", None),
                                      image_input_tokens=getattr(usage, "image_input_tokens", None),
                                      request_id=request_id, provider_status_code=provider_status_code)

    started = time.monotonic()
    try:
        response = await adapter.generate_image(request)
    except Exception as exc:  # noqa: BLE001 - one bounded attempt; any failure falls to Tier 3
        bounded_response = getattr(exc, "response", None)
        _record(
            getattr(exc, "actual_cost_usd", None), getattr(bounded_response, "usage", None),
            getattr(bounded_response, "request_id", None),
            getattr(bounded_response, "provider_status_code", None),
        )
        # The provider adapters' messages carry only status/type information (never request bodies
        # or secrets); a bounded copy is kept so a failed dispatch is diagnosable from the audit.
        detail = " ".join(str(exc).split())[:200]
        logger.warning("kage_generated_image_failed", extra={"error_class": type(exc).__name__, "detail": detail})
        return None, f"generation_error:{type(exc).__name__}" + (f": {detail}" if detail else "")
    _record(
        getattr(response, "cost_usd", None), getattr(response, "usage", None),
        getattr(response, "request_id", None), getattr(response, "provider_status_code", None),
    )
    check = validate_generated_image(getattr(response, "image_bytes", None))
    logger.info("kage_generated_image_result", extra={"valid": check.ok, "reason": check.reason,
                                                       "latency_ms": round((time.monotonic() - started) * 1000)})
    return (response.image_bytes, "ok") if check.ok else (None, f"generated_invalid:{check.reason}")


# --- the tier ladder --------------------------------------------------------------------------------------

@dataclass
class VisualFallbackResult:
    tier: str
    image_bytes: bytes | None
    reason: str
    brief: dict[str, Any] | None = None
    generation_reason: str | None = None
    typography_reason: str | None = None
    compliance: Any | None = None

    def audit(self) -> dict[str, Any]:
        return {
            "name": "visual_fallback", "tier": self.tier, "reason": self.reason,
            "generation_reason": self.generation_reason, "typography_reason": self.typography_reason,
            "brief_fact_ids": (self.brief or {}).get("fact_ids"),
            "named_person_detected": (self.brief or {}).get("named_person_detected"),
            "masked_entity_surfaces": (self.brief or {}).get("masked_entity_surfaces"),
            "brief_prompt": (self.brief or {}).get("prompt"),
            "visual_compliance": self.compliance.audit() if self.compliance is not None else None,
            "image_sha256": hashlib.sha256(self.image_bytes).hexdigest() if self.image_bytes else None,
            "typography_provider_cost_usd": "0" if self.tier == TIER_TYPOGRAPHY else None,
        }


async def resolve_visual_fallback(
    *, title: str, body: str, research: Mapping[str, Any], intelligence: Mapping[str, Any],
    source_headline: str = "", gateway: Any | None = None, compliance_gateway: Any | None = None,
    category: str = "AI", editorial_code: str = "",
    allow_generation: bool = True,
) -> VisualFallbackResult:
    """Tier 2 then Tier 3, each at most once. Returns TIER_HOLD when both fail. `allow_generation=False`
    (dry run) skips the paid Tier 2 call entirely."""
    try:
        brief = build_generation_brief(title=title, body=body, research=research, intelligence=intelligence,
                                       source_headline=source_headline)
    except Exception as exc:  # noqa: BLE001 - no brief means no generation; Tier 3 still possible
        brief, generation_reason = None, f"brief_unavailable:{type(exc).__name__}"
    else:
        if allow_generation:
            generated, generation_reason = await generate_editorial_image(brief["prompt"], gateway=gateway)
        else:
            generated, generation_reason = None, "generation_not_allowed_dry_run"
        if generated is not None:
            from services.kage_visual_compliance import inspect_generated_visual

            compliance = await inspect_generated_visual(
                generated, safe_visual_concept=brief["safe_visual_concept"], gateway=compliance_gateway,
            )
            if not compliance.compliant:
                generation_reason = f"compliance_rejected:{compliance.failure_reason or 'forbidden_pixels'}"
                generated = None
        if generated is not None:
            try:
                from services.brand_renderer import render_news_hero

                branded = render_news_hero(generated, category=category, editorial_code=editorial_code,
                                           branding_strength="MINIMAL")
            except Exception as exc:  # noqa: BLE001 - an unbrandable image is not published
                generation_reason = f"branding_failed:{type(exc).__name__}"
            else:
                return VisualFallbackResult(TIER_GENERATED, branded, "ok", brief, generation_reason,
                                            compliance=compliance)
    try:
        card = render_typography_card(title)
        typography_reason = "ok" if card is not None else "headline_does_not_fit"
    except Exception as exc:  # noqa: BLE001
        card, typography_reason = None, f"render_error:{type(exc).__name__}"
    if card is not None:
        return VisualFallbackResult(TIER_TYPOGRAPHY, card, "ok", brief, generation_reason, typography_reason,
                                    compliance if 'compliance' in locals() else None)
    return VisualFallbackResult(TIER_HOLD, None, HOLD_REASON_VISUAL_FALLBACK_EXHAUSTED, brief,
                                generation_reason, typography_reason,
                                compliance if 'compliance' in locals() else None)
