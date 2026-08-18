"""NINJA PULSE Visual System v1 pre-commit correction - offline, read-only diagnostic for the
"cached file_id branding" limitation (spec item 5).

Does NOT download from Telegram, does NOT add network retrieval, does NOT touch image
persistence. Purely demonstrates, against the real `bot/image_preview_media.py::
resolve_photo_input()` contract and the real branding-decision logic now in
`worker/content_cycle.py`, the three possible `photo_input` shapes and exactly what happens to
each under `presentation_director_mode="enforce"` + `pulse_brand_enabled=True`:

  1. `BufferedInputFile` (fresh local bytes, from `services.image_persistence.
     read_candidate_bytes()`) -> branding IS possible, `render_branded_media()` is called.
  2. `str` (a cached Telegram `file_id` - `EditorialImageCandidate.telegram_file_id` was already
     set from a prior send) -> branding is SKIPPED (no local bytes exist to composite onto);
     `brand_skip_reason="cached_file_id_no_local_bytes"`.
  3. `None` (nothing resolvable at all - no stored bytes, expired/missing file) -> same skip path
     for NEWS; `brand_skip_reason="no_source_media"`.

`resolve_photo_input()`'s own return type is exactly `str | BufferedInputFile | None` (confirmed
by reading `bot/image_preview_media.py` directly) - there is no fourth "plain URL string" case in
this codebase; a bare URL is never passed to Telegram's photo parameter this way.

Run: python scripts/_cached_file_id_branding_diagnostic.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiogram.types import BufferedInputFile  # noqa: E402

from services.presentation_director import NEWS  # noqa: E402


def _decide_brand_applicability(photo_input: str | BufferedInputFile | None, presentation_type: str) -> tuple[bool, str | None]:
    """Mirrors worker/content_cycle.py's own `needs_render`/`skip_reason` logic exactly (the
    real, current source of truth) - kept as a tiny pure re-derivation here only so this
    diagnostic can run without a live DB/session/registry; the real branching this describes
    lives at worker/content_cycle.py's own presentation_director_mode == "enforce" block."""
    source_bytes = photo_input.data if isinstance(photo_input, BufferedInputFile) else None
    needs_render = presentation_type in ("DATA", "QUOTE", "BREAKING") or source_bytes is not None
    if needs_render:
        return True, None
    skip_reason = "cached_file_id_no_local_bytes" if isinstance(photo_input, str) else "no_source_media"
    return False, skip_reason


def run() -> None:
    cases: list[tuple[str, str | BufferedInputFile | None]] = [
        ("BufferedInputFile (fresh local bytes)", BufferedInputFile(b"\xff\xd8\xff\xe0fake-jpeg-bytes", filename="p.jpg")),
        ("str (cached Telegram file_id)", "AgACAgIAAxkBAAI-fake-cached-file-id"),
        ("None (nothing resolvable)", None),
    ]

    print(f"{'photo_input shape':45s} {'branding possible?':20s} {'skip_reason'}")
    print("-" * 95)
    for label, photo_input in cases:
        applicable, skip_reason = _decide_brand_applicability(photo_input, NEWS)
        print(f"{label:45s} {str(applicable):20s} {skip_reason or '-'}")

    print(
        "\nProduction limitation (disclosed, not fixed this checkpoint - would require Telegram "
        "file download + network I/O, explicitly out of scope per spec item 5): any NEWS "
        "presentation whose image candidate already has a `telegram_file_id` (i.e. Telegram "
        "already has a cached copy from an earlier send) skips branding entirely. This is expected "
        "to be rare on a fresh delivery (a brand-new draft's image candidates have no file_id yet - "
        "they only gain one after their own first successful send), but any code path that reuses "
        "an already-sent candidate's cached file_id will silently render unbranded. Observable via "
        "the new `brand_render_skipped` log event (brand_applied=False, "
        "brand_skip_reason='cached_file_id_no_local_bytes')."
    )


if __name__ == "__main__":
    run()
