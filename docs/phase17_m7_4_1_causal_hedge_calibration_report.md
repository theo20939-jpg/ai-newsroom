# Phase 17 M7.4.1 — Hedge-Aware Causal Detection Report

**Scope, strictly as authorized: hedge-awareness only. No new causal vocabulary added — `_CAUSAL_RE`'s
trigger word list is byte-for-byte unchanged.** No architecture change, no LLM call, no feature
flag touched, no production behavior change.

## What was fixed

Two files, both already part of the causal/hedge pipeline (no new modules):

1. **`services/candidate_fact_safety.py`** — added a new, widened `_EPISTEMIC_LIMITATION_RE`
   pattern and applied it directly in `_scan_qualitative_flags()`'s causal-connector check:
   `if _CAUSAL_RE.search(sentence) and not _EPISTEMIC_LIMITATION_RE.search(sentence)`. This
   mirrors a pattern already present in the same function for `unhedged_forecast`
   (`_FORECAST_RE.search(sentence) and not _HEDGE_RE.search(sentence)`) — the causal check simply
   never had the equivalent guard until now. This is the **raw-detector fix** (M7.4 discovery's own
   "Piece 1").
2. **`services/fact_safety_calibration.py`** — widened the existing `_EPISTEMIC_LIMITATION_RE` to
   the same pattern, kept as an independent second copy on purpose (documented in both files' own
   comments): the calibration layer's suppression rule must keep working for a `causal_flags` list
   constructed directly (every existing calibration test does exactly this), not only one produced
   by the now-updated raw detector.

The widened pattern adds, over the previous version:
- Tolerates 0-2 intervening words between a trigger and its verb (`нельзя ОДНОЗНАЧНО утверждать`)
  — the exact, previously-disclosed-but-unfixed `847618cd` gap (first identified in M7.2's own
  plan as "Fix D", never shipped until now).
- New standalone triggers: `неясно`, `непонятно`, `неизвестно`.
- New construction: `нельзя сделать вывод` (in addition to the existing `нельзя утвержда*`/`нельзя
  считать установленным`).
- New: `нет доказательств` (alongside the existing `нет оснований`).
- English additions: `no evidence that/for`, `unclear whether`, `it is unclear`.

## Real examples (all verified live, not assumed)

| Text | Before | After |
|---|---|---|
| `Нельзя утверждать, что X привело к Y.` | not flagged (no current trigger word reaches it) | not flagged — unchanged, confirmed |
| `Неясно, привело ли X к Y.` | not flagged (same reason) | not flagged — unchanged, confirmed |
| `Нет доказательств, что X вызвало Y.` | not flagged (same reason) | not flagged — unchanged, confirmed |
| `По данным компании, неизвестно, повлияло ли X на Y.` | not flagged (same reason) | not flagged — unchanged, confirmed |
| **`Поэтому нельзя сделать вывод, что X стало причиной Y.`** | **flagged** (`Поэтому` is an existing trigger) — the one active, reproducible false positive | **not flagged** — fixed |

