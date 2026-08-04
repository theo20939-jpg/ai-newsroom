# Phase 17 M7.2 — Quantity Claim Classification Plan

**Plan only. No production logic has been changed to produce this document.** Builds directly on
M7 discovery (`docs/phase17_m7_fact_safety_calibration_discovery.md`, class #1) and M7.1's own real
backtest evidence (`docs/phase17_m7_1_fact_safety_calibration_report.md`, "known remaining issues"
§1) that this gap is active, present-day, and now slightly more visible after the трлн addition.

## Current behavior (verified against the real code, not assumed)

`services/fact_safety.py`'s `_MONEY_EXTRACT_PATTERN` has three ways to match, and only one of them
requires a currency signal at all:
```
(?:\$|€|£|₽)\s*(?:NUMBER)(?:\s*MAGNITUDE_WORD|MAGNITUDE_LETTER)?\.?              # currency-symbol-anchored
|(?:NUMBER)\s*MAGNITUDE_WORD\.?\s*(?:CURRENCY_WORD)?                             # magnitude-word-anchored, NO currency required
|(?:NUMBER)\s*CURRENCY_WORD                                                      # currency-word-anchored
```
The second branch is the problem: `NUMBER + million/billion/trillion/тыс/млн/млрд/трлн`, with no
currency symbol or word anywhere nearby, still matches and is typed `"money"`. But
`_normalize_money()` requires a resolvable currency to return anything but `None`:
```python
currency = _CURRENCY_SYMBOLS.get(currency_key)
if currency is None:
    return None
```
And `_claim_matches_any()` treats a `None` normalized value as an immediate, unconditional `False`
— **evidence is never even consulted**. `_classify_claim()` then falls through to `unsupported`
whenever `evidence_complete=True`, at `_UNSUPPORTED_SEVERITY["money"] == "high"` — the *same*
top-tier severity as a genuinely fabricated dollar amount, applied uniformly to token counts,
parameter counts, user counts, and any other bare large quantity, regardless of whether it is true.

**Every consumer that branches on claim type would need to know about a new type** (found by
grepping every `"money"` reference outside tests):

| File | Line(s) | What it does |
|---|---|---|
| `services/fact_safety.py` | `ClaimType` Literal, `_UNSUPPORTED_SEVERITY`/`_UNCERTAIN_SEVERITY`, `extract_claims()`, `_claim_matches_any()` | Defines the type, its severity tiers, extraction, and matching |
| `services/candidate_fact_safety.py` | 148, 160 | Buckets findings into `numeric_flags` vs `entity_flags`; decides `high_severity_unsupported` |
| `services/fact_safety_calibration.py` | 135 | `_sentence_claims()` iterates a fixed 5-type tuple when checking `unhedged_forecast` sentences |

## Failure examples (all real, all from already-recorded production/Stage 2 data)

1. **`847618cd`** (real Stage 2 candidate) — "Он использовал 320,7 млн входных токенов" — a token
   count, verbatim in Research evidence, flagged `unsupported`/`high`. Root cause of the escalation
   M7.1 partially fixed via calibration (raw still fail/high; calibrated now review/medium, but only
   because the *inflection-match* suppression rule happened to catch it — not because the system
   understood this was never a money claim).
2. **`ac1f1ff5`/Kimi K3** (real production draft, `f0c40711...`) — "2,8 трлн параметров" — a model
   parameter count. Before M7.1: invisible (трлн not in the magnitude table at all). After M7.1:
   extracted, still typed `money`, still fails to normalize, now flagged `unsupported`/`high` in the
   real backtest (`review`→`block`) — the exact new instance M7.1's own report disclosed.
3. **`bed6f564`** (real production draft, Samsung mobile loss) — "0,7 трлн вон" (0.7 trillion
   **Korean Won**) — genuinely IS a money claim, and the source article states the identical figure
   ("0,7 трлн вон (~487 млн долларов)"). It fails for a *different*, related reason: `вон`/`Won` is
   not in `_CURRENCY_SYMBOLS` at all, so even a correct money-vs-quantity classifier would still
   need currency-list coverage to fix this specific case. Flagged here as a distinct, adjacent gap
   — not solved by quantity classification alone.
4. **Hypothetical, not yet observed in real data, but structurally identical**: "5 million users",
   "150 million requests", "40,000 API calls" — any metric with a magnitude word and no currency
   would hit the identical failure today.
5. **Correctly unaffected today, for contrast**: "1129 вызовов инструментов" (1,129 tool calls) —
   no magnitude word, never enters the money-extraction path at all. This class of claim is already
   invisible to Fact Safety (a pre-existing, separate, lower-urgency coverage gap — a bare integer
   claim of any kind, not just tool-call counts, is never checked) and is **out of scope** for this
   plan, which only addresses claims that *do* have a magnitude word and are consequently
   mistyped as money today.

## Proposed rules (minimal classification layer)

Three claim buckets, decided at extraction time by what's textually adjacent to the number+
magnitude match — not a rewrite of extraction, an added disambiguation step immediately after it:

1. **Currency** — a currency symbol (`$`/`€`/`£`/`₽`) or currency word (`dollars`/`евро`/`рублей`/
   etc.) is present, exactly as today's `_MONEY_PATTERN` already detects. **Unchanged**: stays typed
   `"money"`, uses the existing `_normalize_money()`/`_money_matches()` path verbatim. This is the
   one bucket M7.2 does not touch.
2. **Metric** (new) — no currency signal, but a recognized metric-unit word immediately follows (or
   closely precedes) the number+magnitude: a narrow, explicit, hand-curated list —
   `tokens`/`параметров`/`параметры`/`users`/`пользователей`/`requests`/`запросов`/`calls`/
   `вызовов`/`operations`/`операций` (mirroring this codebase's own established discipline for
   every prior hand-curated list: `_CURRENCY_SYMBOLS`, `_ENTITY_ALIAS_GROUPS`,
   `_DESCRIPTIVE_NOUN_RE`). New claim type `"metric_quantity"`. New matcher `_metric_matches()`,
   structurally parallel to `_money_matches()` but comparing `(unit_canonical, amount)` instead of
   `(currency, amount)` — no currency lookup involved, so a claim like "320.7 million tokens" can
   resolve and be compared to evidence directly.
3. **Generic quantity** (new) — a magnitude word is present, but neither a currency signal nor a
   recognized metric unit is found nearby. New claim type `"generic_quantity"`. This is the
   genuinely ambiguous fallback — we cannot tell what is being counted, so it should not carry the
   same confidence-implying severity as a claim we successfully typed.

**Severity table, proposed**:

| Type | Unsupported severity | Uncertain severity | Rationale |
|---|---|---|---|
| `money` (unchanged) | high | medium | Unchanged — a currency claim is maximally specific and fabricatable. |
| `metric_quantity` (new) | **high** | medium | A metric claim with a resolvable unit+number is just as specific and checkable as money once resolved — genuinely unsupported should still be caught at the same severity M5's own "high-risk claim types" design intends. |
| `generic_quantity` (new) | **medium** (down from money's current `high`) | low | We don't know what's being measured — this is the direct fix for the false-positive-severity problem: an unclassifiable bare quantity should read as "worth a look" (REVIEW-tier), not "confirmed high-risk fabrication" (FAIL-tier), until proven otherwise. |

This severity change is the actual fix for the `847618cd`/Kimi-K3-class false positives: today,
*every* magnitude-word quantity without currency is unconditionally `high`; under this proposal,
only claims that resolve to a real, matchable metric (and then genuinely fail to match) stay
`high` — an unclassifiable one is downgraded to `medium`, which no longer single-handedly escalates
`CandidateFactSafetyAudit.status` to `FAIL` (per `services/candidate_fact_safety.py`'s own existing
rule: only money/percentage/date/quote-type unsupported claims at `high` severity escalate to
`FAIL`; `generic_quantity` at `medium` would land at `REVIEW`, matching how `entity`-type
unsupported claims are already treated).

## False-negative risks (must be regression-tested before this ships)

1. **A genuine metric fabrication must still be caught.** A candidate claiming "500 million tokens"
   when evidence says "320.7 million tokens" — same unit, different number — must resolve as
   `metric_quantity`/`unsupported`/`high`, not silently pass just because a unit word is present.
2. **A genuine money fabrication must not be misrouted into a lower-severity bucket.** The currency
   detection (bucket 1) must run *before* the metric/generic checks, and must never be weakened —
   a fabricated "$9.4 trillion" must stay `money`/`high`, exactly as M7.1's own test already pins.
3. **The metric-unit word list is inherently incomplete** (deliberately narrow and hand-curated, per
   this codebase's own repeated instruction never to build a general classifier). An unlisted unit
   ("GPU-hours", "sessions", "queries") falls through to `generic_quantity` — this is a *safe*
   direction of failure (downgrades to medium, doesn't silently pass), but should be explicitly
   tested so it's a known, accepted trade-off, not a surprise.
4. **Currency-word coverage remains separately incomplete** (`bed6f564`'s "вон"/Won example) — a
   real money claim in an uncovered currency will land in `generic_quantity` (medium), not `money`
   (high) — arguably *less* cautious than today's behavior for that one narrow case (today it's
   already `unsupported`/`high` via the same-currency-less-quantity bug this plan fixes elsewhere).
   This is the one place this plan could plausibly be argued to reduce caution for a real,
   uncorroborated money claim — flagged explicitly for review, not decided here. A companion
   currency-list expansion (matching the M5.3 CNY/Yuan precedent) would close this specific gap;
   whether to bundle it with M7.3 or do it separately is an open question for you, not assumed.
5. **Ordering/precedence must be deterministic and tested**: a number that could plausibly match
   both a currency word AND a metric unit in the same sentence (unlikely but not impossible in
   dense text) needs an explicit, tested precedence rule (proposed: currency check always wins,
   since it's the most specific/highest-confidence signal).

## Test matrix (to be written in M7.3, not yet written here)

| # | Input (draft claim) | Evidence | Expected type | Expected match | Expected severity if unsupported |
|---|---|---|---|---|---|
| 1 | "$9.4 trillion" | none matching | `money` | unsupported | high (unchanged, existing M7.1 test) |
| 2 | "320.7 million tokens" | "320.7 million tokens" verbatim | `metric_quantity` | **supported** | n/a — direct fix for `847618cd` |
| 3 | "500 million tokens" | "320.7 million tokens" (same unit, different number) | `metric_quantity` | unsupported | high (false-negative-safety pin) |
| 4 | "2.8 trillion parameters" | "2.8 trillion parameters" verbatim | `metric_quantity` | **supported** | n/a — direct fix for Kimi K3 case |
| 5 | "9 trillion parameters" (fabricated) | no parameter-count evidence at all | `metric_quantity` | unsupported | high (false-negative-safety pin) |
| 6 | "40,000 API calls" (no currency, no listed unit match if "API calls" not in the curated list) | anything | `generic_quantity` | unsupported (unmatchable either way) | **medium**, not high — the actual fix |
| 7 | "0.7 trillion won" | "0.7 trillion won" verbatim, but "won" not in `_CURRENCY_SYMBOLS` | `generic_quantity` (known gap, §risk 4) | unsupported | medium — flagged as a real, disclosed limitation, not silently "fixed" |
| 8 | "1,129 tool calls" (bare integer, no magnitude word) | anything | not extracted at all (unchanged) | n/a | n/a — confirms this plan doesn't touch bare-integer claims |
| 9 | Existing `test_fact_safety.py::test_money_normalization_formats` full parametrized set | — | `money`, unchanged | unchanged | unchanged — zero regression on real currency detection |
| 10 | `847618cd` full real fixture (already pinned in `tests/test_phase17_m7_1_fact_safety_calibration.py`) | real research facts | `metric_quantity` for the token claim | supported | raw status should improve directly (not just via calibration's inflection-match rule) |
| 11 | Kimi K3 full real fixture | real research facts | `metric_quantity` for the parameter claim | supported | raw status should improve directly |
| 12 | Real 281-draft backtest (`scripts/phase15_m5_fact_safety_backtest.py`), before/after this change | — | — | — | zero drafts should move toward a *less* cautious verdict (same discipline M7.1 used) |

## Open questions for you before M7.3 implementation begins

1. Bundle the currency-list expansion (риск §4, e.g. adding КРВ/Won) into M7.3, or keep it a
   separate, later milestone?
2. Is the proposed severity table (metric_quantity stays high, generic_quantity drops to medium)
   the right calibration, or should generic_quantity's *uncertain* tier also change from `low`?
3. Should `metric_quantity` also feed into `services/candidate_fact_safety.py`'s `numeric_flags`
   bucket (alongside money/percentage/date, as proposed above), or into a new, separate bucket -
   affects how Stage 2's human comparison packet would eventually present it?

**Status: PLANNED, NOT IMPLEMENTED.** No code, test, or schema file was changed to produce this
document. `services/fact_safety.py`/`services/candidate_fact_safety.py`/`services/
fact_safety_calibration.py` all remain exactly as committed in `checkpoint/
phase17-m7-1-fact-safety-calibration`.
