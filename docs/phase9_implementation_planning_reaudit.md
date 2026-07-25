# Phase 9 Implementation Planning — Final Narrow Re-Audit

**Status: audit document. NOT a specification. NOT binding. Verification only** — no modification was
made to `docs/phase9_research_intelligence_planning.md`, the Contract, production code, or any
migration. Every claim re-checked this pass against the actual repository, fresh — `pydantic`'s
installed version (`2.13.4`, confirmed via `python -c "import pydantic; print(pydantic.VERSION)"`),
`core/config.py`'s current imports, `database/session.py`'s `async_session_factory` configuration,
and — critically — three existing test files
(`tests/test_workflow_registry.py`, `tests/test_workflow_service.py`, `capabilities/registry.py`'s
own docstring) that reference `WorkflowType.DAILY_DIGEST`, none of which were cited in the revision
itself and which this pass found independently to further corroborate M7's choice.

---

## 1. Executive Summary

Both MAJOR findings and all five MINOR findings from `docs/phase9_implementation_planning_audit.md`
are **RESOLVED**. The revised M3 now specifies an explicit, mechanically-checkable Phase A / Phase B
transaction model that correctly implements the Contract's "claim already committed in step 1"
premise and correctly guarantees batch isolation, verified against `services/workflow_service.py`
and `services/collector.py` line-for-line. `stale_processing_threshold_seconds` now carries a
`Field(gt=0)` constraint, confirmed to be valid, standard, fully-supported syntax against the actual
installed Pydantic version, correctly triggering a startup-time `ValidationError` for `0` or negative
values. All five MINOR clarifications are precise, well-grounded, and — in the case of M7's
`WorkflowType.DAILY_DIGEST` choice — turn out to be even more strongly supported by existing
repository precedent than the revision itself cited.

**One new, genuinely subtle transaction-safety question was independently checked this pass and
found already resolved by existing infrastructure, not by the Plan's own text**: whether an ORM
object loaded before Phase A's commit would become stale/expired afterward (SQLAlchemy's default
`expire_on_commit=True` behavior) in a way that could break Phase B's subsequent reads. Confirmed
`database/session.py`'s `async_session_factory` already sets `expire_on_commit=False`, so this
hazard does not arise — the Plan's transaction discipline is safe against this specific,
easy-to-overlook SQLAlchemy pitfall, even though the Plan's own text never explicitly discusses it.
Recorded as an OBSERVATION, not a finding, since no correction is needed.

**No CRITICAL, no MAJOR, no unresolved finding remains.** Two trivial OBSERVATION-level notes are
recorded (a cosmetic type-annotation choice in the shared fixture; the `expire_on_commit` check
above) — neither blocks approval.

---

## 2. M3 Transaction Discipline Re-Audit

Checked against the actual `services/workflow_service.py` (re-read this pass: `create_task()`
commits internally at line 71 only on its own success path; nothing else in that file writes to
`NewsEvent`) and `services/collector.py` (re-read this pass: one shared session per cycle, commit
once per source, explicit `await session.rollback()` in the per-source `except` handler).

