"""Phase V2.3 (docs/nnj_source_faithful_editorial_visual_recomposition_v1.md §15-17): the FIRST
production runtime consumer of the Phase V2.1/V2.2 image-edit infrastructure. A thin, fail-open
recomposition step for the NEWS presentation path only - never a second image-generation
architecture. `ImageGenerationGateway`/`ImageGenerationRequest`/`GeminiImageAdapter` remain
canonical and are called through, never duplicated or reimplemented here.

Gated by `settings.editorial_recomposition_mode` (core/config.py) - default `"off"`:
existing deployments with no new environment variable set behave byte-identically to before this
phase (`maybe_recompose()` returns the original bytes unchanged, zero gateway calls).

Model policy (locked in docs/nnj_source_faithful_editorial_visual_recomposition_v1.md §16-17):
`gemini-3.1-flash-image` only. On ANY failure at the recomposition boundary, this module fails
open to the caller's own original `source_image_bytes` - it NEVER falls back to
`gemini-3-pro-image` or `gpt-image-2` (a more creative/aggressive model is a higher factual-
mutation-risk path, not a safer fallback - see §17's own explicit rule).

Eligibility (Stage 6 - deterministic only, no new ML classifier): reuses
`services/image_quality.py`'s own already-calibrated `resolution_band()`/`aspect_ratio_band()`
functions - the only two deterministic signals reachable at this call site without refactoring
upstream media selection (`worker/content_cycle.py`'s own ranking step discards its
`MediaRankingResult` objects before the point this module is called - see the V2.3 phase's own
Stage 2 audit). No face/portrait detector exists anywhere in this codebase - eligibility is
DELIBERATELY NARROW (requires the single strongest resolution tier + editorial-landscape aspect
ratio) specifically because of this gap, not because those two signals alone prove "safe to
recompose" - this is a disclosed, real limitation, not a claim of portrait detection.

This module never selects media, never publishes, and never knows about Telegram - it accepts
already-selected `source_image_bytes` and returns either the recomposed bytes or the original
bytes, nothing else."""
from __future__ import annotations

import hashlib
import io
import time
from dataclasses import dataclass

from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError

from core.config import settings
from integrations.llm_gateway.image_protocol import (
    ImageGenerationGateway,
    ImageGenerationOperation,
    ImageGenerationRequest,
    ReferenceImage,
)
from integrations.llm_gateway.providers.gemini_image_adapter import (
    GEMINI_3_1_FLASH_IMAGE,
    GeminiImageAdapter,
    GeminiImageAdapterError,
)
from schemas.image_candidate import AspectRatioBand, ResolutionBand
from services.image_quality import aspect_ratio_band, resolution_band
from services.nnj_candidate_c_contract import build_overlay_aware_prompt_clause, load_candidate_c_geometry

