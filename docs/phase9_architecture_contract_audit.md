# Phase 9 Architecture Contract — Final Adversarial Audit

**Status: audit document. NOT a specification. NOT binding.** This document audits
`docs/phase9_research_intelligence_architecture_contract.md` as untrusted, against frozen
Phase 6–8 architecture, the current repository, and the four prior Phase 9 documents. It does not
modify the Contract or any prior document. Every finding below was re-verified against the actual
repository during this audit, including execution of a small Python snippet to empirically confirm
one finding (§7) rather than reasoning about it abstractly.

---

## 1. Executive Summary

The Contract's core boundary is sound and internally consistent on every major axis this audit
tested: ownership, workflow compatibility, capability boundaries, and scope discipline all hold.
No CRITICAL finding was produced — nothing makes the Contract impossible to implement or
contradicts frozen architecture.

Three genuine MAJOR findings were found, none previously disclosed by the Contract or any prior
Phase 9 document:

1. **`WorkflowRunner` has no per-step commit** — traced precisely (`workflows/runner.py:123,194-195,284-285`
   are the only three commit points in the file). If a process crashes between `research` and
   `intelligence` steps *within one `run()` call*, Research's `CapabilityResult` is lost entirely
   — it exists only in a local Python variable until the whole step loop finishes or fails. The
   Contract's §9.1/§14 describe the `step_results` handoff as ready-to-use without disclosing this
   is only true for a single, uninterrupted `run()` invocation.
2. **`TaskPriority` inherits `str`'s alphabetical comparison**, empirically confirmed:
   `TaskPriority.S < TaskPriority.A` is `False`; `sorted([S,A,B,C])` yields `[A, B, C, S]`. This
   accidentally puts `S` "last" (highest) correctly, but silently inverts the intended
   `docs/05 §11` urgency order for `A`/`B`/`C`. The Contract nowhere warns against comparing
   `TaskPriority` values with `<`/`>`/`sorted()`/`min()`.
3. **The `NewsEvent.status` transition's required implementation shape (an atomic, conditional
   `UPDATE ... WHERE status = 'NEW'`, not a read-then-write) is not actually specified in the
   Contract text**, despite being reasoned through during drafting. Without it, even the
   Contract's own "single-in-flight orchestrator" invariant is weaker than intended.

All three have concrete, non-migration corrections, given below (§22).

---

## 2. Contract vs Frozen Architecture

Checked against `docs/phase6_architecture_contract.md`, `docs/phase7_architecture_contract.md`,
`docs/phase8_capability_contract.md`, and the current repository — no contradiction found.

- §11's claim that Research/Intelligence "MUST obey `docs/phase8_capability_contract.md` in full"
  is accurate: both remain `(gateway, prompt_repository)`-only constructions (Phase 8 §4.2), use
  the centralized `call_generate()` mechanism unchanged, and introduce no new error/retry rule.
- §9.1's citation of Phase 6 P4 ("`Capability` → another `Capability` — FORBIDDEN") is accurate,
  re-confirmed against `docs/phase8_capability_contract.md` §2's forbidden-edges table.
- §17's forbidden-edge table for Capabilities matches the *already-existing* mechanically-enforced
  `capability-isolation` rule in `scripts/validate_architecture.py` (M0's exclusion list already
  covers any new file under `capabilities/`) — confirmed, no new validator work is actually needed
  for the Capability half of §17, only for Triage/Orchestrator (§15 below).
- No Phase 5/6/7/8 file is referenced as modified anywhere in the Contract — confirmed by
  re-reading every citation; all are read-only references.

---

## 3. Triage Ownership

Re-verified against §2.1–§2.5 and §7: one clear owner per responsibility.

