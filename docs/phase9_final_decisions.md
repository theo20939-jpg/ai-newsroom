# Phase 9 — Final Decisions

**Status: decision document. Resolves the two CRITICAL findings and all ownership questions from
`docs/phase9_precontract_audit.md`, reconciled against `docs/phase9_research_intelligence_discovery.md`
and `docs/phase9_decision_resolution.md`.** This document does not modify any of the three prior
Phase 9 documents, any frozen Phase 5–8 contract, or any production code. It is the last analysis
step before Architecture Contract drafting — not the Contract itself.

Two additional repository facts, not cited by any prior document, were verified while resolving
these decisions and are load-bearing below: `scripts/run_collector.py` (the established pattern
for how periodic backend work gets triggered in this codebase) and `NewsEvent.status`'s
`EventStatus` enum (`NEW`/`PROCESSING`/`ANALYZED`/`REJECTED`/`ARCHIVED`), which is fully defined
but — confirmed by grep — never transitioned away from `NEW` by anything in production code today.

---

## 1. Executive Summary

Both CRITICAL findings are resolved by narrowing claims, not by changing architecture. Phase 9
proves `ResearchCapability` and `IntelligenceCapability` at the `CapabilityExecutor` boundary,
using synthetic test workflows exactly as Phase 8 always did — it does not claim, attempt, or
require the real `NEWS_ANALYSIS` `WorkflowType` to reach `COMPLETED`. "Opportunity Score" is
dropped entirely; the one sub-input that is genuinely computable today (publication age) is
honestly named Freshness, nothing more.

Triage's output reuses the already-existing, frozen `TaskPriority` enum (S/A/B/C) rather than
inventing a new vocabulary. The orchestration gap the audit found (nothing calls `create_task()`
in production) is resolved by building one small, in-pattern `services/` function plus one thin
`scripts/` entry point — mirroring `services/collector.py`/`scripts/run_collector.py` exactly —
built and tested, but not required to be scheduled/deployed as part of Phase 9. The
never-transitioned `EventStatus` enum is the natural, zero-new-schema mechanism for tracking which
`NewsEvent`s have already been triaged.

No new database model or migration is required anywhere in this boundary.

---

## 2. Resolved Critical #1 — Workflow Completion Boundary

**Decision**: Phase 9's integration proof stops at the `Capability`/`CapabilityExecutor` boundary.
The real, frozen `NEWS_ANALYSIS` `WorkflowDefinition` is not modified, not partially satisfied,
and not claimed to complete.

**Component Integration Proof (what Phase 9 CAN honestly provide)**:
1. `ResearchCapability`/`IntelligenceCapability` unit-tested standalone against
   `FakeLLMGateway`/`FakePromptRepository` (mirrors `tests/test_scoring_capability.py`,
   `tests/test_quality_capability.py`).
2. Both resolved correctly through `build_registry()`/`CapabilityRegistry`, proving registration
   and coexistence (mirrors `tests/test_quality_capability.py::test_scoring_and_quality_coexist_in_the_same_sealed_registry`).
3. **Step-chaining proof**: `IntelligenceCapability` actually consuming
   `CapabilityContext.business.workflow_state.step_results["research"]` — the first real exercise
   of this existing-but-unused Phase 6 mechanism — proven via a **synthetic, Phase-9-local,
   two-step `WorkflowDefinition`** (steps named `"research"`, `"intelligence"` only), run through
   the real `WorkflowRunner`/`CapabilityExecutor`. This synthetic definition is a test fixture,
   never registered in `workflows.registry.WorkflowRegistry`, and is not `NEWS_ANALYSIS`.
4. A real-`RoutingGateway` + `FakeProviderAdapter` end-to-end proof of both Capabilities together,
   mirroring `tests/test_capability_boot_wiring_e2e.py`/`tests/test_phase8_cross_cutting_regression.py`
   — against the same synthetic definition, not the real one.
5. Triage tested as a pure function in isolation.
6. The new orchestrator (Section 8) tested against a real DB session, proving Triage's output
   correctly reaches `create_task(priority=...)`.

