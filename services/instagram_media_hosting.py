"""INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §6: the media-hosting mechanism the Instagram Graph
API publish flow needs - a real, public, internet-fetchable HTTPS URL for the EXACT selected/
rendered asset, nothing else.

Two independent halves, deliberately:

1. **Asset registration/serving** (this module + `app/routes/instagram_media.py`) - real, complete,
   fully tested code. Given already-rendered image bytes for an approved package, computes a
   deterministic content-hash identity, writes the bytes to a bounded local directory, and
   registers a time-limited, exact-lookup-only record. `app/routes/instagram_media.py` serves
   EXACTLY that record by its exact asset id - no directory listing, no arbitrary path traversal,
   no fallback to any other file on disk.
2. **Public reachability** (`is_safe_public_base_url()` + `build_public_media_url()`) - honestly
   NOT satisfiable by code alone. `settings.instagram_media_public_base_url` is `None` in every
   environment this phase touches (confirmed: no TLS/domain/reverse-proxy exists in front of the
   `backend` service today - `docker port` shows only plain HTTP on `0.0.0.0:8000`, no nginx/Caddy/
   Traefik container exists anywhere in the compose stack). This is a genuine, disclosed
   infrastructure/operational decision (which domain, which TLS approach, or an alternative managed
   object-storage service with public HTTPS built in) - analogous to the credential gate, not a
   code defect this phase can or should paper over by serving real production images over
   unencrypted HTTP as a workaround. `MEDIA_HOSTING_READY` is only ever `True` once BOTH halves are
   satisfied - see `media_hosting_readiness()` below, the single source of truth for that metric.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from core.config import settings
from services.image_validation import validate_image_bytes

logger = logging.getLogger(__name__)

MAX_ASSET_BYTES = 8_000_000
"""Meta's own practical media-size guidance for feed images is well under this; bounded here
independently of whatever `services.image_validation` itself enforces, so this module's own limit
never silently drifts if that module's default ever changes."""

ALLOWED_MIME_TYPES = frozenset({"image/jpeg"})
"""Confirmed via live search this phase: Meta's `image_url` publish path requires JPEG. A future
phase adding video/Reels would extend this, never loosen it silently."""

DEFAULT_TTL_SECONDS = 3600
"""Long enough to cover Meta's own container-processing window (typically seconds; bounded here at
one hour for operator margin) - short enough that a stale asset does not linger indefinitely
(§6's own "limited exposure lifecycle where practical")."""

_STORAGE_ROOT = Path(getattr(settings, "instagram_media_storage_root", None) or "/data/instagram_media_public")


class MediaHostingError(ValueError):
    """Raised for a caller error (bad bytes, disallowed mime, oversized) - never for "not
    configured", which is a normal, expected, non-error state (`build_public_media_url()` returns
    `None`, it does not raise)."""


@dataclass(frozen=True)
class PublicationAsset:
    asset_id: str
    """A deterministic `sha256(bytes)[:32]` - the SAME bytes always produce the SAME asset id, so
    registering the same rendered image twice (e.g. a retried package build) never creates a
    second file or a second public identity."""
    local_path: Path
    mime_type: str
    byte_size: int
    package_id: str
    created_at: datetime
    expires_at: datetime

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at


def _ensure_storage_root() -> None:
    _STORAGE_ROOT.mkdir(parents=True, exist_ok=True)


