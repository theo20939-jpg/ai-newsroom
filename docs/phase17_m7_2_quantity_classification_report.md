# Phase 17 M7.2 — Quantity Classification Implementation Report

**Root cause fixed**: `services/fact_safety.py` used to type every number+magnitude match `"money"`,
whether or not a currency was actually present. A bare quantity ("320.7 million tokens", "2.8
trillion parameters") could never resolve (no currency to look up) and was therefore
unconditionally `unsupported`/HIGH regardless of whether it matched evidence — M7 discovery's own
class #1 bug, confirmed live in production data by this milestone's own backtest below.

## Design

Three claim buckets, decided by what immediately follows a number+magnitude match — never by NLP,
only by narrow, explicit, hand-curated word lists, matching every other rule already in this
module:

1. **Currency** — a currency symbol (`$`/`€`/`£`/`₽`) or a known currency word resolves exactly as
   before (`money` type, `_normalize_money()` unchanged). New: an **unrecognized currency-like
   term** (approved decision — "support currency-like patterns... do not rely only on hardcoded
   currency names") also resolves as `money`, via a new `_normalize_ad_hoc_currency()` — the
   unrecognized word itself becomes an ad hoc currency code, so two claims naming the *same*
   unrecognized term (e.g. "Korean Won"/"вон") can still be compared for equal amount via the
   existing `_money_matches()`, unchanged. No real-world currency code or conversion is ever
   guessed.
2. **Metric** (new, `metric_quantity`) — a recognized technology-metric unit word (tokens,
   parameters, users, requests, calls, operations — exactly M7.2's own approved scope, EN+RU
   inflected forms) resolves to `(unit_canonical, amount)` via a new `_normalize_metric_quantity()`
   / `_metric_matches()` pair, structurally parallel to money's own but with no currency lookup at
   all. Works both with a magnitude word ("320,7 млн токенов") and with a bare number ("1129
   вызовов" — no magnitude word required, since the metric-unit list itself is the narrow, safe
   signal).
3. **Generic** (new, `generic_quantity`) — a magnitude word with no resolvable currency and no
   recognized metric unit, OR a vague, numberless magnitude phrase ("billions of users",
   "миллиарды пользователей", "триллионы операций" — a new extraction pattern for this specific
   shape). Matched via normalized-substring containment (same rule `quote` already uses, never
   fuzzy).

**Severity — the actual mechanism implementing "unknown quantity → REVIEW, not FAIL"**:
`metric_quantity` stays HIGH-severity-when-unsupported (it is just as specific/fabricatable as
money once resolved — a real fabrication must still be caught). `generic_quantity` is capped at
MEDIUM (we genuinely don't know what's being counted) — which structurally can never trigger
`_draft_status()`'s BLOCK path (only `unsupported`+HIGH does), so an unresolvable quantity now
always lands at REVIEW, never FAIL, by construction, not by a probabilistic heuristic.

## Implementation

- **`services/fact_safety.py`**: `ClaimType` gained `metric_quantity`/`generic_quantity`; both
  severity tables updated. Removed `_MONEY_EXTRACT_PATTERN`'s old middle branch ("magnitude-word-
  anchored, no currency required" — the literal root cause). Added: `_METRIC_UNIT_WORD`/
  `_METRIC_UNIT_CANONICAL` (hand-curated, EN+RU), `_QUANTITY_EXTRACT_PATTERN` (number+magnitude+
  optional trailing text, disambiguated in Python afterward), `_BARE_METRIC_EXTRACT_PATTERN`
  (bare-number metric case), `_VAGUE_QUANTITY_PATTERN` (numberless "billions of X" case),
  `_normalize_metric_quantity()`/`_metric_matches()`, `_normalize_ad_hoc_currency()`,
  `_classify_quantity_trailing()`, `_extract_quantity_claims()`. `extract_claims()` and
  `_claim_matches_any()` extended to route the two new types. Also added full Russian magnitude
  words (миллион/миллиард/триллион + inflections — not just abbreviations) since the required
  "10 миллионов долларов" test case needed it and the gap was real (verified: it silently failed
  to extract at all before this fix, unrelated to money-vs-quantity classification).
- **`services/candidate_fact_safety.py`**: `metric_quantity`/`generic_quantity` findings bucket
  into `numeric_flags` (alongside money/percentage/date); `metric_quantity` added to the
  `high_severity_unsupported` check (a genuine metric fabrication must still escalate `Candidate
  FactSafetyAudit` to FAIL, exactly like money).
- **`services/fact_safety_calibration.py`**: `_sentence_claims()`'s fixed type tuple extended to
  include the two new types, so an `unhedged_forecast` sentence containing a metric/generic claim
  is checked consistently with every other claim type.

No entity matching, causal detection, scoring thresholds, or production prompts were touched. No
LLM call was made anywhere in this milestone. No production mode was activated.

## Bugs found and fixed during implementation (disclosed, not hidden)

Two real defects were found only by running the actual 281-draft production backtest (§below) —
neither was caught by the unit tests written first, which is exactly why the backtest was run
before declaring this done:

1. **Trailing-word bleed across sentence/clause boundaries.** The first implementation always used
   the *full* captured trailing text (up to 2 words) when building a money claim, even when the
   first word already resolved as a known currency word. On real production drafts this pulled in
   the first word of an unrelated *next sentence* ("5,2 млрд юаней\nКитайский...") or an unrelated
   word later in the *same* sentence ("9,2 млрд рублей за..."), breaking normalization and turning
   a real, matchable currency claim into a spurious `unsupported`/HIGH finding — flipping 4 real
   drafts from `pass`/`review` to `block`. Fixed by: (a) only using the single recognized currency/
   metric word when one is found (the 2-word capture is reserved for the ad hoc/unrecognized case,
   e.g. "Korean Won"), and (b) restricting the trailing capture to never span a newline (`[^\S\n]+`,
   matching `_ENTITY_RUN_PATTERN`'s own existing precedent).
2. **Vague-quantity pattern matched a following preposition as if it were the counted noun.**
   "Иск на миллионы после ранения" ("a lawsuit for millions after an injury") matched
   "миллионы после" as generic_quantity — "после" ("after") is a preposition, not what's being
   counted. Fixed by excluding a small, explicit stopword/preposition set (reusing the same list
   already built for the currency-vs-stopword check) from the word immediately following a vague
   magnitude term.

Both are covered by new, named regression tests (`test_known_currency_word_never_bleeds_a_second_
word_*`, `test_vague_quantity_excludes_a_following_preposition`) pinning the fixed behavior, plus
companion tests confirming the legitimate 2-word ad hoc-currency case and genuine vague-noun
detection still work.

## Before / after examples

| Case | Before | After |
|---|---|---|
| `$10 million.` | money, resolves | unchanged |
| `10 миллионов долларов` | not extracted at all (no abbreviation) | money, resolves — new gap fix |
| `0.7 trillion Korean Won` | money (extracted), fails to normalize → unsupported/HIGH | money, resolves via ad hoc currency code `"korean won"` |
| `320,7 млн токенов` | money, unsupported/HIGH regardless of evidence | metric_quantity, matches evidence exactly → supported |
| `2,8 трлн параметров` | money, unsupported/HIGH regardless of evidence | metric_quantity, matches evidence exactly → supported |
| `1129 вызовов инструментов` | not extracted at all | metric_quantity, matches evidence exactly → supported |
| `миллиарды пользователей` | not extracted at all | generic_quantity, REVIEW/medium if unmatched (never FAIL) |
| `триллионы операций` | not extracted at all | generic_quantity, REVIEW/medium if unmatched (never FAIL) |

## `847618cd` before/after

Raw `CandidateFactSafetyAudit` (not just the calibrated view M7.1 added):

| | Status | Severity | Numeric flags |
|---|---|---|---|
| M7.1 (before M7.2) | FAIL | high | `unsupported:320,7 млн` |
| **M7.2 (after)** | **REVIEW** | **medium** | **none** |

The token-count claim now resolves as `metric_quantity`, matches the research-facts phrasing
exactly, and is `supported` — it no longer appears as a flag at all. Raw status improves directly,
without needing calibration's `russian_inflection_or_quote_match` rescue rule (which M7.1 relied
on and which is now a no-op for this specific case — confirmed by
`test_847618cd_calibration_has_nothing_left_to_suppress`). What's left at REVIEW/medium: the two
entity flags (M7 discovery class #2, unaddressed, out of scope for M7.2) and the causal flag
(class #3, also unaddressed) — confirmed unchanged by a dedicated regression test.

## `ac1f1ff5` (Kimi K3, draft `f0c40711...`) before/after

Real production backtest result: **`block` → `review`**. The `2,8 трлн` claim no longer appears as
a money-type unsupported/HIGH finding (it now correctly resolves as `metric_quantity` and matches
research evidence exactly). What remains: one pre-existing, unrelated entity flag
(`unsupported:Китайская ИИ-модель Kimi K3`, medium severity, out of scope for this milestone).

## `bed6f564` (Samsung mobile loss, "0.7 trillion Korean Won") before/after

Real production backtest result: **`block` → `pass`**. Fully resolved — this was the exact
motivating example from the M7.2 plan's "Failure examples" §3. The claim now correctly resolves as
an ad hoc-currency money claim and matches the source article's own identical phrasing
("0,7 трлн вон (~487 млн долларов)").

## Stage 2 four candidate cases (recomputed under current code, read-only, zero LLM calls)

| Case | Baseline before→after | Candidate before→after |
|---|---|---|
| `2d35bad8` | pass → pass (unchanged) | pass → pass (unchanged) |
| `12ce8e52` | review → review (unchanged) | review → review (unchanged) |
| `847618cd` | review → review (unchanged) | **fail → review** |
| `ac1f1ff5` | review → review (unchanged) | review → review (unchanged) |

Only `847618cd`'s candidate changes — exactly the case this whole M7 arc was investigating. The
other three never had a money/quantity-type flag driving their status, so they are correctly
unaffected.

## Backtest — 281-draft real production set (read-only, zero LLM calls)

Ran `scripts/phase15_m5_fact_safety_backtest.py` twice: once against pre-M7.2 code (`git stash` on
`services/fact_safety.py` only, back to the M7.1 checkpoint `803b141`, restored immediately after
and confirmed back in place via `git diff`), once against the final, bug-fixed M7.2 code. Saved as
`scripts/_phase17_m7_2_backtest_before.json`/`_after.json` (untracked, matching every prior
milestone's own convention).

| | Before | After |
|---|---|---|
| Sample size | 281 | 281 |
| `pass` | 102 | 104 |
| `review` | 97 | 101 |
| `block` | 82 | 76 |

**6 drafts changed status — all 6 improved, 0 worsened**:

| draft_id | Title | Before → After | Cause |
|---|---|---|---|
| `eae93502...` | Moonshot AI $3.5B/$35B raise | block → review | spurious money finding (a bug-#1 artifact) removed |
| `877b5f77...` | Telegram Australia lawsuit | block → **pass** | spurious "54,6 млн" finding removed entirely |
| `bed6f564...` | Samsung mobile loss (Won) | block → **pass** | ad hoc currency fix (target case) |
| `399d7f7c...` | Apple 1.5B paid subscriptions | block → review | now matches evidence via ad hoc term, uncertain not unsupported |
| `f0c40711...` (`ac1f1ff5`) | Kimi K3 (2.8T params) | block → review | metric_quantity fix (target case) |
| `c27472c9...` | WSJ $7T AI investment bubble | block → review | now correctly matches evidence, no longer unsupported |

**Zero movement toward more scrutiny anywhere in the 281-draft set** — verified empirically by
diffing every draft's status, not assumed. `e0f70edd...` (BNY $8.6T, the one case already at
`review`/`uncertain` before this milestone) stays exactly `review`/`uncertain`, unchanged — a
useful stability check, not just an improvement count.

## Tests

- `tests/test_phase17_m7_2_quantity_classification.py` — **40 tests**, covering the full required
  matrix (currency PASS ×6, metric PASS ×6, generic REVIEW ×6, money-format regression ×2,
  false-negative safety ×4, no-double-extraction ×3, plus the 2 real bugs found via backtest ×5,
  each with a companion test confirming the fix didn't regress the legitimate case it was
  protecting).
- `tests/test_phase17_m7_1_fact_safety_calibration.py` — 2 of its 21 tests were **updated** (not
  broken silently): they pinned M7.1-era behavior for the trillion/`847618cd` cases that M7.2
  intentionally, correctly supersedes. Both updates are disclosed in-place with a comment
  explaining exactly what changed and why. All 21 pass.
- Combined (`test_fact_safety.py` + `test_fact_safety_calibration.py` +
  `test_phase17_stage2_candidate_generation.py` + both M7.1/M7.2 files): **170 passed, 2 failed**
  (the same pre-existing baseline, `test_off_mode_leaves_quality_step_result_completely_unchanged`
  / `test_shadow_mode_enriches_quality_result_and_detects_unsupported_claim`).
- **Full regression suite** (`python -m pytest tests/ -q`): **19 failed, 2071 passed, 147 warnings
  in 2373.22s**. The 19 failures are **byte-for-byte identical** to the documented baseline
  (`docs/phase17_final_engineering_completion_report.md`) — **zero new regressions**. (An earlier
  run, launched before the two backtest-found bugs above were fixed, showed a 20th failure in
  `tests/test_analysis_worker_main.py::test_cycle_level_infrastructure_failure_logs_and_waits_for_
  next_interval` — confirmed, via three separate re-runs, to be pre-existing timing flakiness in an
  `asyncio.sleep(0.1)`-based synchronization the test itself uses, in a file this milestone never
  touched (`git diff` confirms zero changes to `worker/analysis_main.py`/its test file) — not a
  regression from this work, disclosed rather than silently discarded.)
- `python -m ruff check` on every touched file: **all checks passed**.
- `python -m mypy` on the three modified service modules: **no issues found**.
- `python -m scripts.phase17_cutover_preflight`: **OVERALL PASS**, all Phase 17 modes confirmed
  still off.

## False-negative analysis

Every false-negative-safety requirement explicitly named in the authorization is covered by a
named, passing test:
- A fabricated metric claim with the same unit but a different number than evidence → still FAIL/
  HIGH (`test_false_negative_safety_fabricated_metric_wrong_number_same_unit`).
- A fabricated metric claim with zero supporting evidence anywhere → still FAIL/HIGH
  (`test_false_negative_safety_fabricated_metric_no_evidence_at_all`).
- A fabricated, currency-bearing claim → still FAIL/HIGH, never downgraded by the new
  disambiguation logic (`test_false_negative_safety_real_currency_fabrication_not_downgraded`).
- The 281-draft backtest itself is the strongest empirical evidence: **zero of 281 real drafts
  moved toward a less-cautious verdict** after this change, in either backtest run (the buggy
  intermediate version was caught and fixed precisely because it briefly violated this).

## Remaining risks (disclosed, not fixed here — out of scope for M7.2 by design)

1. **Currency-word coverage is still incomplete beyond the ad hoc mechanism.** The ad hoc-currency
   path requires the *exact same literal word* in both draft and evidence — it does not know that
   "Won" and "вон" name the same real-world currency across languages (unlike the hand-curated
   `_ENTITY_ALIAS_GROUPS` precedent for a small set of entities). A genuinely-sourced foreign
   currency phrased differently between draft and evidence would still not match. Expanding
   `_CURRENCY_SYMBOLS` directly (matching the M5.3 CNY precedent) remains a separate, narrower,
   lower-risk option for specific high-frequency currencies, not attempted here.
2. **Entity matching (M7 discovery class #2) and causal/hedge detection (class #3) remain
   unaddressed** — confirmed unchanged on `847618cd` by a dedicated regression test. These need
   their own scoped milestone with the same before/after-backtest discipline this one used.
3. **The metric-unit and vague-magnitude word lists are deliberately narrow** (six unit families;
   Russian "тысячи" excluded from the vague pattern entirely due to a genuine grammatical homograph
   with the number-anchored genitive-singular form — disclosed in the code, not silently dropped).
   An unlisted unit or an unusual vague-magnitude phrasing falls through to `generic_quantity`
   (the safe direction) or goes unextracted entirely, never the unsafe direction.
4. **`test_analysis_worker_main.py`'s timing flakiness** (see Tests §) is pre-existing and
   unrelated to this work, but is now disclosed here rather than silently observed and dropped —
   worth a future, separate look if it recurs.

## Recommendation for M7.3

Not started automatically, per instruction. If a future M7.3 is authorized, the highest-value next
step is closing risk #1 (currency coverage) since it's the narrowest, lowest-risk remaining piece
in this same problem family; classes #2/#3 (entity/causal) are larger, separate efforts each
deserving their own scoped milestone and backtest, as M7's own original discovery report already
recommended.
