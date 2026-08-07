"""Phase 16 M3: deterministic editorial-quality signals (docs/phase16_m3_quality_and_deduplication_
report.md). Pure analysis logic only - no networking (M2's integrations/http/safe_fetch.py owns
that), no persistence. Operates on the same already-fetched, already byte-bounded image bytes M2's
services/image_validation.py already validated - reused in-memory, never re-fetched over the
network (a second lightweight in-memory decode, not a second HTTP request).

Deliberately separate from technical validation (TECHNICALLY VALID, M2) and any future semantic
relevance ranking (M4) - this module answers only "is this technically-valid image editorially
USABLE," never "is it relevant to this specific story."
"""
import io
import logging
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from PIL import Image, ImageOps, UnidentifiedImageError

from schemas.image_candidate import (
    AspectRatioBand,
    ImageCandidate,
    ImageDiscoveryMethod,
    QualitySignals,
    ResolutionBand,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dimension / aspect-ratio bands (docs/phase16_m3_quality_and_deduplication_report.md §8/§9 -
# calibrated against M2's own 34-image bounded-validation sample plus generated fixtures).
# ---------------------------------------------------------------------------

_TRACKING_MAX_SHORTEST_SIDE = 3
_TRACKING_MAX_PIXELS = 16
_ICON_MAX_SIDE = 64
_FAVICON_EVIDENCE_MAX_SIDE = 128
_WEAK_MAX_SHORTEST_SIDE = 300
_GOOD_MIN_SHORTEST_SIDE = 600

_ULTRA_EXTREME_RATIO_LOW = 0.05
_ULTRA_EXTREME_RATIO_HIGH = 20.0
_EXTREME_TALL_RATIO = 0.2
_PORTRAIT_RATIO = 0.75
_SQUARE_RATIO = 1.33
_EDITORIAL_LANDSCAPE_RATIO = 2.2
_WIDE_BANNER_RATIO = 5.0


def resolution_band(width: int, height: int) -> ResolutionBand:
    shortest = min(width, height)
    pixel_count = width * height
    if shortest <= _TRACKING_MAX_SHORTEST_SIDE or pixel_count <= _TRACKING_MAX_PIXELS:
        return ResolutionBand.TRACKING
    if shortest <= _ICON_MAX_SIDE:
        return ResolutionBand.ICON
    if shortest < _WEAK_MAX_SHORTEST_SIDE:
        return ResolutionBand.WEAK
    if shortest >= _GOOD_MIN_SHORTEST_SIDE:
        return ResolutionBand.GOOD
    return ResolutionBand.ADEQUATE


def aspect_ratio_band(ratio: float) -> AspectRatioBand:
    if ratio <= _EXTREME_TALL_RATIO:
        return AspectRatioBand.EXTREME_TALL
    if ratio <= _PORTRAIT_RATIO:
        return AspectRatioBand.PORTRAIT
    if ratio <= _SQUARE_RATIO:
        return AspectRatioBand.SQUARE
    if ratio <= _EDITORIAL_LANDSCAPE_RATIO:
        return AspectRatioBand.EDITORIAL_LANDSCAPE
    if ratio <= _WIDE_BANNER_RATIO:
        return AspectRatioBand.WIDE_BANNER
    return AspectRatioBand.EXTREME_WIDE


# ---------------------------------------------------------------------------
# URL/filename/metadata token signals - word-boundary-aware, case-insensitive.
# ---------------------------------------------------------------------------

_LOGO_TOKENS = ("logo", "logotype", "лого")
_ICON_TOKENS = ("favicon", "icon", "apple-touch-icon", "sprite")
_AVATAR_TOKENS = ("avatar", "profile", "author", "userpic", "аватар")
_BANNER_TOKENS = ("banner", "ad", "ads", "advert", "advertisement", "sponsor", "sponsored", "промо", "реклама")
_PLACEHOLDER_TOKENS = ("placeholder", "default", "no-image", "noimage", "no_image", "blank", "stub", "заглушка")
_TRACKING_TOKENS = ("pixel", "tracking", "beacon", "spacer")
_THUMBNAIL_TOKENS = ("thumbnail", "thumb")
# Phase 19 M9: watermark-token / screenshot-token evidence - same word-boundary-aware, case-
# insensitive convention as every token set above.
_WATERMARK_TOKENS = ("watermark", "watermarked", "wm-overlay", "водяной", "копирайт")
_SCREENSHOT_TOKENS = ("screenshot", "screen-shot", "scrnshot", "screengrab", "скриншот")


def _compile_token_pattern(tokens: tuple[str, ...]) -> re.Pattern[str]:
    """`\\b` triggers correctly around `-`/`_`/`.`/`/` (all non-word characters), so "app-icon"
    matches `\\bicon\\b` while "catalogo" does NOT match `\\blogo\\b` (no boundary between the
    shared word characters) - verified directly, not assumed (M3 report §10)."""
    escaped = "|".join(re.escape(token) for token in tokens)
    return re.compile(rf"\b(?:{escaped})\b", re.IGNORECASE)


_LOGO_PATTERN = _compile_token_pattern(_LOGO_TOKENS)
_ICON_PATTERN = _compile_token_pattern(_ICON_TOKENS)
_AVATAR_PATTERN = _compile_token_pattern(_AVATAR_TOKENS)
_BANNER_PATTERN = _compile_token_pattern(_BANNER_TOKENS)
_PLACEHOLDER_PATTERN = _compile_token_pattern(_PLACEHOLDER_TOKENS)
_TRACKING_PATTERN = _compile_token_pattern(_TRACKING_TOKENS)
_THUMBNAIL_PATTERN = _compile_token_pattern(_THUMBNAIL_TOKENS)
_WATERMARK_PATTERN = _compile_token_pattern(_WATERMARK_TOKENS)
_SCREENSHOT_PATTERN = _compile_token_pattern(_SCREENSHOT_TOKENS)


def _searchable_text(url: str | None, alt_text: str | None) -> str:
    """Path + query only - deliberately excludes the hostname (a CDN subdomain that happens to
    contain a generic word, e.g. "logo-cdn.example.com" hosting entirely legitimate hero images,
    must not be flagged - conservative by design, M3 report §10)."""
    parts = [alt_text or ""]
    if url:
        try:
            parsed = urlsplit(url)
            parts.append(parsed.path or "")
            parts.append(parsed.query or "")
        except ValueError:
            pass  # malformed URL - signal extraction degrades to alt_text only, never crashes
    return " ".join(parts)


@dataclass(frozen=True)
class _TokenMatches:
    logo: bool = False
    icon: bool = False
    avatar: bool = False
    banner: bool = False
    placeholder: bool = False
    tracking: bool = False
    thumbnail: bool = False
    watermark: bool = False
    screenshot: bool = False


def _match_tokens(text: str) -> _TokenMatches:
    return _TokenMatches(
        logo=bool(_LOGO_PATTERN.search(text)),
        icon=bool(_ICON_PATTERN.search(text)),
        avatar=bool(_AVATAR_PATTERN.search(text)),
        banner=bool(_BANNER_PATTERN.search(text)),
        placeholder=bool(_PLACEHOLDER_PATTERN.search(text)),
        tracking=bool(_TRACKING_PATTERN.search(text)),
        thumbnail=bool(_THUMBNAIL_PATTERN.search(text)),
        watermark=bool(_WATERMARK_PATTERN.search(text)),
        screenshot=bool(_SCREENSHOT_PATTERN.search(text)),
    )


# ---------------------------------------------------------------------------
# Cheap pixel statistics (same decoded image, no extra fetch/decode) - only ever one input among
# several combined signals, never sufficient alone (M3 task brief's own explicit warning against
# classifying minimalist illustrations as placeholders from color statistics alone).
# ---------------------------------------------------------------------------


def _dominant_color_ratio(image: Image.Image) -> float | None:
    try:
        small = image.convert("RGB").resize((32, 32), Image.Resampling.NEAREST)
        colors = small.getcolors(maxcolors=32 * 32)
        if not colors:
            return None
        total = sum(count for count, _ in colors)
        dominant = max(count for count, _ in colors)
        return dominant / total if total else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Phase 19 M9: two more cheap, deterministic, Pillow-only pixel heuristics - same "one input
# among several combined signals, never sufficient alone" discipline as _dominant_color_ratio
# above. Explicitly disclosed scope (docs/phase19_m9_media_prefilter_notes.md): a cheap
# deterministic obvious-case filter, not a general watermark/UI detector - M13's future vision
# review is where a real refinement would live.
# ---------------------------------------------------------------------------

_TV_ASPECT_RATIO_LOW = 1.7
_TV_ASPECT_RATIO_HIGH = 1.85
_LOWER_THIRD_BAND_FRACTION = 0.22
_LOWER_THIRD_VARIANCE_RATIO_MAX = 0.35

_SCREENSHOT_FLAT_ROW_FRACTION_THRESHOLD = 0.25
_SCREENSHOT_FLAT_ROW_FRACTION_WITH_TOKEN = 0.15
_FLAT_ROW_VARIANCE_MAX = 30.0


def _band_variance(image: Image.Image, y0_frac: float, y1_frac: float) -> float | None:
    """Mean grayscale variance of a horizontal band of the image - a flat, low-variance band is
    consistent with a solid/gradient graphic bar (a TV lower-third, a UI toolbar), never proof of
    one (a plain sky or wall crop looks identical to this cheap statistic - conservative by
    design, only ever combined with other signals as a soft possible_* warning)."""
    try:
        gray = image.convert("L")
        width, height = gray.size
        y0 = int(height * y0_frac)
        y1 = max(y0 + 1, int(height * y1_frac))
        band = gray.crop((0, y0, width, y1)).resize((32, 8), Image.Resampling.NEAREST)
        pixels = list(band.getdata())
        if not pixels:
            return None
        mean = sum(pixels) / len(pixels)
        return sum((p - mean) ** 2 for p in pixels) / len(pixels)
    except Exception:
        return None


def _looks_like_tv_lower_third(image: Image.Image, ratio: float) -> bool:
    """Conservative TV/lower-third heuristic: a 16:9-ish frame whose bottom band is markedly
    flatter than the frame's middle - the shape of a text/graphic bar overlaid on broadcast
    footage. Ambiguous by nature (a legitimate photo with a plain-colored bottom crop scores the
    same) - always a soft possible_* signal, never a hard rejection."""
    if not (_TV_ASPECT_RATIO_LOW <= ratio <= _TV_ASPECT_RATIO_HIGH):
        return False
    bottom_variance = _band_variance(image, 1 - _LOWER_THIRD_BAND_FRACTION, 1.0)
    middle_variance = _band_variance(image, 0.35, 0.65)
    if bottom_variance is None or middle_variance is None or middle_variance <= 0:
        return False
    return bottom_variance < middle_variance * _LOWER_THIRD_VARIANCE_RATIO_MAX


def _flat_row_fraction(image: Image.Image) -> float | None:
    """Fraction of sampled rows (on a downsampled 64x64 grayscale canvas) whose pixel variance is
    near-zero - UI chrome (toolbars, scrollbars, flat-color panels) produces far more of these
    than typical editorial photography, but so does a plain sky/studio backdrop - again, always
    combined with other evidence, never a hard rejection on its own."""
    try:
        gray = image.convert("L").resize((64, 64), Image.Resampling.NEAREST)
        width, height = gray.size
        pixels = list(gray.getdata())
        flat_rows = 0
        for row in range(height):
            row_pixels = pixels[row * width:(row + 1) * width]
            mean = sum(row_pixels) / len(row_pixels)
            variance = sum((p - mean) ** 2 for p in row_pixels) / len(row_pixels)
            if variance < _FLAT_ROW_VARIANCE_MAX:
                flat_rows += 1
        return flat_rows / height
    except Exception:
        return None


def _looks_like_branded_screenshot(flat_row_fraction: float | None, has_screenshot_token: bool) -> bool:
    """Requires a lower flat-row bar when corroborated by URL/alt-text evidence (`screenshot`
    etc.), a higher bar when relying on the pixel signal alone - conservative, ambiguous-by-
    design, always REVIEW-worthy rather than a hard rejection."""
    if flat_row_fraction is None:
        return False
    threshold = (
        _SCREENSHOT_FLAT_ROW_FRACTION_WITH_TOKEN if has_screenshot_token
        else _SCREENSHOT_FLAT_ROW_FRACTION_THRESHOLD
    )
    return flat_row_fraction >= threshold


# ---------------------------------------------------------------------------
# Hard rejection / soft signal assembly.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QualityAnalysis:
    """Internal result of analyzing one candidate's decoded image - services/image_intelligence.py
    combines this with deduplication.py's cluster assignment to build the final QualityValidation
    (dedup fields are attached separately, after all of one event's candidates are analyzed)."""

    signals: QualitySignals
    hard_rejection_reasons: list[str]
    quality_warnings: list[str]
    quality_components: dict[str, int]
    quality_penalties: dict[str, int]
    quality_score: int
    perceptual_hash: str | None
    duration_ms: int
    decode_error: str | None = None


_DISCOVERY_METADATA_CONFIDENCE: dict[ImageDiscoveryMethod, int] = {
    ImageDiscoveryMethod.TELEGRAM_PHOTO: 20,
    ImageDiscoveryMethod.TELEGRAM_DOCUMENT: 20,
    ImageDiscoveryMethod.OPEN_GRAPH_SECURE_IMAGE: 20,
    ImageDiscoveryMethod.OPEN_GRAPH_IMAGE: 18,
    ImageDiscoveryMethod.RSS_MEDIA_CONTENT: 18,
    ImageDiscoveryMethod.JSONLD_ARTICLE_IMAGE: 16,
    ImageDiscoveryMethod.RSS_ENCLOSURE: 14,
    ImageDiscoveryMethod.TWITTER_IMAGE: 14,
    ImageDiscoveryMethod.RSS_MEDIA_THUMBNAIL: 10,
    ImageDiscoveryMethod.RSS_INLINE_IMAGE: 10,
    ImageDiscoveryMethod.IMAGE_SRC_LINK: 10,
    ImageDiscoveryMethod.TELEGRAM_THUMBNAIL: 10,
    ImageDiscoveryMethod.SOURCE_NATIVE_UNKNOWN: 5,
}

_RESOLUTION_COMPONENT: dict[ResolutionBand, int] = {
    ResolutionBand.TRACKING: 0,
    ResolutionBand.ICON: 5,
    ResolutionBand.WEAK: 15,
    ResolutionBand.ADEQUATE: 28,
    ResolutionBand.GOOD: 40,
}

_ASPECT_RATIO_COMPONENT: dict[AspectRatioBand, int] = {
    AspectRatioBand.EXTREME_TALL: 5,
    AspectRatioBand.PORTRAIT: 15,
    AspectRatioBand.SQUARE: 15,
    AspectRatioBand.EDITORIAL_LANDSCAPE: 20,
    AspectRatioBand.WIDE_BANNER: 12,
    AspectRatioBand.EXTREME_WIDE: 5,
}


def compute_dhash(image: Image.Image, hash_size: int = 8) -> str:
    """Difference hash (dHash): resize to (hash_size+1, hash_size), grayscale, compare each pixel
    to its right neighbor. Chosen over average-hash/pHash (M3 report §16) for: robust to resize
    and JPEG recompression (both preserve relative gradients even though absolute pixel values
    shift), naturally SENSITIVE to cropping (a crop changes which gradients exist at all, so
    distinct-but-related crops are correctly NOT collapsed - the M3 task brief's own explicit
    requirement), trivial Pillow-only implementation (no numpy), and cheap (72-pixel resize,
    64 comparisons). EXIF orientation is normalized first so a rotated copy of the same photo
    still hashes identically."""
    normalized = ImageOps.exif_transpose(image) or image
    grayscale = normalized.convert("L")
    resized = grayscale.resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    pixels = list(resized.getdata())
    value = 0
    for row in range(hash_size):
        row_start = row * (hash_size + 1)
        for col in range(hash_size):
            left = pixels[row_start + col]
            right = pixels[row_start + col + 1]
            value = (value << 1) | (1 if left > right else 0)
    return f"{value:0{hash_size * hash_size // 4}x}"


def hamming_distance(hash_a: str, hash_b: str) -> int:
    return bin(int(hash_a, 16) ^ int(hash_b, 16)).count("1")


def analyze_candidate(data: bytes, *, candidate: ImageCandidate) -> QualityAnalysis:
    """The sole per-candidate entry point. Never raises - a decode failure (should not happen
    here, since the caller only invokes this for M2-VALIDATED candidates, but defensively handled
    anyway) returns a QualityAnalysis with `decode_error` set and every signal at its safe,
    neutral default."""
    start = time.monotonic()
    technical = candidate.technical_validation
    width = technical.width if technical else None
    height = technical.height if technical else None

    image: Image.Image | None = None
    try:
        image = Image.open(io.BytesIO(data))
        if width is None or height is None:
            width, height = image.size

        text = _searchable_text(candidate.remote_url, candidate.alt_text)
        tokens = _match_tokens(text)
        dominant_ratio = _dominant_color_ratio(image)
        phash = compute_dhash(image)
        ratio = width / height if height else 1.0
        tv_lower_third = _looks_like_tv_lower_third(image, ratio)
        flat_row_fraction = _flat_row_fraction(image)
        branded_screenshot = _looks_like_branded_screenshot(flat_row_fraction, tokens.screenshot)

        return _assemble_analysis(
            candidate=candidate, width=width, height=height, tokens=tokens,
            dominant_ratio=dominant_ratio, perceptual_hash=phash, start=start,
            tv_lower_third=tv_lower_third, branded_screenshot=branded_screenshot,
        )
    except (UnidentifiedImageError, OSError) as error:
        logger.warning("quality_analysis_decode_failed", extra={"candidate_id": candidate.candidate_id})
        return _neutral_analysis(candidate, start=start, decode_error=type(error).__name__)
    except Exception:
        logger.warning("quality_analysis_unexpected_error", extra={"candidate_id": candidate.candidate_id})
        return _neutral_analysis(candidate, start=start, decode_error="internal_quality_error")
    finally:
        if image is not None:
            image.close()


def _neutral_analysis(candidate: ImageCandidate, *, start: float, decode_error: str) -> QualityAnalysis:
    signals = QualitySignals(resolution_band=ResolutionBand.WEAK, aspect_ratio_band=AspectRatioBand.SQUARE)
    return QualityAnalysis(
        signals=signals, hard_rejection_reasons=[], quality_warnings=["quality_analysis_failed"],
        quality_components={}, quality_penalties={}, quality_score=0, perceptual_hash=None,
        duration_ms=int((time.monotonic() - start) * 1000), decode_error=decode_error,
    )


def _assemble_analysis(
    *, candidate: ImageCandidate, width: int, height: int, tokens: _TokenMatches,
    dominant_ratio: float | None, perceptual_hash: str, start: float,
    tv_lower_third: bool = False, branded_screenshot: bool = False,
) -> QualityAnalysis:
    res_band = resolution_band(width, height)
    ratio = width / height if height else 1.0
    ar_band = aspect_ratio_band(ratio)

    hard_reject: list[str] = []
    warnings: list[str] = []

    # --- hard rejection (docs §5/§7 - conservative, combination-of-evidence only) ---
    if res_band == ResolutionBand.TRACKING:
        hard_reject.append("tracking_pixel_dimensions")
    if width <= _ICON_MAX_SIDE and height <= _ICON_MAX_SIDE and res_band != ResolutionBand.TRACKING:
        hard_reject.append("favicon_dimensions")
    elif width <= _FAVICON_EVIDENCE_MAX_SIDE and height <= _FAVICON_EVIDENCE_MAX_SIDE and (tokens.icon or tokens.tracking):
        hard_reject.append("favicon_with_url_evidence")
    if ratio <= _ULTRA_EXTREME_RATIO_LOW or ratio >= _ULTRA_EXTREME_RATIO_HIGH:
        hard_reject.append("extreme_aspect_ratio")
    if tokens.tracking and res_band in (ResolutionBand.TRACKING, ResolutionBand.ICON):
        hard_reject.append("tracking_pixel_evidence")
    strong_placeholder = tokens.placeholder and (
        res_band in (ResolutionBand.TRACKING, ResolutionBand.ICON)
        or (dominant_ratio is not None and dominant_ratio > 0.97)
    )
    if strong_placeholder:
        hard_reject.append("placeholder_strong_evidence")

    # --- soft signals (possible_*, conservative - never confirmed_*) ---
    possible_icon = tokens.icon and not hard_reject
    possible_logo = tokens.logo or (res_band == ResolutionBand.ADEQUATE and ar_band == AspectRatioBand.SQUARE and dominant_ratio is not None and dominant_ratio > 0.6)
    possible_avatar = tokens.avatar or (ar_band == AspectRatioBand.SQUARE and res_band in (ResolutionBand.WEAK, ResolutionBand.ADEQUATE) and tokens.avatar)
    # WIDE_BANNER alone is not sufficient evidence - legitimate editorial hero crops (e.g. 21:9-ish
    # landscape photos) commonly land in this band with no ad/banner intent. Require corroborating
    # URL/alt-text evidence at that band; only the more pathological EXTREME_WIDE band (>5.0) is
    # treated as suspicious on aspect ratio alone (bounded validation: ammoniaenergy.org 1019x438,
    # ratio 2.33, no banner token - a legitimate wide hero was being flagged before this change).
    possible_banner = tokens.banner or ar_band == AspectRatioBand.EXTREME_WIDE
    possible_placeholder = tokens.placeholder and not strong_placeholder
    possible_tracking_pixel = res_band == ResolutionBand.TRACKING
    # Phase 19 M9: watermark is token-evidence-only (no reliable cheap pixel signal for an
    # overlay that could be anywhere in the frame, any color, any opacity) - deliberately
    # conservative, corroborating URL/alt-text evidence required.
    possible_watermark = tokens.watermark
    possible_tv_lower_third = tv_lower_third
    possible_branded_screenshot = branded_screenshot

    if possible_logo:
        warnings.append("possible_logo")
    if possible_icon:
        warnings.append("possible_icon")
    if possible_avatar:
        warnings.append("possible_avatar")
    if possible_banner:
        warnings.append("possible_banner")
    if possible_placeholder:
        warnings.append("possible_placeholder")
    if tokens.thumbnail:
        warnings.append("possible_thumbnail")
    if possible_watermark:
        warnings.append("possible_watermark")
    if possible_tv_lower_third:
        warnings.append("possible_tv_lower_third")
    if possible_branded_screenshot:
        warnings.append("possible_branded_screenshot")

    signals = QualitySignals(
        resolution_band=res_band, aspect_ratio_band=ar_band,
        possible_tracking_pixel=possible_tracking_pixel, possible_icon=possible_icon,
        possible_logo=possible_logo, possible_avatar=possible_avatar,
        possible_banner=possible_banner, possible_placeholder=possible_placeholder,
        possible_watermark=possible_watermark, possible_tv_lower_third=possible_tv_lower_third,
        possible_branded_screenshot=possible_branded_screenshot,
    )

    components = {
        "resolution": _RESOLUTION_COMPONENT[res_band],
        "aspect_ratio": _ASPECT_RATIO_COMPONENT[ar_band],
        "technical_integrity": _technical_integrity_component(candidate),
        "metadata_confidence": _metadata_confidence_component(candidate),
    }
    penalties: dict[str, int] = {}
    if possible_logo:
        penalties["possible_logo"] = -15
    if possible_avatar:
        penalties["possible_avatar"] = -10
    if possible_banner:
        penalties["possible_banner"] = -12
    if possible_icon:
        penalties["possible_icon"] = -10
    if possible_placeholder:
        penalties["possible_placeholder"] = -20
    if tokens.thumbnail:
        penalties["possible_thumbnail"] = -5
    if possible_watermark:
        penalties["possible_watermark"] = -12
    if possible_tv_lower_third:
        penalties["possible_tv_lower_third"] = -10
    if possible_branded_screenshot:
        penalties["possible_branded_screenshot"] = -15

    raw_score = sum(components.values()) + sum(penalties.values())
    score = max(0, min(100, raw_score))

    return QualityAnalysis(
        signals=signals, hard_rejection_reasons=hard_reject, quality_warnings=warnings,
        quality_components=components, quality_penalties=penalties, quality_score=score,
        perceptual_hash=perceptual_hash, duration_ms=int((time.monotonic() - start) * 1000),
    )


def _technical_integrity_component(candidate: ImageCandidate) -> int:
    technical = candidate.technical_validation
    if technical is None or technical.width is None or technical.height is None:
        return 10  # neutral - missing metadata must not be penalized as if it were bad (never a bonus either)
    declared_w, declared_h = candidate.declared_width, candidate.declared_height
    if declared_w is None or declared_h is None:
        return 20  # nothing to cross-check against - full credit, not a bonus for absence
    width_ok = abs(technical.width - declared_w) <= max(2, round(declared_w * 0.05))
    height_ok = abs(technical.height - declared_h) <= max(2, round(declared_h * 0.05))
    return 20 if (width_ok and height_ok) else 10


def _metadata_confidence_component(candidate: ImageCandidate) -> int:
    base = _DISCOVERY_METADATA_CONFIDENCE.get(candidate.discovery_method, 5)
    if candidate.alt_text and len(candidate.alt_text.strip()) >= 3:
        base = min(20, base + 2)
    return base
