# Phase 9 + Phase 9.5 Completion Report

**Status: historical closure document. Not a contract, not a specification.** This document
records what Phase 9 (Research/Intelligence) and Phase 9.5 (Workflow Persistence Hardening)
actually built, at the point both were approved for closure. It does not authorize future work
and creates no new binding rule beyond what
`docs/phase9_research_intelligence_architecture_contract.md` and
`docs/phase9_5_workflow_hardening_architecture_contract.md` already froze.

---

## 1. Executive Summary

Phase 9 delivered the first real Research/Intelligence layer on top of Phase 8's Capability
framework: a deterministic Triage pipeline (Freshness + Triage + an atomic-claim Orchestrator)
that prioritizes newly-ingested `NewsEvent` rows, and two ordinary Phase 8 Capabilities
(`ResearchCapability`, `IntelligenceCapability`) that perform structured fact extraction and
editorial-significance judgment respectively. Phase 9 M7 discovered, while proving
Research→Intelligence step-chaining, that the frozen Phase 5 `WorkflowRunner` did not persist
step results until an entire step loop finished — meaning a later step in the same pass could
not see an earlier step's already-succeeded result.

Phase 9.5 closed exactly that gap: one additive, 12-line insertion into
`workflows/runner.py` that commits each step's outcome immediately after it completes, instead
of only at the end of the run. Nothing else about workflow semantics changed.

---

## 2. Architecture Overview

```
NewsEvent (status=NEW)
      |
      v
Triage Orchestrator  (Freshness + Triage, atomic claim, stale-recovery)
      |
      v
EditorialTask (created via services.workflow_service.create_task)
      |
      v
WorkflowRunner.run()
      |
      v
CapabilityExecutor  (StepExecutor bridge, Phase 6)
      |
      v
ResearchCapability  --step_results["research"]-->  IntelligenceCapability
```

**Per-step persistence (Phase 9.5)**, shown at the point it applies inside `WorkflowRunner`:

```
for step in remaining_steps:
    outcome = run_step(step)              # SUCCESS / SKIPPED / (required-FAILED -> _fail())
    state.completed_steps.append(step.name)
    # --- Phase 9.5's one new invariant ---
    state.step_results = step_results
    task.workflow = state.model_dump(mode="json")
    await session.commit()                # <- durable here, not only at loop-end
    # ---------------------------------------
# ... post-loop terminal commit (unchanged, pre-existing)
```

This is why `IntelligenceCapability`, reading `context.business.workflow_state.step_results`
via `CapabilityExecutor` (itself unmodified), now genuinely observes `ResearchCapability`'s
output within one uninterrupted `WorkflowRunner.run()` call.

---

## 3. Phase 9 Summary

### M0 — Architecture Validator Extension
- **Goal**: mechanically enforce Freshness/Triage/Orchestrator dependency isolation before any
  Phase 9 production file existed.
- **Result**: three new named-file rules added to `scripts/validate_architecture.py`.
- **Commit**: `75c32ed`

### M1 — Deterministic Triage Policy (Freshness + Triage)
- **Goal**: pure-function Freshness and Triage, zero DB/LLM access, explicit ordinal mapping for
  `TaskPriority` (avoiding the native string-comparison hazard).
- **Result**: `services/freshness.py`, `services/triage.py`.
- **Commit**: `b19e651`

### M2 — Atomic Claim + Stale-Recovery Primitives
- **Goal**: DB-level atomic `NEW→PROCESSING` claim and staleness-gated recovery-ownership
  acquisition, proven under real concurrent execution.
- **Result**: `services/triage_orchestrator.py` (primitives), `stale_processing_threshold_seconds`
  config field.
- **Commit**: `15e375d`

### M3 — Triage Orchestration Service + Script Entry Point
- **Goal**: compose M1 + M2 into the full find-work/claim/Triage/create-task cycle with explicit
  transaction discipline.
- **Result**: `services/triage_orchestrator.py` (completed), `scripts/run_triage.py`.
- **Commit**: `22af66d`

### M4 — ResearchCapability
- **Goal**: structured fact extraction from one `NewsEvent`'s existing text only — no external
  verification, browsing, or tool calls.
- **Result**: `capabilities/research_capability.py`, `prompts/research/v1.yaml`.
- **Commit**: `3b94392`

### M5 — IntelligenceCapability
- **Goal**: editorial-significance judgment from Research's output, consumed exclusively via
  `step_results` — never a direct import of `ResearchCapability`.
- **Result**: `capabilities/intelligence_capability.py`, `prompts/intelligence/v1.yaml`.
- **Commit**: `cc8bb2a`

### M6 — Registration / Boot Wiring
- **Goal**: register both Capabilities in `CapabilityRegistry` via the existing
  `build_registry()` pattern — smallest possible change.
- **Result**: `capabilities/registry.py`, a 4-line diff.
- **Commit**: `882315b`

### M7 — Integration Proof + Cross-Cutting Regression
- **Goal**: prove Research→Intelligence dispatch through the real, unmodified
  `CapabilityExecutor`/`WorkflowRunner`/`CapabilityRegistry` stack, via a synthetic workflow
  definition (never the real `NEWS_ANALYSIS`).
