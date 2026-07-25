# Phase 13 — Automatic News Analysis Architecture Contract

## 1. Status / Authority

**Status: frozen amendment specification, pending adversarial audit.** This document converts
`docs/phase13_automatic_news_analysis_decision_resolution.md` ("Decision Resolution") into binding
implementation form. No production code, test, or migration was modified to produce this document.
Every implementation-fact claim was independently re-verified against current source this session
(cited file:line where practical), including facts already verified in Discovery/Decision
Resolution — not merely copied forward.

**Source-of-truth order**: this Contract (once approved) > Decision Resolution (the approved
product/architecture decisions this Contract codifies, never reinterprets) >
`docs/phase13_automatic_news_analysis_discovery.md` (shared evidence) > frozen Phase 5–12 contracts,
all of which remain in force, unamended except where §11/§26/§27 below narrowly, explicitly amend
`workflows/runner.py`.

Every statement is tagged **FACT** (re-verified source evidence), **DECISION** (frozen, binding
choice, inherited from Decision Resolution), **INFERENCE** (reasoned conclusion), or
**RECOMMENDATION** (non-binding).

## 2. Purpose

**DECISION**: Phase 13 safely automates execution of eligible `EditorialTask(NEWS_ANALYSIS,
CREATED)` tasks — closing the gap Phase 12 deliberately left open. It introduces:
`EngagementCapability` (the one missing workflow step, Discovery §6), a genuinely atomic task-claim
mechanism (closing a Phase 5-era latent concurrency gap, Decision Resolution §4/§14), a dedicated
analysis worker process, and bounded, deterministic automatic execution. **It does not complete the
full editorial pipeline** — `CONTENT_GENERATION` remains manually triggered only, exactly as it is
today.

## 3. Exact Scope

**DECISION — IN SCOPE**:
- `EngagementCapability` implementation, its prompt, its `CapabilityDefinition`, and its
  registration in `capabilities/registry.py::build_registry()`.
- The narrow, atomic-claim fix to `workflows/runner.py::WorkflowRunner.run()`'s existing
  `CREATED → RUNNING` transition.
- A dedicated `NEWS_ANALYSIS` worker (`worker/analysis_main.py`, `worker/analysis_cycle.py`),
  separate OS process/Docker service from Phase 12's collection worker.
- Freshness-bounded eligibility (≤48h), batch cap (5), sequential execution, 300s poll interval.
- Deterministic failure semantics; stale-`RUNNING` observability (no auto-recovery).
- Mandatory automated tests; one human-authorized, tiny-sample manual live validation.

**DECISION — OUT OF SCOPE, binding**:
`CONTENT_GENERATION` triggering of any kind; `ContentDraft` creation; Telegram/public publishing;
Approve/Reject/Rework editorial actions; image/media persistence; the 5+ image-candidate
requirement; real (observed) Telegram engagement-metric persistence; `CostTracker`/`BudgetGuard`
cumulative-ledger remediation; a `max_daily_ai_cost`-style setting; automatic `FAILED`-task retry;
automatic stale-`RUNNING` recovery; historical-backlog drain beyond the freshness cutoff; any
migration.

## 4. Current Architecture

Every claim re-read directly this session:

| Component | Classification | Evidence |
|---|---|---|
| `workflows/definitions/news_analysis.py::DEFINITION` | **EXISTING, unchanged** | 4 steps: research, intelligence, engagement_analysis, scoring — registered, resolvable |
| `capabilities/research_capability.py`, `intelligence_capability.py`, `scoring_capability.py` | **EXISTING, unchanged** | Real, registered, tested capabilities |
| `capabilities/registry.py::build_registry()` | **EXISTING, narrow addition** (§9) | Registers exactly 5 capabilities today; gains a 6th |
| `workflows/runner.py::WorkflowRunner` | **EXISTING, narrow, targeted fix** (§10/§11) | Generic `StepExecutor`-based runner; its own `CREATED→RUNNING` transition is a plain read-then-write today |
| `capabilities/executor.py::CapabilityExecutor` | **EXISTING, unchanged** | The only `StepExecutor` implementation bridging to Capabilities |
| `scripts/run_content_generation.py::run_content_generation_for_event()` | **EXISTING, unchanged, reused as design template only** | The only production wiring of `WorkflowRunner`+`CapabilityExecutor`+`assemble_ai_integration_layer()` today |
| `services/triage_orchestrator.py` | **EXISTING, unchanged** | Creates `EditorialTask(NEWS_ANALYSIS, CREATED)`; the only production creator |
| `worker/main.py`, `worker/cycle.py` (Phase 12) | **EXISTING, unchanged** | Never references `NEWS_ANALYSIS`; frozen boundary confirmed intact |
| `services/freshness.py::compute_freshness()` | **EXISTING, unchanged, reused** | 6-tier freshness function; its last tier boundary (48h) is reused verbatim as this phase's eligibility cutoff |
| `integrations/llm_gateway/boot.py::assemble_ai_integration_layer()` | **EXISTING, unchanged, reused** | Constructs the real `RoutingGateway`/`CapabilityRegistry`; already wires `BudgetGuard.check()` into every dispatch |
| `services/cost_tracker.py::CostTracker.record()` | **EXISTING, confirmed never called in production** | Re-confirmed via grep this session — the spend ledger `BudgetGuard.check()` reads is never written to; not fixed by Phase 13 (§17) |
| A new `EngagementCapability` (`capabilities/engagement_capability.py`) | **NEW IN PHASE 13** | §6–§8 |
| A new analysis worker (`worker/analysis_main.py`, `worker/analysis_cycle.py`) | **NEW IN PHASE 13** | §12 |

## 5. NEWS_ANALYSIS Workflow

**DECISION, binding — order unchanged, re-verified correct, not reordered**:
`workflows/definitions/news_analysis.py:19-24`:

```python
steps=[
    WorkflowStepDefinition(name="research", capability="research", timeout_seconds=30),
    WorkflowStepDefinition(name="intelligence", capability="intelligence", timeout_seconds=30),
    WorkflowStepDefinition(name="engagement_analysis", capability="engagement", timeout_seconds=30),
    WorkflowStepDefinition(name="scoring", capability="scoring", timeout_seconds=30),
],
```

