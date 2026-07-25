# Phase 10 Architecture Contract — Final Re-Audit

**Status: audit document. Does not modify the Contract, production code, tests, or migrations.**
Re-audits `docs/phase10_production_content_pipeline_architecture_contract.md` (revision 2, post
first-audit correction pass) as untrusted. Every claim below was independently re-derived against
the current repository state, not taken on the Contract's, the first audit's, or the correction
report's word.

---

## 1. Executive Summary

All three MAJOR findings from the first audit were genuinely, correctly fixed — verified
independently below, not assumed from the revision report. `QualityCapability`'s adaptation is
narrowly scoped and citation-accurate (its "§4.2"/"§16" references were checked against the actual
Phase 8/6 contract text and hold). The timeout claim is honest. `ContentDraftService`'s session,
commit boundary, and failure semantics are all explicit.

However, this re-audit found **one new CRITICAL defect**, introduced by the correction pass's own
stronger wording, that neither the first audit nor the correction pass caught: **§3's own binding
text — "this Contract authorizes editing exactly two existing files, no more:
`workflows/definitions/content_generation.py` and `capabilities/quality_capability.py`" — never
authorizes editing `capabilities/registry.py` to register `CopywritingCapability`.** Without that
registration, `CapabilityRegistry.resolve("copywriting")` always raises `UnknownCapabilityError`,
and the `CONTENT_GENERATION` workflow can never reach `TaskStatus.COMPLETED` — directly
contradicting §1's own stated Purpose. `docs/phase10_decision_resolution.md`'s own M2 milestone row
(§13) already explicitly named "register Copywriting in `build_registry()`" as required — the
Contract's §3 restriction narrows and contradicts a scope its own governing Decision Resolution
document already correctly anticipated.

**Verdict: PHASE 10 CONTRACT NOT READY — CORRECTIONS REQUIRED.**

---

## 2. Verified Corrections

Each of the first audit's three MAJOR findings and the three additional requested items was
independently re-checked, not merely re-read:

**MAJOR-1 (QualityCapability) — genuinely fixed.** §5.1's amendment is narrow and accurate:
- Confirmed `capabilities/quality_capability.py:81-108` (`_build_request`) is the only method
  named for amendment, and `PROMPT_VERSION` is the only constant named — both real, existing,
  precisely-located symbols in the current file, re-verified by direct read this session.
- Confirmed the citation `capabilities/intelligence_capability.py:93-106` (the
  `step_results.get("research", {})` formatting pattern §5.1 says to mirror) is accurate — re-read
  directly; `_build_request` there does exactly that at those lines.
