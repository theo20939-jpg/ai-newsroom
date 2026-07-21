# Phase 10 — Production Content Pipeline Decision Resolution

## 1. Status

**Decision resolution document. Not a specification, not an implementation plan, not a contract.**
No production code, test, or migration was modified to produce this document; no commit was
created. This document converts `docs/phase10_production_pipeline_discovery.md`'s findings and
open questions into explicit architectural decisions. The next step after this document is the
Phase 10 Architecture Contract — this document does not authorize implementation.

---

## 2. Executive Summary

**DECISION**: Phase 10's boundary is `CopywritingCapability` + a same-task Research→Intelligence→
Copywriting→Quality chain + a minimal `ContentDraft` persistence layer + a CLI-script trigger —
stopping at a reviewable, persisted `ContentDraft` row. Telegram publishing, meme generation, and
a second LLM provider are explicitly deferred to later, narrower phases.

**DECISION, the single most consequential one in this document**: `CopywritingCapability` cannot
receive Research/Intelligence context via the existing `step_results` mechanism unless it runs
**within the same `EditorialTask`/workflow execution** as Research and Intelligence — no
cross-task, cross-workflow, or per-event data-access mechanism exists anywhere in this repository
today (verified in §7). This means Phase 10 cannot use `CONTENT_GENERATION`'s currently-frozen
two-step shape (`copywriting → quality`) unchanged if it wants Copywriting to have real analytical
context — the workflow definition's step list itself, not `WorkflowRunner`'s engine mechanics,
must change. This is flagged explicitly, not smoothed over, and its risk is named in §14.

---

## 3. Discovery Findings Recap

**FACT** (from Discovery §4): `OpenAIAdapter.generate()` is fully implemented against the real
OpenAI Responses API; `enabled_providers` defaults to `[]`; no real network call has ever been
made in this repository's test suite.

**FACT** (from Discovery §5): `workflows/definitions/content_generation.py` already names a
`"copywriting"` step; `capabilities/capability_mapping.py` already maps `"copywriting"` →
`AICapability.COPYWRITING`; `QualityCapability` (the second step) already exists and is
registered.

**FACT** (from Discovery §6): `ContentDraft` already exists with `title`/`body`/`hashtags`/
`version`/`status`/`task_id`, referenced nowhere outside its own migration and
`database/models/__init__.py`.

**FACT** (from Discovery §7-§8): no Telegram publishing service exists; meme image generation has
no representable path through `LLMGateway.generate()`.

This document resolves the open questions Discovery left unresolved; it does not re-derive facts
already established there.

---

## 4. Frozen Constraints (restated, binding on every decision below)

- Phase 5: `WorkflowRunner`'s execution engine (commit discipline, retry/timeout/iteration
  semantics) is frozen except via an explicitly-approved amendment (Phase 9.5's own precedent).
  No scheduler. No crash recovery/resume.
- Phase 6: LLM access only through `LLMGateway`; provider SDKs confined to
  `integrations/llm_gateway/providers/`; a Capability never calls an external service directly.
- Phase 8: every AI function is an ordinary Capability — `__init__(gateway, prompt_repository)`,
  builds `GenerateRequest` via the existing `call_generate()` mechanism, returns
  `CapabilityResult`, owns no infrastructure.
- Phase 9: no direct Capability-to-Capability import; cross-step data flows only through
  `context.business.workflow_state.step_results`.
- Phase 9.5: `step_results` are now durable within one uninterrupted `WorkflowRunner.run()` call,
  immediately after each step succeeds — the mechanism every decision below relies on.

---

## 5. Production API Decision

**FACT**: `OpenAIAdapter` (generate() only) is code-complete; `build_provider_registry()` only
activates a provider that is both named in `enabled_providers` and has a credential present;
`RoutingPolicyRegistry`/`BudgetGuard`/`CostTracker`/`CacheCoordinator` are all already wired in
`assemble_ai_integration_layer()`.

**DECISION**: Phase 10 includes exactly:
1. Production environment configuration — `enabled_providers=["openai"]`, a real
   `openai_api_key`, confirmed Redis/Postgres provisioning. Not a code change.
2. Exactly one deliberate, manually-run, out-of-band smoke test against the live OpenAI API,
   proving `RoutingGateway.generate()` works end-to-end through a real provider — never added to
   the automated suite, matching this repository's own unbroken no-real-network-call testing
   discipline.

**Explicitly OUT OF SCOPE**:
- Provider routing changes — `RoutingEngine`/`FallbackPolicy` (Phase 7, frozen) already function;
  no evidence requires a change.
- A second provider (Anthropic/Gemini) — **DECISION**: deferred. No repository evidence or
  product requirement in Discovery justifies it for this phase; adding one later is a bounded,
  independently-schedulable task (Discovery §4) that does not block Phase 10.
- New cost-control mechanisms — `BudgetGuard`/`CostTracker` already exist; Phase 10 verifies they
  are active in production configuration, it does not build new ones.
- Any `LLMGateway` Protocol change.

---

## 6. CopywritingCapability Decision

**DECISION**: yes, `CopywritingCapability` is implemented in Phase 10. It is the smallest,
most architecture-aligned next Capability, per Discovery §5's evidence (frozen step name already
exists, mapping already exists, its own second workflow step already exists and is registered).

