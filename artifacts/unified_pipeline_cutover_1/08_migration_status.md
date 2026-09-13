# Migration status — `a126e750c727_add_recovery_jobs_table.py`

- **Revision**: `a126e750c727`, `down_revision = 4a1b7c9d2e3f` (the current, unchanged production/dev
  head — single-head graph, confirmed via `alembic heads` showing exactly one head both before and
  after).
- **Cleaned**: the raw `alembic revision --autogenerate` output mixed the new `recovery_jobs` table
  with a large amount of PRE-EXISTING, unrelated schema drift between the shared local dev database
  and the current model set (table drops/constraint changes across ~13 unrelated tables —
  `telegraph_topic_proposals`, `event_recap_reviews`, `story_telegram_deliveries`,
  `news_event_story_links`, `content_draft_story_links`, `stories`, `telegraph_shortlist_batches`,
  `media_vision_reviews`, `ai_executions` indexes, `design_reference_assets`/`instagram_accounts`/
  `instagram_series`/`products`/`telegram_surfaces` unique-constraint/index changes). This drift is
  NOT caused by this phase — it reflects the shared local dev DB having drifted from the fully
  reconciled model set over many prior phases' own work in other worktrees. The migration file was
  manually cleaned to contain ONLY the `recovery_jobs` table, its 3 new enum types
  (`recovery_platform`, `recovery_reason_code`, `recovery_job_state`), and its 2 indexes.
- **Tested, real upgrade/downgrade** against the local dev database (`ai_newsroom`, NOT production):
  ```
  $ python -m alembic upgrade head
  INFO  Running upgrade 4a1b7c9d2e3f -> a126e750c727, add recovery_jobs table
  $ python -m alembic heads
  a126e750c727 (head)
  $ python -m alembic downgrade -1
  INFO  Running downgrade a126e750c727 -> 4a1b7c9d2e3f, add recovery_jobs table
  $ python -m alembic current
  4a1b7c9d2e3f
  ```
  Both directions completed cleanly with no errors; the dev DB was left at `4a1b7c9d2e3f` afterward
  — the exact state found at the start of this phase, undisturbed.
- **Applied to the dedicated pytest database** (`ai_newsroom_test`, structurally separate from both
  dev and production per `tests/conftest.py`'s own Barrier 4) so the new recovery-service test
  suites (`tests/test_unified_pipeline_recovery_service.py`,
  `tests/test_unified_pipeline_orchestrator_cutover.py`,
  `tests/test_unified_pipeline_cutover_authority.py`) have a real `recovery_jobs` table to write to
  — this is the dedicated, isolated test database every other real-Postgres test in this suite
  already writes to, never production, never the shared dev DB.
- **NOT applied to production** — no SSH session was opened to the production VPS at any point in
  this phase, no production migration was run, no production restart occurred.
- **Naming collision resolved by construction**: `database/models/recovery_job.py::RecoveryJob`
  (the new SQLAlchemy model) and `services/editorial_pipeline/contracts.py::RecoveryJob` (the
  pre-existing, unmodified in-process dataclass from UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1) share
  a class name — every real call site that needs both imports the DB model under an alias
  (`from database.models.recovery_job import RecoveryJob as RecoveryJobRow`, consistently, across
  `services/editorial_pipeline/recovery_service.py`, `services/editorial_pipeline/orchestrator.py`'s
  own `TYPE_CHECKING` import, and every new test file).