_FORMAT_TO_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def build_recomposition_prompt() -> str:
    """Byte-identical to `scripts/nnj_visual_recomposition_bakeoff.py::build_recomposition_
    prompt()` - equality enforced by
    tests/test_v2_3_editorial_recomposition.py::test_prompt_matches_canonical_bakeoff_prompt.

    Phase V2.7 §6-7 (forensic finding + fix): the V2.2-era prompt this replaced permitted
    "replace background" and "re-light subtly" with no constraint on HOW MUCH background could
    change or how the real light source must be respected - a real, root-caused contributor to
    the V2.6 canary's own observed failure ("looks synthetic / concept-render-like... large
    generic gray studio background"). Its own MISSION line ("create a CLEANER composition") also
    implicitly invited aesthetic idealization over strict preservation. This version (still
    version-less/canonical per this module's own established convention, but a genuine content
    change, not a copyedit) tightens the contract to SOURCE-PRESERVING EDITING: the photographed
    factual foreground subject is immutable reference content wherever technically possible;
    factual fidelity has absolute priority over composition. No existing FORBIDDEN rule was
    removed - every one is still present, verbatim or consolidated; only new, stricter
    constraints were added (explicit background-replacement / light-source / restyling-as-render
    prohibitions, and the explicit "when uncertain, make a weaker edit" rule)."""
    return (
        "ROLE: You are the NNJ Source-Preserving Editorial Photo Editor.\n\n"
        "MISSION: The supplied source image is real, factual photography. Your task is "
        "source-preserving editing, not illustration or reinterpretation. Treat the photographed "
        "factual foreground subject as immutable reference content wherever technically "
        "possible. Preserving factual fidelity has absolute priority over composition.\n\n"
        "SOURCE FIDELITY: Treat the source image as the source of truth for people, devices, "
        "product appearance, event scenes, logos present in evidence, interfaces/screens, "
        "materials, colors, and the physical relationships between objects.\n\n"
        "SOURCE BRANDING PRESERVATION: If a publisher, outlet, or source credit mark - a "
        "watermark, logo, or credit line - is visible anywhere in the source image, it must "
        "remain present, in its original form, unchanged. Do not erase it, replace it, redraw "
        "it, translate it, or clean it up, even if reframing or background extension would "
        "otherwise make removing it convenient. This applies only to real, visible source/"
        "editorial branding - it does not forbid ordinary in-frame product screens or interface "
        "text, which SOURCE FIDELITY above already covers.\n\n"
        "ALLOWED: extend the existing background; clean minor clutter from the existing "
        "background; a modest whole-subject translation; a modest whole-subject uniform scale; "
        "a modest framing change; create negative space around the subject; global photographic "
        "color/exposure harmonization that does not change the factual appearance of the "
        "subject; reserve a calm lower branding zone.\n\n"
        "FORBIDDEN: rebuilding the product from scratch; redesigning the product; replacing the "
        "product with a visually similar object; changing product geometry; changing "
        "camera/sensor/button/port geometry; changing logos or labels; erasing, deleting, or "
        "redrawing a visible source/publisher watermark or credit mark; changing human identity; "
        "fabricating UI; hallucinating text; deleting real secondary physical objects merely for "
        "composition; changing hand anatomy; changing grip; inventing fingers; materially "
        "changing materials or colors; fully replacing the real background with an unrelated "
        "generic studio backdrop; restyling the photograph as a render, illustration, or concept "
        "image; changing the real light source direction or character beyond subtle, "
        "source-consistent harmonization; adding missing features; creating unsupported event "
        "details; creating fictional scenes that misrepresent the story.\n\n"
        "UNCERTAINTY RULE: If preserving the factual foreground subject while satisfying the "
        "requested composition is uncertain, preserve the source subject and make a weaker "
        "edit. Never sacrifice factual fidelity for a cleaner composition.\n\n"
        "BOTTOM SAFE ZONE: Leave a calm lower area free of crucial detail for deterministic NNJ "
        "branding applied downstream.\n\n"
        "TEXT RULE: Do not generate headlines, article text, fake interface text, exact "
        "statistics, or quote text.\n\n"
        "NNJ BRAND RULE: Do not generate NNJ branding, the NNJ logo, or the pulse line - all NNJ "
        "branding is deterministic and applied downstream, unchanged.\n\n"
        "FAIL-SAFE: If truthful recomposition is not possible, fall back conceptually to a "
        "cleaner crop-based treatment of the source image rather than fabricating details.\n\n"
        "OUTPUT: Only the recomposed visual. No explanations, no extra text, no branding."
    )


def build_overlay_aware_recomposition_prompt() -> str:
    """Phase V2.5 Stage 4 - the ONE authoritative prompt-building path for runtime recomposition:
    `build_recomposition_prompt()` above, byte-identical and never rewritten, plus the locked
    Candidate C spatial clause built from `services.nnj_candidate_c_contract` (the single source
    of truth for that geometry - never a second, hand-typed copy of the coordinates here). Proven
    end-to-end by the V2.4G canary (user-approved result) before this phase wired it into this
    module; `maybe_recompose()`'s live path calls this instead of `build_recomposition_prompt()`
    directly. The base factual-fidelity rules (SOURCE FIDELITY/ALLOWED/FORBIDDEN/NNJ BRAND RULE)
    are appended to, never replaced - Gemini is still never asked to draw NNJ branding, the pulse,
    or the logo itself; the appended clause only describes where NOT to place the factual subject
    so the deterministic Candidate C overlay applied downstream has clean space to sit in."""
    geometry = load_candidate_c_geometry()
    return build_recomposition_prompt() + "\n\n" + build_overlay_aware_prompt_clause(geometry)


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    reason: str


