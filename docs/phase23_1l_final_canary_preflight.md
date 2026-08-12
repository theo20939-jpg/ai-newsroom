# Phase 23.1L — Final Local Acceptance Canary Preflight

Generated 2026-08-11, immediately before Part J's bounded live canary. All checks read-only
except the settings the canary script itself overrides in-process (never written to `.env`).

## 1. Branch / HEAD

`feature/phase19-editorial-depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb` — unchanged
all session, nothing committed.

## 2. Working tree

239 modified/untracked entries (uncommitted work spanning this entire long session, phases 19
through 23.1L). Nothing in this phase's own new files conflicts with or reverts any prior phase's
work — verified via targeted diffs during Parts A-H above.

## 3. Dev DB revision

`8faedf40f596` — unchanged (the accidental migration to `3f37cf34109d` during Part C was fully
reverted back to this exact revision, verified in Part C).

## 4. Test DB identity

`ai_newsroom_test` — a physically separate Postgres database, same server, migrated independently
to Alembic head (`3f37cf34109d`). `settings.postgres_test_db = "ai_newsroom_test"`.

## 5. Proof test DB != live/dev DB

- `settings.postgres_db` (`ai_newsroom`) and `settings.postgres_test_db` (`ai_newsroom_test`) are
  two distinct real Postgres databases (confirmed via `\l` — both listed independently, at
  independent Alembic revisions: dev `8faedf40f596`, test `3f37cf34109d`).
- `tests/conftest.py`'s Barrier 4 (`assert_is_test_database`) fails fast, before any I/O, if the
  two names ever coincide — proven by `tests/test_db_isolation_guard.py` (7/7 pass), including a
  direct negative case ("a test intentionally pointed at the normal development DB" - Part E's own
  required check) and a live round-trip proving `independent_session_factory()`/the `db_session`
  fixture's engine both genuinely connect to `ai_newsroom_test`, verified by asking Postgres
  itself (`SELECT current_database()`), not by re-reading a URL string.
- Directly demonstrated: running the two originally-contaminating test files, then a 7-file
  representative subset, then the full 3226-test suite, left the real dev DB's row counts
  byte-identical before and after every single time (Parts D/E/H).

## 6. Remaining confirmed test-pollution rows in dev DB

**Zero.** All 33 previously-leaked `NewsEvent` rows (plus 18 `NewsSource`, 50 `EditorialTask`, 14
`ContentDraft`, 21 `ContentDraftEditorialPlan`, 17 `NewsEventArticleAcquisition`, and their
`AIExecution` cost rows) were removed via exact-ID deletes in Part D, verified again here with a
fresh read-only query (`title LIKE '%integration test event%'` → 0 rows).

## 7. Worker states

| Container | Status |
|---|---|
| `ai_newsroom_postgres` | Up (healthy) |
| `ai_newsroom_redis` | Up (healthy) |
| `ai_newsroom_backend` | Up |
| `ai_newsroom_automation_worker` | Up (collection + triage, bundled) |
| `ai_newsroom_telegram_bot` | Up |
| `content_worker` | **stopped** (unchanged safety baseline) |
| `news_analysis_worker` | **stopped** (unchanged safety baseline) |

## 8. Active settings (real `.env`, before any in-process override)

`copywriting_prompt_version=4`, `editorial_delivery_mode=legacy`, `fact_safety_mode=shadow`,
`story_memory_mode=off`, `content_generation_dry_run=False`, `image_editorial_preview_enabled=True`,
`image_candidate_persistence_mode=finalists`, `newsroom_telegram_chat_id=None`,
`news_topic_id=None`, `content_generation_min_score=65`,
`content_generation_freshness_cutoff_hours=24.0`, `content_generation_scan_limit=50`,
`content_generation_batch_size=5`.

## 9. Copywriting version

Real `.env` default is `4`. The canary sets `copywriting_prompt_version="8.2"` **in-process only**
— `prompts/copywriting/v8.2.yaml` remains frozen/unmodified this phase, per the brief's explicit
instruction.

## 10. Editorial delivery mode

Real `.env` default is `legacy`. The canary sets `editorial_delivery_mode="router"` **in-process
only**, with `newsroom_telegram_chat_id`/`news_topic_id` hardcoded to the canary's own destination
(§15) — never left to resolve from ambient config.

## 11. Story Memory mode

`story_memory_mode=off`, honestly unchanged. Not touched, not enabled to shadow this phase (out of
scope per the brief's explicit "do not modify Story Memory algorithm" instruction — this canary
only *observes* Story Memory's existing classification for Part N's duplicate check, never alters
it).

## 12. Fact Safety mode

`fact_safety_mode=shadow`, unchanged. No enforcement, no send ever suppressed by it.

## 13. Fresh eligible NEWS_ANALYSIS count

**5** (real, live backlog — `automation_worker`'s own continuous collection+triage, not
manufactured).

## 14. Fresh eligible CONTENT_GENERATION count

**0** (confirms Part D's cleanup was complete and thorough — no leftover test-fixture row, and no
real backlog has accumulated a completed NEWS_ANALYSIS task yet at this exact moment;
`automation_worker` will continue producing NEWS_ANALYSIS completions during the canary's own run,
which the canary's own analysis-cycle rounds will pick up).

## 15. Telegram destination

Hardcoded in the canary script, asserted against the resolved route before any LLM/Telegram call:
`chat_id=-1004297182444`, `message_thread_id=2`. No other chat, no other topic — matches every
prior phase's canary destination exactly.

## Go/no-go

All 15 items confirm a clean, isolated, honestly-disclosed starting state. **Proceeding to Part J
(bounded live canary)**, with the true per-message hard cap (`scripts/_canary_delivery_cap.py`,
Part F/G) wired into the canary's own bot instance from the very first send.
