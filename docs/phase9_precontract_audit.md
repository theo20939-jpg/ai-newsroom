# Phase 9 — Final Adversarial Pre-Contract Audit

**Status: review document. NOT a specification. NOT binding.** This document audits
`docs/phase9_research_intelligence_discovery.md` and `docs/phase9_decision_resolution.md`
adversarially — it does not treat either as automatically correct, and it does not modify either
file. No production code, migration, or frozen Phase 6–8 contract is touched. Several claims below
were verified by reading files neither prior document cited (`workflows/runner.py`,
`workflows/registry.py`, `schemas/workflow.py`, `services/workflow_service.py` in full) — this
audit does not simply re-summarize the prior two documents.

---

## 1. Executive Summary

The core idea — deterministic Triage gating `ResearchCapability`/`IntelligenceCapability` — is not
architecturally invalid. But three mechanical facts, none flagged by either prior document, make
the boundary **as currently described** unsafe to freeze into a Contract without an explicit
decision:

1. **`WorkflowStepDefinition.required` defaults to `True`, and every step in the frozen
   `NEWS_ANALYSIS` definition uses that default** (`workflows/definitions/news_analysis.py`
   passes no `required=` override for any of its four steps;
   `schemas/workflow.py:52` — `required: bool = True`). Mechanically, registering only `research`
   and `intelligence` Capabilities means running the **real, unmodified** `NEWS_ANALYSIS`
   workflow through `WorkflowRunner` will **always** fail at the `engagement_analysis` step
   (`workflows/runner.py:163-172`: a required step's failure ends the task as `FAILED`, full
   stop). This is not a risk — it is what the code does today, traced line by line.
2. **`WorkflowRegistry.register()` allows exactly one `WorkflowDefinition` per `WorkflowType`
   name**, not per `(name, version)` as its own docstring implies (`workflows/registry.py:49-54`:
   `existing = self._definitions.get(definition.name)` — keyed by name alone). There is no clean
   "register a v2 alongside v1" escape hatch. Any change to `NEWS_ANALYSIS`'s step list requires
   either editing the frozen definition file in place, or adding a new `WorkflowType` enum member
   to frozen `schemas/workflow.py` — both are real modifications to committed Phase 5 code, not
   free options.
3. **No test or production code has ever run the real `workflows/definitions/news_analysis.py` or
   `content_generation.py` definitions through `WorkflowRunner`** (grep-confirmed, zero matches).
   Every Phase 8 end-to-end test built its own synthetic, single-step `WorkflowDefinition`. Phase 9
   would be the first phase to attempt the real multi-step definition — on exactly the one that
   currently cannot complete.

A fourth, independent finding (Section 12) shows `docs/05`'s **Opportunity Score** — included in
Decision Resolution's proposed Triage formula — has an unacknowledged partial dependency on
cross-source counting, which is clustering, which is explicitly deferred. Roughly half of
Opportunity's own named sub-inputs cannot be computed in Phase 9 as specified.

None of this invalidates the boundary's core shape. It does mean **"Phase 9 = Triage + Research +
Intelligence, safely testable" is currently an overclaim** until two explicit decisions are made:
how the workflow-completion mismatch is handled, and how far "Opportunity" is honestly scoped.

---

## 2. Triage Ownership Audit

**Challenged against every option the task lists, using the actual repository:**

- **Service**: `services/collector.py`'s own module docstring: *"Contains no AI, scoring, ranking
  or content generation logic - orchestration only."* The Collector explicitly, deliberately
  excludes ranking from its own responsibility. Triage cannot live inside `run_collection_cycle()`
  or `_process_source()`/`_process_item()` without violating that boundary's own stated intent —
  **REJECTED as a Collector-internal responsibility**, but a **new, separate `services/` module**
  (same package, new file, analogous in shape to `services/cost_estimator.py`) is exactly right.
- **Capability**: rejected — Triage has no LLM call, no `GenerateRequest`, no
  `PromptRepository` need; wrapping it in the Capability Protocol for no reason would be
  ceremony without function, and `scripts/validate_architecture.py`'s `capability-isolation` rule
  would immediately flag it for importing whatever deterministic scoring inputs it needs from
  `services/` (forbidden for real Capability files).
- **Workflow step**: rejected, and for a more serious reason than "wrong shape" — `WorkflowStepDefinition`
  requires a `capability` string resolved through `CapabilityRegistry`
  (`capabilities/executor.py:86`); Triage is not a Capability and must run **before** any
  `EditorialTask`/workflow instance exists at all (it decides whether one gets created). It
  structurally cannot be a step inside the workflow it is gating.
- **Source-collector stage**: rejected, same reasoning as "service" above — the Collector's own
  docstring forbids this.