**Important, verified finding carried over from M7.4 discovery**: four of the five required
examples were never actually reaching the detector at all, because none of `_CAUSAL_RE`'s current
trigger words (`поэтому`/`это означает`/`в результате`/`следовательно`/`as a result`/`this
means`/`that's why`) appear in them — `"привело к"`/`"вызвало"`/`"повлияло"` are simply not yet
recognized as causal constructions (that is M7.4.2's own, separate scope). Only the fifth example
(opening with `Поэтому`) was a live bug; it is now fixed.

The three "must remain detectable" examples (`X привело к Y`, `X вызвало снижение`, `Это стало
причиной роста`) are **explicitly and deliberately still not flagged** — pinned with their own
tests, each labeled "out of scope for M7.4.1," so a future reader does not mistake the absence of
a flag here for a bug. They become detectable only once M7.4.2 adds the missing trigger words.

## The real `847618cd` case — fully resolved

This is the single sentence this whole M7 arc has tracked from Stage 2's original human-reviewed
candidate: *"Поэтому по этим данным нельзя однозначно утверждать, что именно потерпело неудачу —
агент или сам эксперимент."*

| Milestone | Raw status | Raw severity | Remaining flags |
|---|---|---|---|
| Stage 2 (pre-M7) | fail | high | numeric (token count) |
| M7.1 (calibration wiring) | fail | high | numeric — calibration rescues to review/medium |
| M7.2 (quantity classification) | review | medium | 2 entity flags |
| M7.3 (entity prefix stripping) | review | low | 1 causal flag |
| **M7.4.1 (this milestone)** | **pass** | **none** | **none** |

Verified directly against the real, already-recorded candidate text, event content, and research
facts (the same fixture data used throughout M7.1-M7.3's own test suites) — not a synthetic
example. `847618cd`'s candidate now has **zero flags of any kind**, raw or calibrated.

## False-negative safety (verified)

The existing calibration-layer fixture `test_unsupported_causal_claim_retained` (`"Это означает
крах всей отрасли полупроводников немедленно"` — a genuine unhedged causal assertion using an
*existing* trigger word, no hedge language present) is re-pinned at the raw-detector level and
confirmed still flagged, both via direct `_scan_qualitative_flags()` call and end-to-end through
`evaluate_candidate_fact_safety()`. The widened epistemic-limitation pattern was also directly
tested against unrelated causal text (`"Компания объявила о росте прибыли"`,
`"Это означает крах всей отрасли"`) to confirm it does not spuriously match ordinary sentences.

## Tests

`tests/test_phase17_m7_4_1_causal_hedge_calibration.py` — **19 tests**: 5 direct-detector pins for
the required "must not flag" examples, 3 explicit "not yet in scope" pins for the "must remain
detectable" examples (labeled as M7.4.2's own future responsibility), 2 false-negative-safety
pins (raw + end-to-end), 6 direct regex tests for the widened `_EPISTEMIC_LIMITATION_RE` (adjacency
tolerance, new standalone triggers, existing-phrase regression, and a false-positive-of-the-fix
check), 2 calibration-layer parity tests (confirming the independent second copy stays in sync),
and 1 end-to-end synthetic-`847618cd`-shaped test reaching `pass`.

Combined (`test_fact_safety.py` + `test_fact_safety_calibration.py` + `test_phase17_stage2_
candidate_generation.py` + M7.1/M7.2/M7.3/M7.4.1 files): **206 passed, 2 failed** (the same
pre-existing baseline). Three M7.1-era tests were **updated** (not silently broken) to reflect the
real, now-complete resolution of `847618cd` — each change disclosed in-place with a comment
explaining exactly what changed and why; a new test
(`test_847618cd_fully_resolved_after_m7_4_1_no_flags_of_any_kind`) replaces the old "known
remaining issue" framing now that there is none left for this case.

`python -m ruff check` on every touched file: all checks passed. `python -m mypy` on both modified
service modules: no issues found.

## Backtest

Not run for M7.4.1 — the 281-draft production backtest (`scripts/phase15_m5_fact_safety_backtest.py`)
exercises `services.fact_safety.evaluate_fact_safety()` only, which never calls the causal/hedge
detector at all (that logic lives exclusively in `services/candidate_fact_safety.py`, used by
Stage 2 tooling, not the production shadow pipeline). A real backtest against
`evaluate_candidate_fact_safety()` is explicitly required for **M7.4.2** (trigger expansion, where
new false positives/negatives are a genuine risk); M7.4.1's own real-world validation is the fully
verified `847618cd` resolution above plus the 19 passing tests, which is proportionate to this
milestone's narrow scope (hedge-awareness only, zero new trigger words, hence no new detection
surface to backtest).

## Status

Committed separately from M7.4.2 (which has not started). No feature flag changed, no LLM call
made, no production behavior affected.
