# Phase 10 Architecture Contract — Adversarial Audit

**Status: audit document. Does not modify the Contract, production code, tests, or migrations.**
Every load-bearing claim in `docs/phase10_production_content_pipeline_architecture_contract.md`
("the Contract") was independently re-derived from the current repository state, not taken on the
Contract's or the Decision Resolution's word.

---

## 1. Executive Summary

The Contract's boundary discipline is sound: it correctly keeps `WorkflowRunner`/`CapabilityExecutor`
untouched, correctly identifies that `CONTENT_GENERATION`'s step-list edit has zero test blast
radius, correctly confirms no migration is needed, correctly confirms the Gateway/Protocol has no
image-generation surface, and correctly scopes Telegram/meme generation out. Those claims were all
independently re-verified and hold.

However, three **MAJOR** gaps were found, all load-bearing:

1. **`QualityCapability`, "reused unmodified," never reads any `step_results` — including
   `step_results["copywriting"]`.** Placing `quality` after `copywriting` does not quality-gate the
   generated draft; `QualityCapability` re-assesses only the raw `NewsEvent` (title/category/summary),
   exactly as its own prompt (`prompts/quality/v1.yaml`) says. The Contract never discloses this.
2. **The proposed `timeout_seconds=120` budget for a 4-step chain is justified by an appeal to
   evidence that does not exist.** The Contract claims this budget is "already proven sufficient for
   a 4-step AI chain by `NEWS_ANALYSIS`'s own frozen definition" — but `NEWS_ANALYSIS` has never
   reached `TaskStatus.COMPLETED` in this codebase (its `engagement` step has no registered
   Capability). The timeout math itself is also tight to the point of near-certain failure under any
   retry.
3. **Session/transaction ownership for the post-run `ContentDraft` write is unspecified.** §7's
   architecture diagram shows `WorkflowRunner.run() → content_draft_service.create_from_result(...)`
   but never says whether that function receives the same `AsyncSession` `WorkflowRunner` used, a
   fresh one, or a fresh connection — exactly the class of gap Phase 9.5's own Contract audit flagged
   as MAJOR (`expire_on_commit=False` dependency) for a nearly identical reason.

No CRITICAL finding was identified — nothing in the Contract is structurally impossible to
implement. But MAJOR-1 in particular means the pipeline, implemented exactly as specified, would
silently fail to deliver its own implied purpose.

---

## 2. Audit Methodology

