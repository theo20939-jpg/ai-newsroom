# Phase 17 M7.2 — Post-Calibration Validation Report

**Read-only validation. No production code was changed, no candidate was regenerated, no
`editorial_preference` was mutated, no artifact file was modified, no LLM call was made.** "Before"
(M7.1) results were computed by extracting `services/fact_safety.py`, `services/
candidate_fact_safety.py`, and `services/fact_safety_calibration.py` at their exact `checkpoint/
phase17-m7-1-fact-safety-calibration` content into a separate, isolated temp package (`git show
<checkpoint>:<path>`, imports redirected to itself) — never by modifying the real `services/`
directory, and never via `git stash` on the working tree (unlike the M7.2 report's own backtest
method) — chosen specifically because this task's own scope ("no production code changes") called
for the extra margin of not touching tracked files at all, even temporarily. Both "before" and
"after" pipelines were run against the exact same real event/research context (read from the
database, read-only) and the exact same baseline/candidate text (read from `scripts/
_phase17_stage2_candidate_results.json`, never written to). The temp package was deleted after use;
`git status` before and after this validation shows no change to any tracked file.

## Before / after table

| Case | Text | Raw status (before → after) | Raw severity (before → after) | Calibrated status (before → after) | Remaining flags (after) | Movement correct? |
|---|---|---|---|---|---|---|
| `2d35bad8` | baseline | pass → pass | — → — | pass → pass | none | ✅ correctly unaffected (no money/quantity claim present) |
| `2d35bad8` | candidate | pass → pass | — → — | pass → pass | none | ✅ correctly unaffected |
| `12ce8e52` | baseline | review → review | medium → medium | review → review | 3 entity flags (unchanged) | ✅ correctly unaffected (entity-only, out of M7.2 scope) |
| `12ce8e52` | candidate | review → review | low → low | review → review | 2 entity flags (unchanged) | ✅ correctly unaffected |
| `847618cd` | baseline | review → review | medium → medium | review → review | 1 entity flag (unchanged) | ✅ correctly unaffected (no money/quantity claim in baseline text) |
| **`847618cd`** | **candidate** | **fail → review** | **high → medium** | review → review (unchanged) | 2 entity + 1 causal flag | ✅ **numeric false positive eliminated at the source** |
| **`ac1f1ff5`** | **baseline** | **fail → review** | **high → medium** | review → review (unchanged) | 1 entity flag | ✅ **numeric false positive eliminated at the source** |
| **`ac1f1ff5`** | **candidate** | **fail → review** | **high → low** | review → review (unchanged) | 1 entity flag (low severity) | ✅ **numeric false positive eliminated at the source** |

Three rows show a real change; five are correctly unaffected (they never had a money/quantity claim
driving their status, so M7.2 — which scoped itself to exactly that claim class — correctly leaves
them untouched). Every changed row moved toward *less* severity, never more; no case moved toward
more scrutiny (consistent with the M7.2 report's own 281-draft backtest finding of 0 worsened
cases).

**A finding not previously called out this precisely**: `ac1f1ff5`'s **baseline** also improved
(`fail`/high → `review`/medium), not just its candidate. The 281-draft production backtest (M7.2
report) already showed this same draft (`f0c40711...`) moving `block`→`review` — this validation
confirms the same fix at the `CandidateFactSafetyAudit` level specifically, with the exact
before/after flag detail.

**Calibrated status did not change for any of the 4 cases** — it was already `review` for all of
them both before and after (correctly; calibration's own rescue rule was already reaching the right
top-line verdict). What changed is *how* that verdict is reached: before M7.2, `847618cd`'s
candidate and `ac1f1ff5`'s baseline/candidate all needed calibration's
`russian_inflection_or_quote_match` suppression rule to survive a raw `fail`/high — after M7.2, zero
suppressions are needed for any of the 4 cases (`suppressed: []` across the board). The signal is
now correct at the source, not rescued after the fact.

## Special review — `847618cd`

- **Numeric token claim no longer creates a false unsupported claim: confirmed.** The candidate's
  raw `numeric_flags` is `[]` after M7.2 (was `["unsupported:320,7 млн"]` before). The claim now
  resolves as `metric_quantity` (`320,7 млн токенов` → `("tokens", 320_700_000.0)`), matches the
  research-facts phrasing exactly, and is classified `supported` — it produces no finding at all.
