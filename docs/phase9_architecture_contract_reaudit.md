# Phase 9 Architecture Contract — Re-Audit

**Status: audit document. NOT a specification. NOT binding.** This document re-audits the revised
`docs/phase9_research_intelligence_architecture_contract.md` (current, on-disk state, 935 lines)
against the three MAJOR findings of `docs/phase9_architecture_contract_audit.md`. It does not
modify the Contract or any other Phase 9 document. Every claim below was re-verified directly
against the current Contract text and the current repository during this audit (line numbers for
`workflows/runner.py`, `services/workflow_service.py`, `database/models/editorial_task.py`, and
`database/models/news_event.py` were re-grepped fresh, not trusted from the prior audit's or
Contract's citations), and `git status`/`git diff --stat` was used to confirm zero production code
was touched by the Phase 9 revision (only Contract and other Phase 9 doc files are untracked; every
frozen model, service, and workflow file is byte-identical to what the original audit inspected).

---

## 1. Executive Summary

All three prior MAJOR findings are **RESOLVED**. The crash/restart limitation is now explicitly
disclosed and cross-referenced from every place that relies on the `step_results` handoff. The
`TaskPriority` native-comparison hazard is now explicitly prohibited, with a mandated ordinal
mapping and a corresponding test requirement. The `NewsEvent.status` claim mechanism is now
specified as an atomic conditional `UPDATE ... WHERE status = 'NEW'` with a mandatory
affected-row-count check, ordered strictly before `create_task()` — closing the exact race the
original audit traced.

However, resolving finding 3 required introducing a **new mechanism** — the
`PROCESSING`-with-no-active-task recovery-candidate selection (§7.2, §7.5) — that the original
audit never reviewed, because it did not exist in the pre-revision Contract. This re-audit finds
that mechanism reintroduces, in a new and partially undisclosed form, the identical
`create_task()`/`_find_active_task()` TOCTOU race the original audit's §4 found and the revision
fixed for the primary claim path. This is a **new MAJOR finding**, not a failure to resolve any of
the original three. It is scoped narrowly (only affects `PROCESSING`+no-active-task events under
genuine concurrent orchestrator execution, itself deferred per §7.4) and has a small,
non-migration correction available (§8, below).

**No CRITICAL finding. No new contradiction with frozen Phase 5–8 architecture. The Phase 9
boundary itself is unchanged and remains sound.**

---

## 2. Crash/Restart Finding Re-Audit

Checklist against `docs/phase9_architecture_contract_audit.md` §7/§22 finding 1 and the Contract's
own required disclosure:

| # | Required claim | Present? | Location |
|---|---|---|---|
| 1 | `WorkflowRunner` persistence semantics are unchanged by Phase 9 | Yes | §14.1 point 1 |
| 2 | `step_results` handoff valid only within one uninterrupted `run()` call | Yes | §9.1 (new paragraph), §14.1 point 2 |
| 3 | Phase 9 MUST NOT claim durable recoverability of intermediate Research output | Yes | §14.1 point 3 |
| 4 | No new per-step persistence model/checkpoint/migration introduced | Yes | §14.1 point 4 |
| 5 | `CapabilityExecutor`-level and synthetic-workflow proofs remain sufficient | Yes | §14.1 point 5, cross-referenced from §13 |
| 6 | Full crash-safe multi-step recovery explicitly DEFERRED (not merely unimplemented) | Yes | §14.1 point 6, §20 item 18, §22 (new DEFERRED row) |
| 7 | A future durable-Research need must be addressed as a workflow-persistence concern, not by reinterpreting Capability semantics | Yes | §14.1 point 7 |

Re-verified directly against the repository, not trusted from the Contract's citations: grepped
`workflows/runner.py` fresh — `await session.commit()` occurs at exactly three points (lines 123,
195, 285), matching the Contract's §14.1 citation (`123`, `194-195`, `284-285`) and the original
audit's trace. `step_results.append(...)` (lines 177, 234, 242, 252) accumulates only in a local
Python list across `_execute_steps`'s loop, confirmed still true — this file is untouched by Phase
9 (confirmed via `git diff --stat workflows/runner.py`, zero output).

The disclosure is not confined to §14.1 in isolation — it is cross-referenced from every place the
original audit flagged as silently assuming crash-safety: §9.1 (the handoff mechanism itself), §13
(integration-proof section, explicitly states proofs "exercise a single, uninterrupted `run()`
call" and do not prove crash-safety), §16 (testing requirements, "no test simulates or claims to
prove crash/restart recovery"), §20 item 18 (non-goal), §21 rule 14 (canonical rule), §22 (DEFERRED
item), and §23 item 17 (acceptance-checklist self-check).

**Verdict: RESOLVED.**

---

## 3. TaskPriority Ordering Re-Audit

Checklist against `docs/phase9_architecture_contract_audit.md` §8/§22 finding 2:

| # | Required claim | Present? | Location |
|---|---|---|---|
| 1 | States the empirical inversion finding (`S < A` is `False`, `sorted()` yields `[A,B,C,S]`) | Yes | §3, "Ordering — binding, frozen" |
| 2 | Freezes the canonical business order `S > A > B > C` | Yes | §3 |
| 3 | Explicitly prohibits native `<`/`>`/`<=`/`>=` on `TaskPriority` | Yes | §3 |
| 4 | Explicitly prohibits `sorted()`/`min()`/`max()` on `TaskPriority` | Yes | §3 |
| 5 | Explicitly prohibits reliance on declaration order | Yes | §3 |
| 6 | Requires an explicit ordinal mapping for any comparison/ranking logic | Yes | §3 |
| 7 | Restated as a testing requirement, distinct from a mere text warning | Yes | §16: "MUST prove the canonical business priority order... using the explicit ordinal mapping directly — never by asserting on `sorted()`/`<`/`>`" |

Re-verified fresh: `database/models/editorial_task.py` — `class TaskPriority(str, enum.Enum)` at
line 13, members `S`/`A`/`B`/`C` at lines 16–19, unchanged from the original audit's citation
(confirmed via `git diff --stat`, zero output — this file is untouched by Phase 9). The Contract's
empirical claim (`TaskPriority.S < TaskPriority.A` is `False`) was independently re-verified as
correct by the original audit's own executed Python and is not re-executed here since the enum
definition is byte-identical; re-deriving the same result from an unchanged input would not add
information.

The rule is echoed consistently everywhere it needs to be: §16 (test requirement), §21 rule 13
(canonical rule), §23 item 18 (acceptance-checklist self-check). No place in the Contract was found
that implicitly relies on `TaskPriority`'s natural order — the one place that performs a
Freshness/Authority-to-priority mapping (§5.2, product configuration) is explicitly left
unspecified as to mechanism, and §3's prohibition applies to it the same as anywhere else.

**Verdict: RESOLVED.**

---

## 4. Atomic Claim/Concurrency Re-Audit

Re-answering the original audit's ten numbered questions (§4), plus one new question this revision
raises, against the current §7.2/§7.5 text:

1. **Can two concurrent orchestrator invocations both observe the same `NewsEvent` as `NEW` and
   both successfully claim it?** No. §7.2 step 1 mandates a single atomic conditional
   `UPDATE ... WHERE status = 'NEW'` (or equivalent database-enforced conditional write); of two
   concurrent attempts, at most one affects a row. The losing attempt affects zero rows and MUST be
   skipped, per §7.2/§7.5. This is now a real, unconditional, DB-level guarantee — re-verified as
   correct standard-SQL semantics for a single conditional `UPDATE` statement against one row.
2. **Can both instances call `create_task()` before either status transition, as the original
   Contract's ordering allowed?** No — this is precisely what was reordered. The claim (step 1) now
   happens strictly before `create_task()` (step 3); only the instance whose claim succeeds ever
   reaches `create_task()` for a given `NEW` event.
3. **Is `DuplicateActiveTaskError` now required to fire under the primary-path race?** Not
   applicable — the race it would have needed to catch cannot occur on the primary path anymore,
   because only one instance's claim can succeed, so only one instance ever calls `create_task()`
   for a given previously-`NEW` event.
4. **Is the duplicate-active-task check itself now atomic?** No — `_find_active_task()`
   (`services/workflow_service.py:89-106`, re-grepped fresh, unchanged) remains a plain `SELECT`,
   not `SELECT ... FOR UPDATE`. This is unchanged from the original audit's finding, but it no
   longer matters for the primary claim path, because the atomic claim in step 1 already prevents
   two instances from reaching `create_task()` concurrently for the same `NEW` event. It still
   matters for the recovery path — see §5 below.
5. **Is `workflow_type` queryable as a real unique key?** No — unchanged, still matched against the
   JSON `workflow` column in Python (`services/workflow_service.py:104`), re-confirmed. The
   Contract does not claim otherwise and does not need to, since it no longer relies on this check
   as the primary safety mechanism for the claim itself (§7.5's explicit distinction between
   "DB-level atomic guarantee" and "not DB-level, bounded and self-healing").
6. **Could duplicate `EditorialTask`s still be created on the primary path?** No — closed by the
   reordering. Could they still be created via the recovery path? Yes — see §5.
7. **Could a `NewsEvent` remain `NEW` while a task exists for it?** No — the claim commits status to
   `PROCESSING` before `create_task()` is even attempted; a `NEW` event by definition never has a
   task yet, and a claimed event is `PROCESSING` immediately.
8. **Could `EventStatus` become `PROCESSING` without a valid task?** Yes — explicitly disclosed as
   the one residual, bounded gap (§7.5): claim succeeds, `create_task()` subsequently fails. This is
   the correct, honestly-scoped residual the Contract's own text claims, not an overclaim.
9. **What happens on retry after partial failure?** §7.5's three-way outcome handling (success /
   `DuplicateActiveTaskError` / other exception) plus §7.2's recovery-candidate selection. Correctly
   specified for the described scenario — see §5 for a gap in the selection criterion itself.
