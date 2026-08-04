# Phase 17 M7 — Fact Safety Calibration Discovery

**Discovery only. No production code was changed to produce this document. No LLM call was made
— every claim below was verified by reading `services/fact_safety.py`, `services/
candidate_fact_safety.py`, `services/fact_safety_calibration.py`, and their existing tests, then
running the real, already-persisted evidence for case `847618cd` (Stage 2's own flagged case)
through the actual functions in a read-only Python session. Nothing here is hypothesized without a
reproduction; where a hypothesis turned out to be wrong or incomplete, that is reported too.**

## Trigger

Stage 2's human comparison packet (`docs/phase17_stage2_human_comparison_packet.md`) flagged case
`847618cd`'s candidate at `CandidateFactSafetyAudit` status `fail`/`high` over the claim "Он
использовал 320,7 млн входных токенов" ("It used 320.7 million input tokens"), despite that exact
sentence appearing verbatim in the event's own Research output. The human decision recorded this
as "a confirmed matcher false positive." This milestone verifies that conclusion and finds two
more, related false-positive classes plus one structural gap while investigating it.

## Discovered false-positive classes

### 1. Numeric claim matcher: bare quantities misclassified as unresolvable "money" claims

**Current behavior.** `services/fact_safety.py`'s `_MONEY_EXTRACT_PATTERN` has three ways to match
a money claim; one of them requires only a number **and** a magnitude word (`million`/`billion`/
`млн`/`млрд`/etc.) — **no currency symbol or currency word required**:

```
(?:{_MONEY_NUMBER})\s*{_MONEY_MAGNITUDE_WORD}\.?\s*(?:{_MONEY_CURRENCY_WORD})?
```

So "320,7 млн" (320.7 million *tokens* — not money at all) is extracted as `claim_type="money"`.
But `_normalize_money()` requires a resolvable currency to return anything but `None`
(`currency = _CURRENCY_SYMBOLS.get(currency_key)`; `if currency is None: return None`) — a bare
quantity has no currency, so normalization always fails. In `_claim_matches_any()`, a `None`
normalized value returns `False` **before evidence is even consulted** — meaning this claim type
is structurally unmatchable against *any* evidence, correct or not. `_classify_claim()` then falls
through every match attempt and, since `evidence_complete=True` for this event (real article body
present), lands on `unsupported`, severity `_UNSUPPORTED_SEVERITY["money"] == "high"`.

**Verified, live**, using the exact real evidence for `847618cd`:
```
_normalize_money("320,7 млн")  ->  None
extract_claims(candidate_body)["money"]  ->  ["320,7 млн"]
extract_claims(research_fact_text)["money"]  ->  ["320,7 млн"]   # the source's OWN phrasing
_normalize_money(research_claim)  ->  None                       # evidence fails identically
```
Both sides fail to normalize identically — the claim was never actually compared to evidence at
all; it was guaranteed `unsupported` the moment it matched the extraction regex.

**Desired behavior.** A bare quantity (number + magnitude word, no currency) should either (a) not
be classified as a `money` claim at all, or (b) be classified as its own claim type with a matcher
that doesn't require currency resolution — direct number+magnitude comparison, the same way
`_percentage_matches`/`_date_matches` don't require a currency either.

**Scope note — this is not Stage-2-only.** `services/fact_safety.py` is shared, unmodified, by
production's own `apply_fact_safety()` (`capabilities/executor.py`) and Stage 2's
`evaluate_candidate_fact_safety()`. Any production baseline draft that states a plain quantity
("5 million users", "1129 tool calls" — no, `1129` alone has no magnitude word so it's not
affected, but "320.7 million" would be) is exposed to the identical bug today. It only surfaced
now because Stage 2's candidate happened to restate a token-count figure the baseline draft never
included.

### 1b. Related coverage gap found incidentally: "trillion"/"трлн" is invisible to Fact Safety

While verifying #1, `_MONEY_MAGNITUDE_WORD` was checked against case `ac1f1ff5`'s own "2,8 трлн
параметров" (2.8 trillion parameters) claim — **`трлн`/`trillion` is not in `_MONEY_MAGNITUDE`
or `_MONEY_MAGNITUDE_WORD` at all**:
```
extract_claims("Kimi K3 содержит 2,8 трлн параметров.")
  -> {'money': [], 'percentage': [], 'date': [], 'entity': ['Kimi K3'], 'quote': []}
```
This is a **false-negative** gap, not a false positive — a fabricated trillion-scale figure would
currently pass Fact Safety silently, uninspected. Flagged here because it was found during the same
investigation, using the same magnitude-word table; not part of the original discovery request but
directly relevant to any fix in that table.

### 2. Entity matcher: multi-word capitalized runs bundle a generic descriptor with a real proper noun

**Current behavior.** `_extract_entities()` applies a "does this lone word carry independent
signal" check (`_is_strong_single_token_entity` — ALL-CAPS, internal capital, or hand-curated
alias) **only to single-token candidates**. Any run of 2+ consecutive capitalized words is kept
unconditionally (`if token_count >= 2: candidates.append(value)`), with no equivalent check that
any *component* of the run is a genuine proper noun rather than ordinary capitalization from
sentence-initial position or a generic role noun attached to a name.