**Input source — the three options, resolved**:

- **Option A (Intelligence output only)** and **Option C (full EditorialTask workflow state)**
  are both **not directly achievable today**, for the same underlying reason, established in §7
  below: Research and Intelligence's `CapabilityResult`s live in `step_results`, which is scoped
  to *one* `EditorialTask`'s `WorkflowExecutionState`. `CONTENT_GENERATION`, as currently frozen,
  is a *separate* `WorkflowType` — a separate `EditorialTask` row, a separate `step_results` list.
  There is no mechanism anywhere in this repository for one task's Capability to read a
  *different* task's `step_results`, and no per-`NewsEvent` persisted analysis summary exists
  either (`NewsEvent.summary` has no writer, confirmed in §7).
- **DECISION: Option B (Research + Intelligence combined context)**, but only achievable if
  Copywriting executes as a step **within the same workflow execution** as Research and
  Intelligence — reusing the exact, already-proven, Phase-9.5-fixed `step_results` mechanism, with
  zero new data-access infrastructure. The precise mechanism by which Copywriting joins that same
  step chain (which file changes, exactly) is left to the Phase 10 Contract to specify in binding
  form — this document decides the *direction* (same-task chaining, never cross-task), not the
  literal diff.

**RECOMMENDATION**: `CopywritingCapability`'s `__init__`, `execute()`, and Gateway-call shape
should be structurally identical to `ResearchCapability`/`IntelligenceCapability`/
`QualityCapability` — no new pattern, no new abstraction.

---

## 7. Data Flow Decision

**FACT**: `CapabilityExecutor._build_context()` (`capabilities/executor.py:125-134`) builds
`step_results` from **all** prior `SUCCESS` steps of the *same* task's `WorkflowExecutionState` —
not merely the immediately-preceding one. `_find_active_task()`
(`services/workflow_service.py:89-106`) enforces active-task uniqueness per
`(event_id, workflow_type)` pair, **not** per event alone — confirmed directly this session: a
`NEWS_ANALYSIS` task and a `CONTENT_GENERATION` task for the same `NewsEvent` are independent
rows with independent `step_results`. `NewsEvent.summary` (`database/models/news_event.py:46`) is
a plain nullable column with no writer anywhere in the codebase (re-confirmed by grep this
session) — there is no per-event, cross-task persisted analysis home today.

**DECISION**:
- Copywriting reads `step_results`. **DECISION on keys**: `step_results["research"]` and
  `step_results["intelligence"]` — the exact, already-established key names
  (`ResearchCapability`/`IntelligenceCapability`'s own `CAPABILITY_NAME` values), reused, never
  renamed.
- **DECISION — output schema ownership**: Copywriting owns its own output schema via its own
  `PromptRepository`-resolved prompt (`prompts/copywriting/v1.yaml`), exactly matching every
  existing Capability's pattern (Phase 8 §7: prompt content, including `output_schema`, is never
  embedded in Capability code). Copywriting's schema is not derived from or coupled to Research's
  or Intelligence's schemas.