10. **Is "do not run concurrently" still the primary safety mechanism, or has it been demoted as
    intended?** Correctly demoted. §7.5's explicit "distinction, binding" paragraph states the
    DB-level atomic claim is now primary and §7.4's scheduling deferral is "no longer... the sole or
    primary safety mechanism" — this directly answers and closes the original audit's question 10.
11. **(New question, raised by the revision itself) Does the newly-introduced recovery-candidate
    mechanism inherit an equivalent DB-level guarantee, or does it fall back to the same
    TOCTOU-vulnerable check the primary path just closed?** It falls back to the TOCTOU-vulnerable
    check. §7.2 states explicitly: for a recovery candidate, "no re-claim is attempted... the
    orchestrator proceeds directly to step 2" — i.e., straight to `create_task()`, with no
    equivalent atomic gate. See §5 for the full analysis.

**Verdict: RESOLVED for the primary `NEW`→`PROCESSING` claim path specifically** (this is exactly
what the three original MAJOR findings were about). **A new, narrower gap was found in the
recovery-candidate path this revision introduced — see §5.**

---

## 5. PROCESSING Recovery Candidate Audit

This mechanism did not exist in the Contract the original audit reviewed; it was added by this
revision specifically to close the residual gap the atomic claim itself creates (claim succeeds,
`create_task()` fails → `PROCESSING` with no task, needs a way back to `NEW`-equivalent eligibility
without literally reusing `NEW`). It must be audited fresh, adversarially, on its own terms.