**Full Workflow Completion (explicitly NOT claimed, NOT attempted)**: `WorkflowType.NEWS_ANALYSIS`
reaching `TaskStatus.COMPLETED` via `WorkflowRunner.run()`. This mechanically requires
`engagement_analysis` and `scoring` (in its full, output-consuming form) to also be real,
registered Capabilities — both are explicitly out of Phase 9's scope (Section 14). This remains
deferred until a future phase completes them.

**Every audit "MUST NOT" is honored by construction**: no `required=False` change, no step
removal, no placeholder Capability registered under `"engagement_analysis"`/`"scoring"` merely to
turn the workflow green, no new `WorkflowType` enum member, no `WorkflowRunner`/`WorkflowRegistry`
semantic change, no claim of `COMPLETED`.

**Correction to a prior document**: `docs/phase9_decision_resolution.md` Section 8's end-to-end
flow diagram visually implies the pipeline continues past the excluded `engagement_analysis`/
`scoring` steps to "editorial decision." Per the audit and this decision, that is not accurate for
the real `NEWS_ANALYSIS` `WorkflowType` — this document does not edit that diagram, but any reader
proceeding to Contract drafting should treat this document's Section 2 as authoritative on this
point, not that diagram.

---

## 3. Resolved Critical #2 — Opportunity Score

**Decision**: Phase 9 does not implement an Opportunity Score, weakened or otherwise, under that
name or any other. `docs/05_Scoring_Ranking_Specification.md` §4.3's five named sub-inputs are:
age (computable today), number of independent sources, spread velocity, engagement-growth
dynamics, and probability of rapid interest growth — the latter four all require either
cross-source clustering or engagement-history data, neither of which exists (Discovery §11, audit
§12). Publishing a component labeled "Opportunity" that only reflects the one available sub-input
would misrepresent what it measures.

**What ships instead**: the one genuinely available, genuinely useful sub-input — publication
age — is folded directly into **Freshness** (Section 4), under its own honest name. The real
Opportunity Score, as fully specified, remains deferred until clustering and/or engagement-history
data exist to feed its other four sub-inputs.

---

## 4. Final Triage Definition

**What Triage is**: a deterministic function computing an `EditorialTask.priority` recommendation
from `NewsEvent`/`NewsSource` data already collected — nothing more. It answers "how much AI
budget should this publication get," never "how editorially important is this fully-analyzed
story" (that remains Final Ranking's job, explicitly deferred, per Section 14 and the audit's
Section 6 pre-filter/final-ranking distinction, unchanged here).

**Output vocabulary — decision**: Triage returns a `TaskPriority` value (`S`/`A`/`B`/`C`), the
**already-existing, frozen** enum `EditorialTask.priority` already uses
(`database/models/editorial_task.py:13-19`). No new vocabulary (`PROCESS_NOW`/`DEFER`/
`SKIP_DUPLICATE`, or `HIGH`/`NORMAL`/`LOW`) is introduced — inventing one would require a
translation layer into `TaskPriority` anyway, since that is the only column that persists the
result. `docs/05` §11-12 already defines what each tier means (S = maximal processing, C =
minimal, never zero) — reusing it directly is the smallest correct choice.

**Why not literal `DEFER`/`SKIP_DUPLICATE` as separate states**: `SKIP_DUPLICATE` is redundant —
exact duplicates never reach Triage at all (`services/deduplication.py` filters them before a
`NewsEvent` row is even created). A genuine `DEFER` state (create no task now, reconsider later)
would require new backlog/reconsideration tracking that does not exist and is not justified by
current evidence — the audit already rejected this for the same reason (Section 7 there). Instead,
the **spirit** of "prefer reversible, avoid false negatives" is honored by construction: Triage
**always** results in an `EditorialTask` being created, at Priority C in the worst case — which
`docs/05` §12 already defines as minimal, not zero, processing. Nothing is ever silently dropped.

**Safest MVP semantics (final)**: Triage always recommends a `TaskPriority`; it never recommends
"do not create a task." The orchestrator (Section 8) always calls `create_task()`.

---

