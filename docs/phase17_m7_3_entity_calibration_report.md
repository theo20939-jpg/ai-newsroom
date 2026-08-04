# Phase 17 M7.3 — Entity Prefix Calibration Report

**Scope, strictly as authorized: Option A only (generic-prefix stripping). Named entity recall is
explicitly NOT addressed** (that remains Option B, a separate, larger, not-yet-authorized effort).
No architecture rewrite, no broad whitelist, no removal of any existing entity check, no severity
threshold change, no LLM call anywhere in this milestone.

## Root cause (confirmed, matching M7.3 discovery exactly)

`_extract_entities()`'s multi-word branch trusted any 2+-word capitalized run unconditionally
(`if token_count >= 2: candidates.append(value)`), with no per-word signal check the way the
single-token path already has. A generic adjective or role noun capitalized only because it opens
a sentence (`Автономный`, `Агент`, `Китайская`) was therefore indistinguishable from a genuine
multi-word proper name (`Kimi K3`).

## Implementation

**File**: `services/fact_safety.py` only. `services/candidate_fact_safety.py` and `services/
fact_safety_calibration.py` were **not** touched — this fix is entirely inside extraction, exactly
as scoped.

1. **New hand-curated word lists** (narrow, explicit, matching every other calibration in this
   module — no morphological/stemming rule):
   - `_ENTITY_GENERIC_ADJECTIVE_WORDS` — nationality/generic adjectives (автономный/китайская/
     российская/американская + inflections).
   - `_ENTITY_GENERIC_ROLE_NOUN_WORDS` — role/category nouns (агент/компания/модель/платформа/
     стартап/разработчик/производитель, EN+RU) — intentionally overlaps with `services/
     candidate_fact_safety.py`'s own `_DESCRIPTIVE_NOUN_RE` (a different purpose), kept in sync by
     hand.
   - `_ENTITY_GENERIC_HYPHENATED_RE` — a hyphenated compound whose own suffix names a generic
     descriptor (`ИИ-модель`/`ИИ-агент`/`ИИ-платформа`), mirroring the existing
     `_ENTITY_DESCRIPTIVE_SUFFIX_PATTERN`'s word list (used for a different purpose — matching,
     not extraction).
2. **`_strip_generic_entity_prefix()`** — iteratively strips leading words from a multi-word run,
   with two **deliberately asymmetric** rules:
   - A role noun or hyphenated descriptor is stripped **unconditionally**.
   - A nationality/generic **adjective** is stripped **only when the very next word is also
     unconditionally generic** — otherwise left in place. This is the fix for the nationality
     requirement (see below): it distinguishes "Китайская ИИ-модель Kimi K3" (strip — next word is
     a generic descriptor) from "Российская Федерация" (keep — next word is not a recognized
     generic word, so this reads as a genuine official name).
3. **`_extract_entities()`** now applies stripping inside the `token_count >= 2` branch: if the
   remainder still has 2+ words, keep the remainder; if exactly 1 word remains, apply the
   **existing, unchanged** `_is_strong_single_token_entity()` check; if the remainder is empty,
   discard entirely.
4. **One related, pre-existing bug found and fixed while verifying this milestone's own examples**
   (disclosed, not silently folded in): `_is_strong_single_token_entity()`'s alias check used to
   route through `_normalize_entity()`'s full pipeline, including its descriptive-suffix stripping
   — so a bare `"ИИ-модель"` (no adjective prefix at all) collapsed to `"ии"` and matched the
   existing `"ИИ"`/`"AI"` alias, making a purely generic compound look like a strong single-token
   signal. Fixed by having the alias check use a narrower normalization (Unicode+casefold+legal-
   prefix/suffix+possessive only, no descriptive-suffix strip) — `"ИИ"` alone is unaffected (it
   already passes via the ALL-CAPS branch).

## Before / after — the three named examples

