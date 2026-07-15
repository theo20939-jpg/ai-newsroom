# Phase 5 Planning Report — Workflow Engine

**Status: APPROVED for implementation**, with the amendments in this revision. No migrations, no changes to `EditorialTask`.

---

## 1. Confirmed requirements (highest-priority documents only)

| # | Requirement | Exact source |
|---|---|---|
| 1 | Phase 5 is named "Workflow Engine," creates a "Task Manager," and supports exactly `NEWS_ANALYSIS`, `CONTENT_GENERATION`, `DAILY_DIGEST` | **docs/10 §6, "PHASE 5"** — verified verbatim, not paraphrased |
| 2 | `EditorialTask` fields: `event_id`, `priority` (S/A/B/C), `workflow` (JSON), `status` (CREATED/RUNNING/WAITING/COMPLETED/FAILED), `retry_count` | **docs/08 §10** — matches the actual ORM model and migration exactly |
| 3 | "Capability" is the only correct term; "Agent" must not be used | **docs/13_1 §6** |
| 4 | AI calls only ever go through a future `LLM Gateway`; no direct provider SDK calls in business logic | **docs/10 Rule 3**, **docs/13_1 §7** |
| 5 | Celery is not used in MVP; APScheduler is the scheduler of record | **docs/10_1 §6**, **CLAUDE.md** |
| 6 | Every AI call logs model/tokens/cost/timestamp; daily/monthly cost caps exist | **docs/10_1 §12** — explicitly a future Cost Control Module (`services/cost_tracker.py`, docs/13_1 §9), not Phase 5 |
| 7 | A separate test database is required; "cannot test on the production database" | **docs/13 §9** |
| 8 | No test in this project currently touches a real Postgres connection (all 88 use mocks/pure functions) | Verified directly (`grep` across `tests/`) |
| 9 | `schemas/` (top-level), not `database/schemas/`, is the established pattern; `schemas/source_import.py` already reuses `SourceType` from `database.models` rather than duplicating it | Verified directly in code — precedent, not a doc |

---

## 2. Document priority — the order followed, and why

Two documents give **incompatible** priority orderings, and neither addresses the other's authority:

- **CLAUDE.md**: `02 > 03 > 06 > 01 > everything else`, with a specific carve-out that `10_1` and `13_1` outrank `07` and `10` — but says nothing about `10_1`/`13_1` vs `02/03/06`.
- **docs/13_1 §14 "Source of Truth"**: `13_1 > 10_1 > 10 > "all other documents"` — placing `02`, `03`, `06`, `08` all in the undifferentiated bottom tier.

**Resolution (approved):** CLAUDE.md is the operating instruction addressed directly to the assistant for this repository — a meta-layer describing how to behave, not a product-architecture document competing with the others on its own terms. `docs/13_1` is a product document; its §14 asserts priority over *other product documents describing the system*, not over the assistant's own operating charter. Working rule:

> **CLAUDE.md governs how document conflicts are resolved. Where CLAUDE.md is silent on a specific pairing (e.g., it never says whether `10_1` outranks `06`), the gap is not filled using `docs/13_1`'s own self-declared ranking — it is flagged as unresolved instead.**

Effective order:

```
02 > 03 > 06 > 01 > (10_1, 13_1 — outrank 07 and 10 specifically) > everything else including 07, 10
```

Under this ordering, `docs/06`'s numbers are **not automatically beaten** by `10_1`/`10` — which is exactly why Conflict 1 needed an explicit decision rather than an automatic one.

---

## 3. Document conflicts (complete, all resolutions approved)

### Conflict 1 — global iteration/cycle cap
- **Document A**: CLAUDE.md + docs/10_1 §9 → `MAX_AI_ROUNDS = 3`
- **Document B**: docs/06 §6.7 (Retry Manager) → "5 workflow cycles"
- **Conflicting values/behaviour**: 3 vs 5, both framed as "stop infinite workflow looping"
- **Implementation impact**: sets the default of `WorkflowDefinition.max_iterations`
- **Resolution (approved)**: **3** — three independent sources (CLAUDE.md, 10_1, 10) converge on it; only docs/06 §6.7 says 5

