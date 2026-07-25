# Phase 9 Implementation Planning — Research / Intelligence MVP

## 1. Planning Status / Authority

**Status: Implementation plan. Not a specification.** This document does not redefine, loosen, or
reinterpret any rule in `docs/phase9_research_intelligence_architecture_contract.md` ("the
Contract"). Where this plan makes a choice the Contract left open (file names, exact test layout,
which config values live in `core/config.py` vs. as module constants), that choice is marked
**IMPLEMENTATION DETAIL** or **PRODUCT CONFIGURATION**, exactly per the Contract's own §22
classification, and is derived from an existing repository pattern, never invented from nothing.

**Source-of-truth order used throughout this plan** (as instructed):
1. Frozen Phase 6/7/8 architecture/contracts.
2. `docs/phase9_research_intelligence_architecture_contract.md` (the approved Contract).
3. `docs/phase9_architecture_contract_audit.md`, `docs/phase9_architecture_contract_reaudit.md`,
   `docs/phase9_recovery_final_reaudit.md` (final audit trail — confirms which findings are
   resolved and which limitations are deliberately preserved, not a source of new rules).
4. `docs/phase9_final_decisions.md`.
5. `docs/phase9_precontract_audit.md`, `docs/phase9_decision_resolution.md`,
   `docs/phase9_research_intelligence_discovery.md` (earlier analysis; superseded wherever they
   conflict with the Contract — used here only for context, e.g. the six-window Freshness-tier
   candidate list already recommended in `phase9_decision_resolution.md` §2).

All eight required documents were read in full before drafting this plan. No conflict was found
between the Contract and any earlier document that the Contract itself hasn't already resolved and
recorded (§26 of the Contract's revision history, `docs/phase9_recovery_final_reaudit.md`'s verdict
"PHASE 9 CONTRACT APPROVED WITH DOCUMENTED LIMITATION"). This plan proceeds on that verdict.

**This document does not modify the Contract, write production code, create a migration, or
implement M0.** It stops after planning, per instruction.

**Revision note**: this Plan was revised once, in response to
`docs/phase9_implementation_planning_audit.md`'s findings (verdict: "PHASE 9 PLAN NOT READY —
CORRECTIONS REQUIRED"). Two MAJOR corrections (M3's transaction/commit/rollback discipline; M2's
staleness-threshold positivity validation) and five MINOR clarifications were applied, all within
M0-M2, M4-M5, and M7's existing text — no milestone was added, removed, or resequenced. See the
"Revision note" at the end of this document (Final Report section) for the itemized list.

---

## 2. Current Repository Baseline

