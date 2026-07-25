# Phase 14 — M6 Live Validation Authorization Check

Planning only. **No code was changed to produce this document. No Telegram API call was made. No
configuration was changed — `content_generation_dry_run` remains `True`, `editorial_chat_id`
remains unset, exactly as verified read-only immediately before writing this document (no
override present in `.env`, code defaults in effect).** M6 itself remains unauthorized until a
human explicitly approves proceeding past §6 of this document.

## 0. What M6 validates, and what it deliberately does not re-validate

Phase 13's own M7 already live-validated the real `NEWS_ANALYSIS` chain (`docs/phase13_m7_live_
validation_report.md` — `COMPLETED`, all 4 steps `SUCCESS`, real provider calls). This M6 exists
to validate the two things Phase 14 actually adds that have never been exercised against a real
provider or a real Telegram chat: (a) the real `CONTENT_GENERATION` chain
(`research→intelligence→copywriting→quality`) completing end-to-end via `scripts/run_content_
generation.py::run_content_generation_for_event()`, and (b) a real `Bot.send_message()` call via
`services/telegram_notifier.py::send_editorial_card()`. It deliberately does **not** re-exercise
`worker/content_cycle.py::_select_eligible_events()` — that eligibility/quality-check/duplicate-
prevention logic is pure SQL/Python, touches no AI provider and no Telegram API, and is already
proven correct by 14 dedicated offline tests (`tests/test_content_worker_cycle.py`, zero real
cost) — there is nothing new to prove live there, and exercising it live would only reintroduce
the exact real-backlog-selection risk Phase 13 M3's own incident already taught this project to
avoid (`docs/phase13_m3_analysis_cycle_report.md`).

## 1. Exact task creation path

Mirrors Phase 13 M7's own precedent exactly (`docs/phase13_m7_live_validation_plan.md` §5,
`docs/phase13_m7_authorization_check.md`): a fresh, synthetic, clearly-labeled `NewsSource` +
`NewsEvent`, created via the same real `workflow_service.create_task()` construction already used
throughout, then run through **exactly one** direct call — no selection query, no batch, no
worker loop.

**Two stages, deliberately different cost profiles:**

**Stage A — the `NEWS_ANALYSIS(COMPLETED)` precondition, zero AI cost.** Directly constructed via
the same technique already proven correct in `tests/test_content_worker_cycle.py::_make_
completed_news_analysis_task` — a real `EditorialTask(NEWS_ANALYSIS)` row, `status=COMPLETED`,
with a `step_results` entry for `"scoring"` carrying a genuine score above `content_generation_
min_score`. **This is not a live re-run of `NEWS_ANALYSIS`** — Phase 13 M7 already proved that
chain live, separately, and `CONTENT_GENERATION`'s own workflow (confirmed by direct re-read of
`scripts/run_content_generation.py` and `workflows/definitions/content_generation.py` this
session) does **not** consume the `NEWS_ANALYSIS` task's own `step_results` at all — it re-derives
`research`/`intelligence` fresh, from the `NewsEvent` directly, as its own independent 4-step
chain. Re-running `NEWS_ANALYSIS` live here would spend real tokens to prove something already
proven, for no new information — so it is not done. This is a deliberate, disclosed cost
optimization for M6, not a shortcut around what M6 actually needs to validate.

**Stage B — the real `CONTENT_GENERATION` chain, real AI cost (§5).** One direct call:

```python
outcome = await run_content_generation_for_event(
    event_id,  # the one synthetic event from Stage A - literal, recorded, not re-queried
    priority=TaskPriority.B,
    # capability_registry omitted -> the real assemble_ai_integration_layer() path, exactly as
    # production requires (scripts/run_content_generation.py's own documented default behavior)
)
```

`run_content_generation_for_event()` is called **exactly as-is**, unmodified, exactly as it
already is in `worker/content_cycle.py::run_content_cycle()` — this is not a new code path, it is
the same function, invoked once, directly, for one known `event_id`, instead of being reached via
`_select_eligible_events()`'s own batch selection.

## 2. How to guarantee only one ContentDraft is created and only one message is sent

**By construction, not by monitoring.** `run_content_generation_for_event()` itself creates
exactly one `CONTENT_GENERATION` `EditorialTask` (one `workflow_service.create_task()` call) and,
if it reaches `COMPLETED`, exactly one `ContentDraft` (`ContentDraftService.create_from_result()`,
one `session.add()` + one `commit()` — re-confirmed by direct re-read this session, no loop
anywhere in that function). Because M6 calls this function **once**, for **one** `event_id`, with
no eligibility query and no batch loop in between, there is no code path through which a second
`ContentDraft` could be created during this procedure. The notification step (§4) is likewise
called **once**, directly, for that one resulting draft — never through `run_content_cycle()`'s
own loop, which is never invoked at any point in this procedure.

## 3. How to verify `editorial_chat_id`

Read-only, before any live send:

1. The human operator states, explicitly, which real Telegram chat (a private chat with the bot,
   or a private group the operator controls) is the intended target, and states its numeric chat
   ID.
2. This chat ID is used **only** as a temporary, in-process override (§4) — never written to
   `.env` or any tracked file as part of this validation.
3. **Dry-run first, mandatory** (already the case today — `content_generation_dry_run=True` is
   the unmodified, current default, verified read-only immediately before writing this document):
   call `send_editorial_card(bot, <candidate_chat_id>, draft, event, dry_run=True)` and inspect
   the returned `NotificationOutcome.chat_id` (echoes back exactly what was passed — confirms no
   transcription error) and `NotificationOutcome.rendered_html` (confirms the message content
   itself is sensible) together with the logged `content_notification_dry_run` entry. The human
   operator visually confirms both the chat ID and the content before §6's authorization is
   requested.
4. Only after this explicit dry-run confirmation may §4's live switch ever be considered.

## 4. How to switch `dry_run` safely

**Not a persistent configuration change.** `core/config.py`'s `settings` object is a singleton
already constructed once, at process start, from defaults plus whatever `.env` provides. The
recommended, safe mechanism — mirroring exactly how every offline test in `tests/test_content_
worker_cycle.py`/`tests/test_content_generation_integration.py` already does this (e.g. `settings.
content_generation_dry_run = False` inside a `try`/`finally`) — is a **temporary, in-process
attribute override inside the one-off validation script itself**, never written to `.env`, never
committed, never touching `core/config.py`:

```python
original_dry_run = settings.content_generation_dry_run
original_chat_id = settings.editorial_chat_id
settings.content_generation_dry_run = False
settings.editorial_chat_id = <the human-confirmed chat ID from §3>
try:
    notification = await send_editorial_card(bot, settings.editorial_chat_id, draft, event, dry_run=False)