| Responsibility | Owner (per Contract) | Ambiguity found? |
|---|---|---|
| Select eligible `NEW` events | Orchestrator (§7.2.1) | None |
| Load `NewsSource` data | Orchestrator (§7.2.2) | None |
| Evaluate Triage | Triage itself, called by Orchestrator (§7.3) | None |
| Create `EditorialTask` | Orchestrator, via unmodified `create_task()` (§7.3) | None |
| Transition `NewsEvent.status` | Orchestrator exclusively (§7.3, mirrors `WorkflowRunner`'s sole-owner precedent for `EditorialTask.status`) | None |
| Start/enqueue later workflow work | `WorkflowRunner`, unchanged (§0, §13) | None |

Triage's purity (§2.2 — no DB, no side effects) and the Orchestrator's thinness (§7.1's explicit
`scripts/run_collector.py` precedent) both hold under inspection. No second orchestration
framework is introduced — §7.2 explicitly forbids the Orchestrator from becoming "a second
`WorkflowRunner`." **No MAJOR ambiguity found in this section.**

---

## 4. Idempotency / Concurrency

Re-traced `services/workflow_service.py` line by line, not assumed from memory.

1. **Can two concurrent orchestrator invocations both observe the same `NewsEvent` as `NEW`?**
   Yes — nothing in the Contract's described flow claims a locking `SELECT` for the initial
   "find eligible events" query, and none is specified.
2. **Can both call `create_task()` before either status transition?** Yes, given the Contract's
   own chosen ordering (§7.5 rule 1: `create_task()` before status transition) — this ordering
   removes the one step (an early atomic claim) that could have prevented this.
3. **Is `DuplicateActiveTaskError` guaranteed to fire under that race?** **No.**
   `_find_active_task()` (`services/workflow_service.py:89-106`) is a plain `SELECT`, not
   `SELECT ... FOR UPDATE`. Two concurrent calls can both execute this `SELECT` and both see "no
   active task" before either commits its own `INSERT`.
4. **Is the duplicate-active-task check atomic?** No — confirmed, it is a classic check-then-act
   (TOCTOU) pattern.
5. **Is `workflow_type` actually queryable in a reliable unique key?** No — it lives inside
   `EditorialTask.workflow` (JSON), matched in Python (`services/workflow_service.py:104`), not a
   real column; no unique index can target it without a schema change.
6. **Could duplicate `EditorialTask`s still be created?** **Yes, under genuine concurrent
   execution** — this is exactly what the Contract's §7.5 already discloses ("true atomicity...
   cannot be guaranteed by the current schema"), re-confirmed here as accurate, not overstated.
7. **Could one task be created while `NewsEvent` remains `NEW`?** Yes, transiently — if the
   process crashes after `create_task()` succeeds but before the status transition commits. The
   Contract's §7.5 rule 3 correctly identifies this as self-healing on the next pass (via
   `DuplicateActiveTaskError`, rule 2).
8. **Could `EventStatus` become `PROCESSING` without a valid task?** Not under the Contract's
   chosen ordering (create-then-transition) — this specific hazard is the one the Contract's
   ordering choice was explicitly designed to prevent, and does prevent, correctly.
9. **What happens on retry after partial failure?** Handled by §7.5 rules 1–3, correctly, for the
   single-orchestrator-instance case.
10. **Is "do not run concurrently" a sufficient architectural invariant, or merely an operational
    assumption?** **Merely an operational assumption, as stated.** Nothing in the Contract gives
    this invariant a mechanical enforcement point (no lock, no singleton-process guarantee, no
    code-level check). This is disclosed honestly (§7.5 calls it a "requirement... enforced at the
    scheduling/invocation level, not the database level") but is a real weakness worth
    strengthening — see finding below.

**Verdict for this section: SAFE ENOUGH FOR PHASE 9's own defined scope** (§7.4 explicitly defers
production scheduling, so genuine concurrent invocation is unlikely in Phase 9's actual operating
envelope), **but the invariant itself is weaker than it needs to be, and a stronger non-migration
guarantee is available and should be adopted (§22).**

**Stronger non-migration invariant available (new finding, not in the Contract)**: the Orchestrator
MAY acquire a row-level lock on each candidate `NewsEvent` via `SELECT ... FOR UPDATE` *within the
same session/transaction it later passes to `create_task()`*. Since `create_task()` accepts the
caller's `session` and only commits once, internally (`services/workflow_service.py:71`), holding
the lock from the initial `SELECT` through that commit serializes two concurrent orchestrator
instances against the same `NewsEvent` row — the second instance blocks until the first's
transaction commits, at which point `_find_active_task()` will correctly see the just-created task
and raise `DuplicateActiveTaskError`. This requires no schema change, only a specific query clause
and transaction-boundary discipline. The Contract does not currently mention this option.

---

## 5. Failure Ordering

All six sequences the audit requires, checked against §7.5/§18:

