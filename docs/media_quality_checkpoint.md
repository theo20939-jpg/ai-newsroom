# Media Quality Checkpoint — corrective phase (Phase 23.1Q, media-quality corrective phase)

Status: **implementation complete, not committed, not deployed**. Follows directly from
`docs/media_wiring_checkpoint_1.md` (Media Roadmap Recovery step 1) and the forensic audit that
preceded this phase (root causes reported inline in the conversation, not as a separate doc). This
document is the required deliverable for the narrowly-scoped three-part corrective phase: restore
the real `[🔗 Источник]` inline button for media-group posts, tighten multi-image eligibility using
existing signals only, and wire within-event near-duplicate detection through already-persisted
hashes. No new DB schema. No media-architecture redesign. Video work remains paused.

## 1. What was broken (forensic recap)

Two real live-output regressions were found in the multi-image path wired by Media Wiring Step 1:

1. **Source button regression.** `bot.send_media_group()` cannot carry `reply_markup` (a real
   Telegram Bot API/aiogram limitation, confirmed directly against the installed aiogram
   signature) — the Step 1 wiring worked around this by appending a visible
   `<a href="...">🔗 Источник</a>` text link into the caption instead of the real inline-keyboard
   button every other NEWS post uses. Rejected as a final solution.
2. **Image quality regression.** `services/media_ranking.py`'s eligibility formula
   (`not video_rejected and not story_reuse_match and quality_score >= 30`) never considered
   `branding_risk` or pixel dimensions, only a low `quality_score` floor — combined with Step 1
   hardcoding `is_duplicate_within_event=False` and `EditorialImageCandidate` not exposing
   `sha256`/`perceptual_hash` at all, real posts shipped near-duplicate and low-value album images
   (a 96×96 avatar, a 140×74 icon, a 128×128 branded screenshot) alongside genuinely good hero
   images (3000×1500, 1920×1005).

## 2. Part 1 — real source button, restored

**Mechanism:** `bot.edit_message_reply_markup()` — a real, previously-unused, already-installed
aiogram method — called on the **first message** of the media group immediately after
`bot.send_media_group()` succeeds.

**File:** `services/telegram_routing.py::send_media_group_to_editorial_destination()`

```python
first_message_id = messages[0].message_id if messages else None
if reply_markup is not None and first_message_id is not None:
    try:
        await bot.edit_message_reply_markup(
            chat_id=route.chat_id, message_id=first_message_id, reply_markup=reply_markup,
        )
    except TelegramAPIError:
        logger.exception("telegram_routing_media_group_keyboard_edit_failed", extra={...})
return RoutingOutcome(..., message_id=first_message_id)
```

Properties, all explicitly required by the authorization and verified by tests:

- Exactly **one** Telegram-visible message (no second/companion message).
- Same canonical `event.url`, same `build_source_only_keyboard(event.url, label="🔗 Источник")` the
  single-photo and text-only paths already use — no separate keyboard-construction path.
- `reply_to_message_id` and `message_thread_id` (topic routing) are threaded through
  `send_media_group_to_editorial_destination()`'s existing parameters, untouched by this change —
  the keyboard-edit step is purely additive after the group already sent.
- A `TelegramAPIError` raised by the edit call is caught, logged
  (`telegram_routing_media_group_keyboard_edit_failed`), and **never** re-raised, retried, or
  treated as a delivery failure — the post itself already sent successfully.
- `worker/content_cycle.py`'s media-group branch was rewired to pass `reply_markup=keyboard` to
  `send_media_group_to_editorial_destination(...)` — the same `keyboard` variable already used by
  the single-photo/text-only paths (`bot/keyboards/image_preview.py::build_source_only_keyboard()`,
  built once, earlier in the function). The prior in-caption `<a href="...">Источник</a>` block was
  deleted entirely — no in-caption source-link fallback remains for media-group posts.
