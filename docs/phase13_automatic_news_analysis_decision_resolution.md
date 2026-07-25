# Phase 13 — Automatic News Analysis Decision Resolution

Decision Resolution only. No production code, test, migration, or Contract was modified. No
`NEWS_ANALYSIS` task or backlog was executed. No live AI/OpenAI call was made. Every claim below was
independently re-verified against current source (`HEAD = e6cf337`), including facts not previously
verified in the Discovery document.

## 1. Executive Summary

Phase 13's boundary is **Option B**: implement `EngagementCapability`, close the workflow-execution
gap with a genuinely atomic claim mechanism, and run `NEWS_ANALYSIS` automatically via a dedicated,
batch-capped worker — stopping at `NEWS_ANALYSIS` completion, with no automatic
`CONTENT_GENERATION` trigger. This resolution also surfaces one **new, previously-unverified
finding**: `CostTracker.record()` is deliberately, explicitly never called anywhere in production
code (confirmed via `integrations/llm_gateway/boot.py`'s and `gateway.py`'s own docstrings, and an
exhaustive grep) — meaning `BudgetGuard`'s `max_daily_ai_cost` ceiling, while genuinely and
automatically consulted before every dispatch, checks a spend ledger that is **never populated**,
and is therefore **not proven functional** as a cumulative-spend cap.

**Human decisions now resolved (both, finally)**: Phase 13 explicitly **defers** any remediation of
the `CostTracker`/`BudgetGuard` cumulative-spend-ledger gap — that is a separate, governed,
cross-cutting remediation concern, out of Phase 13's own scope — and explicitly **does not introduce
a new `max_daily_ai_cost`-style setting** in Phase 13, since doing so without a functioning
cumulative-recording path would create false assurance of a monetary cap that does not actually
exist. Phase 13's cost containment is instead entirely deterministic and workload-based: a 48-hour
freshness cutoff, a 5-task batch cap, sequential execution, no historical-backlog drain, and no
automatic retry storm (§6-§8) — explicitly **not** described as, or treated as equivalent to, a
monetary budget cap. **No human decision remains open after this update (§26).**

