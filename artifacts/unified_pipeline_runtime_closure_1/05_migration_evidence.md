# Migration evidence (§40/§44)

Migration: `database/migrations/versions/c48f6a1e9d02_recovery_jobs_concurrency_and_media_.py`
(`down_revision = 'a126e750c727'`, the current production head).

Purely additive: one `ALTER TYPE ... ADD VALUE IF NOT EXISTS` (new enum value
`MEDIA_RESOLUTION_FAILED`) and one `CREATE UNIQUE INDEX ... WHERE state IN ('PENDING','RETRYING')`
(partial unique index). No existing column, row, or constraint is altered or dropped. `downgrade()`
drops the index (safe) and documents why the added enum value is deliberately left in place
(Postgres has no `ALTER TYPE ... DROP VALUE`; rebuilding the type on downgrade risks data loss if
any row already uses the new value).

**Tested against the isolated local test DB only** (`ai_newsroom_test`, via
`POSTGRES_DB=ai_newsroom_test python -m alembic upgrade head`) - never applied to production
(`ai_newsroom`), per §48's explicit "do NOT apply production DB migration".

Verified post-upgrade, directly via SQLAlchemy against the test DB:

```
CREATE UNIQUE INDEX ix_recovery_jobs_open_lifecycle_identity
    ON public.recovery_jobs USING btree (content_draft_id, platform)
    WHERE (state = ANY (ARRAY['PENDING'::recovery_job_state, 'RETRYING'::recovery_job_state]))

recovery_reason_code enum_range:
['NO_SUITABLE_MEDIA', 'MEDIA_RESEARCH_TIMEOUT', 'MEDIA_SEND_FAILED', 'AMBIGUOUS_TRANSPORT_RESULT',
 'CAPTION_BUDGET_FAILED', 'RENDER_FAILED', 'QUALITY_GATE_FAILED', 'MEDIA_RESOLUTION_FAILED']
```

The new index's real, DB-enforced concurrency guarantee is exercised (not merely asserted) by
`tests/test_unified_pipeline_recovery_concurrency_and_platform_scoping.py::
test_concurrent_create_or_retry_for_the_same_identity_converges_to_one_open_row` - a genuine
`IntegrityError` from this exact index is raised and recovered from during that test run.
