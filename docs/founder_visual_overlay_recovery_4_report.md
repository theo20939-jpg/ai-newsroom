# FOUNDER-VISUAL-OVERLAY-RECOVERY-4 — report

**Phase type:** visual asset / overlay recovery (renderer + evidence only).
**Visual authority #1:** `docs/founder_telegram_board.png` (re-inspected).
**Production:** NOT touched — no SSH, no prod DB write, no VisualSpec activation, no image build,
no worker restart, no public send. `automation_worker` (Story-Continuity shadow, container
`2efc4c8b319d`, image `:c6694b9`) left running, untouched. No image-generation model used.

**Base:** `5a113b0` on `feature/launch-readiness-visual-recap-parallel-1`
(worktree `C:/Users/Theodor/ai-newsroom-launch-visual-recap-1`).

**Verdict:** `FOUNDER_VISUAL_OVERLAY_RECOVERY_PARTIAL` — the refined pulse waveform *geometry* was
recovered from a FOUND_APPROVED asset and wired into BREAKING (+ the DATA hero pulse motif); the
DATA hero **background / technical grid / hero area-chart** and the **exact typeface** have **no
recoverable asset anywhere in the repo or its history** and are disclosed as forensic blockers.

---

## A. Founder rejection summary (verbatim intent)

BREAKING = REJECTED · DATA_SOURCE_INFOGRAPHIC = REJECTED · DATA_HERO_METRIC = REJECTED. Pulse/graph
lines look mechanically broken / angular / crude; DATA background looks generic/cheap; typography
looks like a default technical/programmatic font; BREAKING does not reproduce the refined pulse
overlay in the reference; DATA looks developer-built, not the editorial system; existing design
overlays/templates must be investigated before drawing anything new.

## B. Board re-analysis (`docs/founder_telegram_board.png`, 1024×1280)

* **BREAKING** (bottom-left card): source photo dominant; a thin **red ECG / "Линия пульса"**
  crosses the **lower** portion of the media — long calm baseline, one crisp narrow QRS spike
  (R up, S undershoot), small end-notches; a faint large `⋔⋔` "ninja" watermark glyph behind it;
  no dark band, no baked headline.
* **DATA** (top-right card): near-black ground; left column `500` (white) / `МЛН` (red) /
  `ПОЛЬЗОВАТЕЛЕЙ` (white caps) — a **weight-driven** hierarchy; `Достиг ChatGPT в июле 2025 года`;
  a red **outlined `+38%` pill**; `рост за 2 месяца`. Right side: a **smooth rising red area
  chart** with a red→transparent gradient fill and a **white end-dot**. A very subtle technical
  grid.
* Style legend confirms **Линия пульса** (the red ECG) and **Фирменный знак** (the `nnj` mark) as
  named brand primitives; the bottom bar shows a multi-beat ECG reference.

## C. Complete asset search methodology

* Filesystem sweep: `find assets design -type f` for `png/jpg/jpeg/webp/svg/pdf/ai` + all
  `json/yaml/yml/md/txt`; likely-location probe (`assets/ design/ static/ templates/ overlays/
  media/ references/ newsroom_visuals/ tests/fixtures/` — only `assets/` + `design/` +
  `tests/fixtures/` exist).
* Git history: `git log --all --diff-filter=A --name-only` for pulse/ecg/wave/heartbeat/overlay/
  breaking/data; `git log --all --name-status --diff-filter=D` for deletions;
  `git log --all -- <path>` on `brand_renderer.py` and the overlay pack; `git log --all` for every
  `.svg` and every `.ttf/.otf/.woff*` blob ever committed.
* Every strong candidate opened and inspected pixel-wise (not classified by filename).
* Full inventory table + ASSET_SOURCE resolution: `07_ASSET_INVENTORY.md` (in the review package).

## D. Asset inventory (summary — full table in `07_ASSET_INVENTORY.md`)

