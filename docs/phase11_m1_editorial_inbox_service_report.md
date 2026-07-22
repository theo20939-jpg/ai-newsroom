# Phase 11 — M1 Editorial Inbox Service Report

## Files changed

- `schemas/editorial_inbox.py` (new) — `EditorialInboxCard` DTO, 9 frozen fields per Contract §8.
- `services/editorial_inbox_service.py` (new) — `get_latest_editorial_cards(session, *, limit=5)`.
- `tests/test_editorial_inbox_service.py` (new) — 10 tests.

## Implementation summary

`get_latest_editorial_cards()` runs a two-stage read: (1) `select(ContentDraft).join(EditorialTask,
...).where(status == COMPLETED).order_by(created_at.desc(), id.desc()).limit(limit)`, independently
compiled and verified to produce the exact expected SQL during the Plan Audit; (2) for each
resulting row, `session.get(EditorialTask, ...)` then `session.get(NewsEvent, ...)`, mirroring
`capabilities/executor.py`'s two-hop convention. `hashtags=draft.hashtags  # type: ignore[arg-type]`
mirrors `services/content_draft_service.py:56-59`'s identical, pre-existing convention for the same
ORM-typing looseness. No commit, no mutation, no `aiogram` import, no AI/workflow import anywhere.

## Deviation from the Plan (test-only, non-architectural)

The test database (`localhost:5432/ai_newsroom`) is shared with Phase 10's own live-validation
history — a real, previously-`COMPLETED` `ContentDraft` from Phase 10 M6 persists there, visible to
every test via `db_session`'s SAVEPOINT-scoped rollback (which isolates *this test's own* writes,
not pre-existing committed rows). The Plan's test sketches implicitly assumed an empty starting
table (`cards == []`, exact-list assertions). Adjusted every test to be correct in the presence of
that pre-existing row: membership/relative-order checks against a generous limit (50) instead of
bare equality, and the one genuine "empty" proof issues a `DELETE FROM content_drafts` scoped
entirely to the test's own rolled-back transaction (never committed, never destructive to the real
row — confirmed by re-running the full suite afterward with no data loss). This is a test-fixture
adjustment mechanically required by the real environment, not an architecture or scope change —
explicitly within the "autonomous correction" policy's permitted scope.

## Tests

10/10 passed: COMPLETED included; FAILED excluded; CREATED/RUNNING/WAITING excluded; newest-first
ordering; `id`-descending tie-break; limit-5 enforcement; empty result (via scoped `DELETE`); joined
`NewsEvent` metadata attached correctly (including a `news_url` containing a literal `&`); null
`news_url` handled without error; mechanical AST import-boundary check (no
`workflows.runner`/`capabilities.executor`/any `capabilities.*_capability`/
`scripts.run_content_generation`).

## Gates

- Focused pytest: `tests/test_editorial_inbox_service.py` — **10/10 passed**.
- `ruff check`: clean.
- `mypy` (targeted, `schemas/editorial_inbox.py` + `services/editorial_inbox_service.py`): clean.
- `scripts.validate_architecture`: 0 violations.
- Git scope: exactly `schemas/editorial_inbox.py`, `services/editorial_inbox_service.py`,
  `tests/test_editorial_inbox_service.py` — matches Contract §23/Plan §4 exactly.

## Self-audit

Read-only confirmed (no `session.add()`/`commit()` in the service). No `relationship()` added. No
migration. No AI/workflow import. No Phase 5–10 file touched.

## Verdict

**M1 PASSED — CONTINUING TO M2**
