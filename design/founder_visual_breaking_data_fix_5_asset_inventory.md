# FOUNDER-VISUAL-BREAKING-DATA-RECONSTRUCTION-5 — asset inventory

Re-run forensic sweep (filesystem + full `git log --all`, deleted/renamed blobs included).
`OVERLAY_RECOVERY_CONFIDENCE = HIGH` that the tracked image set below **is** the complete
historical set — `git log --all --pretty=format: --name-status --diff-filter=D` returns **zero
deleted image blobs ever**, and every `.svg` ever committed is one of the two `nnj_logo*` wordmarks.

| Asset | Path | Git origin | Format | Purpose | Board similarity | Use? | Reason |
|---|---|---|---|---|---|---|---|
| Founder board | `docs/founder_telegram_board.png` | supplied | 1024×1280 PNG | **VISUAL AUTHORITY #1** | — | **YES** | BREAKING pulse + DATA bg/grid/curve/typography all pixel-measured from it this phase |
| NNJ wordmark | `assets/brand/nnj_logo.svg` / `nnj_logo_red.svg` | `a74f708` | SVG 480² | canonical mark | STRONG | YES (unchanged) | already composited via `rasterize_nnj_mark` |
| NNJ badge PNG | `assets/brand/nnj_logo.png` | early | PNG 480² | pre-composited red badge | — | NEWS/RECAP only | not the wordmark |
| universal_minimal_01 | `…/v1/overlays/universal/universal_minimal_01.png` | `695a1f1` | 1122×1402 (4:5) raster, soft glow, embedded wordmark | UNIVERSAL design reference | MEDIUM (carries an ECG line, but softer + different placement than the board's BREAKING pulse) | **NO (geometry superseded)** | RECOVERY-4 traced this and the Founder still rejected it as "crude/mechanical"; the board itself is now the geometry source |
| universal_graphite_red_pulse_01 | `…/universal/universal_graphite_red_pulse_01.png` | `695a1f1` | 1122×1402 raster (clean red ECG blip) | UNIVERSAL | MEDIUM | NO | `production_approved: false`; corroborates ECG shape only |
| universal_minimal_02/03, universal_graphite_01, universal_graphite_red_endpoint_01 | `…/universal/*` | `695a1f1` | 1122×1402 raster | UNIVERSAL variants | WEAK | NO | line+brackets; `production_approved: false` on the graphite set |
| breaking_minimal_01 | `…/v1/overlays/breaking/breaking_minimal_01.png` | `695a1f1` | 1122×1402 raster: BREAKING ribbon badge + bottom ECG + wordmark | BREAKING | WRONG_DIRECTION | **NO** | FOUND_REJECTED (`design/reference_manifest.md`) — "heavier than the master prototype supports". Only the bottom line is on-message; the ribbon is not. |
| data_minimal_01/02/03 | `…/v1/overlays/data/data_minimal_0*.png` | `695a1f1` | 1122×1402 raster: tiny bottom-left line/bar+dot motif | DATA | WEAK | NO | a **decorative** motif at the bottom-left, not the board's right-side hero area chart (manifest: "decorative, not a real data renderer") |
| data_template_white / data_template_red | `…/v1/references/data/data_template_*.png` | `de5ba2e` | 1600×900 annotated layout mock | DATA source-preserving layout | MEDIUM | reference only | approved *layout spec* (`production_usage: reference_only`); its framed graphite panel is deferred (destabilises source-signature safety scoring) |
| master prototype | `…/v1/references/nnj_editorial_visual_system_master_prototype.png` | `695a1f1` | board mock (older) | all | superseded by `docs/founder_telegram_board.png` | design-history | — |
| candidate_c_overlay | `…/candidate_c_locked/candidate_c_overlay.png` | `2bfd69e`-era | 1280×720 raster corner signature | UNIVERSAL corner sig | WEAK (corner sig, not a full BREAKING pulse) | NO | build script `scripts/nnj_v2_4f_compact_right_overlay.py` deleted from the tree |
| vrr1 comparison / v2_10h proofs / recap mocks | `…/vrr1_reconciliation/*`, `…/v2_10h_*`, `…/references/recap_mockup_*` | various | comparison artifacts / NEWS proofs / RECAP mocks | — | — | design-history | out of scope |
| bakeoff source photos | `…/v2_1_bakeoff_sources/case*.jpg` | `695a1f1` | JPG | test source images | — | canary inputs | representative BREAKING/NEWS photos |
| **DATA hero background / technical-grid / area-chart asset** | — | — | — | — | — | **DOES NOT EXIST** | reconstructed deterministically from board pixel measurements (§12/§15/§18) |
| **any `.ttf` / `.otf` / font file** | — | — | — | — | — | **DOES NOT EXIST** (repo + full history) | `DATA_FONT` = closest existing OS face, see `08_ASSET_PROVENANCE.md` |

## BREAKING_OVERLAY_SOURCE

`docs/founder_telegram_board.png` — the board's own BREAKING pulse, **pixel-traced** (§9 option D):
red-channel column scan of the BREAKING photo crop → baseline at the photo's bottom edge, a
short LEFT-anchored complex (QRS apex at ~0.33 of the drawn span), **deep S undershoot
(S/R ≈ 0.70)**, small P and T bumps, flat tail; drawn span ≈ 0.46 of the photo width; thin,
clean stroke. Rendered deterministically (4× supersample → LANCZOS) — no raster composited (no
dedicated approved BREAKING overlay asset exists; the 4:3-ish overlay rasters cannot be
aspect-migrated per the recorded V1 product decision).

## DATA_GENERATED_BACKGROUND_SOURCE

`docs/founder_telegram_board.png` DATA card, pixel-measured: background mean RGB ≈ **(6, 7, 9)**
(near-black, faint cool tint); grid peak brightness ≈ +11 over background at ≈ 1/9 of the card
width. Reconstructed as `_HERO_BG=(6,7,9)` + a single-pixel `(17,18,22)` grid at 144 px on the
1280 canvas. No background/grid asset exists to composite.