finally:
    settings.content_generation_dry_run = original_dry_run
    settings.editorial_chat_id = original_chat_id
```

This override exists only for the lifetime of the one-off validation process; once that process
exits, every other process (including a real `content_worker` container, should one ever be
started) continues to read the real, unmodified, `dry_run=True` default from `.env`/code. **Not
recommended, and explicitly out of scope for M6**: editing `.env` to set `CONTENT_GENERATION_DRY_
RUN=false`/`EDITORIAL_CHAT_ID=...` persistently — this would affect every future process
(including an eventual real `content_worker` container) and is a materially larger, unnecessary
change for a single validated send.

## 5. Maximum possible AI/API cost

**Zero additional cost for `NEWS_ANALYSIS`** — §1 Stage A is a direct DB construction, no
provider call.

**`CONTENT_GENERATION`, best case: 4 real calls** (`research`, `intelligence`, `copywriting`,
`quality` — one attempt each, all succeed). **Structural worst case: 12 calls** — re-derived
directly from `workflows/definitions/content_generation.py`'s own 4 `WorkflowStepDefinition`
entries this session (none overrides `max_attempts`, so each defaults to the schema's own
`Field(default=3, ge=1, le=10)`): 4 steps × 3 attempts = 12, if every step needed its full retry
budget — the same bound-derivation method Phase 13 M7's own authorization check already used for
`NEWS_ANALYSIS`, applied here to `CONTENT_GENERATION`'s own, structurally identical, 4-step/
3-attempt shape. No task-level retry exists beyond one `run_content_generation_for_event()` call
(§18-equivalent: no automatic `FAILED` retry anywhere in this Plan).

**Telegram: exactly 1 real API call** (`bot.send_message`), made only after §3's explicit human
dry-run confirmation and only via §4's temporary override — never before.

## 6. Human authorization checkpoint

**STOP HERE.** Everything above (§1 Stage A, §3's dry-run step) is either zero-cost or
already-safe-by-default (dry-run is the unmodified, current default). Proceeding past this point
performs §1 Stage B's real `CONTENT_GENERATION` run (real, billed provider calls) and, if §3's
dry-run confirmation already happened, §4's one live Telegram send. **Do not proceed without an
explicit, separate human "yes, proceed" naming the exact target chat ID.**

## 7. Rollback procedure

**If `CONTENT_GENERATION` reaches `COMPLETED` and the live send succeeds**: no rollback —
preserve every row (`NewsSource`, `NewsEvent`, the directly-constructed `NEWS_ANALYSIS` task, the
real `CONTENT_GENERATION` task, the real `ContentDraft`), clearly labeled as a Phase 14 M6
validation artifact in the synthetic event's own title/content — mirroring Phase 13 M7's own
preserve-and-label policy exactly, for the same reason: this is the durable evidence M6 happened
and succeeded.

**If `CONTENT_GENERATION` reaches `FAILED`**: an honest, disclosed outcome, not rolled back — the
`FAILED` task and its `workflow["failure"]` detail are preserved as real, informative data. No
`ContentDraft` would exist in this case (`ContentDraftService.create_from_result()` is never
reached), so §4's live-send step is simply never attempted. Report and stop; do not retry the same
`event_id` without a fresh, separate authorization.

**If §3's dry-run inspection reveals a wrong chat ID or wrong content**: no rollback needed —
nothing irreversible has happened yet. Correct the input and repeat §3 from the start.

**If the live send itself used a wrong chat ID** (a failure of §3's own human verification step,
not of this procedure's structure): the sent Telegram message cannot be reverted by this codebase
— only manually, by the human, deleting it from that chat if desired. This is exactly why §3's
dry-run confirmation is mandatory and why §6 requires the target chat ID to be named explicitly
in the authorization itself, not merely "some chat."

**Unexpected delta of any kind** (an unrelated `EditorialTask`/`ContentDraft` touched): mirrors
the remediation technique Phase 13 M3's own incident report already established — identify the
exact affected row(s) by direct query, revert to pristine state if genuinely caused by this
session's own action, report to a human before any further action. Given §1/§2's own structural
guarantee (one direct call, no selection step, no loop), this class of problem is not expected to
be reachable here, but the remediation path is stated in case it somehow is.

## 8. Post-send verification

1. `CONTENT_GENERATION` task reaches `COMPLETED`; its `workflow["step_results"]` shows all 4
   steps `SUCCESS`.
2. Exactly one `ContentDraft` row exists for that task, with real, sensible `title`/`body`/
   `hashtags` (not placeholder text).
3. `NotificationOutcome.sent is True` (the live call's own return value).
4. The message actually arrived in the confirmed target chat — human confirms by looking at
   Telegram directly; this is the one step that cannot be automated via a DB query.
5. Zero other `EditorialTask`/`ContentDraft`/`NewsEvent`/`NewsSource` rows were touched by this
   procedure — direct query, diffed against a baseline count recorded before §1 Stage A.
6. `settings.content_generation_dry_run` and `settings.editorial_chat_id` are confirmed back to
   their pre-validation values once the one-off process exits (§4's own `finally` block, or simply
   the process ending) — no persistent drift in any running process's configuration.

## 9. Confirmation of frozen boundaries (re-verified this session, not merely restated)

- **No autopublishing exists**: re-grepped `worker/content_cycle.py`, `worker/content_main.py`,
  `services/telegram_notifier.py` this session for `channel`/`publish`/`autopublish` — zero
  matches. The only outbound action anywhere in these three files is one `bot.send_message()` call
  to a single, explicitly-configured `chat_id` — never a channel, never iterated over a list of
  destinations.
- **No channel posting exists**: `send_editorial_card()`'s own signature takes one `chat_id: int |
  None` parameter, sourced from `settings.editorial_chat_id` alone — there is no channel-ID
  setting anywhere in `core/config.py`, and no code path constructs or resolves one.
- **No approval system exists**: re-grepped the same three files for `approve`/`approval`/
  `InlineKeyboard`/`reject` — zero matches, confirmed identical to the M0–M5 implementation
  report's own finding, re-verified fresh rather than merely re-cited.

---

**This document defines the procedure only. No step in §1 or later has been executed in producing
it — `content_generation_dry_run` remains `True`, `editorial_chat_id` remains unset, confirmed
read-only immediately before this document was written. M6 remains unauthorized pending a human's
explicit go-ahead at the §6 checkpoint, naming the exact target chat ID.**

---

PHASE 14 M6 READY FOR HUMAN AUTHORIZATION