| Example | Before | After |
|---|---|---|
| `Автономный ИИ-агент` | extracted as one 2-word entity | **not extracted at all** |
| `Агент Saul` | extracted as one 2-word entity | **not extracted at all** (disclosed limitation — see below) |
| `Китайская ИИ-модель Kimi K3` | extracted as one 4-word entity | **extracted as exactly `"Kimi K3"`** |

## Before / after — nationality requirement (verified, not assumed)

| Example | Result |
|---|---|
| `Российская Федерация подписала соглашение.` | `["Российская Федерация"]` — preserved intact |
| `Китайская Народная Республика объявила о реформах.` | `["Китайская Народная Республика"]` — preserved intact |
| `Китайская ИИ-модель Kimi K3` | `["Kimi K3"]` — correctly stripped down |

The asymmetric look-ahead rule (§3 above) is what makes this possible: the *same* nationality
adjective is stripped or kept purely based on whether the following word is itself a recognized
generic descriptor — found and fixed via direct testing (the first implementation attempt
incorrectly stripped `"Российская Федерация"`, caught before commit).

## Before / after — safety regressions (verified)

| Example | Result | Unchanged? |
|---|---|---|
| `OpenAI` | `["OpenAI"]` | ✅ unaffected |
| `Kimi K3` (bare) | `["Kimi K3"]` | ✅ unaffected |
| `NASA` | `["NASA"]` | ✅ unaffected |
| `Tesla Inc` | `["Tesla Inc"]` | ✅ unaffected |
| `Samsung` (bare) | `[]` | ✅ unchanged — pre-existing limitation, documented, not fixed (Option B) |
| `Google` (bare) | `[]` | ✅ unchanged — same |
| `Saul` (bare) | `[]` | ✅ unchanged — same |

## Backtest — 281-draft real production set (read-only, zero LLM calls)

Ran `scripts/phase15_m5_fact_safety_backtest.py` twice: once against pre-M7.3 code (`git stash` on
`services/fact_safety.py` only, back to `checkpoint/phase17-m7-2-quantity-classification`, restored
immediately after and confirmed via `git diff`), once against the final M7.3 code.

| | Before | After |
|---|---|---|
| Sample size | 281 | 281 |
| `pass` | 104 | 111 |
| `review` | 101 | 100 |
| `block` | 76 | 70 |
| `entity`-type findings | 284 | 270 (-14) |

**8 drafts changed status — all 8 improved, 0 worsened.** Every removed entity flag was inspected
individually: all 8 are the identical generic-adjective/role-noun-plus-real-name bundling pattern
(`"Автономный ИИ-агент"` ×4 real drafts, `"Агент OpenAI"` ×2, `"Китайская ИИ-модель Kimi K3"` ×1,
`"Стартап Spur Intelligence"` ×1). One case (`"Google представила Gemini Robotics 2"`) surfaced an
unplanned, positive side effect: the draft's own `"Gemini Robotics"` claim now *matches* evidence
because evidence-side extraction of a differently-bundled phrase (`"Новая ИИ-модель Gemini
Robotics"`) is now *also* stripped down to `"Gemini Robotics"` — the fix improves matching
consistency for genuine entities, not just false-positive removal, when both sides happen to bundle
the same real name with different generic prefixes. That same draft still has 2 remaining medium-
severity entity findings unrelated to this fix (`"Новая ИИ-модель"`, `"AI"`) — moved `block`→
`review`, not fully resolved, exactly matching Option A's own disclosed scope.

**No new high-severity false negatives discovered** — every one of the 8 changed drafts was
individually inspected (not just counted); none removed a flag on a claim that was actually a real
fabrication.

## Stage 2 four human-reviewed cases (recomputed under current code, read-only, zero LLM calls)

| Case | Baseline before→after | Candidate before→after |
|---|---|---|
| `2d35bad8` | pass → pass (unaffected) | pass → pass (unaffected) |
| `12ce8e52` | review → review (unaffected — "Правила ЕС"/"Нормы ЕС" are not in any M7.3 word list) | review → review (unaffected) |
| **`847618cd`** | **review → pass** (entity flag removed entirely) | fail (M7.1 baseline) → **review, zero entity flags** (only the causal flag remains) |
| **`ac1f1ff5`** | **review → pass** (entity flag removed entirely) | review → review (one low-severity `uncertain:ИИ` flag remains — a genuine alias entity, not a false positive, correctly untouched) |