### Conflict 2 — internal disagreement inside docs/06
- **Document A**: docs/06 §6.7 (Retry Manager) → "5 workflow cycles"
- **Document B**: docs/06 §7.7 (Quality retry loop) → `max_cycles = 3`
- **Conflicting values/behaviour**: the same document gives two different numbers for the same kind of guardrail
- **Implementation impact**: none directly — disqualifies docs/06 as an internally reliable tie-breaker for Conflict 1
- **Resolution (approved)**: treat docs/06's self-contradiction as additional support for the 10/10_1 value (3)

### Conflict 3 — per-priority retry budget vs. flat iteration cap
- **Document A**: docs/06 §6.6 (Budget Manager) → retries by priority: S=3, A=2, B=1, C=0
- **Document B**: CLAUDE.md / docs/10_1 → flat `MAX_AI_ROUNDS = 3`
- **Conflicting values/behaviour**: not the same axis — one is a per-priority AI-call retry allowance under a Budget Manager that doesn't exist yet; the other is a flat, workflow-level infinite-loop breaker
- **Implementation impact**: if merged, `WorkflowRetryPolicy.max_attempts` would incorrectly become priority-dependent, requiring Priority-Manager/Budget-Manager logic out of scope for Phase 5
- **Resolution (approved)**: Phase 5 implements only the flat, definition-level cap. Priority-dependent retry budgets are not built anywhere in Phase 5.

### Conflict 4 — EditorialTask state machine
- **Document A**: docs/06 §6.1 → `Created → Processing → Review → Approved → Completed → Failed` (6 states)
- **Document B**: docs/08 §10 + the actual migrated ORM model → `CREATED/RUNNING/WAITING/COMPLETED/FAILED` (5 states)
- **Conflicting values/behaviour**: entirely different state sets; no `Review`/`Approved` exist in the real schema
- **Resolution (approved)**: keep the existing 5-state enum unchanged; docs/06 §6.1 is a superseded earlier draft. See §9 for the exact transitions used in Phase 5, further narrowed by amendment 2 below.

### Conflict 5 — which document-priority list governs
- **Document A**: CLAUDE.md's stated priority order
- **Document B**: docs/13_1 §14's own "Source of Truth" order
- **Resolution (approved)**: CLAUDE.md governs how document conflicts are resolved; docs/13_1 §14's self-ranking is authoritative for product/architecture content, not for overriding this conflict-resolution behavior (see §2)

### Conflict 6 — what "Phase 5" means across documents
- **Document A**: docs/06 §12, docs/10_1 §13, docs/12 → "Phase 5 = AI Layer"
- **Document B**: docs/10 §6 → "Phase 5 = Workflow Engine" with exactly `NEWS_ANALYSIS`/`CONTENT_GENERATION`/`DAILY_DIGEST`
- **Resolution (approved)**: docs/10 is the specific, development-order-focused specification for this exact task and matches the brief verbatim; the others are earlier, coarser roadmap drafts

---

## 4. Workflow model (amended)

**Phase 5 registers exactly two workflow types, not three.**

Per approved amendment 1: `DAILY_DIGEST` is **not registered** in `WorkflowRegistry` in Phase 5. `EditorialTask` carries a single `event_id`; a digest inherently spans many events. Registering a workflow that cannot actually run against the current data model would be technical debt, not infrastructure. `DAILY_DIGEST` will be added as a complete, real `WorkflowDefinition` in a future **Digest Engine** phase, once the data model question (how a digest attaches to — or replaces — the single-event shape) is solved on its own terms.

**Exact persisted `WorkflowType` values in Phase 5**: the string literals `"NEWS_ANALYSIS"` and `"CONTENT_GENERATION"` — defined as a Python `WorkflowType(str, Enum)` in `schemas/workflow.py`. (The enum type itself may still declare `DAILY_DIGEST` as a recognized name for forward compatibility with the future Digest Engine phase, but the Registry never registers a definition for it and `resolve(WorkflowType.DAILY_DIGEST)` raises `UnknownWorkflowTypeError` in Phase 5.) There is no database enum/column for workflow type; the value is persisted **only** as the `workflow_name` field inside `EditorialTask.workflow` (JSON).