- **Remaining flags are only entity/causal classes: confirmed.** The candidate's remaining raw
  flags are exactly `unsupported:Автономный ИИ-агент`, `unsupported:Агент Saul` (both entity-type,
  M7 discovery class #2, unaddressed by design) and one `causal_connector` flag (class #3, also
  unaddressed by design). No money, percentage, date, metric_quantity, or generic_quantity flag
  remains on this case.

## Special review — `ac1f1ff5`

- **Trillion parameter claim no longer creates a numeric false positive: confirmed.** Both
  baseline and candidate's raw `numeric_flags` are `[]` after M7.2 (were
  `["unsupported:2,8 трлн"]` / `["unsupported:2,8 трлн", "unsupported:2,8 трлн"]` before — the
  candidate had it twice, once each from title and body). The claim now resolves as
  `metric_quantity` (`("parameters", 2_800_000_000_000.0)`) and matches evidence exactly.
- **Remaining assessment reflects actual uncertainty: confirmed.** What's left is a single
  low-severity `uncertain:ИИ` entity flag on the candidate (down from a `high`-severity money flag
  plus the same entity concern before) and a single medium-severity `unsupported:Китайская
  ИИ-модель Kimi K3` entity flag on the baseline — both are genuine, pre-existing entity-matching
  observations (M7 discovery class #2), not numeric artifacts. The severity profile now honestly
  reflects "this is a specific-entity phrasing question," not "this looks like a fabricated
  trillion-scale number."

## False positives removed

Exactly the 3 numeric false positives identified across M7.1/M7.2's own investigation, now
confirmed gone at the raw-audit level (not just suppressed by calibration):
1. `847618cd` candidate: `"unsupported:320,7 млн"` (token count).
2. `ac1f1ff5` baseline: `"unsupported:2,8 трлн"` (parameter count).
3. `ac1f1ff5` candidate: `"unsupported:2,8 трлн"` ×2 (parameter count, title + body).

No other case in this 4-case sample had a numeric false positive to begin with (`2d35bad8` and
`12ce8e52` never had a money/quantity claim; `847618cd`'s baseline never mentioned the token count
at all — only the candidate did, since the candidate is the longer, more detailed text).

## Remaining risks (unchanged from the M7.2 report — restated here in this sample's own terms)

- **Entity matching (M7 discovery class #2)** is the only thing keeping `847618cd`'s candidate and
  both of `ac1f1ff5`'s texts above `pass`. Both entity flags in this 4-case sample
  (`"Автономный ИИ-агент"`/`"Агент Saul"`/`"Китайская ИИ-модель Kimi K3"`) are the same
  sentence-initial-capitalization / generic-descriptor-plus-name pattern already discussed in the
  Stage 1 acceptance packet and M7 discovery — unresolved, out of scope for M7.2.
- **Causal/hedge detection (class #3)** still flags `847618cd`'s honest uncertainty sentence
  ("...нельзя однозначно утверждать...") as `unresolved`, not because it's wrong to flag but
  because the underlying detector still can't distinguish a hedge from an unhedged causal claim
  reliably — also unaddressed by design.
- **Calibrated status is currently a coarser signal than the underlying flags** — all 4 cases sit
  at `review` regardless of whether 1 low-severity entity flag or 3 mixed-severity flags remain;
  a human reading only `calibrated_status` (not the flags themselves) would not see the real
  improvement this validation documents. This is a pre-existing characteristic of the calibration
  schema, not something this validation flags as new.

## Recommendation for M7.3

Consistent with the M7.2 report's own recommendation, restated with this validation's own
confirmation behind it: the numeric-claim fix is now verified correct and stable across both the
281-draft production set and this dedicated 4-case Stage 2 sample, with zero cases moving toward
more scrutiny anywhere. The next highest-value, lowest-risk target is **entity matching (class
#2)** — it is the single remaining blocker on 3 of the 4 Stage 2 cases reviewed here reaching
`pass`, and every flag observed in this sample is the same, already-diagnosed pattern (generic
descriptor bundled with a real proper noun, or sentence-initial capitalization mistaken for a
proper noun) rather than a new, undiagnosed failure mode. **M7.3 has not been started** — this
document contains no code change, and none was made to produce it.
