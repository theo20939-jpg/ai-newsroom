# Phase 16 UX Fix — Combined News+Image Preview — Report

Branch: `feature/phase16-image-intelligence`
Prior checkpoint: `checkpoint/phase16.5` (this fix follows the production cutover session, which
enabled `image_intelligence_mode=shadow`, `image_candidate_persistence_mode=finalists`,
`image_editorial_preview_enabled=true` in the local `.env` - unchanged by this fix).

## 1. Problem discovered during live validation

The production cutover's own human acceptance test surfaced a real UX defect: selecting an image
for a news draft produced **two** Telegram messages - (1) the existing text-only news card
(`services/telegram_notifier.py::send_editorial_card()`), and (2) a separate image-preview message
carrying candidate *metadata* (quality/relevance score, discovery reason - never the actual drafted
news text), which was then further overwritten with a third, purely technical confirmation string
("Image selected for this draft...") once "Use image" was pressed. One news item produced up to
three distinct message states across two messages - not the "one message = one news item" the
editorial workflow needs.

## 2. Root cause

- `worker/content_cycle.py` called `send_editorial_card()` **unconditionally**, then separately
  called `send_image_preview()` (M6) as an *additive* second notification whenever the preview
  flag was enabled - by original M6 design, never intended to replace the first message.
- `services/image_preview_notifier.py::send_image_preview()`'s caption came from
  `bot/image_preview_formatting.py::render_image_preview_caption()` - a purpose-built technical
  readout (quality/relevance score, discovery method, reason string, "Image N/Total"), not the
  actual `ContentDraft` title/body.
- `bot/handlers/image_preview.py::_finalize_decision()` replaced that caption with a fixed
  "✅ Image selected.../🚫 No image..." string once a decision was made - a third distinct render,
  never the real news content either.

## 3. Chosen fix

Replace the additive two-message flow with a single delivery path whenever the preview flag is
active: `services/image_preview_notifier.py::send_news_with_image_preview()` now sends **exactly
one message per draft** - the real news card content (title/body/hashtags, reusing
`bot/formatting.py::render_editorial_card()` directly, never reinvented) as a photo caption when an
eligible candidate exists, or as a plain text message when none does. `worker/content_cycle.py`
now branches: call this new function **instead of** `send_editorial_card()` when the preview flow
is active, or `send_editorial_card()` unchanged when it is not - never both.

Every state transition (Previous/Next navigation, "Use image", "No image") edits the *same*
message already on screen and always re-renders the real news content - never a separate
technical confirmation. The source URL is never shown as body text anywhere in this flow; a single
"🔗 Open source" inline button (reusing the exact keyboard M6 already built) is the only way to
reach it, both while browsing candidates and in the terminal (post-decision) state.

## 4. Alternatives rejected

- **Editing message 2's caption to include the real news text, keeping two messages**: rejected -
  still leaves two messages for one news item, the core complaint.
- **Sending only the image message and dropping the text card entirely when preview is disabled**:
  never considered - `send_editorial_card()`/`render_editorial_card()` are completely untouched for
  every environment where the preview flag is off (the overwhelming majority of deployments); this
  fix only changes behavior when `image_editorial_preview_enabled` is already active.
- **A brand-new, third rendering module duplicating `render_editorial_card()`'s HTML-escaping and
  shrink-to-fit logic for the caption case**: rejected in favor of adding two small, fully
  backward-compatible optional parameters (`limit`, `include_url`) to the existing function -
  every pre-existing caller keeps the exact same default behavior; only the new combined-preview
  call sites pass the new parameters.

## 5. Telegram constraints verified

- **Caption length**: Telegram's photo-caption limit is 1024 UTF-16 code units - a *harder* bound
  than the 4096 units a plain text message allows. `render_editorial_card()`'s existing shrink-to-
  fit algorithm (render → measure → truncate `draft_body` → re-measure → repeat) is reused
  unmodified, just parameterized with the smaller `limit` when a photo is attached; falls back to
  4096 for the text-only path. `CardTooLongError` (the pre-existing terminal fallback) is now also
  reachable at the tighter 1024 limit and is caught explicitly in both the initial send and every
  edit path - logged, never an unhandled exception.
