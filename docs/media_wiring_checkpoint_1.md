# Media Wiring Checkpoint 1 — Multi-Image Activation

Branch `feature/phase19-editorial-depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb`
(unchanged, nothing committed). Step 1 of the Media Roadmap Recovery follow-up: wiring only,
activating already-built Phase 19 M11 (`rank_media_candidates()`) and M12
(`build_rich_media_plan()`) into the real router-mode NEWS delivery path. No redesign, no new
schema, no second media pipeline, no video activation (Step 2, not started).

---

## Exact files changed

**Production code (3 files):**
- `services/telegram_routing.py` — **one new function added**, `send_media_group_to_editorial_destination()`, mirroring `send_to_editorial_destination()`/`send_photo_to_editorial_destination()`'s exact dry-run/error-handling/destination-resolution contract for `bot.send_media_group()`. No existing function in this file touched.
- `worker/content_cycle.py` — the router branch's image-selection loop replaced with ranking-based multi-candidate selection; the send-decision block extended with a third branch (media group); two new private helpers (`_build_media_ranking_input()`, `_select_top_ranked_image_candidates()`) added as glue, following this file's own established `_extract_scoring_result()`-style precedent for translating between two already-built modules' shapes; one new `ContentCycleResult` counter (`router_media_group_sent`). Non-V8-family (legacy V4/V6/V7) output path left **byte-identical** to before — untouched, since no real canary has ever used it.
- (Reused, **not modified**: `services/media_ranking.py`, `schemas/media_ranking.py`, `services/image_preview_notifier.py::build_rich_media_plan()`, `services/image_quality.py::aspect_ratio_band()`, `services/image_relevance.py::PROVENANCE_TABLE` — every one of these is imported and called exactly as it already existed.)

**Tests (2 files):**
- `tests/test_router_media_integration.py` — `_fake_candidate()` extended with optional, backward-compatible params (`candidate_id`/`rank`/`quality_score`/`relevance_score`); 6 new tests.
- `tests/test_content_cycle_story_delivery.py` — 1 new test (multi-image UPDATE + reply-threading).

**No new file added to `services/`, `schemas/`, or `database/models/`. No migration. No new setting in `core/config.py`.**

---

## Exact dormant components activated

| Component | Prior state | Now |
|---|---|---|
| `services/media_ranking.py::rank_media_candidates()` (Phase 19 M11) | Built, tested, never called from any live/canary path | Called once per V8-family router-mode draft with eligible candidates |
| `services/image_preview_notifier.py::build_rich_media_plan()` (Phase 19 M12) | Built, tested, never called from `worker/content_cycle.py` | Called for the same drafts, capped to 3 candidates |
| `services.telegram_routing`'s destination-resolution pattern for `send_media_group` | Did not exist at all | New function added, mirroring the 2 existing ones exactly |

`send_news_with_rich_media()` itself (the M12 function that *also* internally calls
`render_editorial_card()`) was deliberately **not called** — see "whether rich-media code
required modification" below for why.

---

## Before/after live call path

**Before (every real canary so far):**
```
get_editorial_image_candidates() -> for candidate in image_candidates:
    skip expired / cross-event-duplicate
    resolve_photo_input(candidate)
    break                                    # ALWAYS stops after the first survivor,
                                              # even if resolution returned None
-> send_photo_to_editorial_destination() (1 image) or send_to_editorial_destination() (text-only)
```

**After:**
```
get_editorial_image_candidates() -> filter expired / cross-event-duplicate -> eligible_candidates
    |
    V8-family output?
    |-- yes --> _build_media_ranking_input() per candidate (reuses PROVENANCE_TABLE,
    |           aspect_ratio_band(), quality_warnings - all already-computed signals)
    |           -> rank_media_candidates()                          [Phase 19 M11, unmodified]
    |           -> top _MAX_ROUTER_IMAGES(=3) eligible, ranked
    |           -> build_rich_media_plan(top_candidates, None, caption=html)
    |                                                               [Phase 19 M12, unmodified]
    |              (internally: resolve_photo_input() per candidate, SKIPPING failures and
    |               continuing to the next-ranked one - "a single broken image never kills
    |               the whole media opportunity" falls out of this existing logic for free)
    |           -> >=2 resolved: send_media_group_to_editorial_destination() [NEW]
    |              (source link folded into caption text - media groups have no
    |               reply_markup at all, a real Telegram API constraint)
    |           -> exactly 1 resolved: existing single-photo path, unchanged
    |           -> 0 resolved: existing text-only path, unchanged
    |-- no  --> legacy behavior, byte-identical to before (never used by any real canary)
```

Every step of the "after" path that isn't new glue code is a call into already-existing,
already-tested Phase 19 M11/M12 functions.

---

## Whether rich-media code required modification, or only call-site wiring