@dataclass(frozen=True)
class RecompositionResult:
    """`image_bytes` is ALWAYS populated - the recomposed bytes on success, the caller's own
    original `source_image_bytes` in every other case (mode off, ineligible, or any failure) -
    the fail-open contract (Stage 8) is encoded in the type itself, never left to the caller to
    remember.

    Phase V2.5 Stage 6 - `request_id`/`input_tokens`/`output_tokens`/`units`/`unit_type` extend
    this type to carry the real provider telemetry `ImageGenerationResponse`/`CapabilityUsage`
    already report (the V2.4 canary's own disclosed gap: the raw adapter response HAD this data,
    but nothing above it ever kept it). All five stay `None` on every path that never obtained a
    real response (mode off/dry_run, ineligible, or any failure) - never fabricated, never
    estimated. NEVER carries an API key, an authorization header, or a base64 image payload -
    only plain numeric/string telemetry, same discipline `CapabilityUsage` itself already
    established."""

    used_recomposed_image: bool
    image_bytes: bytes
    mode: str
    eligibility: EligibilityDecision
    provider: str | None
    model: str | None
    source_sha256: str
    result_sha256: str | None
    fallback_reason: str | None
    latency_ms: float | None
    request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    units: int | None = None
    unit_type: str | None = None

    def __repr__(self) -> str:
        # Never dumps image_bytes (module docstring's own "no raw bytes" rule, Stage 9) - the
        # default dataclass repr would otherwise print the full raw JPEG/PNG content.
        return (
            f"RecompositionResult(used_recomposed_image={self.used_recomposed_image!r}, "
            f"image_bytes=<{len(self.image_bytes)} bytes>, mode={self.mode!r}, "
            f"eligibility={self.eligibility!r}, provider={self.provider!r}, model={self.model!r}, "
            f"source_sha256={self.source_sha256!r}, result_sha256={self.result_sha256!r}, "
            f"fallback_reason={self.fallback_reason!r}, latency_ms={self.latency_ms!r}, "
            f"request_id={self.request_id!r}, input_tokens={self.input_tokens!r}, "
            f"output_tokens={self.output_tokens!r}, units={self.units!r}, unit_type={self.unit_type!r})"
        )

    __str__ = __repr__


