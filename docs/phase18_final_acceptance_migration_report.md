# Phase 18 Final Acceptance — Migration Validation Report

Migration under test: `21177d5b859e_add_meme_candidates_table.py`.

## 1. Environment

- Docker Desktop started fresh this session (was not running at session start); `ai_newsroom_
  postgres` (postgres:16-alpine) and `ai_newsroom_redis` (redis:7-alpine) came up healthy.
  `ai_newsroom_backend` came up via Docker's own restart policy (not started by this audit).
  `ai_newsroom_content_worker`, `ai_newsroom_news_analysis_worker`, `ai_newsroom_automation_
  worker`, and `ai_newsroom_telegram_bot` remained in `Exited` state throughout — never started.
- PostgreSQL version: 16.14 (`postgres:16-alpine on x86_64-pc-linux-musl`).
- A dedicated, disposable database `phase18_validation_db` was created via `docker exec
  ai_newsroom_postgres psql ... CREATE DATABASE phase18_validation_db` — never the real
  `ai_newsroom` database. All migration/CRUD/integration work in this acceptance pass ran against
  `phase18_validation_db` only, selected via a `POSTGRES_DB=phase18_validation_db` environment
  variable override on individual command invocations (never by editing `.env`).
- Redis: available at `localhost:6379` (container healthy); used only by unrelated pre-existing
  tests during the full-suite run, not by anything Phase 18 added.

## 2. Static validation

Migration file inspected field-by-field against `database/models/meme_candidate.py`:

| Field | ORM type | Migration type | Nullable | Default | Index/constraint | Match |
|---|---|---|---|---|---|---|
| id | UUID, PK | UUID, PK | not null | Python-side `uuid.uuid4` | PK | ✅ |
| news_event_id | UUID, FK news_events | same | not null | — | FK + index | ✅ |
| editorial_task_id | UUID, FK editorial_tasks | same | nullable | — | FK + index | ✅ |
| content_draft_id | UUID, FK content_drafts | same | nullable | — | FK + index | ✅ |
| status | Enum(MemeCandidateStatus) | same 13-value enum | not null | `concept_generated` | index | ✅ |
| concept_schema_version | String | varchar | not null | — | — | ✅ |
| concept_data | JSON | json | not null | — | — | ✅ |
| concept_regeneration_count | Integer | int | not null | 0 | check ≥0 | ✅ |
| **safety_status** | String, **`index=True`** | varchar, **no index declared** | nullable | — | — | ❌ **found — fixed, see §4** |
| safety_reason_codes | JSON | json | nullable | — | — | ✅ |
| originality_status | String | varchar | nullable | — | — | ✅ |
| originality_reason_codes | JSON | json | nullable | — | — | ✅ |
| copy_schema_version | String | varchar | nullable | — | — | ✅ |
| copy_data | JSON | json | nullable | — | — | ✅ |
| copy_regeneration_count | Integer | int | not null | 0 | check ≥0 | ✅ |
| image_status | String | varchar | nullable | — | — | ✅ |
| image_storage_key | String | varchar | nullable | — | — | ✅ |
| image_provider | String | varchar | nullable | — | — | ✅ |
| image_model | String | varchar | nullable | — | — | ✅ |
| image_regeneration_count | Integer | int | not null | 0 | check ≥0 | ✅ |
| render_storage_key | String | varchar | nullable | — | — | ✅ |
| quality_decision | String | varchar | nullable | — | — | ✅ |
| quality_reason_codes | JSON | json | nullable | — | — | ✅ |
| quality_score | Integer | int | nullable | — | check 0-100 | ✅ |
| editor_decision | String, index=True | varchar, indexed | nullable | — | index | ✅ |
| editor_decision_reasons | JSON | json | nullable | — | — | ✅ |
| editor_decision_notes | Text | text | nullable | — | — | ✅ |
| editor_decision_at | DateTime(tz) | timestamptz | nullable | — | — | ✅ |
| published | Boolean | boolean | not null | False | — | ✅ |
| cumulative_cost_usd | Numeric(12,6) | numeric(12,6) | not null | 0 | check ≥0 | ✅ |
| created_at | DateTime(tz) | timestamptz | not null | server `now()` | — | ✅ |
| updated_at | DateTime(tz) | timestamptz | not null | server `now()` | — | ✅ (ORM `onupdate` is app-side, correctly absent from DDL) |

**Foreign keys**: 3 declared (`news_event_id`→`news_events.id`, `editorial_task_id`→
`editorial_tasks.id`, `content_draft_id`→`content_drafts.id`) — all present, all verified enforced
at runtime (§4).

**Check constraints**: 5 declared, all present: quality_score range, 3× regeneration-count
non-negative, cost non-negative.

## 3. Runtime upgrade

```
POSTGRES_DB=phase18_validation_db python -m alembic upgrade head
```

