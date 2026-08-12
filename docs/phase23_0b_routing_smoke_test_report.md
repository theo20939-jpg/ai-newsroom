# PHASE 23.0B — TELEGRAM ROUTING REAL SMOKE TEST

**Status: one real message sent, to NEWS only. No canary started.**

## 1. Configuration used

Real values (from the Phase 23.0A `/whereami` collection):

```
CHAT_ID          = -1004297182444
NEWS_TOPIC_ID    = 2
```

Applied via **in-process attribute assignment only** on the already-loaded `core.config.settings`
singleton (`settings.newsroom_telegram_chat_id = -1004297182444`,
`settings.news_topic_id = 2`), inside a standalone, one-off script
(`scripts/_phase23_0b_routing_smoke_test.py`, underscore-prefixed per this repo's own established
throwaway-diagnostic-script convention). **Not** written to `.env` or `.env.example` — confirmed
both before and after the run: `git status --short .env .env.example` is empty. Confirmed the
override did not persist beyond that one process: a fresh `python -c` invocation immediately
after the smoke test read `newsroom_telegram_chat_id=None`, `news_topic_id=None` — back to the
real, unconfigured defaults.

## 2. Routing path

Verified directly before sending (not assumed carried over from Phase 22):

- `services/telegram_routing.py::resolve_route()` reads `settings.newsroom_telegram_chat_id` and
  looks up the destination's topic-id attribute name via `_DESTINATION_TOPIC_SETTING[destination]`
  — no topic id or chat id is a literal anywhere in this module (confirmed by direct grep of the
  file before running anything).
- A standalone in-process check (`resolve_route(EditorialDestination.NEWS)` with the real values
  set) returned `RouteTarget(chat_id=-1004297182444, topic_id=2)` — the resolver works correctly
  against the real IDs.
- The smoke test itself called `services/telegram_routing.py::send_to_editorial_destination()`
  unmodified — the real Phase 22 function, not a bypass or a copy.
- `bot/loader.py::create_bot()` (the same, unmodified, real Bot construction every production
  entry point already uses) supplied the real `Bot`.
- Nothing in the script imports or calls any AI/LLM capability, `WorkflowRunner`,
  `CapabilityExecutor`, or `worker/content_cycle.py` — zero AI generation, zero paid call, zero DB
  write (routing itself performs no DB I/O at all).

## 3. Exact Telegram parameters

Printed before the live call (dry-run first, per the phase brief's own §3 requirement):

```
Destination: NEWS
Resolved chat_id: -1004297182444
Resolved thread_id: 2
Payload: 'Phase 23 routing smoke test'
```

Dry-run outcome (no network call, confirms the exact shape before the live one):
```
RoutingOutcome(destination=NEWS, chat_id=-1004297182444, topic_id=2, sent=False, reason='dry_run', message_id=None)
```

Live outcome (exactly one real `bot.send_message()` call, with `message_thread_id=2`):
```
RoutingOutcome(destination=NEWS, chat_id=-1004297182444, topic_id=2, sent=True, reason=None, message_id=62)
```

## 4. Result

- **Telegram API success**: `sent=True`, real `message_id=62` returned.
- **Correct `chat_id`**: `-1004297182444`, exactly the real NINJA NEWSROOM group ID collected in
  Phase 23.0A.
- **Correct `message_thread_id`**: `2`, exactly the real NEWS topic ID collected in Phase 23.0A.
- **Exactly one message sent** — the script constructs and sends only the NEWS route; MEME (`37`),
  TELEGRAPH (`39`), INSTAGRAM (`40`), REELS (`41`) were never referenced or called.
- Message appearing correctly inside the NEWS topic in the live group is a visual confirmation the
  user can verify directly in Telegram (this environment has no way to independently re-read the
  group's message history back).

## 5. Limitations

1. This validates only the **NEWS** destination — MEME/TELEGRAPH/INSTAGRAM/REELS routes are
   configured identically in `core/config.py`/`services/telegram_routing.py` but were not
   exercised live this phase, per the brief's own explicit "do not send to the other four" scope.
2. The chat id / topic id values are **not** persisted anywhere in the real environment — the next
   real send (including any future canary) requires the same in-process (or a deliberate, reviewed
   `.env`) configuration step again; nothing about this phase makes a future send "already
   configured."
3. `services/telegram_routing.py::send_to_editorial_destination()` is still not wired into any
   live/automated path (`worker/content_cycle.py`, `capabilities/executor.py`) — this smoke test
   used a standalone manual script, exactly as scoped; automated use still requires the design
   decision already flagged in `docs/phase23_0_canary_configuration_plan.md` §5.
4. No AI-generated content was involved — the payload was the literal, fixed string the phase
   brief specified (`"Phase 23 routing smoke test"`), not a real editorial draft.
5. Production/worker state is unchanged from Phase 23.0A: `content_worker`/`news_analysis_worker`
   remain `Exited`, `automation_worker`/`telegram_bot`/`postgres`/`redis`/`backend` unchanged. No
   Story Memory, suppression, or story-update setting was touched. `content_generation_dry_run`
   remains `False` in the real environment — the same finding disclosed in Phase 23.0A, still
   unresolved and still blocking any future `content_worker` start until deliberately reviewed.

---

**STOP condition met.** Smoke test successful. Not proceeding to Phase 23.1 (Local Live Newsroom
Canary) — waiting for approval.