- **Pre-workflow gate**: **this is the correct shape**, but it is not free — see below.
- **Task-creation policy (inside `workflow_service.create_task()`)**: rejected on inspection of
  the real function (`services/workflow_service.py:27-78`). `create_task()` is explicitly scoped
  ("Scoped to exactly two functions - create_task() and get_task()," module docstring line 3) and
  takes `priority` as an already-decided input from its caller — it does no scoring today and
  adding any would violate its documented single responsibility and its `frozen=True`
  `EditorialTaskCreate` input contract, which has no field for Triage's own explanatory output.

**Direct answers**:
- **Who calls Triage?** Not `create_task()` itself. Something must call Triage, then call
  `create_task(..., priority=<Triage's recommendation>)`. **This caller does not exist today.**
  Grep confirms zero production callers of `create_task` at all (only `services/workflow_service.py`
  itself and `tests/`). Building this caller is **unavoidable new code** — small (a loop over
  newly-collected `NewsEvent`s, calling Triage then `create_task`), but genuinely new, not a
  reuse of an existing orchestration point. The task's instruction to "not invent a new
  orchestration layer unless unavoidable" is directly tested here: it is unavoidable, because no
  existing code connects "a `NewsEvent` was collected" to "an `EditorialTask` should exist" at
  all, independent of anything Phase 9 does.
