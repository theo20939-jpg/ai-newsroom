# Foldable iPhone Replay — mandatory evidence (§9)

Real, end-to-end selection replay through `services.editorial_pipeline.media.MediaResearchService.
research()` (the exact call the unified pipeline makes), with the real, newly-wired
`services.editorial_pipeline.subject_match.classify_subject_match()` injected as the
`subject_match_classifier` — not a hand-rolled shortcut. Source:
`tests/test_unified_pipeline_media_truthfulness_replay.py`.

## Story intent

```python
MediaIntent(
    subject_type=PRODUCT, primary_entity="Apple's newly announced foldable iPhone",
    product_name="iPhone", model_name="foldable iPhone", company="Apple",
    must_show=["foldable design"], must_not_imply=["standard non-folding design"],
)
```

## Candidates

| ID | Text evidence | Classification | Why |
|---|---|---|---|
| A (ordinary iPhone) | "Apple iPhone 16 Pro Max in Desert Titanium, standard non-folding design" | `MISMATCH` | matches the intent's own `must_not_imply` phrase — never selectable regardless of its TIER2/official-press/6000x4000 resolution |
| B (contextual Apple) | "Apple corporate logo and Apple Park campus signage, generic corporate context photo" | `STRONG_CONTEXT` | confirms the `company` category term only |
| C (exact foldable) | "Apple's newly unveiled foldable iPhone concept, folded and unfolded views showing the foldable design" | `EXACT_SUBJECT` | confirms both required terms (`model_name` + `must_show`) — despite deliberately LOW 800x600 resolution |

## Results

| Scenario | Candidates offered | Selected | `WRONG_IPHONE_IMAGE_SELECTED` |
|---|---|---|---|
| C present | A, B, C | **C** (the low-resolution, confirmed-exact candidate) | `false` |
| C absent | A, B | **B** (truthful contextual fallback) | `false` |
| Only A available | A | **none** (`selected=None`, `exact_subject_media_not_found=True`) | `false` |

Test node IDs (all passing):
```
tests/test_unified_pipeline_media_truthfulness_replay.py::test_foldable_iphone_ordinary_candidate_is_classified_mismatch
tests/test_unified_pipeline_media_truthfulness_replay.py::test_foldable_iphone_replay_exact_candidate_present_wins_over_wrong_and_generic
tests/test_unified_pipeline_media_truthfulness_replay.py::test_foldable_iphone_replay_no_exact_candidate_falls_to_truthful_contextual_fallback
tests/test_unified_pipeline_media_truthfulness_replay.py::test_foldable_iphone_replay_only_wrong_candidate_available_never_selected_as_exact
tests/test_unified_pipeline_media_truthfulness_replay.py::test_low_quality_exact_candidate_beats_high_quality_mismatch_at_selection
```

`WRONG_SUBJECT_CAN_WIN = false` in every one of the three scenarios this replay covers.