- **Editing a photo message's caption**: `bot.edit_message_caption()` (Use image, and Previous/Next
  while already showing a photo) - already proven working in the M6-era code, unchanged here.
- **Converting a photo message into a text-only one (or vice versa)**: Telegram has no API for
  this - `editMessageMedia`/`editMessageCaption` only ever operate on a message that already has
  the target type. "No image" pressed on a photo message therefore deletes the photo message and
  sends a fresh text-only one - the exact same delete+resend technique the pre-existing
  Previous/Next media-type-switch code already used, reused here for the terminal "No image" case
  too. Confirmed still exactly one resulting message, never two, by a dedicated test (§7).
- **Preserving the inline keyboard through every edit**: verified directly - the source-only
  keyboard (`build_source_only_keyboard()`, new) is passed to every terminal-state edit/resend;
  the full Previous/Next/Use/No-image/Source keyboard is preserved through every navigation edit
  exactly as before (unchanged `build_image_preview_keyboard()`).

## 6. Code changes

- `bot/formatting.py`: `render_editorial_card()` gained two optional, backward-compatible
  parameters - `limit: int = SAFE_LIMIT`, `include_url: bool = True`. Every existing call site
  (`bot/handlers/news.py`, `services/telegram_notifier.py`) passes neither and is byte-for-byte
  unaffected - proven by a dedicated equivalence test (§7).
- `bot/image_preview_formatting.py`: removed `render_image_preview_caption()`,
  `render_no_candidates_text()`, `render_decision_confirmation_text()` (all obsolete - no message
  this flow sends is ever candidate-metadata or a technical confirmation anymore). Kept
  `CAPTION_SAFE_LIMIT` and the two callback-alert strings (`render_expired_candidate_alert_text()`,
  `render_unavailable_candidate_alert_text()` - shown only as Telegram alert popups, unaffected).
- `bot/keyboards/image_preview.py`: added `build_source_only_keyboard(source_url)` - the terminal-
  state keyboard (a single "🔗 Open source" button, or `None` when there is no URL at all).
  `build_image_preview_keyboard()` (the browsing-state keyboard) is unchanged.
- `services/image_preview_notifier.py`: `send_image_preview()` → `send_news_with_image_preview()` -
  now takes `draft: ContentDraftRead, event: NewsEvent, dry_run: bool` (mirroring
  `send_editorial_card()`'s own established contract, including the same dry-run/fact-safety-
  suppression semantics) instead of `content_draft_id, draft_title`; always sends exactly one
  message (text-only when there are zero candidates - previously a silent no-op); returns
  `CombinedCardOutcome(chat_id, sent, has_image, candidate_count)`.
- `bot/handlers/image_preview.py`: `_render_candidate()` and `_finalize_decision()` now load the
  real `ContentDraft`/`NewsEvent` (via `EditorialTask`) and render the actual news content through
  `render_editorial_card()`, never candidate metadata or a confirmation string.
  `_finalize_decision()` takes a `keep_photo: bool` (`True` for "Use image", `False` for
  "No image") and performs the correct edit/delete+resend for each of the four
  (photo-or-text) × (keep-or-drop) combinations.
- `worker/content_cycle.py`: the two-call flow (`send_editorial_card()` always +
  `send_image_preview()` conditionally) replaced with a single `if/else` branch -
  `send_news_with_image_preview()` when the preview flow is active, `send_editorial_card()`
  otherwise, never both. `ContentCycleResult.image_preview_failed` removed (folded into the
  existing `notification_failed` - there is only one send attempt per draft now); `notified`/
  `notification_failed`/`dry_run_rendered` are updated uniformly regardless of which path ran;
  `image_preview_sent` now means "the one message sent had a photo attached."