A second finding materially simplifies the design: the atomic claim mechanism (§4) and the
`WorkflowRunner`/claim compatibility question (§14, flagged as critical) resolve to the **same
answer** — `WorkflowRunner.run()`'s own existing `CREATED → RUNNING` transition is fixed to be a
genuine atomic conditional `UPDATE` (mirroring Triage's own proven pattern) instead of its current
read-then-write. No separate claim step, no new column, no new state field is needed.

## 2. Phase Boundary

**RESOLVED: Option B.**

```
EditorialTask(NEWS_ANALYSIS, CREATED)
  → safe atomic claim (inside a fixed WorkflowRunner.run(), §4/§14)
  → research (existing, unmodified)
  → intelligence (existing, unmodified)
  → engagement_analysis (NEW: EngagementCapability, §9-§13)
  → scoring (existing, unmodified)
  → EditorialTask COMPLETED
  → STOP
```

Option A (manual-only) is rejected: it does not solve the stated product problem (fresh news
currently *not* analyzed) and leaves the exact same 4723-task backlog problem for a later phase to
re-discover. Option C (auto-chain into `CONTENT_GENERATION`) is rejected: the product's own explicit
constraints (no auto-publish, `/news` remains editorial-only, Approve/Reject/Rework not yet
architected) mean automatically generating a `ContentDraft` for every analyzed event has editorial-
review-load and cost implications this discovery cannot resolve — it is a distinct, later,
human-owned decision (§17).

## 3. Automation Placement

**RESOLVED: Option B — a dedicated `NEWS_ANALYSIS` worker/process**, structurally separate from
Phase 12's collection worker (its own OS process, its own Docker service), for the reasons the task
itself names: collection and paid AI execution have materially different cost, latency, retry, and
failure profiles. Extending Phase 12's own worker (Option A) would reopen its already-approved,
frozen Contract and couple ingestion cadence to AI-execution cadence — rejected. A generic
`EditorialTask`-type-agnostic worker (Option C) is rejected for the same reason Option C is rejected
in §2: it risks silently making `CONTENT_GENERATION` automatic before that is an authorized decision,
conflating two workflows with very different risk profiles into one piece of infrastructure.

**Structural placement, resolved narrowly**: reuse the existing `worker/` Python package (do not
create a new top-level package) — add `worker/analysis_main.py` (entry point) and
`worker/analysis_cycle.py` (one-cycle orchestration), mirroring `worker/main.py`/`worker/cycle.py`'s
own proven shape exactly. This remains a **separate OS process and separate Docker service**
(satisfying Decision 2's real requirement — process/cost/failure isolation) without introducing a
second top-level package for what is conceptually the same "automation worker" family. Smaller
structural footprint than a new package, and directly reuses `core.logging.setup_logging()`,
`core.config.settings`, and the exact cancellation/disabled-idle pattern Phase 12's `worker/main.py`
already established and tested.

## 4. Task Claim / Concurrency

**RESOLVED: Option A (conditional atomic `UPDATE`), implemented by fixing `WorkflowRunner.run()`
itself, not by adding a separate claim step.**

Re-read `workflows/runner.py:111-123` directly: the current `CREATED → RUNNING` transition is
`task = await session.get(...)` → status check → `task.status = TaskStatus.RUNNING` → `commit()` —
a plain read-then-write. **Resolution**: replace this with a single atomic statement analogous to
Triage's own `_claim_new_event()` (`services/triage_orchestrator.py:45-67`):

```sql
UPDATE editorial_tasks
SET status = 'RUNNING', updated_at = :now
WHERE id = :task_id AND status = 'CREATED'
```

checked via `result.rowcount == 1`. If `0`, another caller already claimed (or completed/failed) the
task — `run()` raises the **same, already-documented** `TaskAlreadyRunningError` it raises today for
the sequential-misuse case (re-reading current state to decide which of the two existing exceptions
applies, so callers see no new exception type). This is a narrow, backward-compatible correctness
fix to an existing, frozen Phase 5 component — it makes `run()`'s own already-documented contract
(*"raises `TaskAlreadyRunningError` for misuse"*) actually true under concurrency, which it is not
today. `Option B` (`SELECT ... FOR UPDATE SKIP LOCKED`) was evaluated and rejected: it introduces a
locking paradigm not used anywhere else in this codebase, where the conditional-`UPDATE` pattern is
already the established, proven idiom (Triage). `Option D` (single-worker assumption) is rejected
per the task's own instruction — nothing in the evidence justifies assuming only one worker instance
will ever run.

**Ordering / batching**: the worker (§3) selects a bounded batch (§7) of `CREATED` `NEWS_ANALYSIS`
task ids via an ordinary `SELECT` (no lock needed for this read — it is not the ownership claim,
just a candidate list), then calls the fixed `run()` for each; a `TaskAlreadyRunningError`/
`TaskAlreadyCompletedError` on any individual task is caught and skipped silently, exactly mirroring
Triage's own "lost the race, not an error" precedent (Contract §18-equivalent).

## 5. Crash / Stale RUNNING Semantics

**RESOLVED: Option A — no automatic recovery in Phase 13; detect/report only.** A worker crash mid-
`RUNNING` leaves the task permanently `RUNNING` (any future `run()` call on it raises
`TaskAlreadyRunningError`, correctly, since it genuinely might still be in progress from the claimer's
perspective). Building a lease/heartbeat (Option C) or timeout-based reclaim (Option B) is real,
non-trivial distributed-systems infrastructure this discovery found no evidence Phase 13 needs on
day one — `Triage`'s own equivalent (`_select_recovery_candidates`/`_acquire_recovery_ownership`)
took a dedicated milestone (Phase 9 M3) to build correctly; inventing an analogous mechanism here
without dedicated design attention would be exactly the kind of technical debt this discovery process
exists to prevent.

**Frozen, explicit MVP expectations**: (1) a monitoring query — `SELECT count(*) FROM
editorial_tasks WHERE status='RUNNING' AND updated_at < now() - interval '1 hour'` (or equivalent) —
must be documented as the manual-recovery operator procedure; (2) manual recovery is a direct,
human-run `UPDATE ... SET status='CREATED' WHERE id=...` after confirming the owning process is
genuinely dead, not a Phase 13 script; (3) this is named explicitly as accepted, temporary
operational debt for a future phase, exactly matching how Phase 12 itself already treats the
`NEWS_ANALYSIS(CREATED)` buildup — the same pattern, one level deeper in the pipeline.

## 6. Backlog Policy

**RESOLVED: Option D — a bounded subset via freshness cutoff, derived from existing Freshness
semantics, not invented.**

`services/freshness.py`'s own `TIER_BOUNDARIES_HOURS = (2.0, 6.0, 12.0, 24.0, 48.0)` already defines
the system's own boundary between "fresh enough to matter" and the lowest-weighted (`0.1`) "48h+"
catch-all tier. **Frozen rule**: a `CREATED` `NEWS_ANALYSIS` task is eligible for automatic claim
only if its `NewsEvent`'s freshness age (same `published_at`-with-`collected_at`-fallback anchor
Triage already uses) is **≤ 48 hours** at claim time — reusing `compute_freshness()` unmodified, not
a new formula.

**Explicit backlog treatment**: of the 4723 currently-`CREATED` tasks, the great majority (the
~3130 that predate Phase 12's own M6 live run) are already well past 48 hours old and will **never**
become eligible under this rule as time passes — they remain `CREATED`, untouched, unexecuted,
**not deleted** (per the explicit no-destructive-deletion instruction), indefinitely, as accepted
historical debt. Only the subset of tasks whose events are within the rolling 48-hour freshness
window at claim time are ever processed. No backfill, no catch-up drain of the historical backlog is
in scope. Cleanup/archival of permanently-stale `CREATED` tasks is explicitly deferred to a future
phase — not resolved here, since no eviction/archival policy exists anywhere in this codebase to
model it on.

## 7. Batch / Cadence

**RESOLVED**: `news_analysis_batch_size = 5`, **sequential** execution within a cycle (not
concurrent) — matching the task's own stated MVP preference and directly bounding worst-case
per-cycle LLM calls to a small, auditable number (§9).

**Derivation**: `ScoringCapability` (`capabilities/scoring_capability.py:193,217`) makes up to 2 real
`call_generate()` calls per execution (an initial attempt plus one correction retry) — combined with
`research` (1), `intelligence` (1), and the new `engagement` (1, following the same single-call
pattern as `IntelligenceCapability`), one `NEWS_ANALYSIS` task can make **4-5 real LLM calls**.
`batch_size=5` therefore bounds one cycle to at most 20-25 real calls — small enough to observe and
reason about directly, large enough to make meaningful progress against the (freshness-bounded)
backlog.

## 8. Cost Controls

**Existing controls, independently re-verified, not assumed**:

- `BudgetGuard.check()` **is** genuinely, automatically invoked — confirmed at
  `integrations/llm_gateway/fallback/policy.py:275`, inside `FallbackPolicy`'s per-candidate dispatch
  loop, using a pre-flight cost *estimate* (`CostEstimator`), before every real provider call. This
  requires zero new Phase 13 code — `NEWS_ANALYSIS`'s calls automatically pass through the same
  `assemble_ai_integration_layer()`-assembled `RoutingGateway` that `CONTENT_GENERATION` already
  uses.
- **New finding, materially important**: `CostTracker.record()` — the function that would write
  *actual* spend to the same Redis ledger `BudgetGuard.check()` reads — is **never called anywhere
  in production**, confirmed by direct grep (`integrations/llm_gateway/`, `services/`,
  `capabilities/` — zero non-test call sites) and by the codebase's own explicit, pre-existing
  documentation: `integrations/llm_gateway/boot.py:126-129` ("*constructed... but not called by
  anything in this delivery*") and `integrations/llm_gateway/gateway.py:12-14` ("*CostTracker.record()
  is deliberately NOT called by this class*"). **This means `settings.max_daily_ai_cost` — even if
  configured — cannot currently function as an effective cumulative-spend cap in production, because
  the ledger it reads is never written to.** This is a genuine, pre-existing, cross-cutting Phase
  7/8-era gap, not something Phase 13 introduces.

**Resolution — DECIDED, binding**: **defer** `CostTracker.record()`/cumulative spend-ledger
remediation entirely **out of Phase 13**. Phase 13 must not modify the cross-cutting LLM
cost-accounting architecture (`RoutingGateway`/`FallbackPolicy`/`CostTracker`/`BudgetGuard`) solely to
enable `NEWS_ANALYSIS` automation — that is a separate, governed, cross-phase remediation concern
(§"Future Remediation" below), not a Phase 13 deliverable. Phase 13 must not create a duplicate
budgeting system either.

**Phase 13 explicitly does not introduce a new `max_daily_ai_cost`-style setting** (§20) — without a
functioning cumulative-recording path, such a setting would create **false assurance** of a monetary
cap that does not actually exist. `settings.max_daily_ai_cost` (the existing, optional field) is
**not** relied upon, referenced as a control, or required to be configured by Phase 13.

**Phase 13's actual, binding cost containment is entirely deterministic and workload-based, not
monetary**:
- `NEWS_ANALYSIS` freshness cutoff = 48 hours (§6);
- batch size = 5 tasks per worker cycle (§7);
- **sequential execution only** — never concurrent;
- polling interval = 300 seconds (§7);
- no automatic historical-backlog drain (§6);
- no automatic `FAILED`-task retry storm (§15/§17);
- existing provider-level safeguards (`RateLimiter`, `FallbackPolicy`, `ProviderHealthStore`) remain
  unchanged and continue to apply automatically, unrelated to the ledger gap.

**These controls must never be described as, or treated as equivalent to, a monetary/dollar budget
cap** — they bound *workload* (task count, call count, cadence), not *spend*. The distinction must be
preserved verbatim wherever this resolution is referenced (Architecture Contract, risk sections,
future audits): `BudgetGuard.check()` remains genuinely wired into the call path (§9's original
finding is unchanged — it still runs, automatically, before every dispatch), but it must not be
represented as a **proven, functional cumulative daily-dollar cap**, because it is not one today.

**Future Remediation (deferred, not designed here)**: a separate, later, governed remediation should
determine how `AIExecution`/`CostTracker`/`BudgetGuard` together produce a complete, accurate
cumulative spend ledger and enforce real monetary budgets. This is named here only so a future phase
does not have to rediscover the gap — no design, schema, or mechanism for that remediation is
proposed in this document.

**Budget-exhaustion behavior — resolved using existing, unmodified mechanics, no new code needed**:
`BudgetExceededError` is a `PermanentCapabilityError` subtype (`capabilities/errors.py:46`, extending
the `PermanentCapabilityError` base) — `CapabilityExecutor.execute()` already converts any
`PermanentCapabilityError` to `PermanentStepFailureError`; `WorkflowRunner._run_step()` already
returns `"FAILED"` immediately (no retry) for that; since every `NEWS_ANALYSIS` step is `required`,
`_execute_steps()` already calls `_fail()`, transitioning the task cleanly to `FAILED` — never
leaving it stuck `RUNNING`, never silently retrying. **Budget exhaustion cannot corrupt task
semantics under the existing, unmodified architecture** — confirmed, not assumed.

## 9. EngagementCapability Semantics

**Resolved purpose**: in Phase 13, `EngagementCapability` estimates **predicted editorial/audience
engagement potential from content alone** — significance, likely audience interest, and virality-
style reasoning inferred by the LLM from the event's own text plus Research/Intelligence's prior
findings. It is **not**, and must not be represented as, a measurement of real, observed engagement
(views/forwards/reactions) — those signals exist upstream (Discovery §7) but are not persisted or
passed to any Capability in Phase 13 (§18 defers this).

**Naming**: the frozen `WorkflowStepDefinition(name="engagement_analysis", capability="engagement")`
(`workflows/definitions/news_analysis.py:22`) and the `capability_mapping.py` alias key `"engagement"`
are **not renamed** — both are already-frozen, in-force identifiers a rename would touch
unnecessarily (the task's own instruction: "do not rename frozen workflow steps casually"; no
evidence requires it). The Python class is named `EngagementCapability`, matching the existing
naming convention (`IntelligenceCapability`, `ScoringCapability`, etc., each named after their
capability-name string). **What changes is documentation and output-field naming discipline** (§11):
every output field must be labeled in a way that cannot be mistaken for observed data (e.g.
`engagement_potential_score`, never a bare `engagement_score` that could be misread as a real,
measured number) — this directly satisfies the frozen invariant (§25 item 8) against fabricating
"observed engagement."

## 10. Engagement Input Contract

Re-read `capabilities/executor.py::_build_context()` and `IntelligenceCapability`'s own established
consumption pattern directly: **no `CapabilityContext` schema change is needed or proposed.**
`NewsEventSnapshot` already exposes `title`, `summary`, `content`, `url`, `category`,
`published_at` to every Capability equally (no source-reliability field is exposed to *any* existing
Capability, including Intelligence — this is consistent with existing precedent, not a new gap
Engagement introduces).

**Required inputs** (all already available via the existing, frozen mechanism, zero new plumbing):
- `context.business.news_event` (title, content, category, published_at) — same as every existing
  capability.
- `context.business.workflow_state.step_results["research"]` — Research's prior output, consumed the
  exact same way `IntelligenceCapability` already consumes it (`capabilities/
  intelligence_capability.py:99`).
- `context.business.workflow_state.step_results["intelligence"]` — Intelligence's prior output
  (significance/angle/audience_relevance/recommendation), consumed via the identical mechanism.

**Optional inputs**: none proposed for Phase 13 — matching the "use only evidence-backed fields, do
not invent complexity" instruction. If Research or Intelligence's output is missing (e.g. an
optional-step skip in some future variant), `EngagementCapability` must degrade the same way
`IntelligenceCapability` already does for missing Research output — proceed on title/category alone,
never raise merely for an absent upstream result (mirroring `_format_research_facts()`'s own
existing "did not run" fallback text).

## 11. Engagement Output Contract

**Resolved, minimal, stable schema** (3 fields, matching `IntelligenceCapability`'s own 4-field
precedent in shape and size):

```json
{
  "engagement_potential_score": 0.0-1.0 (float, required),
  "audience_fit": "string, required (short qualitative descriptor)",
  "reasoning": "string, required (brief rationale, 1-3 sentences)"
}
```

- **`engagement_potential_score`** — explicitly a *predicted* value (LLM's own estimate), never an
  observed metric. Field name deliberately includes `_potential_` to make this unambiguous at the
  schema level, not just in documentation.
- **`audience_fit`** — short text describing which audience segment(s) this would resonate with,
  giving Scoring/a future human reviewer qualitative context beyond a bare number.
- **`reasoning`** — brief, auditable rationale, matching the existing project-wide pattern of never
  returning a bare score without explanation (Triage's own `explanation` dict, Intelligence's
  `recommendation` field).

**Downstream need, verified not assumed**: `ScoringCapability`'s own current input contract does not
consume `engagement_analysis`'s output today (confirmed: `ScoringCapability`'s existing, frozen
implementation predates this capability's existence and was never designed to read it). **Resolved:
`ScoringCapability` is not modified in Phase 13** — it continues producing its existing `score` output
unchanged, matching the "smallest change" principle; whether a future phase should wire Engagement's
output into Scoring is an open, low-stakes question explicitly deferred, not a Phase 13 blocker
(Scoring already functions correctly without it, exactly as it does today for `CONTENT_GENERATION`
workflows that never had an Engagement step either).

**"Predicted vs. observed" clarified explicitly, per the task's own instruction**: `Engagement
Capability`'s output in Phase 13 is **100% predicted/estimated**, **0% observed** — there is no
mechanism by which real Telegram metrics could reach it (§18), and its output schema/naming makes
this structurally unambiguous, not merely asserted in prose.

## 12. Prompt / Structured Output Rules

- **New prompt path**: `prompts/engagement/v1.yaml` — a genuinely new capability, so there is no
  pre-existing v1 predating the OpenAI Structured Outputs strict-mode remediation to preserve
  immutably; it launches directly compliant.
- **Schema compliance, mandatory, no regression**: `output_schema` must set
  `additionalProperties: false` and mark all three fields (§11) `required`, matching every other
  capability's already-remediated `v2`-or-later schema shape (confirmed pattern via
  `prompts/intelligence/v2.yaml`'s own documented purpose). No new prompt in this repository may be
  written non-compliant with this now-standard rule.
- **Versioning convention**: `PROMPT_VERSION = "1"` in `EngagementCapability` (matching how every
  other capability names its own constant), with the prompt file itself declaring `version: "1"` —
  consistent, not a special case.

## 13. Workflow Integration

Confirmed unchanged and correct: `research → intelligence → engagement_analysis → scoring`
(`workflows/definitions/news_analysis.py:19-24`). `EngagementCapability` consumes **both** Research's
and Intelligence's prior `step_results` (§10) — this is exactly why it is correctly positioned
*after* both in the existing, frozen step order; no reordering is justified or proposed.

## 14. WorkflowRunner / Claim Compatibility

**Resolved together with §4** (this section restates the resolution in the terms the task's own
Decision 15 asked for, to close the loop explicitly): the claim is **not** a separate, external
`CREATED → RUNNING` transition performed *before* calling `WorkflowRunner.run()` — it **is**
`run()`'s own (fixed) internal transition. This avoids the exact double-transition/race-window
problem Decision 15 warned about by construction: there is only **one** place `EditorialTask.status`
ever changes from `CREATED`, and it is now atomic. **Pattern chosen: C — "atomic claim and adjust
runner narrowly."** No new ownership field, no new column, no parallel state machine.

## 15. Failure / Retry Semantics

| Cause | Existing mechanism (unmodified) | Resulting task state |
|---|---|---|
| Capability failure (validation, malformed output) | `ValidationCapabilityError` → `PermanentStepFailureError` → `_fail()` | `FAILED` |
| Provider failure (all fallback candidates exhausted) | `RetryableCapabilityError`/`CapabilityTimeoutError` → `StepExecutionError`, retried up to `max_attempts`, then `_fail()` | `FAILED` (after exhausting step retries) |
| Timeout (step-level) | `StepTimeoutError`, treated exactly like `StepExecutionError` | Retried, then `FAILED` if exhausted |
| Budget refusal | `BudgetExceededError` (`PermanentCapabilityError`) → `PermanentStepFailureError` → `_fail()` (§8) | `FAILED` |
| Malformed output | `ValidationCapabilityError` (via `EngagementCapability`'s own floor-validation, mirroring Intelligence's `_floor_validate`) | `FAILED` |
| Worker crash mid-run | No existing mechanism catches this — task remains `RUNNING` | `RUNNING` (stale, §5) |
| Task already claimed (race) | `TaskAlreadyRunningError` (now genuinely atomic, §4) | Unchanged (still `RUNNING`, owned by the winner); the losing caller skips |
| Task already completed | `TaskAlreadyCompletedError` (existing) | Unchanged; caller skips |

**No silent infinite retry, no retry storm**: confirmed by the existing, bounded `max_attempts`
(step-level, default 3) and `max_iterations` (workflow-level, 3) ceilings, both already frozen in
`news_analysis.py`'s `DEFINITION`, unmodified by Phase 13.

## 16. Idempotency Guarantees

**Frozen guarantee**: exactly one active owner per claimed task, enforced by the now-atomic
`CREATED → RUNNING` transition (§4) at the database level — this is a real, verifiable guarantee, not
an aspiration. **Not claimed**: true exactly-once side-effect semantics — a worker crash between a
successful capability call and the next `session.commit()` (per-step persistence, Phase 9.5's own
existing discipline, `workflows/runner.py:189-199`) could in principle leave that one step's result
uncommitted, requiring the *eventual* recovery mechanism (§5, deferred) to re-run it. This is
explicitly disclosed as an **at-least-once** (not exactly-once) guarantee for the work performed,
while ownership itself remains exactly-once — consistent with what the existing, unmodified
architecture can actually deliver, not an invented stronger claim.

## 17. CONTENT_GENERATION Boundary

**Frozen, binding**: successful `NEWS_ANALYSIS` completion does **not** automatically invoke
`run_content_generation_for_event()` in Phase 13. **Why**: (1) the product has not yet decided the
editorial-review policy that should gate automatic draft generation (Approve/Reject/Rework remains
explicitly unbuilt, per the product's own stated constraint); (2) `CapabilityExecutor._build_context()`
has no existing mechanism to pass one task's results into another task's context (Discovery §12) —
building that bridge is itself a real, separately-scoped design question; (3) automatically
generating a `ContentDraft` for every one of the (freshness-bounded) newly-analyzed events would
create exactly the kind of unreviewed-content volume the product has explicitly said it does not
want yet. **Phase 14 (or later) may resolve**: analysis result → selection/threshold →
`CONTENT_GENERATION` trigger. That bridge is not pre-implemented, stubbed, or partially wired here.

## 18. Real Engagement Metrics Deferral

**Resolved: Option B — defer.** Phase 13 functions meaningfully without real Telegram
views/forwards/replies/reactions persistence — `EngagementCapability`'s LLM-reasoning approach (§9)
requires none of it. Per Discovery §17's own comparison, migrating now would touch a currently-frozen
file (`telegram_source.py`), raise an unanswerable historical-backfill question (the data was never
captured), and only benefit ~4/82 currently-configured sources (Telegram), while the blocking gap
(§4/§6 of Discovery) requires none of it. **Conceptual future fields only, no schema design**: a
future increment could add `NewsEvent.telegram_views`/`.telegram_forwards`/`.telegram_reply_count`
(nullable, Telegram-only) and extend `_to_raw_item()`/`RawNewsItem` to carry them — named here only
so a future phase does not have to rediscover that the raw data is available (Discovery §7's own
finding), not designed further.

## 19. Image Requirement Deferral

**Frozen**: 5+ image candidates remain fully out of scope for Phase 13, unchanged from Discovery §14.
Future dependency recorded, not designed: source-media capture and image discovery/generation should
attach after the `CONTENT_GENERATION` boundary is itself resolved (§17) — attaching it to
`NEWS_ANALYSIS` would conflate an analysis step with content-asset assembly, which is not its
purpose (§9).

## 20. Configuration

| Name | Type | Default | Validation | Purpose |
|---|---|---|---|---|
| `news_analysis_enabled` | `bool` | `False` | — | Opt-in gate, matching `news_collection_enabled`'s own established convention — automatic execution never starts until explicitly enabled |
| `news_analysis_poll_interval_seconds` | `int` | `300` | `Field(gt=0)` | How often the dedicated worker checks for claimable `CREATED` tasks — deliberately **not** coupled to `news_collection_interval_seconds` (§7; analysis should not wait up to 30 minutes after Triage just because collection does) |
| `news_analysis_batch_size` | `int` | `5` | `Field(gt=0)` | Max tasks claimed and executed per cycle (§7) |
| `news_analysis_freshness_cutoff_hours` | `float` | `48.0` | `Field(gt=0)` | Backlog eligibility cutoff (§6), matching Freshness's own existing last tier boundary |

**`max_daily_ai_cost` is explicitly NOT introduced/relied upon by Phase 13** (§8, DECIDED) — it
remains the existing, optional, pre-Phase-13 field, untouched, unreferenced by any Phase 13 control.

**Reused, not duplicated**: `settings.redis_unavailable_policy` (existing, required by
`RedisBudgetGuard` already, since `BudgetGuard.check()` still runs regardless of the ledger gap),
`settings.default_content_language` (existing, already injected into every `CapabilityContext`). No
other new setting is justified by the evidence gathered.

## 21. Runtime / Docker

- **Package/module**: `worker/analysis_main.py` (entry point), `worker/analysis_cycle.py`
  (orchestration) — within the existing `worker/` package (§3).
- **Docker service** (new): e.g. `news_analysis_worker`, `command: ["python", "-m",
  "worker.analysis_main"]`.
- **Dependencies — explicitly *not* copied from Phase 12's collection worker**: this worker's actual
  runtime path (`assemble_ai_integration_layer()`) constructs `RedisProviderHealthStore`,
  `RedisLatencyTracker`, `RedisRateLimiter`, `RedisCacheStore`, `RedisBudgetGuard` — **Redis is
  genuinely required here**, unlike Phase 12's collection worker, which correctly excludes it because
  it never touches the AI integration layer at all. `depends_on: postgres, redis` (both), matching
  `backend`'s own existing dependency shape, not Phase 12's `automation_worker`'s.
- **Restart behavior**: `restart: unless-stopped`, matching every existing service.
- **Disabled behavior**: reuse the exact, already-tested Phase 12 idle-while-alive pattern
  (`asyncio.Event().wait()`, log once, cancellation-responsive, zero DB/AI access while disabled) —
  proven correct, no reason to invent a variant.
- **Graceful shutdown**: reuse the exact, already-tested `SIGTERM`/`SIGINT` +
  `NotImplementedError`-guarded signal-handling pattern from `worker/main.py`.

## 22. Test Strategy

Required layers, all achievable without live OpenAI (mirroring Phase 9/10/12's own established
`FakeLLMGateway`/`independent_session_factory()` conventions):

1. `EngagementCapability` unit tests (fake gateway, floor-validation, missing-upstream-step
   degradation).
2. Prompt/schema invariant test (`additionalProperties: false`, required fields — mirroring existing
   per-capability schema tests).
3. Atomic-claim concurrency test — two simulated concurrent `run()` calls on the same task id,
   asserting exactly one succeeds and the other raises `TaskAlreadyRunningError` (a genuine
   concurrency proof, not merely sequential).
4. Worker-cycle tests (claim batch, sequential execution, respects `batch_size`).
5. Failure-semantics tests (§15's table, each row).
6. Backlog freshness-filtering test (task tied to a >48h-old event is never claimed; one tied to a
   <48h-old event is).
7. Batch-cap test (more than `batch_size` eligible tasks exist; only `batch_size` are claimed per
   cycle).
8. Disabled-mode test (reusing Phase 12's own test pattern).
9. Integration test using the real `WorkflowRunner`/`CapabilityExecutor` with a `FakeLLMGateway`
   (mirroring `tests/test_phase10_workflow_integration.py`'s own precedent) — proves the full
   research → intelligence → engagement → scoring chain completes.
10. Real-Postgres isolation, reusing `independent_session_factory()` + explicit FK-safe cleanup —
    the exact, already-proven Phase 12 pattern, not a new one.
11. Mechanical assertion: no `CONTENT_GENERATION` task and no `ContentDraft` row is ever created by
    this worker's own code path.
12. Budget-exhaustion test (`BudgetExceededError` correctly fails the task, per §8/§15).
13. Full repository regression suite must pass, matching every prior phase's own gate.

**No live OpenAI call anywhere in the automated suite** — unbroken discipline since Phase 7,
continued here.

## 23. Live Validation Strategy

Separately, explicitly human-authorized (mirroring Phase 12's own M6 gate) — not part of this
resolution's own scope to execute. **Sample size, resolved**: `news_analysis_batch_size` temporarily
overridden to `1` for the live acceptance run (matching Phase 12 M6's own "smallest sufficient live
proof" discipline), against a single, genuinely fresh (post-Phase-13-enablement) event — **never**
the historical backlog. The exact procedure (baseline snapshot, before/after `CREATED` count,
downstream-boundary re-verification, clean shutdown) should mirror `docs/
phase12_m6_live_acceptance_report.md`'s own structure when the Architecture Contract stage is
reached.

## 24. Migration Decision

**Migration required for Phase 13: NO.**

Real engagement-metric persistence (Telegram views/forwards/replies/reactions) is deferred to a
future, separately-evidenced increment (§18). Nothing in the resolved Phase 13 boundary touches the
database schema.

## 25. Frozen Invariants

1. No automatic `CONTENT_GENERATION` invocation in Phase 13 (§17).
2. No public publishing, no Telegram write action, no channel post (§19 discovery/§21 discovery,
   unchanged).
3. No 5+ image-candidate feature in Phase 13 (§19).
4. No uncontrolled historical-backlog drain — the freshness cutoff (§6) and batch cap (§7) are both
   mandatory, not optional tuning.
5. Batch cap (`news_analysis_batch_size`) is mandatory in every execution path — no "process
   everything eligible" mode exists.
6. Concurrency-safe claim is mandatory — the atomic `UPDATE` fix to `WorkflowRunner.run()` (§4) is a
   precondition for enabling automatic execution at all, not an optional hardening pass.
7. Existing routing-layer safeguards cannot be bypassed — `BudgetGuard.check()`,
   `RateLimiter`, and `FallbackPolicy` remain in the call path unmodified; Phase 13 must not
   introduce any code path that skips the Routing Gateway. (Their presence is not, however, a proven
   monetary cumulative-spend cap — see item 11.)
8. No fake "observed engagement" claims — `EngagementCapability`'s output must be structurally and
   documentarily unambiguous as predicted/estimated, never presented as measured Telegram metrics
   (§9/§11).
9. No automatic `FAILED`-task retry storm — Phase 13 introduces no task-level auto-retry of `FAILED`
   tasks (§17-equivalent, restated as §15's own table).
10. Live validation is separately, explicitly human-authorized, using a minimal sample, never the
    historical backlog (§23).
11. **The `CostTracker`/`BudgetGuard` cumulative spend-ledger gap (§8) is explicitly out of Phase
    13's scope, deferred to a separate, later, governed remediation.** Phase 13 must not modify
    `RoutingGateway`/`FallbackPolicy`/`CostTracker`/`BudgetGuard` to fix it, must not introduce a new
    `max_daily_ai_cost`-style setting, and must disclose verbatim in the Architecture Contract's risk
    section that this ledger is not proven functional as a monetary cap. Cost containment in Phase 13
    is achieved exclusively via deterministic workload controls (48h freshness cutoff, batch size 5,
    sequential execution, 300s polling, no backlog drain, no retry storm) — never described as
    equivalent to a dollar budget.
12. `WorkflowRunner.run()`'s claim-safety fix (§4/§14) is a precondition for any automatic
    execution — a version of Phase 13 that skips this fix and relies on a single-worker assumption
    is explicitly rejected (Decision 4/Option D was rejected, not merely deprioritized).

## 26. Human Decisions

| Original Discovery decision | Status |
|---|---|
| Automation placement | **RESOLVED** — dedicated worker within the existing `worker/` package (§3) |
| Backlog policy / batch size | **RESOLVED** — 48h freshness cutoff, batch size 5, sequential (§6/§7) |
| `max_daily_ai_cost` | **RESOLVED — not introduced.** Human decision received: do not add this (or any) new monetary-cap setting in Phase 13; cost containment is deterministic/workload-based only (§8, DECISION B). |
| `EngagementCapability` input/output contract | **RESOLVED** — §10/§11 |
| Worker package/naming (`worker/analysis_main.py` vs. a new top-level package) | **RESOLVED** — reuse `worker/` (§3/§21), no evidence favors a new package |
| Poll interval exact value (300s default) | **RESOLVED as a default**, genuinely product-tunable via `.env`, consistent with how Phase 12 treated its own interval |
| Whether to fix the `CostTracker` wiring gap now or later | **RESOLVED — deferred.** Human decision received: Phase 13 must not modify the cross-cutting cost-accounting architecture; that remediation is separate and later-governed (§8, DECISION A). |

**No human decision remains open.** Every Discovery-listed decision (§1-§25 above) is resolved from
evidence and/or explicit human decision in this document.

## 27. Architecture Contract Inputs

The Architecture Contract stage should freeze, directly from this resolution: (1) the exact
`WorkflowRunner.run()` diff (atomic `UPDATE`, §4); (2) `EngagementCapability`'s exact file, class,
and prompt shape (§9-§13); (3) `worker/analysis_main.py`/`worker/analysis_cycle.py`'s exact design,
mirroring Phase 12's own frozen worker shape; (4) the **three** new `Settings` fields (§20 —
`news_analysis_enabled`, `news_analysis_poll_interval_seconds`, `news_analysis_batch_size`,
`news_analysis_freshness_cutoff_hours`; no `max_daily_ai_cost`-style field); (5) the new Docker
service with its corrected (Redis-inclusive) dependency list (§21); (6) the explicit, verbatim
`CostTracker`/no-new-cost-setting decision (§8/§25 item 11) in the risk section, stated as a binding
decision, not an open caveat; (7) the exhaustive authorized file scope, including the narrow,
justified edit to the currently-frozen `workflows/runner.py`.

## 28. Final Verdict

All decisions necessary to proceed to an Architecture Contract are resolved, including both
previously-open human decisions (CostTracker remediation: deferred; `max_daily_ai_cost`: not
introduced — §8/§26). No human decision remains open. Phase 13's cost containment is fully specified
as deterministic and workload-based (48h freshness cutoff, batch size 5, sequential execution, 300s
polling, no backlog drain, no retry storm) — not monetary.

PHASE 13 DECISIONS FULLY RESOLVED — READY FOR ARCHITECTURE CONTRACT
