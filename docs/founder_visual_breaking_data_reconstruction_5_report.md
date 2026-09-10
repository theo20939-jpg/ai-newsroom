# FOUNDER-VISUAL-BREAKING-DATA-RECONSTRUCTION-5 — report

## A. Base SHA

`1b6aa09` (`feature/launch-readiness-visual-recap-parallel-1`; parent of that = `5a113b0`).
Worktree `C:/Users/Theodor/ai-newsroom-launch-visual-recap-1`, working tree clean at start
(no unrelated dirty/untracked work; selective staging only; no reset/clean/rebase/amend).

## B. Final SHA

The commit that carries this report on `feature/launch-readiness-visual-recap-parallel-1`
(parent `1b6aa09`) — see `git log`.

## C. Founder rejection statement

After visually reviewing `01_BREAKING_DARK` / `02_BREAKING_LIGHT` / `03_DATA_GENERATED_A` /
`04_DATA_GENERATED_B` / `05_DATA_SOURCE_LIGHT` / `06_DATA_SOURCE_DARK` from RECOVERY-4:
**BREAKING = REJECTED, DATA_GENERATED = REJECTED, DATA_SOURCE_INFOGRAPHIC = REJECTED.** The
BREAKING pulse still does not match the reference; the line geometry still looks
crude / broken / mechanically constructed; the DATA graph styling, background and typography do
not match the board; the DATA result still looks like a programmatically generated chart. These
are **structural** mismatches — not cosmetic polish.

## D. Founder board re-analysis (`docs/founder_telegram_board.png`, 1024×1280, re-inspected)

* **BREAKING** — thin red ECG along the **lower edge** of the photo, **LEFT-anchored**, spanning
  ≈ 46 % of the photo width. Pixel-traced: baseline at the photo's bottom edge; a single complex —
  small P bump, sharp narrow **R** (+20 px), **deep S** trough (−15 px → **S/R ≈ 0.70**), small T
  bump — then a flat tail. A separate faint `⋔⋔` grey watermark glyph sits bottom-right (not part
  of the pulse). No dark band, no baked headline.
* **DATA** — background mean RGB **(6, 7, 9)** (near-black, faint cool tint); a *barely-there*
  technical grid (peak ≈ +11 over bg, ≈ 1/9 of card width). Left text zone ≈ **0.38** of the
  width: `500` (white) / `МЛН` (red) stacked in a **heavy black-weight** grotesque with
  near-circular zeros, `ПОЛЬЗОВАТЕЛЕЙ` (white caps), a grey 2-line secondary, a red **outlined
  `+38%` pill**. Right zone: a rising red **area** line to a **white end-dot** (~45 % height),
  with a restrained red glow that hugs the curve (not a solid triangle).

## E. Complete asset inventory

`design/founder_visual_breaking_data_fix_5_asset_inventory.md` (full table + git-history method).
`OVERLAY_RECOVERY_CONFIDENCE = HIGH` that the tracked image set is the complete historical set:
`git log --all --diff-filter=D` for images → **none ever deleted**; every `.svg` ever → the two
`nnj_logo*` wordmarks; every `.ttf/.otf` ever → **none**.

## F. Overlay assets found

Same set RECOVERY-4 found — nothing new, nothing hidden. Relevant: `breaking_minimal_01.png`
(FOUND_REJECTED), `universal_minimal_0{1,2,3}.png` / `universal_graphite_*` (4:5 design refs,
`production_runtime_asset: false`), `data_minimal_0{1,2,3}.png` (decorative bottom-left motif, not
the hero chart), `data_template_{white,red}.png` (approved *layout spec*, reference only). **No
dedicated approved BREAKING overlay and no DATA hero background/grid/chart asset exists.**

## G. Historical asset provenance

`695a1f1` added the 4:5 overlay pack; `de5ba2e` added `data_template_*`; `a74f708` added the
procedural pulse primitive. `design/reference_manifest.md` (generated from the project's own
manifests) records BREAKING as `REFERENCE_MISSING (production_approved)` and every overlay as
design-DIRECTION only, with the recorded product decision "Do NOT stretch the 1122×1402 overlays
into 16:9". So the geometry authority for this phase is the Founder board itself.

