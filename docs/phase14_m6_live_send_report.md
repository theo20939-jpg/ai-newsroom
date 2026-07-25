# Phase 14 — M6 Live Send Report

## Status: SUCCESS — exactly one message sent

## Pre-send verification

- `ContentDraft` used: **existing, not regenerated** — `049327ed-0a86-4995-9425-d68bb463adc3`
  (the primary draft from Run 1 of the earlier M6 generation attempt, `docs/phase14_m6_live_
  validation_report.md`). No new generation was run; no new `ContentDraft` row was created.
- Recipient re-verified immediately before sending via a fresh, read-only `bot.get_chat(5507703201)`
  call (not merely trusted from the earlier discovery snapshot): `chat.id == 5507703201`,
  `chat.type == "private"` — both confirmed matching before the send proceeded.

## The send

- **`ContentDraft` id used**: `049327ed-0a86-4995-9425-d68bb463adc3`
- **Telegram `message_id`**: `11`
- **Timestamp**: `2026-07-23 17:52:30+00:00`
- **`NotificationOutcome`**: `sent=True`, `chat_id=5507703201`, `rendered_html` populated (the
  exact same rendering path already proven in the earlier dry-run inspection — not regenerated,
  same draft, same event, same card construction)

## How `dry_run` was switched, and reverted

`content_generation_dry_run`/`editorial_chat_id` were overridden **in-process only**, inside the
one-off validation script, for the duration of the single `send_editorial_card(..., dry_run=False)`
call, then reverted in a `finally` block before the script exited. Re-verified from an entirely
**separate, fresh process** immediately after: `content_generation_dry_run == True`,
`editorial_chat_id == None` — confirming the override never persisted anywhere and had zero
effect on any other process. `.env` was checked directly and confirmed to contain no
`EDITORIAL_CHAT_ID`/`CONTENT_GENERATION_DRY_RUN` entries, before and after.

## Post-send verification

- `CONTENT_GENERATION` tasks for this event: **2** — unchanged from before the send (the two
  from the earlier accidental double-run; this send created zero new tasks).
- `ContentDraft` rows for this event: **2** — unchanged from before the send (zero new drafts
  created by this step).
- No background worker was started (`docker ps` shows only `postgres`/`redis`, unchanged
  throughout).
- No other `EditorialTask`/`NewsEvent`/`NewsSource` was touched — this entire procedure operated
  on exactly the one pre-identified `draft_id`/`event_id`/`chat_id`, with no eligibility query, no
  worker loop, no batch of any kind.

## Confirmations (explicitly required)

- **One message only**: exactly one `bot.send_message()` call was made, captured directly via a
  temporary, instance-local wrapper around this one `Bot` object's own method (no production code
  was modified to obtain this) — `message_id=11` is the only Telegram message this procedure
  produced.
- **No channel publishing**: the target was `chat_id=5507703201`, `chat.type=private` — verified
  immediately before sending, not a channel, not a group.
- **No approval workflow**: no buttons, no approve/reject step, no `InlineKeyboard` anywhere in
  this procedure — the message was sent directly once recipient verification passed.
- **No additional tasks created**: confirmed by the post-send count check above — `CONTENT_
  GENERATION` task count and `ContentDraft` count for this event are identical before and after
  this send.

## Final state

- `content_generation_dry_run`: `True` (unchanged, real default, confirmed from a fresh process)
- `editorial_chat_id`: `None` (unchanged, real default, confirmed from a fresh process)
- `.env`: untouched
- No commit was made; repository file state unchanged from before this validation.

---

PHASE 14 M6 LIVE SEND COMPLETE