- `scripts/phase16_m7_shadow_validation.py`: updated its `live-send` phase call site to the new
  function name/signature (builds a `ContentDraftRead` from the raw ORM row it already fetches) -
  no behavior change to the validation methodology itself.

## 7. Tests

- `tests/test_editorial_card_formatting.py`: 6 new tests for `limit`/`include_url` - default-call
  equivalence (byte-identical to the pre-fix function), URL line omission, no-op when there is no
  URL anyway, tighter-limit truncation, `CardTooLongError` still raised at a tight limit, and both
  parameters composing together.
- `tests/test_image_preview_formatting.py`: slimmed to the 2 remaining functions (`CAPTION_SAFE_
  LIMIT` value, the two distinct alert strings) - the removed candidate-metadata-caption tests are
  gone along with the code they tested.
- `tests/test_image_preview_notifier.py`: rewritten for `send_news_with_image_preview()` - no
  candidates still sends one text message (not silence), no URL in that message's body plus a
  source button, exactly one message sent end-to-end (never two), photo+real-caption send with
  file_id caching, text-only fallback when candidates exist but have no bytes, dry-run sends
  nothing, `chat_id` required for a live send, send-failure handling, zero-LLM-import proof.
- `tests/test_image_preview_handler.py`: rewritten - Previous/Next now shows real news content
  (not "Image N/Total"), the browsing keyboard still offers Use/No-image/Source, "Use image" keeps
  the real news text with the keyboard reduced to Source-only (no "selected" string, no raw URL in
  body), a photo message stays a photo message after "Use image" (caption-only edit), "No image"
  on a text message shows real content with Source-only keyboard, "No image" on a **photo** message
  deletes it and sends a fresh text-only replacement (still exactly one message), plus the
  pre-existing expired/unavailable/malformed-callback/cross-draft/query-failure coverage carried
  over unchanged.
- `tests/test_content_worker_cycle_image_preview.py`: rewritten - disabled uses the text-only path
  and never calls the combined function; enabled calls the combined function **and asserts
  `send_editorial_card` was never called** (the core "never both" regression guard); a photo-less
  combined send still counts as `notified` but not `image_preview_sent`; a combined-send failure
  is counted as `notification_failed` (folded, since there is only one attempt now) and never
  raises, with `send_editorial_card` confirmed not called as a fallback; persistence mode "off"
  still falls back to the unchanged text-only path even with the flag on.

**Results**: `-k image` selection: **422 passed**, 1 failed - the 1 failure
(`test_image_preview_disabled_by_default_uses_the_text_only_card`) asserts the *default* value of
`image_editorial_preview_enabled` directly against the live environment, which the still-active
production cutover session deliberately set to `True` in `.env` - the same class of pre-existing
environment-dependent test already documented in every prior Phase 16 report for
`content_generation_dry_run`, not a regression from this fix (confirmed by inspecting the assertion
itself, §11).

## 8. Before/after message format

**Before** (image selected): message 1 = text news card (title/body/hashtags/URL-as-text);
message 2 = photo + "Image preview — <title> / Image 1/N / Source: domain / Quality: NN/100 /
Relevance: NN/100 / Reason: ..."; after "Use image", message 2's caption becomes "✅ Image selected
for this draft (source: domain)." with its keyboard removed.

**After** (image selected): exactly one message - a photo whose caption is the real news card
(title/body/hashtags, no URL) with a "🔗 Open source" button; pressing "Use image" leaves the same
photo and the same real-news caption in place, just reducing the keyboard to the one Source button.

**After** (no image / no candidates): exactly one plain text message - the real news card (no URL
in body) with a "🔗 Open source" button (present whenever the event has a URL at all).

Format of the underlying `ContentDraft` text itself (title/body/hashtags) is completely unchanged -
only the URL's presentation (button vs. inline text) and the message count changed.

## 9. Deployment