## H. BREAKING visual diff (RECOVERY-4 vs board)

| Property | RECOVERY-4 (rejected) | Founder board | RECONSTRUCTION-5 |
|---|---|---|---|
| anchor | horizontally **centred** | **left**-anchored | left-anchored (`_BREAKING_PULSE_LEFT_FRAC=0.03`) |
| span | 0.62 · width | ≈ 0.46 · photo width | 0.46 · width (`_BREAKING_PULSE_WIDTH_FRAC`) |
| S undershoot | ~0.28 · R (shallow) | **≈ 0.70 · R (deep)** | 0.70 · R (traced) |
| baseline | 0.86 · h | at the photo bottom edge | 0.93 · h (S stays on-canvas) |
| shape source | hand-set off a 4:5 raster | the board | **pixel-trace of the board** |
| stroke | 0.006 · h | thin, clean | 0.0045 · **width**, 4× SS → LANCZOS |

## I. BREAKING final overlay source

`BREAKING_OVERLAY_SOURCE = docs/founder_telegram_board.png` (pixel-traced; §9 option D). Baked as
`services/brand_renderer.py::_PULSE_WAVEFORM_UNIT` (23-point P-QRS-T, `x∈[0,1]`, `y` in
"R apex = 1.0" units). No raster composited.

## J. BREAKING implementation

`_draw_recovered_pulse(base_rgba, *, x_left, baseline_y, span, amplitude, stroke, color, waveform)`
— builds a `(span+2·pad)×head` RGBA layer at 4× scale, maps `_PULSE_WAVEFORM_UNIT` onto it,
`_catmull_rom`-smooths, strokes with `joint="curve"`, `resize(÷4, LANCZOS)`, `alpha_composite`.
`render_breaking_frame`: `x_left = 0.03·w`, `baseline_y = 0.93·h`, `span = 0.46·w`,
`amplitude = 0.13·span` (aspect-safe — amplitude scales with the span, not raw canvas pixels),
`stroke = 0.0045·w`. One `rasterize_nnj_mark` in the quieter bottom corner. No `_draw_pulse` on
this path (the crude polyline stays only for the FROZEN NEWS / DATA-source lower signature).
Evidence: `renderer_version = "pulse-breaking-v5-board"`, `placement_zone = "lower_left"`.

## K. DATA visual diff (RECOVERY-4 vs board) — mismatch matrix

| Element | RECOVERY-4 (rejected) | Founder board | RECONSTRUCTION-5 |
|---|---|---|---|
| background | `(14,14,16)` | `(6,7,9)` measured | `(6,7,9)` |
| grid | `(24,24,28)` @ 96 px | peak ≈ +11 @ ≈1/9 width | `(17,18,22)` @ 144 px |
| value/unit weight | Arial **Bold** | black-weight grotesque | Arial **Black** (`heavy` face) |
| left zone | 0.46 · width | ≈ 0.38 · width | 0.38 · width |
| curve | smooth monotone, hard-ish fill | organic + soft glow | smooth monotone, **restrained glow** (vgrad³ × hgrad) |
| end-dot | white | white | white |
| pulse motif | traced-off-raster | board pulse | board pulse (`_PULSE_WAVEFORM_UNIT`) |

## L. DATA background reconstruction / source

No background/grid asset exists (disclosed blocker). Reconstructed deterministically from the
board's pixel-measured `(6,7,9)` ground + a single-pixel `(17,18,22)` grid at 144 px — subtle
technical depth, never a visible "developer dashboard" square grid. `_draw_hero_grid` unchanged
in structure, only its measured colour/step.

## M. DATA typography investigation