Applied the full chain from empty (`ef37f4253252` → ... → `21177d5b859e`), 8 migrations, 0
errors. Final revision confirmed via `alembic current` → `21177d5b859e (head)`. Live `\d
meme_candidates` in `psql` matched every column/type/nullable/default/index/FK/check-constraint
in §2 (table reproduced in full in the working session; the one mismatch is described in §4).

## 4. Real defect found and fixed

**Finding**: `database/models/meme_candidate.py` declares `safety_status` with `index=True`, but
the migration's `upgrade()` never created that index (only `ix_meme_candidates_status` and
`ix_meme_candidates_editor_decision` were explicitly created). This is exactly the kind of
ORM/migration drift a live-database check catches that code inspection alone had missed across
five prior milestone reports (M2 report's own schema description did not flag it).

**Fix**: added `op.create_index("ix_meme_candidates_safety_status", "meme_candidates",
["safety_status"])` to `upgrade()`, with the matching `op.drop_index(...)` added to
`downgrade()`. Safe to edit in place (not a new migration) — this revision had not been applied to
any real database (including the primary `ai_newsroom` database) before this fix; editing an
unpublished migration is the correct, minimal-blast-radius fix, not a schema-drift risk.

**Verification**: `phase18_validation_db` was dropped and recreated, the full chain re-applied,
and `\di ix_meme_candidates_safety_status` confirmed the index now exists.

## 5. Runtime CRUD smoke test

Exercised via `tests/test_phase18_db_integration.py::test_meme_candidate_full_lifecycle` (and
sibling tests) against `phase18_validation_db`, inside `tests/conftest.py`'s `db_session` fixture
(real transaction, rolled back at teardown via savepoints — nothing here was ever actually
persisted, on top of the fact this ran against a disposable database anyway):

- **Insert**: `create_from_concept()` — real row, correct default `status`.
- **Fetch**: `get_by_id()` — JSON round-trips (`concept_data["premise"]` intact).
- **Update allowed fields**: `add_cost()` called twice, accumulates correctly
  (`0.0012 + 0.0008 = 0.002000`, exact `Decimal` precision, not float-approximated).
- **Cost precision**: `Numeric(12,6)` confirmed to hold and return exact decimals.
- **Regeneration counters**: default `0`, columns present and queryable (exercised more fully in
  the offline E2E test, §6 of the DB integration report).
- **Decision recording**: `record_editor_decision(..., reasons=[STALE], notes=...)` — real reason
  taxonomy and notes persisted.
- **Timestamp behavior**: `editor_decision_at` set to a real UTC timestamp on decision.
- **Foreign-key enforcement**: an invalid `news_event_id` (`uuid4()`, no matching row) raises a
  real Postgres foreign-key-violation exception on `flush()` — not merely a Python-level check.
- **Invalid state rejection**: `add_cost()` with a negative `Decimal` raises `ValueError` before
  touching the database at all.
- **Transaction rollback**: proven structurally — every test in this suite runs inside
  `db_session`'s own rolled-back transaction; nothing written by any test is ever actually
  committed to the database's durable state.
- **Deletion/cascade**: no delete/cascade behavior was designed for `meme_candidates` (a
  `MemeCandidate` row is meant to be a permanent audit record, mirroring
  `ImageCandidateRecord`'s own no-cascade-delete precedent) — not tested because it is
  intentionally not a supported operation, not an oversight.

## 6. Downgrade and re-upgrade

```
POSTGRES_DB=phase18_validation_db python -m alembic downgrade -1
```
Result: `meme_candidates` table and its `meme_candidate_status` enum type both cleanly removed
(`\dt` before: 10 tables; after: 9 tables, `meme_candidates` absent; `SELECT typname FROM pg_type
WHERE typname = 'meme_candidate_status'` → 0 rows). All 9 other tables (`ai_executions`,
`alembic_version`, `channels`, `content_drafts`, `editorial_tasks`, `image_candidates`,
`news_events`, `sources`, `users`) remained present and untouched.

```
POSTGRES_DB=phase18_validation_db python -m alembic upgrade head
```
Result: revision `21177d5b859e` reached again cleanly; `ix_meme_candidates_safety_status`
re-verified present (proving the fix in §4 survives a downgrade/re-upgrade cycle, not merely the
first application). Basic CRUD (`test_phase18_db_integration.py`, full 15-test file) re-run and
passed against the re-upgraded schema.

This downgrade/re-upgrade cycle ran only against the disposable `phase18_validation_db`, never
against `ai_newsroom` (the real database) or any shared/production database.

## 7. Limitations

- The full migration *chain* (all 8 revisions back to the empty database) was exercised, not just
  the one Phase 18 revision in isolation — this is a stronger test than the brief's own minimum
  bar, since it also proves Phase 18's migration composes correctly on top of every prior phase's
  schema history, not merely that it is internally well-formed.
- This validation used PostgreSQL 16.14 specifically (the version this project's own
  `docker-compose.yml` pins) — not tested against any other PostgreSQL major version.
- The migration has still never been applied to the real `ai_newsroom` database or any shared/
  production database — only to the disposable validation database, by design.
