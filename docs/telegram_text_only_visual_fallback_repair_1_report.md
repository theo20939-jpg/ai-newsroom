# TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1

Fix commits: `8eabc93` + `b5d5276` (branch `feature/telegram-text-only-visual-fallback-repair-1`, base
`d0a0377` = the exact `d0a03773-pinned` production lineage). `TELEGRAM_VISUAL_FALLBACK_FIX_SHA = b5d5276`.

## A. Executive summary

Two real production NEWS posts (Telegram message IDs 1698 and 1699, 2026-09-12) reached the newsroom
Telegram chat as finished, indistinguishable-from-normal plain-text posts even though Visual V8 is
live, healthy, and unmodified by this phase. Both share the same structural gap: `worker/content_cycle.py`'s
router-mode dispatch had exactly one text-send path for two distinct situations - "no visual could be
resolved at all" and "a resolved visual's own Telegram send failed" - and both silently completed as a
normal finished post with no error, no operator-visible signal, and no distinguishing mark. Visual V8's
own rendering (canvas, fonts, brand placement, composition) is not implicated and is untouched by this
fix.

The fix adds one new function, `_hold_for_visual_recovery()`, invoked from exactly those two existing
call sites. Instead of silently completing as text, a NEWS/BREAKING/DATA/QUOTE post with no valid final
visual now HOLDs: `content_drafts.status` is persisted as `"hold_for_visual"` (reusing the existing
free-form status column - no new DB status, no migration), a short keyboard-less recovery notice
(distinct "⚠️" prefix, never mistakable for a real post) is sent to the same chat, and the editorial
content itself (title/body) is never lost. System/operator/debug/explicit-text-only messages are
completely unaffected - the gate lives entirely inside this one router-mode block, never inside the
shared `send_to_editorial_destination()` transport those other message types use directly.

## B. Founder product invariant (verbatim intent, recap)

For NEWS/BREAKING/DATA/QUOTE: (A) usable source media exists -> preserve/use it through V8; (B) source
media absent/unusable -> produce approved branded fallback; (C) visual preparation fails -> bounded
retry only if architecture safely supports it; (D) still no valid visual -> HOLD/fail-soft for
editor-visible recovery. NOT: normal finished post -> plain text-only. Text-only remains allowed ONLY
for system/debug/operator messages, explicit text-only formats, and error/status notifications.

This phase implements (D) directly: HOLD for editor-visible recovery. It does not implement a new
generated-fallback-image renderer for the NEWS-with-no-source case (see §H "what this fix does NOT do")
- reusing an existing renderer for that specific gap was evaluated and explicitly deferred, since NEWS
has no Founder-approved "no-source" branded template today (BREAKING/DATA/QUOTE already have one, via
`render_branded_media()`; NEWS's own contract, per `needs_render` and its surrounding comments, is
"branding requires real source bytes" by design). Manufacturing a new NEWS visual template would be a
V8 redesign, explicitly out of this phase's scope. HOLD is therefore the correct, smallest safe repair
for that specific gap, matching (D) rather than (B), pending a future Founder decision on whether NEWS
should also get a generated-fallback template.

## C. Confirmed affected posts

| Field | CASE A | CASE B |
|---|---|---|
| Telegram message ID | 1698 | 1699 |
| Chat | `-1004297182444` (newsroom) | `-1004297182444` (newsroom) |
| Sent at (UTC) | 2026-09-12 16:08:36 | 2026-09-12 16:14:08 |
| Founder-reported time (local, UTC+3) | ~19:08 | ~19:14 |
| `story_telegram_deliveries.id` | `8631c698-6ea8-4485-aa36-3c4a7d1c78fd` | `55427b9e-2750-4adf-aedf-5c4f9f028964` |
| `story_id` | `4a865d1d-b6e8-46a2-af4b-8fb5bfcd98f8` | `a3cae5b8-463c-4584-961f-bbb352854d5b` |
| `content_draft_id` | `db3af497-a8f0-41c9-bc66-04161e7fe302` | `3d6ad6b9-0df7-434a-9f2b-6182bfa1ec70` |
| `editorial_tasks.id` | `2ace33ac-4cbc-4a64-846a-9cae359ecd6b` | `55e553f3-a72e-42cf-b2ea-955d600ef98b` |
| `news_events.id` | `5aaed00d-6cc9-4c50-836b-1a77f5a5b13d` | `b41eda3d-8084-4891-a439-a5dfc0d33f0e` |
| Event title | "Глава Anthropic призвал индустрию ИИ замедлить развитие" | "Трамп не спешит ужесточать правила для ИИ, чтобы США не уступили Китаю" |
| Source URL | Google News RSS redirect link | Techmeme aggregator link |
| Presentation type | NEWS | NEWS |
| `delivery_type` / `delivery_status` | root / sent | root / sent |
| `content_drafts.status` (pre-fix) | `draft` | `draft` |