**Verified, live**:
```
_extract_entities("Автономный ИИ-агент протестировал реальный бизнес.")  -> ["Автономный ИИ-агент"]
_extract_entities("Агент Saul получил доступ к бизнесу.")                -> ["Агент Saul"]
```
"Автономный ИИ-агент" ("Autonomous AI-agent") is a generic descriptive phrase, capitalized only
because it opens the sentence/headline — not a proper noun. "Агент Saul" bundles a generic role
noun ("Агент"/"Agent") with the one word that *is* a real proper noun ("Saul"). Because the whole
2-word span is treated as one entity claim, matching requires that **exact 2-word phrase**
somewhere in evidence — but the real Research evidence phrases the agent's name three different
ways ("Агента звали Saul", "Saul использовал...", never "Агент Saul" verbatim), so the bundled
claim can never match even though its real content (the name "Saul") is thoroughly evidenced.

**Desired behavior.** A multi-word capitalized run should require that at least one component word
carry independent signal (mirroring the existing single-token rule) before the whole phrase is
accepted as a genuine proper-noun claim; a run that fails this test but contains a strong-signal
sub-token should extract that sub-token alone rather than discarding the signal or keeping the
noisy bundle.

### 3. Causal-connector matcher: fires on connector words regardless of what the sentence actually asserts

**Current behavior.** `services/candidate_fact_safety.py`'s `_CAUSAL_RE` matches a fixed connector
word list (`поэтому`, `это означает`, `в результате`, `следовательно`, `as a result`, `this means`,
`that's why`) anywhere in a sentence — with no check of what the sentence actually claims. A
sentence that uses "therefore" to introduce an explicit **hedge** ("therefore, we cannot say for
certain...") is flagged identically to one asserting an actual unverified causal claim.

**Verified, live**, the exact flagged sentence from `847618cd`'s candidate:
```
sentence = "Поэтому по этим данным нельзя однозначно утверждать, что именно потерпело неудачу — агент или сам эксперимент"
_CAUSAL_RE.search(sentence)              -> match ("Поэтому")
_HEDGE_RE.search(sentence)                -> no match  ("нельзя" is not in the hedge word list)
```

**This is not fully fixed by the existing M5 calibration layer either** — `services/
fact_safety_calibration.py`'s own `_EPISTEMIC_LIMITATION_RE` (which exists specifically to catch
this class, per its own docstring, case `7352db1a`) also does **not** match:
```
_EPISTEMIC_LIMITATION_RE.search(sentence)  -> no match
```
Root cause: the pattern requires `нельзя утвержда\w*` as directly adjacent tokens; the real
sentence has an intervening adverb (`нельзя ОДНОЗНАЧНО утверждать`), which breaks the match. Both
the raw detector's hedge exclusion (`_HEDGE_RE`) and the calibration layer's epistemic-limitation
exclusion (`_EPISTEMIC_LIMITATION_RE`) miss this specific, real, present-in-production phrasing
pattern.

**Desired behavior.** A causal-connector sentence containing an epistemic-limitation/hedge marker
— including "нельзя" as a standalone trigger, and tolerating a short intervening phrase between
trigger and verb — should be excluded from the flag (raw layer) or suppressed (calibration layer),
consistent with the module's own already-stated intent.