- Single-photo/text-only source-button behavior is byte-identical — neither
  `send_photo_to_editorial_destination()` nor `send_to_editorial_destination()` was touched.

## 3. Part 2 — tightened multi-image eligibility

**No new classification subsystem, no new arbitrary constant.** Reuses two already-computed,
already-calibrated signals:

- `branding_risk` — already computed inside `rank_media_candidates()` itself from the existing
  `possible_logo`/`possible_banner`/`possible_watermark`/`possible_tv_lower_third`/
  `possible_branded_screenshot` warning tokens.
- `resolution_band()` (`services/image_quality.py`, Phase 16 M3, pre-calibrated) — shortest-side
  dimension bands: `TRACKING` (≤3px), `ICON` (≤64px), `WEAK` (<300px), `ADEQUATE` (300–599px),
  `GOOD` (≥600px).

**The important distinction, implemented at the selection layer, not inside the ranking model:**
`services/media_ranking.py::rank_media_candidates()`'s own `eligible_for_delivery` semantic is
**completely unchanged** — a lone candidate that fails the stricter bar below can still be the sole
image on a text-only-alternative post, exactly as before. The stricter bar is applied only to
candidates being considered as the **second or third** album image, in
`worker/content_cycle.py::_select_top_ranked_image_candidates()`:

```python
def _meets_additional_album_image_bar(result: MediaRankingResult, candidate: EditorialImageCandidate) -> bool:
    if result.branding_risk > 0:
        return False
    if candidate.width is None or candidate.height is None:
        return False
    band = resolution_band(candidate.width, candidate.height)
    return band not in (ResolutionBand.TRACKING, ResolutionBand.ICON, ResolutionBand.WEAK)
```

```python
selected = [eligible[0][1]]  # the single best candidate keeps today's existing, unchanged bar
for result, candidate in eligible[1:]:
    if len(selected) >= limit:
        break
    if _meets_additional_album_image_bar(result, candidate):
        selected.append(candidate)
```

The cap (`_MAX_ROUTER_IMAGES = 3`) is never treated as a target — a candidate is only ever added
because it individually cleared the bar, never to "fill up" the album.

### Calibration evidence (the real forensic examples)

| Candidate | Dimensions | Resolution band | Branding risk | Additional-image bar |
|---|---|---|---|---|
| 9to5google avatar | 96×96 | WEAK | 0 | **excluded** (band) |
| icon-shaped image | 140×74 | WEAK | 0 (no warning tokens existed) | **excluded** (band — proves dimensions alone, not `branding_risk` alone, are required) |
| CodeRabbit branded screenshot | 128×128 | WEAK | 25 (`possible_branded_screenshot`) | **excluded** (both signals) |
| hero image A | 3000×1500 | GOOD | 0 | eligible (always the sole best candidate, never subject to this bar) |
| hero image B | 1920×1005 | GOOD | 0 | eligible (same) |

## 4. Part 3 — within-event near-duplicate detection, wired

**No migration, no new schema.** `sha256`/`perceptual_hash` were already persisted (Phase 16 M3)
but never exposed through the read contract used by the router path.

**File:** `services/image_persistence.py::EditorialImageCandidate` — two new fields, both defaulted
to `None` so every pre-existing direct-construction test site is unaffected:

```python
sha256: str | None = None
perceptual_hash: str | None = None
```

`get_editorial_image_candidates()` now maps `row.sha256`/`row.perceptual_hash` through.

**File:** `worker/content_cycle.py::_compute_within_event_duplicate_flags()` — reuses
`services/image_quality.py::hamming_distance()` and `services/media_ranking.py`'s own existing
`_NEAR_DUPLICATE_MAX_HAMMING_DISTANCE = 4` verbatim (imported, never re-declared):

