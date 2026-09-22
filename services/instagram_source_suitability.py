"""Narrow vision check: can a REAL source image serve as primary / full-bleed Instagram media, or is it predominantly a text / article /
promo / interface card?

Why vision: the deterministic flat-card test (services.instagram_asset_profile.suitable_for_final_visual, few dominant colours) misses
press graphics built on gradients - e.g. the Apple Wallet press image (app icon + baked-in wordmark) - and no colour/texture signal
separates those from legitimate studio product shots (measured on the 30 real B.5R.1 sources). What distinguishes them is WHAT the image
is, which only a visual read answers.

Scope is deliberately narrow: only source images of the current post that already passed the deterministic test (i.e. real candidates
for primary media), at most MAX_CHECKS_PER_POST, one small downscaled image per call, through the same `call_generate` -> budgeted
gateway path as the Creative Director. The verdict is computed here from structured fields, never from free text. On any error the
image keeps its deterministic verdict (this is an aesthetic gate, not a fact-safety one) and the error is recorded."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
from typing import Any
from uuid import uuid4

from PIL import Image

from capabilities.gateway_call import call_generate
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, Message
from schemas.capability import RuntimeContext, TaskPriority

PROMPT_NAME = "instagram_source_visual_suitability"
PROMPT_VERSION = "2"
MAX_CHECKS_PER_POST = 8
SUITABLE_KINDS = frozenset({"photograph", "product_render", "illustration_or_artwork"})
UNSUITABLE_KINDS = frozenset({"article_or_news_card", "promo_or_press_graphic", "screenshot_or_interface", "logo_or_wordmark", "chart_or_diagram"})
_MAX_SIDE = 768

_sink: list[dict] | None = None


def set_verdict_sink(sink: list[dict] | None) -> None:
    """Observability hook (acceptance runs): every verdict is appended as a plain dict."""
    global _sink
    _sink = sink


@dataclass(frozen=True)
class SuitabilityVerdict:
    subject_key: str
    suitable: bool | None  # None = unknown (error) -> the caller keeps the deterministic verdict
    image_kind: str | None = None
    baked_in_text_prominent: bool | None = None
    reason: str | None = None
    error: str | None = None
    call: Any = None


def decide(structured: dict) -> bool:
    """Decided from WHAT the image is, not from the model's own overall opinion: asking for a suitability judgement made it
    reject a real photographed papyrus. `primary_media_suitable` is still recorded, it just does not veto a real picture."""
    return not (structured.get("image_kind") in UNSUITABLE_KINDS or bool(structured.get("baked_in_text_prominent")))


def _data_uri(image: Image.Image) -> str:
    rgb = image.convert("RGB")
    rgb.thumbnail((_MAX_SIDE, _MAX_SIDE))
    buf = BytesIO()
    rgb.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


async def _call_vision(gateway: Any, request: GenerateRequest, runtime: RuntimeContext):
    return await call_generate(gateway, request, runtime=runtime, sequence=0)


async def _check_one(gateway: Any, prompt: Any, subject_key: str, image: Image.Image) -> SuitabilityVerdict:
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    request = GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(role="user", content=[
                ContentPart(type="text", text="Classify the attached image."),
                ContentPart(type="artifact_ref", artifact_ref=_data_uri(image), mime_type="image/jpeg"),
            ]),
        ],
        response_mode="json_schema", response_schema=prompt.output_schema, modalities=["text", "image"], max_tokens=400,
    )
    runtime = RuntimeContext(task_id=uuid4(), event_id=uuid4(), capability_name=PROMPT_NAME, priority=TaskPriority.S,
                             attempt=1, iteration_count=0)
    try:
        outcome = await _call_vision(gateway, request, runtime)
    except Exception as exc:  # noqa: BLE001 - an aesthetic check never breaks post generation
        return SuitabilityVerdict(subject_key, None, error=f"{type(exc).__name__}: {exc}"[:200])
    structured = getattr(getattr(outcome, "response", None), "structured_output", None) if outcome.error is None else None
    if not isinstance(structured, dict) or "image_kind" not in structured:
        return SuitabilityVerdict(subject_key, None, error=str(outcome.error or "no structured output")[:200], call=outcome.call)
    return SuitabilityVerdict(subject_key, decide(structured), structured.get("image_kind"), structured.get("baked_in_text_prominent"),
                              str(structured.get("reason") or "")[:200], call=outcome.call)


async def check_primary_suitability(gateway: Any, prompt_repository: Any, candidates: list[tuple[str, Image.Image]]) -> dict[str, SuitabilityVerdict]:
    """`candidates`: (subject key, image) for source images that passed the deterministic test. Returns a verdict per checked key."""
    if gateway is None or prompt_repository is None or not candidates:
        return {}
    try:
        prompt = prompt_repository.resolve(PROMPT_NAME, PROMPT_VERSION)
    except Exception:  # noqa: BLE001
        return {}
    verdicts: dict[str, SuitabilityVerdict] = {}
    for key, image in candidates[:MAX_CHECKS_PER_POST]:
        verdict = await _check_one(gateway, prompt, key, image)
        verdicts[key] = verdict
        if _sink is not None:
            _sink.append({"subject_key": key, "suitable": verdict.suitable, "image_kind": verdict.image_kind,
                          "baked_in_text_prominent": verdict.baked_in_text_prominent, "reason": verdict.reason, "error": verdict.error})
    return verdicts