**Neither, exactly.** `build_rich_media_plan()` needed **zero modification** (it already accepts a
pre-rendered `caption: str` parameter — this was the key discovery that made "wiring only"
possible). But `send_news_with_rich_media()` — the M12 function that wraps
`build_rich_media_plan()` end-to-end — **could not be called as-is**: it internally renders its
own caption via `bot/formatting.py::render_editorial_card()` (the legacy V6-shaped card), which
would have silently replaced the V8.6 card (with its quote block and NINJA PULSE footer) with the
legacy format for every media-group send. Rather than modify that function (which is shared with
the legacy `image_editorial_preview_enabled` flow and not safe to touch for this narrow step), the
wiring **bypasses it entirely** and calls `build_rich_media_plan()` directly from
`content_cycle.py`, passing the already-correct V8.6 `html` as the caption — then sends the
resulting `media_group_items` through one new, thin routing function
(`send_media_group_to_editorial_destination()`) that mirrors the two already-existing router-mode
send functions. **No existing rich-media file (`services/image_preview_notifier.py`) was modified
at all.** The one genuinely new piece of logic is the source-link-in-caption fallback (below),
required by a real Telegram platform constraint, not a design choice.

---

## Test results

All individually verified against the pre-existing, already-documented teardown-only FK cleanup
pattern (confirmed via isolated `1 passed, 1 error` runs for the most complex new cases) — zero
real failures anywhere.

**New tests (7, all passing):**
1. `test_three_useful_ranked_images_send_as_a_media_group` — 3 images ranked → media-group delivery, standalone (NEW post, `reply_to_message_id=None`).
2. `test_five_candidates_selects_at_most_three` — 5 candidates → exactly 3 selected.
3. `test_first_candidate_fails_second_and_third_succeed_media_still_delivered` — highest-ranked candidate unresolvable → the 2 next-ranked still deliver.
4. `test_all_candidates_fail_to_resolve_falls_back_to_text_only` — 3 unresolvable candidates → text-only, no crash, no empty `send_media_group` call.
5. `test_media_group_caption_includes_quote_footer_and_source_link` — quote + NINJA PULSE footer + folded-in source link all present, in the correct order, only on the first media-group item.
6. `test_router_mode_multi_image_update_preserves_reply_to_message_id` — a confirmed UPDATE with a resolvable root + 2 ranked images → real media-group send with `reply_to_message_id` pointing to root, `message_thread_id` independently correct, delivery persisted as `REPLY`.

**Existing tests re-run for regression (32 passed / 0 failed across the full router-media + story-delivery + editorial-delivery-mode + telegram-routing + V8.1-presentation suites — all remaining ERRORs are the pre-existing teardown pattern, confirmed via isolated re-runs):** all single-image cases, caption-overflow fallback, source-button preservation, quote rendering, footer rendering, legacy-mode isolation, reply-threading enforce/shadow/off modes — every one still passes unchanged.

Ruff and mypy: clean on all changed files.

---

## Remaining risks

1. **Media-group sends don't cache resolved Telegram `file_id`s for reuse** (unlike the
   single-photo legacy path's `record_telegram_file_id()` call) — a disclosed, minor
   inefficiency (a re-sent image would be re-uploaded rather than reusing a cached `file_id`), not
   a correctness issue. Not required by this step's own test list; can be added later if desired.
2. **`story_reuse_match`/`is_duplicate_within_event` are not wired into `MediaRankingInput`** this
   step — disclosed in `_build_media_ranking_input()`'s own docstring. Duplicate handling is still
   fully governed by the two *existing* mechanisms already active before this phase
   (within-event dedup at discovery time, cross-event `get_recently_attached_image_source_urls()`
   guard) — satisfying the "governed by existing ranking" requirement — but M11's own additional
   story-scoped perceptual-reuse check specifically is not yet reachable, since it needs
   `sha256`/`perceptual_hash` fields `EditorialImageCandidate` doesn't currently expose and a
   resolved `story_id`.
3. **This has never been exercised against real Telegram infrastructure** — every test uses a
   mocked `bot`. The real `bot.send_media_group()` call, real Telegram size/format handling, and
   real multi-candidate ranking against genuine live image data remain unproven until a live
   canary is authorized.
4. **`_MAX_ROUTER_IMAGES = 3` is a hardcoded module constant**, not a settings field — per your
   explicit instruction not to raise it without authorization; also not made configurable, since
   no configuration mechanism was requested and none existed for this specific value before.
5. **The source-link-in-caption fallback for media groups is new, narrow logic** (not a reuse of
   existing code, since no prior code path needed to solve "no keyboard available" this way) —
   the smallest necessary addition to satisfy "source button remains present," but it is
   genuinely new, not activated-dormant code, and is called out here rather than folded silently
   into "reused" components.

---

## STOP

Step 1 complete per your instruction. No video activation performed. Awaiting review before
Step 2 (video activation review — report only, no implementation).
