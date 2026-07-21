# Phase 10 — Final Independent Architecture Re-Audit

**Status: audit document. Does not modify the Contract, production code, tests, or migrations.**
Independent, adversarial re-audit of `docs/phase10_production_content_pipeline_architecture_contract.md`
(revision 3, "PASS 3"), treated as fully untrusted. Every claim below — including every claim the
Contract itself makes, and every "fixed" claim the two prior audits made — was independently
re-derived against the current repository source this session, not taken on any prior document's
word. This is a readiness determination, not an improvement exercise: findings are reported only
where they bear on whether implementation can safely begin.

---

# Executive Summary

The Contract is technically sound. The one CRITICAL defect the prior final re-audit found
(`scripts/run_content_generation.py` required by §9 but not authorized by §3) is genuinely fixed —
independently re-verified, not assumed. The two MINOR defects from that same audit
(`workflow_type`'s real storage location; the missing direct registry-resolution test obligation)
are also genuinely fixed. No new CRITICAL or blocking MAJOR defect was found in this pass.

One new MINOR finding was identified: §9's claim that `scripts/run_content_generation.py`
"mirrors `scripts/run_triage.py`'s exact, already-proven shape" is imprecise —
`services/triage_orchestrator.py` explicitly documents "no `LLMGateway`, no Capability layer, no
provider SDK," and no production code path anywhere in this repository has ever called
`assemble_ai_integration_layer()`/constructed a `FilePromptRepository` (confirmed: every call site
is a test file). The new script must be the first production code to do so. This does not block
implementation — the construction is fully achievable inside the one file §3 already authorizes,
using only already-existing, unmodified functions (`assemble_ai_integration_layer()`,
`FilePromptRepository`, `build_registry()`), and an already-proven test-only pattern
(`tests/test_capability_boot_wiring_e2e.py`, `tests/test_phase9_research_intelligence_integration.py`)
exists to model it on. It is a documentation-precision gap, not a scope or authorization gap.

**Verdict: PHASE 10 CONTRACT APPROVED.**

---

# Verified Architecture

1. **Architecture consistency** — confirmed. The Contract's four-step chain
   (`research → intelligence → copywriting → quality`) reuses `ResearchCapability`/
   `IntelligenceCapability` unmodified, adds one new Capability, and narrowly amends one existing
   Capability's input assembly. No new abstraction, no new communication mechanism beyond
   `step_results` (already frozen since Phase 9, made durable-within-one-run by Phase 9.5).
2. **Repository consistency** — confirmed against live source (see Verified Repository
   Consistency below); every FACT/line citation checked in this session that was relied upon for a
   finding held up exactly as claimed.
3. **Implementation feasibility** — confirmed, with one caveat (the MINOR finding above): every
   authorized file is genuinely buildable with existing, unmodified infrastructure; no frozen file
   needs a change beyond what §3 already authorizes.
4. **Workflow correctness** — confirmed by direct trace of `workflows/runner.py` and
   `capabilities/executor.py` (see Workflow Verification below): step_results propagation, ordering,
   and persistence timing all support the four-step chain with zero state loss.
5. **Capability integration** — confirmed: `CopywritingCapability`'s proposed shape
   (`__init__(gateway, prompt_repository)`, `call_generate()`, `CapabilityResult`) is structurally
   identical to all four existing Capabilities, verified line-by-line against
   `research_capability.py`/`intelligence_capability.py`/`quality_capability.py`.
6. **Registry integration** — confirmed sufficient (see §1 of Repository Verification below): the
   Contract's authorized two-line `capabilities/registry.py` edit is both necessary and sufficient
   for `CapabilityRegistry.resolve("copywriting")` to succeed.
7. **Prompt integration** — confirmed: `FilePromptRepository`'s directory/glob-based discovery
   (`integrations/prompts/file_repository.py:109-121`) requires zero code change to pick up
   `prompts/copywriting/v1.yaml` or `prompts/quality/v2.yaml` — verified by direct read of the
   constructor's `root.iterdir()`/`name_dir.glob("v*.yaml")` logic.
8. **Persistence design** — confirmed (see Persistence Review below): session reuse,
   `expire_on_commit=False`, commit boundary, and failure semantics are all correctly described
   against `database/session.py` and the real `ContentDraft`/`EditorialTask` models.
9. **Boundary correctness** — confirmed (see Boundary Review below): no hidden dependency on any
   excluded feature found.
10. **Implementation scope completeness** — confirmed COMPLETE (see Authorized Implementation
    Scope below): every production file this chain genuinely requires is on the Contract's
    authorized list; no hidden required file was found.

---

# Verified Repository Consistency

Independently re-read and checked against the Contract's claims this session:
`capabilities/registry.py`, `capabilities/quality_capability.py`, `capabilities/
intelligence_capability.py`, `capabilities/research_capability.py`, `capabilities/executor.py`,
`capabilities/capability_mapping.py`, `workflows/definitions/content_generation.py`,
`workflows/definitions/news_analysis.py`, `workflows/runner.py`, `workflows/registry.py`,
`database/models/content_draft.py`, `database/models/editorial_task.py`, `database/models/
__init__.py`, `database/session.py`, `schemas/editorial_task.py`, `schemas/workflow.py`, `schemas/
capability.py`, `schemas/capability_definition.py`, `integrations/prompts/file_repository.py`,
`integrations/prompts/protocol.py`, `prompts/quality/v1.yaml`, `integrations/llm_gateway/boot.py`,
`services/workflow_service.py`, `services/triage_orchestrator.py`, `scripts/run_triage.py`,
`scripts/validate_architecture.py`, `tests/test_intelligence_capability.py`, `tests/
test_phase9_capability_registration.py`, `tests/test_triage_orchestrator_claims.py`, `tests/
conftest.py`.

Every citation the Contract relies on for its binding claims was re-verified and held up exactly:
- `capabilities/registry.py:134-137` — the four `register()` calls, confirmed at those exact lines.
- `capabilities/quality_capability.py:81-108` — `_build_request()`, confirmed to span exactly that
  range and to read only `news_event` fields today, never `step_results`.
- `capabilities/intelligence_capability.py:93-106` — the `step_results["research"]` formatting
  pattern §5.1 says to mirror, confirmed present and structurally as described.
- `capabilities/research_capability.py:36` (`CAPABILITY_NAME = "research"`) and `:57-82`
  (`_floor_validate`), confirmed at those exact lines.
- `database/models/editorial_task.py:44` (`workflow: Mapped[dict | None]`, unindexed `JSON`
  column) and `:45-46` (`status`, `index=True`), confirmed exactly.
- `database/models/content_draft.py:34-36` (`task_id`, `ForeignKey`, no explicit `index=True`),
  confirmed exactly.
- `database/session.py:14` (`expire_on_commit=False`), confirmed exactly.
- `tests/conftest.py:65` (`expire_on_commit=False` in the test session fixture), confirmed exactly.
- `services/workflow_service.py:89-106` (`_find_active_task`, matching `workflow_type` against the
  JSON snapshot's `workflow_name` key since `EditorialTask` has no dedicated column for it),
  confirmed exactly — this is the citation MINOR-1 of the prior audit's own re-audit was built on,
  and it holds.
- `workflows/definitions/news_analysis.py:31` (`timeout_seconds=120`, 4 steps, an `engagement` step
  naming an unregistered `"engagement"` capability), confirmed exactly — `capabilities/registry.py`
  registers no `"engagement"` Capability, so `NEWS_ANALYSIS` genuinely has never reached
  `COMPLETED`, exactly as the Contract states.
- `docs/phase10_decision_resolution.md`'s M2 milestone row (line 290 in that document as rendered),
  confirmed to explicitly name "register Copywriting in `build_registry()`."
- `capabilities/capability_mapping.py` (not itself cited by line in the Contract, but load-bearing
  for feasibility): confirmed `"copywriting": AICapability.COPYWRITING` is already present
  (line 22) — this is a hidden integration point the Contract never had to authorize because it was
  already done in a prior phase; independently confirmed, not assumed from Discovery's own claim.

No fabricated or stale citation was found anywhere the Contract's binding text depends on.

---

# Findings

## CRITICAL

None.

## MAJOR

None.

## MINOR

### MINOR-1 — §9's `scripts/run_triage.py` comparison understates the new script's actual construction work

**Location**: Contract §9 ("mirroring `scripts/run_triage.py`'s exact, already-proven shape...
exactly one `services/`-layer async call").

**Evidence**: `services/triage_orchestrator.py`'s own module docstring states explicitly: "no
`LLMGateway`, no Capability layer, no provider SDK" (confirmed by direct read, line 6 region) —
`scripts/run_triage.py` never constructs a `CapabilityRegistry`, a `RoutingGateway`, or a
`PromptRepository`. A repository-wide search for `assemble_ai_integration_layer(` — the sole
boot-sequence function that assembles a real, usable `CapabilityRegistry` (`integrations/
llm_gateway/boot.py:143-219`) — shows it is called **only** from test files (`tests/
test_boot_assembly.py`, `tests/test_capability_boot_wiring_e2e.py`, `tests/
test_phase8_cross_cutting_regression.py`, `tests/test_phase9_cross_cutting_regression.py`); zero
production call sites exist anywhere under `scripts/`, `services/`, `bot/`, or `core/`. Likewise,
`FilePromptRepository` (the only concrete `PromptRepository` implementation that exists) is
constructed only inside test files today. `scripts/run_content_generation.py` must therefore be
this repository's **first production code path** to assemble the real AI integration layer
(`FilePromptRepository(root=...)` → `assemble_ai_integration_layer(settings, prompt_repository)` →
`CapabilityExecutor(session, task_id, capability_registry)` → `WorkflowRunner(executor).run(...)`)
— materially more construction than "one `services/`-layer async call" implies, and not actually
analogous to `run_triage.py`'s shape for this part of the work.

**Why this does not block implementation**: every piece this construction needs already exists,
unmodified, and requires no new authorization: `assemble_ai_integration_layer()` already accepts
`prompt_repository` as an injected parameter (no boot.py change needed); `FilePromptRepository`
already discovers `prompts/<name>/v<N>.yaml` files with zero code change; `build_registry()`,
`CapabilityExecutor`, and `WorkflowRunner` are all already-existing, unmodified production code. A
directly-applicable template already exists and is proven correct: `tests/
test_phase9_research_intelligence_integration.py` and `tests/test_capability_boot_wiring_e2e.py`
already assemble this exact stack end-to-end (using fakes for the Gateway, real wiring for
everything else) — an implementer building the script has a concrete, working pattern to follow,
not an open design question. This is a documentation-precision gap in how §9 characterizes the
work, not a missing file, missing authorization, or architectural gap.

**Suggested correction, non-blocking, for a future revision if one occurs for other reasons**: §9
could note explicitly that the script's AI-layer wiring is a novel production-first assembly
(`assemble_ai_integration_layer()` + `FilePromptRepository`), modeled on the existing test-only
pattern, rather than implying `run_triage.py` covers this part of the shape too. Not required for
approval — no re-audit is requested for this alone.

## OBSERVATIONS

- **OBS-1**: `ContentDraft` carries no reference to a target Telegram channel/audience. This is
  irrelevant to Phase 10 (no Publisher is built), but the future Telegram Publisher phase (§10,
  conceptual only) will need to resolve this from data Phase 10 does not produce — worth noting for
  that phase's own discovery pass, not a Phase 10 gap.
- **OBS-2**: `ContentDraft.hashtags` is a `JSON` column; `CopywritingCapability`'s frozen
  `output_schema` types `hashtags` as `array`. Confirmed no type mismatch — a JSON column accepts a
  Python list without translation, and `ContentDraftService`'s "copy verbatim" design (§7.1) is
  sound for all three fields (`title`/`body`: `Text`, nullable; `hashtags`: `JSON`, nullable — all
  three accept the Copywriting output's types directly).
- **OBS-3**: `WorkflowRunner._execute_steps`/`CapabilityExecutor._build_context` were traced
  concretely this session (not merely cited): each step's `WorkflowStepResult.result` is committed
  to `task.workflow` before the next step starts (Phase 9.5's per-step persistence,
  `workflows/runner.py:189-199`), and `CapabilityExecutor.execute()` re-fetches the task via
  `session.get()` at the top of every call (`capabilities/executor.py:69`) — since it's the same
  session and the same in-memory `EditorialTask` object was mutated in place, this reliably
  observes every prior step's result. Traced concretely for the full four-step chain: `quality`'s
  built context will contain `research`, `intelligence`, and `copywriting`'s outputs, exactly as
  §5.1 requires. No ordering problem, naming mismatch, or state-loss risk found.
- **OBS-4**: `CopywritingCapability`'s and the amended `QualityCapability`'s `required_context`
  fields aren't pinned by the Contract (§5, §5.1) — every existing Capability declares
  `required_context=["news_event"]`, but this field appears unused by `CapabilityExecutor` today
  (grep confirms no read of `CapabilityDefinition.required_context` anywhere in
  `capabilities/executor.py`). Not a defect — it's dead/forward-looking metadata already true of
  every existing Capability, not something Phase 10 introduces or needs to resolve.

---

# Authorized Implementation Scope

Every production file genuinely required for the full `Research → Intelligence → Copywriting →
Quality → ContentDraft → manual CLI` chain, independently derived this session, not copied from
the Contract's own list:

**Existing files requiring an edit:**
1. `workflows/definitions/content_generation.py` — step list expansion (4 steps).
2. `capabilities/quality_capability.py` — `_build_request()` + `PROMPT_VERSION` amendment.
3. `capabilities/registry.py` — two-line addition (import + `register()` call) for
   `CopywritingCapability`.

**New files required:**
4. `capabilities/copywriting_capability.py` — the new Capability itself.
5. `prompts/copywriting/v1.yaml` — its prompt content (required by Phase 6 §8's prompt-ownership
   rule; no Capability may embed prompt strings).
6. `prompts/quality/v2.yaml` — the amended Quality prompt version.
7. `schemas/content_draft.py` — `ContentDraftRead`, required as `ContentDraftService`'s declared
   return type.
8. `services/content_draft_service.py` — `ContentDraftService` itself.
9. `scripts/run_content_generation.py` — the manual CLI trigger; the only component that actually
   invokes the chain end-to-end.

**Files independently confirmed to need zero change** (verified this session, not assumed):
`capabilities/capability_mapping.py` (already maps `"copywriting"`), `workflows/registry.py`
(registers the `content_generation.DEFINITION` module object at import time — editing the steps
list inside that module is sufficient, no separate re-registration step exists or is needed),
`integrations/llm_gateway/boot.py` (`assemble_ai_integration_layer()` already accepts
`prompt_repository` as an injected parameter), `integrations/prompts/file_repository.py`
(directory/glob discovery is automatic), `database/models/__init__.py` (`ContentDraft` is already
exported), `capabilities/executor.py`, `workflows/runner.py` (both untouched, as the Contract
requires).

This list is **identical** to the Contract's own §3 authorized-file list (three existing-file edits
+ six new files). No hidden required file was found.

**COMPLETE.**

---

# Contract Readiness Score

**9 / 10** — every CRITICAL and MINOR finding from the prior final re-audit is genuinely fixed,
independently re-verified against live source rather than taken on the revision's word; the
authorized implementation scope is exhaustive and correct; the workflow data-flow was traced
concretely, not merely cited, and holds. One new MINOR, non-blocking documentation-precision
finding (§9's imprecise `run_triage.py` analogy) keeps this from a 10, but it does not affect
whether implementation can safely proceed.

---

# Final Verdict

PHASE 10 CONTRACT APPROVED