| Step name | Capability name (registry key) | Input dependency | Output dependency | Timeout | Failure propagation |
|---|---|---|---|---|---|
| `research` | `"research"` | `NewsEvent` (title/content/category) only | none upstream | 30s | Required step — failure (after 3 attempts) fails the whole task |
| `intelligence` | `"intelligence"` | `NewsEvent` + `step_results["research"]` | consumed by `engagement_analysis` (below) | 30s | Same |
| `engagement_analysis` | `"engagement"` | `NewsEvent` + `step_results["research"]` + `step_results["intelligence"]` (**NEW consumption, §6/§7**) | consumed by nothing downstream in Phase 13 (Scoring is not modified, §7) | 30s | Same |
| `scoring` | `"scoring"` | `NewsEvent` only (**unchanged — does not consume `engagement_analysis`'s output in Phase 13**) | none | 30s | Same |

**No reordering** — the step order is correct precisely because `EngagementCapability` needs both
prior steps' results, and `scoring` already functions independently of it (confirmed:
`ScoringCapability`'s current implementation has no code path reading `step_results["engagement_
analysis"]`, and is not modified by this Contract).

## 6. EngagementCapability

**DECISION, binding, semantics**: `EngagementCapability` computes **predicted editorial/audience
engagement potential**, inferred by the LLM from the event's own text plus Research's and
Intelligence's prior findings. **It is not, and its output schema/naming must never imply, a
measurement of real, observed engagement** (views, reactions, comments, forwards, channel reach).

**FACT, re-confirmed this session**: no real engagement signal of any kind is persisted or passed to
any Capability today — `NewsEventSnapshot` (`schemas/capability.py`, consumed via
`CapabilityExecutor._build_context()`, `capabilities/executor.py:117-125`) exposes only `id`,
`title`, `summary`, `content`, `url`, `category`, `published_at`. `EngagementCapability` therefore
**must not** claim access to actual views/reactions/comments/forwards/reach — none reach it, by
construction, not merely by convention.

**Naming, frozen unchanged**: the workflow step name `"engagement_analysis"` and the capability
registry key `"engagement"` (`workflows/definitions/news_analysis.py:22`,
`capabilities/capability_mapping.py:26`) are **not renamed** — both are already-frozen identifiers;
no evidence requires touching them. The new Python class is named `EngagementCapability`
(`capabilities/engagement_capability.py`), matching the existing per-capability naming convention
(`IntelligenceCapability`, `ScoringCapability`, etc.).

## 7. Input / Output Contract

**DECISION, binding — required inputs** (all reachable via the existing, unmodified `CapabilityContext`
mechanism, zero schema change):
- `context.business.news_event.title`, `.content`, `.category` — **required**.
- `context.business.workflow_state.step_results["research"]` — **required to attempt reading**, but
  **must degrade gracefully** if absent/empty (mirrors `IntelligenceCapability._format_research_
  facts()`'s own existing "Research did not run" fallback text, `capabilities/
  intelligence_capability.py:84-90` — never raises merely for a missing upstream result).
- `context.business.workflow_state.step_results["intelligence"]` — same required-to-attempt,
  graceful-degradation treatment.

**Optional inputs**: none. `context.business.news_event.summary`, `.url`, `.published_at` are
available but not required by this Contract's frozen prompt design (§8) — Planning may reference
`published_at` for freshness framing in the prompt text itself if useful, but it is not a required
field for `execute()` to function.

**DECISION, binding — output contract**, mirroring `IntelligenceCapability`'s established 4-field
shape in size and structure:

```json
{
  "engagement_potential_score": 0.0-1.0 (number, required),
  "audience_fit": "string, required, short (e.g. one phrase/sentence)",
  "reasoning": "string, required, concise (1-3 sentences)"
}
```

- **`engagement_potential_score`**: a bounded `number` in `[0.0, 1.0]`, chosen (not `integer`) to
  match `ScoringCapability`'s/`Freshness`'s own existing convention of expressing normalized signals
  as floats in this exact range (e.g. `FreshnessResult.weight`, Triage's `combined_score`) — the
  field name's own `_potential_` infix makes the predicted-not-observed distinction unambiguous at
  the schema level, not merely in prose.
- **`audience_fit`**: free-text `string`, not an enum — matches `IntelligenceCapability`'s own
  `audience_relevance` field's free-text shape; inventing a fixed taxonomy is unnecessary complexity
  this Contract explicitly declines to add.
- **`reasoning`**: free-text `string`, matching every existing capability's pattern of never
  returning a bare score without an auditable rationale (Triage's `explanation` dict,
  `IntelligenceCapability.recommendation`).

**`CapabilityDefinition`** (mirrors `INTELLIGENCE_CAPABILITY_DEFINITION`'s exact shape,
`capabilities/intelligence_capability.py:38-44`):

```python
ENGAGEMENT_CAPABILITY_DEFINITION = CapabilityDefinition(
    name="engagement",
    version=1,
    config=CapabilityConfig(timeout_seconds=30),
    required_context=["news_event"],
    expected_output_keys=["engagement_potential_score", "audience_fit", "reasoning"],
)
```

## 8. Prompt Contract

**DECISION, binding**:
- **Path**: `prompts/engagement/v1.yaml` — a genuinely new capability; no pre-existing version
  predates the OpenAI Structured Outputs strict-mode remediation, so it launches directly compliant
  (no v1→v2 migration dance).
- **`PROMPT_VERSION = "1"`** constant in `capabilities/engagement_capability.py`, matching every
  other capability's own naming (`capabilities/intelligence_capability.py:36`'s
  `PROMPT_VERSION = "2"` pattern, applied at this capability's own version 1 since it has no prior
  version).
- **`output_schema`**: must set `"additionalProperties": false` and mark all three fields (§7)
  `required`, matching `prompts/intelligence/v2.yaml`'s own already-remediated shape exactly — no
  regression of the cross-phase strict-schema rule is authorized.
- **Prompt immutability**: once `v1.yaml` is committed, it is never edited in place — any future
  semantic change creates `v2.yaml`, per Phase 6 §8's existing, unmodified rule.

## 9. Registry Integration

**DECISION, binding**: `capabilities/registry.py::build_registry()` gains exactly one new
registration line:

```python
registry.register(ENGAGEMENT_CAPABILITY_DEFINITION, EngagementCapability(gateway, prompt_repository))
```

added alongside the existing 5 (`capabilities/registry.py:135-139`), constructed with the same
`(gateway, prompt_repository)` two-argument shape every other capability already uses (no
`BudgetGuard`/`ToolRegistry` injection — matches Amendment C's existing, unmodified rule that no
Capability ever holds `BudgetGuard` directly). `CapabilityRegistry.resolve("engagement")` — the
**exact registry key**, re-confirmed via `workflows/definitions/news_analysis.py:22`'s
`capability="engagement"` (not `"engagement_analysis"`, which is the *step* name, a distinct string
— this distinction is easy to conflate and is frozen explicitly here to prevent a Planning-stage
error) — will resolve successfully once this line exists; today it raises `UnknownCapabilityError`
(Discovery §6, re-confirmed unchanged this session). **No other `CapabilityRegistry`/`build_registry()`
change is authorized** — the 5 existing registrations are untouched.

## 10. Atomic Claim

**DECISION, binding — the core invariant of this Contract.** Re-read `workflows/runner.py:111-123`
directly, unchanged since Phase 5: the current `CREATED → RUNNING` transition is `task =
await session.get(EditorialTask, task_id)` → `if task.status == TaskStatus.RUNNING: raise ...` →
`task.status = TaskStatus.RUNNING` → `await session.commit()` — a plain read-then-write, **not**
atomic under concurrency.

**Frozen fix**: replace this with a single atomic conditional `UPDATE`, mirroring
`services/triage_orchestrator.py::_claim_new_event()`'s own already-proven pattern
(`services/triage_orchestrator.py:62-67`) exactly:

```python
result = await session.execute(
    update(EditorialTask)
    .where(EditorialTask.id == task_id, EditorialTask.status == TaskStatus.CREATED)
    .values(status=TaskStatus.RUNNING, updated_at=now)
)
await session.commit()
claimed = result.rowcount == 1
```

**If `claimed` is `False`** (0 rows affected — another caller already claimed, completed, or failed
this task): `run()` re-reads the task's current status (a plain `session.get()`, safe now that no
ownership decision depends on it) and raises **the same, already-existing exception** the caller
already handles — `TaskAlreadyRunningError` if the current status is `RUNNING`,
`TaskAlreadyCompletedError` if `COMPLETED`/`FAILED`. **No new exception type is introduced.** This is
a narrow, backward-compatible correctness fix: `run()`'s own already-documented contract (*"raises
`TaskAlreadyRunningError`/`TaskAlreadyCompletedError` for misuse"*) becomes actually true under
concurrency, which it is not today — callers observe no behavioral change beyond correctness.

**Does not rely on a single-worker assumption** — proven by construction: the `UPDATE ... WHERE
status = 'CREATED'` statement is safe under arbitrarily many concurrent callers, by the same
database-level guarantee Triage's own identical pattern already relies on.

## 11. WorkflowRunner State Semantics

**DECISION, binding**: the atomic claim (§10) **is** `run()`'s own internal transition — there is no
separate, external pre-claim step, and no external code ever sets `EditorialTask.status` outside
`WorkflowRunner.run()` (this remains true, unmodified — `run()`'s own docstring already states
*"Only WorkflowRunner ever changes an EditorialTask's status"*). This avoids by construction the
double-transition/race-window problem a separate external claim would introduce: there is exactly
**one** place `status` ever leaves `CREATED`, and it is now atomic.

**State machine, frozen**:

| Task status when `run()` is called | Behavior |
|---|---|
| `CREATED` | Atomic claim attempted (§10). On success, proceeds to execute steps. |
| `RUNNING` | Atomic claim affects 0 rows → `TaskAlreadyRunningError` raised, caller skips (§11 below). |
| `COMPLETED` | Atomic claim affects 0 rows (status filter excludes it) → `TaskAlreadyCompletedError` raised. |
| `FAILED` | Same as `COMPLETED` — `TaskAlreadyCompletedError` raised (existing exception already covers both terminal states, `workflows/errors.py:55-56`). |

**No implementation is authorized to add a new task-status value or a separate ownership/lease
column** — the existing four-value `TaskStatus` enum (`CREATED`, `RUNNING`, `COMPLETED`, `FAILED`,
`WAITING` unused by this workflow) is sufficient and unmodified.

## 12. Analysis Worker

**DECISION, binding**: a dedicated worker, **not merged into Phase 12's collection worker**, for the
reasons Decision Resolution §3 already established (materially different cost/latency/failure/
scaling profile) — re-affirmed, not re-litigated here.

**Exact files** (new): `worker/analysis_main.py` (entry point, mirrors `worker/main.py`'s shape
exactly — `setup_logging()`, signal-handler wiring with the same `NotImplementedError` guard,
enabled-loop/disabled-idle branch), `worker/analysis_cycle.py` (one-cycle orchestration: query
eligible tasks, execute up to `news_analysis_batch_size` sequentially, log a structured summary —
mirrors `worker/cycle.py`'s shape). **Same `worker/` package** — no new top-level package (Decision
Resolution §3/§21's own resolution, reused verbatim).

**Composition, reusing existing assembly, zero duplication** (§28 below, Decision Resolution's own
directive): `worker/analysis_main.py` constructs the real AI integration layer exactly as
`scripts/run_content_generation.py:93-97` already does —

```python
prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
ai_layer = assemble_ai_integration_layer(settings, prompt_repository)
capability_registry = ai_layer.capability_registry
```

— constructed once at worker startup (not per-cycle, not per-task), then reused across every cycle
and every claimed task. `WorkflowRunner(CapabilityExecutor(session, task_id, capability_registry))`
is constructed fresh per claimed task (mirroring `scripts/run_content_generation.py:104-105`'s own
per-task construction exactly), inside the transaction that claims it (§24).

## 13. Eligibility / Freshness

**DECISION, binding — exact eligibility query**:

```python
select(EditorialTask.id)
.join(NewsEvent, EditorialTask.event_id == NewsEvent.id)
.where(
    EditorialTask.status == TaskStatus.CREATED,
)
```
filtered in Python (or via a computed freshness predicate, Planning's discretion — see §26) to only
those whose `NewsEvent` freshness age (via `compute_freshness(published_at, collected_at,
reference_now)`, the exact existing function, unmodified) is `<= news_analysis_freshness_cutoff_
hours` (48.0 default) — **then further filtered to `workflow.get("workflow_name") ==
"NEWS_ANALYSIS"`**, since `EditorialTask.status == CREATED` alone is not workflow-type-specific
(mirroring `_find_active_task()`'s own existing JSON-field-matching pattern, `services/
workflow_service.py:97-105`, since `EditorialTask` has no dedicated `workflow_type` column).

**Deterministic ordering, frozen**: `ORDER BY EditorialTask.created_at ASC, EditorialTask.id ASC`
(oldest-eligible-first, stable tie-break) — processes the *most stale-but-still-eligible* items
first within the 48h window, a reasonable, evidence-neutral default (no product signal favors
newest-first instead).

**`LIMIT news_analysis_batch_size`** (5, §14).

**Null/missing timestamp behavior, frozen explicitly, not left to Planning**: `compute_freshness()`
already, unconditionally falls back to `NewsEvent.collected_at` (never null for a persisted row) when
`published_at` is null (`services/freshness.py:62-64`, existing, unmodified) — this eligibility
query relies on that same existing fallback, introducing no new null-handling logic. A `NewsEvent`
with `published_at IS NULL` is therefore still evaluated for freshness (via `collected_at`), never
excluded or included by a separate rule.

## 14. Batch / Cadence

**DECISION, binding**: `news_analysis_batch_size = 5`, **sequential execution only** — one task's
`run()` call completes (`COMPLETED`, `FAILED`, or a skipped-claim exception) before the next begins.
**No concurrent/parallel task execution is authorized in Phase 13.**

**DECISION, binding**: `news_analysis_poll_interval_seconds = 300` (5 minutes) — deliberately
**not** coupled to Phase 12's `news_collection_interval_seconds` (1800s); analysis should not wait up
to 30 minutes after Triage creates a task. Cycle shape, mirroring Phase 12's own proven structure
exactly:

```
while True:
    try:
        await run_analysis_cycle()   # claim ≤5 eligible tasks, execute sequentially
    except Exception:
        logger.exception(...)
    await asyncio.sleep(settings.news_analysis_poll_interval_seconds)
```

Cadence is **cycle duration + interval** (not wall-clock-fixed) — identical semantics to Phase 12's
own disclosed, accepted model (`docs/phase12_fresh_news_automation_architecture_contract.md`'s own
Risk register entry, reused unmodified here).

## 15. Failure / Retry

**DECISION, binding**, reusing existing, unmodified mechanics throughout — no new error-handling
code beyond `EngagementCapability`'s own floor-validation (mirroring `_floor_validate`,
`capabilities/intelligence_capability.py:56-81`, duplicated per that module's own established,
intentional-non-shared-helper convention):

| Cause | Mechanism (unmodified) | Resulting task state |
|---|---|---|
| Capability validation/malformed-output failure | `ValidationCapabilityError` → `PermanentStepFailureError` → `_fail()` | `FAILED` |
| Provider failure (fallback exhausted) | `RetryableCapabilityError`/`CapabilityTimeoutError` → `StepExecutionError`, retried to `max_attempts` (3), then `_fail()` | `FAILED` |
| Step timeout (30s) | `StepTimeoutError`, treated as `StepExecutionError` | Retried, then `FAILED` if exhausted |
| Task claim lost (race) | Atomic claim affects 0 rows (§10) → `TaskAlreadyRunningError`/`TaskAlreadyCompletedError` | Unchanged (owned by winner); worker catches and skips, **not an error** |
| Worker cycle exception (e.g. DB unavailable) | `except Exception` in `worker/analysis_main.py`'s loop (§14) | Logged, cycle proceeds to next interval; no task corrupted |
| Process cancellation (`SIGTERM`/`SIGINT`) | Reuses Phase 12's exact `asyncio.CancelledError` propagation pattern (`except Exception` only, never `BaseException`/bare `except`) | In-flight task's own commit boundary (§24) determines whether it's left `RUNNING` (stale, §16) or already `COMPLETED`/`FAILED` |

**No silent infinite retry, no retry storm** — bounded by the same existing `max_attempts=3`
(step-level) and `max_iterations=3` (workflow-level) ceilings already frozen in
`news_analysis.py`'s `DEFINITION`, unmodified. **No task-level automatic retry of `FAILED` tasks in
Phase 13** — a `FAILED` task requires deliberate, future, out-of-scope intervention to re-attempt.

## 16. Stale RUNNING

**DECISION, binding**: **no automatic reclaim/recovery in Phase 13.** If a worker process crashes
after successfully claiming a task (§10) but before it reaches `COMPLETED`/`FAILED`, that task
remains `RUNNING` indefinitely — any future `run()` call on it raises `TaskAlreadyRunningError`
(correctly, since ownership cannot be distinguished from "still legitimately in progress" without a
lease/heartbeat mechanism this Contract explicitly declines to build, per Decision Resolution §5).

**Required, frozen**:
- **Monitoring query** (documented, not scripted — an operator runs this manually):
  ```sql
  SELECT id, event_id, updated_at FROM editorial_tasks
  WHERE status = 'RUNNING' AND updated_at < now() - interval '1 hour';
  ```
- **Manual recovery procedure**: a human confirms the owning process is genuinely dead (not merely
  slow), then directly executes `UPDATE editorial_tasks SET status = 'CREATED' WHERE id = :id` —
  this is an **operator action**, not Phase 13 code.
- **Explicitly accepted, temporary operational debt** — the same pattern Phase 12 already accepted
  for `NEWS_ANALYSIS(CREATED)` buildup, one level deeper in the pipeline. A future phase may port
  Triage's own `_select_recovery_candidates()`/`_acquire_recovery_ownership()` pattern
  (`services/triage_orchestrator.py:70-138`) if this becomes operationally necessary — not
  pre-designed here.

## 17. Cost Containment

**DECISION, binding — the truth, frozen verbatim, not softened**: `BudgetGuard.check()`
(`integrations/llm_gateway/fallback/policy.py:275`) genuinely, automatically runs before every real
dispatch attempt Phase 13's capability calls make, via the unmodified `RoutingGateway`/
`FallbackPolicy` — **but `CostTracker.record()` is never called anywhere in production**
(re-confirmed this session: zero non-test call sites in `integrations/llm_gateway/`, `services/`,
`capabilities/`; explicitly documented as deliberate in `integrations/llm_gateway/boot.py:126-129`
and `integrations/llm_gateway/gateway.py:12-14`). **The Redis-backed spend ledger `BudgetGuard.
check()` reads is therefore never populated, and `settings.max_daily_ai_cost` is not proven
functional as a cumulative-spend cap.** Phase 13 **must not** claim, imply, or document a real
daily-dollar cap.

**DECISION, binding**: Phase 13 does **not** introduce `max_daily_ai_cost` or any new monetary-cap
setting (Decision Resolution §8, Decision B). Phase 13 does **not** modify
`RoutingGateway`/`FallbackPolicy`/`CostTracker`/`BudgetGuard` to fix the ledger gap (Decision
Resolution §8, Decision A) — that is explicitly deferred to a separate, later, governed remediation,
named here so a future phase does not have to rediscover it, not designed further.

**Phase 13's actual, binding cost exposure bound is entirely deterministic and workload-based**:

- 48-hour freshness cutoff (§13/§18);
- maximum 5 tasks claimed per cycle (§14);
- sequential execution only (§14);
- 300-second poll interval (§14);
- no historical-backlog drain (§18);
- no automatic `FAILED`-task retry (§15);
- no `CONTENT_GENERATION` chaining (§19).

**These bound workload (task/call count), never spend (dollars)** — this distinction must not be
blurred anywhere this Contract or its Implementation Plan is referenced. Existing provider-level
safeguards (`RateLimiter`, `ProviderHealthStore`, `FallbackPolicy`'s own candidate-exhaustion logic)
remain unchanged and continue to apply automatically, independent of the ledger gap.

## 18. Backlog Policy

**DECISION, binding**: of the currently-existing ~4723 `CREATED` `NEWS_ANALYSIS` tasks (re-queryable,
read-only, at Contract-writing time — not re-counted here to avoid staleness; Planning/Implementation
must re-verify the live count before enabling automation), only those whose linked `NewsEvent` is
within the 48-hour freshness window (§13) at claim time are ever eligible. **The bulk of the
historical backlog will never become eligible as time passes and remains `CREATED` forever unless a
future, separately-authorized phase adds backfill/recovery.** No deletion, no archival, no mass
status mutation, no historical drain of any kind is authorized by this Contract. This is named
explicitly as accepted debt (Decision Resolution §6), consistent with how Phase 12 itself already
named the `NEWS_ANALYSIS(CREATED)` buildup as accepted debt one phase earlier.

## 19. CONTENT_GENERATION Boundary

**DECISION, binding, restated exactly**: successful `NEWS_ANALYSIS` completion **MUST NOT** call
`run_content_generation_for_event()`, create a `WorkflowType.CONTENT_GENERATION` `EditorialTask`, or
create a `ContentDraft`, anywhere in Phase 13's own code. **FACT, re-confirmed this session**:
`worker/analysis_main.py`/`worker/analysis_cycle.py` (as designed, §12) import neither
`scripts.run_content_generation` nor construct any `EditorialTaskCreate(workflow_type=WorkflowType.
CONTENT_GENERATION, ...)` — mechanically enforceable the same way Phase 12's own AST import-boundary
test proved its own boundary (§28). A future, separately-governed phase must resolve: analysis
result → selection/threshold → `CONTENT_GENERATION` trigger. That bridge is not pre-implemented,
stubbed, partially wired, or hinted at in code anywhere in this Contract's authorized scope.

## 20. Real Engagement Metrics Deferral

**DECISION, binding**: no migration; no persistence of `views`/`forwards`/`replies`/`reactions` or
any other observed engagement signal in Phase 13. `EngagementCapability`'s output remains 100%
predicted/estimated (§6/§7). A future, separately-evidenced increment may add
`NewsEvent.telegram_views`/`.telegram_forwards`/`.telegram_reply_count` (nullable, Telegram-only) and
extend `integrations/sources/telegram_source.py::_to_raw_item()` to populate them — named here only
so the future phase does not have to rediscover that the raw Telethon data is genuinely available
(Discovery §7's own finding); no schema is designed further here.

## 21. Image Requirement Deferral

**DECISION/FINDING, restated exactly**: the product's binding future requirement — each final
editorial news item must eventually offer at least 5 relevant image candidates — is recorded but
**not implemented, not designed, and not attached to any pipeline point** by this Contract. Per
Discovery §14's own finding, the logical future attachment point is after/alongside
`CONTENT_GENERATION` (an asset-assembly concern, not an analysis concern), which is itself still
manual and out of Phase 13's own scope (§19). No media architecture, no new persistence field, no
adapter change is authorized here.

## 22. Configuration

**DECISION, binding — exactly four new `Settings` fields** (`core/config.py`), naming derived from
the exact convention Phase 12's own two fields already established:

```python
news_analysis_enabled: bool = False
news_analysis_poll_interval_seconds: int = Field(default=300, gt=0)
news_analysis_batch_size: int = Field(default=5, gt=0)
news_analysis_freshness_cutoff_hours: float = Field(default=48.0, gt=0)
```

**`news_analysis_enabled` defaults `False`** — matching `news_collection_enabled`'s own established,
repeated opt-in-by-default convention for exactly this risk profile (real AI cost, real external
provider calls). **`max_daily_ai_cost` is explicitly NOT added or referenced** (§17, Decision
Resolution §8 Decision B) — it remains the existing, untouched, pre-Phase-13 field, unreferenced by
any Phase 13 code path.

## 23. Runtime / Docker

**DECISION, binding**: add exactly one new service to `docker-compose.yml`:

```yaml
news_analysis_worker:
  build: .
  container_name: ai_newsroom_news_analysis_worker
  restart: unless-stopped
  env_file: .env
  environment:
    POSTGRES_HOST: postgres
    REDIS_HOST: redis
  command: ["python", "-m", "worker.analysis_main"]
  depends_on:
    postgres:
      condition: service_healthy
    redis:
      condition: service_healthy
```

**Dependencies re-derived from the actual runtime path, not copied from Phase 12's collection
worker** (which correctly excludes Redis, since it never touches the AI integration layer): this
worker's real path — `assemble_ai_integration_layer()` — constructs `RedisProviderHealthStore`,
`RedisLatencyTracker`, `RedisRateLimiter`, `RedisCacheStore`, and `RedisBudgetGuard`
(`integrations/llm_gateway/boot.py:179-186`, re-confirmed this session) — **Redis is genuinely
required**, unlike Phase 12's `automation_worker`. `restart: unless-stopped` matches every existing
service. No public port (this worker exposes no server). **Disabled behavior**: reuse Phase 12's
exact, already-tested idle-while-alive pattern (`asyncio.Event().wait()`, log once, cancellation-
responsive, zero DB/AI access while disabled) — proven correct, not reinvented. **Graceful
shutdown**: reuse the exact `SIGTERM`/`SIGINT` + `NotImplementedError`-guarded signal-handling
pattern from `worker/main.py`, unmodified in shape.

## 24. Transaction Semantics

**DECISION, binding — critical, explicitly resolved, not left to Planning.** Re-traced
`workflows/runner.py`'s existing, unmodified commit discipline directly: after the (now-atomic)
`CREATED → RUNNING` transition, `run()` **immediately commits** (`await session.commit()`,
`workflows/runner.py:123`, unchanged) — this ends the claiming transaction and releases any row-level
lock the `UPDATE` briefly held, **before** `_execute_steps()` (which makes the LLM calls) even
begins. Each subsequent step's outcome is committed separately, immediately after that step
completes (Phase 9.5's existing per-step persistence discipline, `workflows/runner.py:196-199`,
unmodified) — **no transaction is ever held open across an LLM call**, in the current architecture or
after this Contract's narrow fix. This Contract's atomic-claim change (§10) preserves this exact
discipline unmodified — it only changes *how* the `CREATED → RUNNING` write is issued (a single
atomic `UPDATE` instead of read-then-write), not *when* it commits relative to step execution.
**No new transaction-boundary design is required or authorized.**

## 25. Workflow Composition

**DECISION, binding**: `worker/analysis_main.py` constructs `assemble_ai_integration_layer(settings,
FilePromptRepository(prompts_root))` **once**, at worker startup (not per-cycle, not per-task) —
mirroring the exact, already-proven construction Phase 10 established in `scripts/
run_content_generation.py:93-97`, reused verbatim, not duplicated or reimplemented.
`worker/analysis_cycle.py` receives the resulting `CapabilityRegistry` as a parameter and constructs
a fresh `CapabilityExecutor(session, task_id, capability_registry)` + `WorkflowRunner(executor)` per
claimed task, exactly matching `scripts/run_content_generation.py:104-105`'s own per-task
construction shape. **No new boot-sequence function, no new assembly logic, no duplication of Phase
10's boot wiring is authorized.**

## 26. Authorized File Scope

**DECISION, binding — exhaustive.**

**Existing files authorized for narrow edit**:
- `workflows/runner.py` — **the one frozen-phase amendment this Contract authorizes**: replace
  `WorkflowRunner.run()`'s existing `CREATED → RUNNING` read-then-write (lines 111-123) with the
  atomic conditional `UPDATE` (§10). **No other line of this file may change** — `_execute_steps()`,
  `_run_step()`, `_fail()`, retry/timeout/iteration logic are byte-for-byte unmodified.
- `capabilities/registry.py` — add exactly the one registration line (§9). No other line changes.
- `core/config.py` — add exactly the four `Settings` fields (§22).
- `docker-compose.yml` — add exactly the one service (§23).
- `pyproject.toml` — **no change required**: `"worker"` is already in the `packages` list (added by
  Phase 12); `worker/analysis_main.py`/`worker/analysis_cycle.py` are new modules within an
  already-packaged directory, requiring no new entry.

**New files authorized to create**:
- `capabilities/engagement_capability.py` — `EngagementCapability`, `ENGAGEMENT_CAPABILITY_
  DEFINITION` (§6/§7).
- `prompts/engagement/v1.yaml` (§8).
- `worker/analysis_main.py`, `worker/analysis_cycle.py` (§12).

**Test files** (exact names not frozen beyond this level of specificity, matching every prior
phase's own convention):
- A test file for `EngagementCapability` (e.g. `tests/test_engagement_capability.py`).
- A test file (or addition to `capabilities/registry.py`'s own existing test file) proving
  `"engagement"` resolves.
- A test file for the atomic-claim fix, including a genuine concurrency proof (e.g.
  `tests/test_workflow_runner_atomic_claim.py`, or an addition to `tests/test_workflow_runner.py`).
- A test file for `worker/analysis_main.py`/`worker/analysis_cycle.py` (e.g.
  `tests/test_analysis_worker_cycle.py`, `tests/test_analysis_worker_main.py`).
- An addition to `tests/test_settings_phase7.py` for the four new config fields.
- A real-Postgres offline integration test proving the full research → intelligence → engagement →
  scoring chain via `FakeLLMGateway`, freshness filtering, batch cap, and the `CONTENT_GENERATION`/
  `ContentDraft` exclusion (e.g. added to a new `tests/test_news_analysis_integration.py`, following
  `tests/test_automation_integration.py`'s own established real-Postgres fixture pattern).

**Files explicitly frozen** (§27's full list, restated here as this section's own binding
boundary).

**No broad directory is authorized.** No file outside this exhaustive list may be created or edited
to implement Phase 13.

## 27. Frozen Components

**DECISION, binding — MUST NOT MODIFY**, unless a future session finds direct, cited evidence
proving otherwise (none was found this session):

`worker/main.py`, `worker/cycle.py` (Phase 12's collection worker, entirely untouched);
`services/collector.py`, `services/adapter_registry.py`, `services/adapter_keys.py`, every file under
`integrations/sources/` (collector business logic); `services/triage.py` (scoring logic),
`services/triage_orchestrator.py` (Triage, entirely untouched); `services/content_draft_service.py`,
`scripts/run_content_generation.py`, `workflows/definitions/content_generation.py` (the
`CONTENT_GENERATION` workflow, entirely untouched); `capabilities/copywriting_capability.py`,
`capabilities/quality_capability.py` (their behavior unmodified — quality/copywriting are not part
of `NEWS_ANALYSIS`); `capabilities/research_capability.py`, `capabilities/intelligence_capability.py`,
`capabilities/scoring_capability.py` (reused exactly as-is, zero modification — including
`ScoringCapability` not being updated to consume `engagement_analysis`'s output, per §5's own
explicit decision); `bot/**` (the entire Telegram Editorial Inbox and bot layer); every file under
`database/models/`; every Alembic migration file; `database/session.py`; `integrations/llm_gateway/
routing/**`, `integrations/llm_gateway/fallback/**`, `services/cost_tracker.py`,
`services/budget_guard.py` (the `CostTracker`/`BudgetGuard` architecture — §17's deferral is binding,
not merely a suggestion); `workflows/registry.py`, `workflows/errors.py`, `schemas/workflow.py`
(unchanged — the atomic-claim fix touches only `workflows/runner.py`'s internal method body, not any
of these).

**No evidence surfaced this session that any of the above requires amendment.**

## 28. Testing Requirements

Binding minimums:

**`EngagementCapability` tests**:
- Input propagation: `research`/`intelligence` `step_results` correctly reach the built
  `GenerateRequest`.
- Graceful degradation when `research`/`intelligence` results are missing/empty.
- Output shape/floor-validation (mirroring `_floor_validate`'s own existing test pattern).
- `PROMPT_VERSION`/schema resolution via a `FakeLLMGateway` (no live OpenAI).
- `additionalProperties: false` + all-fields-required schema invariant test.

**Registry test**: `CapabilityRegistry.resolve("engagement")` succeeds once registered; the
production `build_registry()` call itself resolves it (an integration-level smoke assertion).

**Workflow test**: the real `NEWS_ANALYSIS` `WorkflowDefinition` run through the real
`WorkflowRunner`/`CapabilityExecutor` with a `FakeLLMGateway`-backed `CapabilityRegistry` (mirroring
`tests/test_phase10_workflow_integration.py`'s own established pattern) — proves
research→intelligence→engagement→scoring executes in order, `step_results` propagate correctly, and
the task reaches `COMPLETED`.

**Atomic claim tests, mandatory, genuine concurrency proof**:
- Two simulated concurrent `run()` calls (real async tasks, not sequential calls) on the same
  `CREATED` task id: exactly one succeeds through to claiming `RUNNING`; the other raises
  `TaskAlreadyRunningError` and **never calls the LLM** (assert the losing call's `CapabilityExecutor`
  path was never entered).
- `RUNNING` task is not re-executed; `COMPLETED`/`FAILED` tasks are not re-executed (raise the
  existing `TaskAlreadyCompletedError`).
- Static/source check: `workflows/runner.py`'s fix contains no `except BaseException`/bare `except:`.

**Worker tests**: freshness-cutoff filtering (a task linked to a >48h-old event is never claimed; one
linked to a <48h-old event is); batch cap (`LIMIT 5` respected even with more eligible tasks);
deterministic ordering; sequential (not concurrent) execution; disabled-mode (mirroring Phase 12's
own proven test shape); cancellation (cycle and interval-sleep, mirroring `worker/main.py`'s own
tests); cycle-level `except Exception` (not `BaseException`) static check.

**Backlog test**: a task linked to a >48h-old event remains `CREATED` and untouched after a full
cycle runs.

**Boundary tests, mechanical, not merely "no exception"**: after a `COMPLETED` `NEWS_ANALYSIS` task,
zero `EditorialTask(workflow_type=CONTENT_GENERATION)` rows and zero `ContentDraft` rows exist,
scoped to that event — mirroring Phase 12's own `test_full_offline_chain_...` pattern exactly.

**Cost tests**: assert no code path references `settings.max_daily_ai_cost`; assert the workload
caps (batch size, freshness cutoff) are the only enforced limits — a documentation-consistency test,
not a live-spend test.

**No live OpenAI call anywhere in the automated suite** — unbroken discipline since Phase 7,
continued.

## 29. Real Postgres Isolation

**DECISION, binding**: reuse Phase 12's own proven, documented discipline exactly (`docs/
phase12_fresh_news_automation_implementation_plan.md` §12.0, and its own final-re-audit-verified
corrections) — `independent_session_factory()` (`tests/test_triage_orchestrator_claims.py`), unique
test-owned rows (a distinctive name/id prefix), explicit FK-safe `try/finally` cleanup, no
rollback-only isolation (this workflow's own commits are real, independent commits, exactly like
Phase 12's collector/triage), zero test-owned pollution verified post-run. **No separate test
database is assumed to exist** — none does, confirmed unchanged since Phase 12.

## 30. Manual Live Validation

**DECISION, binding — one manual, human-authorized live test, not executed during Contract
writing**: `news_analysis_batch_size` temporarily overridden to `1` for this one run (mirroring Phase
12 M6's own "smallest sufficient live proof" discipline) — never the historical backlog. Procedure,
mirroring `docs/phase12_m6_live_acceptance_report.md`'s own structure:
1. Confirm at least one genuinely fresh (≤48h), `CREATED` `NEWS_ANALYSIS` task exists.
2. Record baseline: `CREATED`/`RUNNING`/`COMPLETED`/`FAILED` counts, `AIExecution` count,
   `ContentDraft` count.
3. Start the real worker (`news_analysis_enabled=true`, `news_analysis_batch_size=1`).
4. Confirm no developer manually invokes the claim/execution path for the duration.
5. Observe one cycle: the task is claimed, `WorkflowRunner` runs it against the real `LLMGateway`,
   `EngagementCapability` produces real output.
6. Confirm the task reaches `COMPLETED` (or, if genuinely ineligible/fails, document the real
   outcome without manipulating thresholds).
7. Confirm, by direct database inspection: zero new `CONTENT_GENERATION` tasks, zero new
   `ContentDraft` rows.
8. Confirm bounded cost exposure (at most ~4-5 real LLM calls occurred, per §14's own derivation).
9. Stop the worker cleanly (mirroring Phase 12 M6's own SIGTERM/best-available-platform-method
   procedure).
10. **No repeated uncontrolled live retries** — if any step fails, stop and report, do not loop the
    attempt.

## 31. Definition of Done

1. `EngagementCapability` exists (`capabilities/engagement_capability.py`).
2. Registered correctly in `capabilities/registry.py::build_registry()`.
3. `prompts/engagement/v1.yaml` is strict-schema compliant (`additionalProperties: false`, all
   fields required).
4. `NEWS_ANALYSIS` executes end-to-end (research→intelligence→engagement→scoring) with
   `FakeLLMGateway` in the automated suite.
5. Atomic claim proven under genuine concurrency (two real concurrent `run()` calls, one winner).
6. Exactly one owner per claimed task, enforced at the database level.
7. Freshness cutoff (≤48h) enforced and tested.
8. Batch cap (≤5) enforced and tested.
9. Execution is sequential, never concurrent, within a cycle.
10. Poll interval is 300s, independently configurable from Phase 12's collection interval.
11. Historical stale (>48h) backlog remains untouched — not deleted, not archived, not mutated.
12. No automatic `FAILED`-task retry exists anywhere in Phase 13's own code.
13. Stale-`RUNNING` auto-recovery is absent, and the manual monitoring/recovery procedure (§16) is
    documented.
14. No `CONTENT_GENERATION` task is ever created by Phase 13's own code (mechanically verified).
15. No `ContentDraft` is ever created by Phase 13's own code (mechanically verified).
16. `EngagementCapability`'s output never claims observed engagement — schema/naming/documentation
    all consistently label it predicted.
17. No migration exists anywhere in the diff.
18. Every mandatory automated test (§28) exists and passes.
19. The full repository regression suite passes.
20. `ruff check .` passes clean.
21. Targeted `mypy` passes clean on every changed/new file.
22. `python -m scripts.validate_architecture` reports 0 violations.
23. Secret/security hygiene passes (reusing the now-established safe Docker validation method,
    `docker compose config --quiet`/`--services`, never plain `docker compose config`).
24. The one manual live tiny-sample acceptance test (§30) passes.

## 32. Risks

| Risk | Cause | Impact | Mitigation | Verification |
|---|---|---|---|---|
| Atomic-claim regression | The `workflows/runner.py` fix (§10) is the one frozen-phase amendment this Contract authorizes | Could silently break `CONTENT_GENERATION`'s own use of the same `run()` function if done carelessly | Fix is narrow (one method body, exception contract unchanged); `scripts/run_content_generation.py`'s own existing tests must continue passing unmodified | Full regression suite (§28/§31 item 19) includes every existing `WorkflowRunner`/`CONTENT_GENERATION` test, unmodified |
| Stale `RUNNING` tasks | No auto-recovery (§16, MVP decision) | A crashed worker leaves a task permanently unexecutable without manual intervention | Documented monitoring query + manual recovery procedure | Operational, not automated — explicitly accepted |
| Backlog burst / AI spend | 4723+ `CREATED` tasks exist; batch/freshness caps are the only bound | Uncontrolled spend if caps are bypassed or misconfigured | Freshness cutoff + batch cap + sequential execution are all mandatory, not optional (§17/§25 item 5) | Backlog test (§28) proves >48h tasks are never claimed |
| `BudgetGuard` false assurance | `CostTracker.record()` never called (§17) | A future reader could wrongly assume `max_daily_ai_cost` provides real protection | Explicitly, verbatim documented as not proven functional; setting is not introduced | This Contract's own §17 language, carried into Implementation Plan/audits unchanged |
| Duplicate execution | Would occur if the atomic claim (§10) were implemented incorrectly | Double AI spend, duplicate `AIExecution`-equivalent work for one task | Atomic `UPDATE`+rowcount pattern, directly modeled on Triage's own proven implementation | Mandatory concurrency test (§28) |
| Provider outage | External dependency, pre-existing risk | Tasks fail via existing `RetryableCapabilityError`/fallback-exhaustion path | Unchanged, existing `FallbackPolicy`/`RateLimiter` | Existing coverage, unmodified |
| Long cycle duration | Sequential execution of up to 5 tasks × up to 4-5 LLM calls each, each with up to 30s timeouts | A cycle could take several minutes under worst-case retries | Accepted, disclosed (mirrors Phase 12's own "cycle duration + interval" model, §14) | No new mechanism needed |
| Worker restart | Standard process lifecycle | In-flight task left `RUNNING` (§16) | Same as stale-`RUNNING` risk above | Same |
| Strict-schema failure | New prompt (§8), unproven in production | `ValidationCapabilityError` → task `FAILED`, not corrupted | Existing floor-validation pattern, reused | Prompt/schema invariant test (§28) |
| Accidental `CONTENT_GENERATION` trigger | Scope-creep risk during implementation | Would violate the frozen boundary (§19) | Explicit prohibition + mechanical, zero-rows test | §28's boundary test |
| Shared dev DB test pollution | No separate test database exists (unchanged since Phase 12) | Test-owned rows could pollute real data if cleanup fails | Reuse Phase 12's own proven `try/finally` + unique-row discipline (§29) | Post-test pollution check, mirroring Phase 12's own M5 gate |

## 33. Canonical Rules

1. Phase 13 executes `NEWS_ANALYSIS` only — nothing further downstream.
2. Dedicated analysis worker, separate process from Phase 12's collection worker.
3. Freshness cutoff: 48 hours, reusing existing `compute_freshness()` unmodified.
4. Batch cap: 5 tasks per cycle, mandatory, never bypassed.
5. Execution: sequential only, never concurrent, within a cycle.
6. Poll interval: 300 seconds, independent of Phase 12's collection interval.
7. Atomic claim is mandatory — `workflows/runner.py::WorkflowRunner.run()`'s `CREATED→RUNNING`
   transition must be a genuine atomic conditional `UPDATE`, not a read-then-write.
8. No historical-backlog drain — tasks older than the freshness cutoff remain untouched forever
   unless a future phase adds recovery.
9. No automatic `FAILED`-task retry anywhere in Phase 13's own code.
10. No automatic stale-`RUNNING` recovery in Phase 13 — monitoring/manual recovery only.
11. `EngagementCapability`'s score is predicted potential, never presented as observed engagement.
12. No real (observed) engagement-metric persistence in Phase 13 — no migration.
13. No `max_daily_ai_cost` or any new monetary-cap setting is introduced.
14. No automatic `CONTENT_GENERATION` invocation anywhere in Phase 13.
15. No `ContentDraft` creation anywhere in Phase 13's own code.
16. No public/Telegram publishing in Phase 13, in any form.
17. No image/media, no 5+ image-candidate implementation in Phase 13.
18. No migration exists in Phase 13.
19. The one manual live acceptance test is separately, explicitly human-authorized, using a
    minimal (batch-size-1) sample, never the historical backlog.

## 34. Acceptance Checklist

Self-audited before submission:

1. **Is the claim truly atomic?** Yes — §10's single `UPDATE ... WHERE status = 'CREATED'` +
   `rowcount` check, directly modeled on Triage's own proven, unmodified pattern.
2. **Can a claim race still double-charge AI?** No — the atomic `UPDATE` guarantees at most one
   caller ever transitions a given task past `CREATED`; the losing caller's code never reaches
   `CapabilityExecutor`/any LLM call (§10/§28's own concurrency test proves this directly, not just
   the claim's DB-level correctness).
3. **Is the transaction released before LLM calls?** Yes — §24 traces the existing, unmodified
   commit discipline directly: the claim commits immediately, before `_execute_steps()` begins; no
   transaction is ever held open across a provider call, in the current architecture or after this
   Contract's fix.
4. **Is `WorkflowRunner` compatible with claim semantics?** Yes — §11: the claim *is* `run()`'s own
   internal transition; no separate external pre-claim exists, so no double-transition/race-window
   is possible by construction.
5. **Are stale tasks excluded?** Yes — §13's eligibility query filters to `≤48h` freshness,
   independently derived from existing `compute_freshness()` semantics, not invented.
6. **Can the 4723-task backlog accidentally drain?** No — §14/§18: batch cap (5/cycle) and
   freshness cutoff (48h) both apply unconditionally; no "process all eligible" mode exists.
7. **Is the batch cap hard?** Yes — `LIMIT news_analysis_batch_size` in the eligibility query
   itself (§13), not a soft/advisory limit.
8. **Is execution sequential?** Yes — §14, explicitly, no parallelism authorized.
9. **Did this Contract falsely imply observed engagement?** No — §6/§7/§17 all explicitly,
   repeatedly state predicted-not-observed, with the output schema's own field naming
   (`engagement_potential_score`) making this unambiguous structurally, not just in prose.
10. **Did this Contract introduce a fake dollar-budget guarantee?** No — §17 states the
    `CostTracker` gap verbatim and explicitly declines to introduce `max_daily_ai_cost`; cost
    exposure is bounded by workload, not spend, and this distinction is stated explicitly, not
    blurred.
11. **Is `CONTENT_GENERATION` impossible to trigger?** Yes — §19, mechanically enforced (§28's
    boundary test), no import, no call site, no partial wiring anywhere in the authorized scope.
12. **Is the exact file scope exhaustive?** Yes — §26: 4 narrow existing-file edits (one of which,
    `workflows/runner.py`, is explicitly scoped to a single method body), 3 new production files,
    and a fully enumerated test-file list.
13. **Can Implementation Planning proceed without inventing new architecture?** Yes — every module
    name, function boundary, configuration field, failure case, transaction boundary, and test
    obligation is frozen at implementation-actionable precision; the only items left to Planning's
    own discretion are genuinely cosmetic (exact test file naming, exact query-construction
    technique for §13's freshness filter — Python-side vs. a computed SQL predicate — since both are
    correctness-equivalent and no evidence favors one).

**No self-audit question surfaced a defect requiring correction before submission.**

---

PHASE 13 CONTRACT READY FOR AUDIT
