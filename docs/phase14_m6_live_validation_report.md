# Phase 14 — M6 Live Validation Report

## Status: BLOCKED — no Telegram send occurred; two operational issues disclosed below

Executed `docs/phase14_m6_live_validation_plan.md` §1 (Stage A + Stage B) and the dry-run render
step. **Stopped before any live send**, for two reasons, both disclosed in full: (1) an
operational mistake in this session's own tooling caused Stage B to run twice, and (2) the
originally-flagged blocker — no `editorial_chat_id` was provided or configured — remains
unresolved. Per the explicit "if any unexpected behavior occurs: STOP immediately" instruction,
this is reported now rather than pushed through.

## Event ID and precondition (Stage A — zero AI cost, as planned)

- `event_id`: `03c98f8b-4c1f-4ced-9a00-9134fbd606cd`
- `NewsSource`: `5a0d95b0-680b-4810-8b87-fc19300960a8` (`phase14-m6-live-validation-<uuid>`)
- `NEWS_ANALYSIS` task: `c2b8afc0-8ffe-4e59-af64-64bd8e617ec4` — directly constructed
  `COMPLETED`, score `85`, zero AI cost, exactly per the Plan's own Stage A design. Confirmed
  untouched (still exactly 1 `NEWS_ANALYSIS` task for this event) after the incident below.

## Incident: Stage B executed twice for the same event_id

**What happened**: the validation script's own `print(notification.rendered_html)` line raised
`UnicodeEncodeError` — this Windows terminal's console encoding (`cp1251`) cannot display the
Cyrillic content the real model generated (this repository's own configured `default_content_
language` is Russian) or the card's own newspaper emoji. This crash happened **after** the real
`CONTENT_GENERATION` run and the dry-run render had already both completed successfully — it was
a display-only failure, not a failure of any validated code path. The shell command used to run
the script had a `(python ...) || (py ...)` fallback pattern (used throughout this session to
handle two possible local Python launchers) — because the first invocation exited non-zero (the
print crash), the fallback triggered a **second, full re-run of the same script**, including its
own real, billed `CONTENT_GENERATION` call, before I recognized the pattern.

**This is a mistake in my own tooling for this one step, not a defect in the Phase 14 code being
validated.**

**Exact, verified damage** (confirmed by direct query, not assumed):

| | |
|---|---|
| `CONTENT_GENERATION` tasks created for this event | **2** (both `COMPLETED`) |
| `ContentDraft` rows created | **2** (one per task, `1:1`, no other duplication) |
| `NEWS_ANALYSIS` task for this event | Still exactly **1**, untouched |
| Other events/tasks touched | **0** — confirmed scoped to this one `event_id` only |
| Telegram messages sent | **0** — `content_generation_dry_run` remained `True` throughout; both runs' own `NotificationOutcome.sent` was `False`, verified before the print crash in each case |

**Root cause of why a second `CONTENT_GENERATION` task was even accepted**: this is a live,
concrete demonstration of an already-disclosed, known limitation — `workflow_service.create_
task()`'s own `_find_active_task()` guard only checks `CREATED`/`RUNNING` siblings, not
`COMPLETED` ones (documented in `docs/phase14_autonomous_newsroom_implementation_plan.md` §3's
own "what this does NOT protect against" section, and in the M0–M5 implementation report's
"known limitations"). By the time the second, accidental run started, the first `CONTENT_
GENERATION` task had already reached `COMPLETED`, so `create_task()` did not block it. This is
not a new bug — it is the first time this specific, previously-only-theoretical gap was actually
exercised, by accident, live.

**Both resulting `ContentDraft` rows are real, valid, non-corrupted output** — neither is
garbage or a partial/failed result; the duplication is purely redundant, not incorrect.

## Real `CONTENT_GENERATION` chain — validated successfully (both times)

| | Run 1 | Run 2 |
|---|---|---|
| `CONTENT_GENERATION` task id | `551d486b-758c-4b42-b55c-1f95432e0712` | `c6afe356-b6d2-4e6f-8415-a78ea0d9f78f` |
| `ContentDraft` id | `049327ed-0a86-4995-9425-d68bb463adc3` | `6f27eef3-8c3a-41ab-af21-a5200fc98abc` |
| Workflow status | `COMPLETED` | `COMPLETED` |
| `title`/`body`/`hashtags` | Present, real, Russian-language, sensible for the synthetic RAG-benchmark event | Present, real, same shape |

**Provider call count**: 4 real calls per run (`research`, `intelligence`, `copywriting`,
`quality` — each `SUCCESS` on its own first attempt, no retries observed) — **8 total**, not the
planned 4, entirely attributable to the accidental duplicate run above.

This is itself the first real, live proof in this project that the `CONTENT_GENERATION` chain
completes successfully end-to-end against a real provider — a genuine, useful result, independent
of the duplication mistake.

## Dry-run payload — rendered successfully (content confirmed, console display failed)

Both runs' `send_editorial_card(..., dry_run=True)` calls completed correctly: `NotificationOutcome.
sent == False` (confirmed, printed successfully before the subsequent crash), `chat_id == None`
(confirmed — `settings.editorial_chat_id` is still unset). The rendered HTML payload itself was
generated correctly but could not be displayed in this Windows terminal due to the Cyrillic/emoji
encoding issue above — this is a local console limitation, not a defect in `render_editorial_
card()` or `send_editorial_card()`.

## Why this stops here — two separate, still-open blockers

1. **`editorial_chat_id` was never provided or configured** — the original blocker from the
   authorization request itself. No numeric chat ID was included in the authorization message,
   and `settings.editorial_chat_id` remains `None`, confirmed. Per the Plan's own §3/§6 and this
   task's own additional checks ("print and verify the resolved `editorial_chat_id` recipient,"
   "require explicit confirmation that the recipient is the intended private editorial chat"),
   there is nothing to print, verify, or confirm — inventing a value is not an option.
2. **Two `ContentDraft` rows now exist for the same event, not one** — before any live send can
   proceed, a human decision is needed on which (if either) should actually be sent, and whether
   the duplicate `CONTENT_GENERATION` task/`ContentDraft` pair should be preserved (as real,
   accidental-but-valid evidence) or cleaned up. This was not anticipated by the original Plan
   (which assumed exactly one Stage B execution) and is not this document's own call to make
   unilaterally.

## What was NOT done

- No Telegram message was sent — confirmed via `NotificationOutcome.sent == False` in both runs,
  and via `settings.content_generation_dry_run` never having been changed from its real,
  unmodified `True` default.
- No `.env` file was changed.
- No other `EditorialTask`/`NewsEvent`/`NewsSource` outside this one controlled `event_id` was
  touched.
- No channel destination was used or configured anywhere.
- No approval flow, no additional messages, no autopublishing — unchanged from the M0–M5
  implementation report's own confirmation.
- Nothing was committed.

## Recommended next step (not executed — awaiting human decision)

1. Provide the real, verified `editorial_chat_id` for the intended private editorial chat.
2. Decide: send using `ContentDraft` `049327ed-0a86-4995-9425-d68bb463adc3` (Run 1) — the other
   (`6f27eef3-8c3a-41ab-af21-a5200fc98abc`, Run 2) would then remain as disclosed, accidental-but-
   valid evidence, not deleted — or specify a different preference.
3. Once both are confirmed, the remaining steps of `docs/phase14_m6_live_validation_plan.md` (§3
   recipient verification, §4 the one temporary `dry_run` override, the single live send, §8
   post-send verification) can proceed exactly as originally planned, using the existing
   `ContentDraft` rather than running Stage B a third time.

---

PHASE 14 M6 LIVE VALIDATION BLOCKED
