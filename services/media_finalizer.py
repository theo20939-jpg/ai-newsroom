"""MEDIA-PROD-1: the single MEDIA FINALIZER choke point for every delivery path in this codebase
that resolves an `EditorialImageCandidate` to a Telegram-sendable photo input OTHER than
`worker/content_cycle.py`'s own router.

Root cause this closes: `bot/image_preview_media.py::resolve_photo_input()` is a shared, PURE
bytes/file_id resolver (by its own design - no branding, no rendering) reused by several
independent delivery paths: `services/image_preview_notifier.py` (initial NEWS send),
`bot/handlers/image_preview.py` (Previous/Next candidate paging), `services/
event_recap_review_notifier.py` (Tier 1/2B real-photo recap candidates), and `services/
final_post_review_notifier.py` (final-post review preview). None of these ever called
`services/nnj_master_news_overlay.py::apply_master_news_branding()` afterward - only `worker/
content_cycle.py`'s own router did, so an image's branding depended entirely on which of these
paths happened to send it, not on the image itself. `finalize_photo_input()` below is a drop-in
replacement for `resolve_photo_input()` that adds the missing branding step, so every one of these
paths now converges on the same outcome the router already produces for its own NEWS sends.

Deliberately NOT a router replacement or a new rendering pipeline: `worker/content_cycle.py` is
untouched by this module and keeps calling `resolve_photo_input()` directly - its own branding
logic already correctly handles NEWS (with Gemini recomposition + source-risk-aware lower-signature
suppression) and DATA/QUOTE/BREAKING (`render_branded_media()`, presentation-type-aware), none of
which the four paths above ever had or need (they only ever send plain NEWS-shaped content - a
recap/final-post preview, never a DATA/QUOTE/BREAKING card). Duplicating that machinery here would
be a real, unnecessary architecture change; this module intentionally applies only the SAME baseline
`apply_master_news_branding()` call the router's own NEWS branch makes on unrecomposed source bytes
- a strict improvement over "no branding at all," not a partial reimplementation of the router.

Gated on the exact same `presentation_director_mode`/`pulse_brand_enabled` settings the router
itself is already gated on, so a `presentation_director_mode="off"` (the default) deployment sees
zero behavior change here, byte-identical to before this module existed. `"shadow"` also passes
bytes through unchanged - unlike the router's own use of "shadow" (compute a decision, log it,
never touch delivery), there is no separate lightweight "decision" to shadow-log here: the only
computation this module ever does IS the branding render itself, so there is nothing more to
observe from running it and discarding the result. Only `"enforce"` actually brands.

The one disclosed, unchanged limitation this module does NOT attempt to fix (matches worker/
content_cycle.py's own accepted "cached_file_id_no_local_bytes" exception, see
scripts/_cached_file_id_branding_diagnostic.py): `resolve_photo_input()` returns a cached Telegram
`file_id` (a plain string) whenever one already exists, and there are no local bytes to composite
onto in that case - branding is skipped, exactly as it already is on the router. Downloading the
file back from Telegram to enable branding would be new network I/O, out of proportion for this
phase's own "no image should bypass branding" goal (the common, load-bearing case - a brand-new
candidate's first send - always has local bytes)."""
from __future__ import annotations

import logging

from aiogram.types import BufferedInputFile

from bot.image_preview_media import resolve_photo_input
from core.config import settings
from services.image_persistence import EditorialImageCandidate
from services.nnj_master_news_overlay import apply_master_news_branding

logger = logging.getLogger(__name__)


def finalize_photo_input(candidate: EditorialImageCandidate) -> str | BufferedInputFile | None:
    """Same return contract as `resolve_photo_input()` (a cached `file_id` string, a branded
    `BufferedInputFile`, or `None` when nothing is resolvable) - every existing caller can swap
    `resolve_photo_input(candidate)` for `finalize_photo_input(candidate)` with no other change.

    Never raises: a branding failure is logged and the ORIGINAL, unbranded `BufferedInputFile` is
    returned instead - mirrors this codebase's own "a failed enhancement never blocks delivery"
    convention (e.g. `services/editorial_recomposition.py::maybe_recompose()`'s own fail-open
    behavior), since the alternative (dropping the image or failing the whole send over a purely
    cosmetic branding failure) would be a strictly worse outcome for the editor."""
    photo_input = resolve_photo_input(candidate)

    if settings.presentation_director_mode != "enforce" or not settings.pulse_brand_enabled:
        return photo_input
    if not isinstance(photo_input, BufferedInputFile):
        # A cached file_id (str) or None - no local bytes to brand, same accepted exception the
        # router's own "cached_file_id_no_local_bytes" skip path already established.
        return photo_input

    try:
        branded_bytes, _decision = apply_master_news_branding(photo_input.data)
    except Exception:  # noqa: BLE001 - branding is a best-effort enhancement, never a delivery blocker
        logger.exception("media_finalizer_branding_failed", extra={"candidate_id": str(candidate.id)})
        return photo_input

    return BufferedInputFile(branded_bytes, filename=photo_input.filename or "preview.jpg")