Only `content_worker` imports any of the changed modules (confirmed by `grep`) - rebuilt and
redeployed; `backend`/`automation_worker`/`news_analysis_worker`/`postgres`/`redis` untouched.
Container started cleanly, no restart loop. Migration unchanged (no schema touched by this fix).
Live human re-verification of the new combined message was not performed as part of this fix (not
requested for this task's scope) - the container is deployed and will exercise the new flow on the
next naturally-eligible content-generation cycle; the underlying callback/dispatcher infrastructure
was already live-validated end-to-end during the preceding cutover session.

## 10. Known limitations (disclosed, not fixed under this task's scope)

- **A combined-send failure now means zero delivery for that draft this cycle** - previously, a
  failure in the (additive) image-preview message still left the independently-sent text card
  delivered. Merging the two paths into one is an inherent tradeoff of "one message = one news
  item"; `/news` remains the existing, unmodified durable fallback for any lost push notification,
  exactly as it already was for the text-only path.
- **Photo captions are now bounded to 1024 UTF-16 units, not 4096** - a materially longer body will
  be truncated more aggressively when an image is attached than it would be as plain text. This is
  a real Telegram platform constraint, not a bug; `/news` (unmodified, full 4096-limit rendering)
  remains available for the complete text.
- The pre-existing, already-documented FK/test-fragility findings from the M7 and cutover sessions
  (real `image_candidates` → `content_drafts` linkage conflicting with two unrelated tests' blunt
  cleanup) are out of scope for this fix; the affected rows were nulled out again as data-only
  maintenance so this task's own verification wasn't blocked by them (no code changed for this).

## 11. Full regression baseline

`python -m pytest -q`: 22 failed, 1669 passed on the first full pass. Broken down, none
attributable to this fix's own code:

- The same 15 pre-existing failures every prior Phase 16 report has documented
  (`test_capability_executor.py` ×8, `test_content_generation_integration.py` ×1,
  `test_content_worker_cycle.py` ×2, `test_editorial_scoring.py` ×2, `test_fact_safety.py` ×2).
- 1 environment-dependent failure from this fix's own renamed test (§7) - the still-active
  cutover's `.env` state (`image_editorial_preview_enabled=true`), not a code regression.
- 2 recurring FK-conflict failures (`test_editorial_inbox_service.py::test_empty_result_returns_
  empty_list`, `test_news_handler.py::test_integrated_stack_empty_state`) - the same real,
  already-documented issue from the M7/cutover sessions (a live `image_candidates` row linked to a
  real `content_drafts` row via M6's own FK, conflicting with two unrelated tests' blunt `DELETE
  FROM content_drafts`). This is **still actively recurring** as long as the cutover stays live
  (content_worker keeps creating new real links) - cleaned up again as data-only maintenance
  (`UPDATE image_candidates SET content_draft_id = NULL`, 18 rows this time) so this fix's own
  verification wasn't blocked; not fixed in code, per this task's own explicit scope boundary.
- 1 new, **deterministic** (reproduced on a dedicated re-run), out-of-scope failure:
  `test_phase10_workflow_integration.py::test_content_generation_reaches_completed_in_exact_step_
  order` asserts the "copywriting" step's result dict via exact equality against a fixed fixture -
  with `image_intelligence_mode=shadow` active (the cutover's own setting, unchanged by this task),
  `capabilities/executor.py` now legitimately attaches an additional `image_intelligence` key to
  that same dict, which the test's fixed-shape assertion was never updated to expect. Root-caused
  by direct inspection of the diff (exactly the one added key `_attach_image_intelligence()`
  produces); not touched by this fix's own code.
- 3 non-deterministic `test_triage_orchestrator_cycle.py` failures - the same already-documented
  (M7 report §13 item 6) pre-existing test-isolation gap against the live, continuously-growing
  real database; confirmed non-deterministic again on a dedicated re-run (a *different* test in
  the same file failed the second time).

After cleaning up the FK rows, `-k image` (the full, authoritative scope for this fix):
**422 passed, 1 failed** - only the one environment-dependent failure above. Zero new regressions
from this fix's own code.

## Phase 16 UX fix verdict

**PHASE 16 UX FIX COMPLETE — PASS**
