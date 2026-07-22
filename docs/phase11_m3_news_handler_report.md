# Phase 11 — M3 /news Handler Report

## Files changed

- `bot/handlers/news.py` (modified) — placeholder body replaced with the real
  query→render→send flow.
- `tests/test_news_handler.py` (new) — 9 tests. This repository's first bot-handler test file.

## Implementation summary

`handle_news()` opens `async_session_factory()` in one `async with` block spanning query + render
+ send (mirroring `scripts/run_content_generation.py`'s established pattern — the bot layer has no
DI, `bot/loader.py::create_dispatcher()` still returns a bare `Dispatcher()`, unchanged). Query
failure → generic text (§16 Case B), logged with full detail server-side only. Empty result →
frozen empty-inbox text (§16 Case A). Each card is rendered and sent in a per-card try/except:
`CardTooLongError` (the M2 terminal-fallback signal) and `TelegramAPIError` (the real,
installed-package exception a still-oversized or malformed payload raises) are each logged and
skipped independently, never aborting the remaining cards (§16 Case E / finding N-2). Forum-topic
`message_thread_id` preservation requires zero handler code — inherited automatically via
`message.answer()`, exactly as Contract §10 (corrected, finding F-3) specifies.

## Test architecture (first-of-its-kind)

Per the Implementation Plan Audit's own MINOR-1 finding, the exact technique it recommended naming
was used: a `FakeSession(aiogram.client.session.base.BaseSession)` subclass overriding
`make_request()`, bound to a real `Bot` instance via `Bot(token=..., session=fake_session)`,
constructing a real `aiogram.types.Message` and binding it via `.as_(bot)`. Zero network access,
zero production-code change. `async_session_factory` and `get_latest_editorial_cards` are patched
at the `bot.handlers.news` module boundary so these tests exercise only the handler's own
orchestration logic, not M1/M2's already-independently-tested internals.

## Deviation (test-double bug, found and fixed within this milestone)

The first `FakeSession.make_request()` draft appended every attempted `SendMessage` to
`self.sent` *before* checking whether it should simulate a Telegram failure — so a message that
correctly raised `TelegramBadRequest` was still recorded as "sent," causing
`test_telegram_send_failure_is_skipped_remaining_cards_still_sent` to see 3 sent messages instead
of 2. Fixed by moving the failure check ahead of the `self.sent.append()` call. This was a bug in
the test double added this milestone, not in `bot/handlers/news.py` — corrected within the
"autonomous correction" policy's explicit permission to fix bugs in code added during the current
milestone.

## Tests

9/9 passed: `/news` calls the service with `limit=5`; empty-inbox sends the frozen text; one
message sent per card; DB/service failure sends the generic text and never leaks exception detail
(explicitly asserted — a raised `RuntimeError` containing a fake hostname string is confirmed
absent from the user-facing reply); a mid-batch `CardTooLongError` skips only that card and both
neighbors are still sent; a mid-batch `TelegramAPIError` (via `TelegramBadRequest`) does the same;
forum-topic `message_thread_id=777` is preserved on the outgoing `SendMessage` with zero handler
code fighting it; a private-chat reply lands in the invoking chat; mechanical AST import-boundary
check confirms zero import of `workflows.runner`/`capabilities.executor`/any
`capabilities.*_capability`/`scripts.run_content_generation`.

## Gates

- Focused pytest: `tests/test_news_handler.py` — **9/9 passed**.
- Combined M1–M3 regression: **43/43 passed**.
- `ruff check`: clean.
- `mypy` (targeted, `bot/handlers/news.py`): clean.
- `scripts.validate_architecture`: 0 violations.
- Git scope: `bot/handlers/news.py` (modified) + 6 new files (3 production, 3 test) — matches
  Contract §23/Plan §4 exactly; `bot/handlers/{start,digest,status,settings}.py`,
  `bot/handlers/__init__.py`, `bot/loader.py`, `bot/main.py` all confirmed untouched.

## Self-audit

No `EditorialTask` creation, no AI/workflow import, no `ContentDraft` mutation, no
delivered/read/review-state marker, no approval/rejection, no public-channel publish call anywhere
in the handler. Session opened once, closed once, no raw `select()`/SQL written in the handler
itself (all query logic remains in `services/editorial_inbox_service.py`).

## Verdict

**M3 PASSED — CONTINUING TO M4**