- **A. `create_task` succeeds → status transition succeeds.** Normal path — correctly defined.
- **B. `create_task` succeeds → status transition fails.** §7.5 rule 3 — self-healing via
  `DuplicateActiveTaskError` on the next pass. Correctly defined, but see the finding below: rule 3
  assumes the *next pass* correctly identifies which `NewsEvent` needs only a status fix, not a new
  task — the Contract does not specify how the orchestrator distinguishes "still `NEW`, needs a
  task" from "still `NEW`, already has a task from a prior partial failure" in its normal *selection
  query* (which only filters on `status == NEW`). Practically, this works because `create_task()`
  itself will raise `DuplicateActiveTaskError` when re-attempted (rule 2 handles it) — but the
  Contract should say explicitly that the orchestrator's selection query alone is not sufficient to
  detect this case; the recovery only works because of the specific `DuplicateActiveTaskError`
  handling downstream, not because the event was pre-identified as a partial failure. **MINOR**
  wording precision gap, not a functional bug.
- **C. `create_task` fails → status transition must not happen.** §7.5 rule 1 — correctly, plainly
  stated.
- **D. `DuplicateActiveTaskError` → what exact state must be checked before treating as
  self-healing?** The Contract's rule 2 does not specify that the orchestrator should verify the
  *existing* active task is actually the one Triage would have created (same event, same
  `NEWS_ANALYSIS` workflow type) before "self-healing" the status. In practice this is
  automatically true (the error is only raised for exactly that `(event_id, workflow_type)` pair,
  per `_find_active_task`'s own filter), so this is not a real ambiguity, but the Contract's prose
  does not spell out *why* it's safe. **MINOR.**
- **E. Orchestrator crashes between task creation and status update.** = Sequence B, already
  covered.
- **F. Rerun after partial completion.** Covered by rules 2–3, correctly, for the orchestrator's own
  partial-failure case. **Not covered**: a rerun after a `WorkflowRunner`-level partial failure
  (§7 finding, different from the orchestrator's own partial failure) — see §14 below, this is a
  distinct gap from the orchestrator's failure semantics.

**No orphan tasks, no permanently-`NEW`-with-active-task, no stuck states found in the
Orchestrator's own failure semantics** — the one genuine "stuck state" risk (`PROCESSING` with no
active task, under true concurrency) is already disclosed in §7.5 as an accepted limitation of the
chosen ordering, not hidden.

---

## 6. EventStatus Semantics

Re-verified: `EventStatus` = `NEW`/`PROCESSING`/`ANALYZED`/`REJECTED`/`ARCHIVED`
(`database/models/news_event.py:26-33`), and `docs/08_Database_Schema_Data_Models.md` §8 lists the
same five values with no further elaboration of their intended distinctions
(`docs/08_Database_Schema_Data_Models.md:339-351`). Grep confirms zero writers of any value other
than `NEW` in the current codebase.

`NEW`→`PROCESSING` for "triaged and task-created" is a **reasonable, low-risk inference** from the
enum's apparent design intent, not a documented requirement — no existing code assumes `PROCESSING`
means anything else, so there is no conflict.

**Gap, not previously flagged**: the Contract never states who (if anyone) transitions
`PROCESSING`→`ANALYZED`, or whether Phase 9 leaves `NewsEvent.status` permanently at `PROCESSING`.
This is **consistent, not broken**, given §13's own finding that no Phase-9-created `EditorialTask`
can ever reach `TaskStatus.COMPLETED` (it always fails at `engagement_analysis`) — so `ANALYZED`
is correctly never reached in Phase 9's own operating envelope. **OBSERVATION**, worth one
clarifying sentence in a future revision, not a blocking gap.

---

## 7. Persistence / Crash-Recovery Audit (elevated ahead of its numbered position, per its
severity)

**This is the audit's most significant finding.** Traced every commit point in
`workflows/runner.py`:

```
workflows/runner.py:123   task.status = RUNNING; commit()      -- before any step runs
workflows/runner.py:194-195  (end of _execute_steps, success)  -- after ALL steps finish
workflows/runner.py:284-285  (inside _fail())                  -- on step failure
```