`847618cd`'s candidate now has **zero** numeric and **zero** entity flags — only the M7 discovery
class #3 causal flag remains, dropping severity from the M7.2-era `medium` to `low`.

## Remaining recall limitations (disclosed, Option A's own accepted scope)

1. **Bare single-word real entities without internal capitalization/ALL-CAPS are still invisible**
   (`Google`, `Samsung`, `Saul` — confirmed unchanged, verified live). This is the pre-existing
   single-token-recall limitation M7.3 discovery identified; Option A does not touch it by design.
2. **`"Агент Saul"` now extracts nothing at all**, rather than `"Saul"` alone — this is the direct,
   accepted consequence of #1: stripping `"Агент"` leaves `"Saul"`, which still fails the existing
   single-token check. Not a new gap (the bundled form never matched differently-phrased evidence
   in practice either — verified in M7 discovery), but also not a full fix.
3. **The generic-prefix word lists are deliberately narrow** — an unlisted adjective or role noun
   (e.g. a nationality not in the four covered, or an uncommon role noun) would still incorrectly
   bundle. Disclosed, not silently assumed complete.
4. **Legal-suffix cases (`"Acme Inc"`) do not get prefix-stripping applied at all** — an untested
   combination in this pipeline's real data, explicitly scoped out.

## Tests

`tests/test_phase17_m7_3_entity_calibration.py` — **17 tests**: 3 false-positive-removed pins (the
named examples), 2 bare-descriptor-already-excluded confirmations, 1 pin for the related
alias-collapse bug fix, 7 safety-regression pins (OpenAI/Kimi K3/NASA/Tesla Inc/Samsung/Google/
Saul, the last three explicitly documenting the unchanged limitation per the authorization's own
instruction), 3 nationality tests (2 preserved official names + 1 direct unit test of the
asymmetric rule), and 2 end-to-end tests (a fully-resolved case reaching `pass`, and a
false-negative-safety pin confirming a genuine fabricated entity with no generic prefix is still
caught).

Two pre-existing M7.1 tests were **updated** (not silently broken) to reflect the real, improved
`847618cd` behavior — both changes disclosed in-place with a comment explaining exactly what
changed and why (`test_847618cd_raw_audit_improves_directly_under_m7_2` now asserts `severity ==
"low"` and `entity_flags == []`; `test_847618cd_entity_and_causal_flags_survive_calibration_
known_remaining_issue` renamed to `test_847618cd_only_causal_flag_survives_after_m7_3_known_
remaining_issue` and asserts `true_positive_flags == []`).

Combined (`test_fact_safety.py` + `test_fact_safety_calibration.py` + `test_phase17_stage2_
candidate_generation.py` + M7.1/M7.2/M7.3 files): **187 passed, 2 failed** (the same pre-existing
baseline).

**Full regression suite**: **19 failed, 2088 passed, 147 warnings in 2404.97s**. The 19 failures
are byte-for-byte identical to the documented baseline — **zero new regressions**.

`python -m ruff check` on every touched file: all checks passed. `python -m mypy services/
fact_safety.py`: no issues found. `python -m scripts.phase17_cutover_preflight`: OVERALL PASS, all
Phase 17 modes confirmed still off.

## Recommendation for future named-entity-recall work

Option B (loosening single-token recall for a word left over after generic-prefix stripping, so
`"Saul"` and similar bare names get a real chance to match evidence) remains the natural next step
in this same problem family, but is a larger, separately-authorized effort — it needs its own
false-positive regression sweep (a bare, ordinary word surviving a stripped prefix is a genuinely
new pattern this codebase has never tested) before it can ship with the same confidence this
milestone's narrower fix has. Causal/hedge detection (M7 discovery class #3 — the one remaining
flag on `847618cd`'s candidate) is a separate, independent effort, **not started automatically per
instruction**.