```python
def _compute_within_event_duplicate_flags(candidates: list[EditorialImageCandidate]) -> dict[UUID, bool]:
    seen_sha256: set[str] = set()
    seen_perceptual: list[str] = []
    flags: dict[UUID, bool] = {}
    for candidate in candidates:  # already rank-ordered; earliest/best-ranked instance survives
        is_duplicate = False
        if candidate.sha256 and candidate.sha256 in seen_sha256:
            is_duplicate = True
        elif candidate.perceptual_hash and any(
            hamming_distance(candidate.perceptual_hash, known) <= _NEAR_DUPLICATE_MAX_HAMMING_DISTANCE
            for known in seen_perceptual
        ):
            is_duplicate = True
        flags[candidate.id] = is_duplicate
        if not is_duplicate:
            if candidate.sha256:
                seen_sha256.add(candidate.sha256)
            if candidate.perceptual_hash:
                seen_perceptual.append(candidate.perceptual_hash)
    return flags
```

The result feeds `_build_media_ranking_input(..., is_duplicate_within_event=...)`, which was already
a real `MediaRankingInput` field — previously always hardcoded `False`. Because
`rank_media_candidates()`'s own `is_duplicate_within_event` only affects composite score/ordering,
never eligibility, `_select_top_ranked_image_candidates()` additionally **hard-excludes** any
candidate flagged as a duplicate from the selected set — the actual "at most one survives"
guarantee is enforced at the selection layer, not merely deprioritized.

## 5. Before / after — the real bad examples

| Post | Before (Step 1 wiring) | After (this phase) |
|---|---|---|
| 9to5google draft #1 | Media group: hero + 96×96 avatar + caption source-link | Single photo: hero only; real inline button |
| 9to5google draft #2 | Media group: hero + 140×74 icon + caption source-link | Single photo: hero only; real inline button |
| CodeRabbit draft | Media group: hero + 128×128 branded screenshot + caption source-link | Single photo: hero only; real inline button |
| (any post with exact/near-duplicate candidates) | Duplicate could occupy an album slot (`is_duplicate_within_event` hardcoded `False`) | Duplicate hard-excluded before selection |

## 6. Tests

All new/updated in this phase, all passing (verified individually and via the full targeted
suites — the only `ERROR`s observed are the pre-existing, already-documented teardown-only FK
cleanup pattern common to nearly every DB-backed test in this project, confirmed via isolated
re-runs each showing `1 passed, 1 error`; never a real regression):

**`tests/test_router_media_integration.py`**
- `test_media_group_source_button_attached_via_keyboard_edit_on_first_message` — correct
  `chat_id`/`message_id`/keyboard URL+label passed to `edit_message_reply_markup`; no companion
  message.
- `test_media_group_keyboard_edit_failure_does_not_duplicate_or_resend_the_post` — a
  `TelegramAPIError` from the edit call never triggers a second `send_media_group`/`send_message`/
  `send_photo` call; the post is still counted as delivered.
- `test_media_group_caption_includes_quote_and_footer_but_no_inline_source_link` — quote above
  footer, footer present exactly once, **no** `Источник`/raw URL anywhere in the caption, button
  attached via the edit call instead.
- `test_hero_plus_tiny_avatar_selects_only_the_hero` (96×96)
- `test_hero_plus_tiny_icon_selects_only_the_hero` (140×74, zero warning tokens — proves dimensions
  alone matter, not just `branding_risk`)
- `test_hero_plus_branded_screenshot_excludes_the_branded_image` (128×128,
  `possible_branded_screenshot`)
- `test_hero_plus_genuinely_useful_second_image_both_stay_eligible` — proves the bar is not
  over-tightened past legitimate secondary images.
- `test_three_genuinely_useful_images_all_allowed` — cap is not artificially lowered.
- `test_identical_sha256_duplicate_excluded_from_the_album` — exact hash match.
- `test_near_duplicate_perceptual_hash_within_threshold_excluded` — Hamming distance exactly 4
  (the calibrated threshold boundary).
- `test_perceptually_distinct_images_both_remain` — Hamming distance 64 (maximally distinct);
  both survive.
