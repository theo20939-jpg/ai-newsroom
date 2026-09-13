# Mismatch Rejection & Ranking Evidence (§10)

10 deterministic scenarios, all passing, covering multiple domains (product/version, vehicle,
person, event) — deliberately not overfit to any one brand or product family. Source:
`tests/test_unified_pipeline_subject_match_classifier.py` (direct classifier unit tests) and
`tests/test_unified_pipeline_media_truthfulness_replay.py` (selection-level proof for scenario 8).

| # | Scenario | Test | Result |
|---|---|---|---|
| 1 | Same brand, wrong exact product | `test_same_brand_wrong_exact_product_is_strong_context_not_exact` | `STRONG_CONTEXT`, never `EXACT_SUBJECT` |
| 2 | Same product family, wrong generation/version | `test_same_product_family_wrong_generation_is_strong_context_not_exact` | `STRONG_CONTEXT` |
| 3 | Correct exact subject | `test_correct_exact_subject_is_exact_subject` | `EXACT_SUBJECT`, confidence `high` |
| 4 | Strong contextual candidate | `test_strong_contextual_candidate` | `STRONG_CONTEXT` |
| 5 | Generic contextual candidate | `test_generic_contextual_candidate` | `GENERIC_CONTEXT` |
| 6 | Explicit mismatch, excellent technical quality (4000x3000, official press asset) | `test_explicit_mismatch_with_excellent_technical_quality_still_mismatches` | `MISMATCH` — quality/resolution/source reputation never override |
| 7 | No exact media available (no descriptive text at all) | `test_no_exact_media_available_falls_to_generic_never_fabricates_exact` | `GENERIC_CONTEXT`, confidence `low` — never fabricated `EXACT_SUBJECT` |
| 8 | Lower-quality exact candidate beats high-quality mismatch | `test_low_quality_exact_candidate_still_classified_exact_regardless_of_resolution` (classifier level) + `test_low_quality_exact_candidate_beats_high_quality_mismatch_at_selection` (real selection level, `MediaResearchService.research()`) | `EXACT_SUBJECT` selected (800x600) over `MISMATCH` (6000x4000) |
| 9 | Person identity mismatch | `test_person_identity_mismatch` | wrong person → `MISMATCH`; right person (category-only match, no `must_show`) → `STRONG_CONTEXT`, never falsely `EXACT_SUBJECT` |
| 10 | Vehicle/model identity case | `test_vehicle_model_identity_case` | wrong model year → `MISMATCH`; correct model year → `EXACT_SUBJECT` |

## Structural invariants (named exactly as the Founder review stated them)

| Invariant | Test | Result |
|---|---|---|
| SAME BRAND != SAME PRODUCT | `test_same_brand_never_equals_same_product` | never `EXACT_SUBJECT` on brand match alone |
| SAME PRODUCT FAMILY != SAME VERSION | `test_same_product_family_never_equals_same_version` | never `EXACT_SUBJECT` on family match alone |
| RELATED EVENT != EXACT EVENT | `test_related_event_never_equals_exact_event` | never `EXACT_SUBJECT` on a differing event string |

`MEDIA_TRUTHFULNESS_ENFORCED = true`. `WRONG_SUBJECT_CAN_WIN = false` — proven both at the
classifier level (13 tests) and at the real selection level (5 tests, including the mandatory
foldable iPhone replay).