| # | Requirement | Verified |
|---|---|---|
| 1 | Claim/CAS committed before Triage, source-dependent work, and `create_task()` | **Yes** — Phase A's text is explicit: `await session.commit()` immediately upon a winning claim/CAS, structurally before Phase B (which contains the `NewsSource` load, Triage call, and `create_task()` call) ever begins. |
| 2 | Losing claimant does not call Triage or `create_task()`, safely moves on | **Yes** — Phase B is described as reachable only "inside the `if won:` branch, never reached otherwise"; a `False` result skips directly to the next loop iteration with no exception and no log entry, matching §18's "not an error" classification exactly. |
| 3 | Phase B failures call `session.rollback()` before reuse | **Yes**, for both failure branches (`DuplicateActiveTaskError` and "any other exception") — the revision deliberately applies rollback uniformly to both, avoiding a fragile special case, and states this explicitly rather than leaving it implicit. |
| 4 | Committed claim not undone by Phase B rollback | **Yes**, and correctly reasoned: since Phase A's commit already closed that transaction before Phase B's own (separate) transaction began, a rollback of Phase B's transaction cannot retroactively affect Phase A's already-durable transaction. This is standard, correct transactional semantics, not an assumption. |
| 5 | One shared session per batch can safely continue after rollback | **Yes** — `session.rollback()` resets the session to a clean, usable state (standard SQLAlchemy behavior); the Plan's own test #3 ("post-claim failure triggers rollback") directly proves this via a trivial follow-up query, not merely asserted. |
| 6 | `create_task()`'s own transaction behavior does not invalidate the ordering | **Yes** — `create_task()`'s internal commit (line 71) only ever finalizes *successful* Phase B work; it is never relied upon to make the claim durable (that already happened in Phase A), so nothing about `create_task()`'s own commit timing can undermine the ordering this revision specifies. |
| 7 | Residual `PROCESSING` + no active task is intentionally, later, recoverable | **Yes**, explicitly named as "not a bug this revision introduces or needs to prevent... the correct, intended outcome," and mapped to the same, already-approved M2 recovery path (`_select_recovery_candidates` + `_acquire_recovery_ownership`), not a new mechanism. |
| 8 | Two-event runtime proof sufficiency | **Yes, sufficient for what it claims to prove** — one event forced to fail after a successful claim, one event succeeding normally, in the *same* `run_triage_cycle()` invocation, with real DB state queried afterward. This is the minimum sufficient scenario to distinguish "isolated per-event handling" from "session-wide poisoning," which is exactly the property being verified; it does not need to be larger (e.g., ten events) to make this specific point. |

**Additional, independently-verified transaction-safety check (not requested by name, but implied by
"look for impossible transaction assumptions")**: SQLAlchemy's `AsyncSession` defaults to
`expire_on_commit=True`, which would normally invalidate a previously-loaded ORM object's attributes
after any commit, forcing an implicit re-`SELECT` on next access. Re-checked `database/session.py`
this pass: `async_session_factory = async_sessionmaker(engine, expire_on_commit=False)` — this
default is already overridden repository-wide, for both the production session factory and the test
`db_session` fixture (`tests/conftest.py`, also `expire_on_commit=False`). Phase A's commit therefore
does not risk silently expiring any `NewsEvent`/`NewsSource` object Phase B goes on to read — a real
SQLAlchemy hazard that would have been easy to introduce unknowingly, already closed by existing
infrastructure the Plan correctly relies on without needing to say so explicitly.

**No impossible transaction assumption found.** Every assumption traces to either standard,
well-understood SQLAlchemy/Postgres transaction semantics or an already-verified repository fact.

**Verdict: RESOLVED.**

---

## 3. Stale Threshold Validation Re-Audit

Verified against the actual installed configuration stack, not assumed:

- `python -c "import pydantic; print(pydantic.VERSION)"` → `2.13.4` — a modern Pydantic v2 release;
  `Field(gt=0)` is standard, fully-supported, unchanged syntax across all Pydantic v2 minor versions.
- `core/config.py`'s `Settings(BaseSettings)` (re-read this pass) is exactly the correct class — the
  Plan's own citation is accurate.
- `Field` is not currently imported in `core/config.py` (only `SecretStr` is) — a one-line import
  addition (`from pydantic import Field, SecretStr`) is needed at implementation time. This is
  ordinary implementation freedom, not an ambiguity — there is only one place this import can
  sensibly go, and the Plan's own instruction not to over-specify trivial mechanics is correctly
  applied here (not flagged as a finding).
- Positive values accepted: confirmed — `Field(gt=0)` imposes no upper bound and no other
  constraint, so `900` and any other positive integer construct `Settings` normally.