| Asset | Board match | Status |
|---|---|---|
| `overlays/universal/universal_minimal_01.png` (4:5 raster, white line+pulse) | carries the refined ECG waveform | **STRONG_MATCH (geometry)** — `production_runtime_asset: false` |
| `overlays/universal/universal_graphite_red_pulse_01.png` (clean red ECG blip) | ECG blip morphology | POSSIBLE_MATCH — `production_approved: false` (corroborates the shape) |
| `overlays/breaking/breaking_minimal_01.png` (BREAKING ribbon + bottom ECG line) | ribbon ✗, line ✓ | **WRONG_DIRECTION** — `production_approved: false` |
| `references/data/data_template_{white,red}.png` + manifest (v2.20b) | source-on-graphite + full-width bottom pulse + NNJ | **STRONG_MATCH** — approved layout spec, `reference_only` |
| `overlays/data/data_minimal_02.png` (tiny bottom-left line+dot motif) | decorative, **not** the hero area chart | POSSIBLE_MATCH (motif only) |
| `candidate_c_locked/candidate_c_overlay.png` (1280×720 corner signature) | corner sig only | POSSIBLE_MATCH — build script deleted from tree |
| `nnj_logo.svg` / `nnj_logo_red.svg` | the canonical mark | STRONG_MATCH — already in use |
| DATA hero background / grid / area-chart asset | — | **DOES NOT EXIST** (repo + history) |
| any `.ttf` / `.otf` / font asset | — | **DOES NOT EXIST** (repo + history) |

## E. Historical git asset findings

`695a1f1` added the 4:5 overlay pack; `a74f708` added the procedural `_draw_pulse_line`; `de5ba2e`
added `data_template_*`; `fd4e006`/`ff458ae`/`577607d`/`d016764` retired the BREAKING dark band.
`git log --all` proves **no vector pulse asset and no font file has ever existed**. The repo's own
`design/reference_manifest.md` states BREAKING is `REFERENCE_MISSING (production_approved)` and that
every overlay is design-DIRECTION only (`production_runtime_asset: false`), with an explicit
recorded product decision: *"Do NOT stretch the supplied 1122×1402 overlays into 16:9."*

## F. Fonts / typography findings

`FOUNDER_BOARD_FONT_REFERENCE = UNKNOWN`. No font file has ever been committed;
`settings.brand_font_path` is unset; the renderer opportunistically uses the OS's Arial /
DejaVu / Liberation Sans. `_font(bold=True)` was a documented **no-op**. Closest existing match,
no download: the OS-provided **bold** companion of the same family (`arialbd.ttf` on Windows;
`LiberationSans-Bold.ttf` / `DejaVuSans-Bold.ttf` on the Linux VPS), resolved by the new
`_resolve_bold_font_path()`; falls back to the regular face when absent. The board's condensed
grotesque still needs a Founder-supplied font asset — **disclosed gap**.

## G. BREAKING — recovered asset / source

`BREAKING_ASSET_SOURCE = universal_minimal_01.png` (FOUND_APPROVED), corroborated by
`universal_graphite_red_pulse_01.png`, the master prototype, and the Founder board. The waveform's
P-QRS-T morphology and proportions (baseline `y≈1285`, R apex `+38 px ≈ +2.7 %` canvas height,
S undershoot `≈ 0.28·R`, small rounded P and T, a long calm baseline) were **measured at native
resolution** and baked into `_PULSE_WAVEFORM_UNIT` (28 control points, `x∈[0,1]`, `y` in
"R apex = 1.0" units). The 4:5 raster is **not** composited (the recorded product decision forbids
the 4:5→16:9 migration); the geometry is rendered deterministically.

## H. DATA generated — recovered assets / source

