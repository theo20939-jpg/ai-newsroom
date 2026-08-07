# Phase 19 M12 — Rich Media Telegram Delivery

## 1. Scope

Extends `services/image_preview_notifier.py` (never a parallel notifier) with
`send_news_with_rich_media()` — multi-photo/mixed-media delivery via `bot.send_media_group()`.
Reuses `bot/formatting.py::render_editorial_card()` and M5's `CAPTION_SAFE_LIMIT`-bounded
caption budgeting exactly, same as the existing single-photo path.

## 2. Composition rules

- **Order**: images first, direct-hosted video last (explicit requirement).
- **Direct-hosted video**: passed to `InputMediaVideo(media=<url>)` as a URL string — Telegram
  fetches it server-side, so this never re-downloads/re-uploads bytes M10 already
  bounded-validated.
- **YouTube/Vimeo**: never included in the media group (never downloaded/re-uploaded, per M10's
  own scope) — appended as a plain link line to the caption text instead.
- **Caption**: only the first media-group item carries it (Telegram's actual behavior — a caption
  on any later item is not shown as the group caption); `build_rich_media_plan()` resolves URLs
  first and constructs the (frozen, Pydantic) `InputMediaPhoto`/`InputMediaVideo` objects last, in
  final order, since the caption must be set at construction time.
- **Telegram's 2–10 item constraint**: fewer than 2 total resolvable items falls back to the
  existing `send_news_with_image_preview()` single-photo/text path (a media group of 1 is
  rejected by Telegram outright). More than 10 photos are truncated to Telegram's own cap (with
  one slot reserved for a trailing direct-hosted video, if present).

## 3. Known UX limitation (documented, not solved — per this milestone's own explicit allowance)

Telegram's Bot API does not support an inline keyboard on a media group at all (`reply_markup` is
not a valid `send_media_group()` parameter). Unlike the single-photo path, a rich-media send
carries no interactive keyboard — the source link lives in the caption text instead. A follow-up
keyboard-bearing message was deliberately rejected: that would reintroduce the exact two-message
UX defect the Phase 16 M6 fix eliminated.

## 4. Setting — built, tested, deliberately not wired into live delivery yet

```python
rich_media_mode: Literal["off", "shadow", "enforce"] = "off"
```

`send_news_with_rich_media()` is fully implemented and tested this milestone but **not called
from `worker/content_cycle.py`'s live loop**. Wiring it in safely requires a specific draft's
ranked media candidates (M11) to actually be computed and available at delivery time — M11
deliberately does not persist a ranking run (see `docs/phase19_m11_media_ranking.md` §1's own
scope decision, since ranking is 100% reproducible on demand). Live wiring is left for a future,
separately-reviewed milestone that decides how/when to invoke M11's ranking during the delivery
step itself. This keeps M12 additive and risk-free: nothing in the existing delivery path changes
while `rich_media_mode` stays at its default.

## 5. Validation performed

- `tests/test_rich_media_notifier.py` (10 tests, `FakeSession`-based, no real Telegram API call):
  `build_rich_media_plan()` ordering/caption/fallback/cap logic (7 pure tests) plus
  `send_news_with_rich_media()` integration-style tests (a real multi-photo `send_media_group()`
  call, single-photo fallback, dry-run never calling the bot).
- Full pre-existing `tests/test_image_preview_notifier.py` suite (9 tests, unmodified) still
  passes.
- Ruff/Mypy clean.

## 6. What this milestone does NOT do

- Does not enable `rich_media_mode` anywhere (defaults `"off"`).
- Does not send a real Telegram message.
- Does not wire itself into `worker/content_cycle.py`'s live delivery loop.
- Does not download/re-upload YouTube/Vimeo video bytes.
- Does not solve the inline-keyboard-on-media-group platform limitation — documented instead.
