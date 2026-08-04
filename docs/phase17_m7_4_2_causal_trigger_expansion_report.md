# Phase 17 M7.4.2 — Causal Trigger Expansion Report

**Only started after M7.4.1 was committed and its own tests passed, per M7.4 discovery's own
explicit sequencing requirement.** No architecture change, no LLM call, no feature flag touched,
no production behavior change.

## What was added

`services/candidate_fact_safety.py::_CAUSAL_RE` gained the missing causal-verb constructions M7.4
discovery identified as invisible:

- Russian: `привело к` / `приводит к` (as requested) plus grammatical siblings of the same
  construction (`привела к`, `привели к`, `привёл к`, `приводят к` — all genders/numbers of the
  same past/present tense, narrow and hand-curated, never a general conjugation rule).
- Russian: `вызвало` (as requested) plus siblings `вызвал`/`вызвала`/`вызвали`.
- Russian: `стало причиной` (as requested) plus siblings `стал причиной`/`стала причиной`/`стали
  причиной`.
- English: `caused`, `led to`, `resulted in` (exactly as requested).

## Why sequencing mattered — proven, not assumed

Every hedged example from M7.4.1's own test suite was re-tested after adding the new triggers.
Three of the five now genuinely match `_CAUSAL_RE` (they weren't reachable before):
`"Нельзя утверждать, что X привело к Y"`, `"Нет доказательств, что X вызвало Y"`, `"Поэтому нельзя
сделать вывод, что X стало причиной Y"`. All three are **still correctly excluded** — because
M7.4.1's hedge check was already in place before this milestone started. A dedicated test
(`test_sequencing_requirement_would_fail_without_hedge_guard`) asserts the raw `_CAUSAL_RE` match
directly, proving these sentences *would* have been new false positives had the trigger words been
added without the hedge guard first — this was not a theoretical risk, it is the literal mechanism
this milestone's own examples demonstrate.

## Real backtest — 281-draft production set (read-only, zero LLM calls)

No existing backtest script exercises the causal detector (`scripts/
phase15_m5_fact_safety_backtest.py` only calls `services.fact_safety.evaluate_fact_safety()`,
which never invokes causal/hedge detection — that logic lives exclusively in `services/
candidate_fact_safety.py`). A new, one-off, read-only script
(`scripts/_phase17_m7_4_2_causal_backtest.py`, untracked, matching every prior milestone's own
scratch-artifact convention) was written to run `evaluate_candidate_fact_safety()` over the same
281 real `ContentDraft` rows, using each draft's own real title/body as "candidate" text against
its real event/research context.

Ran twice: once against pre-M7.4.2 code (`git stash` on `services/candidate_fact_safety.py` only,
back to the M7.4.1 commit `88177e8`, restored immediately after and confirmed via `git diff`), once
against the final M7.4.2 code.

| | Before | After |
|---|---|---|
| Sample size | 281 | 281 |
| Drafts with ≥1 causal flag | 24 | 24 |
| Total causal flags | 25 | 26 |
| **New drafts flagged (had none before)** | — | **0** |
| **Drafts that lost their flag** | — | **0** |

**Zero new drafts were flagged, and zero existing flags disappeared.** The one extra flag (25→26)
landed on a draft that *already* had a different flag (`unhedged_forecast`) — it gained a second,
independent `causal_connector` flag from the new vocabulary (`"...однако вызвал опасения"` — "...
however it caused concerns"), inspected directly and confirmed to be a genuine, correctly-detected
causal assertion, not a false positive.

## A real false positive found and fixed via this same backtest (disclosed, not hidden)

The first version of this milestone's change *did* introduce one new false positive, found only
by running the backtest above, not by the test suite written first: **`"Данные не подтверждают,
что кампания стала причиной финансового результата"`** ("The data does not confirm that the
campaign was the cause of the financial result") was newly flagged. Root cause: the epistemic-
limitation pattern's existing `не подтвержден\w*` only covers the **passive participle** form
("не подтверждено"/"не подтверждена" — "is/are not confirmed"); the sentence uses the **active
verb** form (`"не подтверждают"` — "[the data] does not confirm"), a different Russian stem
(`подтвержда-` vs `подтвержден-`) the pattern did not yet cover.

**Fixed before this milestone was considered complete**: added `не\s+подтвержда\w*` alongside the
existing `не\s+подтвержден\w*`, in both independent copies (`services/candidate_fact_safety.py`
and `services/fact_safety_calibration.py`, kept in sync by hand as already established in M7.4.1).
Re-ran the backtest after the fix: the false positive is gone, and the fix introduced no further
side effects (0 new / 0 removed, confirmed above — this table already reflects the fixed code).
Per this project's own "never merge a known false positive" discipline, this was fixed
immediately, not deferred to a follow-up milestone, and is pinned with its own dedicated regression
test (`test_real_backtest_false_positive_active_verb_hedge_now_fixed`).

## Addendum — a second false positive found during Phase 17's final Stage 2 validation

After this milestone was committed (`300c042`) and checkpointed (`checkpoint/phase17-m7-4`), the
final Phase 17 Stage 2 validation pass (`docs/phase17_final_completion_report.md`) surfaced one
more real false positive on the actual, already-recorded `847618cd` candidate text — not caught by
the 281-draft backtest above because that backtest samples real *production baseline* drafts, and
this sentence only exists in Stage 2's own AI-generated *candidate* text:
**`"привлеченные пользователи не привели к зафиксированному заработку"`** ("the acquired users did
NOT lead to recorded earnings") — a **negated** causal claim (explicitly asserting the *absence* of
a causal link), which matched the new `привел[оаи]\s+к` trigger exactly like an unhedged positive
assertion would.

**Fixed immediately, in the same discipline as the fix above**: added a negative lookbehind
(`(?<!не\s)` / `(?<!not\s)`) directly on each verb-based trigger (`привел[оаи] к`/`вызвал[оаи]?`/
`стал[оаи]? причиной`/`caused`/`led to`/`resulted in`) — scoped only to these new verb triggers,
not the original connector words, which do not have this negation ambiguity in idiomatic use.
Verified: the negated form is now correctly excluded, the positive (non-negated) form of the exact
same verb remains correctly flagged (false-negative safety confirmed), the full test suite (223
passed / 2 pre-existing baseline failures) and the 281-draft backtest (0 new / 0 removed, re-run
after this fix) both remain clean. Pinned with two new tests
(`test_real_stage2_validation_negated_causal_claim_not_flagged`,
`test_negation_guard_does_not_suppress_the_positive_form`).

## False-negative safety (verified)

`test_end_to_end_genuine_unsupported_causal_claim_now_caught` confirms the exact classification-A
example from the M7.4 authorization (`"Компания внедрила AI, что привело к росту прибыли"` —
previously invisible per M7.4 discovery) is now correctly flagged end-to-end.
`test_end_to_end_existing_true_positive_unaffected` confirms the pre-existing M4/M5-era causal
true positive (using an original connector word, not the new vocabulary) remains flagged exactly
as before — the new triggers are additive, not a replacement.

## Tests

`tests/test_phase17_m7_4_2_causal_trigger_expansion.py` — **17 tests**: 7 direct positive-detection
pins for the exact requested examples (RU + EN) plus 2 grammatical-sibling checks, 4 sequencing-
proof tests (hedged variants of the new triggers still correctly excluded) plus 1 direct proof the
raw regex *would* have matched without the guard, 2 end-to-end false-negative-safety tests, and 1
regression pin for the active-verb-hedge false positive found and fixed during this milestone's
own backtest. Three stale M7.4.1 tests (which explicitly pinned "not yet detectable, M7.4.2's own
scope" for these exact three Russian examples) were consolidated into one updated test in `tests/
test_phase17_m7_4_1_causal_hedge_calibration.py`, disclosed in-place.

Combined (`test_fact_safety.py` + `test_fact_safety_calibration.py` + `test_phase17_stage2_
candidate_generation.py` + M7.1/M7.2/M7.3/M7.4.1/M7.4.2 files): **220 passed, 2 failed** (the same
pre-existing baseline). `python -m ruff check` on every touched file: all checks passed. `python -m
mypy` on both modified service modules: no issues found. `python -m scripts.phase17_cutover_
preflight`: OVERALL PASS, all Phase 17 modes confirmed still off.

## Status

Committed separately from M7.4.1. This closes M7 discovery's own class #3 (causal/hedge) — the
last of the three false-positive classes identified back in the original M7 discovery report
(numeric — M7.2, entity — M7.3, causal/hedge — M7.4.1+M7.4.2).
