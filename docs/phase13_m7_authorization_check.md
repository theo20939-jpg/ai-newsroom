# Phase 13 — M7 Final Read-Only Authorization Check

Planning/verification only. No code was executed to produce this document beyond read-only
source re-inspection (no database write, no network call, no worker start). This check refines
one aspect of `docs/phase13_m7_live_validation_plan.md`: §5 of that document selected an
**existing** backlog task via a read-only diagnostic query; this check instead verifies a
**task-creation** path, which is safer still — it eliminates ambiguity about backlog selection
entirely, since the task does not exist until this validation creates it. The rest of
`phase13_m7_live_validation_plan.md` (§6 authorization checkpoint, §8 direct-invocation
execution, §9 requirement mapping, §11 rollback strategy) applies unchanged; only the "which
`task_id`" question is answered differently, more strictly, below.

## 1. Controlled task creation path — creates a fresh task, never selects an existing UUID

The creation path is `services.workflow_service.create_task()` — an already-existing, unmodified,
already-authorized production function (used throughout Triage's own real task creation, and
throughout every M1-M5 test in this Plan). Nothing new is introduced; it is invoked
interactively, exactly as `WorkflowRunner.run()` is in §8 of the live-validation plan.

Verified directly from source this session:

```python
# services/workflow_service.py:27-51 (re-read, unmodified)
async def create_task(session, command, registry=default_registry):
    event = await session.get(NewsEvent, command.event_id)
    if event is None:
        raise NewsEventNotFoundError(...)
    definition = registry.resolve(command.workflow_type)
    existing = await _find_active_task(session, command.event_id, command.workflow_type)
    if existing is not None:
        raise DuplicateActiveTaskError(...)
    state = WorkflowExecutionState(...)
    task = EditorialTask(event_id=..., priority=..., workflow=state.model_dump(mode="json"),
                          status=TaskStatus.CREATED, retry_count=0)
    session.add(task)
    await session.commit()
    ...
    return _to_read_schema(task)
```

