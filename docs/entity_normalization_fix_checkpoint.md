# ENTITY NORMALIZATION FIX CHECKPOINT

Scope: implements exactly the calibrated fix authorized after `docs/research_reuse_entity_normalization_checkpoint.md` — the five real-evidence-backed generic-prefix tokens, nothing broader. Against committed HEAD `c308d45f6d55dc895eabe24b1901e1f99f855bbe` plus the working tree's accumulated post-acceptance fixes. Not committed, not deployed.

## Exact code change

`services/story_memory.py`:

1. A new, deliberately **separate** frozenset, `_CALIBRATED_GENERIC_PREFIX_ENTITIES`, added immediately after the existing `_GENERIC_DETERMINER_ENTITIES` — kept apart rather than merged in, so that set's own docstring claim ("never hardcoded from any calibration case") stays true.
2. `_strip_leading_determiner()` now strips a leading token found in *either* set (identical mechanism, extended membership check).
3. `_extract_entities()`'s standalone-exclusion check (a candidate that is *entirely* a generic token, e.g. a bare sentence-initial "Компания" with nothing capitalized after it) now also checks the new set.

No other file touched. No threshold, weight, RELATED_STORY policy, suppression semantics, or Research-reuse logic modified.

## Exact five-token scope

```python
_CALIBRATED_GENERIC_PREFIX_ENTITIES = frozenset({
    "в", "от", "отчёт", "компани", "правительств",
})
```

Exactly the five tokens authorized, in the post-case-stripped form the extraction pipeline actually produces (`normalize_for_entity_match()` → `strip_ru_case_suffix()` runs *before* this check) — `"компани"`/`"правительств"`, not the dictionary forms `"компания"`/`"правительство"`. No additional nouns or prepositions added.

## VK before/after (real scoring path)

Ran the exact real VK pair (`NewsEvent` titles from the forensic report) through `extract_story_signature()` + `score_candidate()`:

| | Before | After (actual, measured) |
|---|---|---|
| Event 1 entities | `["vk"]` | `["vk"]` (unchanged) |
| Event 2 entities | `["отчёт vk"]` | `["vk"]` |
| `entity_overlap` | `0.0` | **`1.0`** |
| `title_overlap` | `0.8` | `0.8` (unchanged — title text itself untouched) |
| `combined` score | `0.37` | **`0.9700000000000001`** |
| Story Memory zone | `uncertain_match` (below `_LOW_THRESHOLD`... actually between 0.35–0.65) | Confident match zone (`>= _HIGH_THRESHOLD = 0.65`) |

The actual measured result (`0.97`) lands almost exactly on the calibration's own predicted counterfactual (`≈0.97`) — reported as measured, not forced.

## Calibration negatives preserved (verified directly, real titles)

| Case | Result |
|---|---|
| `"AI Cloud"` (standalone `"ai"`, 149 real corpus occurrences) | `"ai cloud"` entity preserved intact |
| `"Google Pixel"` | `"google pixel"` preserved intact |
| `"Apple Watch"` | `"apple watch"` preserved intact |
| `"Amazon Bedrock"` | `"amazon bedrock"` preserved intact |
| `"GitHub Copilot"` | `"github copilot"` preserved intact |
| `"The Witcher"` / bare `"Witcher"` (CD Projekt) | Both still normalize to `"witcher"` — governed entirely by the pre-existing, unchanged `_GENERIC_DETERMINER_ENTITIES`/`"the"` handling, untouched by this fix |
| `"The Guardian"` (pre-existing, already-shipped behavior) | Unchanged — still `"guardian"`, exactly as before this fix (a disclosed, out-of-scope characteristic of the already-shipped CD Projekt fix, not touched here) |
| `"Компания Google"` | `"google"` — confirms the new set correctly reduces to the real entity when a genuine company name follows |
| Two distinct VK stories (earnings vs. a hypothetical product launch) sharing the `"vk"` entity | `entity_overlap=1.0` (correctly shared), but `title_overlap` stays low and `combined` stays below `_HIGH_THRESHOLD` — no false merge from entity overlap alone |

## Tests

All 8 required cases added to `tests/test_story_memory.py`, all passing:

1. `test_real_vk_pair_entity_overlap_and_score_reach_calibrated_counterfactual` — the exact real VK failure shape, asserts the measured before/after numbers above.
2. `test_otchet_vk_normalizes_to_bare_vk` — "Отчёт VK".
3. `test_kompaniya_vk_normalizes_to_bare_vk` — "Компания VK".
4. `test_prepositional_wrappers_v_and_ot_are_stripped` — "В Steam", "От MCP".
5. `test_government_wrapper_case_from_real_calibration_set` — "Правительство России" (real corpus example).
6. `test_calibration_negative_controls_preserved` — AI/Google Pixel/Apple Watch/Amazon Bedrock/GitHub Copilot, all from the checkpoint's own real negative-control list.
7. `test_cd_projekt_regression_unaffected_by_the_new_calibrated_set` — explicit re-confirmation alongside the pre-existing dedicated CD Projekt tests (`test_leading_the_is_stripped_from_a_captured_multi_word_entity`, `test_bare_entity_and_the_prefixed_entity_normalize_identically`, `test_standalone_the_is_still_fully_excluded`, `test_real_cd_projekt_pair_entity_overlap_measurably_improves`, `test_same_company_genuinely_different_event_remains_separate` — all 5 re-run and still passing).
8. `test_distinct_same_entity_vk_stories_remain_separate` — two genuinely different VK stories stay unmerged.

**Results**: `tests/test_story_memory.py` full file — **41 passed**. `tests/test_phase17_m7_3_entity_calibration.py` (a separate, pre-existing entity-adjacent calibration suite) — **17 passed**, unaffected. `tests/test_story_duplicate_guard.py` + `tests/test_analysis_reuse.py` + `tests/test_content_draft_update_repetition_check.py` combined — **46 passed**, 7 teardown-only `ERROR`s (the same well-established, pre-existing "teardown-only FK cleanup" pattern documented and confirmed repeatedly throughout this session — zero `FAILED`, confirmed by direct grep). `tests/test_story_memory_integration.py` + `tests/test_triage_orchestrator_story_memory.py` + `tests/test_triage_orchestrator_claims.py` combined (the broader, real-DB Story Memory match_story()/triage integration path) — **32 passed, 1 skipped, 0 failed**. Ruff (`services/story_memory.py`, `tests/test_story_memory.py`): clean. mypy (`services/story_memory.py`): clean. `scripts/validate_architecture.py`: clean, 0 forbidden-dependency violations.

## Remaining Story Memory risks

- **Not a general-purpose fix**: this set covers exactly the five real, calibrated tokens. Any *other* leading-noun-contamination pattern (the user's own suggested `результаты`/`заявление`/`исследование`/`презентация` had no real corpus hits and were deliberately excluded) remains unaddressed until it gets its own real-evidence check, by design.
- **The pre-existing `"the"`-stripping over-reach** (real outlet names like "The Guardian"/"The New York Times" losing their "The") remains exactly as before — disclosed again here, not touched, out of this fix's authorized scope.
- **`_RELATED_STORY_ENTITY_FLOOR`/threshold calibration remains unchanged and un-revisited** — this fix corrects the *input* (entity extraction), not the scoring bands themselves; a future pair whose entity overlap now correctly reaches, say, 0.4–0.6 (between the low and high thresholds) will still land in `uncertain_match`/`RELATED_STORY` territory exactly as the existing bands already dictate — this fix does not change what those bands do with a now-more-accurate score.
- **Standalone-single-word edge noise observed in calibration** (`"компани"`/`"от"`/`"китайск"` each had a handful of real standalone occurrences in the corpus, per the calibration's own Strategy B table) — these are pre-existing extraction artifacts (a title whose *only* capitalized run happened to be the bare generic word), now correctly excluded outright by this fix's own standalone-check extension, consistent with the pre-existing Checkpoint 6 precedent for `"this"`/`"that"`.
- **No real-corpus stress test exists yet for this fix on live natural traffic** — all verification here is against real, already-collected historical data (the VK pair, the 26-case calibration set) and unit tests; a live validation run (matching the pattern already established for the two prior fixes) would be the natural next confirmation step, not run automatically this phase.

Not committed. Not deployed. Video and source-pack work not resumed.