def _decode_image_info(image_bytes: bytes) -> tuple[int, int, str] | None:
    """Returns (width, height, mime_type), or None if undecodable or an unsupported format."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            fmt = im.format
            width, height = im.size
    except UnidentifiedImageError:
        return None
    mime_type = _FORMAT_TO_MIME.get(fmt or "")
    if mime_type is None:
        return None
    return width, height, mime_type


_CORNERS: tuple[str, ...] = ("lower_right", "lower_left", "upper_right", "upper_left")
_CORNER_FRACTION_W = 0.22
_CORNER_FRACTION_H = 0.16
# Phase V2.10A - calibrated directly against the real V2.10 canary failure (the real robot-vacuum
# photo whose real "9TO5Google" watermark a Gemini recomposition deleted): that image's own four
# raw-resolution corners measured 15.33/16.39/12.71/4.81 (lower_right/lower_left/upper_right/
# upper_left) - three real corners carry genuine dense detail (the watermark itself, plus a bright
# floor-reflection streak and a couch/blur transition, which this coarse signal cannot tell apart
# from real branding - a disclosed limitation, not a claim of watermark-specific detection). The
# two other real, unrelated source photos this project has on disk (iPhone/Honor) measured a
# maximum of 5.83 across all four corners. 10.0 sits in the real, measured gap between those two
# clusters - not a round number chosen for convenience. A false positive here only ever means
# "skip recomposition, use ORIGINAL_SOURCE" - a safe degradation (ORIGINAL_SOURCE is a first-class
# result throughout this project), never a destructive one.
_BRANDING_RISK_EDGE_THRESHOLD = 10.0


def _corner_box(width: int, height: int, corner: str) -> tuple[int, int, int, int]:
    cw, ch = int(width * _CORNER_FRACTION_W), int(height * _CORNER_FRACTION_H)
    if corner == "lower_right":
        return (width - cw, height - ch, width, height)
    if corner == "lower_left":
        return (0, height - ch, cw, height)
    if corner == "upper_right":
        return (width - cw, 0, width, ch)
    return (0, 0, cw, ch)  # upper_left


def assess_pixel_branding_risk(source_image_bytes: bytes) -> str | None:
    """Phase V2.10A - a narrow, deterministic, PIL-only complement to `worker.content_cycle.
    assess_recomposition_source_risk()`'s own `possible_watermark` signal, which is URL/alt-text
    KEYWORD evidence only (services/image_quality.py's own disclosure: "no reliable cheap pixel
    signal for an actual watermark") and therefore cannot catch a real pixel watermark whose URL
    happens not to contain the word "watermark" - exactly the real V2.10 canary case. Measures
    real edge density (`ImageFilter.FIND_EDGES` mean) in each of the four corner regions a
    publisher/editorial watermark or credit mark conventionally occupies; returns the first corner
    name whose measured density is real, dense, logo/text-like content per
    `_BRANDING_RISK_EDGE_THRESHOLD`'s own calibration, else `None`. This is coarse pixel analysis
    of four small regions, not semantic vision or OCR - it cannot distinguish a real watermark from
    other genuinely busy photographic detail in the same corner (a disclosed limitation), and it
    never inspects the interior of the frame, so it cannot and does not flag ordinary in-frame
    product screens/UI text."""
    try:
        with Image.open(io.BytesIO(source_image_bytes)) as im:
            gray = im.convert("L")
            width, height = gray.size
    except UnidentifiedImageError:
        return None
    for corner in _CORNERS:
        box = _corner_box(width, height, corner)
        if box[2] <= box[0] or box[3] <= box[1]:
            continue  # degenerate box on a tiny image - nothing to measure
        edges = gray.crop(box).filter(ImageFilter.FIND_EDGES)
        if ImageStat.Stat(edges).mean[0] >= _BRANDING_RISK_EDGE_THRESHOLD:
            return corner
    return None


def evaluate_eligibility(source_image_bytes: bytes) -> EligibilityDecision:
    """Deterministic-only, narrow by design (module docstring). Requires the single strongest
    resolution tier (`ResolutionBand.GOOD`, shortest side >= 600px per services/image_quality.py's
    own calibration) and an editorial-landscape aspect ratio - both real, already-calibrated
    signals, never a new threshold invented for this phase. Phase V2.10A adds one more
    deterministic gate: `assess_pixel_branding_risk()` - see that function's own docstring for why
    it exists and its disclosed limitations."""
    info = _decode_image_info(source_image_bytes)
    if info is None:
        return EligibilityDecision(False, "undecodable_or_unsupported_format")
    width, height, _mime_type = info
    if resolution_band(width, height) != ResolutionBand.GOOD:
        return EligibilityDecision(False, "resolution_band_not_good")
    if aspect_ratio_band(width / height) != AspectRatioBand.EDITORIAL_LANDSCAPE:
        return EligibilityDecision(False, "aspect_ratio_not_editorial_landscape")
    branding_risk_corner = assess_pixel_branding_risk(source_image_bytes)
    if branding_risk_corner is not None:
        return EligibilityDecision(False, f"possible_source_branding_pixel_risk_{branding_risk_corner}")
    return EligibilityDecision(True, "good_resolution_editorial_landscape_candidate")


def _fail_open(
    *, mode: str, eligibility: EligibilityDecision, source_image_bytes: bytes, source_sha256: str,
    provider: str | None = None, model: str | None = None, fallback_reason: str | None = None,
    latency_ms: float | None = None,
) -> RecompositionResult:
    return RecompositionResult(
        used_recomposed_image=False, image_bytes=source_image_bytes, mode=mode, eligibility=eligibility,
        provider=provider, model=model, source_sha256=source_sha256, result_sha256=None,
        fallback_reason=fallback_reason, latency_ms=latency_ms,
    )


async def maybe_recompose(
    *, source_image_bytes: bytes, gateway: ImageGenerationGateway | None = None,
) -> RecompositionResult:
    """The one entry point `worker/content_cycle.py` calls. Never raises - every failure at this
    boundary (Stage 8's own exhaustive list: provider error, timeout, malformed response, invalid
    MIME, undecodable image, empty image, unsupported operation, budget/safety rejection, any
    unexpected exception) resolves to a `RecompositionResult` carrying the ORIGINAL bytes.

    `gateway` is injectable for tests only - production callers never pass it; a real
    `GeminiImageAdapter` is constructed internally when eligible and mode is `"live"`."""
    mode = settings.editorial_recomposition_mode
    source_sha256 = hashlib.sha256(source_image_bytes).hexdigest()

    if mode == "off":
        return _fail_open(
            mode="off", eligibility=EligibilityDecision(False, "mode_off"),
            source_image_bytes=source_image_bytes, source_sha256=source_sha256,
        )

    eligibility = evaluate_eligibility(source_image_bytes)
    if not eligibility.eligible:
        return _fail_open(
            mode=mode, eligibility=eligibility, source_image_bytes=source_image_bytes, source_sha256=source_sha256,
        )

    if mode == "dry_run":
        return _fail_open(
            mode="dry_run", eligibility=eligibility, source_image_bytes=source_image_bytes,
            source_sha256=source_sha256, provider="gemini", model=GEMINI_3_1_FLASH_IMAGE,
        )

    # mode == "live"
    info = _decode_image_info(source_image_bytes)
    assert info is not None  # eligibility already proved this decodes and has a supported MIME
    _width, _height, mime_type = info

    adapter = gateway
    if adapter is None:
        api_key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
        if not api_key:
            return _fail_open(
                mode="live", eligibility=eligibility, source_image_bytes=source_image_bytes,
                source_sha256=source_sha256, provider="gemini", model=GEMINI_3_1_FLASH_IMAGE,
                fallback_reason="gemini_api_key_absent",
            )
        adapter = GeminiImageAdapter(model_id=GEMINI_3_1_FLASH_IMAGE, api_key=api_key)

    request = ImageGenerationRequest(
        prompt=build_overlay_aware_recomposition_prompt(), operation=ImageGenerationOperation.IMAGE_EDIT,
        reference_images=(ReferenceImage(data=source_image_bytes, mime_type=mime_type),),
        target_aspect_ratio="16:9",
    )

    started = time.monotonic()
    try:
        response = await adapter.generate_image(request)
    except GeminiImageAdapterError as exc:
        return _fail_open(
            mode="live", eligibility=eligibility, source_image_bytes=source_image_bytes,
            source_sha256=source_sha256, provider="gemini", model=GEMINI_3_1_FLASH_IMAGE,
            fallback_reason=f"{type(exc).__name__}", latency_ms=(time.monotonic() - started) * 1000,
        )
    except Exception as exc:  # noqa: BLE001 - Stage 8's own explicit "catch failures only at the
        # appropriate recomposition boundary" - this IS that boundary; never lets an unexpected
        # provider/gateway exception escape and block the NEWS send path.
        return _fail_open(
            mode="live", eligibility=eligibility, source_image_bytes=source_image_bytes,
            source_sha256=source_sha256, provider="gemini", model=GEMINI_3_1_FLASH_IMAGE,
            fallback_reason=f"unexpected_error:{type(exc).__name__}", latency_ms=(time.monotonic() - started) * 1000,
        )
    latency_ms = (time.monotonic() - started) * 1000

    if not response.image_bytes:
        return _fail_open(
            mode="live", eligibility=eligibility, source_image_bytes=source_image_bytes,
            source_sha256=source_sha256, provider="gemini", model=GEMINI_3_1_FLASH_IMAGE,
            fallback_reason="empty_image", latency_ms=latency_ms,
        )
    try:
        with Image.open(io.BytesIO(response.image_bytes)) as im:
            im.load()
    except (UnidentifiedImageError, OSError):
        return _fail_open(
            mode="live", eligibility=eligibility, source_image_bytes=source_image_bytes,
            source_sha256=source_sha256, provider="gemini", model=GEMINI_3_1_FLASH_IMAGE,
            fallback_reason="undecodable_result_image", latency_ms=latency_ms,
        )

    result_sha256 = hashlib.sha256(response.image_bytes).hexdigest()
    usage = response.usage
    return RecompositionResult(
        used_recomposed_image=True, image_bytes=response.image_bytes, mode="live", eligibility=eligibility,
        provider="gemini", model=GEMINI_3_1_FLASH_IMAGE, source_sha256=source_sha256,
        result_sha256=result_sha256, fallback_reason=None, latency_ms=latency_ms,
        request_id=response.request_id,
        input_tokens=usage.input_tokens if usage is not None else None,
        output_tokens=usage.output_tokens if usage is not None else None,
        units=usage.units if usage is not None else None,
        unit_type=usage.unit_type if usage is not None else None,
    )