- **DECISION — prompt knowledge of prior capability names**: prompts do not reference capability
  names as identifiers. `CopywritingCapability`'s own `_build_request()` helper (mirroring
  `ResearchCapability`/`IntelligenceCapability`'s identical, already-established pattern) formats
  `step_results["research"]`/`step_results["intelligence"]`'s *content* into a plain CONTEXT text
  block; the prompt text itself never says "the Research Capability said..." — it just receives
  assembled facts/judgment as data.
- **DECISION — avoiding Capability-to-Capability coupling**: `capabilities/copywriting_capability.py`
  MUST NOT import `capabilities/research_capability.py` or `capabilities/intelligence_capability.py`
  — verified mechanically the same way `IntelligenceCapability`'s Phase 9 tests already did (an
  AST-based import check), reused as the exact same test technique.

---

## 8. ContentDraft Decision

**FACT**: `ContentDraft` (`database/models/content_draft.py`) already has every column a first,
text-only content slice needs: `task_id`, `type` (`ContentType`, including `POST`), `title`,
`body`, `hashtags` (JSON), `version`, `status`. No `schemas/content_draft.py` or
`services/content_draft_service.py`-equivalent exists.

**DECISION**: **Option A + Option B combined** — the smallest solution available. **Option A**:
`ContentDraft`'s existing columns are used unchanged; no schema/model migration (ruling out
Options C and D — no evidence requires either). **Option B**: add a small, new
`schemas/content_draft.py` (mirroring `schemas/editorial_task.py`'s DTO-boundary pattern) and a
correspondingly scoped `services/content_draft_service.py` (mirroring `services/workflow_service.py`'s
"scoped, two-function service" precedent) — neither exists today and both are needed before any
row can be written or read through a proper boundary.

**DECISION — who writes it**: a new function in `services/content_draft_service.py`, called
**after** `WorkflowRunner.run()` returns a `COMPLETED` `WorkflowRunResult` (reading
`result.step_results` already in hand), **not** a new `CapabilityExecutor` responsibility. This
requires zero change to any frozen Phase 5/6 file — `CapabilityExecutor` and `WorkflowRunner`
remain exactly as they are. The trigger mechanism (§10) is the natural caller of this function,
since it already holds the `WorkflowRunResult` synchronously.

---

## 9. Workflow Decision

**FACT**: `CONTENT_GENERATION` is already registered in the real, global `WorkflowRegistry`
(`workflows/registry.py:82`); its `quality` step is already a registered Capability; its
`copywriting` step has no implementation.

**DECISION**: yes, Phase 10 makes `CONTENT_GENERATION` genuinely completable — but, per §6/§7's
resolution, only by expanding its step list to include `research` and `intelligence` ahead of
`copywriting`/`quality`, reusing the already-registered `ResearchCapability`/
`IntelligenceCapability` as-is (zero code change to either). **Expected flow**:

```
EditorialTask (CONTENT_GENERATION)
      ↓
Research           (reused, unmodified)
      ↓
Intelligence       (reused, unmodified)
      ↓
Copywriting        (new, Phase 10)
      ↓
Quality            (reused, unmodified)
      ↓
services.content_draft_service (new, Phase 10) → ContentDraft row
```

**RECOMMENDATION**: this makes `CONTENT_GENERATION` the first `WorkflowType` in this system's
history to reach `TaskStatus.COMPLETED` for real, using entirely already-existing or
already-decided-minimal new components — no new `WorkflowType`, no `WorkflowRunner` change beyond
what Phase 9.5 already shipped.

**Risk of this decision is named explicitly in §14, not hidden.**

---

## 10. Trigger Decision

**FACT**: `scripts/run_triage.py` is the established, existing precedent for a thin, ~20-line
script entry point wrapping exactly one `services/` function call (Phase 9 M3).

**DECISION: Option A — a CLI script** (e.g. `scripts/run_content_generation.py`), mirroring
`scripts/run_triage.py`'s exact shape: `setup_logging()` + one `services/`-layer async call that
creates a `CONTENT_GENERATION` task for a given `event_id` (or a small, explicit set of eligible
events) and runs it to completion, then calls `services.content_draft_service`'s new persistence
function.

**Why not the alternatives**: Option B (Telegram admin command) entangles `bot/` changes into a
content-generation milestone, mixing concerns Discovery §7 already recommended keeping separate.
Option C (internal service function only, no entry point) leaves no way to actually invoke it in a
real environment without *also* building a caller — the CLI script *is* the minimal caller,
already-precedented, not a new abstraction. Option D was not evidenced by anything in this
repository.

**Explicitly not a scheduler**: no cron, no timer, no automatic polling loop — a human or an
external process invokes the script, exactly as `scripts/run_triage.py`'s own current production
status is today (built and testable, not wired into automatic scheduling, per Phase 9 Contract
§7.4's own precedent).

---

## 11. Telegram Boundary Decision

**DECISION**: Telegram publishing is **not** part of Phase 10. Phase 10 stops at a persisted,
reviewable `ContentDraft` row — a deliberate, evidence-grounded stopping point (Discovery §7: no
publishing component exists in any form today, not even a placeholder; building it correctly
requires its own scoping pass).

**DECISION — architecture for a future phase, conceptual only, not designed here**:
`ContentDraft → Publisher Service → Telegram Bot API`, where the Publisher Service is a new
`services/`-layer component (never a Capability — Capabilities never call external services
directly, per Phase 6), reusing `bot/loader.py::create_bot()` for the `Bot` instance and
`TelegramChannel.telegram_chat_id` as its target. This mirrors `services/collector.py`'s existing
role for the opposite (inbound) direction.

**RECOMMENDATION**: the Publisher Service should be its own future phase (or Phase 10's own
directly-following milestone set, decided separately), gated on Phase 10's `ContentDraft` actually
existing and being reviewable first.

---

## 12. Meme Generation Decision

**DECISION**: meme generation, in any form, is **not** part of Phase 10.

**Reasoning, per Discovery §8's evidence**: `MemeOpportunityCapability` (text-only judgment) is
architecturally unblocked, but has no consumer without a Publisher (deferred, §11) and would
compete for the same "first new Capability" slot Copywriting already fills for this phase. Image
*rendering* has a genuinely unresolved question — whether it requires a Phase 6 `LLMGateway`
Protocol amendment or a deliberately parallel, non-Gateway integration — that must not be decided
inside an implementation milestone.

**RECOMMENDATION**: meme generation (both halves) becomes its own future phase's discovery/decision
pass, evaluated only after Phase 10's Copywriting/ContentDraft pattern is proven in production,
giving that future phase a working precedent to model itself on (exactly how Phase 10 itself
models `CopywritingCapability` on Research/Intelligence).

---

## 13. Phase 10 Final Boundary

| # | Title | Depends on | Goal | Why now | Explicitly excluded |
|---|---|---|---|---|---|
| M0 | Production LLM provider verification | — | Real `openai_api_key`/`enabled_providers` configuration; one manual, out-of-band live smoke test proving `RoutingGateway.generate()` works against the real API. | Every subsequent milestone's real-world value depends on this actually working — must be verified before anything is built on top of it, not assumed. | Any Gateway code change; a second provider; cost-control implementation. |
| M1 | `CopywritingCapability` | — (buildable/testable with fakes independent of M0) | An ordinary Phase 8 Capability, mapped to the existing `"copywriting"` name, consuming `step_results["research"]`/`step_results["intelligence"]`. | The exact missing piece Discovery identified; zero new architecture. | Any change to Research/Intelligence/Quality; any Capability-to-Capability import. |
| M2 | `CONTENT_GENERATION` workflow integration | M1 | Expand `CONTENT_GENERATION`'s step list to `research → intelligence → copywriting → quality`, reusing already-registered Capabilities; register Copywriting in `build_registry()`. | Makes real, end-to-end completion possible — the direct analog of Phase 9 M6's "registration" milestone. | Any change to `WorkflowRunner`, `WorkflowType` enum, or `NEWS_ANALYSIS`. |
| M3 | `ContentDraft` lifecycle | M2 | `schemas/content_draft.py` + `services/content_draft_service.py`; persists a `ContentDraft` row from a completed `CONTENT_GENERATION` run's `step_results["copywriting"]`. | Closes Discovery's "who writes ContentDraft" open question with the smallest-footprint answer (§8). | Any migration; any change to `ContentDraft`'s existing columns; any Telegram code. |
| M4 | MVP trigger | M1, M2, M3 | `scripts/run_content_generation.py`, mirroring `scripts/run_triage.py`'s shape — creates and runs a `CONTENT_GENERATION` task for a given event, then persists its `ContentDraft`. | Closes Discovery's "inert code" risk — the smallest possible way to produce real, observable end-to-end value. | Any scheduler, cron, or automatic trigger. |

5 milestones total. M0 and M1 have no dependency on each other and could proceed in parallel;
M2–M4 are strictly sequential.

---

## 14. Risks

- **Named explicitly, not hidden**: M2 (§13) requires editing `workflows/definitions/
  content_generation.py` — a Phase 5 workflow *definition* file. This document's position is that
  a workflow definition's step list is pipeline-shape configuration, not `WorkflowRunner` engine
  mechanics, and is therefore a materially smaller change than a Phase 9.5-style engine amendment
  — but it is still a change to a file this task's own instructions describe as subject to "no
  workflow redesign." The Phase 10 Architecture Contract must explicitly authorize this specific,
  narrow change (mirroring exactly how the Phase 9.5 Contract explicitly authorized one narrow
  `WorkflowRunner` change) — it must not be treated as pre-approved by this document alone.
- **RISK**: `CopywritingCapability`'s real, live-API behavior is unverified until M0's smoke test
  runs — the same class of risk already named in Discovery §10, restated here since M1 depends on
  M0 for any real (non-fake) value.
- **RISK**: expanding `CONTENT_GENERATION` to include `research`/`intelligence` means a
  `NewsEvent` could now legitimately have both a `NEWS_ANALYSIS` task and a `CONTENT_GENERATION`
  task independently running Research/Intelligence against the same event — duplicating Gateway
  calls (and cost) if both are triggered for the same event. This document does not resolve
  whether that duplication is acceptable for a first slice or needs de-duplication logic; flagged
  for the Contract phase to decide explicitly, not silently accepted.
- **RISK**: `ContentDraft.status`'s free-text nature (no constrained enum, per the model's own
  comment) means M3 must decide a concrete, documented set of status values it actually writes,
  even though the column itself permits anything — an implementation-detail risk, not an
  architectural one, but worth naming so M3 doesn't invent business rules ad hoc.

---

## 15. Open Questions

Carried forward, not resolved by this document (deliberately, per its own scope):

1. Exact mechanism for M2's `CONTENT_GENERATION` step-list expansion (a direct edit to
   `content_generation.py`, or some other equally small approach) — left to the Phase 10 Contract.
2. Whether `NEWS_ANALYSIS`/`CONTENT_GENERATION` running Research/Intelligence independently for
   the same event (§14) needs de-duplication in this phase or a later one.
3. Exact `ContentDraft.status` value set M3 will write (e.g., `"draft"`/`"ready_for_review"` or
   similar) — a small, concrete decision the Contract or M3's own planning should make explicitly.
4. Timing of the Telegram Publisher and meme-generation future phases relative to each other —
   not decided, not required to be decided now.

---

## 16. Final Verdict

DECISIONS RESOLVED — READY FOR PHASE 10 ARCHITECTURE CONTRACT.