## Structural finding: Stage 2 candidate audits never pass through the M5 calibration layer at all

**Verified, live** (grep, not inference):
```
grep "calibrat" scripts/phase17_stage2_candidate_generation.py scripts/phase17_m4_1_failed_case_replay.py \
     scripts/phase17_m4_beginner_copywriting_comparison.py   ->  0 matches
grep "calibrate_fact_safety" capabilities/executor.py         ->  1 match (production/shadow path)
```
`capabilities/executor.py` (the real production `EDITORIAL_COMPLETENESS_MODE=shadow` path) calls
`calibrate_fact_safety()` for every baseline draft's shadow assessment. **None of the M3/M4/M4.1/
Stage 2 candidate-generation scripts ever call it** — `scripts/phase17_stage2_candidate_generation.py`
computes both `baseline_fact_safety` and `candidate_fact_safety` via the same raw
`evaluate_candidate_fact_safety()` (symmetric between the two, at least — no bias *within* Stage 2's
own comparison), but both numbers are systematically harsher than what the same text would show
under the calibration production baselines already benefit from in the real shadow pipeline.

**Tested what calibration alone would have changed for `847618cd`'s real recorded flags:**
```
raw:        status=FAIL/high    numeric=["unsupported:320,7 млн"]  entity=["unsupported:Автономный ИИ-агент", "unsupported:Агент Saul"]
calibrated: status=REVIEW       numeric flag SUPPRESSED (russian_inflection_or_quote_match, via fuzzy_phrase_contains)
                                 both entity flags SURVIVE as true_positive (calibration has no rule for class #2 above)
```
So: wiring Stage 2 through the existing calibration layer would have fixed the *numeric*
false-positive automatically (it already has a working, tested rule for it — `fuzzy_phrase_contains`
found "320,7 млн" verbatim in the combined source+research text) and dropped the status from
FAIL/high to REVIEW/medium — but the two entity flags (class #2) and the causal flag (class #3)
would still have survived calibration unchanged, because calibration has no rule addressing either
of those two classes. **Wiring in calibration is a real, partial, low-risk fix; it does not
substitute for fixing classes #1/#2/#3 at the root.**

## Proposed fixes (not implemented)

| # | Fix | Where | Risk |
|---|---|---|---|
| A | Route `evaluate_candidate_fact_safety()` output through `calibrate_fact_safety()` in Stage 2 tooling, store both raw and calibrated, mirroring production's own pattern. | `scripts/phase17_stage2_candidate_generation.py` | Low — calibration is already tested against a 269-case backtest with an explicit never-suppress-money/percentage/date-except-via-literal-match discipline. Retroactively changes how already-recorded Stage 2 output should be read (disclose, don't silently reinterpret past decisions). |
| B | Stop classifying a bare number+magnitude-word (no currency) as `money`; either drop it from money extraction or give it its own claim type/matcher that compares magnitude directly, without requiring currency resolution. | `services/fact_safety.py` (`_MONEY_EXTRACT_PATTERN`, `_normalize_money`, `_claim_matches_any`) | Medium — touches the shared production Fact Safety module; must preserve this codebase's own "never trade a false negative for a false-positive reduction" rule (a genuinely fabricated large number must stay caught). Needs the same before/after backtest discipline M5.3's own calibration changes used. |
| B2 | Add `трлн`/`trillion` to the magnitude table (found incidentally, §1b). | `services/fact_safety.py` (`_MONEY_MAGNITUDE`, `_MONEY_MAGNITUDE_WORD`) | Low — pure addition, same shape as the existing M5.3 CNY/Yuan addition already in this file. |
| C | Require at least one component of a multi-word capitalized entity run to carry independent signal (reusing `_is_strong_single_token_entity`'s existing per-token logic) before accepting the whole run; fall back to extracting the strong-signal sub-token alone otherwise. Consider a narrow, hand-curated generic-descriptor-prefix list (`автономный`, `агент`, ... — several already exist in `candidate_fact_safety.py`'s own `_DESCRIPTIVE_NOUN_RE`) to strip, mirroring the existing suffix-stripping precedent. | `services/fact_safety.py` (`_extract_entities`) | Medium — could under-extract a genuine multi-word proper noun with no internally-strong token (rare, per this codebase's own existing entity examples, but not impossible). Needs a false-negative regression fixture, same discipline as existing calibration tests. |
| D | Widen `_HEDGE_RE`/`_EPISTEMIC_LIMITATION_RE` to recognize "нельзя" as a standalone hedge trigger, and tolerate 1-2 intervening words between trigger and verb. | `services/candidate_fact_safety.py` (`_HEDGE_RE`) and/or `services/fact_safety_calibration.py` (`_EPISTEMIC_LIMITATION_RE`) | Medium — a too-loose pattern could suppress a genuine unhedged causal claim that happens to sit near an unrelated hedge word. Keep narrow (fixed trigger list, small token-gap bound), not a general hedge classifier — matching this codebase's own repeatedly-stated instruction. |

None of A-D have been implemented. No test was modified. No production file was modified.

## Risks of NOT fixing (for context, not a recommendation to skip validation)

- Every Stage 2 comparison run to date (`docs/phase17_stage2_human_comparison_packet.md`) has
  candidate Fact Safety numbers that are harsher than production calibration would show for
  identical text — a human reviewer unaware of this could reject a genuinely safe candidate, or
  (as already happened once) have to manually re-derive what calibration would have told them
  automatically.
- Class #1's root cause lives in shared production code — a real baseline draft could hit the same
  bug today, independent of Stage 2 entirely.
- Class #1b (trillion) is a live coverage gap in production Fact Safety right now, unrelated to
  Stage 2.

## Test cases needed (for the future implementation milestone — not written here)

1. Regression: a bare currency-less quantity ("320.7 million tokens") present verbatim in evidence
   must not escalate to `unsupported`/`high` (the exact `847618cd` case, pinned).
2. Regression: a fabricated trillion-scale claim must still be caught once `трлн`/`trillion` is
   added to the magnitude table (false-negative safety for fix B2).
3. Regression: a genuine large-number fabrication (money or bare quantity) not present in any
   evidence must still be flagged after fix B (false-negative safety).
4. Regression: "generic descriptor + proper noun" run ("Агент Saul", "Автономный ИИ-агент")
   matches evidence when the core name/acronym is independently evidenced, even without the exact
   phrase appearing verbatim.
5. Regression: a genuinely fabricated 2-word entity phrase with no strong-signal sub-token must
   still be flagged after fix C (false-negative safety).
6. Regression: "нельзя [adverb] утверждать..." and similar hedge phrasing with an intervening word
   must not be flagged as a risky causal claim.
7. Regression: a genuine unhedged causal claim near an unrelated hedge word must still be flagged
   after fix D (false-negative safety).
8. Integration: Stage 2 script records both raw and calibrated Fact Safety per case once fix A
   lands, and existing recorded `editorial_preference`/`editorial_notes` from prior runs are
   preserved untouched (resume-safety, matching the resume-logic bug already fixed in `checkpoint/
   phase17-stage2-live-candidates-generated`).
9. Full-suite regression: re-run the M5 gold-set backtest (`docs/
   phase17_m5_editorial_completeness_gate_shadow_report.md`'s own 269-case set) after any of B/C/D
   land, confirming no known true-positive fabrication case flips to suppressed — this project's
   own explicit, repeated "never trade a false negative for a false-positive reduction" discipline.

## Validation performed for this discovery milestone

- `python -m pytest tests/test_fact_safety.py tests/test_fact_safety_calibration.py -q` →
  **2 failed, 96 passed**. The 2 failures
  (`test_off_mode_leaves_quality_step_result_completely_unchanged`,
  `test_shadow_mode_enriches_quality_result_and_detects_unsupported_claim`) are both members of
  the already-documented, pre-existing 19-failure baseline (`docs/
  phase17_final_engineering_completion_report.md`) — **zero new failures**, `test_fact_safety_calibration.py`
  fully passing.
- `python -m scripts.phase17_cutover_preflight` → **OVERALL: PASS**, including
  `feature_modes_safe_default: all Phase 17 candidate-generation/enforcement modes off` — confirms
  no config/mode drift occurred during this investigation.
- `git status` before and after this milestone: **zero tracked-file changes** — every reproduction
  in this document was run in an ad hoc read-only Python session against real, already-persisted
  data; no test, script, or service file was edited.