**Are `NEWS_ANALYSIS`/`CONTENT_GENERATION` real workflow definitions?** Yes — each gets its own concrete `WorkflowDefinition` instance (steps, retry policy, timeouts, required/expected I/O), registered in `WorkflowRegistry` at import time from `workflows/definitions/{news_analysis,content_generation}.py`. They are not placeholder labels; the Registry rejects `resolve()` for anything unregistered with `UnknownWorkflowTypeError`.

**Representation of the 11-step pipeline (docs/13_1 §11)** — two `WorkflowDefinition`s in Phase 5, each covering a disjoint slice:
- `NEWS_ANALYSIS` → steps 4–7 (Research → Intelligence → Engagement Analysis → Scoring), one `NewsEvent` in.
- `CONTENT_GENERATION` → steps 9–10 (Copywriting → Quality), one already-analyzed task in.
- Step 8 (Digest Generation) is not represented by any `WorkflowDefinition` in Phase 5 — deferred to the future Digest Engine phase along with `DAILY_DIGEST` itself.

The steps themselves (Research, Intelligence, Scoring, Copywriting, Quality) are represented as a small reusable **step vocabulary** (`WorkflowStepDefinition.capability` string identifiers) — not a separate "step library" module, since each workflow only reuses these same named capability placeholders, not shared executable code.

**Exact JSON snapshot stored in `EditorialTask.workflow`** (amended: integer `workflow_version`, per-step `started_at`/`finished_at`):
```json
{
  "workflow_name": "NEWS_ANALYSIS",
  "workflow_version": 1,
  "current_step": "intelligence",
  "completed_steps": ["research"],
  "iteration_count": 1,
  "step_results": [
    {
      "step_name": "research",
      "status": "SUCCESS",
      "attempt": 1,
      "started_at": "2026-07-15T16:00:00Z",
      "finished_at": "2026-07-15T16:00:00.412Z",
      "error": null,
      "result": {}
    }
  ],
  "failure": null
}
```
`failure`, when set, is itself a flat JSON-serializable dict, e.g. `{"step": "scoring", "error_type": "PermanentStepFailureError", "message": "...", "occurred_at": "2026-07-15T16:00:00Z"}`. Nothing else — no Python objects, no `WorkflowDefinition`, no callables — is ever written to this column. `started_at`/`finished_at` per step exist specifically so that SLA measurement, Capability duration analytics, and bottleneck-finding can be built later **without any change to this JSON structure**.

---

## 5. Limits and retry — six concepts, kept fully separate, plus the Iteration/Retry invariant

| Concept | What it is | Value | Where it lives |
|---|---|---|---|
| `MAX_AI_ROUNDS` | A **documentation-level** concept (CLAUDE.md, docs/10_1 §9, docs/10 §8) describing "don't let AI chains run forever" | 3 (as documented) | Not a Phase 5 field by this name — informs the default below |
| workflow `max_iterations` | The **actual Phase 5 field**, on `WorkflowDefinition`, checked by `WorkflowRunner` once per full step-loop pass | **3** (default) | `WorkflowDefinition.max_iterations` |
| retry counts by priority (S/A/B/C = 3/2/1/0) | A **future** per-priority AI-call retry budget (docs/06 §6.6, Budget Manager) | Not implemented | Out of scope for Phase 5 entirely |
| `WorkflowStepDefinition.max_attempts` | Per-step retry bound, independent of `max_iterations` | Proposed default: 3 | `WorkflowStepDefinition.max_attempts`, per step, can differ step to step |
| `EditorialTask.retry_count` | Existing DB column, cumulative across the whole task's life | Incremented by 1 each time the Runner retries a step (any attempt beyond the first for that step) | Existing column, unchanged type |
| timeout | `WorkflowStepDefinition.timeout_seconds` (per step) and `WorkflowDefinition.timeout_seconds` (whole run) | No doc gives numbers for Phase 5 | Enforced structurally (e.g. `asyncio.wait_for`) even with a deterministic placeholder executor |

