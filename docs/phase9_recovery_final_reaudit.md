# Phase 9 Recovery Safety — Final Narrow Re-Audit

**Status: audit document. NOT a specification. NOT binding. Verification only — no Contract, code,
test, migration, or prior Phase 9 document was modified in this pass.** This document audits the
recovery/concurrency corrections currently present in
`docs/phase9_research_intelligence_architecture_contract.md` (current on-disk state, 1178 lines)
against the actual repository, re-verifying claims rather than trusting prior citations. One new
piece of empirical evidence was gathered this pass (a disposable script against the real dev
Postgres DB, deleted afterward); everything else was re-derived by reading
`services/workflow_service.py`, `database/models/editorial_task.py`, and a repo-wide grep for
`create_task`/`WorkflowRunner` call sites in full, fresh.

**Governing question**: is the combined NEW-claim + stale-recovery + `create_task()` path actually
safe enough to freeze?

---

## 1. Verify Primary NEW Claim

- **Atomic**: §7.2 step 1 mandates a single conditional `UPDATE ... WHERE status = 'NEW'` (or
  equivalent), never read-then-write. Re-confirmed against Postgres's row-level `UPDATE` semantics
  and against the empirical proof already on record (a Core-level conditional `UPDATE` correctly
  affects exactly one row when the guard matches).
- **At most one winner**: of two concurrent attempts against the same row, at most one affects a
  row; the other affects zero. Standard single-statement `UPDATE` atomicity — not scheduling- or
  deployment-dependent.
