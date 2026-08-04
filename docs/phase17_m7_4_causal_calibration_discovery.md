# Phase 17 M7.4 — Causal / Hedge Calibration Discovery

**Discovery only. No code was changed to produce this document. No LLM call was made — every
claim below was verified by reading `services/candidate_fact_safety.py` and `services/
fact_safety_calibration.py` directly and running their real functions, read-only, against the
exact classification examples named in the authorizing message plus the real, already-recorded
`847618cd` production case.**

## Current behavior

Two separate layers, confirmed unchanged by M7.1/M7.2/M7.3 (none of those milestones touched
causal/hedge logic):

1. **Raw detection** (`services/candidate_fact_safety.py::_scan_qualitative_flags()`): for every
   sentence in the candidate body, `_CAUSAL_RE` is checked; on a match, the sentence is
   unconditionally flagged `causal_connector: <sentence>` — **no hedge check happens at this
   stage at all**. This is an asymmetry already visible in the same function: the sibling
   `unhedged_forecast` check explicitly excludes a hedge (`if _FORECAST_RE.search(sentence) and
   not _HEDGE_RE.search(sentence)`), but the causal check has no equivalent `and not
   _HEDGE_RE.search(sentence)` guard.
2. **Calibration** (`services/fact_safety_calibration.py::_suppress_hedge_language()`): only after
   a sentence is already flagged does a SEPARATE, narrower phrase list
   (`_EPISTEMIC_LIMITATION_RE`) get a chance to suppress it. Causal-family survivors that are not
   suppressed are filed as `unresolved`, never `true_positive` (the raw detector's own disclosed
   "flag for human review, not a verification" design) — so a causal flag alone can never escalate
   `CandidateFactSafetyAudit`/`CalibratedFactSafetyAssessment` past `REVIEW`/low-severity, but it
   does keep a draft off `PASS`.

`_CAUSAL_RE`'s actual trigger word list, verified directly:
```
поэтому | это означает | в результате | следовательно | as a result | this means | that's why
```

## Real examples — verified live, not assumed

**The "known issue" pattern as literally written in the authorizing message does NOT currently
trigger the detector at all.** Tested directly:

| Text | `_CAUSAL_RE` match? | `_EPISTEMIC_LIMITATION_RE` match? | Flagged? |
|---|---|---|---|
| `Компания внедрила AI, что привело к росту прибыли.` (classification A) | **No** | No | **No — not flagged** |
| `Исследование показало, что X приводит к Y.` (classification B) | **No** | No | No |
| `Нельзя утверждать, что X привело к Y.` (classification C) | **No** | Yes (moot — nothing flagged it) | No |
| `Компания заявляет, что X привело к Y.` (classification D) | **No** | No | No |
| **Real `847618cd` candidate sentence** (already in production data): `Поэтому по этим данным нельзя однозначно утверждать, что именно потерпело неудачу.` | **Yes** (`поэтому`) | **No** (adjacency-breaking adverb, already disclosed in M7 discovery) | **Yes — false positive, confirmed** |

**This changes the shape of the problem.** The real, reproducible false positive requires the
sentence to *also* contain one of the five/seven specific connector words already in `_CAUSAL_RE`
— `"привело к"`/`"приводит к"` (the single most common way to express causation in Russian news
writing) is not one of them, so a hedge wrapped around that construction currently produces **no
flag of any kind**, correct or incorrect. The `847618cd` case is a false positive only because its
hedge sentence happens to open with `"Поэтому"`.

## False positives (confirmed root cause, narrower than assumed)