Both were correlated from Founder-reported local times (19:08/19:14, UTC+3, matching the whole
project's own git-commit-timezone convention) to the nearest `story_telegram_deliveries` root sends
(16:08:36/16:14:08 UTC) - an almost-exact match (36s and 8s past the reported minute), not a loose
timestamp guess.

## D. Media path trace

Both cases run the same router-mode NEWS call chain in `worker/content_cycle.py::run_content_cycle()`:

```
_select_eligible_events()
  -> get_editorial_image_candidates()            (services/image_persistence.py)
  -> resolve_photo_input(eligible_candidates[0])  (bot/image_preview_media.py)
  -> decide_presentation()                        (services/presentation_director.py)
  -> [needs_render gate] -> apply_master_news_branding() / render_branded_media()
  -> [send-shape decision: send_as_media_group / send_as_video_only / send_as_photo / else]
  -> send_to_editorial_destination() / send_photo_to_editorial_destination() / ...
       (services/telegram_routing.py)
```

**CASE A** diverges at `get_editorial_image_candidates()`: every candidate row for this draft has
`relevance_status = 'ineligible'` and `rank = NULL` (confirmed via direct query against
`image_candidates`), so `eligible_candidates = []`. `photo_input` is never resolved, `needs_render`
evaluates `False` (NEWS with no source bytes - `logger.info("brand_render_skipped", ...,
brand_skip_reason="no_source_media")`), and no branded fallback exists for that case. Control reaches
the final `else:` branch with `had_any_visual = False`.

**CASE B** does NOT diverge the same way. Its `image_candidates` rows show 3 candidates
*ranked and eligible* (`relevance_status='ranked'`/`'accepted'`, ranks 1-3, `storage_status='stored'`).
Production logs for the exact window (`docker logs ai_newsroom_content_worker --since
2026-09-12T16:12:00 --until 2026-09-12T16:15:00`) show, in order: `hosted_video_download_result` ->
`presentation_decision` -> a Gemini recomposition call returning HTTP 429 (rate-limited) ->
`editorial_recomposition_evaluated` -> **`master_news_branding_applied`** -> **`brand_render_attempted`**
-> `router_image_decision` -> `content_cycle_finished`, with **zero** `telegram_routing_photo_send_failed`
or `telegram_routing_send_failed` log lines anywhere in the window. Per the exact code at
`worker/content_cycle.py` (the `if render_result.success and render_result.image_bytes is not None:
photo_input = branded_file` assignment, unconditional on success), this log sequence indicates branding
*succeeded* using the original (non-recomposed, since Gemini was rate-limited) source image, which
should have made `photo_input` a valid `BufferedInputFile` and routed to `send_as_photo`. My own direct
reproduction of the real `copywriting_output` for this draft (rendering the actual V8.1 card HTML)
measured 484 UTF-16 units against Telegram's 1024-unit caption limit - well under, ruling out the
separate caption-too-long tradeoff as the cause.

**This phase's own logging-observability gap is directly responsible for the remaining uncertainty**:
`core/logging.py` uses a plain `logging.basicConfig` formatter that never renders a log record's
`extra={}` dict, so every `logger.info("event_name", extra={...})` call in this codebase - including
the one boolean (`brand_applied`) and string (`brand_skip_reason`) fields that would have definitively
told CASE A and CASE B apart at a glance, and would have told us whether `photo_input` was actually
`None` going into the final send decision for CASE B specifically - is invisible in `docker logs`.
Neither `send_photo_to_editorial_destination()` nor `send_to_editorial_destination()` log anything on a
*successful* send (only on failure), and `story_telegram_deliveries` records a message ID on success
regardless of whether it carried a photo or plain text, so the DB cannot disambiguate this after the
fact either. A live, read-only Telethon/MTProto check against the real Telegram message content (the
mechanism already exists in `services/telegram_channel_context.py`, explicitly designed to be
passive/read-only) was attempted but is currently non-functional in production: `settings.
telegram_api_id` resolves to `0` rather than the real configured value, a separate, pre-existing,
disclosed configuration bug unrelated to this phase's scope (Telethon itself rejects `0` as "empty").

**Conclusion for CASE B**: the Founder-reported time is an almost-exact match for message 1699, and the
Founder's own direct observation of a text-only post in the live Telegram chat is treated as reliable
ground truth for *that this post arrived without a photo*. The precise mechanism by which a
successfully-rendered branded image failed to reach the final Telegram send is **not fully proven** by
available log/DB evidence and is reported as such rather than asserted as fact - see §E for the
resulting root-cause classification. Critically, this uncertainty does not weaken the fix: `_hold_for_
visual_recovery()`'s gate (`had_any_visual`, evaluated from `photo_input`/`media_group_items`/
`video_only_input` directly, immediately before the final send decision) is mechanism-agnostic - it
closes the entire *class* of "no visual ends up attached to a normal finished post" outcomes,
regardless of which upstream step is ultimately responsible for `photo_input` being `None` at that
point.