`FOUNDER_BOARD_FONT_REFERENCE = UNKNOWN` (unidentifiable; no font file has ever been in the repo).
`07_TYPOGRAPHY_COMPARISON.png` renders `500 / МЛН / ПОЛЬЗОВАТЕЛЕЙ / +38%` in every heavy OS face
available: Arial Bold (RECOVERY-4), **Arial Black**, Segoe UI Black, Bahnschrift, Arial Narrow
Bold, Tahoma Bold. Evaluated on weight, near-circular numerals, Cyrillic quality, condensation,
uppercase, spacing.

## N. Selected font + rationale

    DATA_FONT_FAMILY  = Arial (OS-provided; same family as the existing regular face)
    DATA_FONT_HEAVY   = C:/Windows/Fonts/ariblk.ttf  (Arial Black)  — value + unit
                        Linux VPS fallback: DejaVuSans-Bold.ttf / LiberationSans-Bold.ttf
    DATA_FONT_BOLD    = C:/Windows/Fonts/arialbd.ttf  (Arial Bold)  — label
    DATA_FONT_REGULAR = C:/Windows/Fonts/arial.ttf  — grey secondary
    FONT_MATCH_CONFIDENCE = MEDIUM

Arial Black matches the board's weight and near-circular digit shapes and has clean Cyrillic;
Segoe UI Black is close but Windows-only with no Linux equivalent. A true *condensed* black
grotesque would need a Founder-supplied, license-clear font asset — disclosed gap. New resolvers
`_resolve_heavy_font_path` / `_resolve_bold_font_path` degrade heavy → bold → regular; nothing is
downloaded or shipped. `core/config.py` adds optional `brand_font_heavy_path`.

## O. DATA graph implementation

`_draw_hero_sparkline(canvas, series, *, box)` — anchors at exact linear x, min-max-normalised y,
verbatim. `_monotone_cubic` (Fritsch-Carlson) densifies for a smooth curve. Rendered on a 4× RGBA
layer: gradient area fill (`vgrad ** 3.0` fades fast downward × `hgrad` dimmer to the left → a
glow that hugs the curve, not a wedge) → smooth stroke → white end-dot → `LANCZOS` down. Chart box
`(0.44·W, 0.16·H) … (W−margin, 0.86·H)`.

## P. Graph interpolation / factual safety

`_monotone_cubic` is **monotone by construction** → the curve never leaves `[min, max]` of any
adjacent pair → it can never imply a value outside the supplied series. No numeric label is
derived from the interpolated path. `< 3` points → straight segment; `< 2` → no chart. The series
values are the sole factual anchors and are plotted verbatim
(`test_hero_graph_interpolation_never_overshoots_and_has_no_synthetic_points`,
`test_hero_metric_is_verbatim_and_wrapping_is_deterministic`).

## Q. DATA source treatment

`render_data_card` (MINIMAL_SOURCE_PRESERVING): the fitted infographic + an adaptive **bottom-only
pulse+mark** signature *when* `_select_data_signature` can place it safely (thin, adaptive
white/red); otherwise **BRAND SUPPRESSION** — the source ships unbranded. The RECOVERY-4 fallback
**badge / dark plate is gated OUT of this path** (`presentation_mode != MINIMAL_SOURCE_PRESERVING`
guard; the legacy stat-block DATA card keeps its MEDIA-PROD-1 guarantee). Third-party publisher
logos are never touched (`06c_DATA_SOURCE_BR_OCCUPIED.png`). Canaries: light → suppressed (clean);
dark → thin bottom pulse+mark placed.

## R. One-NNJ result

`FINAL_VISIBLE_NNJ_COUNT <= 1` everywhere: BREAKING = 1; DATA generated = 1 (lower-right);
DATA source = 1 (adaptive signature) or 0 (suppressed); internal already-NNJ template = 0 renderer
marks (`source_carries_canonical_nnj`). `render_data_card` composites at most one signature layer.

## S. RenderEvidence changes

* BREAKING: `renderer_version` `pulse-breaking-v4-recovered` → **`pulse-breaking-v5-board`**;
  `placement_zone` `lower_center` → **`lower_left`**; `notes.overlay_asset` now names
  `docs/founder_telegram_board.png` (pixel-traced, no raster composited).