- Confirmed the "Phase 8 §4.2" citation (§5, §5.1, §15 item 2) is real and accurate: in
  `docs/phase8_capability_contract.md`, section "## 4. Capability Protocol," numbered rule 2 reads
  *"A `Capability` implementation MUST accept, at construction, only: an `LLMGateway` instance, a
  `PromptRepository` instance, and — only if it invokes at least one tool — a `ToolRegistry`
  instance."* — this is exactly the constructor-shape rule §5.1 claims is preserved (`__init__`
  unchanged). The "§16 / Amendment B" citation for `CapabilityExecutor`'s read-only session use is
  likewise confirmed accurate against `docs/phase6_architecture_contract.md:893` ("## 16. Amendment
  B — AIExecution Persistence Deferral"). Neither citation is fabricated.
- Confirmed `QUALITY_CAPABILITY_DEFINITION.expected_output_keys` (`["passed", "issues"]`) is
  unaffected by the amendment as claimed — the amendment touches only `_build_request()`'s input
  assembly, never `execute()`'s output construction.
- Confirmed `FilePromptRepository` (`integrations/prompts/file_repository.py:109-121`) auto-
  discovers `prompts/quality/v2.yaml` with zero code change, and independently keeps `v1.yaml`
  resolvable via an explicit `resolve("quality", "1")` call (`self._prompts` is a dict keyed by
  `(name, version)`, never pruned) — §5.1/§12's claims about `v1` remaining resolvable are accurate.
- **Capability isolation preserved**: the amendment adds no new constructor parameter, no new
  Capability-Protocol method, and no import of `copywriting_capability` — re-confirmed against
  Phase 8 Contract §4 rule 2 (constructor) and rule 5 (no provider SDK, unaffected) and the
  established AST-based non-coupling test pattern (§5, `tests/test_intelligence_capability.py:
  246-265`), which the Contract correctly says is mechanically extensible to this pair.

**MAJOR-2 (Timeout) — genuinely fixed.** §3 no longer claims `120`s is "proven sufficient." It now
states plainly that `120`/`30` are reused, pre-existing values (not new numbers), explicitly
withdraws the prior claim, and names that `NEWS_ANALYSIS` has never reached `COMPLETED` in this
codebase (re-confirmed: `capabilities/registry.py:134-138` still registers only
scoring/quality/research/intelligence — no `"engagement"` Capability exists). `WorkflowRunner`'s
timeout mechanics are stated as fully unchanged, with accurate line citations
(`workflows/runner.py:134-136`, `:239`) re-verified against the unmodified file.

**MAJOR-3 (ContentDraftService transaction ownership) — genuinely fixed, and internally consistent.**
§7.1 names the session (same one `WorkflowRunner.run()` used), the commit boundary (its own,
single, separate commit), and explicit failure semantics (a `COMPLETED` task with no
`ContentDraft` is a named, disclosed, non-hidden gap). The `expire_on_commit=False` precondition is
cited accurately: re-confirmed at `database/session.py:14`
(`async_session_factory = async_sessionmaker(engine, expire_on_commit=False)`) and
`tests/conftest.py:65` (`expire_on_commit=False` inside the test session fixture). The class-based
`ContentDraftService(session: AsyncSession)` design has genuine precedent in this codebase —
re-confirmed `services/budget_guard.py`'s `RedisBudgetGuard` is itself a class with an `__init__`,
not a plain-function module like `workflow_service.py` — so `ContentDraftService` as a class is not
an invented pattern.

**Additional items — all present and correctly scoped:**
- Copywriting output schema frozen in §5 (`title`/`body`/`hashtags`, typed, `required`), matching
  `ContentDraft`'s existing columns with no translation logic.
- Mandatory `ContentDraft` durability test added to §12, correctly mandating the
  `independent_session_factory()`/`real_committed_event()` technique and explicitly forbidding the
  `db_session` fixture for that one test.
- Prompt `expected_output` contract added to §6, correctly generalized as a rule (`output_schema.
  required` MUST equal `expected_output_keys`) rather than scoped only to Copywriting.

**Scope boundary re-attacked, no leakage found**: every section touched by this revision (§1, §3,
§5, §5.1, §6, §7, §7.1, §9, §12, §14, §15) was re-read for any mention of Telegram, meme/image
generation, a scheduler, analytics, monetization, a user system, or a second LLM provider being
introduced. None was found — §2's boundary, §10's Telegram exclusion, and §11's meme exclusion are
untouched, exactly as the revision report claims.

---

## 3. Findings Table

| # | Severity | Location | Summary |
|---|---|---|---|
| 1 | CRITICAL | Contract §3 (file-edit authorization) vs. §1 (Purpose) vs. Decision Resolution §13 M2 row | §3's "exactly two existing files, no more" never authorizes editing `capabilities/registry.py` to register `CopywritingCapability` — without which the pipeline can never reach `COMPLETED`. |
| 2 | MINOR | Contract §7.1 | `ContentDraftRead` (the method's declared return type) and `schemas/content_draft.py` are used/implied but never explicitly declared as an authorized new file, unlike `CopywritingCapability`'s explicit file coverage. |
| 3 | MINOR | Contract §7.1, §14 | The only detection mechanism for a "`COMPLETED` task with no `ContentDraft`" is a log line inside an unscheduled, manually-run CLI script — no query/report mechanism is named for a human to discover this later. |
| 4 | OBSERVATION | Contract §5.1 | A new, additive `DraftQualityCapability` was one alternative to amending `QualityCapability` in place; not discussed or explicitly ruled out, though the chosen approach matches the user's own correction instruction and Decision Resolution's reuse-first bias. |
| 5 | OBSERVATION | Contract §12 | The "empty `step_results['copywriting']`" regression test §5.1 mandates exercises a state that is not actually reachable via the real `CONTENT_GENERATION` chain once `copywriting` is `required: bool = True` (its default) — correct defensive coverage, but worth noting it tests a synthetic, not a production-reachable, path. |

---

## 4. CRITICAL Findings

### CRITICAL-1 — §3's file-edit authorization omits the one file that must change for the pipeline to function at all

**Location**: Contract §3 ("this Contract authorizes editing exactly two existing files, no more:
`workflows/definitions/content_generation.py` ... and `capabilities/quality_capability.py`...");
Contract §1 ("why Phase 10 exists: ... plus exactly one new Capability (`CopywritingCapability`)");
`capabilities/registry.py:116-139`; `docs/phase8_capability_contract.md`, section "## 5. Capability
Registry," rule 1; `docs/phase10_decision_resolution.md:290` (M2 milestone row).

**Evidence**: `capabilities/registry.py::build_registry()` is the sole place any `Capability` is
ever registered in this codebase — confirmed by direct read: it hardcodes four `registry.register(...)`
calls (scoring, quality, research, intelligence) and the module's own docstring states "No dynamic
discovery." Phase 8 Contract §5 rule 1 is binding and unconditional: *"Every `Capability`
implementation MUST be registered via `capabilities.registry.build_registry()` before
`CapabilityRegistry.seal()` is called."* There is no other registration path. For
`CopywritingCapability` — which the Contract's own §1 Purpose requires to exist and actually run —
to ever be dispatchable, `capabilities/registry.py` must gain a fifth import and a fifth
`registry.register(COPYWRITING_CAPABILITY_DEFINITION, CopywritingCapability(gateway,
prompt_repository))` call, exactly mirroring Phase 9 M6's own 4-line precedent for
Research/Intelligence.

`docs/phase10_decision_resolution.md`'s own M2 milestone row (line 290) already says this
explicitly: *"Expand `CONTENT_GENERATION`'s step list to `research → intelligence → copywriting →
quality`, reusing already-registered Capabilities; **register Copywriting in
`build_registry()`**."* The Contract, which sits above Decision Resolution in its own
source-of-truth order specifically to make binding, deliberate calls, does the opposite here: its
§3 sentence — added in the correction pass, more emphatic than the original draft's softer
"authorizes editing exactly one file" framing — explicitly forecloses any file edit beyond the two
named ones, silently dropping a requirement its own governing document already correctly named.

**Impact**: read literally and followed exactly, this Contract is self-contradictory in a way that
makes its own stated Purpose (§1: "the first Capability-driven content-generation pipeline that
reaches `TaskStatus.COMPLETED` for real") structurally impossible. `CapabilityExecutor.execute()`
would call `self._registry.resolve("copywriting")`, get `UnknownCapabilityError`, and raise
`PermanentStepFailureError` — every single time, at the very first new step in the chain,
regardless of how correctly `CopywritingCapability` itself is built and tested in isolation. This is
not a hypothetical edge case; it is the default, only, and certain outcome of implementing exactly
what §3 currently authorizes.

**Required correction**: add `capabilities/registry.py` as a third explicitly-authorized file in
§3's edit list, scoped narrowly (one new import line + one new `registry.register(...)` call,
mirroring Phase 9 M6's own precedent exactly — no other line of `build_registry()` changes). This
is a small, mechanical fix, but it must be made explicitly, in binding form, not left to an
implementer's inference — which is the same standard this Contract itself applied when it corrected
MAJOR-1 in the prior pass.

---

## 5. MAJOR Findings

None. All three MAJOR findings from the first audit are confirmed fixed (§2).

---

## 6. MINOR Findings

### MINOR-1 — `schemas/content_draft.py`/`ContentDraftRead` used but not explicitly authorized

**Location**: Contract §7.1 (`create_from_result(...) -> ContentDraftRead`).

`docs/phase10_decision_resolution.md` §8 explicitly named a new `schemas/content_draft.py` as
needed (mirroring `schemas/editorial_task.py`'s DTO pattern), but the Contract's own §7/§7.1 never
states this file must be created, unlike §5/§6's explicit, itemized coverage of every new
Copywriting-related file (`capabilities/copywriting_capability.py`, `prompts/copywriting/v1.yaml`).
This is a smaller, lower-stakes omission than CRITICAL-1 (creating a new file is implicitly covered
by §7's overall authorization to build `ContentDraftService`, unlike editing an existing,
previously-untouched production file), but should be named explicitly for the same precision
standard the rest of this Contract holds itself to.

**Required correction**: add one sentence to §7.1 naming `schemas/content_draft.py` and
`ContentDraftRead` as an authorized new file/type, mirroring `schemas/editorial_task.py`'s pattern.

### MINOR-2 — Detection of a "`COMPLETED` with no `ContentDraft`" gap relies solely on a log line

**Location**: Contract §7.1, §9, §14.

§7.1/§9 correctly require the CLI trigger to "log and surface this case distinctly," but Phase 10
has no scheduler, no monitoring, and explicitly no analytics (§13 item 5) — so the only way this
disclosed gap is ever actually noticed is if a human is watching the CLI's output at the exact
moment it happens. This is consistent with Phase 10's own deliberately minimal MVP scope and is not
a reason to block approval, but the Contract should be explicit that "bounded" here means "logged,"
not "discoverable after the fact" — a distinction §14's current wording blurs slightly.

**Required correction**: either accept and state explicitly that post-hoc discovery of this gap is
out of scope for Phase 10 (a one-sentence addition to §14, consistent with §13's existing analytics
exclusion), or note it as a natural candidate for a future phase's monitoring work.

---

## 7. Observations

**OBS-1**: an alternative to amending `QualityCapability` in place — adding a new, additive
`DraftQualityCapability` that leaves the original untouched — was not discussed or explicitly ruled
out in §5.1. The chosen approach (amend in place) directly follows the user's own correction
instruction ("require QualityCapability to consume copywriting output") and Decision Resolution's
general reuse-first bias, so this is not a defect, just worth naming for completeness.

**OBS-2**: §12's mandated test for `QualityCapability` given an *empty* `step_results["copywriting"]`
exercises a state that cannot actually occur via the real `CONTENT_GENERATION` chain once
`copywriting`'s `required` field is left at its default (`True`, per `schemas/workflow.py:52` —
unchanged by this Contract): if `copywriting` fails, the task fails via `_fail()` before `quality`
ever runs, so `quality` only ever executes when `step_results["copywriting"]` is already populated.
The test is good defensive coverage (and cheap), but the Contract should note it protects a
synthetic scenario (e.g., `QualityCapability` invoked directly in a unit test), not a real
production path — a small precision improvement, not a defect.

---

## 8. Contract Score

**6 / 10** — the correction pass genuinely fixed all three MAJOR findings from the first audit, with
every citation independently re-verified against real source, not just re-stated. But the
correction pass's own new, more emphatic file-edit restriction in §3 introduced a fresh CRITICAL
defect that makes the Contract's central Purpose unimplementable as literally written — a
one-sentence gap, but a load-bearing one, and exactly the kind of contradiction this repository's
own process exists to catch before a contract is approved.

---

## 9. Final Verdict

PHASE 10 CONTRACT NOT READY — CORRECTIONS REQUIRED
