# Phase 18 M8 — Telegram Editorial Preview: Implementation Report

Status: complete (engineering). **No live Telegram send was made or attempted.**
`meme_telegram_preview_mode` defaults to `"off"`; its `Literal` type does not contain a `"live"`
value — same structural guarantee M5 established for image generation. The new
`bot/handlers/meme_preview.py` router is registered in the bot's root router (inert — nothing in
production code sends a `"memeprev:"` message yet).

## 1. What was built

| File | Purpose |
|---|---|
| `schemas/meme_preview.py` | `MemePreviewCard` — transport-neutral view model |
| `bot/keyboards/meme_preview.py` | callback_data codec + `build_meme_preview_keyboard()`/`build_decided_keyboard()` |
| `bot/meme_preview_formatting.py` | `render_meme_preview_caption()` — pure, no aiogram/Bot type |
| `services/meme_preview_summary.py` | `build_safety_summary()`/`build_quality_summary()` from M3/M7's own results |
| `services/meme_preview_notifier.py` | `send_meme_preview()` — dry-run-first send, mirrors `telegram_notifier.py` exactly |
| `services/meme_candidate_service.py` | `get_by_id()`, `record_editor_decision()` added |
| `bot/handlers/meme_preview.py` | callback router — approve/reject persist a decision; regenerate/fallback are acknowledged, not yet orchestrated (§6) |
| `bot/handlers/__init__.py` | new router registered (inert) |
| `core/config.py` | `meme_telegram_preview_mode: Literal["off", "dry_run"] = "off"` |
| `tests/test_phase18_m8_meme_telegram_preview.py` | 25 tests |

## 2. What's in the preview (brief's own checklist)

- **Meme image** — `MemePreviewCard.image_storage_key` (a reference; `send_meme_preview()` reads
  bytes fresh from `ImageStorage` only at send time, never earlier).
- **Brief tie to the source news** — title, category, and (as an inline URL button, never a raw
  link pasted into the caption body — mirrors `bot/keyboards/image_preview.py`'s own "Open
  source" button convention) the article URL.
- **Safety/quality summary** — one short line each, built by `build_safety_summary()`/
  `build_quality_summary()` from M3's `MemeSafetyOriginalityGateResult` and M7's
  `MemeQualityAssessment` — never the full raw assessment JSON dumped into a Telegram message.
- **Optional reason/explanation for the editor** — `MemeCopy.editor_explanation`, rendered when
  present, omitted entirely when not (tested: `test_render_caption_omits_explanation_block_when_
  absent`).

## 3. Editor actions

Six buttons: **Approve**, **Reject**, **🔄 Concept**, **🔄 Image**, **🔄 Text**, **📰 Fallback to
normal news** — every one of the brief's own listed actions, plus a persistent "Open source" link
when a URL is available. Approve/Reject call `MemeCandidateService.record_editor_decision()`,
which sets `editor_decision`/`editor_decision_at`/`status` on the `MemeCandidate` row (columns
reserved since M2's migration) and is idempotent (a double-tap just refreshes the timestamp, never
a duplicate row or an error). The three regenerate actions and the fallback action are recognized
and acknowledged via `callback.answer(...)` but do not yet re-run any generation step — see §6.

## 4. Why `send_meme_preview()` is safe by construction, not just by convention

Mirrors `services/telegram_notifier.py::send_editorial_card()`'s exact contract: `dry_run=True`
renders the full caption, resolves whether a photo is available, and returns — `bot.send_photo()`/
`bot.send_message()` is never called. This was proven with the strongest test double available: a
`_NeverCalledBot` whose `__getattr__` raises `AssertionError` on *any* attribute access, not just
the expected send methods — if `send_meme_preview()`'s dry-run path called literally anything on
the bot object, the test would fail immediately, not merely "happen to not call the one method the
test checked." `meme_telegram_preview_mode`'s `Literal["off", "dry_run"]` type has no `"live"`
member — a future authorized milestone must add that value in code before any live-sending
behavior could even be *selected*, the same structural guarantee M5 established for image
generation.

## 5. Testing

25/25 tests pass: callback_data encode/parse round-trips for every one of the six documented
actions; malformed/wrong-prefix/unknown-action/non-UUID callback data all correctly return `None`
(never raise); the keyboard includes every action's callback data and the source-URL button when
present, and correctly omits the URL button when absent; the terminal "decided" keyboard is
`None` without a URL and contains exactly one button with it; caption rendering includes the
on-image text and both summary lines, omits the explanation block when absent, and raises
`MemePreviewCaptionTooLongError` (never silently truncates) when over Telegram's caption limit;
the safety/quality summary builders correctly surface sensitivity flags and failed-check lists;
and `send_meme_preview()`'s dry-run contract is proven four ways (never touches the bot at all;
correctly reports `has_image=False` with no storage key; tolerates `chat_id=None` without
asserting or crashing; and a render failure still returns a clean, unsent outcome).

Regression: full Phase 18 suite — **138/138 pass** across all eight milestones together.
`tests/test_bot_router_registration.py` (3/3) confirms the existing root-router/dispatcher
registration tests are unaffected by adding the new (inert) router. `python -m pytest
--collect-only -q` — **2281 tests collected** (2256 + 25 new), 0 collection errors.

Not run this session (disclosed, unchanged constraint): `bot/handlers/meme_preview.py` itself
against a live Telegram Bot or database — both require infrastructure unavailable in this
session. It was written to mirror `bot/handlers/image_preview.py`'s already-proven shape as
closely as possible (fresh re-query per callback, terminal-state message editing, the same
alert-vs-message-edit split) specifically to minimize the risk of a structural mistake even
without a live run.

## 6. What is explicitly NOT done in M8 (disclosed, not oversights)

- **Regenerate/fallback actions do not regenerate anything yet.** No live orchestrator exists
  that can re-run `meme_concept`/`meme_image`/`meme_copywriting` for an already-created
  `MemeCandidate` row (M2–M7 built the individual pipeline pieces; wiring them into a callable,
  re-triggerable unit was never in any single milestone's scope, including this one — the brief's
  own M8 section lists these as preview *actions* to have, not as a requirement to fully implement
  live regeneration inside M8). The buttons exist, are pressable, and are acknowledged
  (`meme_preview_action_acknowledged_not_orchestrated` log event) — building the actual
  regeneration trigger is future work, clearly logged as such rather than silently faked.
- **No `telegram_file_id` caching** (§ module docstring of `services/meme_preview_notifier.py`) —
  `MemeCandidate` has no such column; every send reads bytes fresh. A reasonable, contained future
  optimization, not attempted here.
- **No live send, no live Telegram Bot instantiation, no `.env` change.**

## 7. Next milestone

M9 (Human Feedback & Decision Logging) — extends `record_editor_decision()`'s Approve/Reject with
the full reason taxonomy (not-funny/unclear/factual-risk/bad-image/off-brand/too-toxic/stale/
duplicate-idea) for rejections, plus regeneration-count and cumulative-cost reporting (columns
already reserved since M2).