### Architectural invariant: Iteration ≠ Retry (approved amendment 3)

These are **two fully independent mechanisms** and must never be conflated in code:

- **Iteration**: one complete pass of the workflow through *all* its steps, start to finish. `iteration_count` increments only when a full pass completes (successfully or by reaching the end of the step list), and is compared against `max_iterations`.
- **Retry**: re-execution of exactly *one* `WorkflowStep`, in place, without restarting the workflow or touching `iteration_count`. Bounded by that step's own `max_attempts`, and reflected in `EditorialTask.retry_count`.

Explicitly: **a retry never increments `iteration_count`**, and **an iteration is never used to mean "retry one step."** Nothing in `WorkflowRunner` may increment both counters for the same event.

---

## 6. EditorialTask compatibility — field by field, with migration verdict

| Field | Current model | Phase 5 requirement | Compatible? |
|---|---|---|---|
| `event_id` | `UUID`, FK → `news_events.id`, not null | `WorkflowService.create_task()` needs exactly this | Yes |
| `priority` | Enum `TaskPriority` (S/A/B/C), not null | Explicit caller input (no Priority Manager exists to derive it) | Yes |
| `workflow` | `JSON`, nullable | Holds `WorkflowExecutionState`; Service always populates it on insert | Yes |
| `status` | Enum `TaskStatus` (CREATED/RUNNING/WAITING/COMPLETED/FAILED), not null, default CREATED | Phase 5 only ever uses CREATED/RUNNING/COMPLETED/FAILED (see §9) | Yes |
| `retry_count` | `Integer`, not null, default 0 | Incremented per step retry only (never per iteration) | Yes |
| `created_at`/`updated_at` | Server-managed (`server_default`/`onupdate`) | No application code touches these directly | Yes |

**Migration verdict: no migration is needed. Phase 5 is fully implementable against the current `EditorialTask` schema exactly as it exists today.** `WAITING` remains in the enum solely for schema compatibility (see §9) — its presence in the column type requires no migration action since it is already part of the existing enum.

---

## 7. Proposed architecture (amended)

