# Proposed CANDIDATE specs — telegram_news v2 / telegram_breaking v2

Status: **FOUNDER REVIEW REQUIRED. Not applied. No DB row created (VISUAL-RENDERER-
RECONCILIATION-1 §19 forbids DB mutation this phase).** This document is the reviewable diff.

## Why

`VISUAL-RENDERER-RECONCILIATION-1 §1` forensically reconciled NEWS against the accepted design
authority order. Conclusion: **`NEWS_MASTER_EXPECTED_LAYOUT = B` (FUSED_LOWER_RIGHT_SIGNATURE)**.

Evidence (authority order 1 → 6):

1. **Explicit user-approved decision** — `services/nnj_master_news_overlay.py` module docstring:
   "Phase V2.10H — the locked MASTER NEWS visual contract … **user-approved production selection:
   MASTER_BALANCED lower signature + MEDIUM upper mark**", later narrowed by
   `VISUAL-SINGLE-BRAND-MARK-1` (commit `7761a35`) to exactly one canonical mark. The approved
   unit is **one lower signature = thin edge line + pulse + NNJ mark, fused, at one corner
   (LOWER_RIGHT preferred)**.
2. **Master prototype** —
   `assets/brand/newsroom_visuals/v1/references/nnj_editorial_visual_system_master_prototype.png`,
   NEWS row (and BREAKING row, and DATA row): the red pulse/ECG line runs left→right along the
   bottom and **terminates at the "nnj" wordmark on the RIGHT** — a single continuous bottom
   signature, not a separate lower-left accent. See
   `assets/brand/newsroom_visuals/vrr1_reconciliation/news_current_vs_master.png` — current
   production NEWS is pixel-consistent with the prototype.
3. **Visual-system doc** `docs/nnj_editorial_visual_system_v1.md` §1: "a thin bottom-edge line
   (optionally carrying a small red NNJ pulse/ECG motif) and restrained NNJ branding **as the
   signature device**" — one signature device. (§4's `render_news_hero()` "logo bottom-right …
   pulse line bottom-left" is a superseded implementation note for a path that is
   dead/unreachable from the real send path — the doc's own words.)
5. **ACTIVE `telegram_news v1`** declares `placement_zone=lower_left`. This was derived from the
   superseded §4 `render_news_hero` note, **not** from the approved MASTER contract / prototype.
   It is a wrongly-derived parameter (authority 5, overruled by 1–3).

`telegram_breaking v1` carries the **same** `placement_zone=lower_left`, from the same source, and
after this phase's renderer correction BREAKING uses the identical MASTER NEWS fused signature —
so the same correction applies.

## The correction (semantic only — nothing else changes)

**Drop `placement_zone`.** The pulse is part of the single lower signature, whose anchor corner is
already captured by `logo_zone=lower_right`. There is no independently-placed accent for
`placement_zone` to describe. (Alternative the Founder may prefer: set `placement_zone=lower_right`
to keep the field and make it an explicit checked invariant — functionally equivalent for
SPEC_MATCH, which then returns PASS either way.)

Every other parameter is unchanged.

### telegram_news v2 (proposed)

```
scope:            telegram_news
spec_type:        declarative_visual_params
supersedes:       <telegram_news v1 id>
parameters:
    safe_margin_frac:        0.019      # unchanged
    logo_zone:               lower_right # unchanged
    scrim_treatment:         none        # unchanged
    source_image_treatment:  preserve    # unchanged
    # placement_zone:        REMOVED  (was lower_left — wrongly derived; the pulse is fused into
    #                                  the single lower-right signature per the master prototype)
notes: "v2 (VISUAL-RENDERER-RECONCILIATION-1 §1/§3, case B): placement_zone dropped. The MASTER
        NEWS renderer was NOT changed - it already matches the approved prototype's fused
        lower-right signature. This removes the last SPEC_MATCH PARTIAL_EVIDENCE gap for NEWS."
```

### telegram_breaking v2 (proposed)

```
scope:            telegram_breaking
spec_type:        declarative_visual_params
supersedes:       <telegram_breaking v1 id>
parameters:
    safe_margin_frac:        0.019      # unchanged
    logo_zone:               lower_right # unchanged
    scrim_treatment:         none        # unchanged — NOW SATISFIED: the retired dark-gradient
    #                                      band + baked "BREAKING" wordmark + red accent rule were
    #                                      removed from render_breaking_frame() in this phase.
    source_image_treatment:  preserve    # unchanged
    # placement_zone:        REMOVED  (same rationale as telegram_news v2)
notes: "v2 (VISUAL-RENDERER-RECONCILIATION-1 §5-9): placement_zone dropped. render_breaking_frame()
        was corrected to the restrained NEWS family (native-size source + the exact MASTER NEWS
        fused lower signature via select_master_news_branding()). Removes the last SPEC_MATCH
        PARTIAL_EVIDENCE gap for BREAKING."
```

## How to apply (Founder, later — NOT this phase)

```python
from services.design_spec_registry import create_candidate_spec, promote_candidate
from database.models.design_spec_version import DesignSpecType

news_v2 = await create_candidate_spec(
    session, scope="telegram_news", spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
    parameters={"safe_margin_frac": 0.019, "logo_zone": "lower_right",
                "scrim_treatment": "none", "source_image_treatment": "preserve"},
    notes="v2 VISUAL-RENDERER-RECONCILIATION-1: drop wrongly-derived placement_zone",
)
# review, then:  await promote_candidate(session, news_v2.id)

breaking_v2 = await create_candidate_spec(
    session, scope="telegram_breaking", spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
    parameters={"safe_margin_frac": 0.019, "logo_zone": "lower_right",
                "scrim_treatment": "none", "source_image_treatment": "preserve"},
    notes="v2 VISUAL-RENDERER-RECONCILIATION-1: band removed + drop wrongly-derived placement_zone",
)
# review, then:  await promote_candidate(session, breaking_v2.id)
```

After promotion, `_evaluate_spec_match` (unchanged) returns **SPEC_MATCH = PASS** for both NEWS and
BREAKING on their accepted renders — verified in
`tests/test_design_spec_enforcement.py::test_breaking_corrected_render_has_no_band_no_scrim_mismatch_and_matches_news_family`
(the `v2_params` assertion) and
`tests/test_render_evidence_parity.py`.

`AUTO_PROMOTION = false`. `NEWS_SPEC_CORRECTION_REQUIRES_FOUNDER_APPROVAL = true`.
`BREAKING_SPEC_CORRECTION_REQUIRES_FOUNDER_APPROVAL = true`.