`DATA_GENERATED_ASSET_SOURCE = UNKNOWN` — forensic blocker. No background / grid / hero-chart asset
exists. Only `docs/founder_telegram_board.png` (authority #1) as a visual target and
`design/proposed_telegram_data_quote_vnext_candidates.md` describing the *structure*. Recovered /
permitted improvements only: the smooth area curve (§11), the recovered pulse motif, real bold
type (§6/§12). The graphite ground + technical grid are **kept as-is** (only made more restrained:
grid step `64→96`, colour `(34,34,39)→(24,24,28)`) — **not reinvented**.

## I. DATA source treatment evidence

`DATA_SOURCE_TREATMENT_SOURCE = data_template_{white,red}.png` + `data_template_manifest.json`
(v2.20b): source image on a graphite ground + one full-width bottom pulse + one NNJ, no card, no
upper mark, `one_nnj_logo: true`. The renderer already honours the substance (full-width bottom
pulse+mark via `_DATA_SIGNATURE_FULL_WIDTH_FRAC`; `FINAL_VISIBLE_NNJ_COUNT ≤ 1`). Adopting the
template's **framed graphite-panel contain-fit** was implemented, tested, and then **reverted**:
the DATA source-signature safety scoring (`_select_data_signature`, four-tier degradation) is
calibrated against `_fit_photo_to_canvas`'s cover-fit; switching to contain-fit destabilised a
real fixture regression test and risks the §14 non-negotiable. Deferred as a disclosed PARTIAL
item — needs its own bounded pass. Source preservation is unchanged and proven (§O).

## J. Assets found but previously unused (`APPROVED_ASSETS_EXIST_BUT_UNUSED`)

**true** — the FOUND_APPROVED `universal_minimal_*` / `data_minimal_*` overlays and the
`data_template_*` references were classified into `design_reference_assets` but never wired to
runtime selection (`production_runtime_asset: false` by design). This phase is the first to pull
one of them (the `universal_minimal_01` waveform geometry) into an active renderer.

## K. Old procedural paths identified

* `_draw_pulse()` (`nnj_master_news_overlay.py`) — the rejected `baseline → top → bottom →
  baseline` 6-point polyline. **Still used** by the FROZEN NEWS + DATA-source lower signature
  (`_build_lower_signature_image`, `_build_data_lower_signature_image`); **removed from the
  BREAKING path.**
* `_draw_pulse_line()` (`brand_renderer.py`) — the small 6-point heartbeat accent. **Removed from
  the DATA hero card** (→ `_draw_recovered_pulse`); still referenced by `render_news_hero` (dead
  code) and RECAP.
* `_draw_hero_sparkline()` raw `draw.line(points, joint="curve")` on the un-interpolated anchor
  points — **replaced** with the monotone-cubic smooth area curve (same function name).

## L. Renderer changes

`services/brand_renderer.py`
* new `_PULSE_WAVEFORM_UNIT` (recovered morphology) + `_catmull_rom()` + `_draw_recovered_pulse()`
  (4× supersampled AA layer, LANCZOS-downscaled, alpha-composited).
* `render_breaking_frame()` — draws `_draw_recovered_pulse` across the lower media; no
  `_draw_pulse`. `renderer_version` semantics bumped.
* `_monotone_cubic()` (Fritsch-Carlson) + `_draw_hero_sparkline()` rewritten → smooth red area
  curve, red→transparent gradient fill, white end-dot, on a 4× AA layer; values used verbatim as
  anchors, never overshooting the series range.
* `render_data_hero_card()` — value / unit / label in the real **bold** face; the small pulse
  motif is `_draw_recovered_pulse`; grid made more restrained.
* `_fit_single_line()` / `_fit_wrapped_block()` — new `bold: bool` param.
* font: `_FONT_BOLD_CANDIDATE_PATHS` + `_resolve_bold_font_path()`; `_font(bold=True)` now real.

`services/render_evidence.py`
* `derive_breaking_render_evidence()` — `renderer_version = "pulse-breaking-v4-recovered"`;
  `notes["overlay_asset"]` names `universal_minimal_01.png` and states the geometry is recovered,
  not composited.

`core/config.py` — optional `brand_font_bold_path` pin (unset by default).

## M. Exact overlay composition logic

`_draw_recovered_pulse(base_rgba, *, cx, baseline_y, span, amplitude, color, stroke)`:
build a `(span+2·pad)×(head+foot)` RGBA layer at 4× scale → map `_PULSE_WAVEFORM_UNIT`
(`x·span`, `baseline − y·amplitude`) → `_catmull_rom(control, 16)` smooth polyline →
`ImageDraw.line(..., width=stroke·4, joint="curve")` → `resize(÷4, LANCZOS)` →
`base_rgba.alpha_composite(layer, (cx − span/2 − pad, top))`. Nothing but the one waveform is
added. BREAKING: `cx = w/2`, `baseline_y = 0.86·h`, `span = 0.62·w`, `amplitude = 0.045·h`,
`stroke = 0.006·h`. Hero motif: `span 200`, `amplitude 22`, `stroke 4`.

## N. Graph interpolation logic

`_monotone_cubic(xs, ys, samples_per_segment=28)` — Fritsch-Carlson monotone cubic Hermite. The
tangents are clamped so **each segment is monotone**, which guarantees the curve stays within
`[min, max]` of every adjacent pair — it can never imply a value outside the supplied series
(§11). The real series points remain the only factual anchors; no numeric label is derived from
the interpolated path; `< 3` points fall back to the straight segment; `< 2` points draw no
chart. Verified by `test_hero_trend_is_monotone_and_never_overshoots_the_series_range`.

## O. Factual-safety proof

* DATA hero — `test_hero_metric_is_verbatim_never_reformatted` (value/unit/label/evidence/delta
  unchanged); `test_hero_curve_anchors_are_the_supplied_series_verbatim` (data-driven, deterministic);
  monotone curve → no fabricated values (§N).
* DATA source — `test_data_source_infographic_is_preserved_with_one_mark`: MAD of the top 65 %
  (title, hero stat, most bars) between source and output `< 6.0`; branding confined to the lower
  band. `NUMBER_MISMATCH` / `INFOGRAPHIC_DESTROYED` gates unchanged.
* BREAKING — source composited at native size, `source_image_treatment = "preserve"`,
  `source_preserved = True`; `test_breaking_keeps_source_native_size_one_mark_no_band`.

## P. Canary matrix

| File | Source | Result |
|---|---|---|
| `01_BREAKING_DARK.png` | `case1_hero_product_iphone.jpg` (dark product) | recovered ECG across lower media, 1 mark, no band |
| `02_BREAKING_LIGHT.png` | `case3_bright_promotional_scene.jpg` (bright/busy) | same, reads cleanly on a light source |
| `03_DATA_GENERATED_A.png` | `500` / `МЛН` + rising 7-pt series | bold hierarchy, smooth area curve + end-dot, recovered pulse motif, 1 mark |
| `04_DATA_GENERATED_B.png` | `68` / `%` + different 5-pt series | proves it is a SYSTEM, not a one-off |
| `05_DATA_SOURCE_LIGHT.png` | `tests/fixtures/external_source_infographic.jpg` | source preserved intact, 1 mark |
| `06_DATA_SOURCE_DARK.png` | deterministic dark PIL infographic fixture (no NNJ) | source preserved intact, full-width bottom pulse+mark |

## Q. Reference-vs-recovered package

`C:/Users/Theodor/Desktop/NINJA_PULSE_OVERLAY_RECOVERY_REVIEW/`
`00_REFERENCE_VS_RECOVERED.png` (board BREAKING + DATA crops on top, all six recovered outputs
below at large size), `01`–`06` full renders, `07_ASSET_INVENTORY.md`.

## R. Tests

New `tests/test_founder_visual_overlay_recovery_4.py` (13, all passing):
BREAKING uses `_draw_recovered_pulse` not `_draw_pulse`; recovered waveform has an ECG P-QRS-T
morphology (one R apex, real S undershoot, long calm baseline, ≥ 24 points); the render is smooth
+ antialiased (many rows, blended edges); evidence names `universal_minimal_01.png` +
`pulse-breaking-v4-recovered`; source native size / one mark / no band; the only BREAKING asset
stays rejected and is never `.open()`-ed; hero trend is monotone and never overshoots the series;
curve anchors are the series verbatim (data-driven, deterministic); no crude polyline
(`_monotone_cubic` + LANCZOS); bold face wired for value/unit/label; metric verbatim; DATA source
preserved (MAD < 6 on the top 65 %); NEWS/QUOTE did not absorb the recovery.

Updated: `test_brand_renderer.py`, `test_founder_visual_polish_2.py`,
`test_founder_visual_board_alignment_1.py`, `test_render_evidence_parity.py`,
`test_design_spec_enforcement.py` (`_draw_pulse(`→`_draw_recovered_pulse(`; `pulse-breaking-v3`→
`pulse-breaking-v4-recovered`; hero body token `_draw_pulse_line`→`_draw_recovered_pulse`).

Broad regression: **362 passed, 6 skipped, NEW_FAILURES = 0**. Pre-existing on base `5a113b0`
(verified via `git stash`): `test_visual_spec_v2_activation.py::test_final_matrix_all_pass_no_placement_zone_partial`
(hero font 200 vs stale `telegram_data` v1 spec range [48,88]) and
`test_presentation_director_mode_contract.py::test_enforce_gate_actually_assigns_every_mutating_target_at_least_once`
(`assert not {'keyboard'}`). Collection errors `test_v2_4d_overlay_contract.py` /
`test_v2_4f_compact_overlay.py` also pre-existing (missing fixture / deleted script).

## S. Static checks

`ruff check services/ tests/… scripts/… core/config.py` → clean. `mypy services/brand_renderer.py
services/render_evidence.py services/nnj_master_news_overlay.py core/config.py` → clean.
**NEW_STATIC_ERRORS = 0.**

## T. Changed files

```
services/brand_renderer.py         recovered pulse primitive + monotone-cubic area chart + bold typography
services/render_evidence.py        breaking evidence: recovered-asset provenance, v4 version
core/config.py                     optional brand_font_bold_path pin
tests/test_founder_visual_overlay_recovery_4.py   NEW (13)
tests/test_brand_renderer.py                       _draw_recovered_pulse assertions
tests/test_founder_visual_polish_2.py              _draw_recovered_pulse / v4 version
tests/test_founder_visual_board_alignment_1.py     v4 version
tests/test_render_evidence_parity.py               v4 version
tests/test_design_spec_enforcement.py              v4 version
scripts/_founder_visual_overlay_recovery_4_canary.py   NEW
artifacts/founder_visual_overlay_recovery_4/           NEW (00–07)
docs/founder_visual_overlay_recovery_4_report.md       NEW (this file)
```

## U. Commit SHA

This report is committed together with the renderer changes on
`feature/launch-readiness-visual-recap-parallel-1` (parent `5a113b0`); see `git log` for the
exact SHA of the commit that carries this file.

## V. Remaining visual uncertainties

1. **DATA hero background / technical grid** — no asset exists; kept restrained-procedural, not
   recovered. Needs a Founder-supplied background/grid primitive (or explicit approval of the
   current one) to close.
2. **Typography** — `FONT_SOURCE = UNKNOWN`; bold companion of the OS sans is the closest existing
   match. A condensed grotesque needs a Founder-supplied, license-clear font asset.
3. **DATA hero chart character** — the board's curve reads as volatile/jagged (implies more data
   points than the real series carries); the recovered render is a smooth monotone curve through
   the actual points. Confirm the smooth reading is acceptable, or supply denser structured data.
4. **BREAKING `⋔⋔` watermark glyph** — visible on the board behind the pulse; not reproduced
   (it would be a new decorative element, out of scope for a recovery phase).
5. **DATA source framed graphite panel** (`data_template_*` contain-fit) — deferred; needs its
   own bounded pass to re-calibrate the source-signature safety scoring.
6. **VPS Cyrillic + bold face availability** — unverified from this environment (no VPS access
   this phase); the resolver degrades safely to the regular face.

---

`FOUNDER_VISUAL_OVERLAY_RECOVERY_PARTIAL`

Not production-ready. The Founder must visually inspect the recovered BREAKING and DATA outputs
first. Work stops here — no provenance, dependency, spec, or production-rollout work follows.