**There is no commit between individual steps inside `_execute_steps`'s loop.** `step_results:
list[WorkflowStepResult]` (line 156) is a local Python variable, appended to across the loop
(line 177, inside `_run_step`'s caller), and only written to `task.workflow` / committed once the
*entire* loop finishes or a step fails.

**Consequence, verified, not hypothetical**: if a process crashes after the `research` step
succeeds but before the `intelligence` step completes — within the *same* `WorkflowRunner.run()`
call — Research's `CapabilityResult` is **never persisted**. It existed only in that
now-dead process's memory. `EditorialTask.status` remains `RUNNING` (the last committed value,
from line 123), and `EditorialTask.workflow` is whatever it was *before this run started* — it
does not reflect Research having run at all. A subsequent call to `WorkflowRunner.run()` for that
same task would raise `TaskAlreadyRunningError` (line 114-115) — it cannot even be retried without
manual intervention to reset `status` back to `CREATED`, since nothing in the current
`WorkflowRunner`/`workflow_service` API resets a stuck `RUNNING` task.

**Is this a NEW Phase 9 defect, or pre-existing?** Pre-existing — this is a general characteristic
of `WorkflowRunner`'s design (Phase 5, frozen), true for *any* multi-step `WorkflowDefinition`,
including the already-frozen `NEWS_ANALYSIS`/`CONTENT_GENERATION`. **What Phase 9 changes is that
this gap starts to matter**: every prior exercise of `WorkflowRunner` (Phase 5's own
`DeterministicPlaceholderExecutor`, Phase 8's synthetic single-step test workflows) either carried
no real data between steps or had only one step, so this gap was invisible. Phase 9's own proposed
synthetic two-step integration proof (§13 of the Contract) is the **first** scenario where a
process crash between two steps would lose real, meaningful data.

**Does this make the Research→Intelligence handoff "impossible" (CRITICAL, per the audit's own
bar)?** No — it works correctly, exactly as the Contract describes, for any *uninterrupted*
`run()` call, which is what every test the Contract's §13/§16 proposes will actually exercise (a
test process does not crash mid-assertion). **Classified MAJOR, not CRITICAL**: a real,
previously-undisclosed gap in the Contract's own persistence story (§14 says nothing about
crash recovery at all), not a defect that blocks implementation.

**Required correction**: §14 (and/or §9.1) should add an explicit sentence disclosing that
`step_results`-based handoff is not crash-safe across a process restart *within* one `run()` call
— consistent with how §7.5 already discloses the orchestrator's own, different concurrency
limitation. This is a disclosure fix, not an architecture fix (the underlying `WorkflowRunner`
behavior is frozen Phase 5, out of Phase 9's authority to change).

---

## 8. TaskPriority Semantics

**Empirically verified** (Python executed during this audit, not reasoned about abstractly):

```python
from database.models.editorial_task import TaskPriority
TaskPriority.S < TaskPriority.A   # => False
sorted([TaskPriority.S, TaskPriority.A, TaskPriority.B, TaskPriority.C])
# => [TaskPriority.A, TaskPriority.B, TaskPriority.C, TaskPriority.S]
```

`TaskPriority(str, enum.Enum)` inherits `str`'s lexicographic comparison
(`database/models/editorial_task.py:13`; MRO confirmed:
`(TaskPriority, str, Enum, object)`). Alphabetically, `A < B < C < S`. Editorially, per
`docs/05_Scoring_Ranking_Specification.md` §11, urgency descends `S > A > B > C` — i.e., ascending
urgency is `C < B < A < S`. **These orders agree only at the very top** (`S` happens to be both
alphabetically last and editorially highest) **and are inverted for `A`/`B`/`C`.**

**No ordering is defined anywhere in the codebase today** — grep confirms `TaskPriority` is never
compared with `<`/`>`/`sorted()`/`min()`/`max()` anywhere in current production or test code; this
hazard is latent, not yet triggered.

**The Contract does not warn against this.** §3/§4 describe Triage "mapping" Freshness+Authority to
a `TaskPriority`, which inherently requires *some* notion of relative ordering (a higher combined
score should map to a higher-urgency tier) — a natural, easy implementation mistake would be to
build this mapping using Python's native comparison or `sorted()`/`max()` on `TaskPriority` values
directly, silently producing an inverted `A`/`B`/`C` assignment that would be very hard to catch in
casual testing (since `S` — the most visually distinctive case — would still work correctly).

**Classified MAJOR.** Required correction (§22): the Contract must state explicitly that
`TaskPriority` MUST NOT be compared via native `<`/`>`/`sorted()`/`min()`/`max()`; any
priority-mapping logic MUST use an explicit ordinal mapping (e.g. a dict assigning each tier a
rank), never rely on the enum's inherited string ordering.

---

## 9. Triage Signal / Freshness Audit

Re-verified directly, not trusted from the Contract's own citations:

```python
NewsEvent.published_at: Mapped[datetime | None]        # nullable=True (implicit, per | None)
NewsEvent.collected_at: Mapped[datetime]                # server_default=func.now(), not null
NewsSource.reliability_score: Mapped[float | None]      # mapped_column(Float, nullable=True)
```

All three match the Contract's §3/§6 citations exactly.

**Edge cases**:
- `published_at` null: §5.1 rule 3 — handled, `collected_at` fallback, flagged.
- `collected_at` null: cannot occur (`server_default`, non-nullable) — the Contract correctly
  treats this as impossible rather than defending against it defensively (appropriately minimal).
- Naive vs. timezone-aware datetime: both columns are `DateTime(timezone=True)` at the DB level —
  confirmed, §5.1 rule 6 correctly requires timezone-aware comparison.
- Future timestamps: §5.1 rule 4 — clamped to zero age, handled.
- Malformed timestamps: not directly applicable — SQLAlchemy/Postgres reject genuinely malformed
  values at the type level before a row could ever be persisted; this is not a Triage-level
  concern.
- `reliability_score` null: §6 rule 4 — a defined, deterministic default is required (exact value
  left as configuration). Handled, correctly.
- **`reliability_score` out of `[0.0, 1.0]` range** — **new finding, not addressed by the
  Contract**. The DB column has no `CheckConstraint` (confirmed: `mapped_column(Float,
  nullable=True)`, no bounds). Only the *import-time* Pydantic schemas
  (`SourceImportItem`/`SourceDefinition`, both `Field(ge=0.0, le=1.0)`) enforce the range, and only
  for values that flow through those specific import paths. A manually-edited or
  future-import-path-bypassing row could in principle hold an out-of-range value. **MINOR** — low
  current risk (all populated sources today go through the bounded import schemas), but the
  Contract should specify defensive clamping behavior for completeness, matching how it already
  handles the null case.

---

## 10. Triage Determinism

§5.1 rule 1 explicitly requires `reference_now` as an injectable parameter, prohibiting internal
wall-clock reads — confirmed sufficient and explicit; no ambiguity found. §3's closed signal list
plus §6's default-value requirement for null reliability together make every required input
explicit. Policy/config versioning is correctly left as non-mandatory metadata (§16/§22 — not
over-designed, matching the audit's own "do not over-design" instruction). **No finding.**

---

## 11. ResearchCapability Audit

§8's table and its "binding scope clarification" paragraph were checked against Phase 8's frozen
mechanics and the current absence of any tool-integration infrastructure (re-confirmed: Phase 8's
contract permanently defers tool integration for this delivery; no partial implementation exists
anywhere in `capabilities/` or `integrations/`). The Contract correctly:
- Restricts construction to `(gateway, prompt_repository)` only.
- Names the forbidden responsibilities precisely (external verification, browsing, agent loops,
  importance judgment, calling another Capability, mutable state).
- Explicitly names the scope-honesty correction ("Research" = fact extraction, not verification) —
  this directly prevents the misleading-naming risk the audit asked about.

**No finding.** The naming clarification already present is sufficient.

---

## 12. IntelligenceCapability Audit

§9's table is similarly precise. Checked specifically:
- Does not duplicate Research's output — §9's "MUST NOT" column explicitly forbids re-extracting
  facts from raw content.
- Does not become Final Ranking, Engagement Analysis, or a Triage-adjacent priority decision — all
  three explicitly forbidden in §9's table.
- Does not directly import/call `ResearchCapability` — §9.1 explicitly forbids this, correctly
  citing Phase 6 P4.

---

## 13. Research→Intelligence Handoff

**This is the audit's other most load-bearing check, alongside §7.** The Contract's §9.1 claims
correctly, for the *uninterrupted-execution* case: `CapabilityContext.business.workflow_state.step_results`
(`schemas/capability.py`'s `WorkflowExecutionStateSnapshot`) is populated by
`CapabilityExecutor._build_context()` from `state.step_results` — which, within one
`_execute_steps` loop, does contain Research's completed `SUCCESS` result by the time Intelligence's
step executes (verified: `step_results.append(...)` happens before the loop moves to the next
step, `workflows/runner.py:252-257`, and `_build_context()` reads from exactly this accumulated
list).

**Verified**: this mechanism does NOT depend on which `WorkflowDefinition` drives execution — a
synthetic two-step test definition exercises the identical code path as the real
`NEWS_ANALYSIS` would. The Contract's §13 claim that a synthetic definition genuinely proves this
mechanism is **accurate**, re-confirmed by tracing the generic (not `NEWS_ANALYSIS`-specific) code
in `capabilities/executor.py`/`workflows/runner.py`.

**Not "impossible" — but not crash-safe**, per §7's finding above. This section's verdict is:
**the handoff is real and correctly described for the case the Contract's own tests will exercise;
the crash-recovery caveat from §7 applies here specifically and should be cross-referenced from
this exact claim in a future revision.**

---

## 14. Registration / Workflow Compatibility

§12/§13 re-verified against the actual Phase 8 M7 precedent (`capabilities/registry.py`'s existing
two-line-per-Capability pattern) — confirmed the Contract describes it accurately. §13's central
claim (`required: bool = True` default, all four `NEWS_ANALYSIS` steps unmodified, the workflow
will still fail at `engagement_analysis` after Phase 9) was independently re-verified during this
audit by re-reading `schemas/workflow.py:52` and `workflows/definitions/news_analysis.py` — accurate,
unchanged from when the Contract was drafted. No registration collision with `ScoringCapability`/
`QualityCapability` (different names, `"research"`/`"intelligence"` vs `"scoring"`/`"quality"`).
Registering Research/Intelligence does **not** imply `engagement_analysis` gets registered — the
Contract states this explicitly (§12, §13, §21 rule 8). **No finding.**

---

## 15. Forbidden Dependency Audit

§17's table checked for loopholes:
- Triage importing `LLMGateway` indirectly: not possible through any documented dependency, since
  Triage's own allowed inputs (§3) are plain scalar values passed by its caller, not live objects
  from `integrations.llm_gateway`.
- A `services/` module importing a concrete `PromptRepository`: not applicable — Triage/Orchestrator
  have no `PromptRepository` dependency in this Contract at all (only Capabilities do).
- Orchestrator importing Capability implementations: explicitly forbidden (§2.3's ownership row,
  §17).
- Capability importing `WorkflowService`: not explicitly listed in §17's Capability row, but
  already covered by the *existing*, mechanically-enforced `capability-isolation` rule's
  `workflows` forbidden prefix (confirmed in `scripts/validate_architecture.py`, M0) — no gap.
- Direct DB session inside a Capability: already covered by the same existing rule
  (`database.session`/`sqlalchemy` forbidden prefixes).
- Provider adapter leakage: covered by the existing `provider-sdk-confinement` rule, which applies
  repo-wide, not just to `capabilities/`.

**Mechanical enforceability, checked precisely**: the Capability half of §17 is *already*
enforceable with zero new validator work (M0's exclusion-list rule automatically covers any new
file under `capabilities/`). **The Triage/Orchestrator half of §17 is not yet enforceable** —
there is no existing per-file or per-directory rule in `scripts/validate_architecture.py` covering
arbitrary new files under `services/` (the existing rules are all named per-file:
`budget-guard-isolation`, `cost-tracker-isolation`, etc.). The Contract already states this table
is "to be mechanically encoded... by a future implementation milestone" (§17's own header) — this
is correctly disclosed, not hidden. **OBSERVATION**, not a gap requiring correction now.

---

## 16. Call Semantics / Cost

§10/§16 re-checked for accidental over-freezing. §10 explicitly states the Contract "does not
mandate that every accepted `NewsEvent` MUST always incur exactly two sequential Gateway calls" and
§11 separately acknowledges the optional §10 (Phase 8) correction-retry rule "MAY" apply to either
Capability. **These two statements are consistent with each other but never explicitly connected
in one sentence** — a reader of §10 alone might not realize §11 already implies a single Capability
execution can itself cause more than one Gateway call (via retry), independent of the
Research-vs-Intelligence "two Capabilities" framing. **MINOR** wording-clarity gap: a single
sentence in §10 explicitly distinguishing "Capability execution count" from "Gateway call count"
would close this.

---

## 17. Configuration vs Architecture

Re-checked §5.2, §6 rule 4 (only the *default's existence* is frozen, not its value), and §22's
table. Confirmed correctly separated: tier boundaries/weights, threshold mappings, and the
reliability-null default value are all correctly left as configuration (§5.2, §22), while the
allowed-signal-category closure (§3), the no-hard-drop rule (§4), `TaskPriority` reuse (§3), and
the Opportunity Score prohibition (§3, §20) are all correctly frozen. **Checked whether
configurable policy could silently introduce a forbidden signal**: §3's closed list is stated as
requiring "a Contract amendment" to extend — this is the correct guard; a future config change
alone cannot smuggle in a new signal without also violating this Contract's own text. **No
finding.**

---

## 18. Scope Leakage

Re-scanned the full Contract text for every item on the audit's checklist: clustering, embeddings,
vector DB, engagement collection, final ranking, Opportunity Score, source-reputation learning,
browsing tools, autonomous agents, persistent intelligence graph, workflow redesign, scheduler
redesign. Every one of these is explicitly named in §20 (Explicit Non-Goals) as excluded, and no
other section of the Contract implicitly requires any of them to function. **No finding.**

---

## 19. Implementability / Internal Consistency

**Could two competent developers independently implement this Contract and produce compatible
systems?** Yes, for the large majority of it — §3/§4/§8/§9/§11/§12/§13/§14/§20 are all precise
enough. **Two rules are currently too vague to guarantee compatible implementations**:
- The exact mechanics of the `NewsEvent.status` transition (§7.2/§7.5) — "transitions... to
  `EventStatus.PROCESSING`" does not specify *how* (atomic conditional `UPDATE` vs. read-then-write),
  and two developers could reasonably implement either, with materially different safety properties
  under concurrency. **MAJOR** — this is the third headline finding (§22).
- `TaskPriority` comparison/mapping (§8 above) — without an explicit prohibition, two developers
  could plausibly implement the Freshness→priority mapping differently (one using an explicit
  ordinal table, one naively using `sorted()`), producing genuinely incompatible, silently-wrong
  systems for the `A`/`B`/`C` tiers specifically.

No other MUST/MUST NOT rule in the Contract was found to be ambiguous enough to produce
incompatible implementations.

---

## 20. Internal Consistency

Checked every example pairing the task lists:

- **Pure Triage vs. logging side effects**: not a contradiction — §2.2 states Triage itself has no
  side effects and returns a value; §15 requires the *caller* (the Orchestrator, or whichever
  component receives Triage's output) to log it. Triage does not log itself. Consistent.
- **No new persistence vs. required persistent decision state**: not a contradiction — §3/§14
  explicitly restrict Triage's explanation to logs only, never a persisted row. Consistent.
- **No hard drop vs. SKIP semantics**: not a contradiction — the Contract never introduces a SKIP
  state; §4 explicitly rejects that vocabulary. Consistent.
- **No full workflow completion vs. E2E wording**: checked explicitly (§21 audit item below) — no
  instance of misleading "end-to-end" wording was found; §13's language is precise throughout
  ("integration proof," never "workflow completion").
- **Separate Capabilities vs. required single-call optimization**: not a contradiction — §10
  explicitly declines to freeze call cardinality while keeping the Capabilities separate; these are
  orthogonal, not opposed.
- **No workflow redesign vs. new orchestration responsibility**: not a contradiction — the
  Orchestrator (§7) is explicitly outside `workflows/` entirely, gating `EditorialTask` creation,
  never touching `WorkflowRunner`/`WorkflowRegistry`. Consistent, and explicitly checked against
  P7/P10 (§1).

**No contradiction found within the Contract's own text.** The three MAJOR findings in this audit
are all *omissions* (missing disclosure or missing precision), not internal contradictions.

---

## 21. Workflow Claim Boundary (folded from Audit 11)

Searched the full Contract text for wording that could imply `NEWS_ANALYSIS` completion,
end-to-end delivery, `engagement_analysis` existing, or final scoring being complete. **None
found.** §0, §13, §20, and §21 rule 8 all state the boundary precisely and consistently:
Triage + Research + Intelligence, `Capability`/`CapabilityExecutor`-level proof only, explicit
prohibition on claiming `COMPLETED`. This is the one area where the Contract is unambiguously
strict, with no softening language anywhere.

---

## 22. Findings by Severity and Required Contract Corrections

**CRITICAL**: None.

**MAJOR**:
1. **§14 (and §9.1) do not disclose that `step_results`-based Research→Intelligence handoff is not
   crash-safe across a process restart within one `WorkflowRunner.run()` call** (§7 of this audit).
   *Correction*: add one explicit sentence to §14 (or a new §14.1) stating this limitation, citing
   `workflows/runner.py`'s single-commit-per-run behavior, and noting it is a pre-existing Phase 5
   characteristic Phase 9 does not introduce but is the first to make consequential.
2. **§3/§4 do not warn against native comparison of `TaskPriority`** (§8 of this audit, empirically
   verified). *Correction*: add one sentence to §3 or §21 (Canonical Rules) stating `TaskPriority`
   MUST NOT be compared via `<`/`>`/`sorted()`/`min()`/`max()`; any ordering logic MUST use an
   explicit ordinal mapping.
3. **§7.2/§7.5 do not specify that the `NewsEvent.status` `NEW`→`PROCESSING` transition must be an
   atomic, conditional `UPDATE ... WHERE status = 'NEW'`, not a read-then-write** (§4/§19 of this
   audit). *Correction*: add this as an explicit implementation-shape requirement in §7.2 or §7.5,
   and additionally consider recommending the `SELECT ... FOR UPDATE` row-locking pattern (§4 of
   this audit) as a stronger, still-migration-free option for closing the duplicate-task race when
   the single-in-flight assumption is ever relaxed.

**MINOR**:
1. §7.5 rule 2's self-healing logic is correct but its precondition ("why this is safe") is not
   spelled out in prose (§5 of this audit).
2. §10/§11's distinction between "Capability execution count" and "Gateway call count" is
   consistent but never stated in one explicit sentence (§16 of this audit).
3. §6 does not specify defensive behavior for an out-of-`[0.0, 1.0]`-range `reliability_score`,
   though the DB column has no constraint preventing one (§9 of this audit).

**OBSERVATION**:
1. The Contract never states who (if anyone) transitions `PROCESSING`→`ANALYZED` — consistent
   with §13's own finding that no Phase-9-created task can reach `COMPLETED`, so this is benign
   (§6 of this audit).
2. §17's Triage/Orchestrator forbidden-edges are not yet mechanically enforceable (no generic
   `services/` validator rule exists) — already disclosed by the Contract itself, not hidden
   (§15 of this audit).

---

## 23. Scores

| Dimension | Score /10 | Basis |
|---|---|---|
| Frozen Architecture Compatibility | 10 | Zero contradictions found against Phase 6/7/8 or current code |
| Contract Internal Consistency | 9 | No true contradiction found (§20); docked only for the three MAJOR omissions being invisible cross-references rather than stated in one place |
| Triage Safety | 9 | Signal closure, no-hard-drop, and determinism are all solid; docked for the `TaskPriority` comparison hazard |
| Idempotency / Recovery Safety | 6 | Real, disclosed limitation (§4/§7.5) is honest but under-specified; the crash-recovery gap (§7) was entirely undisclosed until this audit |
| Capability Boundary Quality | 10 | §8/§9/§9.1/§11 are precise and verified accurate against real Phase 8 mechanics |
| Persistence Correctness | 7 | §14's mapping table is accurate for the steady-state case; docked for the undisclosed crash-recovery gap |
| Workflow Compatibility | 10 | §13's central claim independently re-verified, accurate, and the completion-boundary wording is unambiguous throughout (§21) |
| Scope Discipline | 10 | §18/§20 — no leakage found anywhere |
| Implementability | 7 | Two rules (status-transition mechanics, priority comparison) are currently too vague to guarantee compatible implementations (§19) |
| Contract Readiness | 7 | Sound boundary, real but narrow and fixable gaps; not yet safe to freeze without the three MAJOR corrections |

**Overall (evidence-weighted): 8.5/10.**

---

## 24. Final Verdict

**PHASE 9 CONTRACT NOT READY — CORRECTIONS REQUIRED**

No CRITICAL finding exists, and no finding requires reopening the boundary itself (Triage +
Research + Intelligence, `CapabilityExecutor`-level proof, no `NEWS_ANALYSIS` completion claim, no
new persistence) — that boundary remains correct and well-supported by the repository. But three
MAJOR findings — an undisclosed crash-recovery gap in the Research→Intelligence handoff, an
undisclosed and empirically-confirmed `TaskPriority` comparison hazard, and an under-specified
`NewsEvent.status` transition mechanism that weakens the Contract's own concurrency story — must be
corrected in the Contract's text before it is safe to treat as frozen. All three corrections are
small, targeted text additions to already-existing sections (§14, §3/§21, §7.2/§7.5
respectively), not a redesign, and none requires a migration or touches frozen Phase 5–8
architecture.