`847618cd`'s real sentence is the only reproducible instance in this codebase's own test/production
data: a sentence opens with a connector word (`Поэтому`) that is grammatically being used to
introduce a **hedge** ("we cannot say for certain..."), not a causal assertion. Two independent gaps
compound this, both already identified but neither fixed:
1. The raw detector never checks for hedge language before flagging (asymmetric with
   `unhedged_forecast`'s own existing pattern).
2. Even the calibration layer's own hedge-suppression rule (`_EPISTEMIC_LIMITATION_RE`) requires
   tight word adjacency (`нельзя утвержда\w*`) and does not match `"нельзя ОДНОЗНАЧНО
   утверждать"` (an intervening adverb breaks it) — already disclosed in the M7.2 plan's own
   "Fix D" (never implemented).

## False negative risks (the larger finding this discovery surfaces)

1. **The dominant Russian causal-claim construction is entirely invisible to the detector.**
   `"X привело к Y"` / `"X приводит к Y"` / English `"led to"`/`"leads to"`/`"caused"`/`"resulted
   in"` are not in `_CAUSAL_RE` at all. Classification A (`"Компания внедрила AI, что привело к
   росту прибыли"` — a genuinely unsupported causal claim, exactly the shape M4's own module
   docstring says this detector exists to catch) currently produces **zero flags**. This is a much
   larger gap than the false-positive class this milestone was asked to investigate — the detector
   is not just occasionally wrong on hedges, it is blind to most real causal claims in the first
   place.
2. **Zero direct unit test coverage of the raw detector.** Every existing causal/hedge test
   (`tests/test_fact_safety_calibration.py`, `tests/test_phase17_m7_1_fact_safety_calibration.py`)
   constructs a `CandidateFactSafetyAudit` with a pre-set `causal_flags` list and tests only the
   calibration layer — none of them call `_scan_qualitative_flags()`/`_CAUSAL_RE` directly. A
   regression in extraction itself would not be caught by the existing suite at all.
3. **Attribution is not distinguished from bare assertion, and neither is currently caught.**
   Classification D (`"Компания заявляет, что X привело к Y"`) reports what a company *claims*,
   which is a materially different risk than asserting the causal link as established fact
   (classification A) — but today neither is flagged, so this distinction has never been exercised
   in this codebase at all. Any future fix that adds `"привело к"`-style detection needs to decide
   deliberately whether an attributed claim should be treated the same as a bare one, rather than
   inheriting an accidental non-answer.

## Classification (verified against the required A/B/C/D taxonomy)

| Class | Example | Should be flagged? | Currently flagged? |
|---|---|---|---|
| A. Real unsupported causal claim | `Компания внедрила AI, что привело к росту прибыли.` | Yes — a specific, checkable causal assertion with no cited evidence | **No** (false negative) |
| B. Supported causal claim | `Исследование показало, что X приводит к Y.` | Arguably no, if the "исследование" (research/study) is itself sourced elsewhere in the draft — but the detector has no way to know that either way today | No (coincidentally, not by design) |
| C. Hedged claim | `Нельзя утверждать, что X привело к Y.` | No — this is exactly the honest-uncertainty case the hedge exclusion exists to protect | No (coincidentally correct outcome, not because hedging is recognized — the sentence just never reaches the detector) |
| D. Attribution | `Компания заявляет, что X привело к Y.` | Debatable — reports a claim, doesn't assert it; likely lower severity than A, not necessarily zero | No (same reason as B/C) |

**The practical takeaway**: today's causal detector's false-positive rate on THIS specific 4-way
taxonomy is 0% only because its false-negative rate is so high that none of B/C/D reach it in the
first place — not because hedging or attribution is correctly modeled. Any minimal fix that only
tightens hedge-exclusion (addressing the `847618cd`-style false positive) without also addressing
the missing `"привело к"` trigger will leave classification A permanently invisible; any fix that
adds the missing trigger without ALSO fixing hedge-exclusion will make new, real false positives
out of classifications B/C/D that don't exist today (since they're currently never reached).

## Proposed minimal fix (not implemented — discovery only)

Two independent, separately-shippable pieces, matching this arc's own established "one fix at a
time, each backtested" discipline:

