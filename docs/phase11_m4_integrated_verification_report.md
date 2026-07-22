# Phase 11 — M4 Integrated Read-Only Verification Report

## Scope

No new production code this milestone. Added 4 integration tests to the already-authorized
`tests/test_news_handler.py` (no new test file — Contract §23/Plan §4 authorize exactly 3 test
files; adding integration coverage to the existing handler-test file is the correct home, since it
already has the `aiogram` fake-session infrastructure these tests reuse). Confirmed via grep: no
existing test elsewhere in the repository required mechanical modification because `/news`'s
behavior changed — no other test imports anything from `bot.*`.

## What was proven, real stack end to end

Real `db_session` → real `services.editorial_inbox_service.get_latest_editorial_cards` → real
`bot.formatting.render_editorial_card` → real `bot.handlers.news.handle_news`, with only the
external Telegram transport faked (the same `FakeSession` technique from M3). No OpenAI, no
`WorkflowRunner`, no `ContentDraft` generation anywhere — fixture rows constructed directly at the
ORM level, exactly as M1's own tests do.

- **Safe HTML end to end**: a real `NewsEvent.title` containing `<script>...</script> &`, a real
  `ContentDraft.title` containing `<b>title</b>`, and a `NewsEvent.url` containing a literal `&`
  were all persisted, retrieved through the real query, rendered through the real renderer, and
  sent through the real handler — the outgoing text is confirmed free of the raw `<script>` tag,
  correctly escaped, and within the UTF-16 length invariant.
- **Ordering and limit**: 6 real rows with distinct `created_at` values → exactly 5 sent, in
  newest-first order (the 6th, oldest row correctly excluded by the frozen limit).
- **Empty state**: a `DELETE FROM content_drafts` scoped entirely to the test's own
  SAVEPOINT-rolled-back transaction (never committed, never destructive to Phase 10's real M6
  validation row) produces the frozen empty-inbox message.
- **Zero DB mutation**: a real `ContentDraft` row's full field snapshot is byte-for-byte identical
  before and after a real `handle_news()` invocation.

## M4 final automated gate

| Gate | Result |
|---|---|
| Focused Phase 11 tests (`test_editorial_inbox_service.py` + `test_editorial_card_formatting.py` + `test_news_handler.py`) | **47/47 passed** (10 + 24 + 13) |
| Full repository `python -m pytest -q` | **774/774 passed** (0:05:57) |
| `python -m ruff check .` | Clean (one `F841` unused-variable finding surfaced and fixed during this milestone — see Deviations) |
| Targeted `mypy` on all 4 changed/new production files | Clean |
| `python -m scripts.validate_architecture` | 0 violations |
| Secret hygiene | `.env` not tracked, not in `git status`; no credential-shaped string in any new file (the test file's Telegram token is an explicitly-labeled, non-functional placeholder, `123456:FAKE-TEST-TOKEN-...`) |
| Git scope | Exactly `bot/handlers/news.py` (modified) + `schemas/editorial_inbox.py` + `services/editorial_inbox_service.py` + `bot/formatting.py` (new) + 3 new test files — no migration, no unexpected file |

## Deviations found and fixed within authorized scope this session

1. **M1** (`tests/test_editorial_inbox_service.py`): the shared test database carries real,
   pre-existing `COMPLETED` data from Phase 10's own M6 live validation. Tests were written to be
   correct in its presence (membership/relative-order checks, a transaction-scoped `DELETE` for the
   one genuine "empty" proof) rather than assuming an empty table.
2. **M2** (`tests/test_editorial_card_formatting.py`): one test's expected UTF-16/`len()` delta was
   corrected from 5 to 6 (the card's own static header emoji is itself astral and contributes its
   own +1) — a test-expectation fix, not a renderer fix.
3. **M3** (`tests/test_news_handler.py`): the `FakeSession` test double initially recorded a failed
   `SendMessage` attempt as "sent" before raising the simulated Telegram error, causing a false
   failure in the send-failure-continuation test — fixed by moving the failure check ahead of the
   bookkeeping append. A bug in test infrastructure added this session, not in `bot/handlers/news.py`.
4. **M4**: `ruff` flagged one unused local variable (`draft`) in a new integration test — fixed by
   using it in two additional assertions (title sanity-check, `news_url` escaping check),
   strengthening the test rather than merely silencing the linter.

All four are within the "autonomous correction" policy's explicit permission (bugs/fixture
adjustments in code added during the current milestone). No architecture, scope, or Contract/Plan
text was touched.

## Self-audit

See consolidated 18-question self-audit in the final response below — all 18 answers match the
Contract/Plan's expected values; no blocker was triggered.

## Uncommitted state

**Nothing has been committed.** All 7 files (1 modified, 6 new) remain in the working tree,
unstaged, exactly as required by this task's commit discipline.

## Verdict

**M4 PASSED.**