**Mechanism, as specified (§7.2, §7.5)**: the orchestrator's eligible-event query additionally
selects any `NewsEvent` with `status == PROCESSING` and no active (`CREATED`/`RUNNING`)
`EditorialTask`, per `_find_active_task()`. For each such candidate, **no re-claim is attempted**
(§7.2: "it is not `NEW`; the orchestrator proceeds directly to step 2") — Triage runs, then
`create_task()` is called directly.

**Finding — two related problems, one already partially named by the Contract, one not named at
all:**

**(a) The disclosed "recovery-vs-recovery race" is described more safely than it actually is.**
§7.5 point 2 names this scenario directly: *"a narrower, lower-stakes race between two
recovery-path attempts for the same stuck event"* and classifies it as *"not a failure"* because
`DuplicateActiveTaskError` will fire and the orchestrator treats that as success. But whether
`DuplicateActiveTaskError` reliably fires under a true race is exactly the fact the original audit's
§4 question 3 established as **false**: `_find_active_task()` is a plain `SELECT`, and two
concurrent `create_task()` calls can both execute it and both see "no active task" before either
commits its own `INSERT`. Nothing in this revision changes that fact for the recovery path — it was
only closed for the primary path, by preventing two instances from ever reaching `create_task()`
concurrently for the same event via the atomic claim. The recovery path has no such gate. So under a
genuine race, **two `EditorialTask` rows can silently both be created** for the same recovery
candidate — not merely a `DuplicateActiveTaskError` that gets swallowed as benign, but an actual
duplicate, with neither call raising an error to signal it happened.