- **Result**: discovered the same-pass `step_results` propagation gap (documented, not fixed in
  Phase 9 — became Phase 9.5's own mandate). 667 tests passing at close.
- **Commit**: `9d51a1c`

---

## 4. Phase 9.5 Summary

### M1 — Per-Step Persistence Implementation
- **Goal**: implement the exact commit-point insertion the Contract specifies, and update the
  one existing test it invalidates in the same commit.
- **Result**: `workflows/runner.py` (+12 lines), `tests/test_phase9_research_intelligence_integration.py`
  (regression-lock assertion flipped to positive propagation), `tests/test_workflow_runner_per_step_persistence.py`
  (5 new tests). 672 tests passing.
- **Commit**: `e1cf9a8`

### M2 — Independent-Connection Durability Proof
- **Goal**: prove a step's per-step commit is durable to a genuinely independent database
  connection, not merely visible within the producing session.
- **Result**: one test added to `tests/test_workflow_runner_per_step_persistence.py`, reusing
  Phase 9 M2's own `independent_session_factory()`/`real_committed_event()` helpers. No
  production code changed. 673 tests passing.
- **Commit**: `07c6b51`

**The main fix, stated plainly**: `step_results` are now available to later steps within the
same `WorkflowRunner.run()` execution — the exact gap Phase 9 M7 discovered. Nothing about
workflow semantics changed; only the timing of an already-existing persistence operation.

---

## 5. Architectural Guarantees

Now genuinely provided and verified, end to end:

- ✅ Deterministic Triage (Freshness + Triage, zero LLM/DB access, explicit `TaskPriority`
  ordinal mapping)
- ✅ Atomic `NewsEvent` claiming (DB-level conditional `UPDATE`, staleness-gated recovery)
- ✅ Research → Intelligence `step_results` propagation, within one uninterrupted `run()` call
- ✅ Durable step persistence, proven cross-connection (Phase 9.5 M2)
- ✅ Capability isolation (no Capability imports another; mechanically enforced)
- ✅ Gateway-only LLM access (no provider SDK outside `integrations/llm_gateway/providers/`)
- ✅ `PromptRepository` ownership of all prompt content (no embedded prompt strings)

---

## 6. Explicit Non-Goals

Not implemented by Phase 9 or Phase 9.5 — stated explicitly, not merely absent:

- ❌ Crash recovery
- ❌ Workflow resume
- ❌ Scheduler / production automation
- ❌ Automatic retries after a process crash
- ❌ Final Editorial Ranking / Scoring completion
- ❌ Engagement Analysis
- ❌ Semantic clustering
- ❌ Embeddings / vector search
- ❌ Production newsroom automation of any kind

---

## 7. Known Limitations

Carried forward, none resolved by either phase:

- **Staleness-threshold operational constraint** (Contract §7.6): a healthy worker whose own
  claim-to-`create_task()` latency exceeds `stale_processing_threshold_seconds` can be raced by
  a stale-recovery attempt. Architectural, not a bug — no heartbeat/lease mechanism was added to
  close it.
- **`FAILED`/`COMPLETED` task-lifecycle limitation**: `_find_active_task()`'s `CREATED`/`RUNNING`-
  only definition of "active" means a `NewsEvent` whose task ever reaches a terminal status
  becomes recovery-eligible again once stale. No production call site currently exercises this
  path, but it must be revisited before any future scheduling phase relies on it.
- **`WorkflowRunner` crash limitation**: a process crash mid-run still leaves the task `RUNNING`
  and permanently unresumable via `run()`'s unconditional guards — Phase 9.5 improved
  *mid-run visibility* of progress, not *resumability* after interruption. Explicitly disclosed,
  not silently left open.
- **Repo-wide mypy baseline issue**: `tests/fakes/fake_provider_adapter.py` module-collision
  error (`mypy .` fails immediately on it) — pre-existing since before Phase 9, unrelated,
  never touched by either phase.

---

## 8. Testing Summary

| Milestone | Full-suite pytest count |
|---|---|
| Phase 9 (through M7) | 667 passed |
| Phase 9.5 M1 | 672 passed (+5 new) |
| Phase 9.5 M2 (final) | 673 passed (+1 new) |

**Quality gates, both phases, final state**:
- `ruff check .` — all checks passed
- `python -m scripts.validate_architecture` — clean, 0 forbidden-dependency violations
- `mypy` (targeted, every new/changed file across both phases) — no issues found
- `mypy .` (repo-wide) — fails only on the pre-existing `fake_provider_adapter.py` baseline
  collision (§7), unrelated to and unchanged by either phase

---

## 9. Future Phase Requirements

What a future phase must account for before building on top of Phase 9/9.5:

1. **Workflow scheduling** — no production trigger exists for `scripts/run_triage.py` or for
   driving `WorkflowRunner.run()` automatically; must be designed and added.
2. **Crash recovery** — `WorkflowRunner`'s per-step persistence (Phase 9.5) makes progress
   *visible* mid-run but not *resumable*; a real resume path requires revisiting `run()`'s
   `TaskAlreadyRunningError` guard and the task-lifecycle model.
3. **Real `NEWS_ANALYSIS` completion** — `engagement_analysis` and `scoring` (the real
   `ScoringCapability` does not satisfy `NEWS_ANALYSIS`'s scoring step) remain unregistered;
   the real workflow still ends `FAILED`.
4. **Ranking engine** — Final Editorial Ranking / the full Scoring specification
   (`docs/08_Database_Schema_Data_Models.md` §14) is not built.
5. **Engagement analytics** — no engagement-data collection or `EngagementAnalysisCapability`
   exists.

---

## 10. Final Status

PHASE 9 COMPLETE

PHASE 9.5 COMPLETE

READY FOR NEXT ARCHITECTURE DISCUSSION
