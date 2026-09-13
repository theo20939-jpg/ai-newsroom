"""CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1 section 15: safe, bounded download + cache for a
media candidate's actual bytes. Reuses the existing, already-audited safety boundary rather than
building a new one (this codebase's own established discipline - see
`integrations/http/safe_fetch.py`'s own docstring: "No adapter, service, or workflow file builds
its own httpx.AsyncClient for this purpose"):

  - network fetch -> `integrations.http.safe_fetch.safe_fetch()` (SSRF-safe, IP-pinned, bounded
    redirects/timeouts/bytes - the exact same boundary `services/image_intelligence.py` uses)
  - MIME/pixel/decode validation -> `services.image_validation.validate_image_bytes()` (Phase 16
    M2, unmodified)
  - content hash -> `integrations.http.safe_fetch.sha256_hex()` (unmodified)
  - perceptual hash -> `services.image_quality.compute_dhash()`/`hamming_distance()` (Phase 16 M3,
    unmodified)

Nothing here re-implements any of the above; this module only adds the bounded local CACHE layer
(section 15's own explicit "bounded cache, duplicate detection" requirement) on top of them, plus a
safe filename convention (the content hash itself - never a caller-supplied string touches the
filesystem path)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from integrations.http.safe_fetch import SafeFetchError, SafeFetchPolicy, safe_fetch
from services.image_quality import compute_dhash
from services.image_validation import validate_image_bytes

logger = logging.getLogger(__name__)

# Reuses the EXACT same bounds `services/image_intelligence.py` already applies to every image
# download in this codebase (`core/config.py`'s own `image_intelligence_*` settings) - a new media-
# research download policy deliberately does not invent a second, divergent set of limits.
DEFAULT_POLICY = SafeFetchPolicy(
    connect_timeout_seconds=3.0, read_timeout_seconds=7.0, total_timeout_seconds=12.0,
    max_redirects=3, max_bytes=10_000_000,
)
DEFAULT_MAX_DECODED_PIXELS = 40_000_000

_MAX_CACHE_FILES = 500  # section 15's own "bounded cache" - a hard ceiling, not a soft target


@dataclass(frozen=True)
class DownloadOutcome:
    ok: bool
    local_path: str | None
    sha256: str | None
    perceptual_hash: str | None
    width: int | None
    height: int | None
    byte_size: int | None
    error_code: str | None  # a `FetchErrorCode` value, a `TechnicalValidation.error_code` value,
    # or "cache_full" - never a raw exception string (mirrors safe_fetch's own discipline)


def _orientation(width: int | None, height: int | None) -> str | None:
    if not width or not height:
        return None
    ratio = width / height
    if ratio > 1.15:
        return "landscape"
    if ratio < 0.9:
        return "portrait"
    return "square"


def _ensure_cache_dir(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)


def _cache_is_full(cache_dir: Path) -> bool:
    try:
        return sum(1 for _ in cache_dir.glob("*")) >= _MAX_CACHE_FILES
    except OSError:
        return False


async def download_and_validate(
    url: str, *, cache_dir: Path, policy: SafeFetchPolicy = DEFAULT_POLICY,
    max_decoded_pixels: int = DEFAULT_MAX_DECODED_PIXELS,
) -> DownloadOutcome:
    """Never raises - every failure path returns `ok=False` with a structured `error_code`,
    mirroring `safe_fetch`/`validate_image_bytes`'s own "never a bare exception reaches the
    caller" discipline."""
    _ensure_cache_dir(cache_dir)

    try:
        fetch_result = await safe_fetch(url, policy=policy)
    except SafeFetchError as exc:
        return DownloadOutcome(
            ok=False, local_path=None, sha256=None, perceptual_hash=None, width=None, height=None,
            byte_size=None, error_code=exc.code.value,
        )

    technical = validate_image_bytes(fetch_result.body, max_pixels=max_decoded_pixels)
    if technical.error_code is not None:
        return DownloadOutcome(
            ok=False, local_path=None, sha256=technical.sha256, perceptual_hash=None,
            width=technical.width, height=technical.height, byte_size=technical.byte_size,
            error_code=technical.error_code,
        )

    sha256 = technical.sha256 or ""
    ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}.get(technical.format or "", "jpg")
    # Safe filename convention: the content hash ONLY - a caller-supplied URL/title never touches
    # the filesystem path (section 15's own "safe filename/storage" requirement).
    dest = cache_dir / f"{sha256}.{ext}"

    if dest.exists():
        pass  # already cached under its own content hash - no re-download, no duplicate file
    else:
        if _cache_is_full(cache_dir):
            return DownloadOutcome(
                ok=False, local_path=None, sha256=sha256, perceptual_hash=None,
                width=technical.width, height=technical.height, byte_size=technical.byte_size,
                error_code="cache_full",
            )
        dest.write_bytes(fetch_result.body)

    phash: str | None = None
    try:
        with Image.open(dest) as im:
            phash = compute_dhash(im.convert("RGB"))
    except Exception as exc:  # pragma: no cover - validate_image_bytes already decoded this once;
        # a second failure here would mean the just-written file itself is unreadable, logged not
        # silently swallowed, never re-raised (mirrors this module's own "never raises" contract).
        logger.warning("media_research_phash_failed", extra={"error": type(exc).__name__})

    return DownloadOutcome(
        ok=True, local_path=str(dest), sha256=sha256, perceptual_hash=phash,
        width=technical.width, height=technical.height, byte_size=technical.byte_size,
        error_code=None,
    )
