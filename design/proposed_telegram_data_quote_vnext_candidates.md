# telegram_data / telegram_quote vNEXT — Founder-review CANDIDATES (not promoted)

Status: **CANDIDATE only.** `AUTO_PROMOTION=false`. Created via the canonical registry lifecycle
(`create_candidate_spec()`), never `promote_candidate()`. Applied to the **development
control-plane DB only**; production is untouched. Founder promotion is a separate, explicitly
authorized phase.

Origin: `FOUNDER-VISUAL-BOARD-ALIGNMENT-1`, against visual authority `docs/founder_telegram_board.png`
(the real Founder-approved Telegram board — board format 3 "DATA", board format 4 "QUOTE").

## Why

The board's **generated DATA** post is a hero-metric infographic ("500 / МЛН / ПОЛЬЗОВАТЕЛЕЙ",
grey secondary line, red trend line, red delta pill, technical grid, black/graphite base) — not
the retired V2.20 compact-corner stat on a photo. The renderer now produces that
(`brand_renderer.render_data_hero_card`), so the ACTIVE `telegram_data` v1 parameters no longer
describe the accepted render:

| field | v1 ACTIVE | why it no longer fits the hero card |
|---|---|---|
| `font_size_max` / `font_size_min` = 88 / 48 | compact corner stat | the hero primary number is dominant — fitted in `[88, 200]` |
| `source_image_treatment` = `preserve` | source photo is the primary visual | the hero card is a **generated** panel — there is no source photo to preserve/crop |
| (no placement field) | — | the hero metric block sits `upper_left`; worth declaring as a checked invariant |

The board's **QUOTE** post keeps the same margin / logo-zone / scrim / (no) source-photo
semantics as v1 — the change is compositional (large red quote-mark motif, author name in NNJ
red, author role/title in smaller grey, and the `PULSE / QUOTE` label + `NP-xxxx` code **removed**
from the baked media because the board renders them Telegram-natively). None of that maps to a new
`DeclarativeVisualParameters` field, so the `telegram_quote` candidate carries the **same
parameters as v1** and records the composition change in `notes` for the Founder's record.

`telegram_data` EXISTING-INFOGRAPHIC handling is unchanged and still governed by v1 semantics via
`MINIMAL_SOURCE_PRESERVING` — a pre-made infographic is **never** converted into a hero card
(Founder decision, phase §3). `NUMBER_MISMATCH` and `INFOGRAPHIC_DESTROYED` remain hard BLOCK.

## telegram_data vNEXT (CANDIDATE)

```
scope:            telegram_data
spec_type:        declarative_visual_params
supersedes:       <telegram_data v1 id>
parameters:
    font_size_max:           200          # hero primary number (was 88)
    font_size_min:            88           # (was 48)
    max_line_count:          2            # unchanged — label wraps to <= 2 lines
    safe_margin_frac:        0.019         # unchanged
    logo_zone:               lower_right   # unchanged — exactly one NNJ mark, lower-right
    scrim_treatment:         none          # unchanged
    placement_zone:          upper_left    # NEW — the dominant metric block's own corner
    # source_image_treatment: REMOVED  (the generated hero card uses no source photo)
notes: "vNEXT (FOUNDER-VISUAL-BOARD-ALIGNMENT-1, board format 3): generated DATA hero-metric card
        - dominant primary number (white) + unit (NNJ red) + label (white) + grey secondary line
        + optional red delta pill + optional red trend line plotted verbatim from a supplied
        series + technical grid. EXISTING_INFOGRAPHIC still routes to MINIMAL_SOURCE_PRESERVING
        under v1 semantics. Not promoted."
```

## telegram_quote vNEXT (CANDIDATE)

```
scope:            telegram_quote
spec_type:        declarative_visual_params
supersedes:       <telegram_quote v1 id>
parameters:
    safe_margin_frac:        0.019         # unchanged
    logo_zone:               lower_right   # unchanged — exactly one NNJ mark
    scrim_treatment:         none          # unchanged (the dark left panel is the card's own ground)
    source_image_treatment:  preserve      # unchanged — portrait pasted at its own aspect, no crop
notes: "vNEXT (FOUNDER-VISUAL-BOARD-ALIGNMENT-1, board format 4): large red quote-mark motif;
        dominant white quote body (verbatim, font-fitted, never clipped); author portrait on the
        supporting right strip; author name in NNJ red; author role/title beneath in smaller
        neutral grey (drawn only when supplied - never fabricated). The PULSE/QUOTE label and the
        NP-xxxx editorial code are NO LONGER baked into the media (the board renders them
        Telegram-natively). Parameters are byte-identical to v1. Not promoted."
```

## How to apply (Founder, later — NOT this phase)

`scripts/propose_visual_spec_vnext_candidates.py` is idempotent: it creates the two CANDIDATE
rows if absent and never promotes. A later, explicitly-authorized phase runs
`promote_candidate()` after Founder review.