- `test_three_useful_ranked_images_send_as_a_media_group`,
  `test_five_candidates_selects_at_most_three`,
  `test_first_candidate_fails_second_and_third_succeed_media_still_delivered`,
  `test_all_candidates_fail_to_resolve_falls_back_to_text_only` — pre-existing Step 1 tests,
  re-verified unaffected by this phase's tightened bar (their fixtures already use GOOD-band
  dimensions with no warnings).

**`tests/test_content_cycle_story_delivery.py`**
- `test_router_mode_multi_image_update_preserves_reply_to_message_id` — extended with an
  assertion that `edit_message_reply_markup` is called once, targeting the group's first message
  (`1001`, not the reply-target `999`), with the correct source URL — proves the button fix and
  UPDATE reply-threading are independent mechanisms that do not interfere with each other.

**Full validation sweep run this phase:**
- `python -m py_compile worker/content_cycle.py` — clean.
- `python -m ruff check worker/content_cycle.py services/telegram_routing.py services/image_persistence.py tests/test_router_media_integration.py tests/test_content_cycle_story_delivery.py` — clean.
- `python -m mypy worker/content_cycle.py services/telegram_routing.py services/image_persistence.py` — clean (no issues).
- `python -m mypy tests/test_content_cycle_story_delivery.py` — clean.
- `python -m mypy tests/test_router_media_integration.py` — 9 pre-existing errors remain, all in
  code this phase did not touch (`test_source: object` parameter typing used throughout this
  file's existing fixtures since before this phase, plus one pre-existing generator-typing note on
  the file's own `_reset_delivery_mode` fixture) — not introduced by this phase. The one new-code
  mypy error this phase's own tests introduced (`TelegramAPIError(method=None, ...)`) was fixed
  with a `# type: ignore[arg-type]`, matching this codebase's own established convention for the
  same construct in `tests/test_telegram_editorial_routing.py`/`tests/test_telegram_notifier.py`.
- `pytest tests/test_router_media_integration.py` — 32 passed (29 DB-backed tests each show the
  documented teardown-only error; 3 are pure/sync tests with no DB teardown at all).
- `pytest tests/test_content_cycle_story_delivery.py` — 9 passed (same teardown pattern on all 9,
  since all are DB-backed).
- `pytest tests/test_news_telegram_presentation_v81.py tests/test_telegram_editorial_routing.py` —
  36 passed, no errors (no DB fixtures in these files).

## 7. Remaining risks / disclosed gaps (not in scope for this phase)

- `scripts/_canary_delivery_cap.py`'s `HardDeliveryCap`/`wrap_bot_with_hard_cap` does not wrap
  `bot.send_media_group()` (only `send_message`/`send_photo`) — a real safety gap for any future
  live canary involving multi-image delivery, flagged during the earlier forensic audit, not fixed
  here (out of scope; a canary operator must be aware a hard cap will not stop a media-group send).
- `story_reuse_match` (cross-STORY reuse, `services/media_ranking.py`'s own separate concern from
  within-one-event duplication) remains unwired — this phase wires within-event duplication only,
  as explicitly authorized.
- The tightened additional-image bar's calibration is directly evidenced by the real forensic
  examples above; it has not been validated against a broader live sample. If a legitimate
  ADEQUATE-band (300–599px shortest side) secondary image turns up excluded in practice, that
  threshold — not the mechanism — would need recalibration.

## 8. Explicit scope confirmation

- Not committed. Not deployed. No live canary run.
- Video activation work was not resumed.
- No DB migration added or applied in this phase.
- No media-architecture redesign — every change reuses existing, already-calibrated
  functions/constants (`resolution_band`, `hamming_distance`,
  `_NEAR_DUPLICATE_MAX_HAMMING_DISTANCE`, `build_source_only_keyboard`,
  `edit_message_reply_markup`).
- Single-photo and text-only source-button behavior is unmodified.
