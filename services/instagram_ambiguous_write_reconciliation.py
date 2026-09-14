"""INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §9/§13: what happens after a Meta publish attempt
returns an AMBIGUOUS (network/timeout) result - the exact scenario §9's own brief names: "Instagram
network timeout after a publish request is dangerous... do NOT blindly resend."

Deliberately a thin layer ON TOP of the existing, unmodified, already-well-tested
`services.instagram_publish_adapter.publish_instagram_content()` - that function's own real
behavior (fail-closed gates, bounded retries for RATE_LIMITED/TRANSIENT, non-retry for AUTH_ERROR/
INVALID_MEDIA) is completely untouched and still correct on its own. This module adds exactly the
ONE missing decision `publish_instagram_content()` cannot make by itself: when the failure class is
`NETWORK` (a timeout/connection error - the request's fate at Meta's end is genuinely unknown),
readback-and-reconcile via the real, official, read-only API BEFORE deciding whether it is safe to
retry at all."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

logger = logging.getLogger(__name__)

_READBACK_WINDOW_MINUTES = 15
"""How far back a readback search looks for a matching post - generous enough to cover a real
container-processing + publish round trip, bounded so an old, unrelated post can never be
mistaken for confirmation of a much later attempt."""


class ReadbackMediaLike(Protocol):
    caption: str | None
    timestamp: str | None
    media_id: str
    permalink: str | None


class ReadbackReader(Protocol):
    async def fetch_recent_media(self, limit: int = ...) -> list[ReadbackMediaLike]: ...


@dataclass(frozen=True)
class ReconciliationOutcome:
    resolution: str  # "confirmed_published" | "confirmed_absent" | "unknown"
    matched_media_id: str | None = None
    matched_permalink: str | None = None
    detail: str = ""


def _caption_matches(candidate_caption: str | None, expected_caption_prefix: str) -> bool:
    if not candidate_caption or not expected_caption_prefix:
        return False
    # A prefix match (not exact) - Instagram may append/normalize whitespace; a real duplicate
    # post from THIS SAME attempt will always share at least the first real sentence verbatim
    # (the package's own caption is never regenerated between attempts of the same idempotency key).
    prefix = expected_caption_prefix.strip()[:80]
    return bool(prefix) and prefix in candidate_caption


def _within_window(timestamp: str | None, *, since: datetime) -> bool:
    if not timestamp:
        return False
    try:
        posted_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    return posted_at >= since


async def reconcile_ambiguous_publish(
    reader: ReadbackReader, *, expected_caption_prefix: str, attempted_at: datetime,
    window_minutes: int = _READBACK_WINDOW_MINUTES,
) -> ReconciliationOutcome:
    """Never raises - a readback failure itself (network error on the READ side too) resolves to
    `"unknown"`, never silently treated as either confirmation or absence (§9's own "if still
    unknown: AMBIGUOUS/HOLD"). Only ever inspects the account's own recent media - never a broader
    search, never any write."""
    since = attempted_at - timedelta(minutes=1)  # small backward margin for clock skew
    cutoff = attempted_at + timedelta(minutes=window_minutes)
    try:
        recent = await reader.fetch_recent_media()
    except Exception as exc:  # noqa: BLE001 - a reconciliation-read failure is itself "unknown", never a crash
        logger.warning("instagram_ambiguous_reconciliation_readback_failed", extra={"error": type(exc).__name__})
        return ReconciliationOutcome(resolution="unknown", detail=f"readback failed: {type(exc).__name__}")

    for media in recent:
        if not _within_window(media.timestamp, since=since):
            continue
        if _caption_matches(media.caption, expected_caption_prefix):
            logger.info(
                "instagram_ambiguous_reconciliation_confirmed_published",
                extra={"media_id": media.media_id, "permalink": media.permalink},
            )
            return ReconciliationOutcome(
                resolution="confirmed_published", matched_media_id=media.media_id,
                matched_permalink=media.permalink, detail="matched a recent post within the readback window",
            )

    now = datetime.now(timezone.utc)
    if now < cutoff:
        # Too soon to be confident the post would have appeared by now even if it succeeded -
        # never concludes "absent" prematurely.
        return ReconciliationOutcome(resolution="unknown", detail="readback window not yet elapsed")

    logger.info("instagram_ambiguous_reconciliation_confirmed_absent", extra={"window_minutes": window_minutes})
    return ReconciliationOutcome(resolution="confirmed_absent", detail="no matching post found within the readback window")