def register_publication_asset(
    image_bytes: bytes, *, package_id: str, ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> PublicationAsset:
    """Validates (reuses `services.image_validation.validate_image_bytes()` - never a second,
    divergent image-technical-validation implementation), then writes to a bounded local directory
    under a content-hash filename. Raises `MediaHostingError` for anything that fails validation -
    never silently hosts an unvalidated/oversized/wrong-mime file."""
    if len(image_bytes) > MAX_ASSET_BYTES:
        raise MediaHostingError(f"asset exceeds MAX_ASSET_BYTES ({len(image_bytes)} > {MAX_ASSET_BYTES})")

    technical = validate_image_bytes(image_bytes, max_pixels=40_000_000)
    if technical.error_code is not None:
        raise MediaHostingError(f"image validation failed: {technical.error_code}")

    mime = technical.observed_mime
    # Deliberately narrow: `observed_mime` may report other formats `validate_image_bytes()` itself
    # accepts (PNG/WEBP/GIF) for OTHER callers - Instagram's own `image_url` path requires JPEG
    # specifically, so this module's own allowlist has exactly one entry, never silently widened.
    if mime is None or mime not in ALLOWED_MIME_TYPES:
        raise MediaHostingError(f"unsupported mime for Instagram image_url: observed={mime!r}, only JPEG is accepted")

    asset_id = hashlib.sha256(image_bytes).hexdigest()[:32]
    _ensure_storage_root()
    dest = _STORAGE_ROOT / f"{asset_id}.jpg"
    now = datetime.now(timezone.utc)
    if not dest.exists():
        dest.write_bytes(image_bytes)
    else:
        # INSTAGRAM-MEDIA-HOSTING-CLOSURE-1 §7: a dedup hit (identical bytes already staged from an
        # earlier registration) must still refresh this asset's exposure window - `get_publication_
        # asset()` derives expiry from the file's own mtime, so without this a re-registration of
        # content that happens to match a stale, already-expired file would be silently unservable
        # the instant it's "registered" again. mtime is the single source of truth for "last
        # registered at", never "first ever written at" - a real re-publish of the same rendered
        # image (e.g. a retried package build) must always get a fresh TTL, not inherit history.
        os.utime(dest, (now.timestamp(), now.timestamp()))


    asset = PublicationAsset(
        asset_id=asset_id, local_path=dest, mime_type=mime, byte_size=len(image_bytes),
        package_id=package_id, created_at=now, expires_at=now + timedelta(seconds=ttl_seconds),
    )
    logger.info(
        "instagram_media_asset_registered",
        extra={"asset_id": asset_id, "package_id": package_id, "byte_size": asset.byte_size, "expires_at": asset.expires_at.isoformat()},
    )
    return asset


def get_publication_asset(asset_id: str) -> PublicationAsset | None:
    """Exact-id lookup only - never a directory listing, never a prefix/glob match. Returns `None`
    for anything not found, malformed, or expired (the file is left in place for TTL bookkeeping
    simplicity; `app/routes/instagram_media.py` treats `None` as a 404 either way, so an expired
    asset is never actually servable regardless of whether the bytes still exist on disk)."""
    if not asset_id or not all(c in "0123456789abcdef" for c in asset_id) or len(asset_id) != 32:
        return None  # never even attempts a filesystem lookup for a malformed id (no path traversal surface)
    path = _STORAGE_ROOT / f"{asset_id}.jpg"
    if not path.is_file():
        return None
    stat = path.stat()
    created_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    expires_at = created_at + timedelta(seconds=DEFAULT_TTL_SECONDS)
    if datetime.now(timezone.utc) >= expires_at:
        return None
    return PublicationAsset(
        asset_id=asset_id, local_path=path, mime_type="image/jpeg", byte_size=stat.st_size,
        package_id="", created_at=created_at, expires_at=expires_at,
    )


def _hostname_resolves_to_public_ip(hostname: str) -> bool:
    """Real DNS resolution + `ipaddress` classification - mirrors the same class of check
    `integrations/http/safe_fetch.py` already uses for outbound fetches (S: never a second,
    divergent SSRF-safety convention), applied here to the OTHER direction: validating that a
    CONFIGURED base URL for OUR OWN outbound-facing hosting is not accidentally private/loopback."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        raw_ip = info[4][0]
        try:
            ip = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False
    return bool(infos)


def is_safe_public_base_url(url: str | None) -> bool:
    """`True` only for a real `https://` URL whose hostname is neither empty, a bare IP literal in
    a private range, `localhost`, nor DNS-unresolvable to any public address. Never accepts `http://`
    (§6's own explicit HTTPS requirement), never a `/mnt/data`-style local path, never an empty
    host."""
    if not url:
        return False
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        return False
    hostname = parsed.hostname
    if not hostname or hostname.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        return not (literal_ip.is_private or literal_ip.is_loopback or literal_ip.is_link_local or literal_ip.is_reserved or literal_ip.is_unspecified)
    return _hostname_resolves_to_public_ip(hostname)


def build_public_media_url(asset: PublicationAsset) -> str | None:
    """Returns `None` (never raises, never fabricates a URL) whenever
    `settings.instagram_media_public_base_url` is unset or fails `is_safe_public_base_url()` -
    this IS the mechanism by which a real publish attempt fails closed instead of ever sending a
    localhost/private/unreachable URL to Meta's API."""
    base = getattr(settings, "instagram_media_public_base_url", None)
    if not is_safe_public_base_url(base):
        return None
    return f"{base.rstrip('/')}/media/instagram/{asset.asset_id}.jpg"


def media_hosting_readiness() -> dict[str, object]:
    """The single source of truth for `MEDIA_HOSTING_READY` - both halves must hold. Never invents
    a "ready" state from partial evidence."""
    base = getattr(settings, "instagram_media_public_base_url", None)
    base_configured = bool(base)
    base_safe = is_safe_public_base_url(base) if base_configured else False
    return {
        "code_path_ready": True,  # registration + serving + validation are real and tested this phase
        "public_base_url_configured": base_configured,
        "public_base_url_safe": base_safe,
        "media_hosting_ready": base_safe,  # code_path_ready alone is never sufficient
    }
