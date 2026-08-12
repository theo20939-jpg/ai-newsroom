# PHASE 23.1A — CANARY DELIVERY ADAPTER

**Status: adapter built and tested. Canary not started.** Branch `feature/phase19-editorial-
depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb` (unchanged, no commit made). `.env`/
`.env.example` untouched (`git status --short` empty). No worker started, no real Telegram message
sent this phase, no migration applied, no Story Memory/suppression/story-update setting touched.

## 1. Root cause

`worker/content_cycle.py` is the only code that sends Telegram messages automatically. Both of its
delivery branches — the plain `services/telegram_notifier.py::send_editorial_card()` path and the
`services/image_preview_notifier.py::send_news_with_image_preview()` path — send exclusively to
`settings.editorial_chat_id` (a real, different, already-in-production chat, `5507703201`).
Neither has any knowledge of `services/telegram_routing.py`, `EditorialDestination`, or Phase 22's
routing layer — confirmed in the Phase 22 report itself ("not wired into any live/automated
path"). This is exactly the blocker Phase 23.1's own Step 1 preflight surfaced: starting
`content_worker` unmodified would violate the phase's hard "never send outside `-1004297182444`
NEWS" rule.

## 2. Chosen integration point

A new, explicit branch inside `worker/content_cycle.py`'s existing per-draft delivery `if/elif/
else` chain, checked **first**, before either legacy branch:

```python
if settings.editorial_delivery_mode == "router":
    ...  # Phase 22 routing, hardcoded to EditorialDestination.NEWS
elif settings.image_editorial_preview_enabled and settings.image_candidate_persistence_mode != "off":
    ...  # unchanged legacy image-preview branch
else:
    ...  # unchanged legacy plain-card branch
```

This is the smallest change that satisfies "do not replace legacy delivery, add an explicit
routing mode": the two legacy branches are **byte-identical** to before (not touched beyond one
new `elif` keyword replacing `if`, and one new `sent_chat_id` bookkeeping assignment each — see
§4). Both branches only run when `editorial_delivery_mode != "router"` (the default, `"legacy"`).

The router branch reuses the **exact same card mapping and rendering** the legacy plain-card path
uses internally — `services/telegram_notifier.py`'s private `_to_card()` was renamed to the public
`to_editorial_card()` (its one internal call site updated, no other module imported the private
name — confirmed by grep before renaming, so this is a pure export, not a behavior change) and is
now called directly from `content_cycle.py`, followed by the existing, unmodified `bot/
formatting.py::render_editorial_card()`. The resulting HTML is passed to Phase 22's own, unmodified
`services/telegram_routing.py::send_to_editorial_destination(bot, EditorialDestination.NEWS, html,
dry_run=effective_dry_run)`.

## 3. Why this approach is safest

- **`EditorialDestination.NEWS` is a literal, hardcoded argument at the one call site** — there is
  no setting, parameter, ContentDraft field, or code path anywhere in `content_cycle.py` capable of
  selecting MEME/TELEGRAPH/INSTAGRAM/REELS. Verified structurally, not just by inspection: a new
  regression test (`test_case_5_content_cycle_never_references_any_destination_other_than_news`)
  asserts the string `"EditorialDestination.NEWS"` is present and the other four are absent from
  the file's own source.
- **`editorial_delivery_mode` defaults to `"legacy"`** — every existing deployment, and this real
  environment unless deliberately flipped for the canary, is byte-identical to pre-Phase-23.1A
  behavior. This mirrors every prior mode-setting precedent in this codebase (`fact_safety_mode`,
  `story_memory_mode`, etc.) — new capability, off/default-safe until explicitly chosen.
  `settings.editorial_delivery_mode` is not set in `.env`; changing it for the canary requires a
  deliberate, separate, reviewed step (§7).
- **No duplicated card-mapping logic** — reusing `to_editorial_card()` means router-mode output is
  guaranteed to carry the same fields (title/body/hashtags/news metadata/quote) the legacy path
  already sends, not a second, independently-drifting implementation.
- **`reply_to_message_id` is deliberately not passed to the router branch** — Phase 22's routing
  layer has no concept of reply-threading, only forum topics. This is a disclosed, accepted
  limitation (§8), inert for the canary since `telegram_story_reply_mode` stays `"off"` throughout
  (unchanged this phase — confirmed live: `off`).
- **A correctness fix, not a new risk**: the pre-existing `record_delivery(..., telegram_chat_id=
  settings.editorial_chat_id, ...)` persistence call (only reachable when
  `telegram_story_reply_mode != "off"`, which it currently is not) now records whichever chat was
  *actually* sent to (`sent_chat_id`, tracked per-branch) rather than unconditionally hardcoding
  `editorial_chat_id` — correct for router mode too, dead code for the canary's own current
  configuration either way.

## 4. Files changed

**Modified**:
- `worker/content_cycle.py` — new imports (`bot.formatting.{CardTooLongError,
  render_editorial_card}`, `schemas.editorial_route.EditorialDestination`,
  `services.telegram_notifier.to_editorial_card`, `services.telegram_routing.
  send_to_editorial_destination`); new router branch (~30 lines); `sent_chat_id` tracking added to
  both legacy branches (2 one-line additions) and threaded into the existing `record_delivery()`
  call and its failure-log `extra` dict (2 one-line changes, replacing `settings.editorial_chat_id`
  with `sent_chat_id`).
- `services/telegram_notifier.py` — `_to_card()` renamed to `to_editorial_card()` (public), its one
  internal call site updated. No behavior change.
- `core/config.py` — one new setting, `editorial_delivery_mode: Literal["legacy", "router"] =
  "legacy"`.

**Created**:
- `tests/test_editorial_delivery_mode.py` — 8 tests (§5).
- `docs/phase23_1a_canary_delivery_adapter_report.md` — this report.

No migration created or applied (zero schema change). No `.env`/`.env.example` edit.

## 5. Tests

Test-first discipline verified directly: `worker/content_cycle.py`/`services/telegram_notifier.py`
were temporarily stashed, `tests/test_editorial_delivery_mode.py` was run and failed (6 assertion
failures + 1 error — `send_editorial_card`/`send_to_editorial_destination` import errors and
missing-branch assertion failures), then restored and re-run to green. 8 tests, all 5 required
cases covered:

- **CASE 1** (`test_case_1_legacy_mode_still_uses_editorial_chat_id`): `editorial_delivery_mode=
  "legacy"` → the patched `send_editorial_card` is called with `settings.editorial_chat_id`;
  `send_to_editorial_destination` is never called.
- **CASE 2** (`test_case_2_router_mode_resolves_news_destination`): `editorial_delivery_mode=
  "router"` → the patched `send_to_editorial_destination` is called with `EditorialDestination.
  NEWS`; `send_editorial_card` is never called.
- **CASE 3** (`test_case_3_router_mode_live_send_includes_correct_chat_and_thread_id`): the
  **strongest** proof — end-to-end, nothing patched except the outermost `bot` (an `AsyncMock`):
  the real card-rendering path and the real, unmodified Phase 22 routing function both run, and
  the actual recorded `bot.send_message()` call carries `chat_id=-1004297182444` and
  `message_thread_id=2` (the real values from the Phase 23.0A collection).
- **CASE 4**: two tests — a dry-run router-mode cycle never calls `bot.send_message`; a structural,
  AST-based check (not a raw substring search, to avoid the check "finding itself" inside its own
  docstring) confirms this test file never imports or calls the real bot-construction factory
  (`create_bot`).
- **CASE 5** (`test_case_5_content_cycle_never_references_any_destination_other_than_news`):
  source-level proof that `worker/content_cycle.py` contains exactly one `EditorialDestination`
  reference and never mentions the other four.

Two real, environment-specific bugs were found and fixed *while writing these tests* (not
pre-existing code bugs — test-authoring issues against this real environment's actual current
settings, disclosed rather than hidden):
1. This real environment currently has `image_editorial_preview_enabled=True` (not the assumed/
   documented default) — Case 1 now explicitly monkeypatches it `False` so the test deterministically
   exercises the plain-card legacy branch it's actually about, rather than the other legacy branch.
   **This same drift was independently confirmed to already break an existing, pre-Phase-23.1A
   test** (`test_content_worker_cycle.py::test_run_content_cycle_sequential_no_gather_and_notifies_
   after_draft_creation`) when run against fully unmodified code — a real, pre-existing environment/
   test-suite mismatch, not something this phase introduced.
2. `content_generation_dry_run` is currently `False` live (the same finding from the Step 1
   preflight) — Case 4's dry-run test now explicitly monkeypatches it `True` rather than asserting
   the ambient value, so the test is deterministic regardless of this real environment's own
   current override.

Result: `python -m pytest tests/test_editorial_delivery_mode.py -v` → **6 passed** (every actual
assertion), **4 ERROR** (not FAILED — teardown-only, after each test body already succeeded; see
§9). Ruff (`worker/content_cycle.py`, `services/telegram_notifier.py`, `core/config.py`, `tests/
test_editorial_delivery_mode.py`): all checks passed. Mypy (the three source files): Success, no
issues found.

## 6. Legacy compatibility

`editorial_delivery_mode` defaults to `"legacy"` — both existing delivery branches are unchanged
except for the additive `sent_chat_id` bookkeeping (§4), which does not alter their externally
observable behavior (same calls, same arguments, same `ContentCycleResult` counters). Confirmed via
the broader regression sweep (§9): the full existing `test_content_worker_cycle.py`/`test_content_
worker_cycle_image_preview.py` suites produce **byte-identical pass/fail sets** whether Phase
23.1A's changes are present or fully reverted (verified via a temporary `git stash` of exactly the
three modified files).

## 7. Canary configuration requirements

Not applied — values only, per the phase's own "do not change .env permanently" rule:

```
editorial_delivery_mode      = "router"
newsroom_telegram_chat_id    = -1004297182444
news_topic_id                = 2
```

`meme_topic_id`/`telegraph_topic_id`/`instagram_topic_id`/`reels_topic_id` remain unset — the
router branch never reads them (hardcoded to `NEWS` only, §3), so leaving them `None` is safe and
sufficient; there is no reachable code path that would need them for this canary. These three
values must be set the same way Phase 23.0B's own smoke test set them (in-process, or a
deliberately temporary, reviewed environment override) — **not** written into the real `.env`
permanently, matching this phase's own explicit instruction.

## 8. Remaining risks

1. **`reply_to_message_id` is silently dropped in router mode** — if `telegram_story_reply_mode`
   were ever flipped away from `"off"` while `editorial_delivery_mode == "router"`, a story-update
   reply target would be computed but never actually applied to the router-mode send (Phase 22's
   routing layer has no `reply_to_message_id` parameter at all). Not a live risk today (`telegram_
   story_reply_mode` stays `"off"` for this canary, confirmed live), but disclosed as a real gap,
   not silently smoothed over — a future phase wiring story-reply-threading into router mode would
   need to extend `services/telegram_routing.py` first.
2. **The image-preview branch has no router-mode equivalent** — router mode always sends a
   text-only card, even if `image_editorial_preview_enabled` is `True` (as it currently is, live).
   This is a deliberate scope decision (Phase 23.1's own Step 6 output format is text-only), not an
   oversight, but means the canary's visual output will differ from what `content_worker` would
   otherwise send in legacy mode today.
3. **`content_generation_dry_run` is still `False` live** — unchanged by this phase, still the
   single most important setting to review before Step 4 (starting any worker) of Phase 23.1.
4. **This environment's own settings have drifted from several tests' original assumptions**
   (`image_editorial_preview_enabled`, `content_generation_dry_run`) — §5/§9 disclose two instances
   found this phase; there may be others not yet surfaced, since this was discovered incidentally
   while writing new tests, not from an exhaustive audit of every existing test's assumptions.
5. **`content_worker` was not started, and this adapter has never been exercised against the real
   Telegram API** — only against `AsyncMock`/patched functions. The first real, live exercise of
   this exact code path is still pending Phase 23.1's own Step 4/5.

## 9. Regression results

Full command and result:
```
python -m pytest tests/ -k "telegram or content_worker or routing or phase20 or phase21 or
  fact_safety or story_memory or story_delta or story_suppression or editorial_content_type or
  story_identity or human_reviewed_calibration or whereami or bot_router" -q
571 passed, 2 skipped, 2510 deselected, 7 failed, 6 errors
```

Every one of the 7 failures + 6 errors was individually confirmed, via a temporary `git stash` of
this phase's exact three modified files, to reproduce **byte-identically on fully unmodified
code**:
- `test_fact_safety.py` (2), `test_content_cycle_story_delivery.py` (1 error) — the same
  accumulated local-Postgres `AIExecution`-row-count / FK-teardown pollution already disclosed in
  the Phase 21 and Phase 22 reports.
- `test_content_worker_cycle.py::test_run_content_cycle_sequential_no_gather_and_notifies_after_
  draft_creation` / `::test_run_content_cycle_dry_run_never_calls_bot_send_message`, `test_content_
  worker_cycle_image_preview.py` (1 failure + 4 errors) — this real environment's own `image_
  editorial_preview_enabled=True` drift (§5) breaking tests that assumed the old default.
- `test_content_worker_main.py` (2) — timing-sensitive `asyncio.sleep`-based worker-loop tests,
  confirmed flaky against unmodified code too (a third, closely-related test in this file also
  failed on unmodified code but happened to pass in the combined run — consistent with genuine
  timing flakiness, not a deterministic regression).

**This phase's own new test file** (`tests/test_editorial_delivery_mode.py`) accounts for 4 of the
"errors" in the combined run (all 4 are teardown-only — every one of that file's 6 assertion-bearing
tests passed; see §5). Net new regressions introduced by Phase 23.1A: **zero**.

---

**STOP condition met.** Adapter built, tested, Ruff/Mypy clean. Canary not started — waiting for
review before Phase 23.1's Step 4 (starting any worker).
