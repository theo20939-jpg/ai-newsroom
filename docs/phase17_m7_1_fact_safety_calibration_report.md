# Phase 17 M7.1 — Fact Safety Calibration Implementation Report

**Scope, strictly as authorized**: (A) route Stage 2 candidate generation through the existing,
already-tested `calibrate_fact_safety()` layer; (B) add the missing `трлн`/`trillion` quantity
magnitudes. No other Fact Safety logic changed — entity matching, causal detection, scoring
thresholds, and the money-without-currency normalization gap (M7 discovery's own class #1) are all
explicitly untouched. No LLM call was made. No production mode was activated. Stage 3 was not
started.

## Changes

### A — Stage 2 now computes calibrated Fact Safety alongside raw

**File**: `scripts/phase17_stage2_candidate_generation.py`.

- New import: `services.fact_safety_calibration.calibrate_fact_safety`.
- `_new_record()` gained two new fields, both `None` by default:
  `baseline_calibrated_fact_safety`, `candidate_calibrated_fact_safety`.
- Both places that call `evaluate_candidate_fact_safety()` (baseline text, candidate text) now
  additionally call `calibrate_fact_safety()` on that same raw audit object and store the result in
  the new field. **The raw `baseline_fact_safety`/`candidate_fact_safety` fields are computed and
  stored exactly as before — never overwritten, never removed.** Both raw and calibrated views are
  now present, independently, side by side.
- This mirrors the exact calibration path production's own shadow pipeline already uses
  (`capabilities/executor.py` → `calibrate_fact_safety()`), which M7's discovery found Stage 2 had
  never been wired through at all.

### B — трлн/trillion added to the magnitude table

**File**: `services/fact_safety.py`.

- `_MONEY_MAGNITUDE`: added `"trillion": 1e12, "трлн": 1e12`.
- `_MONEY_MAGNITUDE_WORD`: added `trillion|трлн` to the regex alternation (this constant is shared
  by both the money-normalization pattern and the money-extraction pattern, so both picked up the
  addition automatically — no separate edit needed for extraction).
- Deliberately **not** added: single-letter `T`/`tn` shorthand — not requested, and higher
  collision risk with ordinary words than the existing `b`/`m`/`k` shorthand already carries.

## Why scoped this way

M7's discovery report (`docs/phase17_m7_fact_safety_calibration_discovery.md`) found four related
issues. Fix A (calibration wiring) and fix B2 (трлн addition) were chosen as the *lowest-risk*
subset because:
- Fix A reuses machinery that is already implemented, already tested (20 tests in `tests/
  test_fact_safety_calibration.py`, all passing before this milestone touched anything), and
  already validated against a 269-case backtest when it was built for production's own shadow
  pipeline (M5). Wiring it into a second call site changes *what Stage 2 reports*, never *how
  calibration itself decides* anything.
- Fix B2 is a pure, narrow addition to a lookup table — the same shape as the M5.3 calibration's
  own prior addition of Yuan/CNY/RMB to the currency table, already a proven-safe pattern in this
  codebase.
- Fixes B (money-without-currency normalization) and C/D (entity bundling, causal/hedge detection)
  all require changing matching *logic*, not just adding table entries — each needs its own
  before/after backtest discipline and a dedicated false-negative regression fixture, which M7's
  own recommendation explicitly deferred past this milestone.

## Before / after: `847618cd`

| | Raw status | Raw severity | Numeric flags | Entity flags | Causal flags |
|---|---|---|---|---|---|
| **Before M7.1** | fail | high | `unsupported:320,7 млн` | `unsupported:Автономный ИИ-агент`, `unsupported:Агент Saul` | `causal_connector: Поэтому...` |
| **After M7.1 (raw, unchanged)** | fail | high | `unsupported:320,7 млн` | `unsupported:Автономный ИИ-агент`, `unsupported:Агент Saul` | `causal_connector: Поэтому...` |
| **After M7.1 (calibrated, new)** | **review** | medium | suppressed (`russian_inflection_or_quote_match`) | both survive as `true_positive` | survives as `unresolved` |

Exactly as expected and as M7 discovery predicted: **raw stays FAIL/high (unchanged, as required —
fix A never touches raw detection), calibrated improves to REVIEW/medium** via calibration's own
already-existing `russian_inflection_or_quote_match` suppression rule (it independently rediscovers
that "320,7 млн" is present, in fuzzy-normalized form, in the combined source+research text — no new
suppression rule was written for this milestone). The two entity flags and the one causal flag
**remain unresolved after calibration** — this is the known, disclosed limitation from M7 discovery
(classes #2/#3), out of scope here, not a defect in this milestone's own work.

## Before / after: real production dataset (281 drafts, read-only, zero LLM calls)

Ran `scripts/phase15_m5_fact_safety_backtest.py` (existing, read-only, LLM-free tool) twice: once
against the pre-fix code (`git stash` on `services/fact_safety.py` only, then restored — confirmed
via `git diff` that the fix was back in place before continuing), once against the post-fix code.
Saved as `scripts/_phase17_m7_1_backtest_before.json` / `_after.json` (untracked scratch, not
committed, same convention as every prior milestone's own backtest artifact).

| | Before | After |
|---|---|---|
| Sample size | 281 | 281 |
| `pass` | 104 | 102 |
| `review` | 98 | 97 |
| `block` | 79 | 82 |
| `money`-type findings | 19 | 27 (+8, all трлн/trillion) |

**4 drafts changed overall status** — all four moved *toward more scrutiny*, none moved toward
less (no `block`→`review` or `review`→`pass` transition occurred anywhere in the dataset):

| draft_id | Title | Claim | Currency present | Before → After |
|---|---|---|---|---|
| `e0f70edd...` | BNY blockchain ($8.6T) | `$8,6 трлн.` | yes | pass → review (matched research paraphrase as `uncertain`) |
| `c27472c9...` | WSJ AI investment bubble | `$7 трлн` (×2) | yes | review → block (currency resolved correctly; claim itself found no matching evidence — a genuine new catch, not a normalization artifact) |
| `bed6f564...` | Samsung mobile loss (0.7T) | `0,7 трлн` | **no** | pass → block |
| `f0c40711...` (`ac1f1ff5`) | Kimi K3 (2.8T params) | `2,8 трлн` | **no** | review → block |

**Two of the four (`e0f70edd`, `c27472c9`) are genuine, correct improvements** — a currency-bearing
trillion-scale claim that was previously invisible to Fact Safety is now properly extracted,
normalized, and checked against evidence. **Two of the four (`bed6f564`, `f0c40711`) are new
instances of the already-disclosed currency-less-quantity normalization gap** (M7 discovery class
#1, explicitly out of scope for this milestone) — a bare quantity with no currency word still
cannot resolve via `_normalize_money()`, so it is unconditionally treated as `unsupported`/`high`
regardless of whether it is true. This was foreseeable and is disclosed here, not hidden: adding
трлн detection without also fixing the underlying currency-requirement makes this specific pattern
newly visible wherever it occurs at trillion scale, exactly as it already existed at million/
billion scale before this milestone.

**No false negatives were introduced** — verified empirically, not just reasoned about: zero drafts
in the full 281-draft dataset moved toward a *less* cautious verdict after this change.

## Tests

New file: `tests/test_phase17_m7_1_fact_safety_calibration.py` — 21 tests, all passing:
- 3 tests proving trillion-scale detection works with a currency present (English and Russian),
  and that extraction now occurs where it previously did not.
- 1 test pinning the known, disclosed limitation (bare trillion quantity, no currency, still fails
  to normalize) — documented as expected, not silently left for a future session to rediscover.
- 8 tests re-asserting every existing money-format case from `tests/test_fact_safety.py::
  test_money_normalization_formats` is byte-for-byte unchanged.
- 1 false-negative-safety test: a fabricated trillion-scale claim *with* a currency, not present in
  evidence, is still correctly flagged `fail`/`high`.
- 4 tests pinning the real `847618cd` before/after behavior described above, using the real,
  persisted `NewsEvent.content` (fetched once, read-only, hardcoded as a fixture — not re-queried
  at test time).
- 1 structural test confirming `calibrate_fact_safety()` never mutates the raw audit object it
  receives.
- 3 supporting tests for the wiring's own correctness (details above).

Full validation run:
```
tests/test_fact_safety.py + tests/test_fact_safety_calibration.py +
tests/test_phase17_stage2_candidate_generation.py + tests/test_phase17_m7_1_fact_safety_calibration.py
  -> 130 passed, 2 failed
```
The 2 failures (`test_off_mode_leaves_quality_step_result_completely_unchanged`,
`test_shadow_mode_enriches_quality_result_and_detects_unsupported_claim`) are the same,
already-documented pre-existing baseline failures present before this milestone touched anything
(`docs/phase17_final_engineering_completion_report.md`) — **zero new failures**.

`python -m scripts.phase17_cutover_preflight` → **OVERALL: PASS**, including
`feature_modes_safe_default: all Phase 17 candidate-generation/enforcement modes off` — confirms no
config/mode drift.

## Known remaining issues (unchanged from M7 discovery, not addressed here by design)

1. **Money-without-currency normalization** (discovery class #1) — a bare quantity (any magnitude,
   not just трлн) with no currency word still cannot resolve, and is unconditionally treated as
   `unsupported`. This milestone's own backtest (§"Before/after: real production dataset") shows
   this pattern newly manifesting at trillion scale for 2 real drafts — direct, current evidence
   this fix is now higher-priority than before, since M7.1 made the gap more visible, not less.
2. **Entity matcher multi-word bundling** (discovery class #2) — `847618cd`'s two entity flags
   still survive calibration untouched; confirmed unchanged by this milestone's own test #`test_847618cd_entity_and_causal_flags_survive_calibration_known_remaining_issue`.
3. **Causal-connector/hedge detection gap** (discovery class #3) — the same case's causal flag
   still survives as `unresolved`; also confirmed unchanged.
4. Stage 2's newly-added calibrated fields are **not yet consumed anywhere** — the human comparison
   packet (`docs/phase17_stage2_human_comparison_packet.md`) and decision result
   (`docs/phase17_stage2_human_decision_result.md`) were both produced *before* this milestone and
   still reflect only raw Fact Safety numbers. Regenerating those documents, or amending them with
   the calibrated view, was not requested and was not done here.

## Recommendation for M7.2

**Should begin, but scoped narrowly again, one fix at a time with its own before/after backtest**:
priority order — (1) the money-without-currency normalization fix (class #1), since this
milestone's own real-data backtest just demonstrated it is an active, present-day source of new
`block`-tier false positives, not a hypothetical; (2) entity multi-word bundling (class #2); (3)
causal/hedge detection widening (class #3). Each should follow the exact discipline this milestone
used: a real before/after backtest across all 281 (or however many then exist) production drafts,
an explicit false-negative regression test, and a written report before the next fix starts. **M7.2
has not been started by this document** — no code beyond fixes A/B exists yet for classes #1/#2/#3.
