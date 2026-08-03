# Phase 17 Stage 2 — Controlled Candidate Generation Plan

**This is a plan for a future, separately-authorized implementation. No code in this repository
has been written or changed to build Stage 2 as of this document. No LLM call has been made to
produce it. No production behavior is affected by this document existing.**

Authorized by: explicit user message, 2026-08-04, following human acceptance of Stage 1 (`docs/
phase17_stage1_human_acceptance_result.md`). Scope, per that authorization, verbatim:

- Do NOT activate production enforcement.
- Do NOT change default behavior.
- Generate candidate copy alongside existing production draft.
- Do not replace `ContentDraft`.
- Do not send Telegram automatically.
- Do not mutate production state.
- Require manual comparison.
- Track: baseline text, candidate text, editorial preference, failure reasons.
- No LLM calls until implementation requires them.
- No production activation.

## 1. What already exists (do not rebuild)

Stage 2 is not a greenfield build — most of the required machinery already exists from M3/M4 and
only needs to be unified and extended for tracking, not reinvented:

- **Config gate**: `core/config.py` already defines `adaptive_length_mode` and
  `beginner_copywriting_mode` as `Literal["off", "shadow", "comparison"]`. `"comparison"` already
  means "same shadow computation in the worker path, plus a required precondition for offline
  scripts to make one real paid candidate call" — this is exactly Stage 2's shape. No new config
  enum value is needed; Stage 2 is a controlled, tracked use of the mode that already exists.
- **Comparison scripts**: `scripts/phase17_m3_adaptive_length_comparison.py` and `scripts/
  phase17_m4_beginner_copywriting_comparison.py` already implement, and have already been run for
  real: read-only `ContentDraft`/`EditorialTask`/`NewsEvent` selects, `--dry-run` default, a real
  call gated behind `--live` + `--confirm-paid-calls` + the matching config mode, a hard per-run
  candidate-call cap, resume support via an existing `--output` file, per-case failure isolation,
  and output written only to an untracked local JSON artifact — never to `ContentDraft`/
  `EditorialTask`. This safety discipline is the baseline Stage 2 must preserve, not redesign.
- **Deterministic second-pass audit**: `services/candidate_fact_safety.evaluate_candidate_fact_safety()`
  already runs, zero-LLM-cost, against baseline and candidate text alike — already wired into the
  M4 comparison script.
- **Governed candidate prompts**: `copywriting_adaptive_candidate` (M3) and
  `copywriting_beginner_candidate` (M4) already exist as separately named, versioned prompts,
  distinct from the production `copywriting` prompt.

## 2. What Stage 2 actually adds

The one genuinely new thing Stage 2 requires that M3/M4 did not build: **a durable, reviewable
record of the human's editorial preference and failure reasons per case**, not just the
candidate/baseline text pair. M3/M4's own comparison scripts produced text for a human to read in
the moment (`_phase17_m3_ab_review.json`/`_phase17_m4_abc_review.json`-style manual review
artifacts) but did not have a structured field for "which did the editor prefer, and why not the
other" as a first-class, queryable record.

Concretely, Stage 2 needs:

1. **A unified controlled-generation script** (working name:
   `scripts/phase17_stage2_candidate_generation.py`), built on the exact same safety scaffolding as
   the M3/M4 comparison scripts (read-only DB access, `--dry-run` default, `--live` +
   `--confirm-paid-calls` + config-mode gate, hard call cap, resume support, per-case failure
   isolation, untracked JSON output only). It does not need to reimplement candidate generation —
   it can call the same prompt/generation path M3/M4 already use, parameterized by which candidate
   type is being compared.
