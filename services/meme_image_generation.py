"""Meme Image Generation (Phase 18 M5): orchestrates one image-generation attempt for an
already-approved `MemeConcept` through `ImageGenerationGateway`, then persists the bytes via
`integrations.storage.image_storage.ImageStorage` (docs/phase18_m5_meme_image_generation_report.md).

Deliberately NOT built as a `capabilities.registry.Capability` - see the M5 report §3 for the
full rationale (in short: `capabilities.registry.build_registry()`'s constructor signature is a
contractually-frozen boot-sequence seam, and threading a new `ImageGenerationGateway` dependency
through it for a feature no live workflow run yet reaches would be a disproportionate,
unnecessary architecture change at this stage - "не менять архитектуру проекта без
необходимости"). This is instead a plain orchestration function, directly analogous to
`services/telegram_notifier.py::send_editorial_card()` or
`services/image_preview_notifier.py::send_news_with_image_preview()` - both already-established
"service function with a directly-inspectable outcome object" patterns in this codebase, neither
of which goes through the Capability Framework either.

Generates the image WITHOUT any text baked in (docs/phase18_m0_meme_discovery_report.md §"M5"'s
own stated preference: "генерировать изображение без текста, а потом накладывать текст
детерминированно" - preferred). `build_image_prompt()` explicitly instructs against any text/
letters appearing in the image; M6's renderer is the only place overlay text is ever added.

Bounded retries only (brief's own "bounded retries" / "без неограниченной регенерации"
requirement) - `_MAX_GENERATION_ATTEMPTS` attempts within ONE call to `generate_meme_image()`,
never an unbounded loop. Regeneration ACROSS separate calls (a human clicking "regenerate image"
in a future M8 preview) is a distinct, caller-tracked concern
(`database.models.meme_candidate.MemeCandidate.image_regeneration_count`), not something this
function loops on itself.
"""
from __future__ import annotations

import hashlib
import logging
from io import BytesIO
from typing import Literal

from PIL import Image, UnidentifiedImageError

from core.config import settings
from integrations.llm_gateway.image_protocol import ImageGenerationGateway, ImageGenerationRequest
from integrations.storage.image_storage import ImageStorage, StorageError
from schemas.meme_concept import MemeConcept
from schemas.meme_image import MemeImageGenerationResult, MemeImageStatus

logger = logging.getLogger(__name__)

_MAX_GENERATION_ATTEMPTS = 2


def build_image_prompt(concept: MemeConcept) -> str:
    """Pure, deterministic. Describes only the visual scene - never includes the punchline/copy
    text, and explicitly instructs against rendering any text at all (M6 owns all on-image text,
    added deterministically after generation - module docstring)."""
    parts = [concept.visual_scene]
    if concept.characters_objects:
        parts.append(f"Depicting: {', '.join(concept.characters_objects)}.")
    parts.append(
        "Photographic or illustrated scene only - no text, no letters, no words, no captions "
        "anywhere in the image."
    )
    return " ".join(parts)


async def generate_meme_image(
    concept: MemeConcept,
    *,
    gateway: ImageGenerationGateway,
    storage: ImageStorage,
    mode: Literal["off", "dry_run"],
) -> MemeImageGenerationResult:
    """`mode="off"` is a zero-cost, zero-call no-op - the safe default (mirrors every other
    Phase 15-18 mode flag's own "off means byte-identical no-op" discipline). `mode="dry_run"`
    performs a real call through whichever `gateway` was injected - in every call site this phase
    wires up, that is `MockImageAdapter` (zero network, zero cost); a real, paid provider adapter
    is a distinct, not-yet-built, separately-authorized future step (module docstring).

    Never raises - a generation or storage failure after `_MAX_GENERATION_ATTEMPTS` attempts
    returns `MemeImageStatus.FAILED` with an `error_code`, exactly like every other best-effort
    boundary in this codebase (`_attach_*` hooks, `NotificationOutcome`)."""
    if mode == "off":
        return MemeImageGenerationResult(status=MemeImageStatus.OFF, mode=mode)

    prompt = build_image_prompt(concept)
    request = ImageGenerationRequest(prompt=prompt)

    last_error_code: str | None = None
    for attempt in range(1, _MAX_GENERATION_ATTEMPTS + 1):
        try:
            response = await gateway.generate_image(request)
        except Exception as exc:  # noqa: BLE001 - translated to a stable, loggable code, never re-raised
            last_error_code = f"generation_failed:{type(exc).__name__}"
            logger.warning(
                "meme_image_generation_attempt_failed",
                extra={"attempt": attempt, "error_code": last_error_code},
            )
            continue

        try:
            sha256 = hashlib.sha256(response.image_bytes).hexdigest()
            with Image.open(BytesIO(response.image_bytes)) as decoded:
                decoded.verify()
            with Image.open(BytesIO(response.image_bytes)) as decoded:
                width, height = decoded.size
                image_format = decoded.format or "PNG"
            stored = storage.store_validated_image(
                response.image_bytes, sha256=sha256, image_format=image_format,
                max_bytes=settings.meme_image_max_bytes,
            )
        except (UnidentifiedImageError, StorageError, OSError) as exc:
            last_error_code = f"storage_failed:{type(exc).__name__}"
            logger.warning(
                "meme_image_storage_failed",
                extra={"attempt": attempt, "error_code": last_error_code},
            )
            continue

        logger.info(
            "meme_image_generated",
            extra={
                "attempt": attempt, "provider": response.provider, "model_used": response.model_used,
                "storage_key": stored.storage_key, "byte_size": stored.byte_size,
            },
        )
        return MemeImageGenerationResult(
            status=MemeImageStatus.GENERATED,
            mode=mode,
            storage_key=stored.storage_key,
            mime_type=response.mime_type,
            provider=response.provider,
            model_used=response.model_used,
            width=width,
            height=height,
            byte_size=stored.byte_size,
            sha256=stored.sha256,
            # Mock provider only as of M5 - always $0. A real provider's own PricingCatalog
            # entry/cost formula is added alongside whichever future milestone wires one in.
            cost_usd="0",
            attempt_count=attempt,
        )

    logger.warning(
        "meme_image_generation_exhausted_attempts",
        extra={"max_attempts": _MAX_GENERATION_ATTEMPTS, "error_code": last_error_code},
    )
    return MemeImageGenerationResult(
        status=MemeImageStatus.FAILED, mode=mode, error_code=last_error_code,
        attempt_count=_MAX_GENERATION_ATTEMPTS,
    )