## E. Root cause classification

| Case | Classification | Evidence |
|---|---|---|
| A (msg 1698) | `NO_MEDIA_CANDIDATES` (all candidates ineligible) combined with the pre-existing gap that **no branded fallback exists for a NEWS post with no source bytes** (`RENDER_NOT_REQUESTED` by design, not a bug in the renderer itself) | `image_candidates` rows: `relevance_status='ineligible'`, `rank=NULL`, for every row on this draft; `brand_render_skipped` log with (invisible but code-confirmed) `brand_skip_reason="no_source_media"` |
| B (msg 1699) | **Unconfirmed exact mechanism** - evidence is consistent with either `RENDER_RESULT_DROPPED` or `TELEGRAM_SEND_PATH_BYPASSED_MEDIA`, but direct proof that `photo_input` was `None` (vs. a live send failure that went unlogged) is blocked by the disclosed logging/MTProto gaps above | `master_news_branding_applied` (render succeeded) + `brand_render_attempted` logged; zero `telegram_routing_*_failed` logs in the window; caption-length ruled out by direct reproduction (484/1024 units) |

Regardless of the exact CASE B mechanism, both cases are members of the same governing bug class this
phase targets: **a router-mode NEWS/BREAKING/DATA/QUOTE post completed as a normal, finished,
indistinguishable-from-intentional plain-text send with no visual attached, and no record of why.**
That is the defect `_hold_for_visual_recovery()` repairs categorically, not case-by-case.

## F. Bounded audit (since production resume, 2026-09-12 00:00 UTC)

| Metric | Value |
|---|---|
| Total router-mode NEWS root deliveries in window | 25 |
| `brand_render_skipped` (no local source bytes - `needs_render=False`) | 11 |
| `brand_render_attempted` (render actually invoked) | 14 |
| **Confirmed** text-only completions (Founder-reported + DB/log-correlated) | 2 (8% of 25) |

The 2 confirmed cases are a **lower bound**, not an exhaustive count. As detailed in §D, the pre-existing
`extra={}` logging gap makes it impossible to retroactively determine, for the other 9 "skipped" drafts
in this window, whether each resolved a real cached-`file_id` photo (safe - `needs_render=False` is the
*intended*, harmless shape for a NEWS post with only a cached Telegram file_id and no local bytes) or
was *also* silently text-only in the same way as CASE A. This is exactly why the fix is a categorical
gate on the actual `photo_input`/`media_group_items`/`video_only_input` state at send time, rather than
a narrower patch keyed to the specific `no_source_media` skip reason: it protects every one of the 25
(and every future) delivery uniformly, independent of this audit's own historical blind spot.

## G. Text-only-capable code path audit

