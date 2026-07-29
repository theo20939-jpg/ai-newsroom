"""Phase 16 M2: technical image validation (docs/phase16_m2_secure_fetch_and_validation_report.md
§12/§13). Pure decode/validation logic only - no networking (integrations/http/safe_fetch.py owns
that boundary entirely) and no persistence. Operates on already-fetched, already byte-bounded
image bytes; never touches a database session, a workflow object, or the network.
"""
import io
import logging
import time

from PIL import Image, UnidentifiedImageError

from integrations.http.safe_fetch import sha256_hex
from schemas.image_candidate import TechnicalValidation

logger = logging.getLogger(__name__)

# Raster formats this milestone actually decodes and accepts - SVG is explicitly excluded (never
# reaches Pillow at all, rejected by signature alone) and no PDF/EPS/PostScript/ICO/video/audio
# format is ever attempted.
_SUPPORTED_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "GIF"})


def _sniff_signature(data: bytes) -> str | None:
    """Magic-byte signature only - never trusts a declared Content-Type or URL extension. Returns
    None for anything unrecognized (including PDF/EPS/PostScript/ICO/video/audio - all correctly
    fall through to `unsupported_format` without ever reaching the decoder)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    head = data[:512].lstrip().lower()
    if head.startswith(b"<?xml") or head.startswith(b"<svg") or b"<svg" in head[:200]:
        return "image/svg+xml"
    if head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<html" in head[:100]:
        return "text/html"
    return None


def _duration_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def validate_image_bytes(data: bytes, *, max_pixels: int) -> TechnicalValidation:
    """Never raises - every failure mode returns a `TechnicalValidation` with `error_code` set,
    so the caller (services/image_intelligence.py) never needs a try/except around this call.
    `final_url`/`http_status`/`redirect_count` are left at their defaults here; the caller fills
    them in from the `SafeFetchResult` that produced `data`, since this function has no network
    context at all.
    """
    start = time.monotonic()
    byte_size = len(data)
    sha256 = sha256_hex(data)
    signature_mime = _sniff_signature(data)

    if signature_mime == "image/svg+xml":
        return TechnicalValidation(
            observed_mime=signature_mime, byte_size=byte_size, sha256=sha256,
            error_code="svg_rejected", duration_ms=_duration_ms(start),
        )
    if signature_mime == "text/html":
        # An HTML error/interstitial page served with an image URL - never HTML disguised as an
        # accepted image, regardless of what Content-Type the server declared.
        return TechnicalValidation(
            observed_mime=signature_mime, byte_size=byte_size, sha256=sha256,
            error_code="signature_mismatch", duration_ms=_duration_ms(start),
        )
    if signature_mime is None:
        return TechnicalValidation(
            byte_size=byte_size, sha256=sha256,
            error_code="unsupported_format", duration_ms=_duration_ms(start),
        )

    image: Image.Image | None = None
    try:
        image = Image.open(io.BytesIO(data))
        width, height = image.size
        pixel_count = width * height

        # Decompression-bomb protection: checked from the lazily-parsed header (Image.open() does
        # not decode pixel data), strictly before .load() ever runs - never disables Pillow's own
        # independent MAX_IMAGE_PIXELS protection, which stays at its library default as a second,
        # untouched layer.
        if pixel_count > max_pixels:
            return TechnicalValidation(
                observed_mime=signature_mime, width=width, height=height, pixel_count=pixel_count,
                byte_size=byte_size, sha256=sha256,
                error_code="pixel_limit_exceeded", duration_ms=_duration_ms(start),
            )

        image.load()  # forces full decode - raises on corrupt/truncated data
        format_name = image.format or ""
        if format_name not in _SUPPORTED_FORMATS:
            return TechnicalValidation(
                observed_mime=signature_mime, format=format_name, width=width, height=height,
                pixel_count=pixel_count, byte_size=byte_size, sha256=sha256,
                error_code="unsupported_format", duration_ms=_duration_ms(start),
            )

        animated = bool(getattr(image, "is_animated", False))
        frame_count = getattr(image, "n_frames", 1) if animated else 1
        aspect_ratio = round(width / height, 4) if height else None

        if animated:
            # Preferred M2 behavior (docs/phase16_m2_secure_fetch_and_validation_report.md's own
            # animation policy): detect and record it, but reject for editorial use - never decode
            # every frame (n_frames is a cheap header read, not a decode of each frame).
            return TechnicalValidation(
                observed_mime=signature_mime, format=format_name, width=width, height=height,
                pixel_count=pixel_count, aspect_ratio=aspect_ratio, animated=True,
                frame_count=frame_count, byte_size=byte_size, sha256=sha256,
                error_code="animation_unsupported", duration_ms=_duration_ms(start),
            )

        return TechnicalValidation(
            observed_mime=signature_mime, format=format_name, byte_size=byte_size,
            width=width, height=height, pixel_count=pixel_count, aspect_ratio=aspect_ratio,
            animated=False, frame_count=1, sha256=sha256,
            duration_ms=_duration_ms(start), error_code=None,
        )
    except Image.DecompressionBombError:
        return TechnicalValidation(
            observed_mime=signature_mime, byte_size=byte_size, sha256=sha256,
            error_code="pixel_limit_exceeded", duration_ms=_duration_ms(start),
        )
    except UnidentifiedImageError:
        return TechnicalValidation(
            observed_mime=signature_mime, byte_size=byte_size, sha256=sha256,
            error_code="decode_failed", duration_ms=_duration_ms(start),
        )
    except Exception:
        logger.warning("image_decode_unexpected_error")
        return TechnicalValidation(
            observed_mime=signature_mime, byte_size=byte_size, sha256=sha256,
            error_code="decode_failed", duration_ms=_duration_ms(start),
        )
    finally:
        # Deterministic resource cleanup regardless of outcome - image bytes are never persisted,
        # only the derived TechnicalValidation fields are (docs §11 non-goals).
        if image is not None:
            image.close()