- **What object does Triage receive?** A `NewsEvent` (plus, to compute Authority, its `NewsSource`
  — either passed in or resolved by the caller and passed as a value, never a live session held
  by Triage itself, mirroring `CostEstimator`'s pattern of receiving already-loaded data).
- **What object does it return?** A plain value object (score + priority recommendation +
  explanation breakdown) — never an ORM row, never something it writes itself.
- **Does Triage persist anything?** No — same discipline as `services/cost_estimator.py`, a pure
  function.
- **Does Triage create `EditorialTask`?** No.
- **Does Triage decide whether `EditorialTask` is created?** No — it *informs* that decision.
  **The new, minimal caller described above makes the actual creation decision**, using Triage's
  output plus whatever else is relevant (e.g., `docs/05` §12's Editorial Budget, which is
  `BudgetGuard`'s domain, not Triage's).

---

## 3. Frozen Workflow Compatibility

Testing all four possibilities the task lists, against the actual code:

- **A — Triage happens before `EditorialTask` creation.** Mechanically sound and requires zero
  change to `workflows/`. This is the *only* option that touches nothing frozen. It is what
  Section 2 concludes for Triage's placement.
- **B — Triage becomes a new workflow step.** Rejected in Section 2 (structurally incompatible —
  Triage must run before the `EditorialTask`/workflow instance it would be "a step of" exists).
- **C — Triage happens inside `ResearchCapability`.** Rejected: this would make the *first* LLM
  call happen unconditionally for every publication before any gating occurs, defeating Triage's
  entire cost-control purpose, and would violate `capabilities/executor.py`'s established pattern
  where `CapabilityExecutor` (not the Capability itself) is the only thing that decides *whether*
  a step runs.
- **D — Workflow orchestration invokes Triage before entering the existing step sequence.**
  Equivalent to A in effect, but implies `WorkflowRunner` itself gains gating logic — rejected,
  since `WorkflowRunner`'s own module docstring states it "has zero knowledge of any concrete
  Capability" and interacts with steps only through the generic `StepExecutor` protocol; teaching
  it about a pre-step gate would be new `WorkflowRunner` behavior, which the task's own list of
  forbidden actions (Section on scope leakage, and the earlier instruction not to redesign the
  Workflow Layer) rules out.

**A is the only option compatible with the frozen architecture without modifying it.**

**Hidden duplication of orchestration responsibility — found**: none between Triage and
`WorkflowRunner`/`CapabilityExecutor` (A cleanly avoids this, per above). **However**, a *different*
duplication risk exists and neither prior document flagged it: if Triage's new caller is built as
an ad hoc script rather than living clearly inside `services/`, its responsibility ("decide
whether/at what priority to create work") overlaps conceptually with what `docs/05` §12's
Editorial Budget table describes as `BudgetGuard`'s domain (available AI budget affecting how much
processing a priority tier gets). These are two different concerns (Triage: per-item score;
Budget: system-wide spend ceiling) that must stay separate, but a careless implementation could
blur them into one "decide everything" orchestration function — worth an explicit Contract-phase
boundary statement, not an architecture blocker.

---

## 4. Phase 9 Completion Boundary

**Direct test, traced mechanically through `workflows/runner.py`**: if only `research` and
`intelligence` are registered (leaving `engagement_analysis` unregistered, exactly as both prior
documents propose), running `WorkflowRunner.run()` against a real `NEWS_ANALYSIS`-typed
`EditorialTask` produces, step by step:
1. `research` — `CapabilityExecutor.execute()` resolves it (newly registered), succeeds →
   `WorkflowStepResult(status="SUCCESS")`.
2. `intelligence` — same, succeeds.
3. `engagement_analysis` — `capabilities/executor.py:80-90`: `resolve_ai_capability("engagement")`
   succeeds (Amendment A's alias to `AICapability.INTELLIGENCE` still resolves the *persistence
   mapping*), but `CapabilityRegistry.resolve("engagement")` raises `UnknownCapabilityError`
   (never registered) → re-raised as `PermanentStepFailureError` → `workflows/runner.py:163-172`:
   since `step.required` is `True` (the unmodified default), this is **not** treated as skippable
   → `_execute_steps` calls `self._fail(...)` → **`task.status = TaskStatus.FAILED`**, permanently,
   with `state.failure = {"step": "engagement_analysis", ...}` persisted into
   `EditorialTask.workflow`.
4. `scoring` is never reached — irrelevant that Phase 8 already registered it.

**Is the workflow "partially executable"?** Only in the sense that two of four steps run and
succeed before the third fails — the task's terminal state is `FAILED`, identically to a task
that failed on its very first step. There is no partial-success state in this system; `TaskStatus`
is binary at completion (`COMPLETED` or `FAILED`).

**"Non-executable end-to-end"?** Correct characterization — the real `NEWS_ANALYSIS` workflow,
unmodified, cannot reach `COMPLETED` once Phase 9 registers only two of its four steps (it
already cannot today, since none of the four are registered — Phase 9 only moves the failure
point from step 1 to step 3).

**"Safely testable in isolation"?** Yes, but only if "isolation" means testing each Capability
directly via `CapabilityExecutor`/`build_registry()` with a **synthetic** single- or two-step
`WorkflowDefinition** — exactly Phase 8's own, never-deviated-from precedent (confirmed: zero
existing tests import the real `workflows.definitions` modules). This is safe, proven, and
requires no change to anything frozen.

**"Misleadingly described as integrated"?** Decision Resolution's Section 8 end-to-end flow
diagram is the clearest example: it shows `research → intelligence → [engagement analysis, out of
scope] → scoring / final ranking → editorial decision` as a continuous flow with only a labeled
gap, which reads as "the pipeline continues past the gap." **It does not** — the real workflow
halts and fails at that gap, it does not flow around it. This is the overclaim this audit was
asked to find.

**Honest completion boundary (this document's finding, not present in either prior document)**:
Phase 9 proves `ResearchCapability` and `IntelligenceCapability` are correct and reachable via
`CapabilityExecutor` **against synthetic test workflows**, mirroring Phase 8 M3/M4 exactly. Phase
9 explicitly does **not** claim the real `NEWS_ANALYSIS` `WorkflowType` reaches `COMPLETED`
end-to-end, because with the current frozen definition it mechanically cannot, and Phase 9's own
excluded scope (`engagement_analysis`, Scoring enhancement) does not change that. If a real,
`WorkflowRunner`-driven, `NEWS_ANALYSIS`-typed completion proof is wanted, that requires an
explicit, disclosed decision (see Section 14) to either mark `engagement_analysis`/`scoring` as
`required=False` in the frozen definition file, or introduce a new `WorkflowType`. Silently doing
either inside Contract drafting, without calling it out as a frozen-file modification, would
repeat this audit's central finding.

---

## 5. Research vs Intelligence Responsibility Audit

| | `ResearchCapability` | `IntelligenceCapability` |
|---|---|---|
| **INPUT** | `CapabilityContext.business.news_event` (title, category, content — `summary` is always `None`, confirmed: `services/collector.py` never sets it) | Same `CapabilityContext`, **plus** `context.business.workflow_state.step_results["research"]` (the first real exercise of this existing-but-never-used Phase 6 mechanism) |
| **OUTPUT** | Facts extracted/organized from the given text, a confidence signal on that extraction — shape inspired by (not required to literally match) `docs/08` §12: `facts`, `sources` (as referenced in-text, not externally verified — see below), `contradictions` (internal, within the given text), `confidence_score` | Importance/significance judgment, audience angle, recommendation — shape inspired by `docs/08` §13: `importance`, `angles`, `recommendation`, `confidence` |
| **RESPONSIBILITY** | Fact-finding / extraction from what was already collected | Editorial judgment about what the extracted facts mean and why they matter |
| **MUST NOT DO** | Must not judge importance, audience fit, or editorial angle — that is Intelligence's job. Must not claim external fact-verification it cannot perform (see below). | Must not re-extract or re-summarize facts from raw text — it consumes Research's already-extracted facts, not the raw `NewsEvent.content` a second time from scratch |

**A scope-honesty finding neither prior document stated explicitly**: without tool integration
(explicitly deferred, per `docs/phase8_capability_contract.md` and Discovery's own exclusions),
`ResearchCapability` **cannot verify facts against any external source** — it can only extract,
organize, and flag internal-consistency/confidence on the single `NewsEvent.content` string it is
given. Calling this "Research" in the deep sense (cross-checking claims against other sources) is
not something Phase 9 can honestly deliver. It is closer to **structured fact extraction**. This
should be named precisely in the Contract, not left implied by the word "Research."

**Should they be one Capability?** Challenged directly, per the task's instruction not to
preserve two components merely because Phase 5 named two steps:
- **Genuine task distinctness**: fact-extraction and editorial-importance-judgment are different
  cognitive tasks; folding them into one prompt risks letting "why this matters" bias "what is
  actually true," a real and known failure mode in single-pass reasoning, not a hypothetical one.
- **A mechanical reason, independent of task-distinctness**: `workflows/definitions/news_analysis.py`
  names `research` and `intelligence` as two separate `capability` strings. If one merged
  Capability is registered under only *one* of those two names, the *other* step is still
  unregistered and still fails the workflow — reproducing exactly Section 4's `engagement_analysis`
  problem for whichever name is left out. Registering the **same object instance under both
  names** avoids that failure mechanically, but produces two `WorkflowStepResult`s and two
  `AIExecution`-shaped records for what is actually one underlying LLM call — a cost/audit
  double-count and a misleading `CapabilityCall` history. **This is a real architecture smell any
  merge would introduce**, not just a coherence preference.
- **Cost, at ~1000/day**: doubling calls matters (Section 11), but the fix for that is Triage
  filtering the *input* volume, not merging two genuinely different judgments into one call and
  accepting the bias/audit risk above.

**Conclusion: two genuinely separate Capabilities remain justified** — for reasons independent
of, and stronger than, "Phase 5 already named two steps."

---

## 6. Available Triage Signals

Verified directly against `database/models/news_event.py`, `database/models/news_source.py`,
`schemas/source_definition.py`, and every source adapter — no assumption of unavailable data:

| Signal | Available today? | Source |
|---|---|---|
| Publication timestamp | Yes (`published_at`, nullable) / Yes (`collected_at`, never null) | `NewsEvent` |
| Source identity | Yes | `NewsEvent.source_id` → `NewsSource` |
| Source reliability | Yes, statically populated at import | `NewsSource.reliability_score` |
| Source's own declared category/tags | Yes, but **per-source**, not per-item | `NewsSource.category: str \| None`; `SourceDefinition.tags`/`.category` (config-level, richer) |
| Title | Yes, but naive (first line of text, capped at 120 chars) | `NewsEvent.title`, via `services/cleaning.py:57-65` |
| Summary | **No — always `None`.** Never populated by any adapter or `services/cleaning.py`. | Confirmed by grep: zero writers |
| Content/text length | Yes, derivable from `NewsEvent.content` | `NewsEvent` |
| Exact-dedup state | Yes (implicit — Triage only ever sees already-deduplicated rows) | `services/deduplication.py` |
| Per-item category classification | **No — always `UNKNOWN`.** | `services/collector.py:156` |
| Engagement metrics (views/reactions/etc.) | **No, for any source type** | Section 5 of `docs/phase9_decision_resolution.md`, re-confirmed unchanged |
| Number of independent sources covering this story | **No — requires clustering** | No clustering construct exists |

**Sufficiency assessment**: Freshness (timestamp) and Authority (`reliability_score`) are fully,
reliably available today — sufficient for a genuinely meaningful, if narrow, Triage signal.
**Opportunity, as `docs/05` fully defines it, is not fully available** — see Section 12's finding.
A per-item category proxy is only weakly available (inherited from the *source's* declared
category/tags, not verified per item) — usable as a coarse signal, not a precise one, and should
be labeled as such if used at all.

**Verdict**: Triage can make a **meaningful but narrow** decision today — Freshness + Authority
alone are real, reliable, already-existing signals. Claiming a fuller "Raw Score" (as `docs/05`
names it) would require either inventing data that does not exist or silently narrowing what
"Opportunity" means without saying so (exactly Section 12's finding).

---

## 7. Triage Failure-Mode Analysis

**Challenged options**:
- **Hard DROP** (no `EditorialTask` ever created, and no future reconsideration mechanism):
  rejected. `NewsEvent` rows are never deleted by anything in this codebase, so the underlying
  data always survives — but a silent, permanent decision to never automatically process it is
  the exact false-negative risk the task named, and nothing today would ever revisit that
  decision automatically.
- **Priority tiers, always creating a task** (Decision Resolution's own recommendation):
  reversible in the sense that matters most — nothing is silently discarded from the pipeline;
  `docs/05` §12's own Editorial Budget table already describes Priority C as "Минимальный," not
  "zero," meaning even the lowest tier gets *some* processing under the original design's own
  intent.
- **PASS/DEFER** (some items get no task now, but are queued for reconsideration later): requires
  a new tracking mechanism ("remember to re-look at this") that does not exist and is not free to
  build — more machinery than the always-create-with-priority option for no proven benefit at
  1000/day scale.
- **Budget-aware sampling** (randomly process a fraction of low-priority items): introduces
  non-determinism, directly conflicting with `docs/05` §2's explicit "reproducible" requirement.
  Not justified without evidence that deterministic priority tiering alone is insufficient for
  cost control — no such evidence exists yet.

**Recommendation (reaffirming, not contradicting, Decision Resolution, now with the reversibility
argument made explicit)**: Triage **always** results in an `EditorialTask` being created; it only
ever affects **priority**, never existence. This is the most reversible option available without
new infrastructure, and it is the one already implied by `docs/05` §11-12's S/A/B/C + budget
design.

---

## 8. Freshness Audit

Re-auditing Decision Resolution's Decision 1, checking edge cases it did not address:

- **`published_at` nullable behavior**: correctly handled (fallback to `collected_at`, flagged).
- **`collected_at` fallback**: sound — `DateTime(timezone=True), server_default=func.now()`,
  never null (`database/models/news_event.py:55-57`).
- **Timezone assumptions**: both columns are `DateTime(timezone=True)` — timezone-aware storage is
  guaranteed at the DB level. Freshness computation must compare against a timezone-aware `now()`
  (matching the established `datetime.now(timezone.utc)` convention already used throughout
  Phase 7/8, e.g. `capabilities/gateway_call.py`). **Not previously stated explicitly by either
  prior document** — worth freezing as an implementation-consistency rule, not a product question.
- **Future timestamps**: **not addressed by either prior document.** A malformed feed, clock skew,
  or a scheduled/pre-dated post could produce a `published_at` in the future, yielding a negative
  age. Recommendation: clamp age to zero (treat any non-positive age as the most-fresh tier),
  never a negative bucket — deterministic, safe, simple, and should be frozen as a correctness
  rule, not left to configuration.
- **Stale imported content**: correctly bucketed as "48h+" for genuinely old items — not a bug.
  But a **new nuance neither prior document raised**: not every implemented source type is
  "breaking news" in nature. `arxiv_source.py`/`github_source.py` content (papers, releases) is
  not perishable the way a Telegram post is; scoring it on the same breaking-news freshness decay
  as `docs/05` implicitly assumes may not be meaningful. **OBSERVATION, not blocking** — a
  candidate for source-type-aware freshness weighting in a later refinement, not required for
  Phase 9's MVP.
- **Deterministic reproducibility**: "deterministic" here must mean *rule-based, no randomness, no
  LLM* — **not** "produces an identical result forever." Freshness legitimately changes over time
  for the same `NewsEvent` (that is the entire point of a decay signal), unlike Authority
  (source-level, stable) or exact-dedup (permanent). Neither prior document stated this precision;
  worth freezing explicitly so "deterministic" is not misread as "idempotent" during Contract
  drafting.

**What must be frozen vs. left as configuration**: the *behavioral/correctness rules* — the
`published_at`→`collected_at` fallback, the negative-age clamp, and the timezone-aware comparison
requirement — should be frozen (they are about correctness, not tuning, and getting them wrong is
a bug, not a product preference). The six bucket boundaries and their numeric weights should
remain configuration, per `docs/05` §14's own explicit principle, already correctly identified by
Decision Resolution.

---

## 9. Republication-Check Audit

**Does it duplicate existing dedup responsibility?** No. Exact dedup is keyed on `(source_id,
external_id)` (`services/collector.py:173-179`) — it only ever catches the *same item re-fetched
from the same source*. Title-overlap operates *across* different `(source_id, external_id)`
pairs entirely — a structurally different check, not a restatement of the existing one.

**Is it useful without clustering?** Modestly, yes — it has a real, if narrow, target: near-verbatim
republication (e.g., wire-service content republished across multiple RSS feeds with only minor
edits), a genuinely observable pattern for the RSS-heavy source roster this repository already
implements. Its recall for genuine cross-source *paraphrased* coverage of the same story is
effectively zero — that needs semantic understanding, unchanged from Discovery's conclusion.

**False-positive risk — a concern neither prior document weighed**: the implemented
`EventCategory` roster (AI, TECH, STARTUPS, etc.) is a domain with notoriously **formulaic
headlines** ("X releases Y," "X raises $N"). A naive title-token-overlap check risks flagging two
genuinely *different* stories that merely share common phrasing as "possible republication." This
is a real, evidence-grounded risk specific to this content domain, not a generic caveat.

**Recommendation**: keep it in Phase 9 scope, but strictly as a **low-weight, non-blocking input**
to Triage's priority computation — never a hard filter, never presented as "novelty" (reaffirming
Decision Resolution's own naming discipline), and its false-positive risk is itself a second,
independent argument (beyond Section 7's general reversibility principle) for never letting it
cause a hard drop.

---

## 10. Persistence Audit

Re-auditing Decision Resolution's "no new model needed" claim:

- **Triage result**: Decision Resolution is correct that the *consequence* (a chosen
  `EditorialTask.priority` value) needs no new persistence — that column already exists. **Not
  fully addressed by either prior document**: the *breakdown* (why this priority — which
  Freshness bucket, which Authority value, whether the republication flag fired) is not persisted
  anywhere if only the final enum value is written. `docs/05` §2/§13's "Explainable Ranking"
  principle asks for exactly this breakdown to be *available*, not merely computed and discarded.
  For Phase 9's MVP, **structured logging** (mirroring the `capability_call_failed`-style pattern
  already established in `capabilities/scoring_capability.py`) is a reasonable, evidence-consistent
  way to satisfy this without a new table. Whether the product actually wants this breakdown
  **queryable** later (not just grep-able in logs) is a real, open, deferred product question —
  flagged explicitly rather than silently assumed either way.
- **Research output / Intelligence output**: confirmed, unchanged from Discovery/Decision
  Resolution — `CapabilityResult.structured_output` flows into `EditorialTask.workflow`'s JSON
  `step_results`, an already-existing mechanism, no new model required for Phase 9's proposed
  scope.
- **`AIExecution` cost-audit gap**: re-flagged with sharper urgency than either prior document
  gave it. Phase 8's two Capabilities made only minimal, test-scale LLM calls; Phase 9 would be
  the first phase making **real, volume-bearing** LLM calls (up to 2000/day pre-Triage, per
  Section 11) with **zero** cost-audit write path (`services/ai_execution_mapper.py` maps but
  never writes, per Amendment B). This does not block Phase 9's Capability-building work, but it
  is a materially bigger gap once real cost is actually being incurred at volume, versus Phase
  8's proof-of-mechanism scale.

**No new database model or migration is required for the boundary as re-scoped in Section 4
(Capability-level proof, not real-workflow completion).** If a future decision requires the real
`NEWS_ANALYSIS` workflow to actually complete (Section 4/14), that decision is about the frozen
workflow definition, not about persistence — it introduces no new table either.

---

## 11. Cost / Call-Volume Analysis

Structural modeling at ~1000 publications/day, per the task's explicit pass-rate examples:

| Scenario | Research calls/day | Intelligence calls/day | Total/day |
|---|---|---|---|
| No Triage (100% reach AI) | 1000 | 1000 | 2000 (up to ~4000 worst-case with M5-style correction retries) |
| Triage pass rate 50% | 500 | 500 | 1000 |
| Triage pass rate 25% | 250 | 250 | 500 |
| Triage pass rate 10% | 100 | 100 | 200 |

**Are two LLM calls per accepted publication justified?** Yes, conditional on Triage actually
filtering meaningfully — Section 5's argument (genuine task distinctness, avoiding the
double-registration/double-audit smell a merge would introduce) holds independent of exact pass
rate. The *number* of calls per accepted item (2) is justified; the *total* daily volume is
entirely a function of how much Triage actually filters, which is not yet known (no real pass-rate
data exists — this document does not fabricate one, consistent with Discovery's own instruction
not to produce ungrounded numbers).

**Deterministic preprocessing**: Triage itself *is* this — already accounted for, not an
additional opportunity beyond what's proposed.

**Batching**: **not recommended without stronger evidence.** Each `NewsEvent` is analyzed
independently today; batching multiple items into one prompt would compromise per-item
auditability and break the established "one `CapabilityCall` = one Gateway invocation" pattern
(`schemas/capability.py`'s own binding rule, unchanged since Phase 6). No evidence in either prior
document or this audit's own findings supports the added complexity yet — correctly *not*
proposed by either prior document, and this audit does not propose it either.

**Single-call structured output**: already true — each Capability's `response_mode="json_schema"`
already returns one structured result per call; no redesign needed.

---

## 12. Scope-Leakage Audit

Systematically checked against every item the task lists:

| Deferred system | Hidden dependency found? |
|---|---|
| Semantic event clustering | Explicitly and correctly deferred by both documents |
| Embeddings / vector DB | Explicitly and correctly deferred |
| Engagement data collection | Explicitly and correctly deferred (Decision Resolution's Section 5) |
| Final ranking / Scoring enhancement | Explicitly and correctly deferred (this audit's Section 4 reinforces why) |
| Source reputation *system* (dynamic history) | Correctly avoided — only the static, already-populated `reliability_score` is used, never a dynamic/historical Authority score requiring new tracking |
| Persistent intelligence graph | Not present in either document — clean |
| Web research agents / autonomous loops | Explicitly and correctly excluded per the master task constraints |
| New Workflow Engine behavior | **Found, not previously flagged** — see Section 3/4: any attempt to make the real `NEWS_ANALYSIS` workflow reach `COMPLETED` in this phase requires either new `WorkflowRunner`-adjacent behavior or a frozen-file edit; the proposed boundary must NOT silently assume this is free |

**A genuinely new finding not on the task's own checklist**: **`docs/05`'s "Opportunity Score,"
included in Decision Resolution's proposed Triage formula, has a hidden, unacknowledged
dependency on clustering.** Re-reading `docs/05` §4.3 precisely, Opportunity's named sub-inputs
are: *возраст новости* (age — computable today), *количество источников* (**number of
sources** — requires knowing which `NewsEvent`s cover the same story, i.e. clustering),
*скорость распространения* (**spread velocity** — same dependency), *динамика роста
вовлечённости* (engagement growth dynamics — requires engagement data, also deferred), *вероятность
быстрого роста интереса* (probability of rapid growth — derived from the above, same dependency),
*наличие свободного информационного окна* (a vague, undefined "open information window" concept,
not concretely computable from any current field). **Only the age sub-input is actually
computable today.** Decision Resolution's Section 9 "Ready to Freeze" list includes "Freshness +
Authority + Opportunity" in the MVP Raw Score without flagging that "Opportunity" as named in the
source spec is roughly five-sixths blocked on deferred systems.

**This is the audit's single most important scope-leakage finding.** It means the proposed Triage
formula, as currently described, silently claims a component ("Opportunity") it cannot actually
deliver in full. Either the Contract must rename/rescope this to something honest (e.g., an
explicit "age-decay component," not "Opportunity Score"), or Opportunity must be dropped from
Phase 9's Triage formula entirely, leaving Freshness + Authority only, with Opportunity's fuller
form explicitly deferred alongside clustering and engagement collection.

---

## 13. Contract-Ready Decisions

Carried forward from Decision Resolution where this audit found no defect, plus this audit's own
additions:

1. Freshness anchor = `published_at`, falling back to `collected_at` when null, fallback flagged.
2. Freshness computed as ordered, monotonically-decreasing-weight tiers over the six named
   windows; exact weights are configuration.
3. Freshness computation must use timezone-aware comparison against the existing
   `datetime.now(timezone.utc)` convention (this audit's addition).
4. Freshness must clamp negative age (future timestamps) to the most-fresh tier, never a negative
   bucket (this audit's addition).
5. Novelty is not achievable pre-clustering; only a title-overlap republication proxy is
   achievable, and it must never be labeled "novelty."
6. The republication proxy is a low-weight, non-blocking Triage input only, never a hard filter
   (this audit sharpens Decision Resolution's framing with the formulaic-headline false-positive
   risk as explicit justification).
7. `EditorialTask.priority` remains creation-time-only (Option B); no mutation pathway is added.
8. Triage is a pure, stateless, non-persisting computation (`services/`, new module), architecturally
   identical in shape to `services/cost_estimator.py`.
9. Triage always results in an `EditorialTask` being created — it affects priority only, never
   existence (no hard drop).
10. `ResearchCapability` and `IntelligenceCapability` remain two separate Capabilities, justified
    independently of Phase 5's step-naming (this audit's Section 5 argument).
11. `ResearchCapability` must be scoped honestly as fact-*extraction* from given text, not
    external fact-*verification* (no tool integration in this phase) — this audit's addition.
12. No new database model or migration is required for the Capability-level proof scope (Section
    4's re-scoped boundary).

## 14. Remaining Decisions

**BLOCKER — must be resolved before Contract**:
- **How Phase 9 handles the real `NEWS_ANALYSIS` workflow's non-completability** (Section 4).
  Options, none free: (a) accept that Phase 9 proves Capabilities only via `CapabilityExecutor` +
  synthetic test workflows, never claiming the real workflow completes; (b) explicitly authorize
  marking `engagement_analysis`/`scoring` as `required=False` in the frozen definition file; (c)
  explicitly authorize a new `WorkflowType` enum member for a Phase-9-scoped parallel workflow.
  This document recommends (a) as the only option requiring zero frozen-file changes, but does not
  have the authority to choose on the reader's behalf.
- **Whether "Opportunity Score" is dropped from Phase 9's Triage formula or explicitly rescoped to
  its age-only sub-component** (Section 12). Shipping it unscoped, as currently described, would
  overclaim.

**IMPLEMENTATION DETAIL — Contract can define the boundary and leave this open**:
- Exact numeric Freshness/Authority weights and Editorial Priority thresholds.
- Exact title-similarity algorithm/threshold for the republication check.
- Exact `ResearchCapability`/`IntelligenceCapability` output JSON Schema field names (the
  `docs/08` §12-13 shapes are inspiration, not a binding requirement).
- Whether the Triage-explanation breakdown is logged only or made queryable (Section 10).

**PRODUCT CONFIGURATION — should remain configurable, per `docs/05` §14's own principle**:
- All score weights and priority thresholds.
- Freshness bucket boundaries (the six windows themselves could, in principle, also be tuned
  later, though this document does not recommend changing them from the task's stated values for
  the MVP).

**DEFERRED — explicitly outside Phase 9, unchanged from Decision Resolution**:
- Semantic clustering, embeddings/vector search, engagement-data ingestion, `AIExecution` real
  write path, Amendment A's `"engagement"` resolution, Scoring enhancement.
- The production trigger connecting Collector cycles to Triage's new caller (Section 2) — Phase 9
  can ship with this manually/test-invoked, same as `create_task()` already is today.

---

## 15. Findings by Severity

**CRITICAL**:
- The real, frozen `NEWS_ANALYSIS` `WorkflowDefinition` mechanically cannot reach `COMPLETED`
  with only `research`+`intelligence` registered — `engagement_analysis`'s `required=True` default
  guarantees `PermanentStepFailureError` → task `FAILED` every time (Section 4). Decision
  Resolution's end-to-end flow diagram (its Section 8) reads as if the pipeline continues past this
  point; it does not.
- `docs/05`'s "Opportunity Score," as included in the proposed Triage formula, is roughly
  five-sixths dependent on deferred clustering/engagement infrastructure and cannot be computed as
  specified in Phase 9 (Section 12).

**MAJOR**:
- `WorkflowRegistry` allows exactly one definition per `WorkflowType` — there is no free
  "register a v2" escape hatch; any workflow-completion fix touches a frozen file (Section 1, 3).
- No existing test or production code has ever exercised the real multi-step workflow definitions
  through `WorkflowRunner` — Phase 9 is the first attempt, on the one guaranteed to fail as-is
  (Section 1, 4).
- Triage has no existing caller and needs new (small, unavoidable) orchestration code —
  correctly anticipated as an open item by Decision Resolution, but not stated with this much
  mechanical certainty (Section 2).

**MINOR**:
- Freshness edge cases (future timestamps, timezone-aware comparison, non-idempotent
  "determinism") were not addressed by either prior document (Section 8).
- Republication-check false-positive risk from formulaic tech-news headlines was not weighed
  (Section 9).
- Triage's explanation breakdown has no persistence story beyond logging (Section 10).
- `ResearchCapability`'s inability to externally verify facts (no tool integration) should be
  named explicitly rather than implied by the word "Research" (Section 5).

**OBSERVATION**:
- Not every implemented source type is "breaking news" in nature (arXiv/GitHub content ages
  differently than a Telegram post) — a candidate for future source-type-aware freshness
  weighting, not blocking (Section 8).
- `AIExecution`'s cost-audit gap becomes materially more urgent once Phase 9 makes real,
  volume-bearing LLM calls, versus Phase 8's proof-of-mechanism scale (Section 10).

---

## 16. Recommended Final Phase 9 Boundary

Unchanged in *shape* from Decision Resolution's Section 7 (D — narrower than Discovery's original
proposal), but **corrected in two specific ways** this audit found necessary:

**Phase 9 =**
1. **Deterministic Triage**, computed from Freshness + Authority only (Opportunity's full form
   dropped per Section 12's finding; a narrow, explicitly-labeled age-decay component may
   optionally be folded into Freshness itself rather than kept as a separate "Opportunity" name,
   avoiding the overclaim), feeding `EditorialTask.priority` via a new, minimal, unavoidable
   orchestration caller (Section 2) — no schema change.
2. **`ResearchCapability`**, honestly scoped as fact-extraction from given text (no external
   verification), registered as `"research"`.
3. **`IntelligenceCapability`**, consuming Research's `step_results` output, registered as
   `"intelligence"`.
4. **Proof tier**: `CapabilityExecutor`-level, via synthetic test workflows — **not** a claim that
   the real `NEWS_ANALYSIS` `WorkflowType` reaches `COMPLETED`, unless Decision 14's BLOCKER item
   is explicitly resolved in the Contract to authorize one of the three named options.

**Explicitly excluded, unchanged**: Final Ranking/Scoring enhancement, Engagement Analysis,
semantic clustering, embeddings/vector search, full cross-source novelty, dynamic source
reputation, engagement-data collection.

---

## 17. Final Verdict

**PHASE 9 NOT READY — DECISIONS REQUIRED**

The boundary's core shape (deterministic Triage gating two genuinely-distinct LLM Capabilities) is
sound and this audit did not invalidate it. But two concrete, previously-unaddressed blockers must
be explicitly resolved before Contract drafting can proceed honestly: (1) how Phase 9 handles the
real `NEWS_ANALYSIS` workflow's mechanical inability to complete with only two of its four steps
registered, and (2) whether "Opportunity Score" is dropped or explicitly rescoped, given its
undisclosed dependency on deferred clustering/engagement infrastructure. Both have clear,
low-cost resolutions recommended in this document (Sections 4 and 12/16) — neither requires
redesigning the boundary — but freezing a Contract without deciding them would encode an overclaim
into a binding document.