* DATA hero: `renderer_version` `pulse-data-hero-v1` → **`pulse-data-hero-v2-board`**; the deriver
  replays the REAL fit (`heavy=True`, board-measured left column) so `primary_font_size` is
  truthful; new `notes`: `typography` (weight per role + resolved heavy face), `graph_interpolation`
  (monotone_cubic, non-overshooting), `graph_factual_series_count`, `background_version`.
* DATA source: unchanged fields; the suppression path reports `logo_count` truthfully.

## T. VisualSpec candidate impact

No production VisualSpec touched, nothing promoted. `telegram_breaking` v1 declares
`placement_zone: lower_left` — the reconstructed pulse now genuinely IS `lower_left`, so SPEC_MATCH
against it is **PASS** (the previous soft `SPEC_PLACEMENT_ZONE_MISMATCH` is resolved by the
renderer, not by weakening the spec). The stale `telegram_data` v1 font range `[48, 88]` vs the
hero's heavy value size remains a pre-existing local-candidate gap (unrelated test
`test_visual_spec_v2_activation::test_final_matrix…` was already red on `1b6aa09`).

## U. Canary matrix

| File | Input | Result |
|---|---|---|
| `01_BREAKING_DARK.png` | `case1_hero_product_iphone.jpg` | short left-anchored deep-S pulse, lower edge, 1 mark, no band |
| `02_BREAKING_LIGHT.png` | `case3_bright_promotional_scene.jpg` | same, reads cleanly on a bright source |
| `03_DATA_GENERATED_A.png` | `500` / `МЛН` + rising 7-pt series | heavy type, near-black bg, faint grid, smooth glow-fill curve + end-dot, board pulse motif, 1 mark |
| `04_DATA_GENERATED_B.png` | `68` / `%` + different 5-pt series | proves it is a SYSTEM |
| `04c_DATA_GENERATED_C_short_label.png` | `1,4 млрд` / `сообщений` + 4-pt series, short label | long value fits one line; typography scales |
| `05_DATA_SOURCE_LIGHT.png` | deterministic light infographic (no NNJ) | source preserved exactly; branding suppressed (no badge) |
| `06_DATA_SOURCE_DARK.png` | deterministic dark infographic (no NNJ) | source preserved; thin bottom pulse+mark placed |
| `06c_DATA_SOURCE_BR_OCCUPIED.png` | light infographic + `chartsource.io` watermark bottom-right | publisher watermark untouched; branding suppressed |

## V. Review package paths

`C:/Users/Theodor/Desktop/NINJA_PULSE_BREAKING_DATA_FIX_V5/` —
`00_REFERENCE_VS_FIXED.png` (board BREAKING + DATA crops on top, all fixed outputs below at large
size), `01`–`06` + `04c` + `06c` renders, `07_TYPOGRAPHY_COMPARISON.png`, `08_ASSET_PROVENANCE.md`.
Mirror in `artifacts/founder_visual_breaking_data_reconstruction_5/`.

## W. Tests

New `tests/test_founder_visual_breaking_data_reconstruction_5.py` (16, all passing): board-traced
left-anchored deep-S waveform; supersampled primitive, no crude polyline; pulse in the lower-media
left half + no dark band; no baked headline, one mark, evidence v5; board-measured near-black bg;
heavy face for value/unit; verbatim metric + deterministic wrap; interpolation non-overshooting +
no synthetic points + data-driven; area fill is a restrained glow not a block; motif uses the
board primitive; exactly one NNJ; DATA source light/dark preserved; suppression not a badge;
FINAL_VISIBLE_NNJ ≤ 1; NEWS/QUOTE/QUOTE_NO_ROLE frozen.

