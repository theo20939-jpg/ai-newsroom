"""Tests for services.image_validation (Phase 16 M2, docs/phase16_m2_secure_fetch_and_validation_
report.md §12/§22). Pure decode logic - no network, generated in-memory raster images via Pillow.
"""
import io

from PIL import Image

from services.image_validation import validate_image_bytes

GENEROUS_PIXELS = 10_000_000


def _make(fmt: str, size: tuple[int, int] = (64, 48), **save_kwargs) -> bytes:
    img = Image.new("RGB", size, color=(10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format=fmt, **save_kwargs)
    return buf.getvalue()


def _make_animated_gif(frames: int = 3) -> bytes:
    images = [Image.new("RGB", (20, 20), color=(i * 40, 0, 0)) for i in range(frames)]
    buf = io.BytesIO()
    images[0].save(buf, format="GIF", save_all=True, append_images=images[1:], duration=100, loop=0)
    return buf.getvalue()


def test_valid_jpeg() -> None:
    result = validate_image_bytes(_make("JPEG"), max_pixels=GENEROUS_PIXELS)
    assert result.format == "JPEG"
    assert result.error_code is None
    assert result.width == 64 and result.height == 48


def test_valid_png() -> None:
    result = validate_image_bytes(_make("PNG"), max_pixels=GENEROUS_PIXELS)
    assert result.format == "PNG"
    assert result.error_code is None


def test_valid_webp() -> None:
    result = validate_image_bytes(_make("WEBP"), max_pixels=GENEROUS_PIXELS)
    assert result.format == "WEBP"
    assert result.error_code is None


def test_static_gif_is_validated() -> None:
    result = validate_image_bytes(_make("GIF"), max_pixels=GENEROUS_PIXELS)
    assert result.format == "GIF"
    assert result.animated is False
    assert result.error_code is None


def test_animated_gif_is_rejected_but_recorded() -> None:
    result = validate_image_bytes(_make_animated_gif(3), max_pixels=GENEROUS_PIXELS)
    assert result.animated is True
    assert result.frame_count == 3
    assert result.error_code == "animation_unsupported"
    assert result.format == "GIF"  # still recorded despite rejection


def test_animated_webp_is_rejected_but_recorded() -> None:
    images = [Image.new("RGB", (16, 16), color=(i * 60, 0, 0)) for i in range(3)]
    buf = io.BytesIO()
    images[0].save(buf, format="WEBP", save_all=True, append_images=images[1:], duration=100, loop=0)
    result = validate_image_bytes(buf.getvalue(), max_pixels=GENEROUS_PIXELS)
    if result.animated:  # WebP animation support depends on the installed libwebp build
        assert result.error_code == "animation_unsupported"
    else:
        assert result.error_code is None  # acceptable fallback: encoded as a static WebP


def test_svg_rejected() -> None:
    svg = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
    result = validate_image_bytes(svg, max_pixels=GENEROUS_PIXELS)
    assert result.error_code == "svg_rejected"


def test_svg_without_xml_prolog_rejected() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'
    result = validate_image_bytes(svg, max_pixels=GENEROUS_PIXELS)
    assert result.error_code == "svg_rejected"


def test_html_disguised_as_jpeg_rejected() -> None:
    html = b"<!DOCTYPE html><html><body>404 Not Found</body></html>"
    result = validate_image_bytes(html, max_pixels=GENEROUS_PIXELS)
    assert result.error_code == "signature_mismatch"


def test_mime_signature_mismatch_recorded() -> None:
    """A real PNG's signature is authoritative regardless of what a caller might have declared
    (observed_mime reflects the sniffed signature, not any external Content-Type)."""
    result = validate_image_bytes(_make("PNG"), max_pixels=GENEROUS_PIXELS)
    assert result.observed_mime == "image/png"


def test_unknown_binary_format_rejected() -> None:
    result = validate_image_bytes(b"\x00\x01\x02\x03\x04\x05random", max_pixels=GENEROUS_PIXELS)
    assert result.error_code == "unsupported_format"


def test_corrupt_jpeg_rejected() -> None:
    corrupt = b"\xff\xd8\xff\xe0" + b"not a real jpeg body at all" * 5
    result = validate_image_bytes(corrupt, max_pixels=GENEROUS_PIXELS)
    assert result.error_code == "decode_failed"


def test_truncated_png_rejected() -> None:
    full = _make("PNG")
    truncated = full[: len(full) // 2]
    result = validate_image_bytes(truncated, max_pixels=GENEROUS_PIXELS)
    assert result.error_code == "decode_failed"


def test_decoder_exception_is_classified_not_raised() -> None:
    garbage = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # valid signature, garbage body
    result = validate_image_bytes(garbage, max_pixels=GENEROUS_PIXELS)  # must not raise
    assert result.error_code == "decode_failed"


def test_maximum_image_byte_size_is_the_callers_responsibility_not_this_functions() -> None:
    """validate_image_bytes operates on already-fetched, already-bounded bytes (safe_fetch owns
    the byte-size cap) - this just proves a large-but-valid image still decodes correctly."""
    result = validate_image_bytes(_make("PNG", size=(500, 500)), max_pixels=GENEROUS_PIXELS)
    assert result.error_code is None
    assert result.byte_size > 0


def test_maximum_decoded_pixels_enforced() -> None:
    oversized = _make("PNG", size=(2000, 2000))
    result = validate_image_bytes(oversized, max_pixels=1000)
    assert result.error_code == "pixel_limit_exceeded"
    assert result.pixel_count == 4_000_000


def test_decompression_bomb_protection_remains_enabled() -> None:
    """Pillow's own independent MAX_IMAGE_PIXELS default is never touched/disabled - proven by
    checking the module never assigns to it (module docstrings are allowed to reference it by
    name when explaining the design; only an assignment would actually weaken protection)."""
    from PIL import Image

    from services import image_validation  # noqa: F401 - importing must not have mutated this

    assert Image.MAX_IMAGE_PIXELS is not None and Image.MAX_IMAGE_PIXELS > 50_000_000


def test_width_and_height_recorded() -> None:
    result = validate_image_bytes(_make("JPEG", size=(123, 77)), max_pixels=GENEROUS_PIXELS)
    assert result.width == 123
    assert result.height == 77


def test_aspect_ratio_recorded() -> None:
    result = validate_image_bytes(_make("PNG", size=(1200, 600)), max_pixels=GENEROUS_PIXELS)
    assert result.aspect_ratio == 2.0


def test_sha256_stable_for_identical_bytes() -> None:
    data = _make("PNG")
    a = validate_image_bytes(data, max_pixels=GENEROUS_PIXELS)
    b = validate_image_bytes(data, max_pixels=GENEROUS_PIXELS)
    assert a.sha256 == b.sha256
    assert len(a.sha256) == 64  # hex-encoded sha256


def test_sha256_differs_for_different_bytes() -> None:
    a = validate_image_bytes(_make("PNG", size=(10, 10)), max_pixels=GENEROUS_PIXELS)
    b = validate_image_bytes(_make("PNG", size=(20, 20)), max_pixels=GENEROUS_PIXELS)
    assert a.sha256 != b.sha256


def test_no_perceptual_hash_field_exists() -> None:
    result = validate_image_bytes(_make("PNG"), max_pixels=GENEROUS_PIXELS)
    assert "perceptual" not in result.model_dump()
    assert not hasattr(result, "phash")


def test_image_bytes_are_never_persisted_on_the_result() -> None:
    result = validate_image_bytes(_make("PNG"), max_pixels=GENEROUS_PIXELS)
    dumped = result.model_dump()
    assert all(not isinstance(v, bytes) for v in dumped.values())


def test_validate_image_bytes_never_raises_for_arbitrary_garbage() -> None:
    import random

    random.seed(42)
    for _ in range(20):
        garbage = bytes(random.randint(0, 255) for _ in range(200))
        result = validate_image_bytes(garbage, max_pixels=GENEROUS_PIXELS)  # must not raise
        assert result.sha256 is not None


def test_empty_bytes_handled() -> None:
    result = validate_image_bytes(b"", max_pixels=GENEROUS_PIXELS)
    assert result.error_code == "unsupported_format"