The proposed M7 creation step: insert one real, uniquely-named, clearly-labeled `NewsSource` and
`NewsEvent` (mirroring the exact fixture pattern already proven safe in `tests/test_
analysis_worker_cycle.py`/`tests/test_news_analysis_integration.py` — unique name marker, e.g.
`phase13-m7-live-validation-<uuid>`, honest, human-readable title such as "Phase 13 M7 live
validation event — synthetic, not real news"), then call `create_task(session,
EditorialTaskCreate(event_id=<the new event's id>, workflow_type=WorkflowType.NEWS_ANALYSIS,
priority=TaskPriority.B))` with the **default** registry (no override). This is a real `INSERT`,
committed, producing a real `EditorialTask` row — not a selection from anything that already
exists. **Verified: PASS.**

## 2. The UUID passed to `WorkflowRunner.run()` is created during this validation, cannot
reference historical backlog

`EditorialTask.id` is `mapped_column(UUID(as_uuid=True), primary_key=True,
default=uuid.uuid4)` — re-read directly from `database/models/editorial_task.py:37` this
session. `uuid.uuid4()` generates a new random UUID (122 bits of randomness) at `INSERT` time;
it is not derived from, does not reference, and cannot coincide with any pre-existing row's ID.
The `task_id` used in §8 of the live-validation plan would therefore be the literal value
returned by this fresh `INSERT` — read directly from the just-created row, never typed in from
memory, never re-derived from a query against existing data. There is no code path by which this
identifier could resolve to one of the ~4,723 historical or ~1,100+ currently-fresh-eligible
backlog tasks. **Verified: PASS.**

Corollary, restated from the live-validation plan's own §3/§9: because the task does not exist
until this step creates it, `_select_eligible_task_ids()`/`run_analysis_cycle()` remain entirely
unused in this revised procedure too — the safety argument from the earlier plan (no selection
mechanism is ever invoked) is unweakened, and is now reinforced by the target UUID being
freshly minted rather than freshly *chosen*.

## 3. The created task uses the real `NEWS_ANALYSIS` workflow definition

`create_task()`'s own default parameter, `registry: WorkflowRegistry = default_registry`,
resolves to the module-level singleton constructed in `workflows/registry.py`:

```python
# workflows/registry.py:80-82 (re-read, unmodified)
registry = WorkflowRegistry()
registry.register(news_analysis.DEFINITION)
registry.register(content_generation.DEFINITION)
```

`news_analysis.DEFINITION` is the real, frozen `WorkflowDefinition` from `workflows/definitions/
news_analysis.py` — 4 steps (`research`→`intelligence`→`engagement_analysis`→`scoring`),
`max_iterations=3`, `retry_policy=WorkflowRetryPolicy(max_attempts=3, ...)`, `timeout_
seconds=120` — the exact same definition every real, Triage-created `NEWS_ANALYSIS` task in
production uses, byte-for-byte unmodified by any Phase 13 work. Calling `create_task()` with
`workflow_type=WorkflowType.NEWS_ANALYSIS` and no `registry=` override (the M7 procedure's own
design, matching how every real task is actually created) guarantees this real definition is
what gets attached — not a synthetic, test-only, or reduced definition. **Verified: PASS.**

## 4. Cleanup / preservation policy — explicit

**Decision: PRESERVE, not delete, following successful verification — with mandatory, permanent,
unambiguous labeling.**

Rationale: unlike M1-M5's own automated tests (which fabricate throwaway rows solely to exercise
code paths, correctly deleted after each run per the FK-safe `try/finally` convention already
established), M7 is not a test — it is the one human-authorized live proof that the real,
production `NEWS_ANALYSIS` pipeline genuinely works end-to-end with a real provider. Its
resulting row is the actual evidentiary record of that fact. Deleting it would discard the one
piece of durable proof that M7 happened and succeeded, leaving only this document's own
transcript as evidence.

**Explicit conditions attached to preservation**:
- The synthetic `NewsSource`/`NewsEvent` title/content must make unambiguous on read that this
  is a validation artifact, not real news (e.g., "Phase 13 M7 live validation event — synthetic,
  not real news, created <date>, see docs/phase13_m7_authorization_check.md").
- This row must never be surfaced to any editorial/publishing-facing view (`/news` or
  equivalent) as if it were a real event — out of this document's own scope to verify UI-layer
  filtering, flagged here as a follow-up check before this artifact could ever be considered
  fully inert, not merely functionally inert at the data layer.
- If the run instead ends `FAILED` (a genuine, honest outcome per the live-validation plan's own
  §11), the same preserve-with-labeling policy applies — a `FAILED` validation is still real
  evidence, not noise to discard.
- If §10 of the live-validation plan's own post-execution verification finds *any* unexpected
  delta (an unintended `CONTENT_GENERATION` task, a `ContentDraft` row, or a change to any task
  other than this one), the remediation path is deletion/reversion of only the *unexpected*
  artifact (mirroring the M3 incident's own remediation technique) — the intended, correctly-
  labeled validation row itself is never deleted merely because something else went wrong
  alongside it.

This is stated as the recommended, default policy for this check to be considered complete — a
human may override it (e.g., prefer deletion for a clean environment) at the same §6 authorization
checkpoint already defined in the live-validation plan, but the default is preserve-and-label, not
silently decided either way. **Verified: PASS (explicit, not left open).**

## 5. Maximum provider call budget remains bounded

Unchanged from `phase13_m7_live_validation_plan.md` §9 row 4, re-confirmed here since the
creation-path revision does not alter workflow execution mechanics at all (only how the target
`task_id` comes to exist): best case **4** real provider calls (research, intelligence,
engagement, scoring — one attempt each, all succeed). Structural worst case, re-derived directly
from `workflows/definitions/news_analysis.py`'s own 4 `WorkflowStepDefinition` entries (none
overrides `max_attempts`, so each defaults to the schema's own `Field(default=3, ge=1, le=10)`):
**12** calls (4 steps × 3 attempts each), if every step required its full retry budget — disclosed
as the honest structural ceiling, not the expected case. No task-level retry exists beyond a
single `run()` call (no automatic `FAILED` retry, Plan §18); `max_iterations=3` does not add
further calls within one `run()` invocation, since `iteration_count` only increments on a full
successful pass and a required-step failure aborts immediately via `_fail()` rather than
re-attempting the whole workflow. **Verified: PASS — unchanged, re-confirmed.**

## Summary

| # | Check | Verdict |
|---|---|---|
| 1 | Fresh creation, not existing-UUID selection | PASS |
| 2 | Target UUID cannot reference historical backlog | PASS |
| 3 | Real, unmodified `NEWS_ANALYSIS` definition used | PASS |
| 4 | Cleanup/preservation policy explicit | PASS (preserve + label, decided) |
| 5 | Provider call budget bounded | PASS (4 best case / 12 structural ceiling) |

No code was changed. No worker was started. No API call was made. No live execution occurred.
This document, together with `docs/phase13_m7_live_validation_plan.md` (§6 onward, using this
check's task-creation refinement in place of that document's own §5 selection step), is the
complete procedure awaiting one human's explicit go-ahead.

---

PHASE 13 M7 READY FOR HUMAN AUTHORIZATION