Updated: `test_founder_visual_overlay_recovery_4.py` (new waveform morphology, evidence v5),
`test_founder_visual_polish_2.py` (DATA-source no-badge / suppression contract, v5, `lower_left`),
`test_brand_renderer.py`, `test_render_evidence_parity.py`, `test_founder_visual_board_alignment_1.py`,
`test_design_spec_enforcement.py` (BREAKING v5 now PASSes `telegram_breaking` v1's `lower_left`).

Broad regression sweep: **350 passed, 6 skipped, NEW_FAILURES = 0**. Pre-existing on `1b6aa09`
(verified via `git stash`): `test_visual_spec_v2_activation::test_final_matrix_all_pass_no_placement_zone_partial`
and `test_presentation_director_mode_contract::test_enforce_gate_actually_assigns_every_mutating_target_at_least_once`;
plus the pre-existing collection errors in `test_v2_4d_overlay_contract.py` / `test_v2_4f_compact_overlay.py`.

## X. Static checks

`ruff check` on all changed `services/`, `core/`, `tests/`, `scripts/` files → clean.
`mypy services/brand_renderer.py services/render_evidence.py core/config.py` → clean.
**NEW_STATIC_ERRORS = 0.**

## Y. Changed files

```
services/brand_renderer.py    board-traced pulse (_PULSE_WAVEFORM_UNIT + _draw_recovered_pulse left-anchored);
                              heavy font tier (_resolve_heavy_font_path, _font(heavy=)); DATA hero bg/grid/
                              layout/typography/area-fill reconstructed from board measurements; DATA source
                              badge fallback gated out of MINIMAL mode (suppression)
services/render_evidence.py   BREAKING evidence v5 / lower_left / board provenance; DATA hero evidence v2-board,
                              truthful heavy-face replay, typography/interpolation/series/background notes
core/config.py                optional brand_font_heavy_path pin
tests/test_founder_visual_breaking_data_reconstruction_5.py   NEW (16)
tests/test_founder_visual_overlay_recovery_4.py               new waveform morphology + evidence v5
tests/test_founder_visual_polish_2.py                         DATA-source no-badge/suppression + v5 + lower_left
tests/test_render_evidence_parity.py / test_founder_visual_board_alignment_1.py                 v5 version + lower_left
tests/test_design_spec_enforcement.py                          v5 version + lower_left + BREAKING SPEC_MATCH now PASS
scripts/_founder_visual_breaking_data_reconstruction_5_canary.py   NEW
design/founder_visual_breaking_data_fix_5_asset_inventory.md       NEW
artifacts/founder_visual_breaking_data_reconstruction_5/           NEW (00–08 + 04c + 06c)
docs/founder_visual_breaking_data_reconstruction_5_report.md       NEW (this file)
```

## Z. Remaining visual mismatches

1. **DATA graph character** — the board's curve reads organic/jagged (it plots a denser series);
   the reconstruction renders a *smooth* monotone curve because the `DataCandidate.series` is
   sparse (4–7 points) and fabricating volatility is forbidden. Confirm the smooth reading is
   acceptable, or supply denser structured data.
2. **Exact DATA typeface** — `FONT_MATCH_CONFIDENCE = MEDIUM`. Arial Black matches weight and
   digit shape; a *condensed* black grotesque needs a Founder-supplied font asset.
3. **BREAKING `⋔⋔` watermark glyph** — visible faint on the board behind the pulse; not
   reproduced (a new decorative element, out of scope for a reconstruction pass).
4. **DATA source framed graphite panel** (`data_template_*` contain-fit) — still deferred; it
   destabilises the source-signature safety scoring and needs its own bounded pass.
5. **DATA hero area-fill intensity** near the peak is still fairly saturated vs the board's softer
   diffuse glow — tunable if the Founder wants it lighter.
6. **VPS heavy-face availability** — unverified from this environment; the resolver degrades to
   bold, then regular.

---

`FOUNDER_VISUAL_BREAKING_DATA_RECONSTRUCTION_5_READY_FOR_REVIEW`

No production touched. The Founder must visually inspect the reconstructed BREAKING and DATA
outputs before any production work. Work stops here.