- **`WorkflowDefinition`** — frozen Pydantic model: `name` (`WorkflowType`), `version` (**`int`**, not a string — simplifies future compatibility checks), `steps` (`list[WorkflowStepDefinition]`, min length 1), `max_iterations`, `retry_policy` (`WorkflowRetryPolicy`), `timeout_seconds`, `required_input`, `expected_output`.
- **`WorkflowStepDefinition`** — frozen Pydantic model: `name`, `capability` (placeholder string, e.g. `"research"` — not an implementation), `required`, `max_attempts`, `timeout_seconds`.
- **`WorkflowRetryPolicy`** — frozen Pydantic model: `max_attempts`, **`retry_delay_seconds`** (replaces the earlier `backoff_seconds` name; defaults to `0` in Phase 5, kept as a real field now so a future phase can populate it without a model change), `retryable_error_types` (a closed list of error-type names, not arbitrary strings).
- **`WorkflowRegistry`** — plain class over an immutable in-memory dict built once, at import time, from the registered definition modules (`news_analysis.py`, `content_generation.py` only — see §4). `register()` enforces unique `(name, version)` → `DuplicateWorkflowRegistrationError`; `resolve(workflow_type)` returns a frozen `WorkflowDefinition` or raises `UnknownWorkflowTypeError`. **Architectural invariant (approved amendment 7): the Registry is immutable after construction — no dynamic registration at runtime, ever. Every workflow that exists in the running system was registered at import time; nothing calls `register()` outside of module-load. No database access, no Telegram/AI dependency, no runtime state.**
- **`WorkflowService`** — module of async functions (mirrors `services/collector.py`'s style, not a class). **Scope, per approved amendment 9, is exactly two functions:**
  - `create_task(session, event_id, workflow_type, priority)`: validates the `NewsEvent` exists, checks for an existing active task (see uniqueness key below), resolves the definition via the Registry, builds the initial snapshot, inserts the `EditorialTask` with `status=CREATED`, logs, returns `EditorialTaskRead`.
  - `get_task(session, task_id)`: read-only lookup, returns `EditorialTaskRead` or raises `TaskNotFoundError`.
  - **`WorkflowService` never transitions a task's status itself, under any circumstance. Status changes are the exclusive responsibility of `WorkflowRunner`.**
- **`WorkflowRunner`** — class holding a `StepExecutor`. `run(session, task_id)`: enforces status guards, resolves the definition by the name/version recorded in the snapshot, loops steps respecting `max_iterations`/`max_attempts` (per the Iteration/Retry invariant in §5), persists status/`retry_count`/snapshot transitions, logs start/step/end/error, returns `WorkflowRunResult`. **Architectural invariant (approved amendment 8): `WorkflowRunner` has zero knowledge of any concrete Capability. It interacts with steps exclusively through the `StepExecutor` interface. No `if step.capability == "..."` branching, no `match capability: case ...`, and no other capability-name dispatch of any kind may appear in `WorkflowRunner`.**
- **`StepExecutor` Protocol** — one async method executing a single step and returning an outcome. Phase 5 ships exactly one deterministic, non-AI placeholder implementation, injectable for tests; this is the seam future Capability implementations plug into.
- **Error hierarchy** (amended to support `get_task()`):
  ```
  WorkflowConfigError
      UnknownWorkflowTypeError
      DuplicateWorkflowRegistrationError
  TaskNotFoundError                 # shared: raised by both WorkflowService.get_task() and WorkflowRunner.run()
  WorkflowServiceError
      NewsEventNotFoundError
      DuplicateActiveTaskError
  WorkflowRunnerError
      TaskAlreadyRunningError
      TaskAlreadyCompletedError
      MaxIterationsExceededError
      StepTimeoutError
      StepExecutionError            # retryable
      PermanentStepFailureError     # not retryable
  ```
  No bare `except Exception` without logged context anywhere.
- **Pydantic schemas** — `WorkflowType`, `WorkflowRetryPolicy`, `WorkflowStepDefinition`, `WorkflowDefinition`, `WorkflowExecutionState`, `WorkflowStepResult` (now including `started_at`/`finished_at`), `WorkflowRunResult`, `EditorialTaskCreate`, `EditorialTaskRead` — the latter two reuse `TaskPriority`/`TaskStatus` from `database.models.editorial_task`, following the `schemas/source_import.py` precedent.
- **Database boundaries** — only `WorkflowService` and `WorkflowRunner` touch `AsyncSession`/`EditorialTask` directly; `WorkflowRegistry` never touches the database; ORM rows never cross a module boundary — callers only ever receive the Pydantic schemas above.

---

## 8. Proposed file tree (amended — no `daily_digest.py` in Phase 5)

**New files only — nothing existing changes:**
```
workflows/
    __init__.py
    definitions/
        __init__.py
        news_analysis.py
        content_generation.py
    registry.py
    runner.py
    errors.py

schemas/
    workflow.py
    editorial_task.py

services/
    workflow_service.py

tests/
    test_workflow_registry.py
    test_workflow_service.py
    test_workflow_runner.py
    test_editorial_task_db_integration.py
```

**Changed files: none.** `services/collector.py`, everything under `integrations/sources/`, `database/models/*.py`, `database/migrations/*`, `services/adapter_registry.py`, `services/source_registry.py`, and all existing tests remain untouched.

---

## 9. State machine (amended — WAITING removed from Phase 5 transitions)

**Allowed transitions in Phase 5**
```
CREATED  -> RUNNING     Runner.run() starts on a fresh task
RUNNING  -> COMPLETED   all steps succeeded
RUNNING  -> FAILED      permanent step error, step max_attempts exhausted, or max_iterations exceeded
```

`WAITING` remains a valid value of the `TaskStatus` enum **solely for compatibility with the existing database schema** — removing it would require a migration, which is forbidden. In Phase 5, **no code path ever produces a `RUNNING → WAITING` or `WAITING → RUNNING` transition.** Those two transitions do not exist in this phase's Runner, full stop — not "unused," but structurally absent from the transition logic.

**Forbidden transitions and rerun behaviour**
```
CREATED             -> COMPLETED / FAILED   directly, skipping RUNNING       -- not permitted; Runner is the only path in
RUNNING             -> RUNNING (double-start)                               -- raises TaskAlreadyRunningError, zero DB mutation
COMPLETED / FAILED  -> RUNNING (rerun call)                                  -- raises TaskAlreadyCompletedError, zero DB mutation
FAILED              -> RUNNING (implicit automatic retry)                    -- never automatic; re-processing means creating a
                                                                                 new EditorialTask, a policy decision Phase 5
                                                                                 does not make on its own
any state           -> WAITING / WAITING -> any state                        -- does not occur anywhere in Phase 5
```
Every rerun-guard exception is raised **before** any write — a rejected rerun never touches the row.

---

## 10. Test plan

**Unit** (no database): `WorkflowRegistry` (register / duplicate / unknown / immutability of returned definitions / confirming `DAILY_DIGEST` is absent and raises `UnknownWorkflowTypeError`); Pydantic schema boundary validation (empty `steps`, out-of-range `max_attempts`, invalid `retryable_error_types`, integer `version`); error-hierarchy identity checks; `WorkflowRunner`'s step-sequencing logic driven by an injected fake `StepExecutor`, confirming it never branches on `capability` name; a dedicated test asserting `iteration_count` and `retry_count`/step-attempt tracking never cross-increment each other (the Iteration/Retry invariant).

**Integration** (real `AsyncSession`, single-call scope): `WorkflowService.create_task()` and `get_task()` against a real `NewsEvent` row — duplicate-active-task rejection keyed on `(event_id, workflow_type)`, missing-event rejection, `TaskNotFoundError` from `get_task()`, exact shape of the initial JSON snapshot (integer version, empty `step_results`), confirmation that `create_task()`/`get_task()` never write a `status` transition.

**Real test-PostgreSQL** (full Service→Runner cycle, end to end): status genuinely transitions CREATED→RUNNING→COMPLETED/FAILED in the database (verified via direct SQL); `retry_count` genuinely increments across a retried step while `iteration_count` in the JSON does not; `started_at`/`finished_at` are genuinely populated per step; `workflow` JSON genuinely round-trips through Postgres; a mid-run error genuinely rolls back rather than leaving a half-updated row; a rerun on a COMPLETED task is verified via SQL to have made zero changes.

**Regression**: the full existing 88-test suite passes unmodified; a diff check confirms `services/collector.py`, `services/source_registry.py`, `services/adapter_registry.py`, and everything under `integrations/sources/` and `database/` is untouched; `ruff`/`mypy` clean on every new file.

---

## 11. Runtime validation plan

Using a **real** `NewsEvent` already present in Postgres from Phase 4 and a **real** `EditorialTask`, no AI call anywhere:

1. `WorkflowService.create_task(session, event_id=<real id>, workflow_type=NEWS_ANALYSIS, priority=B)` → verify the inserted row directly via SQL (`status='CREATED'`, `workflow` populated, `workflow_version` stored as an integer).
2. `WorkflowRunner.run(session, task_id)` → verify the `status` transition via direct SQL before and after the call, and verify `started_at`/`finished_at` are present per step in the stored JSON.
3. Re-run `WorkflowRunner.run()` on the now-terminal task → confirm `TaskAlreadyCompletedError` is raised and confirm via SQL that zero columns changed.
4. Attempt `WorkflowService.create_task(..., workflow_type=DAILY_DIGEST, ...)` → confirm `UnknownWorkflowTypeError` is raised (proves `DAILY_DIGEST` is genuinely not registered).
5. Full `pytest` run → confirm no regression against the 88 existing tests.

The placeholder `StepExecutor` is deterministic and synchronous throughout — no network call, no provider SDK, no `services/llm_gateway.py` (which doesn't exist yet) is invoked at any point.

---

## 12. Open questions

All previously open design questions are now resolved by this approval, **except one**, which was not addressed in the approval and remains open:

- **Test database strategy** — this project has zero tests touching real Postgres today. Recommended (carried over, not yet explicitly confirmed): a pytest fixture wrapping each DB test in a transaction rolled back at teardown, run against the existing dev Postgres. Proceeding with this default during implementation since it was the standing recommendation and the overall architecture has been approved, but flagging explicitly that this specific point was not itself checked off — please say so if a different approach (e.g., a dedicated test database) is preferred.

Resolved by this approval (no longer open):
- `DAILY_DIGEST` → not registered in Phase 5 (amendment 1).
- `StepExecutor` → stays a Protocol (confirmed).
- `WAITING` → unused in Phase 5, and now structurally absent from the transition logic, not merely dormant (amendment 2, stricter than the prior draft).
- Backoff → logged only, no `asyncio.sleep()` (confirmed).
- Active-task uniqueness → `(event_id, workflow_type)` (confirmed).
- Iteration vs. retry → formally independent invariants (amendment 3).
- `WorkflowExecutionState` step entries → include `started_at`/`finished_at` (amendment 4).
- `WorkflowDefinition.version` → integer, not string (amendment 5).
- `WorkflowRetryPolicy` → gains `retry_delay_seconds` (amendment 6, replacing the earlier `backoff_seconds` name).
- `WorkflowRegistry` → immutable, no dynamic registration (amendment 7).
- `WorkflowRunner` → no capability-name branching, `StepExecutor`-only (amendment 8).
- `WorkflowService` → scoped to `create_task()`/`get_task()` only; never transitions status (amendment 9).

---

## Canonical rules (Phase 5) — approved

| Rule | Value |
|---|---|
| Registered workflow types | `NEWS_ANALYSIS`, `CONTENT_GENERATION` only |
| `DAILY_DIGEST` | Not registered in Phase 5; deferred to a future Digest Engine phase as a complete `WorkflowDefinition` |
| `WorkflowDefinition.version` | Integer (e.g. `1`), not a string |
| `WorkflowDefinition.max_iterations` default | **3** |
| `WorkflowStepDefinition.max_attempts` default | **3** |
| `WorkflowRetryPolicy.retry_delay_seconds` | Present as a real field; defaults to `0` in Phase 5 |
| Priority-dependent retry budgets (S/A/B/C) | Not implemented in Phase 5 |
| Iteration vs. retry | Fully independent counters; a retry never increments `iteration_count`, an iteration is never a step retry |
| `EditorialTask.retry_count` semantics | Incremented once per step retry (attempt > 1); independent of the JSON snapshot's `iteration_count` |
| `WorkflowExecutionState` step entries | Include `started_at` and `finished_at` per step |
| `WAITING` state | Kept in the enum for schema compatibility only; no transition into or out of it exists in Phase 5 |
| Retry backoff | Logged only; no real `asyncio.sleep()` |
| `StepExecutor` | Injectable Protocol; one deterministic, non-AI default implementation shipped |
| `WorkflowRegistry` | Immutable after construction; no dynamic registration at runtime |
| `WorkflowRunner` | No knowledge of concrete Capabilities; interacts only through `StepExecutor`; no capability-name branching |
| `WorkflowService` scope | `create_task()` and `get_task()` only; never transitions task status itself |
| Active-task uniqueness | `(event_id, workflow_type)` |
| Test database approach | pytest fixture, transactional rollback, against existing dev Postgres (not explicitly re-confirmed in this approval — see §12) |
| Document-priority stance | CLAUDE.md governs conflict resolution; docs/13_1 §14's self-ranking applies to product content, not to overriding this |

**Architecture approved. Proceeding to Phase 5 implementation** under this specification. Forbidden during implementation: changing the database, changing `EditorialTask`, changing the Collector, changing the Source Registry, changing the Adapter Registry, changing the architecture of any previous phase, starting Phase 6.