**(b) A broader, previously entirely undisclosed hazard: the recovery-candidate criterion cannot
distinguish "genuinely orphaned" from "currently mid-flight, still healthy."** Consider ordinary,
non-crashed concurrent execution of two orchestrator batch passes (still within Phase 9's own
scope — §7.4 defers *scheduling*, but does not forbid two passes from ever overlapping, and the
Contract's own §7.5 concurrency guarantee is framed as holding "unconditionally, regardless of
deployment or scheduling discipline," which invites exactly this scrutiny). Instance A claims a
`NewsEvent` (step 1, committed: `NEW`→`PROCESSING`) and is now between step 1 and step 3 — a real,
nonzero window while Triage runs and `create_task()` is being called. During precisely this window,
the event's state is indistinguishable from a genuinely-orphaned recovery candidate: `status ==
PROCESSING`, no active `EditorialTask` yet exists (A hasn't created it yet). If Instance B's
eligible-event query runs during this window, B will select this event as a "recovery candidate"
per §7.2's literal criterion and proceed directly to `create_task()` for it — racing A's own,
entirely healthy, in-progress `create_task()` call. This is not a double-failure edge case; it can
occur on **any** claim, any time a second orchestrator pass's query happens to run during the
narrow claim-to-create_task window of a first, perfectly healthy pass. §7.2's selection criterion
(`PROCESSING` + no active task) has no time/staleness component to exclude this case.

**Why this is a new MAJOR finding, not a restatement of an already-accepted limitation**: the
Contract explicitly frames the atomic claim as closing exactly this class of race ("no two
concurrent orchestrator executions can both successfully claim the same `NEW` `NewsEvent`... This
holds unconditionally," §7.5) and frames the residual gap it does accept as narrow and specifically
scoped to "the window between a successful claim and a successful `create_task()` call" for **one**
instance's own sequence, self-healing via recovery. It does not disclose that the recovery mechanism
meant to heal that narrow window is itself susceptible to the identical class of concurrent-duplicate
race the primary path was just fixed to prevent — nor that this susceptibility extends beyond actual
recovery scenarios to any concurrently-overlapping healthy pass.

**Concrete, non-migration correction available**: `NewsEvent.updated_at` already exists
(`database/models/news_event.py:65-67`, `DateTime(timezone=True), server_default=func.now(),
onupdate=func.now(), nullable=False`) — an existing, unused-for-this-purpose column. Adding a
staleness threshold to the recovery-candidate criterion (e.g., `PROCESSING` + no active task **+**
`updated_at` older than a defined minimum age, e.g. several multiples of the orchestrator's own
expected claim-to-create_task duration) would exclude any event still plausibly mid-flight in a
healthy pass, narrowing recovery eligibility to genuinely stale rows without a migration or new
column. This does not fully eliminate problem (a) (two truly concurrent recovery passes both older
than the threshold could still race each other), but it closes problem (b) entirely and shrinks (a)
to the same order of rarity the Contract already accepts elsewhere (two passes racing within the
same narrow window, now the recovery-staleness window instead of the claim-to-create_task window) —
consistent with the risk level the rest of this Contract treats as acceptable given §7.4's deferred
scheduling.

**Verdict: SAFE WITH LIMITATION.** Not UNSAFE — no data loss, no silent permanent drop, and the
scenario requires genuine concurrent orchestrator execution, which remains deferred/unlikely within
Phase 9's own declared operating envelope (§7.4), consistent with how the original audit scoped its
own §4 verdict ("SAFE ENOUGH FOR PHASE 9's own defined scope") before requiring the primary-path fix
anyway. The same standard applied there — close the race rather than rely solely on "unlikely" —
applies here.

---

## 6. Phase 9 Boundary Consistency

Re-checked the IN/OUT boundary the original audit reviewed and approved (§21 of that audit) against
the current Contract, line by line:

- **§0 Purpose / pipeline diagram**: unchanged in substance — Triage → task creation →
  `ResearchCapability` → `IntelligenceCapability`; explicit statement that Phase 9 does not complete
  `NEWS_ANALYSIS`. Matches the original audit's citation exactly.
- **§1 Principles P1–P12**: all twelve present, unchanged in content and number (re-read in full
  this audit — no principle was added, removed, or reworded by the revision; the revision note at
  the top of the Contract explicitly confirms this and this audit independently corroborates it by
  direct reading).
- **§20 Explicit Non-Goals**: items 1–17 unchanged in content (clustering, embeddings, vector DB,
  engagement collection, Final Ranking, Opportunity Score, source-reputation learning, browsing
  tools, autonomous agents, persistent intelligence graph, new Workflow Engine, new scheduler, new
  DB model/migration, republication check — all present, matching the original audit's §18 Scope
  Leakage checklist one-for-one). Exactly one item was added: **item 18**, the crash-safe
  checkpointing non-goal (§14.1) — a pure OUT-of-scope addition that does not touch, narrow, or
  widen the IN-scope boundary (Triage + Research + Intelligence).
- **§13 completion-boundary language**: unchanged in its central claims (four `required=True` steps,
  `engagement_analysis` unregistered, `NEWS_ANALYSIS` still ends `FAILED` after Phase 9); gained only
  the crash-safety cross-reference sentence, which narrows what "integration proof" is allowed to
  claim — a tightening, not a boundary change.
- **No file outside Phase 9's five components (Freshness, Triage, Triage Orchestrator,
  `ResearchCapability`, `IntelligenceCapability`) gained new responsibility.** The
  recovery-candidate mechanism (§5, above) is additional *specification* of the Triage
  Orchestrator's existing, already-in-boundary responsibility (§2.3: "atomically claim each one"),
  not a boundary expansion.

Re-confirmed via `git status`/`git diff --stat`: zero Phase 5–8 production files are modified;
every citation to frozen code (`workflows/runner.py`, `services/workflow_service.py`,
`database/models/editorial_task.py`, `database/models/news_event.py`, `schemas/workflow.py`,
`workflows/definitions/news_analysis.py`) was re-grepped fresh this audit and matches exactly what
the original audit inspected.

**Verdict: CONSISTENT. No boundary drift.**

---

## 7. Implementability

**Could two competent developers now implement §7 (claim + recovery) and produce compatible,
equally-safe systems?**

- **Primary claim path**: Yes, now unambiguous. §7.2 step 1 specifies the exact SQL shape (a single
  conditional `UPDATE ... WHERE status = 'NEW'`, or equivalent), forbids read-then-write explicitly,
  and mandates an affected-row-count check. Verified independently implementable with the existing
  `AsyncSession` and SQLAlchemy Core (`update(NewsEvent).where(...)`, `result.rowcount`) — no new
  dependency, no schema change; confirmed no existing precedent for this exact pattern exists
  elsewhere in the repository, but it requires no capability the stack doesn't already have.
- **`TaskPriority` comparison**: Yes, now unambiguous — the explicit-ordinal-mapping requirement and
  its accompanying test rule leave no room for a naive `sorted()`-based implementation to pass
  review or tests.
- **Crash/restart scope**: Yes, now unambiguous — §14.1's seven points leave no room for a developer
  to reasonably believe durable recovery is in scope or that `step_results` survives a restart.
- **Recovery-candidate path (§5, this audit)**: **Not yet unambiguous.** Two developers implementing
  §7.2's recovery-candidate criterion exactly as written could reasonably produce systems with
  materially different duplicate-task exposure — one might add an incidental staleness check out of
  caution (closing the gap unknowingly), another might implement the literal criterion
  (`PROCESSING` + no active task, no staleness) and ship the race described in §5. This is the one
  remaining implementability gap this audit found.

**Verdict: Implementable for all three originally-audited areas. Not yet fully implementable
without residual, developer-dependent risk for the newly-added recovery-candidate mechanism.**

---

## 8. Remaining Findings

**CRITICAL**: None.

**MAJOR** (new — not a restatement of any original finding, all three original findings are marked
RESOLVED above):
1. **The `PROCESSING`-with-no-active-task recovery-candidate mechanism (§7.2, §7.5) lacks an
   equivalent DB-level guarantee to the primary claim path, and its selection criterion cannot
   distinguish a genuinely orphaned event from one merely mid-flight in a healthy, concurrent
   orchestrator pass** (§5 of this audit). *Correction*: add a staleness condition to the
   recovery-candidate selection query, reusing the existing `NewsEvent.updated_at` column
   (`database/models/news_event.py:65-67`, no migration required), and revise §7.5 point 2's
   "not a failure... lower-stakes race" language to acknowledge that `DuplicateActiveTaskError`
   firing is not DB-guaranteed under a true race (consistent with how §7.5 already, correctly,
   declines to overstate the primary path's guarantees).

**MINOR**: None new. The three MINOR items from the original audit (§7.5 rule 2 precondition prose,
the Capability-execution-count vs. Gateway-call-count distinction, and out-of-range
`reliability_score` defensive behavior) were out of scope for this focused re-audit (the user's
instruction limited it to the three MAJOR findings) and were not revisited; they remain open,
low-priority items from the prior audit, unaffected by this revision.

**OBSERVATION**: None new.

---

## 9. Scores

| Dimension | Score /10 | Basis |
|---|---|---|
| Crash/Restart Clarity | 10 | All seven required disclosure points present, cross-referenced from every dependent section; independently re-verified against unchanged `workflows/runner.py` |
| Priority Semantics Safety | 10 | Empirical finding stated, canonical order frozen, native comparison explicitly prohibited, ordinal mapping mandated, backed by a test requirement |
| Concurrency/Claim Safety | 9 | Primary `NEW`→`PROCESSING` claim path now has a real, verified DB-level atomic guarantee; docked one point only because the claim mechanism's own justification (§7.5) slightly overstates the recovery path's safety by extension |
| Recovery Safety | 5 | The recovery mechanism is a genuine, well-motivated addition that correctly handles the *disclosed* failure mode, but its selection criterion is not narrow enough and reintroduces an undisclosed TOCTOU race under concurrent execution |
| Internal Consistency | 8 | No true contradiction found; docked because §7.5's "not a failure... lower-stakes race" framing for recovery-vs-recovery races is inconsistent in rigor with how carefully the primary path's guarantee is scoped elsewhere in the same section |
| Implementability | 8 | Three of four claim-related mechanisms are now unambiguous; the recovery-candidate criterion is the one remaining area where two compliant implementations could diverge in safety |
| Contract Readiness | 7 | All three original MAJOR findings genuinely resolved; one new, narrowly-scoped MAJOR finding must be closed before freezing — same bar this Contract has been held to throughout |

**Overall (evidence-weighted): 8.1/10.**

---

## 10. Final Verdict

**PHASE 9 CONTRACT STILL NOT READY**

All three MAJOR findings from `docs/phase9_architecture_contract_audit.md` are fully and correctly
resolved: the crash/restart limitation is disclosed and scoped precisely, the `TaskPriority`
ordering hazard is prohibited with a mandated mitigation and test, and the primary `NewsEvent` claim
is now a real, verified DB-level atomic guarantee, correctly reordered ahead of `create_task()`. The
Phase 9 boundary itself is unchanged and remains sound — no drift found anywhere in §0, §1, or §20.

However, the mechanism this revision introduced to make the primary-path fix complete — the
`PROCESSING`-with-no-active-task recovery-candidate selection — was never reviewed by the original
audit (it did not exist yet) and, on adversarial review here, reintroduces a narrower version of the
exact TOCTOU duplicate-task race the primary-path fix was designed to eliminate, with no staleness
gate to exclude events merely mid-flight in a healthy concurrent pass. This is a new MAJOR finding,
not a failure of the requested corrections, and it has a small, concrete, non-migration fix
available (§8: a staleness condition on the existing `updated_at` column). One further, narrowly
targeted revision pass — to §7.2's recovery-candidate criterion and §7.5 point 2's framing only — is
required before this Contract is safe to freeze.
