# Phase 17 Stage 2 — Human Decision Result

**Source of truth: explicit, verbatim human decisions given in conversation on 2026-08-04, recorded
into `scripts/_phase17_stage2_candidate_results.json` via `scripts/phase17_stage2_candidate_generation.py
record-preference` (file-only mutation, no database access, no LLM call). Post-write verification
read the artifact back and confirmed all four `editorial_preference`/`editorial_notes` fields match
these decisions exactly, byte-for-byte.**

This closes the loop opened by `docs/phase17_stage2_human_comparison_packet.md` — every case there
was `not_yet_reviewed`; every case here has an explicit human verdict.

## Decisions

| Case | Category | Editorial preference | Completeness | Fact Safety | Notes |
|---|---|---|---|---|---|
| `2d35bad8` | AI | **Candidate** | Candidate better | Equal | Candidate improves context without adding unsupported facts. |
| `12ce8e52` | STARTUPS | **Candidate** | Candidate better | Candidate better | Candidate reduces unsupported framing by attribution and explicit unknowns. |
| `847618cd` | SOFTWARE | **Candidate** | Candidate better | Equal | Candidate is preferred. Safety escalation is a confirmed matcher false positive because the numeric claim exists verbatim in Research evidence. |
| `ac1f1ff5` | AI | **Candidate** | Candidate better | Candidate better | Candidate correctly attributes source claims instead of presenting them as confirmed facts. |

**Result: 4/4 candidates preferred over baseline.** No case was a tie, no case rejected.

## `847618cd` resolution (the one flagged case)

The candidate's raw, automated `CandidateFactSafetyAudit` **still reads `fail`/`high`** in the
artifact — recording the human decision does not overwrite or suppress that automated finding, by
design (the audit result and the human judgment are stored as separate fields, never merged). The
human decision explicitly records *why* the preference is "Candidate" despite that flag: the
flagged numeric claim ("320,7 млн" / 320.7 million input tokens) was independently verified against
this event's actual, persisted Research output during the review preparation step and found to be
present there **verbatim** — the escalation is judged a matcher false positive, not a retraction of
the underlying finding. Both the raw `fail` status and this human resolution are preserved
side-by-side in the artifact for anyone reviewing this case later.

## What this decision does — and does not — authorize

- Recorded: `editorial_preference` and `editorial_notes` for 4 cases, in the local Stage 2 JSON
  artifact only.
- **Not done**: no `ContentDraft` was modified (verified: all 4 rows' `updated_at` byte-identical
  before and after this step). No `EditorialTask` state changed. No Telegram message was sent. No
  candidate text was published, scheduled, or routed anywhere.
- A human preference for "Candidate" here is an editorial judgment on these 4 specific comparisons
  — it is **not** itself an authorization for Stage 3 (canary delivery), production cutover, or any
  automated use of these preferences going forward. Per the Stage 2 plan
  (`docs/phase17_stage2_controlled_candidate_generation_plan.md`), promoting this signal into
  anything that touches real delivery is explicitly out of scope and would need its own separate
  authorization and, per that plan's §5, additional engineering not yet built.

## Status

Human decisions: **RECORDED**. `ContentDraft`/`EditorialTask`: **unchanged** (verified). Telegram:
**untouched**. Stage 3: **not started**.