- `0` rejected: confirmed — `gt=0` means "strictly greater than zero"; `0` fails this constraint and
  `pydantic.ValidationError` is raised.
- Negative values rejected: confirmed, same constraint.
- Env override still works: `pydantic-settings`'s `BaseSettings` coerces an environment-variable
  string to the declared `int` type *before* applying `Field` constraints — this is standard,
  unmodified `pydantic-settings` behavior, not something Phase 9 needs to implement; the Plan
  correctly relies on it rather than reimplementing coercion/validation.
- Architecture invariant cannot be disabled accidentally: confirmed — because `settings =
  get_settings()` executes eagerly at module import time (unchanged, pre-existing pattern), an
  invalid value crashes the process at startup, before any Phase 9 code path that depends on it could
  run with a bad value. There is no code path that catches this `ValidationError` and falls back to a
  default — none is planned, and none should be (the Plan explicitly states "not a silent clamp...
  not a silent fallback").
- Exact default remains product configuration: confirmed — only the `900` default value is
  labeled configurable (Contract §22); the `gt=0` constraint itself is stated as architecture, not
  configuration, matching Contract §7.6 rule 5's exact framing ("its *existence and positivity* are
  not [configuration]").

**Verdict: RESOLVED.**

---

## 4. M0 Validator Re-Audit

Re-checked all three retained rules against the full, current `scripts/validate_architecture.py`
(re-read this pass in full — unchanged since the original audit).

| Rule | Forbidden edge | Target | Existing coverage? | Mechanically enforceable? | False-positive risk | Exclusion list needed? |
|---|---|---|---|---|---|---|
| `freshness-purity` | No DB, no other `services/` module, no `LLMGateway` | `services/freshness.py` | None — no existing rule scopes to this path | Yes, plain import-prefix match | None found — Freshness's only legitimate import is the stdlib | No — single-file `_under()` rule, correctly not `_under_excluding()` |
| `triage-purity` | No DB, no `LLMGateway`, no Capability layer, no `workflows` | `services/triage.py` | None | Yes | None found — `services.freshness` and `database.models.editorial_task.TaskPriority` are both correctly left unforbidden | No |
| `triage-orchestrator-isolation` | No `LLMGateway`, no `capabilities.*` (blanket), no provider SDK | `services/triage_orchestrator.py` | Provider-SDK half already covered by `provider-sdk-confinement` (disclosed, deliberate, minor overlap for error-message locality, not a hidden redundancy) | Yes | None found — `services.workflow_service` and `schemas.workflow` are both correctly, explicitly left unforbidden (re-confirmed: neither is under a `capabilities.` or `integrations.llm_gateway` prefix, so the blanket rule cannot accidentally catch them) | No |

**Blanket `capabilities.` prefix, specifically re-audited**: confirmed this correctly and completely
prevents the Orchestrator from depending on any Capability implementation or internal
(`capabilities.registry`, `capabilities.executor`, `capabilities.errors`,
`capabilities.capability_mapping`, `capabilities.research_capability`,
`capabilities.intelligence_capability`, `capabilities.gateway_call` — all caught) while never
touching a legitimate, frozen abstraction the Orchestrator actually needs
(`services.workflow_service.create_task`, `schemas.workflow.WorkflowType`,
`database.models.news_event.*`, `database.models.editorial_task.*` — none of these live under
`capabilities.`, so none is caught). This is strictly *more* robust than the original four-item
enumeration it replaced (which would have missed a hypothetical future
`capabilities/some_other_capability.py` the Orchestrator should also never import) without any new
false-positive surface.

**No rule found redundant. No rule found in need of further shrinking.** The one disclosed, minor
overlap with `provider-sdk-confinement` remains a deliberate, stated design choice (single-message
error locality), not a hidden or accidental duplication, matching the Plan's own reasoning exactly.

**Verdict: VALID.**

---

## 5. Research→Intelligence Fixture Re-Audit

Checked `tests/fakes/research_output.py`'s planned design against every item requested:

- Represents only the Research structured-output contract: confirmed — `CANONICAL_RESEARCH_OUTPUT`'s
  three keys (`facts`, `confidence`, `gaps`) match exactly M4's own stated output shape, nothing more.
- Not a production schema: confirmed — it lives in `tests/fakes/`, an existing, already-established
  test-double directory; no production file in this repository imports from `tests/` anywhere
  (re-confirmed by the existing convention — `capabilities/scoring_capability.py`,
  `capabilities/quality_capability.py` neither import test code, and nothing in this Plan's
  production-scope sections for M4/M5 references `tests/fakes/research_output.py`).
- M4 owns creation: confirmed, explicit in M4's Files/Implementation scope.
- M5 imports it only in tests: confirmed — M5's "Implementation scope" (§4, production code) makes
  no reference to it at all; only M5's "Tests required" (§6) imports it.
- Production `IntelligenceCapability` does not import test code: confirmed by the same check.
- Fixture does not become a hidden coupling mechanism between the production Capabilities: confirmed
  — the two Capabilities' *production* files remain fully decoupled (no import of one by the other,
  consistent with §9.1's binding rule); only their *test suites* share this one constant, which is
  precisely test-scaffolding sharing, not production coupling.
- Changing Research's output incompatibly would fail M5's compatibility test: confirmed as designed
  — M5's positive test imports the *same* `CANONICAL_RESEARCH_OUTPUT` object M4's own test asserts
  its real output matches; a shape change to one side without the other would surface as a concrete
  test failure, not a silent drift.

**Smallest safe approach**: confirmed — reuses an existing directory and convention, introduces one
plain dict constant, no new framework, no new type system, no schema validation library.

**One cosmetic OBSERVATION**: `CANONICAL_RESEARCH_OUTPUT: dict[str, object]` uses `object` as the
value-type annotation. `object` is a stricter (less permissive) type than the `Any` used elsewhere in
this codebase for the equivalent field (`CapabilityResult.structured_output`, and every other
Capability's own `structured_output` dict) — a consumer typing this constant strictly could see mypy
friction using its values in contexts that expect `Any`-typed structured output. A one-character fix
(`dict[str, Any]`) at implementation time resolves it; not required to be specified in the Plan
itself, since this is exactly the class of trivial typing detail ordinary implementation judgment
handles.

**Verdict: VALID WITH MINOR NOTE** (the note above; non-blocking).

---

## 6. Synthetic WorkflowType Re-Audit

Independently re-verified against the actual repository, going beyond the precedent the revision
itself cited (`tests/test_capability_boot_wiring_e2e.py`'s `CONTENT_GENERATION` reuse):

- **No new enum member added or planned**: confirmed — `schemas/workflow.py`'s `WorkflowType` is
  never listed among M7's (or any milestone's) files to modify anywhere in the Plan.
- **No production `DAILY_DIGEST` definition mutated**: confirmed there is no production
  `DAILY_DIGEST` `WorkflowDefinition` to mutate in the first place —
  `workflows/definitions/__init__.py`'s own docstring (re-read this pass) states plainly: "Only
  `NEWS_ANALYSIS` and `CONTENT_GENERATION` are defined here. `DAILY_DIGEST` is deliberately absent"
  (because `EditorialTask.event_id` is a single foreign key, unrelated to Phase 9's synthetic-test
  use). M7's synthetic definition exists only inside its own, local, test-scoped `WorkflowRegistry()`
  instance and touches nothing in `workflows/definitions/`.
- **Test registration isolated**: confirmed — a local `WorkflowRegistry()`, never the global
  `workflows.registry.registry` singleton, matching the already-real `CONTENT_GENERATION` precedent
  exactly.
- **No semantic behavior of `DAILY_DIGEST` leaks into the proof**: confirmed — `DAILY_DIGEST` carries
  no behavior anywhere in the codebase beyond being an enum member and a registry key; nothing reads
  its value to branch logic.
- **`WorkflowRegistry` permits the intended construction**: confirmed by re-reading
  `workflows/registry.py`'s `register()` — it accepts any `WorkflowDefinition` for any
  `WorkflowType` member with no restriction beyond duplicate-name/seal checks, both trivially
  avoidable in a fresh, empty, locally-constructed registry.
- **No collision with an already-registered definition**: confirmed, and further strengthened by a
  fresh finding this pass — `tests/test_workflow_registry.py` already contains
  `test_daily_digest_is_not_registered_in_the_real_registry()` (`"""Phase 5 approval: DAILY_DIGEST
  must never be registered."""`), and `tests/test_workflow_service.py` already contains
  `test_create_task_unknown_workflow_type_raises`, which calls `create_task(..., workflow_type=
  WorkflowType.DAILY_DIGEST)` specifically *because* it is unregistered in the real/default registry,
  using `create_task()`'s own existing `registry: WorkflowRegistry = default_registry` parameter
  exactly as M7's plan proposes to override it. Both existing tests are scoped to *the real, global*
  registry specifically (by name and by docstring); M7's local registry is a structurally separate
  object, so neither existing test is affected, and — more importantly — this confirms `DAILY_DIGEST`
  is *already the established idiom in this exact codebase* for "the `WorkflowType` you reach for when
  you need one that is real but deliberately unregistered," an even stronger precedent than the one
  the revision cited.

**`DAILY_DIGEST` is not awkward; no fallback to `CONTENT_GENERATION` is needed** — though the Plan's
own stated fallback remains valid and available if ever required.

**Verdict: VALID.**

---

## 7. Freshness Boundary Re-Audit

- `reference_now == published_at` (and the `collected_at` fallback variant) now has an explicit test,
  distinct from the existing "future timestamp" test — confirmed, not merely implied by a "recent"
  case.
- Deterministic behavior: confirmed — age is computed as a pure function of the two timestamps;
  zero is a single, unambiguous value, not a range needing special interpretation.
- Correct bucket/threshold interpretation: age exactly zero falls inside the freshest configured tier
  under any reasonable inclusive-lower-bound convention (`0 ≤ age < 2h`, the first window) — the Plan
  correctly asserts this is deterministic per whatever tier convention is chosen, without prematurely
  fixing the tier boundary numbers themselves (still correctly left as product configuration, §5.2).
- No negative-age artifact: confirmed — zero is not negative, so no clamping logic is invoked for
  this case at all; it is a distinct code path from the future-timestamp (negative-age) case, and the
  Plan's own new test is correctly kept separate from that existing test rather than merged into it.
- Consistent with future-timestamp handling: confirmed — both cases resolve to the same "maximally
  fresh" classification (zero age and clamped-to-zero age produce the same tier), and the Plan does
  not introduce any special-casing that could make them diverge.

**Verdict: RESOLVED.**

---

## 8. Sequencing / Rollback Re-Audit

- **M5's test dependency on M4's shared fixture is now explicit**: confirmed in three places,
  cross-checked for consistency — the Dependency Graph's "why this ordering is dependency-correct"
  bullet, M5's own "Rollback safety" section, and the Final Report's ordering summary. All three now
  correctly distinguish "no production-code dependency" from "a real test-level dependency," where the
  original Plan understated this as "no dependency... not by import" without the test-level caveat.
- **Production M5 still does not depend directly on M4's implementation**: confirmed — no import of
  `capabilities/research_capability.py` anywhere in M5's production scope, and this remains correctly
  forbidden by Contract §9.1 regardless of planning choices.
- **Rollback notes accurately identify shared files**: re-verified against every milestone's own
  "Files" section — `services/triage_orchestrator.py` (M2 + M3, both milestones' own rollback notes
  correctly cross-reference this), `capabilities/registry.py` (M6 only, pre-existing history,
  correctly flagged), `tests/fakes/research_output.py` (M4 creates, M5's tests import — both
  milestones' rollback notes now correctly state this). No inaccuracy found.
- **No hidden M3↔M4/M5/M6 dependency**: confirmed by re-checking every file M3 touches
  (`services/triage_orchestrator.py`, `scripts/run_triage.py`) against every file M4-M6 touch
  (`capabilities/research_capability.py`, `capabilities/intelligence_capability.py`,
  `capabilities/registry.py`, two `prompts/` directories, `tests/fakes/research_output.py`) — zero
  overlap, zero cross-import in either direction.
- **M7 as the first Phase 9 boundary integration point — clarified, not contradicted**: M7 is
  correctly the first point both Capabilities are registered together and the Research→Intelligence
  `step_results` handoff is proven for real. It is **not**, and is not claimed to be, a single test
  connecting M3's real orchestrator-created `EditorialTask` all the way through a real
  `WorkflowRunner.run()` reaching Intelligence — and per Contract §13, no such single connected proof
  is possible without either using the real `NEWS_ANALYSIS` definition (which would hit the
  already-disclosed, accepted `FAILED`-at-`engagement_analysis` wall, proving nothing new) or
  inventing an unauthorized workaround. The Plan's actual design — M3 proves the Triage-side
  ownership/task-creation chain in isolation, M7 proves the Capability-side handoff in isolation, per
  Contract §13's own explicit list of allowed proofs — is the *correct*, Contract-consistent shape,
  not a gap.

**Verdict: no remaining finding.**

---

## 9. Scope Consistency

Re-swept the full revised document for every forbidden item this pass, fresh (not reused from the
prior audit's sweep): `EngagementAnalysisCapability`, `scheduler`, `WorkflowRunner` redesign,
`migration`, new `WorkflowType`, `FAILED`/`COMPLETED` lifecycle fix, full `NEWS_ANALYSIS` completion,
final scoring/ranking, `clustering`, `embedding`/`vector DB`, `autonomous`, `distributed lock`,
`two-phase commit`, `checkpoint`(ing). Every match found is inside an "out of scope," "non-goal,"
"MUST NOT," "forbidden," or "deferred" context, or is an unrelated homonym (`"Expected commit
checkpoint"` — the milestone's git-commit-message field; `"cross-cutting checkpoint"` — the M7
regression-suite name). **No implementation scope was added anywhere.**

The two new production surfaces this revision does add — `Field(gt=0)` on one config field, and the
explicit Phase A/Phase B commit/rollback sequencing inside `services/triage_orchestrator.py` — are
both refinements of already-in-scope M2/M3 responsibilities, not new functional scope.

**Confirmed clean.**

---

## 10. Implementation Readiness

Re-checked every named category for remaining ambiguity capable of producing incompatible
implementations (not ordinary implementation freedom):

- **M0 validator scope**: unambiguous — three named files, explicit forbidden-prefix lists, a
  worked justification table.
- **M1 config ownership**: unambiguous — module constants for pure tuning values,
  `core/config.py` `Settings` for the one operationally-relevant value, both with stated reasoning.
- **M2 primitive API boundaries**: unambiguous — three named, typed function signatures, explicit
  return-value semantics (`bool`, rowcount-based), explicit "commit is caller's responsibility."
- **M3 session/commit/rollback ownership**: **now unambiguous** — this was the one real gap the
  original audit found; the Phase A/Phase B model, the binding invariant statement, and the six named
  tests together leave no room for a materially different, still-compliant implementation.
- **M4 Research output shape**: unambiguous — a concrete, named shape, now additionally pinned by a
  shared, importable constant.
- **M5 Intelligence prior-step input shape**: unambiguous — the same shared constant, plus the exact,
  real field path (`context.business.workflow_state.step_results.get("research", {})`), independently
  re-verified against `capabilities/executor.py`'s real construction logic in the original audit and
  unchanged since.
- **M6 registry names**: unambiguous — `"research"`/`"intelligence"`, independently re-verified
  against `workflows/definitions/news_analysis.py`'s real step definitions.
- **M7 synthetic integration strategy**: **now unambiguous** — `WorkflowType.DAILY_DIGEST` named
  explicitly, with a stated fallback, and (per this pass's own additional finding) even more strongly
  precedented than the revision itself knew.

**No remaining ambiguity capable of producing an incompatible implementation was found.**

---

## 11. Remaining Findings

**CRITICAL**: None.

**MAJOR**: None. Both prior MAJOR findings — RESOLVED (§2, §3 above).

**MINOR**: None. All five prior MINOR findings — RESOLVED (§4-§7 above, plus §5's "VALID WITH MINOR
NOTE" fixture typing observation, downgraded to OBSERVATION since it was not itself one of the five
original MINOR findings and does not rise to the same severity).

**OBSERVATION**:
1. `tests/fakes/research_output.py`'s planned `dict[str, object]` annotation is stricter than the
   `Any`-typed convention used elsewhere for `structured_output`; a trivial fix if it causes friction,
   not required to be specified in the Plan itself (§5 above).
2. The transaction discipline's safety depends on `expire_on_commit=False`, which is already true
   repository-wide (`database/session.py`, `tests/conftest.py`) but is never stated explicitly in the
   Plan's own text — worth one citation in a future revision for completeness, not because anything is
   actually at risk (§2 above).

---

## 12. Scores

| Dimension | Score /10 | Basis |
|---|---|---|
| Contract Coverage | 10 | No gap found this pass beyond what was already resolved; every §7.5/§7.6 premise now has an explicit implementation-level guarantee |
| Transaction Safety | 10 | Phase A/Phase B model independently verified against real `services/workflow_service.py`/`services/collector.py` code and against the `expire_on_commit` hazard this pass specifically checked for |
| Concurrency Safety | 10 | M2's primitives unchanged and already verified in the prior full audit; M3's composition of them is now safe by construction |
| Configuration Safety | 10 | Positivity constraint verified against the actual installed Pydantic version and `pydantic-settings` behavior, not merely described |
| Validator Quality | 10 | All three rules re-confirmed necessary and non-redundant; the blanket-prefix simplification re-verified to be strictly safer than the enumeration it replaced |
| Capability Compatibility | 9 | Shared-fixture mechanism verified sound end-to-end; docked one point only for the cosmetic `object`-vs-`Any` typing note |
| Sequencing | 10 | Every dependency, including the newly-explicit test-level M4→M5 link, independently re-derived and confirmed accurate |
| Rollback Safety | 10 | Every multi-milestone file overlap correctly and consistently disclosed across both milestones involved |
| Scope Discipline | 10 | Fresh, independent sweep found zero leakage |
| Implementation Readiness | 10 | Both remaining sources of possible incompatible implementation (transaction timing, `WorkflowType` choice) are now closed |

**Overall (evidence-weighted): 9.9/10.**

---

## 13. Final Verdict

**PHASE 9 IMPLEMENTATION PLAN APPROVED**

Both MAJOR findings and all five MINOR findings from `docs/phase9_implementation_planning_audit.md`
are fully resolved, verified this pass against the actual repository rather than trusted from the
revision's own text — including one additional, independent check (SQLAlchemy's `expire_on_commit`
behavior around the new Phase A/Phase B commit boundary) that the revision did not itself raise, and
one additional piece of corroborating evidence (existing tests already treating `DAILY_DIGEST` as the
established "real but deliberately unregistered" `WorkflowType`) that makes M7's synthetic-workflow
choice stronger than originally argued. No new contradiction, no scope expansion, and no remaining
ambiguity capable of producing an incompatible implementation was found. Two trivial, non-blocking
OBSERVATIONs are recorded for optional future polish. This Plan is ready for implementation beginning
at M0, pending the user's own separate decision on when to proceed.