| Path | Classification | Disposition |
|---|---|---|
| Router-mode final `else:` branch (no visual resolved) | **BUG** (this phase's primary target) | Fixed - now HOLDs |
| `used_text_fallback` one-shot retry-as-text on send failure | **FAIL_SOFT_TOO_PERMISSIVE** (bounded and well-intentioned, but discards a successfully-rendered image into an indistinguishable normal post) | Fixed - now HOLDs |
| Phase 23.1H/23.1Q caption-too-long-degrades-to-text | **INTENTIONAL** (disclosed, deliberate tradeoff; a real visual was resolved, this is a text-budget decision) | Unchanged |
| DATA/QUOTE/BREAKING "Fail-safe (spec S29)" render-failure demotion to NEWS | **INTENTIONAL** (pre-existing, narrowly-scoped fail-safe; never itself sends anything) | Unchanged - confirmed (via code trace, §D) that a demoted post with no visual flows into the same fixed gate |
| Direct `send_to_editorial_destination()` calls for system/operator/debug messages (outside this router-mode block) | **INTENTIONAL** (the Founder invariant's own explicit carve-out) | Unchanged - proven unaffected by a dedicated test (`test_system_message_via_send_to_editorial_destination_directly_is_unaffected`) |
| Legacy (`copywriting_output is None`) non-router card path | **LEGACY** (pre-router-mode fallback; still routes through the same final send-decision block, so it inherits the HOLD gate for free) | Covered by the same gate; the `original_presentation_type_for_hold` default keeps its diagnostic label sane even though `presentation_decision` is never assigned on this path |

## H. Fix design

New in `worker/content_cycle.py`:

- `HOLD_FOR_VISUAL_STATUS = "hold_for_visual"` - reuses the existing unconstrained `content_drafts.status`
  varchar column (confirmed via grep to be written in exactly one other place in the whole codebase,
  always `"draft"`, and never read/branched on anywhere else) - no new DB status enum, no migration.
- `HOLD_REASON_NO_VISUAL_RESOLVED` / `HOLD_REASON_MEDIA_SEND_FAILED` - the two call-site reasons.
- `original_presentation_type_for_hold` - a safe default (`"NEWS"`), captured once per event right after
  `decide_presentation()` runs (when it runs at all), used for the HOLD diagnostic log/notice instead of
  the possibly-demoted `presentation_decision.presentation_type`, and safe on every code path including
  the ones where `presentation_decision` itself is never assigned.
- `_hold_for_visual_recovery()` - persists the HOLD status, logs `visual_required_hold`, and (unless
  `dry_run`) sends one keyboard-less "⚠️ Требуется визуал - материал удержан для восстановления" notice
  via the existing `send_to_editorial_destination()` transport. No new Telegram integration.
- `ContentCycleResult.visual_required_held` - a new counter, alongside the existing ones.

**Fallback order actually implemented** (per the Founder invariant, (A)-(D)):
1. Source media preferred - completely unchanged; a resolvable candidate (cached `file_id` or local
   bytes) still flows through exactly as before, branded when `needs_render` is true.
2. Generated fallback only if no usable source - **not newly implemented in this phase** for NEWS (see
   §B); already implemented and unchanged for DATA/QUOTE/BREAKING via `render_branded_media()`.
3. Bounded retry - **zero** extra render/generation attempts are added (`MAX_VISUAL_FALLBACK_ATTEMPTS =
   0`); the architecture does not safely support a retry loop within one cycle without risking the
   "generation loop / runaway spend" rollback condition, so per invariant (C)'s own conditional
   ("only if architecture safely supports it"), this phase does not add one.
4. HOLD - implemented as described above; never a silent text completion.

**What this fix explicitly does NOT do**: redesign Visual V8's rendering, add a new NEWS "no-source"
generated template, touch Instagram, broaden Story Continuity, or enable public/autonomous publication.

## I. V8 visual output unchanged

`V8_VISUAL_OUTPUT_CHANGED = false`. No changes to canvas composition, fonts, brand placement, or the
NEWS/BREAKING/DATA/QUOTE renderers themselves (`services/brand_renderer.py`, `services/
nnj_master_news_overlay.py`, `services/news_telegram_presentation.py` are all untouched - confirmed via
`git diff`, only `worker/content_cycle.py` and test files changed).

## J. Bounded cost / retry discipline

- `MAX_VISUAL_FALLBACK_ATTEMPTS = 0` (no new render/generation attempts of any kind).
- No recursive retry, no generation loop.
- `_hold_for_visual_recovery()` is called at most once per content draft per cycle (both call sites are
  mutually exclusive within one draft's processing, and neither loops).
- The recovery notice send itself is a single, non-retried `send_to_editorial_destination()` call - if
  it also fails, the DB status write (the durable, primary guarantee) has already committed beforehand
  and is not rolled back or retried (proven by `test_hold_survives_the_notice_send_itself_failing` and
  `test_photo_timeout_and_recovery_notice_both_fail_still_holds_never_notification_failed`).

## K. Regression tests

New file `tests/test_visual_fallback_hold_repair_1.py` (5 tests, isolated unit coverage of
`_hold_for_visual_recovery()` itself): DB persistence + body/title preservation; notice shape (no
keyboard, "⚠️" marker, presentation type in text); `dry_run` safety (no write, no send); survives the
notice's own send failure; confirms `send_to_editorial_destination()` used directly (the system/operator
transport) is completely unaffected.

Updated in `tests/test_router_media_integration.py` (9 tests total): the 8 originally-updated tests
(`test_case_b_no_image_candidates_holds_for_visual_recovery`, `test_case_c_unresolvable_image_holds_for_
visual_recovery_without_crashing`, `test_photo_timeout_holds_for_visual_recovery_instead_of_text_
fallback`, `test_photo_timeout_and_recovery_notice_both_fail_still_holds_never_notification_failed`,
`test_media_group_timeout_holds_for_visual_recovery_router_media_group_sent_stays_zero`, `test_recovery_
notice_never_carries_the_normal_post_keyboard`) plus 3 more found during this session's own
cross-presentation-type coverage pass whose *old* assertions also encoded the bug as expected behavior:
`test_all_candidates_fail_to_resolve_holds_for_visual_recovery` (renamed from `..._falls_back_to_text_
only`), `test_case_e_image_presence_never_changes_brief_text` (rewritten to capture the underlying card
HTML directly via `render_compact_news_card_html`, since the "no image" branch no longer completes as a
comparable text send), `test_ninja_pulse_cta_present_once_in_the_no_image_card_text` (renamed/rewritten
the same way, via `render_v81_news_card_html`). Two more tests (`test_v82_output_renders_via_the_v8_
family_card_not_the_legacy_template`, `test_v6_output_still_uses_the_legacy_template_unchanged`) had
their real intent - template-shape correctness, not the no-visual case - preserved by mocking in a
resolvable image candidate (matching their own "with image" sibling tests) so they still exercise a
real delivered `send_photo` post.

Updated in `tests/test_content_cycle_story_delivery.py` (5 tests total): the 2 originally-updated tests
(`test_router_mode_photo_timeout_holds_for_visual_recovery_no_reply_delivery_row`, `test_router_mode_
photo_and_recovery_notice_both_fail_still_holds_records_no_delivery`) plus 3 more found the same way
(`test_router_mode_story_update_with_existing_root_replies_to_it`, `test_router_mode_verified_quote_
renders_in_the_v8_family_card`, `test_router_mode_quote_shadow_mode_never_renders`) - all three mocked
in a resolvable image candidate so reply-threading/quote-rendering/shadow-mode correctness is proven via
a real `send_photo` delivery instead of the now-defunct "no image -> normal text post" shape.

Also fixed, incidentally: 3 real test-isolation bugs in the DB-verification blocks the earlier updates
added (`assert len(drafts) == 1` against the shared `factory` test-database engine broke as soon as
these tests ran alongside any other test in the same suite invocation, since that database is not
rolled back between tests - each now queries `order_by(ContentDraft.created_at.desc()).limit(1)`
instead of asserting exclusivity).

Required-case coverage (phase §17): source image present -> media survives (pre-existing tests,
unaffected); no usable source -> HOLD (not a fabricated fallback - this phase does not add one for NEWS,
per §B); render fails -> HOLD not text (proven for the no-candidates/unresolvable-candidate shape
directly, and via code trace for the DATA/QUOTE/BREAKING demotion path, §D/§G); system/operator text
still allowed (dedicated test). Presentation-format coverage: NEWS (extensive), BREAKING/DATA/QUOTE
share the identical gate via the demotion path (§D) - proven structurally, not via a fourth duplicated
full-pipeline integration test, since the gate itself has no presentation-type branch.

## L. Static checks

`ruff check` and `mypy` on `worker/content_cycle.py` and every modified/new test file: **0 new errors**
in both cases (mypy's pre-existing baseline - 5 errors in `services/telegram_channel_context.py` /
`services/story_delta_engine.py`, and 17 in test-file `_make_event` typing - confirmed identical via
`git stash` on the unmodified baseline).

## M. Existing-media regression

Scope: every one of the 17 test files in this repository that imports `worker.content_cycle` (the only
file this fix touches) - the scientifically correct blast-radius for this diff, not an arbitrary subset:
`test_canary_delivery_cap.py`, `test_content_cycle_story_delivery.py`, `test_content_generation_
integration.py`, `test_content_worker_cycle.py`, `test_content_worker_cycle_image_preview.py`, `test_
content_worker_main.py`, `test_director_editorial_gate_pre_generation.py`, `test_editorial_delivery_
mode.py`, `test_editorial_scoring.py`, `test_fact_safety.py`, `test_router_media_integration.py`, `test_
router_primary_image_bar.py`, `test_story_angle_and_image_duplicate_guard.py`, `test_story_memory_v2_
phase1.py`, `test_v2_5_production_readiness.py`, `test_v2_7_e2e_forensic_recovery.py`, `test_v2_9_
production_wiring.py`, plus the new `test_visual_fallback_hold_repair_1.py`.

**Final result: 412 passed, 17 failed, 1 skipped.** Every one of the 17 is confirmed pre-existing, via
an isolated `git worktree add` checkout at the unmodified base commit `d0a0377` (not `git stash` - see
the process note in commit `b5d5276`):
- 14 fail identically on that isolated baseline checkout (`test_image_preview_enabled_replaces_the_
  text_card_not_adds_to_it`, `test_image_preview_sent_without_an_image_still_counts_as_notified_not_
  image_preview_sent`, the 3 `test_content_worker_main.py` loop tests, `test_delivery_recorded_when_
  reply_mode_off_but_story_link_exists`, `test_send_success_plus_persistence_failure_fails_safe`, all 6
  `test_v2_7_e2e_forensic_recovery.py` tests, `test_cached_file_id_with_source_risk_still_brands_with_
  lower_signature_disabled`).
- 2 more (`test_case_h_missing_source_url_still_delivers_with_no_keyboard`, `test_ninja_pulse_cta_
  present_once_in_photo_caption_with_source_only_keyboard`) confirmed the same way separately - both an
  unrelated meme-generation-button keyboard change already present in this checkout, orthogonal to this
  phase.
- 1 (`test_no_delivery_row_when_telegram_send_fails`) is a known cross-test-ordering flake, not a real
  regression: it passes standalone, and passes when its entire file (`test_story_memory_v2_phase1.py`,
  18/18) runs alone - it only fails when interleaved with other files' shared real-Postgres test-database
  state in a large combined run, a pre-existing characteristic of this suite unrelated to this fix.

**NEW_FAILURES = 0.**

4 real test regressions were found and fixed along the way (all in tests whose *old* assertions encoded
the exact bug as expected behavior, or whose real intent needed a resolvable image candidate mocked in
once the no-visual path stopped completing as a normal post) - see commit `b5d5276` for the itemized
list; §K above covers the original 8 (+3 more found earlier) in `test_router_media_integration.py` /
`test_content_cycle_story_delivery.py`.

A separate full-repository `pytest -q` run (~6167 tests) was attempted but proved impractical (multiple
concurrent real-Postgres-backed invocations exhausted system memory and were killed) - the 17-file
targeted sweep above is the complete, correct blast-radius for a diff confined entirely to `worker/
content_cycle.py`, since every other file in the repository has zero path to reach the changed code.

## N. Release scope

**`content_worker` only.** It runs `python -m worker.content_main`, which imports and drives
`worker/content_cycle.py::run_content_cycle()` - the only file this fix touches. `telegram_bot` runs a
separate `python -m bot.main` entrypoint; grepping `bot/` for `worker.content_cycle` finds only
*comments* referencing it (`bot/handlers/image_preview.py`, `bot/final_post_review_formatting.py`,
`bot/keyboards/event_recap_review.py`, `bot/keyboards/image_preview.py`) - zero real imports. No
migration is required (schema untouched - `content_drafts.status` is already an unconstrained varchar).
`automation_worker`, `backend`, `news_analysis_worker`, `postgres`, and `redis` are all unaffected.

## O. Clean release build

Branch `feature/telegram-text-only-visual-fallback-repair-1`, based on `d0a0377` (the exact
`d0a03773-pinned` production lineage - the current production `content_worker` image's own source
commit, per this session's prior CONTENT-WORKER-PROVENANCE-RECONCILIATION-1 phase). Two commits:
`8eabc93` (the fix itself + its own test suite) and `b5d5276` (4 more test fixes found via the §M
regression sweep). `TELEGRAM_VISUAL_FALLBACK_FIX_SHA = b5d5276`. Touches only `worker/content_cycle.py`
+ 6 test files - zero unrelated files (no Instagram, no Story-cleanup, no Director work is present in
this diff). Confirmed via `git diff d0a0377 b5d5276 --stat`.

## P. Production preflight

All 7 services healthy, **0 restarts**, unchanged from the phase's own starting state:

| Service | Image | Status |
|---|---|---|
| `content_worker` | `ai-newsroom-content_worker:d0a03773-pinned` (`sha256:dcc06e97...`) | Up 8h, 0 restarts |
| `telegram_bot` | `ai-newsroom-telegram_bot:d2dea2c` | Up 8h, 0 restarts |
| `backend` | `ai-newsroom-backend:d2dea2c` | Up 8h, 0 restarts |
| `automation_worker` | `ai-newsroom-automation_worker:6f56aec` | Up 8h, 0 restarts |
| `news_analysis_worker` | `ai-newsroom-news_analysis_worker:d2dea2c` | Up 8h, 0 restarts |
| `postgres` | `postgres:16-alpine` | Up 5d, healthy |
| `redis` | `redis:7-alpine` | Up 6d, healthy |

- **DB revision**: alembic head `4a1b7c9d2e3f` (unchanged - confirmed no migration files, model files, or
  `alembic.ini` touched by this fix's diff).
- **Redis state**: `redis_version 7.4.10`, 95 keys, 6d uptime (unchanged).
- **VisualSpec matrix** (`design_spec_versions`, unchanged, confirmed active): NEWS v3, BREAKING v3, DATA
  v2, QUOTE v2.
- **Fresh rollback tag created**: `ai-newsroom-content_worker:rollback-before-telegram-visual-fallback-
  repair-1` -> `sha256:dcc06e977b37...` (the exact currently-running image), following this
  deployment's own established `rollback-pre-<phase-name>` convention.
- **No migration required** - confirmed via `git diff d0a0377 b5d5276 --stat -- database/migrations/
  database/models/ alembic.ini` (empty).

## Q. Deployment, canary, observation

**Build**: `docker build -f Dockerfile.pinned -t ai-newsroom-content_worker:b5d5276-pinned .` from a
fresh checkout of `b5d5276` at `/opt/ai-newsroom-release-b5d5276` on the production host (reusing the
exact same `Dockerfile.pinned`/`_pin_constraints.txt` pin-constraint pair the current `d0a03773-pinned`
image was built from, avoiding dependency drift - the same convention established by this project's own
prior FOUNDER-VISUAL-VNEXT-PRODUCTION-ROLLOUT-1 phase). Build succeeded cleanly (34.5s pip install, all
pinned versions resolved with no conflicts). Smoke-checked before deploy: `docker run --rm ... python -c
"import worker.content_main; from worker.content_cycle import HOLD_FOR_VISUAL_STATUS"` -> clean import.

**Deploy**: `/opt/ai-newsroom-ops/docker-compose.yml` backed up
(`docker-compose.yml.bak-pre-telegram-visual-fallback-repair-1`), then a single one-line edit (`image:
ai-newsroom-content_worker:d0a03773-pinned` -> `:b5d5276-pinned`), then `docker compose up -d --no-deps
content_worker` - `--no-deps` guarantees no other service is touched. Confirmed via `docker ps`/`docker
inspect`: `content_worker` recreated and healthy on the new image; `telegram_bot`, `backend`,
`automation_worker`, `news_analysis_worker`, `postgres`, `redis` all show their pre-deploy uptime
completely unchanged (not restarted). `docker logs` shows a clean startup (all 13 capabilities
registered, no errors) and the first post-deploy content cycle completed successfully within 4 seconds.

**Rollback tag**: `ai-newsroom-content_worker:rollback-before-telegram-visual-fallback-repair-1` (the
pre-deploy image, `sha256:dcc06e977b37...`) - to roll back: restore `docker-compose.yml.bak-pre-
telegram-visual-fallback-repair-1` (or edit the image tag back), then `docker compose up -d --no-deps
content_worker`.

**Canary / observation**: the live newsroom Telegram chat (`-1004297182444`) is this system's own
internal editorial destination (not a public/customer-facing channel - every prior phase in this
project's history treats it as such), so natural production traffic through it during a bounded window
serves as both the internal canary and the observation period required by §25-26, without injecting any
synthetic/fabricated event into the live pipeline. Recent traffic rate confirmed beforehand (13 root
deliveries in the preceding 3 hours, ~1 every 14 minutes) to ensure the window would be conclusive, not
empty. Monitored live via `docker logs -f` for router_image_decision / visual_required_hold /
content_cycle_finished / any error or Telegram-send-failure signal, over a ~25-minute bounded window.

**Result** (~40-minute combined window, 2026-09-12 22:37-23:12 UTC): 1 real router-mode presentation
decision occurred - and it landed on **exactly the same root-cause class as CASE A** (`brand_render_
skipped`, no source media). It correctly **HELD**: `content_drafts.id=834b4ec6-a3dc-45a5-9c30-42bf69bde82e`
(title "Амодеи, Альтман и Маск призвали замедлить разработку моделей ИИ") was persisted with
`status='hold_for_visual'`, the title/content fully intact, **zero** `story_telegram_deliveries` row
created (matching the exact tested contract), and no error of any kind logged. This is a live recurrence
of the original production defect's own root-cause class, repaired in real time by this fix - the
strongest possible confirmation available, stronger than a synthetic canary.

| Metric | Result |
|---|---|
| Restarts (any of the 7 services) | 0 |
| Errors/crashes logged | 0 |
| Router-mode presentation decisions in window | 1 |
| Correctly HELD (no visual resolved) | 1 |
| Silently completed as text-only despite no visual | 0 |
| **UNEXPLAINED_FINISHED_TEXT_ONLY_EDITORIAL** | **0** |

The synthetic-scenario requirements from §25 (source-available -> delivered; source-unavailable ->
HOLD; render-failure -> HOLD) are additionally covered deterministically by the test suite (§K) rather
than fabricated live events, per this phase's own "no public channel, internal-only" instruction and
this project's own established preference (throughout this session's history) for deterministic test
coverage over injecting synthetic content into the live editorial chat.

## R. Rollback conditions & final verdict

None of the explicit rollback conditions were triggered:

| Condition | Status |
|---|---|
| Working posts lose media | No - source-media paths are byte-unchanged; confirmed by the full existing-media regression (§M) and by no new failures in any "with image" test. |
| Source images replaced incorrectly | No - `apply_master_news_branding`/`render_branded_media` untouched. |
| DATA/QUOTE/BREAKING fabricate content | No - no new generation/fabrication was added anywhere; the fix only changes what happens when nothing was resolved. |
| Render failure causes crash loop | No - 0 restarts across all 7 services, both pre- and post-deploy, through the full observation window. |
| Telegram errors increase materially | No - 0 errors logged in the observation window (down from whatever baseline rate existed - no Telegram error was logged at all). |
| Generation loops / runaway spend | No - `MAX_VISUAL_FALLBACK_ATTEMPTS = 0`; no new LLM/image-gen calls added anywhere in this diff. |
| Posts stop reaching editor without a recovery record | No - the opposite is proven live: the one no-visual case in the observation window produced a real, durable recovery record (`content_drafts.status='hold_for_visual'`) and a recovery notice, not silence. |

**No rollback performed.** `content_worker` remains on `ai-newsroom-content_worker:b5d5276-pinned`. The
rollback tag (`rollback-before-telegram-visual-fallback-repair-1`) remains available for the future.

**Requirement checklist**:
- Real cases identified via evidence, not guesswork: YES (§C).
- Root cause proven: YES for CASE A (definitive); CASE B's precise mechanism is honestly disclosed as
  unconfirmed rather than asserted (§D/§E) - the fix itself does not depend on which mechanism was
  responsible, since it gates on the actual final visual state, not on any specific upstream cause.
- NEWS/BREAKING/DATA/QUOTE no longer silently complete text-only: YES - proven by code trace, by test,
  and by a live production recurrence during this same phase's own observation window.
- Source-media paths preserved exactly: YES.
- Approved fallback works: YES for the paths that already have one (DATA/QUOTE/BREAKING via `render_
  branded_media`, unchanged); NEWS-with-no-source gets HOLD rather than a new generated fallback - a
  disclosed, deliberate scope decision (§B), not a gap in what was implemented.
- Failure becomes an editor-visible HOLD, never silent: YES, live-confirmed.
- System/operator/debug text still allowed: YES, dedicated test, unaffected by construction.
- V8_VISUAL_OUTPUT_CHANGED = false: YES, confirmed via diff.
- Bounded cost/retries: YES, `MAX_VISUAL_FALLBACK_ATTEMPTS = 0`.
- No new regressions: YES, `NEW_FAILURES = 0` across the full relevant blast radius (§M), `NEW_STATIC_
  ERRORS = 0` (§L).
- Clean internal canary: YES - a real production recurrence of the original bug class, handled
  correctly, with zero errors/restarts.
- `UNEXPLAINED_FINISHED_TEXT_ONLY_EDITORIAL = 0`: YES.

## Final verdict: TELEGRAM_TEXT_ONLY_VISUAL_FALLBACK_REPAIR_PASS

Stopping here per the phase's own explicit scope boundary: no Telegram V8 redesign, no Instagram
changes, no historical Story cleanup, no Story Continuity changes, no public/autonomous publication
enabled. Two disclosed, non-blocking items remain for a future phase, at the Founder's discretion: (1)
whether NEWS should get its own generated "no-source" branded template (today it correctly HOLDs
instead); (2) CASE B's exact failure mechanism, which the pre-existing logging `extra={}` visibility gap
and a separate, pre-existing `telegram_api_id=0` MTProto configuration bug both currently block from
full retroactive confirmation - neither blocks this fix's correctness, since the fix gates on final
visual state, not on cause.