**Piece 1 — hedge-check moved into the raw detector (fixes the confirmed false positive)**:
add `and not _is_hedged(sentence)` to the causal-connector check in `_scan_qualitative_flags()`,
mirroring `unhedged_forecast`'s own existing pattern exactly. `_is_hedged()` would need to combine
`_HEDGE_RE` (already in `candidate_fact_safety.py`) with a **widened** version of
`_EPISTEMIC_LIMITATION_RE` (currently only in the calibration layer) — widened specifically to (a)
add `"нельзя"` as its own standalone trigger (not requiring `"утвержда"` immediately adjacent) and
(b) tolerate 1-2 intervening words between a trigger and its verb, exactly as M7.2's own plan
already proposed and never shipped. This alone fixes `847618cd` at the raw-detector level, not just
via calibration.

**Piece 2 — add the missing causal-verb trigger (fixes the larger false-negative gap)**: extend
`_CAUSAL_RE` (or add a sibling pattern) with `привело к|приводит к|приводят к|led to|leads to|
resulted in|caused` — **only shippable together with Piece 1**, since adding this trigger without
the hedge-check would immediately create the exact false-positive class this milestone was asked
to investigate, at a much higher volume (this construction is far more common than the five/seven
words already in `_CAUSAL_RE`). Sequencing matters: Piece 1 must land and be backtested first,
Piece 2 second, each with its own before/after real-data comparison.

**Attribution (classification D) — flagged as an open question, not decided here**: whether an
attributed causal claim ("Компания заявляет, что...") should be excluded, flagged at lower
severity, or treated identically to a bare assertion is a genuine design choice with no existing
precedent in this codebase to defer to. Recommend treating it as a **separate, later** refinement
(Piece 3) rather than bundling it into the first fix, since it requires its own new
attribution-verb word list and its own severity-tier decision.

## Required tests (for the future implementation milestone — not written here)

1. **New: direct raw-detector tests.** `_scan_qualitative_flags()`/`_CAUSAL_RE` currently has zero
   dedicated tests — any implementation must add them, independent of the calibration-layer tests
   that already exist.
2. Regression: `847618cd`'s real sentence (`"Поэтому по этим данным нельзя однозначно
   утверждать..."`) must not be flagged after Piece 1 ships — a real production regression pin.
3. False-negative safety: a genuine causal-connector false claim (the existing
   `test_unsupported_causal_claim_retained` fixture, `"Это означает крах всей отрасли
   полупроводников немедленно"`) must remain flagged after Piece 1 — the hedge-check must not
   over-suppress a real unhedged causal assertion.
4. Classification A (`привело к`-style unsupported claim) must be flagged once Piece 2 ships —
   currently impossible to test since it's invisible; this is the direct regression pin for the
   larger gap this discovery found.
5. Classification C (`нельзя утверждать, что X привело к Y`) must NOT be flagged once Piece 2
   ships alongside Piece 1 — the exact pairing requirement; testing Piece 2 in isolation (without
   Piece 1) should be explicitly shown to fail this test, to prove the sequencing requirement is
   real, not assumed.
6. Widened hedge-word list: `"нельзя"` alone (no `"утвержда"` immediately adjacent) and `"нельзя
   [adverb] утверждать"` (intervening word) must both suppress/exclude, closing the exact gap
   M7.2's own plan already identified and left unfixed.
7. Existing calibration-layer tests (`test_hedge_phrase_not_treated_as_unsupported_forecast`,
   `test_confirmed_what_next_retained`, `test_unsupported_future_claim_still_flagged`,
   `test_unsupported_causal_claim_retained`) must continue passing unchanged.
8. Backtest: the same 281-draft real-production backtest discipline M7.1/M7.2/M7.3 used, run
   separately for Piece 1 and Piece 2, each with its own before/after table and an explicit
   "0 worsened" confirmation before the next piece starts.

## Status

**Discovery only — no code, test, or schema file was changed.** `git status` before and after this
document confirms zero tracked-file changes beyond this new doc.