## 5. Allowed Triage Signals

| Signal | Classification | Note |
|---|---|---|
| `NewsEvent.published_at` | AVAILABLE | Nullable — needs the fallback rule (Section 6) |
| `NewsEvent.collected_at` | AVAILABLE | Never null, server-defaulted |
| `NewsEvent.source_id` → `NewsSource.reliability_score` | AVAILABLE | Static, populated at import time |
| `NewsSource.type` | AVAILABLE | Not used by the Phase 9 formula itself, but legitimately inspectable |
| `NewsEvent.title` | AVAILABLE | Present, but a naive first-line extraction — not used by the Phase 9 formula (only relevant to the deferred republication check, Section 7) |
| `NewsEvent.content` | AVAILABLE | Not used by Triage's formula (relevant to Research/Intelligence, not Triage) |
| Existing exact-dedup result | AVAILABLE (implicit) | Triage only ever sees already-deduplicated `NewsEvent`s |
| `NewsSource.category` / `SourceDefinition.tags` | PARTIALLY AVAILABLE | Per-*source*, not per-item; only populated for sources present in the config pack; **not used** by Phase 9's Triage formula |
| `NewsEvent.summary` | NOT AVAILABLE | Always `None` — no adapter or cleaning step populates it |
| `NewsEvent.category` (`EventCategory`) | NOT AVAILABLE | Always `UNKNOWN` at creation |
| Engagement metrics (any kind) | NOT AVAILABLE | Confirmed: no adapter captures them, for any source type |
| Cross-source event count / spread velocity / engagement-growth dynamics | NOT AVAILABLE | Requires clustering — does not exist |
| Semantic novelty / embeddings | NOT AVAILABLE | Confirmed unimplemented end to end |

**Signals Phase 9 Triage MAY actually use**: `published_at`, `collected_at`, `NewsSource.reliability_score`.
That is the complete, final list. Everything else in the "NOT AVAILABLE" and "PARTIALLY AVAILABLE"
rows is explicitly excluded from the Triage formula itself for this phase.

---

## 6. Freshness Invariants vs Configuration

**Architectural invariants (frozen in Contract, not product-tunable)**:
1. Freshness computation is a pure function of `(published_at | None, collected_at, reference_now)`
   — it must accept its reference "now" as an **explicit, injectable parameter**, never call
   `datetime.now()`/`.utcnow()` internally. This is required for deterministic tests and replay,
   and is a straightforward extension of the pure-function discipline already established by
   `services/cost_estimator.py` and `capabilities/gateway_call.py`'s own helpers. **Not
   implemented yet** — a Contract/implementation-phase task, recorded here as a binding
   requirement.
2. When `published_at` is present, it is the freshness anchor; when it is `None`, `collected_at`
   (never null) is used instead, and the fallback is flagged in the computed result so a reviewer
   can distinguish "measured from publish time" from "measured from collection time."
3. Any non-positive computed age (a `published_at` in the future, from clock skew or a malformed
   feed) is clamped to the freshest tier — never a negative value, never an error.
4. All timestamp comparisons are timezone-aware, consistent with `DateTime(timezone=True)` storage
   (`database/models/news_event.py:52-57`) and the `datetime.now(timezone.utc)` convention already
   used throughout the Gateway/Capability layers.
5. "Deterministic" here means *rule-based, reproducible given a fixed reference timestamp* — not
   *idempotent forever*. Recomputing Freshness for the same `NewsEvent` at a later reference time
   legitimately yields a different result; this is expected, not a bug.