2. **A tracking record schema**, per case, containing exactly the four things requested:
   - `baseline_text` (the real, already-sent production `ContentDraft` body — read, never
     modified).
   - `candidate_text` (the newly generated candidate, when a real call was made; absent/null in
     `--dry-run`).
   - `editorial_preference`: a small enum — e.g. `baseline`, `candidate`, `neither`,
     `not_yet_reviewed` — plus free-text notes. This is filled in by a human, not inferred or
     defaulted by any heuristic.
   - `failure_reasons`: a list of free-text or coded reasons, covering both "why a candidate call
     could not be attempted" (e.g. `insufficient_source`, `generation_error`) and "why the editor
     rejected the candidate" (e.g. `fabricated_detail`, `tone_mismatch`, `too_long`) — this needs a
     human-facing field, not just an automated error string, since editorial rejection reasons are
     the actual signal Stage 2 exists to collect.
   This record is a new local artifact (JSON, matching the existing `scripts/_phase17_*` naming and
   git-ignore convention) — **not** a new database table or `ContentDraft`/`EditorialTask` column,
   consistent with "do not mutate production state." A future stage could promote this into a real
   table if the editorial signal proves valuable; that decision is explicitly out of scope here.
3. **No automatic selection logic.** The script's job ends at generating the candidate and
   recording the comparison; a human fills in `editorial_preference` afterward (e.g. by editing the
   output JSON or via a small follow-up review step) — no code path chooses `candidate` over
   `baseline` or vice versa.

## 3. Non-goals (explicitly out of scope for Stage 2)

- Replacing or mutating any `ContentDraft` row.
- Sending anything to Telegram, automatically or otherwise.
- Any `REJECT`/`ACCEPT` enforcement based on `channel_relevance` or `editorial_completeness`
  shadow output (Stage 5 territory, still unauthorized, still blocked on the M5 calibration gap
  per `docs/phase17_stage1_human_acceptance_result.md`).
- Canary delivery to any real chat (Stage 3 — explicitly flagged in the M6.1 runbook as needing
  net-new routing code not yet built).
- Any change to default `.env` values or worker startup behavior. Stage 2 remains an
  explicitly-invoked, human-gated script, exactly like M3/M4 before it — never a background worker
  behavior.

## 4. Cost discipline

Identical to M3/M4's already-proven pattern: `--dry-run` is the default and makes zero LLM calls.
A real (paid) run requires all of: `--live`, `--confirm-paid-calls`, and the relevant
`core.config.settings.*_mode == "comparison"`. A hard per-run cap on candidate-generation calls
carries forward unchanged. **No LLM call will be made to build or test this plan, or before a
human explicitly invokes the script with all three gates set.**

## 5. Open engineering questions (for implementation time, not now)

- Whether Stage 2 targets `adaptive_length_mode`/`beginner_copywriting_mode` candidates
  independently (as M3/M4 did) or introduces a single combined "Stage 2 candidate" prompt — likely
  the latter, since the human acceptance packet's own editorial questions (channel fit,
  completeness, production text quality) span both dimensions together, but this is an
  implementation-time decision, not a blocker to this plan.
- Whether `editorial_preference`/`failure_reasons` should be collected via a manually-edited JSON
  file (fastest, matches existing scripts) or a small dedicated review CLI/step (more structured,
  more code). Recommend starting with manually-edited JSON, matching the project's existing
  `scripts/_phase17_m3_manual_ab_evaluation.json`/`_phase17_m4_manual_abc_evaluation.json`
  precedent, and only building a dedicated tool if that proves too error-prone in practice.
- Sample selection for the first controlled batch (which real events/drafts to run Stage 2
  against) — deferred to the point of actual implementation/execution, which itself requires
  separate authorization beyond this plan.

## 6. Authorization checkpoint

This plan alone does not authorize execution. Per the M6.1 runbook's own precedent (`docs/
phase17_m6_1_production_cutover_runbook.md`, Prerequisites), a separate, explicit human
authorization is required before:
- Writing the Stage 2 script itself.
- Running it in `--dry-run` mode against real data (lower risk, but still worth a explicit go-ahead
  given this project's own discipline of never taking a paid-call-adjacent action without one).
- Running it `--live` with `--confirm-paid-calls` (real cost, real candidate text generated).

**Status: PLANNED, NOT IMPLEMENTED. No code written. No LLM call made. Production unchanged.**
