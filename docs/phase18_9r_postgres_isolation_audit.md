# Phase 18.9-R M6 — Production Database Isolation Audit

Status: complete. Read-only investigation, one honest correction made to the brief's own assumed
shape (documented below rather than silently reinterpreted).

## Does the test suite connect to the real, local production PostgreSQL database?

**Yes, confirmed directly.** `tests/conftest.py::_test_engine = create_async_engine(settings.
database_url, poolclass=NullPool)` uses the exact same `settings.database_url` the production
application itself uses. `SELECT current_database()` via this same connection path returns
`ai_newsroom` - the real, live database name, not a separate `..._test` database. **Database
identity is the same, not different.**

## Correction to the brief's own assumed test shape

The brief's M6 asks for a test "proving that test database identity is not the production database
identity." Given the finding above, that specific claim would be **false** if asserted - no
separate test database exists anywhere in this codebase's current infrastructure, and creating one
now would be a large, disproportionate infrastructure change (new `docker-compose.yml` service, CI
wiring, migration duplication) unrelated to this incident's actual cause. **Not implemented**,
documented here rather than silently reinterpreted or falsely claimed done. What §2 below
implements instead is one of the brief's own other three listed acceptable options: "explicit
fixture-bound rollback" (already the existing `db_session` design) - verified, not replaced.

## Why SAVEPOINT-based rollback is, on its own evidence, sufficient for Postgres-row isolation

`db_session` wraps every test's Postgres work in a real transaction, joined via
`create_savepoint` mode, rolled back at teardown - meaning **no row any test creates, updates, or
deletes is ever actually committed to `ai_newsroom`**, regardless of how many times the code under
test calls `session.commit()` (each such call only commits the SAVEPOINT, not the outer
transaction). This is not a new claim - it is this project's own, already-established,
years-deep-tested convention, used by hundreds of existing tests.

**Direct proof this held even during the real Phase 18.9 incident**: the vulnerable test created a
real `EditorialTask`/`NewsEvent` pair and ran a genuine `WorkflowRunner.run()` against it - yet
`ai_executions`/`editorial_tasks`/`news_events` row counts were checked repeatedly throughout the
incident investigation and never showed any permanent change attributable to it (the real damage
was entirely in Redis, never in Postgres). **SAVEPOINT rollback was never the gap** - the gap was
that a test could reach *external* side effects (a real paid API call, real Redis writes) that a
Postgres rollback structurally cannot undo, because they are not part of the Postgres transaction
at all. That gap is what Barriers 1-3 (M2-M4) and the Redis isolation (M5) close - M6 confirms the
Postgres side was never the actual vulnerability, not that it needed the same kind of fix.

## Real, current production counts (baseline for M9's own before/after comparison)

| Table | Count |
|---|---|
| `news_events` | 13,744 |
| `ai_executions` | 4,632 |
| `content_drafts` | 284 |
| `editorial_tasks` | 14,303 |

(`news_events`/`editorial_tasks` continue growing - `automation_worker` remains running per
Phase 18.8's own authorized state; this is expected, real, ordinary collection activity, not
test-attributable growth. `ai_executions`/`content_drafts` are the two tables genuinely at risk of
test-attributable growth, since only a real paid workflow execution can add to them - both remain
unchanged from every check throughout this entire session.)

## Tests added (M7)

Rather than a (false) "different database identity" assertion, `tests/
test_phase18_9r_isolation_barriers.py` includes a database-isolation test category that:
- confirms `db_session`'s own real `current_database()` equals `ai_newsroom` (documents the true
  shared-identity fact rather than hiding it);
- proves a `db_session`-scoped write (a real `EditorialTask`/`NewsEvent` insert, flushed) is
  invisible to a **separate**, independent connection querying the real table directly - i.e., the
  SAVEPOINT is never visible outside its own transaction, the actual property that matters;
- confirms real `news_events`/`ai_executions`/`content_drafts`/`editorial_tasks` counts, read via
  a connection outside any test transaction, are unaffected by running the isolation-barrier test
  file itself.

No `meme_candidates` migration was applied anywhere in this milestone.
