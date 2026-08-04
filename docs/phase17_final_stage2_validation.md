# Phase 17 — Final Stage 2 Validation (Post-M7.4)

**Read-only. No candidate was regenerated, no `editorial_preference` was mutated, no artifact file
was modified, no LLM call was made.** Completeness, Fact Safety (raw + calibrated), entity flags,
quantity flags, and causal flags were all recomputed directly against the real, already-recorded
baseline/candidate text and real event/research context, using the final, fully-fixed M7.1-M7.4
code (including the negation fix committed after this validation surfaced it).

## The four Stage 2 cases

| # | Case | Short event ID | Category |
|---|---|---|---|
| 1 | Google satellite spoofing | `2d35bad8` | AI |
| 2 | EU AI regulation | `12ce8e52` | STARTUPS |
| 3 | Bottleneck Labs / Saul agent | `847618cd` | SOFTWARE |
| 4 | Kimi K3 | `ac1f1ff5` | AI |

## Before (baseline) vs after (candidate) — full comparison

| Case | Baseline: Fact Safety (raw/calibrated) | Baseline: Completeness | Candidate: Fact Safety (raw/calibrated) | Candidate: Completeness | Entity flags (base→cand) | Quantity flags (base→cand) | Causal flags (base→cand) | Human preference |
|---|---|---|---|---|---|---|---|---|
| `2d35bad8` | pass / pass | NOT_READY (0.500) | pass / pass | REVIEW (0.682) | none → none | none → none | none → none | **candidate** |
| `12ce8e52` | review / review | INSUFFICIENT_SOURCE (0.500) | review / review | INSUFFICIENT_SOURCE (0.800) | 3 → 2 (severity down) | none → none | none → none | **candidate** |
| `847618cd` | pass / pass | REVIEW (0.591) | **pass / pass** | REVIEW (0.773) | none → none | none → none | none → **none** | **candidate** |
| `ac1f1ff5` | pass / pass | REVIEW (0.636) | review / review | REVIEW (0.818) | none → 1 (low, genuine alias) | none → none | none → none | **candidate** |

## Case 3 (`847618cd`) — the fully resolved flagship case

This is the single case tracked across the entire M7 arc (M7.1 → M7.2 → M7.3 → M7.4.1 → M7.4.2 →
the negation fix). Its candidate's raw Fact Safety status:

| Stage | Status | Severity | Remaining flags |
|---|---|---|---|
| Stage 2 original (pre-M7) | FAIL | high | numeric (token count) |
| M7.1 (calibration wiring) | FAIL → review via calibration | high → medium | numeric — rescued, not fixed |
| M7.2 (quantity classification) | REVIEW | medium | 2 entity flags |
| M7.3 (entity prefix stripping) | REVIEW | low | 1 causal flag |
| M7.4.1 (hedge-aware causal detection) | **PASS** | none | none |
| M7.4.2 + negation fix | **PASS** (confirmed stable) | none | none |

Both baseline and candidate now reach a clean `pass`/`pass` for this case. Completeness still
prefers the candidate (0.591 → 0.773) on its own, independent merits — length, structure, and
explicit uncertainty coverage — not on Fact Safety grounds (both are equally clean now).

## Case 4 (`ac1f1ff5`) — the one remaining flag is a genuine, correctly-classified case

The candidate's single `uncertain:ИИ` entity flag is the `"ИИ"`/`"AI"` alias — a real, low-severity,
low-confidence entity match (uncertain, not unsupported), not a false positive of any of the M7.1-
M7.4 fixes. It reflects the candidate's own more thorough sourcing language, not a defect.

## Human preference results (verified present, not touched)

All 4 cases retain their originally-recorded human decision from the Stage 2 human review session:
**`editorial_preference: "candidate"` in all 4 cases**, each with its own recorded
`editorial_notes` (unchanged, confirmed byte-for-byte identical in `scripts/
_phase17_stage2_candidate_results.json`, which this validation read but never wrote to). No
preference was inferred, changed, or overwritten by this validation pass.

## What changed since the human review was originally recorded

The human reviewers' own notes on `847618cd` explicitly called the original Fact Safety escalation
"a confirmed matcher false positive" — this validation confirms that judgment was correct: the
underlying detector defect is now fixed at the source (M7.2's metric-quantity classification, M7.3's
entity-prefix stripping, and M7.4's hedge-aware causal detection combined), and the candidate now
reaches `pass` on its own technical merits, not merely on the human's forgiving read of a noisy
signal.

## Status

Validation complete. No preference was automatically changed. No production code was modified by
this validation step itself (the one code fix it surfaced — the negated-causal-claim false
positive — was committed separately, disclosed in `docs/
phase17_m7_4_2_causal_trigger_expansion_report.md`'s own addendum, before this validation document
was finalized).