Every claim below was checked by opening the cited file directly (not by trusting the Contract's or
Decision Resolution's paraphrase) via `Read`/`Grep`/`Glob` against the working tree at the time of
this audit. Where the Contract cites a specific file:line, that citation was independently
re-derived, not merely spot-checked for plausibility. Test-blast-radius claims were checked by
grepping the full `tests/` tree for the exact production symbols in question. No test was run and no
file was modified.

Files read in full or in relevant part: `workflows/definitions/content_generation.py`,
`workflows/definitions/news_analysis.py`, `workflows/runner.py`, `workflows/registry.py`,
`capabilities/registry.py`, `capabilities/capability_mapping.py`, `capabilities/executor.py`,
`capabilities/research_capability.py`, `capabilities/intelligence_capability.py`,
`capabilities/quality_capability.py`, `capabilities/scoring_capability.py`,
`database/models/content_draft.py`, `database/models/ai_execution.py`,
`database/models/telegram_channel.py`, `services/workflow_service.py`, `scripts/run_triage.py`,
`schemas/workflow.py`, `integrations/prompts/protocol.py`, `integrations/prompts/file_repository.py`,
`integrations/llm_gateway/protocol.py`, `integrations/llm_gateway/providers/openai_adapter.py`
(relevant sections), `integrations/llm_gateway/models/catalog.py`, `core/config.py`,
`scripts/validate_architecture.py`, `tests/test_intelligence_capability.py`,
`tests/test_phase9_research_intelligence_integration.py` (header), plus a repository-wide grep for
`CONTENT_GENERATION`, `retry_policy`, `expected_output`, and the non-coupling-test pattern.

---

## 3. Verified Claims

Claims independently re-derived and confirmed **accurate**:

- `workflows/definitions/content_generation.py`'s current, frozen definition is exactly as the
  Contract quotes it (2 steps, `timeout_seconds=60`) — confirmed byte-for-byte.
- `CAPABILITY_NAME` constants: `"research"` (`capabilities/research_capability.py:36`),
  `"intelligence"` (`capabilities/intelligence_capability.py:35`), `"quality"`
  (`capabilities/quality_capability.py:32`) — all confirmed exact.
- `capabilities/capability_mapping.py` already maps `"copywriting"` → `AICapability.COPYWRITING`
  and `"creative"` → `AICapability.CREATIVE` — confirmed, no edit to this file is required.
- `CapabilityExecutor._build_context()` (`capabilities/executor.py:125-134`) builds
  `workflow_state.step_results` as a dict of **every** prior `SUCCESS` step's `result`, keyed by
  `step_name` — not just the immediately-preceding step. This genuinely supports Copywriting reading
  both `step_results["research"]` and `step_results["intelligence"]` simultaneously.
- Phase 9.5's per-step persistence commit (`workflows/runner.py:189-199`) is present exactly as
  described, confirmed by direct read, not by memory of the Phase 9.5 Contract.
- **Zero test blast radius for the `content_generation.py` step-list edit**: a repository-wide grep
  for `content_generation.DEFINITION` and `from workflows.definitions import` inside `tests/`
  returned no matches. Every test that exercises `WorkflowType.CONTENT_GENERATION` constructs its
  own local `WorkflowDefinition` and passes an explicit local `registry=` override to
  `workflow_service.create_task()`/`WorkflowRunner()` (confirmed in `test_capability_executor.py`,
  `test_workflow_runner.py`, `test_workflow_runner_per_step_persistence.py`,
  `test_capability_boot_wiring_e2e.py`). The only real-registry assertion,
  `test_workflow_registry.py:71`, checks only `.name`, unaffected by a step-list change. The
  Contract's claim that this is a narrow, safe amendment is correct.
- `database/models/content_draft.py`'s `ContentDraft` model has every column the Contract's §7
  lifecycle needs (`task_id`, `type`, `title`, `body`, `hashtags`, `version`, `status`) — no
  migration is required, confirmed by direct read of the model.
- `services/workflow_service.py::_find_active_task()` (lines 89-106) scopes active-task uniqueness
  to `(event_id, workflow_type)`, confirmed exactly as the Contract's §4 states — a `NEWS_ANALYSIS`
  and a `CONTENT_GENERATION` task for the same event are independent rows.
- `integrations/prompts/file_repository.py`'s `FilePromptRepository.__init__` auto-discovers
  `root/<name>/v<N>.yaml` directories at construction time (lines 109-121) — adding
  `prompts/copywriting/v1.yaml` requires **zero** code change to the repository class itself,
  confirming the Contract's §6 claim precisely.
- `integrations/llm_gateway/providers/openai_adapter.py`'s `generate()` hardcodes `artifacts=None`
  (line 279) and `integrations/llm_gateway/models/catalog.py`'s `OPENAI_MODELS` contains exactly
  three text-only chat models (Sol/Terra/Luna), no image-generation model — confirms the Contract's
  §11 claim that no image-output path exists anywhere in the current Gateway stack.
- `capabilities/capability-isolation` architecture-validator rule (`scripts/validate_architecture.py:
  112-146`) does **not** forbid a Capability file from importing `database.models.content_draft`
  (only `database.session`/`sqlalchemy` directly) — the Contract's §12 claim that a *new,
  not-yet-written* mechanical test is needed to enforce "no Capability creates a `ContentDraft`" is
  correctly scoped as future work, not misrepresented as an already-enforced rule.
- The AST-based non-coupling test technique the Contract's §5 cites
  (`tests/test_intelligence_capability.py::test_non_coupling_never_imports_research_capability`,
  lines 246-265) exists exactly as described and is mechanically reusable for a Copywriting
  equivalent.
- Telegram: `bot/` contains only `handlers/`, `keyboards/`, `middlewares/`, `loader.py`, `main.py` —
  no `services/`-level content-drafts-to-Telegram directory or publishing service exists anywhere in
  the repository. The Contract's §10 "not implemented in Phase 10" claim holds.

---

## 4. Findings Table

| # | Severity | Location | Summary |
|---|---|---|---|
| 1 | MAJOR | Contract §3, §5; `capabilities/quality_capability.py:81-108`; `prompts/quality/v1.yaml` | `QualityCapability`, reused unmodified, never reads `step_results["copywriting"]` (or any `step_results` key) — the `quality` step cannot quality-gate the generated draft. |
| 2 | MAJOR | Contract §3; `workflows/runner.py:217-272`; `workflows/definitions/news_analysis.py`; `capabilities/registry.py:116-139` | `timeout_seconds=120` for a 4-step chain is justified by an unproven precedent (`NEWS_ANALYSIS` has never reached `COMPLETED`) and the timeout math itself leaves no margin for any retry. |
| 3 | MAJOR | Contract §7 | Session/transaction ownership for `content_draft_service.create_from_result()` is unspecified — same class of gap Phase 9.5's own Contract audit flagged as MAJOR. |
| 4 | MINOR | Contract §5 | `CopywritingCapability` is restricted to `news_event.title`/`category` only (no `content`), a Contract-level decision not derived from Decision Resolution, unjustified beyond an analogy to Intelligence. |
| 5 | MINOR | Contract §12 | No durability/session test is mandated for `ContentDraft` persistence, despite Phase 9.5 M2 establishing exactly this class of test as necessary for any new per-step or post-run DB write. |
| 6 | MINOR | Contract §3; `workflows/definitions/content_generation.py:30` | `expected_output=["draft_content", "quality_report"]` is left stale in the Contract's own proposed diff — doesn't name `research`/`intelligence` outputs, even as non-binding documentation. |
| 7 | OBSERVATION | `capabilities/registry.py:134-138`; `docs/phase9_9_5_completion_report.md` §9 item 3 | `NEWS_ANALYSIS` has never completed in this system — its `engagement` step has no registered Capability (`build_registry()` registers only scoring/quality/research/intelligence). Directly underlies Finding 2. |
| 8 | OBSERVATION | `integrations/llm_gateway/protocol.py:85-94` | `GenerateResponse.artifacts: list[ArtifactRef] \| None` already exists on the Protocol, unused by any adapter — a latent extension point, not a contradiction of Contract §11's claims. |
| 9 | OBSERVATION | `schemas/workflow.py:31-38`; repo-wide grep | `WorkflowDefinition.retry_policy` (`WorkflowRetryPolicy`) is never referenced by `WorkflowRunner` anywhere — dead/vestigial Phase 5 field. Actual retry ceiling is governed solely by `WorkflowStepDefinition.max_attempts` (default 3). Pre-existing, not introduced by Phase 10, but relevant context for Finding 2. |

---

## 5. CRITICAL Findings

None. Nothing in the Contract is structurally impossible to implement, and no proposed change
contradicts a frozen Phase 5/6/8/9/9.5 rule outright.

---

## 6. MAJOR Findings

### MAJOR-1 — `QualityCapability` cannot quality-gate Copywriting's output as currently written

**Severity**: MAJOR — the Contract can enter implementation, but as specified, it silently fails to
deliver what its own step ordering implies.

**Location**: Contract §3 ("reusing the already-registered ... `quality`") and §5 (Copywriting's
Input/Output contract, silent on what `quality` does with Copywriting's result);
`capabilities/quality_capability.py:81-108` (`_build_request`); `prompts/quality/v1.yaml:1-7`.

**Evidence**: `QualityCapability._build_request()` builds its `GenerateRequest` from exactly
`news_event.title`, `news_event.category`, `news_event.summary`, and `context.business.language` —
confirmed by direct read of lines 86-92. It never touches
`context.business.workflow_state.step_results` at all — no `.get("copywriting", ...)`, no reference
to `step_results` anywhere in the file. Its own prompt content
(`prompts/quality/v1.yaml`, lines 4-7) states its scope explicitly: *"Given a news event's title,
category, and summary, you assess whether it meets basic editorial quality standards"* — the
NewsEvent's own inherent editorial merit, not any generated content. This is true of `quality` today,
even under the currently-frozen 2-step `copywriting → quality` definition — `quality` has never, at
any point in this codebase's history, read Copywriting's output.

**Why it matters**: the Contract's own Purpose (§1) and Workflow Decision (§3) present
`research → intelligence → copywriting → quality` as an ordered pipeline where `quality` is the final
gate before a `ContentDraft` is persisted. A reader (and any future implementer) will reasonably
assume `quality` reviews the draft `copywriting` just produced. It does not, and cannot, without a
code change. Per Decision Resolution's own M2 milestone table (§13), "Any change to
Research/Intelligence/Quality" is explicitly excluded from that milestone's scope — meaning the
Contract, by insisting Quality is "reused unmodified," structurally locks in a `ContentDraft` that
gets persisted after a "quality" step that never actually looked at it. This is exactly what audit
checklist item 3 ("whether each Capability receives enough information") and item 1 ("hidden
workflow coupling / incorrect assumptions about `WorkflowRunner`") ask to be found — and it is nowhere
disclosed in the Contract's Risks (§14).

**Required correction**: the Contract must explicitly choose one of:
(a) state plainly that `quality`, as positioned, evaluates the underlying `NewsEvent`'s editorial
merit only — never the generated draft — and adjust §1/§3/§5's framing so no reader infers otherwise
(cheapest fix, zero code impact); or
(b) authorize a narrow, explicitly-scoped extension to `QualityCapability` (or a distinct capability)
to also read `step_results["copywriting"]`, which requires revisiting Decision Resolution §13's
stated non-goal for M2 and should be done consciously, not by omission.

### MAJOR-2 — `timeout_seconds=120` is justified by an unproven precedent and leaves no retry margin

**Severity**: MAJOR.

**Location**: Contract §3 ("the same 120s budget already proven sufficient for a 4-step AI chain by
`NEWS_ANALYSIS`'s own frozen definition"); `workflows/runner.py:133-145, 217-272`;
`workflows/definitions/news_analysis.py:31`; `capabilities/registry.py:134-138`.

**Evidence**: `WorkflowRunner.run()` wraps the *entire* remaining step loop in one outer
`asyncio.wait_for(..., timeout=definition.timeout_seconds)` (`workflows/runner.py:134-136`). Inside
that loop, `_run_step()` gives **each individual attempt** of a step its own fresh
`timeout_seconds` budget (`workflows/runner.py:239`, inside a `for attempt in range(1,
step.max_attempts + 1)` loop) — `WorkflowStepDefinition.max_attempts` defaults to 3
(`schemas/workflow.py:53`) and is not overridden by either `news_analysis.py` or
`content_generation.py`. This means a single step that needs even one retry can alone consume
`2 × 30s = 60s`; a step needing all 3 attempts can consume `90s` — against a 120s *whole-workflow*
ceiling shared by all 4 steps combined. Zero steps have any margin if even one of the four needs a
single retry.

The Contract's justification that this budget is "already proven sufficient" by `NEWS_ANALYSIS`
does not hold: `capabilities/registry.py::build_registry()` (lines 134-138) registers only
`scoring`, `quality`, `research`, `intelligence` — there is no registered Capability named
`"engagement"`, which is `NEWS_ANALYSIS`'s third step (`workflows/definitions/news_analysis.py:22`,
`capability="engagement"`). Resolving it raises `UnknownCapabilityError` →
`PermanentStepFailureError` inside `CapabilityExecutor.execute()`. This matches
`docs/phase9_9_5_completion_report.md` §9 item 3's own, already-recorded finding: *"the real workflow
still ends FAILED."* `NEWS_ANALYSIS` has therefore never run to `COMPLETED` in this system, live or
otherwise — its 120s budget has never been exercised end-to-end, let alone "proven sufficient."

**Why it matters**: this is the load-bearing number for whether Phase 10's actual deliverable (a
`CONTENT_GENERATION` task reaching `TaskStatus.COMPLETED` against the real OpenAI API) succeeds on a
normal run, let alone one with any transient failure. If it is too tight, the first live run is
likely to fail via `WorkflowTimeoutError`, undermining the Contract's own §1 Purpose.

**Required correction**: either (a) independently derive a real timeout budget from expected live
OpenAI Responses API latency for the specific prompts involved (informed by the M0 smoke test
Decision Resolution §13 already schedules), rather than citing an unexercised precedent, or (b)
explicitly acknowledge the budget is a first-pass estimate subject to revision after M0's live smoke
test, and drop the "already proven sufficient" claim.

### MAJOR-3 — Session/transaction ownership for the post-run `ContentDraft` write is unspecified

**Severity**: MAJOR.

**Location**: Contract §7 ("Architecture, frozen" diagram: `WorkflowRunner.run() →
services.content_draft_service.create_from_result(...) → ContentDraft row").

**Evidence**: the Contract states the creation function is called "after `WorkflowRunner.run()`
returns a `COMPLETED` `WorkflowRunResult`" but never states what `AsyncSession` that function uses.
`services/workflow_service.py` and `workflows/runner.py` both take an explicit `session: AsyncSession`
parameter supplied by the caller; there is no established precedent in this repository for a
`services/`-layer write happening implicitly on "whatever session is lying around" versus an
explicitly fresh one. This matters concretely: if `content_draft_service.create_from_result()` reuses
the *same* session `WorkflowRunner.run()` already used and committed on, that session's identity-map
state and any framework-level assumptions carried over from Phase 9.5's `expire_on_commit=False`
dependency (`database/session.py:14`) need to be positively confirmed to still hold for a *new*
INSERT issued after the run's own final commit — not merely assumed by analogy. If it opens a fresh
session/connection instead, the CLI trigger (§9) needs to explicitly own two separate transactions
with defined failure semantics (what happens if the workflow completes but the `ContentDraft` write
fails?) — a question the Contract's Risks (§14) does not name.

**Why it matters**: Phase 9.5's own Contract audit (cited approvingly by this repository's own
history) treated an almost identical class of omission — an unstated session-lifecycle dependency —
as MAJOR-1, specifically because it is exactly the kind of gap that looks fine on paper and breaks at
runtime (`MissingGreenlet`-class errors, or silent partial completion where a task is `COMPLETED` but
its `ContentDraft` never got written). The Phase 10 Contract, citing Phase 9.5 as its own stylistic
and architectural precedent, does not apply that lesson to its own new cross-boundary write.

**Required correction**: §7 must state explicitly which session `content_draft_service.
create_from_result()` uses (the same one as the just-completed `run()` call, or a new one it opens
itself), and must state the failure semantics if the `ContentDraft` write fails after
`WorkflowRunner.run()` has already durably committed `TaskStatus.COMPLETED` (a task that completed
successfully but has no corresponding draft is a real, reachable state that needs a named answer, even
if the answer is "out of scope, logged as a known gap").

---

## 7. MINOR Findings

### MINOR-1 — Copywriting's input restriction to title/category (no raw `content`) is under-justified

**Location**: Contract §5 ("reads exactly `context.business.news_event`... title/category only").

Decision Resolution §6/§7 decides *that* Copywriting reads `step_results["research"]`/
`["intelligence"]`, but never decides that it must additionally be barred from `news_event.content`.
The Contract adds this restriction on its own authority, justified only by analogy to
`IntelligenceCapability`'s "MUST NOT re-extract facts" rule — a rule that exists for a different
reason (Intelligence must not duplicate Research's extraction work). Copywriting is not extracting
facts; it is producing prose, for which direct access to source material is a normal and often
quality-improving input (style, direct quotes, tone). This is a legitimate design choice the Contract
is allowed to make, but it should be justified on its own terms rather than borrowed from an
inapplicable precedent, since it will directly affect drafting quality once M0's live smoke test runs.

**Required correction**: either justify this restriction independently, or relax it to allow
`news_event.content` as an optional additional input.

### MINOR-2 — No durability/session test mandated for `ContentDraft` persistence

**Location**: Contract §12 (Testing Requirements, "ContentDraft tests").

The listed tests check *ordering* (only after `COMPLETED`) and *isolation* (no Capability creates a
draft), but not durability — whether a created `ContentDraft` row is actually visible to a genuinely
independent connection, the same class of test Phase 9.5 M2 built specifically because the standard
`db_session` fixture's SAVEPOINT-based semantics can produce a false pass (Phase 9.5 Contract Audit
MAJOR-2, already an established precedent in this repository). This connects directly to MAJOR-3
above — once session ownership is decided, its correctness should be positively tested the same way.

**Required correction**: add an independent-connection durability test for `ContentDraft` persistence
to §12, reusing the same `independent_session_factory()`/`real_committed_event()`-style precedent
already established in `tests/test_triage_orchestrator_claims.py` and reused in
`tests/test_workflow_runner_per_step_persistence.py`.

### MINOR-3 — `expected_output` left stale in the Contract's own proposed diff

**Location**: Contract §3; `workflows/definitions/content_generation.py:30`.

The Contract's proposed 4-step `DEFINITION` snippet does not update `expected_output=
["draft_content", "quality_report"]`, even though the Contract itself notes this field "MAY be
extended... implementation detail, not frozen here." Since this field is purely declarative
(confirmed unreferenced by any runtime code via repo-wide grep), leaving it stale costs nothing
functionally, but it is a small, free-to-fix documentation inconsistency inside a document whose
entire purpose is precision.

**Required correction**: either extend `expected_output` in the Contract's own snippet, or state
explicitly that it is deliberately left unchanged and why.

---

## 8. Observations

**OBS-1**: `NEWS_ANALYSIS` has never reached `TaskStatus.COMPLETED` in this codebase — confirmed via
`capabilities/registry.py:134-138` (no `"engagement"` Capability registered) and independently
corroborated by `docs/phase9_9_5_completion_report.md` §9 item 3's own prior finding. This is not
new information, but it is worth stating plainly here because MAJOR-2 depends on it, and because any
future Contract that cites `NEWS_ANALYSIS` as a "working precedent" for anything should be read
skeptically until that gap is closed.

**OBS-2**: `GenerateResponse.artifacts: list[ArtifactRef] | None` already exists on the Gateway
Protocol (`integrations/llm_gateway/protocol.py:91`) and is hardcoded to `None` by the only adapter
(`openai_adapter.py:279`). This does not contradict Contract §11's claims (no method, no model, no
adapter support for image *generation*) — but it is worth noting the Protocol's shape already has an
unused extension point that a future meme-generation phase might reach for before reaching for a
Protocol amendment. Not actionable now.

**OBS-3**: `WorkflowDefinition.retry_policy` (`WorkflowRetryPolicy`) is declared on every
`WorkflowDefinition`, including the Contract's proposed one, but is never read by
`workflows/runner.py` or anywhere else in the codebase (confirmed by repo-wide grep for
`.retry_policy`). The actual, enforced retry ceiling is `WorkflowStepDefinition.max_attempts`
(per-step, default 3). This is a pre-existing Phase 5 characteristic, not introduced or worsened by
the Contract, but it directly explains why MAJOR-2's timeout math is as tight as it is — retries are
real and unavoidable, governed by a field the workflow-level `retry_policy` gives no visibility into.

---

## 9. Contract Score

**7 / 10** — architecturally sound boundary discipline (Phase 5/6/8/9/9.5 respected, no coupling
violations, no unnecessary migration, correct Telegram/meme exclusion), but not yet safe to hand to
an implementer: MAJOR-1 means the pipeline as specified silently fails its own implied purpose, and
MAJOR-2/MAJOR-3 are both exactly the class of unstated-precondition gap this repository's own process
has already learned, once, to catch before freezing a contract (Phase 9.5's own audit history).

---

## 10. Required Corrections

Before this Contract can be approved:

1. **MAJOR-1**: explicitly resolve what `quality` actually evaluates in the 4-step chain — either
   correct the Contract's framing to state it reviews the `NewsEvent`, not the draft, or authorize a
   scoped change to make it actually read `step_results["copywriting"]` (reopening Decision
   Resolution's M2 non-goal deliberately, not by omission).
2. **MAJOR-2**: replace the "already proven sufficient" claim with either an independently-derived
   timeout budget or an explicit acknowledgment that it is a first-pass estimate pending M0's live
   smoke test.
3. **MAJOR-3**: state explicitly which `AsyncSession` `content_draft_service.create_from_result()`
   uses, and name the failure semantics for a `COMPLETED` task whose `ContentDraft` write fails.
4. **MINOR-1/2/3**: recommended before implementation, not blocking on their own — but should be
   folded into the same correction pass as the MAJOR items above, since all three touch the same
   sections already being revised.

---

## 11. Final Verdict

PHASE 10 CONTRACT NOT READY — CORRECTIONS REQUIRED