- **Loser gets rowcount == 0**: §7.2 step 1 explicit ("If this claim affects zero rows... this
  event MUST be skipped entirely").
- **Loser does not proceed**: §7.2's step ordering makes step 1's success a precondition for steps
  2–3 (Triage, `create_task()`) — a losing attempt never reaches either.

**Verdict: PASS**

---

## 2. Verify Fresh PROCESSING Safety

- **`PROCESSING` + no active task is NOT sufficient for recovery**: §7.2's selection paragraph and
  §7.6's eligibility invariant both require staleness as a third, mandatory condition, stated
  explicitly ("`PROCESSING` + no-active-task, by itself, is NOT sufficient").
- **Staleness required**: `(reference_now - updated_at) > staleness_threshold` — §7.6 rule set.
- **Exactly-at-threshold is not stale**: §7.6 rule 3, explicit and frozen ("strictly greater
  than... An event whose age exactly equals the threshold is treated as not yet stale").
- **Future `updated_at` is not stale**: §7.6 rule 4 — a negative age is always less than a
  non-negative threshold; re-confirmed against the empirical finding that the DB accepts a future
  timestamp without a `CHECK`-constraint rejection, so this arithmetic-only handling is the correct
  and sufficient response (no DB-level defense needed).
- **A healthy recent claimant cannot be recovered immediately**: proven by construction — `age ≈ 0`
  immediately after a claim, and the eligibility invariant requires `age > threshold`.

**Operational limitation, honesty check**: §7.6 states plainly, under "Honest operational
constraint, stated plainly, not hidden," that a healthy worker whose own processing exceeds the
threshold before reaching `create_task()` *can* be raced by a recovery attempt, and describes the
exact bounded consequence (a `create_task()`-level race, resolved by `DuplicateActiveTaskError`,
never a silent duplicate beyond what §7.5 already accepts). This is stated as a real constraint,
with its actual consequence spelled out, not minimized or hidden behind reassuring language. It
also states the operator-facing mitigation (configure the threshold with a wide safety margin) and
requires logging of every successful recovery-ownership acquisition (§15) — giving operators a
concrete signal if the constraint is ever actually being exercised.

**Verdict: PASS WITH DOCUMENTED LIMITATION** (the limitation is honestly and specifically stated,
not merely acknowledged in the abstract — this satisfies the bar for "documented enough," not
"insufficiently disclosed")

---

## 3. Verify Stale Recovery Ownership

- **Recovery requires stale `PROCESSING` + no active task**: confirmed, §7.6's eligibility
  invariant, all three conditions `AND`-ed together, none optional.
- **Ownership uses atomic CAS against observed `updated_at`**: confirmed, §7.6's
  ownership-acquisition mechanism — `UPDATE ... WHERE status = 'PROCESSING' AND updated_at = <the
  exact value observed during selection>`.
- **Exactly one concurrent winner**: re-confirmed via the empirical proof recorded in the prior
  correction pass — a second CAS attempt using the same, now-superseded `updated_at` value
  deterministically affects zero rows (measured directly against the real database, not assumed).
- **Losers do not proceed**: §7.6 explicit — a zero-row result means "this event MUST be skipped
  entirely for this pass, with no error," mirroring the `NEW`-claim loser handling exactly.
- **Ownership acquisition refreshes `updated_at`**: confirmed empirically — `onupdate=func.now()`
  fires on a Core-level conditional `UPDATE` even when `updated_at` is not named in `.values()`; the
  Contract also permits explicitly setting it, either way satisfying the requirement that the row
  advance so a second, stale-keyed attempt can no longer match.
- **Re-check after ownership acquisition, where required**: the "still `PROCESSING`, still at that
  exact `updated_at`" re-check is structural — the CAS's own `WHERE` clause *is* the re-check,
  evaluated atomically by the database at execution time (no separate application-level re-read is
  needed or specified, correctly). The remaining re-check — "no active task now exists" — is
  performed by `create_task()`'s own existing, internal `_find_active_task()` call, confirmed by
  reading `services/workflow_service.py` fresh this pass: it is the *first* thing `create_task()`
  does, before any write (line 46, ahead of the `EditorialTask` construction at line 53). This
  re-check is real and load-bearing, not merely asserted.

**Verdict: PASS**

---

## 4. Verify Active-Task Precedence

Traced the actual logic path the Contract specifies, against the actual code:

- §7.6's eligibility invariant lists `no active (CREATED/RUNNING) EditorialTask exists for it
  (_find_active_task())` as a condition independent of, and prior to, the staleness condition, and
  states explicitly: "An event with an active task is never a recovery candidate regardless of how
  old `updated_at` is... the active-task check takes precedence over staleness entirely, and is
  evaluated first."
- `_find_active_task()` (re-read fresh, `services/workflow_service.py:89-106`) filters on
  `EditorialTask.status.in_(ACTIVE_STATUSES)` where `ACTIVE_STATUSES = (TaskStatus.CREATED,
  TaskStatus.RUNNING)` (line 24) — a real, correctly-scoped filter matching what §7.6 assumes.
- The partial-failure matrix (§7.6, state D/F) states this precedence explicitly for the two states
  where it matters: an active task blocks recovery "regardless of `updated_at`'s age, however old it
  grows."

**Verdict: PASS** — for the specific claim as stated (an event with a `CREATED`/`RUNNING` task is
never a recovery candidate). See §5 below for a related, but distinct, finding about what happens
once a task leaves the active set entirely (reaches `FAILED`/`COMPLETED`) — that is a different
question from the one this section verifies, and does not invalidate this verdict.

---

## 5. Critical Check — `create_task()` Duplicate Safety

Re-read `services/workflow_service.py` in full this pass (not trusted from memory or prior audits)
and re-checked `database/models/editorial_task.py` for constraints/indexes.

1. **Is `_find_active_task()` check-then-act?** Yes, confirmed — a plain `SELECT` (line 91-97),
   filtered further in Python (line 98-100), with the `INSERT`+`commit()` (lines 53-71) happening
   later in the same function, no lock held across the gap.
2. **Is there a DB-level unique constraint preventing two active `EditorialTask`s for the same
   logical `NewsEvent`/workflow?** No. Re-read `database/models/editorial_task.py` in full:
   `event_id` is a plain `ForeignKey` column with no `unique=True` and no composite index; there is
   no column for `workflow_type` at all (it lives inside the `workflow` JSON blob, matched in
   Python). No constraint of any kind — unique, check, or exclusion — could enforce this at the DB
   level today without a migration.
3. **Can two independent callers of `create_task()` still race and both insert active tasks?**
   Yes, in the abstract/general sense — nothing internal to `create_task()` prevents this; it is
   confirmed non-atomic as a standalone function, unchanged from every prior audit's finding.
4. **Does the Phase 9 orchestrator's atomic `NewsEvent` claim/CAS eliminate that race for both
   paths?**
   - **`NEW` path**: yes — only one instance's claim can succeed for a given `NewsEvent`, so only
     one instance ever reaches `create_task()` for it via this path.
   - **Stale-recovery path**: yes, for the ordinary case — only one instance's CAS can succeed for a
     given stale candidate. The one disclosed exception is the "stolen healthy worker" scenario
     (§2, above): if a legitimate claimant's own processing exceeds the staleness threshold, a
     recovery attempt can acquire ownership concurrently with the original claimant's own,
     still-in-flight path to `create_task()` — in that specific, honestly-disclosed case, two
     callers *can* reach `create_task()` for the same event, and `create_task()`'s own non-atomic
     `_find_active_task()` check is what is relied on to prevent a duplicate — probabilistically,
     not with a DB-level guarantee. This is the one place ownership exclusivity does not, by itself,
     fully eliminate the race; the Contract discloses this rather than overstating a guarantee it
     does not have.
5. **Could any other production path call `create_task()` for the same event concurrently, bypassing
   the `NewsEvent` claim discipline?** Re-checked by grepping the entire repository fresh: no
   caller of `workflow_service.create_task` exists anywhere in `app/`, `bot/`, `scripts/`, or
   `services/` today — the only reference outside `services/workflow_service.py` itself is a
   docstring citation in `schemas/editorial_task.py`. **Today, no such path exists.** The Contract's
   own Component Model (§2) enumerates exactly five Phase 9 components, none of which is a second
   caller of `create_task()`.
6. **Does the Contract require that ALL Phase 9 task creation for a `NewsEvent` happen only after
   successful ownership acquisition?** Functionally, yes — §7.2/§7.3 describe the orchestrator as
   the sole creator of `EditorialTask`, always via steps 1→2→3 in order. **Textually, this is not
   stated as an explicit, standalone `MUST NOT` rule** (e.g., "no Phase 9 component other than the
   orchestrator's own claimed/owned sequence may call `create_task()`") the way other exclusivity
   rules in §7.2 are — it is established by the narrative structure of §7.2/§7.3 rather than a
   dedicated prohibition. This is a real, minor textual completeness gap, not a functional one,
   since (per finding 5) no other caller exists to violate it.
7. **Is that sufficient within Phase 9 scope even though `create_task()` itself remains globally
   non-atomic?** Yes, for Phase 9's own actual, delivered scope, given findings 4–6 above.

**Distinguishing GLOBAL `create_task()` safety from PHASE 9 ORCHESTRATOR safety**: `create_task()`
itself is, and remains, globally check-then-act — this is unchanged, pre-existing, frozen Phase 5
behavior this Contract does not (and could not, without a migration) fix. What Phase 9 actually
guarantees is narrower and different: that *every call to `create_task()` originating from its own
orchestrator* is preceded by an exclusive, DB-level-atomic ownership acquisition over the
`NewsEvent` involved, for both the `NEW` and stale-recovery paths, with one honestly-disclosed,
narrow, bounded exception (the "stolen healthy worker" scenario, itself bounded by the same
already-accepted residual-race class §7.5 discloses elsewhere).

**Conclusion: A.** *Phase 9 is safe because every Phase 9 `create_task()` call is serialized by
exclusive `NewsEvent` ownership, even though `create_task()` itself remains globally check-then-act*
— confirmed, with two caveats stated plainly rather than overstated away: (i) the one narrow,
already-disclosed exception where a stolen claim produces two legitimate callers, resolved
probabilistically by `create_task()`'s own check, not a DB guarantee; (ii) the Contract's exclusivity
of the orchestrator as `create_task()`'s sole Phase 9 caller is established narratively, not stated
as one standalone binding rule — true today (no other caller exists) but not mechanically enforced
or explicitly prohibited in `scripts/validate_architecture.py` for future callers, worth a small
textual tightening in a future pass, not blocking now.

**New finding, not previously disclosed anywhere (surfaced by this final pass)**: `_find_active_task()`'s
"active" definition is `TaskStatus.CREATED`/`RUNNING` only — a task that has reached `FAILED` or
`COMPLETED` is no longer "active." Re-confirmed via repo-wide grep this pass: **nothing in the
current repository ever instantiates `WorkflowRunner` or calls `.run()` outside of tests** — no
scheduler, service, or script drives any `EditorialTask` to a terminal status today. Consequently,
within Phase 9's own delivered and tested scope, an `EditorialTask` created by the orchestrator stays
`CREATED` (still "active") indefinitely, and the eligibility invariant's "no active task" condition
correctly and permanently excludes it from recovery. **However**, once a future phase (or any
operational process) actually invokes `WorkflowRunner.run()` on these tasks, §13's own already-frozen
finding guarantees every one of them ends `FAILED` (at `engagement_analysis`, unregistered). At that
point, the same `NewsEvent` becomes `PROCESSING` + no *active* task once again (a `FAILED` task is
not "active"), and — once `updated_at` (untouched since the original claim/ownership-acquisition)
exceeds the staleness threshold — it becomes a fresh recovery candidate, whose successful CAS and
`create_task()` call would create a **second** `EditorialTask` for an event that has already been
fully, if unsuccessfully, processed once. This is not bounded or self-healing the way the disclosed
residual gaps are — it would repeat indefinitely for every event, once triggered. **This is
currently unreachable** (no code path in the repository can trigger it), so it does not compromise
Phase 9's own safety as delivered, and is explicitly out of Phase 9's own scope to fix (Phase 9 does
not run `WorkflowRunner` on real tasks — §13). It is, however, a real latent gap in the recovery
mechanism's general reusability that a future phase adding a `WorkflowRunner` scheduler will need to
address (e.g., by also treating a terminal-but-never-superseded task as evidence the event should
not be re-recovered) before that future phase can safely rely on this same eligibility invariant.
**Classified: OBSERVATION, non-blocking for Phase 9, worth a documentation note in a future,
narrow revision — not a defect in what this Contract governs today.**

---

## 6. Verify Partial-Failure Recovery

| Case | Ends NEW/PROCESSING | Active task exists? | Rerun safe? | Duplicate possible? | Deterministic? |
|---|---|---|---|---|---|
| A. `NEW` claim → Triage → `create_task()` all succeed | `PROCESSING` | Yes (`CREATED`) | N/A, already succeeded | No | Yes |
| B. `NEW` claim succeeds, `create_task()` fails before task exists | `PROCESSING` | No | Yes — becomes stale-recoverable after threshold (§7.6) | No — a lost claim never reaches `create_task()` again until re-claimed via recovery, gated by staleness | Yes |
| C. `NEW` claim succeeds, task created, process crashes before later work (i.e. before `WorkflowRunner.run()` ever executes on it) | `PROCESSING` | Yes (`CREATED`, unchanged — nothing ever runs it) | N/A — permanently, correctly excluded from recovery by the active-task check (§4, above) | No | Yes |
| D. Recovery CAS succeeds, `create_task()` fails | `PROCESSING` | No | Yes — re-eligible once stale again from the ownership-acquisition's own fresh `updated_at` (§7.6 state G-equivalent) | No | Yes |
| E. Recovery CAS succeeds, active task appears before `create_task()` is called | `PROCESSING` | Yes, by the time `create_task()` runs | `create_task()` correctly raises `DuplicateActiveTaskError` (§7.5 point 2); orchestrator treats it as handled, moves on | No — this is exactly the scenario `create_task()`'s existing check exists to catch, and it does (§3, above) | Yes |
| F. Two recovery workers observe the same stale event | Exactly one acquires CAS ownership | Depends on which caller reaches `create_task()` first (only one path proceeds) | Yes — the loser skips silently at the CAS step, never reaching `create_task()` at all | No — closed at the CAS step, before either could race at `create_task()` (§3, above) | Yes |

All six cases have deterministic, previously-reasoned-through outcomes; none produces an undefined
or ambiguous state. Case C's outcome depends on the assumption (verified this pass, §5 above) that
nothing currently drives tasks to a terminal state — flagged there as the one place this assumption
is load-bearing beyond Phase 9's own scope.

**Verdict: PASS**

---

## 7. Verify No Migration / No Hidden State

Re-confirmed by reading the full Contract text and the actual model files this pass:

- `NewsEvent.status` — existing column, existing enum, reused (§7.2).
- `NewsEvent.updated_at` — existing column (`database/models/news_event.py:65-67`), reused (§7.6).
- `EditorialTask` queries — the existing, unmodified `_find_active_task()`
  (`services/workflow_service.py:89-106`), reused as-is.
- Transaction/session primitives — standard `AsyncSession`/Core `update()`, already in use
  elsewhere in the codebase (e.g. `WorkflowRunner`'s own commit pattern).

No migration, no new column, no lease table, no Redis/distributed lock, no hidden scheduler state
anywhere in the Contract's text — confirmed by direct reading of §7.2/§7.5/§7.6/§20 (items 16, 19).

**Verdict: PASS**

---

## 8. Verify Contract Wording

Grepped the entire current Contract for every variant of "`PROCESSING` + no active task" (both the
literal phrase and its structural equivalents) this pass, fresh — every occurrence found is
qualified by the staleness/ownership requirement, or is describing a *state* (not asserting
sufficiency for recovery). No unqualified "`PROCESSING` + no active task = recoverable" wording
remains anywhere in the document.

Checked separately for any claim that `create_task()` itself provides DB-level duplicate safety:
none found. §7.5's "Explicit distinction, binding" block states the opposite, precisely: the
DB-level atomic guarantee belongs to the claim/ownership-acquisition mechanisms (§7.2 step 1, §7.6);
`create_task()`'s own `DuplicateActiveTaskError` check is explicitly framed as "not DB-level —
bounded and self-healing instead," secondary to, never a substitute for, `NewsEvent` ownership.

**Verdict: PASS**

---

## 9. Final Safety Matrix

| State | Can be claimed? | Can be recovered? | Can create task? | Can duplicate? | Expected next state |
|---|---|---|---|---|---|
| `NEW` / no task | Yes (atomic claim, §7.2 step 1) | N/A (not `PROCESSING`) | Yes, after claim succeeds | No | `PROCESSING` + active task |
| `NEW` / active task | Not reachable via Phase 9's own orchestrator (no path creates a task before claiming); would only arise via a hypothetical bypass caller (§5 finding 6) | N/A | N/A | N/A (out-of-model state) | N/A |
| Fresh `PROCESSING` / no task | No (not `NEW`) | No — age ≤ threshold (§7.6 rule 3) | Only by the original claimant, already in flight | No, unless threshold is misconfigured too low relative to real latency (§2, disclosed) | `PROCESSING` + active task, or (rarely) stays fresh-then-stale if `create_task()` fails |
| Stale `PROCESSING` / no task | No (not `NEW`) | Yes — atomic CAS ownership acquisition (§7.6) | Yes, by the CAS winner only | No — at most one CAS winner (§3, above); bounded exception only if the "stolen healthy worker" case co-occurs (§2, §5) | `PROCESSING` + active task, or re-enters this same state once stale again if `create_task()` fails |
| `PROCESSING` / active task | No (not `NEW`) | No — active-task check takes precedence unconditionally (§4, above) | N/A — already has one | No — this is the excluded state itself | Unchanged until the task itself resolves (currently: stays `CREATED` indefinitely — no process in this repository ever advances it, §5 new finding) |

---

## 10. Final Verdict

**PHASE 9 CONTRACT APPROVED WITH DOCUMENTED LIMITATION**

All nine required conditions hold within Phase 9's own actual, delivered scope:

- `NEW` claim is atomic (§1: PASS).
- Stale recovery ownership acquisition is atomic (§3: PASS).
- Fresh in-flight claims are protected from premature recovery (§2: PASS, with an honestly-stated
  operational constraint on threshold calibration).
- Two concurrent recovery workers cannot both win (§3, §6 case F: PASS).
- Every Phase 9 orchestrator `create_task()` call is preceded by exclusive `NewsEvent` ownership,
  for both paths, with one narrow, already-disclosed exception bounded by `create_task()`'s own
  existing self-healing check (§5, conclusion A).
- No other current path in the repository bypasses ownership to call `create_task()` (§5, finding
  5 — verified by fresh repo-wide grep).
- Active-task precedence is correct and unconditional (§4: PASS).
- All six partial-failure cases are deterministic and recoverable (§6: PASS).
- No migration, new column, or hidden infrastructure is required (§7: PASS).

**Two things keep this from an unqualified APPROVED**, both disclosed here plainly rather than
smoothed over:

1. The pre-existing, already-Contract-documented operational constraint on staleness-threshold
   calibration (§2 of this audit; §7.6 of the Contract) — genuinely bounded, honestly stated, not a
   defect.
2. **One new, non-blocking observation surfaced by this pass**: the recovery mechanism's reliance on
   `_find_active_task()`'s `CREATED`/`RUNNING`-only definition of "active" means a task that ever
   reaches a terminal status (`FAILED`/`COMPLETED`) would make its `NewsEvent` recoverable again,
   risking unbounded duplicate task creation — **currently unreachable**, since nothing in this
   repository invokes `WorkflowRunner.run()` on any real task (verified by fresh grep), and squarely
   outside Phase 9's own scope (§13 already forbids treating real workflow completion as anything
   Phase 9 proves or relies on). This does not compromise Phase 9's safety as delivered. It is a
   latent gap a future phase must address before wiring up real `WorkflowRunner` scheduling against
   these tasks — worth a small, narrow documentation note in a future revision, not a reason to
   withhold approval now.

No CRITICAL or blocking finding exists. The combined NEW-claim + stale-recovery + `create_task()`
path is safe enough to freeze as specified.