Inspected directly (not assumed from the Contract's own citations) before drafting milestones:

| Area | Finding | Relevance |
|---|---|---|
| `database/models/news_event.py` | `EventStatus` (`NEW/PROCESSING/ANALYZED/REJECTED/ARCHIVED`), `published_at`/`collected_at`/`updated_at` exactly as the Contract cites. Zero writers of any status beyond `NEW` today (`services/collector.py:159`). | Confirms M2/M3's claim/recovery primitives have a clean, currently-unused enum to build on. |
| `database/models/news_source.py` | `reliability_score: float \| None`, no `CHECK` constraint. | Confirms M1's null-handling requirement (§6 rule 4). |
| `database/models/editorial_task.py` | `TaskPriority(str, Enum)` = `S/A/B/C`; `TaskStatus` = `CREATED/RUNNING/WAITING/COMPLETED/FAILED`; `ACTIVE_STATUSES = (CREATED, RUNNING)` lives in `services/workflow_service.py`, not the model. | Confirms M1's ordinal-mapping requirement and M2's active-task precedence logic. |
| `services/workflow_service.py` | `create_task()` — check-then-act, commits internally (line 71); `_find_active_task()` (lines 89-106) — plain `SELECT`, matches `workflow_type` against the JSON `workflow` column in Python. Zero other callers repo-wide (`app/`, `bot/`, `scripts/` all clean). | Confirms M3 calls this **unmodified**; confirms the Contract's §5 "Conclusion A" (Phase 9 orchestrator serializes every call via ownership, even though `create_task()` itself stays globally non-atomic) is still accurate today. |
| `services/collector.py` | The direct precedent for M3's shape: a `CollectionReport` `@dataclass`, a `run_collection_cycle()` async function, one shared session for the whole cycle, per-source try/except isolation with an explicit `await session.rollback()` on failure, module-level tuning constants (`MAX_FETCH_ATTEMPTS`, `RETRY_BACKOFF_SECONDS`) rather than `core/config.py` entries. | M3 mirrors this file's overall shape (report dataclass, one shared session, explicit commit/rollback discipline) but **not** its exact commit *granularity* — collector.py commits once per source (which may hold many items); M3 must commit once per *event* (M3's own atomic unit), per this revision's explicit Phase A/Phase B transaction discipline. Also the precedent used to decide where Freshness/Triage tuning constants live (see §17 below). |
| `scripts/run_collector.py` | ~20 lines: `setup_logging()` + one `services.*` call, `python -m scripts.run_collector`. | M3's script entry point mirrors this exactly. |
| `workflows/runner.py` | Confirmed unchanged since the last audit (`git diff --stat` clean): three commit points only (lines 123, 195, 285); `TaskAlreadyRunningError` on re-run. | Grounds §14.1's crash/restart disclosure — M4-M7 must not claim otherwise. |
| `workflows/registry.py` / `workflows/definitions/news_analysis.py` | `research`/`intelligence`/`engagement_analysis`/`scoring` steps, all `required=True` (schema default, no override). `capability="research"`/`"intelligence"` match the step names exactly. | Confirms M4/M5's capability names need zero change to this file; confirms M7 must not attempt to run the real `NEWS_ANALYSIS` definition to completion. |
| `capabilities/capability_mapping.py` | `"research": AICapability.RESEARCH`, `"intelligence": AICapability.INTELLIGENCE` **already present**. | Zero change needed anywhere in this file for M4-M6. |
| `capabilities/registry.py` | `build_registry(gateway, prompt_repository, budget_guard, tool_registry)` — two-line-per-Capability pattern (`ScoringCapability`, `QualityCapability` already registered this way). `budget_guard`/`tool_registry` accepted, passed to neither. | M6 adds exactly two more `registry.register(...)` lines; no signature change. |
| `capabilities/scoring_capability.py` / `capabilities/quality_capability.py` | The direct implementation precedent for M4/M5: `__init__(gateway, prompt_repository)` only; `call_generate()` for the Gateway call; `PromptRepository.resolve()` for prompt content; `CapabilityDefinition`/`CapabilityConfig` module-level constants. | M4/M5 follow this file's shape line for line. |
| `scripts/validate_architecture.py` | `capability-isolation` rule already covers **any** new file under `capabilities/` (5 named exclusions, neither of which will be `research_capability.py`/`intelligence_capability.py`) — confirmed by reading `_under_excluding()`'s exact exclusion list. No generic rule exists yet for arbitrary `services/*.py` files — only named-file rules (`budget-guard-isolation`, `cost-tracker-isolation`, etc.) exist. | Confirms **zero validator change needed for M4/M5**; confirms M0 must add three new **named-file** rules (`services/freshness.py`, `services/triage.py`, `services/triage_orchestrator.py`), mirroring the existing named-file pattern exactly — not a new generic mechanism. |
| `tests/fakes/` | `fake_gateway.py`, `fake_prompt_repository.py`, `fake_provider_adapter.py`, `fake_capability.py`, `fake_infra.py` — all directly reusable for M4/M5/M7 with zero modification. | No existing fake is modified. M4 adds exactly one small, new, plain-constant file to this directory (`tests/fakes/research_output.py`, §17) — the shared Research→Intelligence shape fixture resolving the cross-milestone shape-consistency gap the planning audit found; this is an addition consistent with the directory's existing purpose, not a new mechanism. |
| `tests/conftest.py` | `db_session` fixture: one connection, `join_transaction_mode="create_savepoint"`, rolled back at teardown — correct for single-session integration tests, but **not** sufficient by itself for true cross-connection concurrency tests (two independent orchestrator instances racing), because it shares one physical connection/transaction. | M2's concurrency tests need two independent `AsyncSession`s against two independent connections from the real test engine (`tests.conftest._test_engine`), each committing for real and cleaning up its own rows explicitly — the exact pattern already used and empirically verified during the Contract's own drafting (`docs/phase9_recovery_final_reaudit.md` §3). This is a **test-only** pattern, not a new fixture the Contract requires; M2 adds a small, local, test-file-scoped helper (or a new fixture in `tests/conftest.py`) for this — implementation detail, decided in M2's own section below, not asked about here. |
| `core/config.py` | `Settings` (`pydantic-settings`, env-var-driven): safety/operational knobs (`redis_unavailable_policy`, `max_daily_ai_cost`) live here; algorithm-tuning constants (e.g. `services/collector.py`'s retry counts) do **not** — they live as module-level constants in the relevant service file. | Grounds the Product Configuration split in §17 below: the stale-recovery threshold (operational/safety-relevant, analogous to `redis_unavailable_policy`) goes in `Settings`; Freshness tier boundaries/weights and the reliability-null default (pure algorithm tuning, analogous to `MAX_FETCH_ATTEMPTS`) stay as module constants. |

No other repository area needed inspection to plan milestones — `schemas/capability.py`,
`schemas/capability_definition.py`, and `integrations/prompts/` were also read; they confirm the
Phase 8 `Capability` shapes M4/M5 must match exactly and are not repeated here since M4/M5's
sections below cite them directly.

---

## 3. Frozen Phase 9 Boundary

Restated from the Contract's §0/§1/§20, for milestone-scoping reference only — this plan does not
redefine it.

**IN**: deterministic Triage; Freshness; `NewsSource.reliability_score` input; explicit
`TaskPriority` ordinal mapping (`S > A > B > C`); atomic `NEW` claim; stale-`PROCESSING` recovery;
atomic recovery CAS/ownership; thin Triage-orchestration service; thin script entry point;
`ResearchCapability`; `IntelligenceCapability`; Research→Intelligence via existing `step_results`;
Contract-required registration/wiring; `Capability`/`CapabilityExecutor`-level integration proof;
tests; architecture-validator extension where the Contract itself flags it as needed (§17).

**OUT** (no milestone below touches any of these): `EngagementAnalysisCapability`; Final Editorial
Ranking; Opportunity Score; clustering; embeddings; vector DB; true novelty detection;
engagement-data collection; source-reputation learning; autonomous/browsing research agents;
Workflow Engine redesign; scheduler redesign; automatic production scheduling (§7.4 stays deferred);
durable per-step `WorkflowRunner` checkpointing (§14.1 stays a disclosed limitation, not a fix
target); any new DB model or migration; any `FAILED`/`COMPLETED` task-lifecycle redesign
(`_find_active_task()`'s `CREATED`/`RUNNING`-only definition is reused exactly as-is, not touched).

---

## 4. Known Limitations / Deferred Follow-Ups (preserved, not "fixed")

Carried forward verbatim in spirit from `docs/phase9_recovery_final_reaudit.md` — every milestone
below is checked against this list; none is permitted to close these gaps as a side effect.

**A. Staleness-threshold operational constraint (Contract §7.6).** A healthy worker whose own
claim-to-`create_task()` latency exceeds the configured `stale_processing_threshold_seconds` can be
raced by a stale-recovery attempt. No milestone introduces a heartbeat, lease, Redis lock,
distributed lock, or new column to close this. M2/M3 keep the claim-to-`create_task()` path minimal
(claim → load one `NewsSource` row → call pure Triage → `create_task()`, no unrelated work
in between) specifically to keep this window small relative to the configured threshold, and M3's
Definition of Done requires measuring this window's real duration as runtime evidence, precisely so
the chosen default threshold (§17 below) can be sanity-checked against real behavior before this
phase closes — not to eliminate the constraint, which is architectural and permanent.

**B. `FAILED`/`COMPLETED` task lifecycle observation (`docs/phase9_recovery_final_reaudit.md` §5).**
`_find_active_task()`'s `CREATED`/`RUNNING`-only definition of "active" means a `NewsEvent` whose
task ever reaches a terminal status becomes recovery-eligible again once stale, risking a duplicate
task. **Confirmed still unreachable in this repository**: a fresh `grep -rn "WorkflowRunner("` and
`grep -rn "\.run(session"` across `scripts/`, `services/`, `app/`, `bot/` (re-run during this
planning pass) again returns **zero** production call sites — nothing drives any `EditorialTask` to
a terminal status outside tests, today. No milestone below adds one. **This is recorded here,
explicitly, as deferred technical debt and a prerequisite for a future scheduling phase** — before
any future phase wires `WorkflowRunner.run()` into automatic production scheduling, that phase's own
planning MUST revisit `_find_active_task()`'s active-task definition (or the recovery-eligibility
query) before relying on it. Phase 9 does not change `_find_active_task()` and does not need to.

**C. Research→Intelligence crash/restart scope (Contract §14.1).** The `step_results` handoff is
valid only within one uninterrupted `WorkflowRunner.run()` call. M7's integration proof exercises
exactly this uninterrupted case and explicitly does not, and must not, claim more.

**D. Real `NEWS_ANALYSIS` never reaches `COMPLETED` in this phase (Contract §13).** `research` and
`intelligence` become independently executable after M6, but `engagement_analysis` remains
unregistered — `WorkflowRunner.run()` against the real `WorkflowType.NEWS_ANALYSIS` still ends
`FAILED`, now at the third step instead of the first. No milestone uses the real definition as its
completion proof (M7 uses a synthetic definition, per Contract §13's explicit list of allowed
proofs).

**Recorded audit observations (non-blocking — noted, not acted on)**, per
`docs/phase9_implementation_planning_audit.md` §19's two OBSERVATION-level items: (1) Contract
P12/§19's future-extension-compatibility promise (a later phase adding `EngagementAnalysisCapability`/
Final Scoring without breaking Triage's, Research's, or Intelligence's contracts) has no dedicated
verification milestone or test — this Plan's existing boundary tests plus M0's architecture rules are
judged sufficient; no milestone is added or expanded to independently prove a forward-compatibility
promise that is, by its nature, only checkable once that future phase actually exists. (2) Contract
§6 rules 2-3 (no dynamic/historical authority score, no engagement/clustering-derived authority) have
no dedicated negative test — this is structural (Triage's function signature has no DB access and no
`**kwargs` escape hatch to compute or accept one) rather than merely asserted, and this Plan does not
add an artificial test whose only purpose would be proving a structural impossibility. Both items are
recorded here as review notes; neither adds a milestone, a test, or any new implementation scope.

---

## 5. Dependency Graph

```
M0  Architecture Validator Extension
      |
      +--------------------+
      |                    |
      v                    v
M1  Triage Policy      M2  Claim/Recovery Primitives
 (Freshness + Triage,   (atomic NEW claim, staleness
  pure, no DB)           eligibility, CAS ownership)
      |                    |
      +---------+----------+
                v
      M3  Triage Orchestration Service + Script Entry Point
                                                              M4  ResearchCapability
                                                                    |
                                                              M5  IntelligenceCapability
                                                                    |
                                                              M6  Registration / Boot Wiring
                                                                    |
      +---------------------------------------------------- M7  Integration Proof +
      |                                                          Cross-Cutting Regression
      v                                                           ^
(M3's own tests already prove the Triage-Orchestrator             |
 side in isolation; M7 does not re-test it, only confirms  -------+
 no regression was introduced by M4-M6's registration)
```

**Why this ordering is dependency-correct**:
- M0 must precede M1-M3 in delivery order because it is cheap, has zero functional dependency on
  files that don't exist yet (the AST scanner is a no-op against a path with no file), and — per
  the explicit planning instruction — mechanical enforcement should exist *before* the components it
  protects, exactly mirroring Phase 8's own M0 precedent.
- M1 and M2 are mutually independent (Triage is pure and DB-free; the claim/recovery primitives need
  only the existing `NewsEvent`/`EditorialTask` models and `_find_active_task()`, not Triage). They
  are sequenced M1-then-M2 rather than run "in parallel" only because milestones are implemented one
  at a time; either order is architecturally valid. M1 first because it is smaller and has zero
  concurrency-testing complexity, giving an easy, low-risk first real milestone after M0.
- M3 depends on **both** M1 (calls Triage) and M2 (calls the claim/recovery primitives) — it is the
  first point they are composed, exactly matching Contract §7.2's three-step sequence.
- M4 (`ResearchCapability`) has no functional dependency on M1-M3 at all — it is an ordinary Phase 8
  `Capability`, wired into an entirely different subsystem (`capabilities/`, not `services/`). It is
  sequenced after M3 to mirror the Contract's own §0 pipeline order and to keep the
  highest-scrutiny, most concurrency-sensitive work (M1-M3) built and proven first, but this is a
  scheduling choice, not a hard blocker — M4 could be built before M1 without breaking anything.
- M5 (`IntelligenceCapability`) has no *production-code* dependency on M4 (no import of
  `capabilities/research_capability.py` — forbidden by §9.1 anyway); its **tests** do import M4's
  shared `tests/fakes/research_output.py` fixture (§17 below), which is exactly why it is sequenced
  after M4 rather than merely "by convention" — M7's step-chaining proof also needs both built, and
  Phase 8's own precedent builds one Capability fully (incl. tests) before starting the next.
- M6 depends on M4 + M5 (`build_registry()` needs both `CapabilityDefinition`s to exist).
- M7 depends on M6 (both Capabilities must be registered before a synthetic-workflow proof can
  resolve either capability name via the real `CapabilityRegistry`) and, transitively, on M0-M3
  remaining regression-free (M7's cross-cutting checkpoint re-runs the full suite, not just Phase
  9's own tests).

---

## 6. Milestone Overview Table

| # | Title | Depends on | Primary files | Contract sections |
|---|---|---|---|---|
| M0 | Architecture Validator Extension | — | `scripts/validate_architecture.py` | §17, §2.5 |
| M1 | Deterministic Triage Policy (Freshness + Triage) | M0 | `services/freshness.py`, `services/triage.py` | §2.1, §2.2, §3, §4, §5, §6, §21 rules 1-5,13 |
| M2 | Atomic Claim + Stale-Recovery Primitives | M0 | `services/triage_orchestrator.py` (primitives only) | §7.2 step 1, §7.5, §7.6, §18 (claim/recovery rows), §21 rules 12,15 |
| M3 | Triage Orchestration Service + Script Entry Point | M1, M2 | `services/triage_orchestrator.py` (full cycle), `scripts/run_triage.py` | §2.3, §7 (all), §15 (first two bullets), §16 (Orchestrator section), §18 (full table) |
| M4 | `ResearchCapability` | — (sequenced after M3) | `capabilities/research_capability.py`, `prompts/research/v1.yaml` | §8, §11, §16 (`ResearchCapability`/`IntelligenceCapability` section) |
| M5 | `IntelligenceCapability` | M4 (sequencing only) | `capabilities/intelligence_capability.py`, `prompts/intelligence/v1.yaml` | §9, §9.1, §10, §11, §16 |
| M6 | Registration / Boot Wiring | M4, M5 | `capabilities/registry.py` | §12, §17 (Capability rows, already-enforced) |
| M7 | Integration Proof + Cross-Cutting Regression | M6 | `tests/test_phase9_*` (new), full-suite re-run | §9.1, §13, §14.1, §15, §16 (Integration section), §21 rule 14, §23 |

8 milestones total.

---

## 7. Detailed Milestones

### M0 — Architecture Validator Extension

**1. Goal**: mechanically enforce, before any Phase 9 production file exists, the dependency
boundaries Contract §2.5/§17 assign to Freshness, Triage, and the Triage Orchestrator — the one
place the Contract itself states enforcement does not yet exist ("to be mechanically encoded... by
a future implementation milestone", §17's own header).

**2. Contract coverage**: §17's Freshness/Triage/Orchestrator rows; §2.5's "Must NOT depend on"
columns for the same three components. (§17's `ResearchCapability`/`IntelligenceCapability` rows are
explicitly **not** in scope here — already mechanically enforced by the existing `capability-isolation`
rule, confirmed in §2 above; adding a redundant rule for them would violate the "if existing Phase 8
rules already enforce everything needed, do not invent redundant rules" instruction.)

**3. Files**:
- Production: `scripts/validate_architecture.py` (add three `Rule` entries to the existing `RULES`
  tuple; zero change to any existing rule).
- Tests: `tests/test_validate_architecture.py` (add one "flagged" test and confirm-clean coverage
  per new rule, mirroring `test_workflow_importing_capabilities_is_flagged`'s exact shape).
- Docs/config: none.

**4. Implementation scope**:

**Validator-rule necessity review (resolves `docs/phase9_implementation_planning_audit.md` MINOR
finding 4)**: checked each of the three proposed rules against the full, existing `RULES` tuple in
`scripts/validate_architecture.py` before retaining it. All three remain necessary — none is
redundant with any existing Phase 6/7/8 rule — because no existing rule targets an arbitrary
`services/*.py` file by name (only `budget-guard-isolation`, `cost-tracker-isolation`,
`cost-estimator-isolation`, `pricing-catalog-isolation` do, each scoped to its own single, different
file). `capability-isolation` only applies under `capabilities/`, not `services/`. This review also
simplifies one rule's forbidden-prefix list, per the audit's specific finding, without adding or
removing a rule:

| Rule | Exact forbidden edge (Contract citation) | Target | Why no existing rule covers it |
|---|---|---|---|
| `freshness-purity` | No DB, no `services/`, no `LLMGateway` (§2.5's Freshness row) | `services/freshness.py` | No existing rule scopes to this file; the closest, `capability-isolation`, only applies under `capabilities/` |
| `triage-purity` | No DB, no `LLMGateway`, no `CapabilityRegistry`/`CapabilityExecutor`, no `workflows` (§2.5's Triage row) | `services/triage.py` | Same — no existing rule scopes to `services/triage.py` |
| `triage-orchestrator-isolation` | No `LLMGateway`, no Capability layer of any kind, no provider SDK (§2.5's Orchestrator row: "`LLMGateway`, provider SDKs, `CapabilityExecutor`, `CapabilityRegistry`, ... `ResearchCapability`/`IntelligenceCapability` directly") | `services/triage_orchestrator.py` | Same — no existing rule scopes to this file; `provider-sdk-confinement` already covers the provider-SDK half repo-wide, kept here too only for single-message error locality (a disclosed, deliberate, minor overlap, not a redundant rule in the sense the audit asks to eliminate) |

- `freshness-purity` rule: `applies_to=_under("services/freshness.py")`, forbidden prefixes =
  `database.session`, `sqlalchemy`, `integrations.llm_gateway`, `services.` (everything under
  `services/` except itself — Freshness must not depend on any other `services/` module, §2.5).
  Note: since the rule's `applies_to` predicate already scopes matching to this one file, forbidding
  the `services.` prefix here does not (and must not) block the file's own module path; the AST
  scanner only flags *imports*, never the file's own identity, so this is safe exactly as written.
- `triage-purity` rule: `applies_to=_under("services/triage.py")`, forbidden prefixes =
  `database.session`, `sqlalchemy`, `integrations.llm_gateway`, `capabilities.registry`,
  `capabilities.executor`, `workflows` (Triage may import `services.freshness` and
  `database.models.editorial_task` for the `TaskPriority` enum only — a plain enum reference, not a
  session, exactly the same exception `capability_mapping.py`'s own comment already establishes for
  Capability-isolation; no special-casing needed since `database.models` is never in this rule's
  forbidden-prefix list).
- `triage-orchestrator-isolation` rule: `applies_to=_under("services/triage_orchestrator.py")`,
  forbidden prefixes = `integrations.llm_gateway`, **`capabilities.`** (a single blanket prefix,
  simplified from four individually-enumerated sub-modules per the audit's finding — the
  Orchestrator has no legitimate need for *any* `capabilities/` import, not merely the four named
  ones, so a blanket prefix is both simpler and automatically covers a future capability file this
  enumeration would otherwise need hand-updating for), plus *provider SDK prefixes* (already covered
  repo-wide by `provider-sdk-confinement`, listed here too only for single-message error locality,
  matching `budget-guard-isolation`'s own style). **Not** forbidden: `workflows.registry`/
  `schemas.workflow` (`WorkflowType` lives in `schemas/`, not `workflows/`, so no rule needs to
  special-case it) and `services.workflow_service` (Contract §7.2 step 3 explicitly requires this
  import) — confirmed by re-reading §17's Orchestrator row, which forbids `WorkflowRunner internals`,
  not `workflow_service` or `WorkflowType`.

**Only these three rules are added. No fourth rule is introduced for `capabilities/research_capability.py`/
`capabilities/intelligence_capability.py` — the existing `capability-isolation` rule already covers
any new file under `capabilities/` with zero change, confirmed in §2 of this Plan's Repository
Baseline and re-confirmed by this review; adding one would be exactly the kind of redundant-for-
symmetry rule the audit instructs against.**

**5. Explicitly out of scope**: any change to `capability-isolation`, `workflow-isolation`, or any
other existing rule; any generic (non-named-file) `services/*` rule; anything touching
`capabilities/research_capability.py`/`capabilities/intelligence_capability.py` (M6 confirms, does
not re-litigate, that these need no new rule).

**6. Tests required**:
- Positive: a clean synthetic `services/freshness.py`/`services/triage.py`/
  `services/triage_orchestrator.py` under `tmp_path` (correct imports only) produces zero violations.
- Negative: one synthetic bad-import file per new rule (e.g. `services/freshness.py` importing
  `sqlalchemy` → flagged `freshness-purity`; `services/triage.py` importing
  `integrations.llm_gateway.gateway` → flagged `triage-purity`; `services/triage_orchestrator.py`
  importing `capabilities.registry` → flagged `triage-orchestrator-isolation`).
- Edge case: confirm `services/triage_orchestrator.py` importing `services.workflow_service` and
  `schemas.workflow` produces **zero** violations (proves the rule doesn't over-block the Contract's
  own required imports — this is the one case most likely to be gotten wrong by copy-pasting
  `budget-guard-isolation` too literally).
- Concurrency: not applicable to this milestone.

**7. Definition of Done**: `python -m scripts.validate_architecture` exits 0 against the current
repository (no existing file trips a new rule); all new and pre-existing tests in
`tests/test_validate_architecture.py` pass; the three new rules are present in `RULES` with
docstring-cited Contract sections, mirroring every existing `Rule.description`'s citation style.

**8. Verification commands**:
```
pytest tests/test_validate_architecture.py -v
python -m scripts.validate_architecture
ruff check scripts/validate_architecture.py tests/test_validate_architecture.py
mypy scripts/validate_architecture.py
```

**9. Runtime evidence**: actual terminal output of `python -m scripts.validate_architecture`
showing `"validate_architecture: clean - 0 forbidden-dependency violations..."`; actual `pytest -v`
output showing every new test name and `PASSED`.

**10. Rollback safety**: fully independent — a pure validator/test change with no functional
dependency from any other milestone's *passing tests* (M1-M3's own unit/integration tests do not
import or invoke the validator). Reverting M0 in isolation would only remove mechanical enforcement,
never break M1+ functionality. Safe to revert at any point.

**11. Expected commit checkpoint**: "Phase 9 M0: extend architecture validator for Freshness/Triage/
Orchestrator isolation."

**12. Human review gate**: **STOP** after implementation and verification. Do not commit or begin M1
until explicitly approved, unless a later autonomous-mode instruction overrides this gate.

---

### M1 — Deterministic Triage Policy (Freshness + Triage)

**1. Goal**: deliver the two pure-function components (§2.1, §2.2) that decide a `TaskPriority` for
one `NewsEvent`, with zero DB access, zero LLM/provider access, and a `TaskPriority`-ordering
implementation that is empirically proven immune to the native-comparison hazard Contract §3
identifies.

**2. Contract coverage**: §2.1 (Freshness table), §2.2 (Triage table), §3 (Deterministic Triage
Contract, including the ordinal-mapping requirement), §4 (No-Hard-Drop Invariant), §5 (Freshness
Contract, all 7 architectural invariants), §6 (Source Reliability), §16 (Triage/Freshness testing
section), §21 rules 1-5 and 13.

**3. Files**:
- Production: `services/freshness.py` (new), `services/triage.py` (new).
- Tests: `tests/test_freshness.py` (new), `tests/test_triage.py` (new).
- Docs/config: none — Freshness tier boundaries/weights, the priority-mapping thresholds, and the
  reliability-null default are module-level constants inside these two files (§17 below explains
  why, citing `services/collector.py`'s `MAX_FETCH_ATTEMPTS` precedent).

**4. Implementation scope**:
- `services/freshness.py`: `FreshnessResult` (`@dataclass(frozen=True)`, mirroring
  `CollectionReport`'s pattern — JSON-serializable fields only: age-derived tier, whether the
  `collected_at` fallback was used, the raw age in seconds). `compute_freshness(published_at:
  datetime | None, collected_at: datetime, reference_now: datetime) -> FreshnessResult` — pure,
  takes plain scalar `datetime` values (never an ORM object), per §5.1 rules 1-7 exactly: no
  internal clock read; `published_at` anchor when present; `collected_at` fallback with a flagged
  result when not; negative age clamped to zero, never raised; timezone-aware comparison enforced
  (raises a plain `ValueError` — not a `CapabilityError`, since Freshness is not a Capability — if
  either input is naive, since accepting a silently-wrong comparison would violate rule 6 more than
  failing loud does); tier boundaries as module constants (the six windows already recommended in
  `docs/phase9_decision_resolution.md` §2: 0–2h/2–6h/6–12h/12–24h/24–48h/48h+), each with a
  monotonically-decreasing placeholder weight.
- `services/triage.py`: `TriageResult` (`@dataclass(frozen=True)`: `priority: TaskPriority`,
  `explanation: dict[str, Any]` — JSON-serializable, §3's "Output shape" requirement).
  `TASK_PRIORITY_ORDINAL: dict[TaskPriority, int]` — the explicit ordinal mapping Contract §3/§21
  rule 13 requires (`{TaskPriority.C: 0, TaskPriority.B: 1, TaskPriority.A: 2, TaskPriority.S: 3}`),
  the single place any priority comparison in this phase is permitted to happen.
  `decide_triage(published_at, collected_at, reliability_score: float | None, reference_now:
  datetime) -> TriageResult` — pure; calls `compute_freshness()`; applies the null-`reliability_score`
  default (module constant, midpoint 0.5, §6 rule 4); combines Freshness tier weight + reliability
  into a single deterministic score via an explicit, documented formula; maps the combined score to
  a `TaskPriority` via **explicit threshold constants compared against the combined score**, then
  looks up `TASK_PRIORITY_ORDINAL` only for the resulting enum's rank when logging/explaining — never
  for the decision itself. **Never** imports `TaskPriority.__lt__`/`sorted()`/`min()`/`max()`
  anywhere on `TaskPriority` values.

**5. Explicitly out of scope**: any DB access; any read of `NewsEvent`/`NewsSource` ORM rows
(callers pass plain scalars); persistence of `TriageResult` (§14 — logging only, wired in M3);
Freshness/Triage tier-weight *tuning* (values are provisional, product-configurable, §17 below);
title/content/category signals (§3's closed list forbids them).

**6. Tests required**:
- Positive: `published_at` present → correct tier; `reliability_score` present → correctly
  weighted into the combined score.
- Negative/edge: `published_at` None → `collected_at` fallback used, flagged in `FreshnessResult`;
  future `published_at` (negative age) → clamped to zero, no raise; naive `datetime` input → raises
  `ValueError`, never silently wrong; `reliability_score` None → default applied, event still gets a
  priority (never skipped); `reliability_score` at each boundary of `[0.0, 1.0]`.
- **Zero-age boundary (this revision's required addition, resolving audit MINOR finding 5)**: an
  explicit test where `reference_now == published_at` exactly (and a second variant where
  `reference_now == collected_at` exactly, for the fallback path) — age is exactly zero, not merely
  "small" or "approximately fresh." Asserts the deterministic, freshest-tier outcome the configured
  tier boundaries imply, exactly like every other explicit boundary this Plan tests (M2's exact
  staleness-threshold test is the direct precedent) — not left implicit or only incidentally covered
  by a "recent `published_at`" test that never pins the age to precisely zero.
- No-hard-drop: a test parametrized across every reachable input combination asserts
  `decide_triage()` always returns a `TriageResult` with a valid `TaskPriority` — never `None`,
  never an exception for well-typed input (§4, §16 explicit requirement).
- Ordinal-mapping proof (§16's explicit requirement): a dedicated test asserts
  `TASK_PRIORITY_ORDINAL[TaskPriority.S] > TASK_PRIORITY_ORDINAL[TaskPriority.A] >
  TASK_PRIORITY_ORDINAL[TaskPriority.B] > TASK_PRIORITY_ORDINAL[TaskPriority.C]` **using the dict
  directly** — and a second, explicit **negative** test asserting `TaskPriority.S < TaskPriority.A`
  is `False` (documenting the hazard the Contract found, not merely avoiding it) — matching §16's
  instruction to prove the business order "never by asserting on `sorted()`/`<`/`>`."
- Determinism: same inputs + same `reference_now` → byte-identical `FreshnessResult`/`TriageResult`
  across repeated calls.
- Concurrency: not applicable — these are pure functions with no shared state.

**7. Definition of Done**: both modules import cleanly with zero dependency beyond the stdlib
(`services/freshness.py`) and `services.freshness` + `database.models.editorial_task.TaskPriority`
(`services/triage.py`); `python -m scripts.validate_architecture` still exits 0 (M0's new rules
pass against these real files); every test in bullet 6 passes; no test touches a DB session or the
network.

**8. Verification commands**:
```
pytest tests/test_freshness.py tests/test_triage.py -v
pytest --tb=short -q            # full suite, zero-regression check
ruff check services/freshness.py services/triage.py tests/test_freshness.py tests/test_triage.py
mypy services/freshness.py services/triage.py
python -m scripts.validate_architecture
```

**9. Runtime evidence**: `pytest -v` output for the two new test files, including the explicit
ordinal-mapping proof and its companion negative test printed as `PASSED`; a short interactive
demonstration (e.g. a one-off REPL/script snippet run and its output pasted into the milestone
report, not committed) showing `decide_triage()` called with a representative event and its
`TriageResult` printed, to show the JSON-serializable shape concretely, not just asserted by a test.

**10. Rollback safety**: fully independent — no other milestone's code exists yet that imports these
modules except M3 (not yet built). Revertible in isolation with zero impact on M0.

**11. Expected commit checkpoint**: "Phase 9 M1: deterministic Triage policy (Freshness + Triage)."

**12. Human review gate**: **STOP** after implementation and verification. Do not commit or begin M2
until explicitly approved, unless a later autonomous-mode instruction overrides this gate.

---

### M2 — Atomic Claim + Stale-Recovery Primitives

**1. Goal**: deliver, and prove under real concurrent execution, the two atomic DB primitives
Contract §7.2/§7.5/§7.6 require — the `NEW`→`PROCESSING` claim and the stale-`PROCESSING`
recovery-ownership acquisition — **without** yet wiring them into a full "find work, call Triage,
create task" cycle (that composition is M3). This is the highest-scrutiny part of the whole phase
(three audit rounds were spent on exactly this mechanism); it gets its own milestone specifically so
its concurrency proof is not diluted by unrelated orchestration-loop code in the same review.

**2. Contract coverage**: §7.2 step 1 (atomic claim), §7.5 (concurrency guarantee, ordering),
§7.6 (stale-claim recovery — eligibility invariant, time semantics, atomic ownership acquisition,
at-most-one-winner guarantee), §18 (claim-failure and recovery-ownership-failure rows), §21 rules
12 and 15.

**3. Files**:
- Production: `services/triage_orchestrator.py` (new — this milestone adds only the primitive
  functions below; M3 completes the file).
- Tests: `tests/test_triage_orchestrator_claims.py` (new — concurrency-focused; kept as a separate
  test file from M3's higher-level cycle tests, mirroring how Phase 8 separated
  `test_scoring_capability.py` from `test_scoring_capability_retry.py` by concern, not by file).
- Docs/config: `core/config.py` gains
  `stale_processing_threshold_seconds: int = Field(default=900, gt=0)` (see §17 below for the
  15-minute default's justification; **the `gt=0` constraint resolves
  `docs/phase9_implementation_planning_audit.md` MAJOR finding 2** — see below); `.env.example`
  gains the matching commented entry, mirroring how every other `Settings` field is documented
  there.

**Positive-staleness-threshold validation — binding, explicit** (resolves audit MAJOR finding 2).
Contract §7.6 rule 5 and §22 both freeze "a staleness guard MUST exist... its existence and
positivity are not [configuration]" as architecture, not product tuning — only the *duration* is
configurable. `stale_processing_threshold_seconds` MUST therefore be declared with an explicit
lower-bound constraint (`Field(gt=0)`, Pydantic's own idiom, already used elsewhere in this
repository for range-constrained values, e.g. `schemas/source_definition.py`'s
`Field(ge=0.0, le=1.0)`), not a bare `int`. Because `core/config.py`'s `Settings` is constructed
eagerly at module import time (`settings = get_settings()`), a configured value of `0` or a negative
integer causes `pydantic`'s `ValidationError` to raise **at process startup**, before any code that
depends on this value ever runs — a loud, immediate failure, not a silent clamp, not a silent
fallback to the default, and not a disabled guard. This is the only behavior consistent with the
Contract's own "positivity is not configuration" framing: an invalid value is a configuration error
to reject, never a value to auto-correct.

**4. Implementation scope**:
- `_claim_new_event(session, event_id, *, now) -> bool`: a single Core-level
  `sqlalchemy.update(NewsEvent).where(NewsEvent.id == event_id, NewsEvent.status ==
  EventStatus.NEW).values(status=EventStatus.PROCESSING)`, `await session.execute(...)`, returns
  `result.rowcount == 1`. **Never** a `SELECT` followed by a separate `UPDATE` (§7.2's explicit
  prohibition). Commits are the caller's responsibility (M3), matching the existing codebase's own
  session-lifecycle convention (compare `_find_active_task()`, which also does not commit).
- `_select_recovery_candidates(session, *, now, staleness_threshold_seconds) ->
  list[NewsEvent]`: `SELECT` for `status == PROCESSING`, filtered in Python (or SQL, whichever
  reads more clearly — implementation detail) by `now - updated_at > timedelta(seconds=...)`
  (§7.6 rule 3's strict inequality, frozen), then filtered further by
  `_find_active_task(session, event.id, WorkflowType.NEWS_ANALYSIS) is None` — reusing
  `services.workflow_service._find_active_task` **unmodified**, exactly as the Contract requires
  (never reimplementing "is there an active task" independently).
- `_acquire_recovery_ownership(session, event_id, observed_updated_at, *, now) -> bool`: a single
  Core-level conditional `UPDATE ... WHERE id = event_id AND status = 'PROCESSING' AND updated_at =
  observed_updated_at`, setting a value that advances `updated_at` (relying on the existing
  `onupdate=func.now()` behavior — empirically confirmed in the Contract's own drafting record to
  fire for exactly this construct — or an explicit `.values(updated_at=now)`; pick whichever
  reads more clearly, both are Contract-compliant). Returns `result.rowcount == 1`.
- All three functions are private (leading underscore) — M3's `run_triage_cycle()` is the only
  intended public caller within Phase 9's own component model (§2.3's Triage Orchestrator owns
  this), consistent with `_find_active_task()`'s own privacy convention in
  `services/workflow_service.py`.

**5. Explicitly out of scope**: calling Triage; calling `create_task()`; the `scripts/` entry point;
any change to `services/workflow_service.py` (Contract forbids modifying `create_task()`/
`_find_active_task()` — this milestone imports and reuses them, never edits them); any lease/
heartbeat/lock mechanism (§20 item 19 — explicitly forbidden).

**6. Tests required** (integration-tier, real Postgres, per §16's explicit instruction that this is
integration- not unit-tier):
- Positive: a `NEW` event is claimed successfully; `_claim_new_event()` returns `True`, row's
  `status` is `PROCESSING` after commit.
- Negative: a `PROCESSING` (or any non-`NEW`) event's claim attempt returns `False`, row unchanged.
- **Two normal claimers** (concurrency): two independent `AsyncSession`s (own connections, from the
  real test engine — `db_session`'s single-connection fixture is not sufficient here, per §2's
  baseline finding above) both attempt `_claim_new_event()` against the same row concurrently;
  exactly one returns `True`, the other `False`; **no assumption about which one wins** is asserted,
  only that exactly one does.
- Fresh `PROCESSING` not recoverable: a just-claimed event (age ≈ 0) does not appear in
  `_select_recovery_candidates()`'s result with a small `staleness_threshold_seconds`.
- Exact-threshold-not-stale: an event whose `now - updated_at` is exactly equal to the threshold
  (constructed precisely, not approximately, using a frozen `now` and a manually-set `updated_at`)
  is excluded — proves §7.6 rule 3's strict-inequality boundary choice, not an off-by-one guess.
- Future `updated_at` not stale: an event with `updated_at` set in the future relative to `now`
  (simulating clock skew) is excluded from recovery candidates, with no exception raised.
- Active task blocks recovery regardless of age: a `PROCESSING` event with a `CREATED` task, aged
  far beyond the threshold, is still excluded — proves §7.6's active-task-takes-precedence rule.
- **Two recovery claimers** (concurrency): two independent sessions both attempt
  `_acquire_recovery_ownership()` against the same stale candidate, using the same
  `observed_updated_at`; exactly one returns `True`.
- Loser never proceeds: for both the `NEW` and stale-recovery races above, assert the losing
  session's own view of the row (re-read after its own failed attempt) shows no unexpected mutation
  it did not itself cause.
- State re-check / TOCTOU safety: after a successful `_acquire_recovery_ownership()`, a second
  attempt using the **same, now-superseded** `observed_updated_at` value returns `False` (the
  structural re-check §7.6 describes, proven directly, not just asserted from the Contract's prose).
- Partial task-creation failure / rerun safety: **not fully testable in isolation from M3**
  (requires calling `create_task()`, which is M3's job) — this milestone tests only that a claimed-
  but-never-progressed event (simulated by claiming and doing nothing further) correctly becomes a
  recovery candidate once its `updated_at` is aged past the threshold in the test's own setup; the
  full success/`DuplicateActiveTaskError`/other-exception three-way handling is M3's test
  responsibility (§7.5), not duplicated here.
- **Staleness-threshold configuration validation (this revision's required addition, resolving audit
  MAJOR finding 2)**:
  1. A positive `stale_processing_threshold_seconds` value (the default, `900`, and at least one
     other positive override) constructs `Settings` successfully.
  2. `stale_processing_threshold_seconds=0` raises `pydantic.ValidationError` at `Settings`
     construction — never silently accepted, never silently clamped to the default.
  3. A negative `stale_processing_threshold_seconds` (e.g. `-1`) raises the same `ValidationError`.
  4. The configured value deterministically affects staleness eligibility: constructing
     `_select_recovery_candidates()`'s query with two different (both valid, positive) threshold
     values against the same fixed candidate event and `reference_now` produces two different
     eligibility outcomes where the candidate's age falls between them — a direct, executable proof
     that the threshold is actually load-bearing, not merely present.

**7. Definition of Done**: every test in bullet 6 passes against the real dev Postgres database
(via `db_session`/a dedicated two-connection helper, defined locally in this milestone's own test
file per §17's test-helper-location rule); `_claim_new_event`/`_acquire_recovery_ownership` never
perform a `SELECT` immediately followed by a separate `UPDATE` (confirmed by code review against
§7.2's explicit prohibition, not just by tests passing); `stale_processing_threshold_seconds` rejects
`0` and negative values at `Settings` construction (confirmed by the four validation tests above,
not just by the field declaration existing); no migration file is created (this repository's real
migration tool, confirmed this pass to be Alembic — `alembic.ini` + `database/migrations/` both
exist — history is unchanged, confirmed via `git status` showing no new file under
`database/migrations/`).

**8. Verification commands**:
```
pytest tests/test_triage_orchestrator_claims.py -v
pytest --tb=short -q
ruff check services/triage_orchestrator.py tests/test_triage_orchestrator_claims.py core/config.py
mypy services/triage_orchestrator.py
python -m scripts.validate_architecture
git status   # confirm no new migration file
```

**9. Runtime evidence**: `pytest -v` output for every concurrency test, run at least twice in a row
(concurrency tests are exactly the class of test most prone to flaking if the atomicity claim is
subtly wrong — running twice is a cheap, meaningful extra signal, not a formal proof); the actual
observed `rowcount` values for a winning vs. losing concurrent attempt, printed/logged during a
manual verification run (not just asserted in a test) to show the real database's behavior
concretely, mirroring how the Contract's own drafting empirically verified this exact mechanism.

**10. Rollback safety**: fully independent of M0/M1 (no import of either). M3 will depend on this
milestone's functions; reverting M2 after M3 exists would break M3 — safe to revert only before M3
is built, or together with M3 in the same revert.

**11. Expected commit checkpoint**: "Phase 9 M2: atomic NewsEvent claim and stale-recovery
ownership primitives."

**12. Human review gate**: **STOP** after implementation and verification. Do not commit or begin M3
until explicitly approved, unless a later autonomous-mode instruction overrides this gate.

---

### M3 — Triage Orchestration Service + Script Entry Point

**1. Goal**: compose M1's pure Triage with M2's atomic primitives into the full
`services/triage_orchestrator.py` responsibility Contract §2.3/§7 defines — find eligible events,
acquire ownership (claim or recovery), call Triage, call `create_task()`, handle every outcome — plus
the thin `scripts/run_triage.py` entry point, mirroring `scripts/run_collector.py` exactly.

**2. Contract coverage**: §2.3 (Triage Orchestrator table), §7.1 (precedent), §7.2 (full
responsibilities, both claim branches), §7.3 (precise responsibility answers), §7.4 (production
scheduling stays deferred), §7.5 (`create_task()` outcome handling, all three cases, **and the
"claim already committed in step 1" premise** — this revision makes the transaction discipline that
premise depends on explicit, per `docs/phase9_implementation_planning_audit.md` MAJOR finding 1),
§7.6 (residual-state/recovery interplay with the transaction model below), §15 (Triage explanation
logging, recovery-acquisition logging), §16 (Triage Orchestrator testing section, all 8
stale-claim-recovery test requirements, plus the six transaction-discipline tests below), §18 (full
failure-semantics table).

**3. Files**:
- Production: `services/triage_orchestrator.py` (completes the file M2 started), `scripts/
  run_triage.py` (new).
- Tests: `tests/test_triage_orchestrator_cycle.py` (new — the full-cycle/outcome-handling tests,
  separate from M2's claim-focused file per the same by-concern split Phase 8 used).
- Docs/config: none beyond M2's already-added `stale_processing_threshold_seconds`.

**4. Implementation scope**:

**Transaction discipline — binding, explicit, the one thing this revision adds** (resolves
`docs/phase9_implementation_planning_audit.md` MAJOR finding 1). `run_triage_cycle()` uses **one
shared `AsyncSession` for the whole batch** (`async with session_factory() as session:`, mirroring
`services/collector.py`'s own single-session-per-cycle shape), but — **unlike** `services/collector.py`,
which commits once per *source* (a source can contain many items) — Phase 9 commits and rolls back
**once per event, not once per batch and not once per source-equivalent grouping**, because each
event's ownership claim, not the batch as a whole, is the atomic unit of correctness this Contract
defines (§7.5's "the claim, already committed in step 1" premise is specifically about one event's
claim, not a batch). Every event goes through exactly two phases:

**Phase A — Ownership acquisition (commit-or-skip, never partial)**
- *Normal path*: attempt `_claim_new_event()` (M2). If it returns `True` (won), **immediately
  `await session.commit()`** — this is the durable fact §7.5 calls "the claim, already committed in
  step 1." If it returns `False` (lost), no commit is needed (nothing changed); skip this event
  entirely and continue the loop — **no exception, no log entry**, per §18's "not an error"
  classification.
- *Recovery path*: for a stale candidate (already selected by M2's `_select_recovery_candidates()`,
  which already re-verified staleness and no-active-task at selection time), attempt
  `_acquire_recovery_ownership()` (M2) keyed on the candidate's observed `updated_at`. Same
  commit-or-skip rule: `True` → `await session.commit()` immediately; `False` → skip silently,
  continue.
- **A losing claimant (either path) MUST NOT proceed to Phase B at all** — it must not load
  `NewsSource`, must not call Triage, must not call `create_task()`. This is enforced structurally
  by the loop's own control flow (Phase B is inside the `if won:` branch, never reached otherwise),
  not merely by convention.

**Phase B — Post-claim processing (runs only after Phase A's commit succeeded)**
1. Loads the now-owned event's `NewsSource`.
2. Calls `decide_triage()` (M1) with a real `reference_now = datetime.now(timezone.utc)` **captured
   once per event, at the top of this phase** (never re-read mid-phase — determinism within one
   decision), logs the structured Triage explanation (§15) and, if this was a recovery path, the
   claim-age-at-acquisition (§15's second bullet).
3. Calls `workflow_service.create_task()` unmodified; handles all three outcomes exactly per §7.5:
   - **Success**: `create_task()`'s own internal commit (`services/workflow_service.py:71`) finalizes
     this event's work. Nothing further required from the orchestrator.
   - **`DuplicateActiveTaskError`**: not a failure (§7.5 point 2). Caught, logged at `info`,
     `await session.rollback()` called anyway — defensively, uniformly, even though no SQL statement
     actually failed here (`_find_active_task()` is a plain `SELECT`) — so this path never needs a
     special case distinct from "any other exception" below. Loop continues.
   - **Any other exception** (`NewsEventNotFoundError`, `UnknownWorkflowTypeError`, or unexpected):
     caught, logged at `error` (§15/§18), **`await session.rollback()` called before the loop
     continues to the next event**.
4. Returns to the loop; the next event is processed using the **same** session, now guaranteed to be
   in a clean, usable transaction state regardless of what just happened.

**The binding invariant this revision states explicitly, not vaguely**: *one event's post-claim
failure MUST NOT leave the SQLAlchemy session in a failed-transaction state that breaks the
processing of later events in the same batch.* `await session.rollback()` in Phase B's failure paths
is what guarantees this — it discards only the current (uncommitted) Phase-B work for the failing
event; it **does not and cannot** undo that event's own Phase-A claim, because that claim was already
committed, in its own prior transaction, before Phase B ever began. This is precisely why Phase A's
"commit immediately, before Phase B starts" rule matters: it is what makes Phase B's rollback safe to
call without also erasing the ownership fact the rest of this Contract's recovery story depends on.

**Consequence, explicitly named, matching Contract §7.5/§7.6**: after a Phase B failure, the event is
left exactly at `status == PROCESSING`, no active `EditorialTask` — the residual, bounded state
§7.5 already describes and accepts. This is not a bug this revision introduces or needs to prevent;
it is the correct, intended outcome, and it is only reachable *as described* because the claim was
independently durable. That residual state is picked up again, later, only once it becomes stale,
by the existing recovery path (M2's `_select_recovery_candidates()` + `_acquire_recovery_ownership()`,
composed here in Phase A) — no new recovery mechanism is introduced by this revision.

**No distributed transaction, no cross-session coordination, and no change to session ownership is
introduced anywhere in this discipline** — every commit/rollback is a plain, single-session
operation on the one `AsyncSession` `run_triage_cycle()` already owns for the whole batch; `create_task()`'s
own internal commit is untouched and unmodified, exactly as the Contract requires.

- `TriageCycleReport` (`@dataclass`, mirroring `CollectionReport` exactly): counts for events
  claimed, events recovered, tasks created, claim races lost, `DuplicateActiveTaskError` outcomes,
  other (rolled-back) failures.
- `run_triage_cycle(session_factory=async_session_factory) -> TriageCycleReport`: selects eligible
  `NEW` events and stale recovery candidates (M2's `_select_recovery_candidates` plus a
  `NEW`-status query), then runs the Phase A / Phase B sequence above for each, returning the
  populated `TriageCycleReport`.
- `scripts/run_triage.py`: `setup_logging()` + `await run_triage_cycle()`, `python -m
  scripts.run_triage` — the same ~20-line shape as `scripts/run_collector.py`, confirmed by direct
  comparison during implementation, not just by description here.

**5. Explicitly out of scope**: any scheduler, cron, or daemon wrapper around
`scripts/run_triage.py` (§7.4 — explicitly deferred); catching and swallowing a claim function's own
internal DB errors beyond the documented outcomes (a genuine connection failure propagates, exactly
as `services/collector.py`'s own top-level `try/except` around the whole cycle already handles for
its analogous case — reused, not reinvented); any distributed transaction, two-phase commit, or
cross-session coordination mechanism (the transaction discipline above uses only the one, already-
existing `AsyncSession`/`session.commit()`/`session.rollback()` primitives every other service in
this repository already uses — no new session-ownership model, no redesign); fixing or working
around the `_find_active_task()` `CREATED`/`RUNNING`-only lifecycle gap (Limitation B, §4 —
unaffected by this revision, still deferred).

**6. Tests required** (integration-tier, real Postgres):
- Positive: end-to-end — a real `NEW` `NewsEvent` + `NewsSource` row (`real_news_event` fixture) run
  through one `run_triage_cycle()` call results in exactly one `EditorialTask` at the priority
  `decide_triage()` would independently compute for the same inputs.
- `create_task()` outcome handling — all three cases, using real DB state, not mocks: (a) success;
  (b) forced `DuplicateActiveTaskError` (pre-create an active task for the same event before running
  the cycle); (c) another exception (e.g. an unregistered `WorkflowType`, if constructible without
  touching frozen `workflows/registry.py` — otherwise a monkeypatched `create_task` raising a generic
  exception, clearly labeled as a test-only substitution, not a production code path).
- **Transaction-discipline tests (this revision's required additions, resolving audit MAJOR finding
  1)**:
  1. **Claim committed before Triage executes**: after a successful Phase A claim, read the event's
     `status` back via a **second, independent session** (not the one `run_triage_cycle()` is using)
     *before* Phase B would plausibly finish — e.g. by monkeypatching `decide_triage()` to block or
     raise immediately after being called — and assert the second session already observes
     `status == PROCESSING`, proving the commit happened strictly before Triage ran, not merely
     before the whole event finished.
  2. **Claim committed before `create_task()` executes**: same technique, monkeypatching
     `workflow_service.create_task` to raise immediately, and confirming (via a second, independent
     session) that `status == PROCESSING` is already durably visible despite `create_task()` never
     reaching its own internal commit.
  3. **Post-claim failure triggers rollback**: force a Phase B failure (e.g. a monkeypatched
     `create_task` raising a generic exception) and assert the *same* `session` object used by
     `run_triage_cycle()` is still usable immediately afterward (e.g. a trivial `SELECT 1`-equivalent
     query succeeds) — a direct proof the session was not left in Postgres's
     `InFailedSqlTransaction` state.
  4. **Later events in the same batch still process successfully**: two real `NewsEvent` rows in one
     `run_triage_cycle()` call; the first is forced to fail in Phase B (monkeypatched `create_task`
     failure for that one event only); the second is left to succeed normally. Assert the second
     event ends with exactly one `EditorialTask` at the correct priority, and the first ends at
     `status == PROCESSING` with no active task — **this is the direct, executable proof of batch
     isolation**, replacing the earlier, vaguer "mirrors `services/collector.py`'s per-source
     isolation" description with a concrete assertion.
  5. **Residual `PROCESSING`/no-task state remains recoverable later**: after test 4's forced
     failure, advance a controlled `reference_now` past the configured staleness threshold and run a
     second `run_triage_cycle()` call; assert the first event is now claimed via the recovery path
     and ends with exactly one `EditorialTask` — proving the residual state this revision's Phase B
     failure handling produces is the same, already-approved recovery path M2 already tests, not a
     new one.
  6. **Losing claimant does not execute post-claim work**: two independent `run_triage_cycle()`-style
     claim attempts (or `run_triage_cycle()` run concurrently with a direct M2 primitive call) racing
     the same `NEW` event; assert the loser's own code path never calls `decide_triage()`/
     `create_task()` (via a call-counting spy on the loser's code path) and that exactly one
     `EditorialTask` results overall.
- Rerun safety: running `run_triage_cycle()` twice in a row against the same, already-fully-processed
  event produces no duplicate `EditorialTask` (the event no longer matches either eligibility branch
  once it has an active task).
- No-hard-drop end-to-end: every `NEW` event in a batch gets exactly one `EditorialTask`, including
  one deliberately constructed to land in the lowest (`C`) tier.
- Concurrency: two full `run_triage_cycle()` invocations (two independent session factories/event
  loops, not the shared `db_session` fixture) against a shared pool of `NEW` + stale-`PROCESSING`
  events produce, in total, exactly one `EditorialTask` per event — no duplicates, no event left
  unprocessed after both cycles complete.
- Logging: a test asserts the structured Triage-explanation log record's required fields (§15) are
  all present for at least one successful decision.

**Test helper location** (resolves audit MINOR finding 3): the two-independent-session helper M2
introduces for its own concurrency tests (`tests/test_triage_orchestrator_claims.py`) is reused
as-is by this milestone's own concurrency and transaction-discipline tests
(`tests/test_triage_orchestrator_cycle.py`), via a plain Python import between the two test modules
(`from tests.test_triage_orchestrator_claims import <helper>`). **`tests/conftest.py` is not
modified by M2 or M3.** This is the smallest existing-pattern-compatible choice: exactly two Phase 9
test modules need this helper (both introduced by this Contract's own claim/recovery mechanism, not
by an unrelated future need), so a shared, local, Phase-9-scoped helper is justified per "prefer
local helpers unless multiple modules genuinely need the same fixture" — but a *global* `conftest.py`
fixture, used by every test file in the repository regardless of relevance, is not, and is
deliberately avoided.

**7. Definition of Done**: `python -m scripts.run_triage` runs successfully against the real dev
database (manually, as runtime evidence — not just via pytest) and produces a sensible
`TriageCycleReport`; every test in bullet 6 passes, **including all six transaction-discipline
tests**; code review confirms `await session.commit()` appears exactly once per successful Phase A
outcome (never deferred to Phase B) and `await session.rollback()` appears in every Phase B
exception path (never omitted, never conditional on exception type); §16's explicit "no test may
claim `NEWS_ANALYSIS` reaches `COMPLETED`" constraint holds (grep the new test files for
`TaskStatus.COMPLETED` and confirm no assertion pairs it with the real `WorkflowType.NEWS_ANALYSIS`).

**8. Verification commands**:
```
pytest tests/test_triage_orchestrator_cycle.py tests/test_triage_orchestrator_claims.py -v
pytest --tb=short -q
ruff check services/triage_orchestrator.py scripts/run_triage.py tests/test_triage_orchestrator_cycle.py
mypy services/triage_orchestrator.py scripts/run_triage.py
python -m scripts.validate_architecture
```

**9. Runtime evidence**: actual terminal output of `python -m scripts.run_triage` run against the
real dev DB with at least one real `NEW` `NewsEvent` present (e.g. seeded via
`python -m scripts.run_collector` first, or a manual insert), showing the resulting
`TriageCycleReport` and the created `EditorialTask` row's priority queried back afterward; **the
measured wall-clock duration of one claim-to-`create_task()` sequence**, logged or timed explicitly,
compared against the configured `stale_processing_threshold_seconds` default — this is the concrete
check on Limitation A (§4 above), not a formality. **Batch-isolation runtime evidence (this
revision's required addition)**: seed two real `NEW` `NewsEvent` rows against the real dev DB; run
`python -m scripts.run_triage` once with the first event rigged to fail in Phase B (e.g. a
temporary, manual duplicate-task pre-seed for that one event, reverted after the run — not a
permanent code change) and the second left normal; observe and record, from real queried DB state
afterward, that the first event is `PROCESSING` with no active task and the second has exactly one
`EditorialTask` — the concrete, executed demonstration that one event's failure did not poison the
other's processing in the same run.

**10. Rollback safety**: depends on M1 + M2; revertible together with them if ever needed, but not
independently once M4+ exist (M4-M7 do not import `services/triage_orchestrator.py`, so reverting M3
alone would not break the Capability-side milestones — only Phase 9's own Triage pipeline).

**11. Expected commit checkpoint**: "Phase 9 M3: Triage orchestration service and script entry
point."

**12. Human review gate**: **STOP** after implementation and verification. Do not commit or begin M4
until explicitly approved, unless a later autonomous-mode instruction overrides this gate.

---

### M4 — `ResearchCapability`

**1. Goal**: deliver `ResearchCapability` as an ordinary Phase 8 `Capability` — structured fact
extraction from one `NewsEvent`'s existing text, nothing more — following
`capabilities/scoring_capability.py`'s shape exactly.

**2. Contract coverage**: §8 (`ResearchCapability` Contract, full table + binding scope
clarification), §11 (Capability Execution/Error Model — full compliance, no fork), §16
(`ResearchCapability`/`IntelligenceCapability` testing rules).

**3. Files**:
- Production: `capabilities/research_capability.py` (new), `prompts/research/v1.yaml` (new).
- Tests: `tests/test_research_capability.py` (new), `tests/fakes/research_output.py` (new — the
  shared canonical-shape fixture, see below).
- Docs/config: none.

**Mechanical Research→Intelligence shape ownership** (resolves
`docs/phase9_implementation_planning_audit.md` MINOR finding 2). This milestone adds
`tests/fakes/research_output.py`, a small, plain constant living in the same, already-existing
`tests/fakes/` directory every other Phase 8/9 test double already lives in (no new framework, no
new directory, no coupling between the two Capabilities themselves — only their *tests* share this
one value):

```python
# tests/fakes/research_output.py
CANONICAL_RESEARCH_OUTPUT: dict[str, object] = {
    "facts": ["<example fact 1>", "<example fact 2>"],
    "confidence": 0.8,
    "gaps": [],
}
```

`tests/test_research_capability.py`'s own happy-path test asserts `ResearchCapability.execute()`'s
`structured_output` **matches this exact constant's shape** (same keys, same value types) — locking
`ResearchCapability`'s real output shape to this one, single, named artifact, not merely describing
it in prose. `IntelligenceCapability`'s tests (M5) import and reuse this **same** constant to seed
`step_results["research"]` (see M5 below) — so a future change to Research's output shape that
breaks Intelligence's assumption shows up as a **test failure in M5's own suite the moment `M4`'s
constant changes**, not only once M7's full integration proof eventually runs it for real. This is
the mechanical ownership the audit asked for: `tests/fakes/research_output.py`, introduced here by
M4, is the one artifact both Capabilities' test suites are pinned to.

**4. Implementation scope**: `__init__(self, gateway: LLMGateway, prompt_repository:
PromptRepository)` — exactly `ScoringCapability`'s shape, no additional dependency (§8, §4.2 of the
frozen Phase 8 contract). `CAPABILITY_NAME = "research"` (already mapped in
`capabilities/capability_mapping.py` — zero change needed there, confirmed in §2 above).
`RESEARCH_CAPABILITY_DEFINITION` (`CapabilityDefinition`, `required_context=["news_event"]`,
`expected_output_keys` matching the frozen output shape below). `execute()`: resolves the prompt via
`PromptRepository.resolve()`, builds a `GenerateRequest` from `CapabilityContext.business.news_event`
only (title, category, content, language — **no** `workflow_state` access, since Research runs
first and has nothing upstream to read, per §8's Input row), calls `call_generate()` (the centralized
M1-mechanism, reused unmodified), validates the structured-output floor, returns a `SUCCESS`
`CapabilityResult` with `structured_output` shaped as `{"facts": [...], "confidence": <float>,
"gaps": [...]}` — a concrete, minimal instantiation of §8's frozen conceptual shape ("facts,
confidence, optionally flagged gaps/ambiguity"); exact field names are, per §22, an implementation
detail this plan fixes here rather than leaving open, since the Contract explicitly delegates that
choice to implementation. Retry (§10) is **not** implemented for M4, matching `QualityCapability`'s
own precedent that implementing it is optional, not mandatory (§11's explicit citation) — a smaller
first cut, extensible later without breaking the output contract (§19 rule 2).

**5. Explicitly out of scope**: any external fact-checking, web browsing, or tool call (§8's
binding scope clarification — Phase 8 permanently defers tool integration); reading
`workflow_state.step_results` (Research is always the first step to run in this phase — nothing
exists there yet); the §10 correction-retry mechanism (optional, deferred to a later milestone or
phase if ever needed); any `BudgetGuard`/`CostTracker` reference (forbidden, §2.5).

**6. Tests required** (unit-tier, `FakeLLMGateway` + `FakePromptRepository`, mirroring
`tests/test_scoring_capability.py` exactly):
- Positive: happy path — a well-formed fake response produces a `SUCCESS` result with the expected
  `structured_output` shape.
- Negative: structured-output validation-floor failure → raises the correct `CapabilityError`
  subtype (no retry attempted, since M4 does not implement §10).
- `GatewayError`→`CapabilityError` translation: exercised via `FakeLLMGateway.generate_error()`,
  proving the centralized `call_generate()` translation path is used, not reimplemented.
- Repeated-invocation independence: two consecutive `execute()` calls on the same instance with
  different `CapabilityContext`s produce independent results (no leaked state, §3.2).
- Scope-honesty: a test explicitly asserts the built `GenerateRequest`/prompt never references
  external verification, browsing, or a tool call — a regression guard for §8's binding scope
  clarification, not just an implicit property.
- Concurrency: not applicable — Capabilities are already proven stateless/concurrency-safe by the
  frozen Phase 8 contract; no new proof needed here.

**7. Definition of Done**: `python -m scripts.validate_architecture` still exits 0 (confirms the
existing `capability-isolation` rule catches nothing — this file needs zero new validator rule,
confirmed in §2 above, not merely assumed); all tests in bullet 6 pass; the module is **not yet**
registered in `capabilities/registry.py` (that is M6's job, kept separate so this milestone's tests
prove the Capability in isolation first, matching Phase 8's own M3-before-M4 split).

**8. Verification commands**:
```
pytest tests/test_research_capability.py -v
pytest --tb=short -q
ruff check capabilities/research_capability.py tests/test_research_capability.py
mypy capabilities/research_capability.py
python -m scripts.validate_architecture
```

**9. Runtime evidence**: `pytest -v` output; the actual `structured_output` dict produced by the
happy-path test, printed/logged, to confirm the concrete shape matches what M5 will need to read
from `step_results["research"]` (a direct, verifiable link to M5's dependency, not just an assertion
of shape equality in code).

**10. Rollback safety**: fully independent — not yet registered anywhere, not imported by any other
production file. Trivially revertible in isolation.

**11. Expected commit checkpoint**: "Phase 9 M4: ResearchCapability."

**12. Human review gate**: **STOP** after implementation and verification. Do not commit or begin M5
until explicitly approved, unless a later autonomous-mode instruction overrides this gate.

---

### M5 — `IntelligenceCapability`

**1. Goal**: deliver `IntelligenceCapability` — editorial-significance judgment from Research's
already-extracted facts, consumed exclusively through the existing, frozen `step_results` mechanism,
never by importing `ResearchCapability`.

**2. Contract coverage**: §9 (`IntelligenceCapability` Contract), §9.1 (the `step_results`
consumption mechanism, including its §14.1 crash/restart scope cross-reference), §10 (Research vs
Intelligence call semantics), §11, §16.

**3. Files**:
- Production: `capabilities/intelligence_capability.py` (new), `prompts/intelligence/v1.yaml` (new).
- Tests: `tests/test_intelligence_capability.py` (new).
- Docs/config: none.

**4. Implementation scope**: identical construction shape to M4
(`__init__(gateway, prompt_repository)`). `CAPABILITY_NAME = "intelligence"` (already mapped, zero
change needed). `execute()` reads `context.business.workflow_state.step_results.get("research",
{})` (§9.1's exact, already-frozen field path — **never** a direct import or call of
`ResearchCapability`, mechanically unenforceable by name alone but confirmed by code review and by
the fact that `capabilities/intelligence_capability.py` will not appear in
`capabilities/research_capability.py`'s importers and vice versa) to build its prompt context
alongside `context.business.news_event` (for identifying context only — title/category — **never**
re-reading `content` for fact extraction, per §9's explicit "MUST NOT re-extract" rule). Output
shape: `{"significance": <float>, "angle": <str>, "audience_relevance": <str>,
"recommendation": <str>}` — a concrete instantiation of §9's frozen conceptual shape. If
`step_results["research"]` is missing or empty (Research did not run, or this is a malformed
synthetic test), `execute()` still runs — Intelligence MUST NOT raise merely because Research's
output is absent, since §9.1 describes the mechanism, not a hard requirement that it always be
populated in every conceivable caller; the prompt notes the absence explicitly rather than fabricating
facts. Retry (§10) not implemented, same reasoning as M4.

**5. Explicitly out of scope**: importing or holding a reference to `ResearchCapability` (§9.1,
mechanically checked by grep during review — `import.*research_capability` must not appear in this
file); computing a final, cross-event-comparable score (Final Ranking's job, §9's explicit
prohibition); deciding AI processing priority or budget (Triage's job, upstream, §9/P3); any Engagement
Analysis responsibility (§20 item 2).

**6. Tests required** (unit-tier, `FakeLLMGateway` + `FakePromptRepository`):
- Positive: happy path with `step_results["research"]` populated from **`tests/fakes/research_output.py`'s
  `CANONICAL_RESEARCH_OUTPUT`** (M4's own artifact, imported here, never hand-duplicated — resolves
  audit MINOR finding 2/§10/§13: this is the mechanical link between M4's real output shape and M5's
  input assumption, not a manually-maintained parallel description) produces a `SUCCESS` result
  correctly reflecting Research's facts in the built prompt (asserted by inspecting the fake
  gateway's `received_requests`, mirroring `tests/test_scoring_capability_retry.py`'s existing
  pattern for inspecting sent requests).
- Negative: structured-output validation-floor failure → correct `CapabilityError`.
- Missing `step_results["research"]`: `execute()` still completes (does not raise merely for this
  reason) — proves the "does not hard-require it be populated" design decision above is actually
  implemented, not just described.
- Non-coupling proof: a static/import-level test (or a simple `ast`-based check, reusing
  `scripts/validate_architecture.py`'s own approach at a test-file level, or a plain
  `"research_capability" not in Path(...).read_text()` check) confirms this file never imports
  `capabilities.research_capability` — a **direct, mechanical** proof of §9.1's binding rule, not
  merely an assumption.
- `GatewayError` translation, repeated-invocation independence: same pattern as M4.
- Concurrency: not applicable, same reasoning as M4.

**7. Definition of Done**: same shape as M4's DoD — validator clean, all tests pass, not yet
registered (M6's job).

**8. Verification commands**:
```
pytest tests/test_intelligence_capability.py -v
pytest --tb=short -q
ruff check capabilities/intelligence_capability.py tests/test_intelligence_capability.py
mypy capabilities/intelligence_capability.py
python -m scripts.validate_architecture
```

**9. Runtime evidence**: `pytest -v` output; the actual built `GenerateRequest` text for the
happy-path test, printed/logged, showing Research's fake facts genuinely present in Intelligence's
prompt — a concrete demonstration of the `step_results` handoff working at the unit level, ahead of
M7's full integration proof.

**10. Rollback safety**: independent of M4 at the *production* code level (no import of
`capabilities/research_capability.py`, and §9.1's binding rule forbids one). M5's **tests** do
import `tests/fakes/research_output.py` (M4's shared fixture, §2/§3 above) — a small, test-only
dependency, revertible together with M4's test artifact if M4 is ever reverted, but this does not
affect `IntelligenceCapability`'s own production code, which remains independently revertible.

**11. Expected commit checkpoint**: "Phase 9 M5: IntelligenceCapability."

**12. Human review gate**: **STOP** after implementation and verification. Do not commit or begin M6
until explicitly approved, unless a later autonomous-mode instruction overrides this gate.

---

### M6 — Registration / Boot Wiring

**1. Goal**: register both Capabilities into `CapabilityRegistry` via `build_registry()`, following
Phase 8 M7's exact precedent — the smallest possible change.

**2. Contract coverage**: §12 (Registration — binding constraints), §17 (confirms, does not
re-litigate, that `capability-isolation` already covers both new files).

**3. Files**:
- Production: `capabilities/registry.py` (two new `import` lines + two new
  `registry.register(...)` lines inside `build_registry()`'s existing body — no other line changes).
- Tests: extend `tests/test_capability_boot_wiring_e2e.py` (or add a small, focused new test file if
  the existing one is already large/single-purpose — decided at implementation time by inspecting
  its current size, an implementation detail).
- Docs/config: none. `integrations/llm_gateway/boot.py` needs **zero** change — confirmed by
  re-reading it in full during planning: `assemble_ai_integration_layer()` already calls
  `build_registry(gateway, prompt_repository, budget_guard, tool_registry)` generically; the two new
  registrations live entirely inside `build_registry()`'s own body.

**4. Implementation scope**: exactly Phase 8 M7's pattern — `from capabilities.research_capability
import RESEARCH_CAPABILITY_DEFINITION, ResearchCapability`, `from
capabilities.intelligence_capability import INTELLIGENCE_CAPABILITY_DEFINITION,
IntelligenceCapability`, then two `registry.register(...)` calls added to `build_registry()`'s
existing body, alongside the two already there. `budget_guard`/`tool_registry` continue to be
accepted and passed to neither (§12, §18 rule 19 of the frozen Phase 8 contract — unchanged
by this milestone, restated not altered).

**5. Explicitly out of scope**: any registry redesign, runtime discovery, or plugin mechanism (§12
explicit prohibition); any `ProviderRegistry`/`ModelRegistry` change; any claim, test, or comment
that this makes `NEWS_ANALYSIS` "now executable" or "complete" (§12's explicit binding statement —
checked directly in code review, not just assumed).

**6. Tests required**:
- Positive: `build_registry()` resolves both `"research"` and `"intelligence"` after this change,
  alongside the pre-existing `"scoring"`/`"quality"` — a four-capability coexistence test, the direct
  analog of Phase 8 M8's own cross-cutting concern (ambiguous-routing risk when multiple
  `ModelDescriptor`s share a quality tier) is re-checked here too, reusing the same fix pattern
  (explicit `preferred_model` per capability's `CapabilityContext.execution`) if it recurs — not
  assumed away.
- Negative: attempting to register either new Capability a second time raises
  `DuplicateCapabilityRegistrationError` (mirrors the existing test pattern for the first two
  Capabilities, applied to the new ones for symmetry, not because a new mechanism needs proving).
- No completion-claim regression: a `grep`-based or explicit test-suite-wide check (can be a simple
  repo-wide `grep -rn "NEWS_ANALYSIS" tests/` review during this milestone, not necessarily a new
  automated test) confirms no test added by M6 pairs `WorkflowType.NEWS_ANALYSIS` with
  `TaskStatus.COMPLETED`.
- Concurrency: not applicable — registration happens once at boot, already covered by
  `CapabilityRegistry`'s existing seal-based immutability guarantees (frozen Phase 6/8 behavior, not
  re-tested here).

**7. Definition of Done**: `build_registry()` returns a sealed registry containing all four
Capabilities; `python -m scripts.validate_architecture` still exits 0; all tests in bullet 6 pass;
`capabilities/registry.py`'s diff is exactly the four-line addition described (plus imports) —
verified by `git diff --stat capabilities/registry.py` showing a small, expected line count, not a
large unexpected change.

**8. Verification commands**:
```
pytest tests/test_capability_boot_wiring_e2e.py -v
pytest --tb=short -q
ruff check capabilities/registry.py
mypy capabilities/registry.py
python -m scripts.validate_architecture
git diff --stat capabilities/registry.py
```

**9. Runtime evidence**: `pytest -v` output; a short manual `python -c` snippet (run, not committed)
constructing a real `CapabilityRegistry` via `build_registry()` with fakes and calling `.resolve()`
for all four names, printing each `CapabilityDefinition.name`/`version` to confirm the registry's
real runtime contents, not just a mocked assertion.

**10. Rollback safety**: fully independent — a small, additive change to one file. Trivially
revertible; would only "un-register" Research/Intelligence, not affect M4/M5's own already-passing
unit tests (which never go through the registry).

**11. Expected commit checkpoint**: "Phase 9 M6: register ResearchCapability and
IntelligenceCapability."

**12. Human review gate**: **STOP** after implementation and verification. Do not commit or begin M7
until explicitly approved, unless a later autonomous-mode instruction overrides this gate.

---

### M7 — Integration Proof + Cross-Cutting Regression

**1. Goal**: the final Phase 9 milestone — prove Research→Intelligence step-chaining works for real
through the actual, unmodified `WorkflowRunner`, using a synthetic `WorkflowDefinition` exactly as
§13 specifies, then run a full-repository regression pass confirming zero unrelated breakage.

**2. Contract coverage**: §9.1 (step-chaining mechanism, real proof), §13 (all "Allowed Phase 9
integration proof" bullets; the explicit prohibition on using the real `NEWS_ANALYSIS` definition);
§14.1 (crash/restart scope — the proof explicitly does not exceed one uninterrupted `run()` call);
§15 (observability, full compliance check); §16 (Integration section, all three bullets); §21 rule
14; §23 (self-audit against the full Acceptance Checklist, as a final confirmation, not a new
obligation).

**3. Files**:
- Production: none (this milestone is proof-only, per §13's own framing — "integration proof," not
  new capability).
- Tests: `tests/test_phase9_research_intelligence_integration.py` (new — the synthetic-workflow
  step-chaining proof, mirroring `tests/test_capability_boot_wiring_e2e.py`/
  `tests/test_phase8_cross_cutting_regression.py`'s exact structure), `tests/test_phase9_cross_cutting_regression.py`
  (new — the four-capability coexistence + no-completion-claim regression checkpoint, the direct
  Phase-9 analog of Phase 8's own M8).
- Docs/config: none.

**4. Implementation scope**:

**Synthetic `WorkflowType` — binding, explicit** (resolves
`docs/phase9_implementation_planning_audit.md` MINOR finding 1). Contract P10 explicitly, bindingly
forbids "no new `WorkflowType` enum member" — this revision states plainly that M7 **MUST NOT** add
one, and **MUST NOT** modify `schemas/workflow.py` in any way. The synthetic two-step
`WorkflowDefinition` this milestone builds reuses the **existing** `WorkflowType.DAILY_DIGEST` enum
value — chosen specifically because its own docstring already states it is "never registered in
`WorkflowRegistry`... resolving it raises `UnknownWorkflowTypeError`" under the real, global
registry, meaning it has no competing real `WorkflowDefinition` anywhere in the codebase to be
confused with (unlike `WorkflowType.CONTENT_GENERATION`, which does have one). This mirrors an
already-real, already-used precedent in this exact codebase: `tests/test_capability_boot_wiring_e2e.py`
(re-read in full during the prior audit pass) already constructs its own **local**
`WorkflowRegistry()` instance and registers a **custom, test-only** `WorkflowDefinition` under an
existing `WorkflowType` value (`CONTENT_GENERATION`, in that file's case) — never touching the real,
global `workflows.registry.registry` singleton and never adding an enum member. M7's synthetic
definition follows this identical pattern one level cleaner (reusing `DAILY_DIGEST` instead, to avoid
any adjacency to a real definition): a local `WorkflowRegistry()`, sealed, holding only the
two-step `research`/`intelligence` definition under `WorkflowType.DAILY_DIGEST`, passed explicitly
to `workflow_service.create_task(..., registry=<local registry>)` — never registered in, and never
resolved through, the real global registry. **If this specific reuse were ever found impossible**
(it is not — the pattern is already proven, working code in this repository), the fallback would be
to reuse `WorkflowType.CONTENT_GENERATION` instead (the exact value the existing precedent test
already uses) — under no circumstance does M7 add a new `WorkflowType` member.

A test-local `WorkflowDefinition` with exactly two steps named `"research"`/`"intelligence"` (never
registered in the real `WorkflowRegistry`, per §13's explicit instruction — confirmed zero existing
test imports `workflows.definitions.*` directly, so this milestone's test does not become the first
to break that pattern), run through the real, unmodified `WorkflowRunner` against a real
`EditorialTask`/`NewsEvent` (via `db_session`), proving:
(a) Research's `CapabilityResult` lands in `step_results["research"]`; (b) Intelligence's `execute()`
genuinely reads it (asserted via the fake gateway's received-request content, not merely via a
`SUCCESS` status, to actually prove the data flowed, not just that both steps ran); (c) the
synthetic task reaches `TaskStatus.COMPLETED` (a synthetic definition legitimately can — §13 only
forbids the **real** `NEWS_ANALYSIS` `WorkflowType` from being used as the completion proof, and this
is explicitly a different, test-local `WorkflowType`/definition, per §13's own allowed-proof list).
A second variant using a real `RoutingGateway` + `FakeProviderAdapter` (mirroring
`tests/test_capability_boot_wiring_e2e.py`) proves the same chain through the real Gateway machinery,
not only through `FakeLLMGateway`.

**5. Explicitly out of scope**: running the real `WorkflowType.NEWS_ANALYSIS` definition through
`WorkflowRunner` for any test or documentation purpose (§13's explicit, binding prohibition —
checked by the same `grep`-based review as M6); any crash/restart simulation (§14.1 — out of scope
entirely, not partially); any claim in a docstring, test name, or comment that this proves crash
safety, durability, or full pipeline completion; **adding a new `WorkflowType` enum member or
modifying `schemas/workflow.py` in any way (Contract P10, restated inline here per the audit's own
instruction, mirroring how M6 restates §12's "no completion claim" prohibition inline rather than
leaving it only implicit)**.

**6. Tests required**:
- The synthetic step-chaining proof described in bullet 4 (both `FakeLLMGateway` and real
  `RoutingGateway`+`FakeProviderAdapter` variants).
- Cross-cutting regression: all four Capabilities (`scoring`, `quality`, `research`, `intelligence`)
  resolve correctly from one shared, sealed `CapabilityRegistry` with no ambiguous-routing failure
  (re-checked directly, not assumed safe merely because M6 already checked it once).
- Negative/boundary: attempting to resolve `"engagement_analysis"`/`"scoring"` against the real,
  frozen `WorkflowRegistry.resolve(WorkflowType.NEWS_ANALYSIS)` and then running it through
  `WorkflowRunner` still ends `TaskStatus.FAILED` at the `engagement_analysis` step — a direct,
  executed proof of §13's own claim (re-verified as still true against real code, not merely cited
  from the Contract's prose) — and an explicit assertion that this is the *expected*, not
  regressed, outcome.
- Full-suite zero-regression check (§15 of the task instructions): the **entire** repository test
  suite is run; every pre-Phase-9 test that passed before this milestone still passes; any
  pre-existing, already-known-baseline failure (if one exists — none is currently known, per Phase
  8's own clean-baseline confirmation) is explicitly distinguished from a new regression, never
  silently "fixed" as a side effect of this milestone.
- Concurrency: none new — M2/M3 already carry Phase 9's own concurrency proofs; this milestone does
  not repeat them.

**7. Definition of Done**: every test in bullet 6 passes; `pytest` (full suite) shows the same pass
count plus exactly the new Phase 9 tests added across M0-M7, with zero unexplained failures
elsewhere; `ruff`/`mypy` clean repo-wide (or, if a pre-existing baseline gap is found, it is
identified by name and confirmed pre-existing via the same `git stash`-based verification Phase 8
used, never silently patched inside a Phase 9 commit); `python -m scripts.validate_architecture`
exits 0; a final self-audit against Contract §23's 20-item Acceptance Checklist confirms every item
still holds against the **implemented** code, not just the Contract's own text (the Contract audited
itself in §23; this milestone is the first point real code exists to check that self-audit against).

**8. Verification commands**:
```
pytest -v tests/test_phase9_research_intelligence_integration.py tests/test_phase9_cross_cutting_regression.py
pytest --tb=short -q                          # full repository suite
ruff check .
mypy .                                        # compared against the pre-Phase-9 baseline, per §15
python -m scripts.validate_architecture
git status && git diff --stat main            # or the relevant base branch — full Phase 9 diff scope
```

**9. Runtime evidence**: full `pytest -v` output for the new integration tests, showing the
actual `step_results` dict passed between steps (printed, not only asserted) as concrete proof of
the handoff; the full-suite pass/fail summary line; the `mypy`/`ruff` output compared explicitly
against the M0-baseline output captured before Phase 9 began (a real diff of error counts, not a
claim).

**10. Rollback safety**: test-only milestone (no production file changes) — trivially revertible
with zero impact on M0-M6's own passing state, since it adds proof, not new runtime behavior.

**11. Expected commit checkpoint**: "Phase 9 M7: Research→Intelligence integration proof and
cross-cutting regression checkpoint." This is also the natural point to consider a short,
**separate**, explicitly-requested documentation commit for this Planning document itself, if the
user later asks for one — not implied or assumed here.

**12. Human review gate**: **STOP** after implementation and verification. This is the final
milestone — do not proceed to any further Phase 9 work (e.g. a future scheduling phase revisiting
Limitation B) without a new, explicit planning pass, unless a later autonomous-mode instruction
overrides this gate.

---

## 8. Cross-Milestone Verification Strategy

Every milestone's own §8 (Verification commands) is the authoritative per-milestone list; this
section states the discipline applied consistently across all eight:

- **Focused pytest** (the milestone's own new test file(s)) runs first, fast feedback.
- **Full pytest** runs before any milestone is reported complete — "zero regression from the
  previous approved checkpoint" is the acceptance bar, **not** a hardcoded total test count (a
  future milestone or an unrelated concurrent change to the repository could legitimately add or
  remove tests elsewhere; the count itself is never the signal, only whether previously-passing
  tests still pass).
- **ruff** and **milestone-scoped mypy** run against exactly the files each milestone touches.
- **Repo-wide mypy baseline comparison**: before M0 begins, capture the current repo-wide `mypy .`
  output once as the baseline (the known, pre-existing `types-PyYAML`-related gap documented during
  Phase 8 is expected to still be present and is **not** Phase 9's to fix). Each milestone's own
  mypy check is scoped to its own files; the full-repo baseline is only re-compared at M7, to catch
  any accidental widening of the gap — never to demand the pre-existing gap be closed.
- **Architecture validator** (`python -m scripts.validate_architecture`) runs after every milestone,
  not only M0 — cheap, fast, and the single most direct mechanical proof that isolation boundaries
  hold as new files accumulate.
- **Runtime evidence**: each milestone's §9 specifies what must actually be *run and observed*, not
  only asserted by a test — continuing this whole engagement's established discipline of
  empirical verification over trust.
- **Migration check**: `git status` after every milestone that touches the database layer (M2, M3)
  explicitly confirms no new file appears under this repository's migrations directory — a direct,
  cheap check against P8/§20 item 16, not merely an assumption from not having written one.
- **Known baseline issues vs. new regressions**: if `mypy`/`ruff`/`pytest` surface a failure, the
  first action is always to determine — via `git stash`/isolation, exactly as Phase 8 did for its
  own pre-existing mypy gap — whether the failure predates the current milestone's changes. A
  pre-existing issue is recorded as a note in the milestone's review report, never silently patched
  inside an unrelated Phase 9 commit (this instruction is binding, restated from the task directly).

---

## 9. Rollback Strategy

Each milestone's §10 states its own specific rollback scope; the general pattern:

- M0, M4, M5, M6, M7 are **independently revertible** at any point — each is additive, touches a
  small, self-contained file set, and nothing outside Phase 9 imports any of them.
- M1 and M2 are independently revertible **until M3 exists** (M3 is the first consumer of both).
  After M3 is built, reverting M1 or M2 alone would break M3 — they should be reverted together with
  M3 if ever necessary.
- M3 depends on M1+M2 but nothing outside Phase 9 depends on M3 — reverting M1+M2+M3 together at any
  point leaves the rest of the repository (including M4-M7, if already built, since they touch an
  entirely separate subsystem) unaffected.
- M6 is the one milestone that changes a file with a pre-existing history
  (`capabilities/registry.py`) — its rollback is a small, well-isolated diff (four lines plus two
  imports), independently revertible without affecting `ScoringCapability`/`QualityCapability`'s own
  registration.
- No milestone in this plan requires a migration, so no milestone's rollback ever involves a
  database schema reversal — every rollback is a pure code/test revert.
- **Standing safety net, unchanged from every Phase 9 document before this one**: even in a total
  worst-case rollback of every milestone in this plan, nothing outside `services/freshness.py`,
  `services/triage.py`, `services/triage_orchestrator.py`, `scripts/run_triage.py`,
  `capabilities/research_capability.py`, `capabilities/intelligence_capability.py`,
  `prompts/research/`, `prompts/intelligence/`, `capabilities/registry.py`'s four added lines, three
  new `scripts/validate_architecture.py` rules, and `core/config.py`'s one new field is ever touched
  — Phase 5/6/7/8 remain byte-identical throughout, confirmed at every milestone via `git status`/
  `git diff --stat` exactly as every prior Phase 9 audit round already established as this
  engagement's standing discipline.

---

## 10. Deferred Work

Restated from §4 above, plus items the Contract itself already classifies as DEFERRED (§22) and
which no milestone in this plan touches:

- Production scheduling for `scripts/run_triage.py` (§7.4) — a future integration milestone, same
  status `scripts/run_collector.py` already has.
- The `_find_active_task()` `CREATED`/`RUNNING`-only lifecycle gap (Limitation B, §4 above) — **must
  be revisited before any future phase wires automatic `WorkflowRunner` scheduling against real
  tasks**, explicitly flagged here as that future phase's own prerequisite, not Phase 9's.
- Durable, crash-safe multi-step `WorkflowRunner` checkpointing (§14.1, §20 item 18) — a distinct
  future workflow-persistence concern, not a Capability-semantics one, per the Contract's own §14.1
  point 7.
- The title-overlap/republication check (`docs/phase9_final_decisions.md` §7) — deferred, not
  merely undecided (§20 item 17).
- `EngagementAnalysisCapability`, Final Editorial Ranking, Opportunity Score, clustering, embeddings,
  vector DB, engagement-data collection, source-reputation learning, autonomous research agents — all
  §20 non-goals, none scheduled by this plan.
- Tuning the provisional Freshness tier weights, priority-mapping thresholds, reliability-null
  default, and staleness threshold against real production data once Phase 9 has run for a while —
  explicitly product-configuration, explicitly not this plan's job to finalize with real-world
  evidence that does not exist yet (§17 below states the chosen starting defaults and why they are
  safe-but-provisional).

---

## 11. Implementation Readiness Checklist

- [x] Contract, both audits, the recovery re-audit, and all four earlier Phase 9 documents read in
  full before drafting this plan.
- [x] Current repository baseline inspected directly for every file/pattern the Contract or this
  plan references (§2 above) — no milestone below relies on an unverified assumption about existing
  code shape.
- [x] Every milestone traces to specific Contract section(s); no milestone introduces a
  responsibility the Contract does not authorize.
- [x] No milestone touches Phase 5/6/7/8 frozen files, adds a migration, or modifies the Contract.
- [x] Architecture-validator gap identified and scheduled early (M0), not deferred or skipped;
  confirmed which existing rules already suffice (Capability-isolation) so no redundant rule is
  invented.
- [x] Product-configuration values identified, defaulted, and explicitly separated from architecture
  invariants (§17 below).
- [x] All three "documented limitations" (§4 above) are explicitly preserved by name in at least one
  milestone's "explicitly out of scope" list, not merely absent from the plan by omission.
- [x] Dependency graph independently derived from actual repository/Contract dependencies, not
  copied from the task's suggested shape without verification (§5's "why" explains every deviation
  and every confirmation).
- [ ] **User approval of this plan** — pending, per the mandatory human review gate before M0 begins.

---

## Product Configuration (§17 of the planning instructions)

**Architecture invariants (frozen, not configurable — restated from Contract §22's own "Frozen, not
provisional" paragraph, not reopened here)**: the closed Triage input-signal set; the
deterministic/no-LLM requirement; the no-hard-drop invariant; the `NewsEvent` atomic-claim and
stale-recovery-ownership DB-level guarantees; the requirement that *some* positive staleness guard
exist; the `TaskPriority` explicit-ordinal-mapping requirement; the uninterrupted-execution scope of
the `step_results` handoff.

**Initial configurable defaults chosen by this plan** (all product-tunable per Contract §22; none is
architecture):

| Value | Default | Where it lives | Why |
|---|---|---|---|
| `stale_processing_threshold_seconds` | `900` (15 minutes), `Field(gt=0)` | `core/config.py` `Settings` field, env-overridable | Operational/safety-relevant (directly gates the §7.6 "stolen healthy worker" constraint), analogous to `redis_unavailable_policy` — belongs in `Settings`, not a module constant, so it can be tuned per environment without a code change. 15 minutes is a wide, deliberately conservative margin over the expected claim-to-`create_task()` latency (no LLM call in that path — one `NewsSource` load, one pure-Python Triage call, one `create_task()` call — realistically sub-second to low-seconds), leaving orders of magnitude of headroom. M3's runtime evidence measures the real observed latency to sanity-check this margin before Phase 9 closes. The *duration* (`900`) is product configuration; the `Field(gt=0)` constraint is architecture (Contract §7.6 rule 5, §22) and is not itself configurable — see M2's "Positive-staleness-threshold validation" for the binding rule and its tests. |
| Freshness tier boundaries (0–2h/2–6h/6–12h/12–24h/24–48h/48h+) | as listed | module constant in `services/freshness.py` | Pure algorithm tuning, not an operational/deployment concern — mirrors `services/collector.py`'s `MAX_FETCH_ATTEMPTS`/`RETRY_BACKOFF_SECONDS` precedent directly. Values already recommended (not invented here) in `docs/phase9_decision_resolution.md` §2. |
| Freshness tier weights | monotonically decreasing placeholders | module constant in `services/freshness.py` | Same reasoning; exact numbers are explicitly PRODUCT CONFIGURATION per Contract §5.2/§22, not derivable from the Contract or repository — chosen here only as a safe, ordered starting point, not a product decision this plan is authorized to finalize. |
| `reliability_score` null default | `0.5` (midpoint of `[0.0, 1.0]`) | module constant in `services/triage.py` | Directly matches Contract §6 rule 4's own worked example ("e.g. the midpoint of the configured range") — not an invented value. |
| Freshness+Authority → `TaskPriority` thresholds | explicit numeric cutoffs over a weighted-sum combined score | module constant in `services/triage.py` | Same reasoning as tier weights — PRODUCT CONFIGURATION per §22, given a safe, explicit, ordinal-mapping-compliant starting point rather than left unimplemented. |

This split (`Settings` for the one operationally/safety-relevant value; module constants for pure
algorithm tuning) is the smallest existing-pattern-compatible choice available, not a new
configuration mechanism — no third option (a database-backed config table, a feature-flag service,
a YAML policy file) is introduced, since none is needed and Contract P8/§20 forbid new persistence
in any case.

---

## Implementation Questions

None. Every choice this plan had to make beyond the Contract's own explicit rules (file layout,
value-object representation, exact output field names, config-mechanism placement, test-file
splitting) was resolvable from an existing, directly-analogous repository pattern
(`services/collector.py`, `capabilities/scoring_capability.py`, `core/config.py`'s existing field
mix, `tests/test_validate_architecture.py`'s existing test shapes) without inventing a new product
or architecture decision. No genuine ambiguity requiring the user's judgment was found.

---

## Final Report

**Milestone count**: 8 (M0–M7).

**Milestone titles**:
1. M0 — Architecture Validator Extension
2. M1 — Deterministic Triage Policy (Freshness + Triage)
3. M2 — Atomic Claim + Stale-Recovery Primitives
4. M3 — Triage Orchestration Service + Script Entry Point
5. M4 — `ResearchCapability`
6. M5 — `IntelligenceCapability`
7. M6 — Registration / Boot Wiring
8. M7 — Integration Proof + Cross-Cutting Regression

**Why the ordering is dependency-correct**: M0 precedes everything (cheap, no functional
dependency, mirrors Phase 8's own precedent, and the task's explicit "schedule validator changes
early" instruction). M1/M2 are mutually independent pure-policy/DB-primitive foundations, sequenced
before M3 because M3 is their first and only consumer. M4/M5/M6 form an entirely separate subsystem
(the Capability layer) with no code dependency on M1-M3, sequenced afterward to mirror the
Contract's own pipeline order and to build the highest-scrutiny concurrency mechanism first; M5's
production code depends on M4 only by convention (build-one-Capability-at-a-time, matching Phase 8's
own practice, and forbidden from importing it directly by §9.1 regardless), though M5's *test suite*
does import M4's shared `tests/fakes/research_output.py` fixture by design (§17). M6 requires both
M4 and M5 to exist (registers both). M7 requires M6 (needs both
Capabilities resolvable via the real registry) and functions as the final, whole-repository
regression gate.

**Unresolved implementation questions**: none (see "Implementation Questions" above).

**Revision note**: this document was revised once, in response to
`docs/phase9_implementation_planning_audit.md`'s two MAJOR findings (M3's transaction/commit/rollback
discipline, now made explicit via the Phase A/Phase B model in M3; `stale_processing_threshold_seconds`'s
missing positivity validation, now enforced via `Field(gt=0)` in M2) and five MINOR findings (M7's
synthetic `WorkflowType` reuse now named explicitly as `DAILY_DIGEST`; the Research→Intelligence
output-shape link now mechanically owned by `tests/fakes/research_output.py`; the two-connection test
helper now explicitly placed locally, not in `tests/conftest.py`; M0's validator rules reviewed and
one simplified (blanket `capabilities.` prefix) with none removed, since all three remain genuinely
necessary; M1 gained an explicit zero-age Freshness boundary test). The two OBSERVATION-level items
are recorded in §4 above without adding scope. Milestone count remains 8; sequencing is unchanged
except for one clarification (M5's tests, not its production code, now explicitly depend on M4's
shared fixture); no new functional scope, migration, `WorkflowRunner` redesign, scheduler, or
`FAILED`/`COMPLETED` lifecycle fix was introduced.

**Git status/diff scope for this revision turn**: only `docs/phase9_research_intelligence_planning.md`
was modified (`git status --porcelain` confirmed). No production code, test, migration, or prior
Phase 9 document (including the Contract and the planning audit itself) was modified — `git diff
--stat` against every other tracked/untracked path is empty. M0 was not implemented.

---

**PHASE 9 PLANNING REVISION COMPLETE — READY FOR RE-AUDIT**