**Product configuration (left open, per `docs/05` §14's own principle)**:
- The exact tier boundaries (the six windows: 0–2h / 2–6h / 6–12h / 12–24h / 24–48h / 48h+) and
  their numeric weights.
- Whether Freshness is ultimately bucketed, continuous, or hybrid in its final numeric form (the
  buckets above are the labels used for explainability regardless of the underlying computation
  shape — Decision Resolution's Section 2 hybrid framing stands, unchanged).
- Any future source-type-aware freshness weighting (audit Section 8's observation that arXiv/GitHub
  content ages differently than a Telegram post) — explicitly out of Phase 9.

---

## 7. Republication Decision

**Decision: B — defer title-overlap entirely from Phase 9.**

Reconsidered against the audit's own framing: exact deduplication already runs upstream and
catches the cleanest, highest-confidence duplicate case. Title-overlap's real recall is narrow
(near-verbatim republication only), its false-positive risk is concrete and domain-specific
(formulaic tech-news headlines — "X raises $N," "X releases Y" — genuinely different stories share
this phrasing), and — decisively — there is no measured evidence, only a plausible narrative, that
it would reliably improve Triage's output. Per the governing principle restated for this decision
("if it cannot reliably improve Triage without creating false-negative risk, defer it") and given
Triage's own "never hard-drop" design (Section 4) already bounds the worst case of a false
positive to a mild priority reduction rather than exclusion, there is no urgent case for it, and
building it now would be exactly the "complexity without evidence" every prior Phase 9 document
has otherwise avoided. It remains a well-scoped, cheap candidate for a **future** increment once
real triage/priority data exists to evaluate it against — not part of Phase 9's build.

It is never to be labeled "novelty" if built later, unchanged from all three prior documents.

---

## 8. Triage Orchestration Ownership

**Confirmed separation** (matches the task's proposed TRIAGE / ORCHESTRATOR / WORKFLOW split,
verified against the repository rather than assumed):

- **TRIAGE**: a pure, deterministic function. No DB session, no side effects, no knowledge of
  `EditorialTask`/`WorkflowRegistry`. Input: a `NewsEvent`'s relevant fields plus
  `NewsSource.reliability_score` plus an injected reference timestamp (Section 6). Output: a
  `TaskPriority` recommendation plus an explanation breakdown (for structured logging, not
  persistence — Section 12).
- **ORCHESTRATOR** (new, small, unavoidable — confirmed by the audit's own grep: zero production
  callers of `create_task()` exist today): a new `services/` function that (1) finds `NewsEvent`
  rows with `status == EventStatus.NEW` (an existing, fully-defined, currently-unused enum value —
  confirmed via grep that nothing transitions it today), (2) calls Triage for each, (3) calls the
  existing, **unmodified** `workflow_service.create_task(session, EditorialTaskCreate(event_id=...,
  workflow_type=WorkflowType.NEWS_ANALYSIS, priority=<Triage's recommendation>))`, and (4)
  transitions that `NewsEvent.status` to `EventStatus.PROCESSING` so it is never re-triaged. This
  reuses an existing, already-modeled state machine — **no new column, table, or migration is
  needed for "has this event been triaged yet."**
- **WORKFLOW**: `WorkflowRunner`, unchanged, executes whatever workflow the orchestrator's
  `create_task()` call started, exactly as it does today.

**Precedent, not invention**: `scripts/run_collector.py` is a thin, ~20-line entry point
(`python -m scripts.run_collector`) that does nothing but wire logging and call
`services.collector.run_collection_cycle()`. The orchestrator above should be built as **one more
instance of this exact, already-established pattern** — a new `services/` function plus a thin
`scripts/run_triage.py` mirroring it precisely. This is not a new orchestration layer; it is the
same shape this codebase already uses for exactly this kind of periodic batch work.

**Does Phase 9 need to wire this into production scheduling now?** No. The orchestrator function
and its script entry point should be **built and tested** as part of Phase 9 (without them,
Triage's output has nowhere to go, and the "safely testable" claim in Section 2 would be
incomplete) — but **scheduling** it (cron, systemd timer, or otherwise triggering it
automatically in production) is an operational/deployment concern, not an architecture concern,
and can remain a later integration milestone, exactly as `scripts/run_collector.py` itself is
never confirmed to be wired into any scheduler in this repository today either.

---

## 9. ResearchCapability Boundary

| | |
|---|---|
| **INPUT** | `CapabilityContext` for one `NewsEvent` — title, category (always `UNKNOWN` today), content, language. No external data. |
| **OUTPUT** | Structured facts extracted/organized from the given text, plus a confidence signal on that extraction (not on external verification) and any internally-flagged ambiguity/gaps. Exact field names are Contract-phase detail; the conceptual shape is a faithful, organized restatement of what the text actually says — never inventing claims not present in it. |
| **RESPONSIBILITY** | Turn one `NewsEvent`'s unstructured text into structured, reviewable factual content. |
| **MUST NOT DO** | Verify facts against any external source (no tool integration exists in this architecture, per Phase 8's frozen scope); judge importance, audience fit, or editorial angle (Intelligence's job); browse the web or invoke any tool/agent loop; call another Capability; hold per-call mutable state (contract §3.2, unchanged, applies identically). |

**"Research" clarified for the MVP**: without tool integration, this Capability cannot research in
the deep, external-verification sense. It is honestly **fact extraction**, and the Architecture
Contract should name it precisely as that, not imply external verification the architecture
cannot currently deliver.

---

## 10. IntelligenceCapability Boundary

| | |
|---|---|
| **INPUT** | `CapabilityContext` for the same `NewsEvent`, **plus** `context.business.workflow_state.step_results["research"]` — the first real production use of this existing Phase 6 mechanism. |
| **OUTPUT** | Editorial-significance judgment: importance/significance, an editorial angle, audience relevance, and a recommendation. Exact field names are Contract-phase detail; conceptually inspired by, not required to literally match, `docs/08_Database_Schema_Data_Models.md` §13's `importance`/`audience`/`angles`/`recommendation`/`confidence` shape. |
| **RESPONSIBILITY** | Given Research's already-extracted facts, assess what they mean editorially and why they matter. |
| **MUST NOT DO** | Re-extract or re-summarize facts from raw `NewsEvent.content` (must consume Research's output, not redo Research's job); compute a final, cross-event-comparable ranking score (Final Ranking/Scoring's job, explicitly deferred, Section 2/14); decide AI processing priority or budget (Triage's job, upstream and unrelated); invoke tools/agents. |

**Distinction from Research — confirmed strong enough to justify two separate LLM calls, not by
inertia**: Research answers "what does this publication say" (fact-finding, source-critical);
Intelligence answers "what does that mean for us editorially" (judgment, audience-aware). Beyond
the genuine cognitive-task difference, there is a **mechanical** reason independent of preference:
`workflows/definitions/news_analysis.py` names `"research"` and `"intelligence"` as two separate
step/capability strings. Merging them into one Capability registered under only one name leaves
the other step permanently unregistered, reproducing exactly Section 2's `engagement_analysis`
failure for whichever name is dropped. Registering the same object under both names avoids that
mechanically but produces two `WorkflowStepResult`s and two implied `AIExecution` records for one
actual LLM call — a real cost/audit double-count, not a simplification. **Not flagged as a
blocker**: the distinction holds on both grounds.

---

## 11. Research vs Intelligence Call Semantics

**Decision**: the Architecture Contract freezes the **logical responsibility split** — two
distinct Capabilities, with Intelligence depending on Research's output — as an architectural
invariant. It does **not** freeze "exactly two sequential Gateway calls, always, for every
accepted publication" as an immutable mandate.

**Why this distinction matters**: it leaves room for a legitimate future optimization — e.g.,
skipping Research for the lowest-priority accepted items, or letting Intelligence work directly
from raw content when Research's structured extraction isn't warranted — as an **orchestration
or Triage-level decision about whether/when each Capability's `execute()` is invoked**, not a
change to what either Capability does when it is invoked. This is not proposed as Phase 9 work
(no evidence yet justifies it, consistent with "do not prematurely optimize"), but the Contract
should not accidentally forbid it either by over-specifying call cardinality as a hard rule.

**Not required for Phase 9 to decide further**: batching, combining calls, or reusing Research
output across multiple Intelligence invocations — none of these are proposed, none are evidenced,
and the Contract does not need to rule on them now.

---

## 12. Persistence Decision

**No new database model or migration is required for this boundary.**

| Result | Lives in | Mechanism |
|---|---|---|
| Triage result (`TaskPriority` value) | `EditorialTask.priority` | Existing column, existing `create_task()` API — no change |
| Triage explanation breakdown | Structured log only | Mirrors `capabilities/scoring_capability.py`'s existing `capability_call_failed`-style structured logging pattern; not persisted as a queryable record in Phase 9 — an explicitly open product question (Section 17) if browsable history is later wanted |
| "Has this `NewsEvent` been triaged" | `NewsEvent.status` (`EventStatus.NEW` → `PROCESSING`) | Existing, fully-modeled, currently-unused enum — reused, not extended |
| `ResearchCapability`/`IntelligenceCapability` `CapabilityResult` | `EditorialTask.workflow` JSON `step_results` | Existing Phase 6/8 mechanism, first real production use |
| Per-call cost/audit record | **Nowhere yet** | `AIExecution`'s write path remains unwired (Amendment B) — unchanged, not required for Phase 9 the same way it was not required for Phase 8 |
| Persistent cross-task domain knowledge (a durable "what we know about topic X" store) | **Not built** | Correctly excluded — this is what `research_reports`/`intelligence_reports`/a persistent intelligence graph would be; none is justified by proven need yet |

Runtime result (`CapabilityResult`, transient Python object), audit record (`AIExecution`, unwired,
unchanged), workflow/task state (`EditorialTask.workflow`, used), and persistent domain knowledge
(not built) are four genuinely distinct categories, and Phase 9 only actually needs the third.

---

## 13. Exact Phase 9 IN Scope

1. Deterministic Triage — a pure function over `published_at`/`collected_at`/
   `NewsSource.reliability_score`, returning a `TaskPriority` recommendation (Sections 4–6).
2. Freshness as the one honestly-named deterministic Triage signal (Section 3/6) — Opportunity is
   not implemented under any name.
3. A minimal orchestration boundary (new `services/` function + thin `scripts/` entry point,
   mirroring `services/collector.py`/`scripts/run_collector.py`) connecting newly-collected
   `NewsEvent`s to Triage to `create_task()`, built and tested, not required to be scheduled in
   production (Section 8).
4. `ResearchCapability`, registered as `"research"` (Section 9).
5. `IntelligenceCapability`, registered as `"intelligence"`, consuming Research's `step_results`
   output (Section 10).
6. Integration proof at the `Capability`/`CapabilityExecutor` boundary, via synthetic test
   workflows only — never a claim that the real `NEWS_ANALYSIS` `WorkflowType` completes (Section
   2).
7. Tests and observability required by the already-frozen Phase 6–8 contracts (unit tests, no real
   network/provider/DB in the unit tier, structured logging for Triage's explanation and for
   Capability failures, mirroring Phase 8's established conventions throughout).

---

## 14. Exact Phase 9 OUT of Scope

1. `EngagementAnalysisCapability` (blocked independently on Amendment A's `AICapability` enum gap
   — unchanged from Discovery).
2. Final Editorial Ranking / full Scoring implementation (`ScoringCapability` enhancement to
   consume Research/Intelligence output).
3. Opportunity Score, under any name (Section 3).
4. Semantic event clustering.
5. Embeddings / vector DB.
6. True cross-source novelty detection.
7. Title-overlap/republication check (Section 7 — deferred, not merely "not yet decided").
8. Persistent intelligence graph or any new domain-knowledge table.
9. Web-research agents, autonomous loops, or any tool-integration for Research (Phase 8's frozen
   scope already excludes tool integration entirely).
10. Any modification to the frozen `NEWS_ANALYSIS` `WorkflowDefinition`, `WorkflowRunner`, or
    `WorkflowRegistry`.
11. Any claim that `NEWS_ANALYSIS` reaches `COMPLETED` end-to-end.
12. Scheduling/deploying the Triage orchestrator into an automatic production trigger (built and
    tested only, per Section 8).
13. `AIExecution`'s real write path (unchanged Amendment B gap, not required for this phase).

---

## 15. Contract-Ready Invariants

Safe to freeze into `docs/phase9_research_intelligence_contract.md` as binding rules:

1. Triage is a pure function; it never persists anything itself and never creates an
   `EditorialTask` itself.
2. Triage's output type is `TaskPriority` (S/A/B/C) — no new vocabulary.
3. Triage never recommends "no task" — every triaged `NewsEvent` results in exactly one
   `EditorialTask`, at some priority, including the minimal-but-nonzero C tier.
4. Triage's allowed input signals are exactly: `published_at`, `collected_at`,
   `NewsSource.reliability_score` — nothing else, for this phase.
5. Freshness computation takes its reference "now" as an explicit parameter — never reads the
   system clock internally.
6. Freshness's `published_at`→`collected_at` fallback and negative-age clamp are correctness
   rules, not configuration.
7. `ResearchCapability` and `IntelligenceCapability` remain two separate Capabilities; Intelligence
   consumes Research's `step_results` output; neither computes a final cross-event ranking score.
8. `ResearchCapability` performs no external fact verification (no tool integration).
9. The orchestrator reuses `NewsEvent.status` (`NEW`→`PROCESSING`) for triage-bookkeeping; no new
   column or table is introduced for this purpose.
10. No new database model or migration is authorized by this phase's scope.
11. Neither Capability is registered under, and no component implements, `"engagement_analysis"`
    or an enhanced `"scoring"` in this phase.

---

## 16. Deferred Product Configuration

Left open for the Contract to either fix with a concrete default or explicitly delegate to
runtime configuration, per `docs/05` §14's own principle:

1. Freshness tier boundaries and their numeric weights.
2. The exact mapping from a Freshness+Authority combination to a specific `TaskPriority` tier
   (thresholds).
3. Whether the Triage explanation breakdown should be persisted queryably in a later phase, versus
   remaining log-only indefinitely.
4. Any future source-type-aware freshness weighting.
5. The republication/title-overlap check, if ever revisited (Section 7) — including its algorithm,
   threshold, and weight.

---

## 17. Remaining Open Questions

| Question | Classification |
|---|---|
| Whether/when to authorize marking `engagement_analysis`/`scoring` as `required=False`, or adding a new `WorkflowType`, to eventually let `NEWS_ANALYSIS` complete for real | DEFERRED FUTURE PHASE |
| Whether `AIExecution` gets a real write path | DEFERRED FUTURE PHASE |
| Whether/how to eventually collect real engagement data (Telegram views/reactions/forwards, HN score/descendants) to unlock Popularity Score | DEFERRED FUTURE PHASE |
| Whether the Triage orchestrator gets scheduled in production, and by what mechanism (cron, systemd timer, task queue) | NON-BLOCKING IMPLEMENTATION DETAIL |
| Exact `services/`/`scripts/` module names and file layout for Triage and its orchestrator | NON-BLOCKING IMPLEMENTATION DETAIL |
| Concurrency-safety of the `EventStatus.NEW`→`PROCESSING` transition (avoiding a double-triage race if the orchestrator is ever run concurrently) | NON-BLOCKING IMPLEMENTATION DETAIL |
| Exact `ResearchCapability`/`IntelligenceCapability` output JSON Schema field names | NON-BLOCKING IMPLEMENTATION DETAIL |
| All items in Section 16 | PRODUCT CONFIGURATION |
| Amendment A's `"engagement"` capability-name resolution | DEFERRED FUTURE PHASE (unchanged since Discovery) |

**No item in this table is classified BLOCKING.**

---

## 18. Final Verdict

**PHASE 9 READY FOR ARCHITECTURE CONTRACT**

Both CRITICAL findings from `docs/phase9_precontract_audit.md` are resolved with concrete,
evidence-grounded decisions (Sections 2–3), every ownership question the audit raised has a
definitive answer verified against actual repository patterns rather than assumed (Section 8, using
`scripts/run_collector.py` and the unused `EventStatus` enum as precedent), and every remaining
open item is correctly classified as non-blocking, product configuration, or explicitly deferred
future-phase work (Section 17). Nothing in this document required redesigning the boundary Decision
Resolution proposed and the audit tested — it required narrowing two overclaims and answering
"who owns what" precisely, both now done.
