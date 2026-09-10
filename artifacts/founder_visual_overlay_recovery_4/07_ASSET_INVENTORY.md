# FOUNDER-VISUAL-OVERLAY-RECOVERY-4 — asset inventory

Full sweep of the current filesystem **and** all git history (`git log --all`, deleted/renamed
blobs included) for visual primitives / overlays / templates / fonts tied to BREAKING and DATA.

## A. Every visual asset found (repo + history)

| Asset | Type | Historical source | Intended format | Board match | Status |
|---|---|---|---|---|---|
| `assets/brand/nnj_logo.svg` / `nnj_logo_red.svg` | SVG wordmark (480×480) | `a74f708` NINJA PULSE visual system v1 | all — the canonical mark | mark only | **STRONG_MATCH** — already used at runtime via `rasterize_nnj_mark()` |
| `assets/brand/nnj_logo.png` | pre-composited red badge (480×480) | early | NEWS/RECAP badge | badge | IN USE (NEWS/RECAP), not the wordmark |
| `assets/brand/newsroom_visuals/v1/overlays/universal/universal_minimal_01.png` | raster overlay 1122×1402 (4:5), soft-glow, white line+pulse+wordmark | `695a1f1` | UNIVERSAL (design reference) | **carries the refined ECG waveform** | **STRONG_MATCH (geometry)** — `production_runtime_asset: false`; waveform morphology recovered here |
| `.../universal/universal_minimal_02.png` / `_03.png` | as above + 2 corner brackets (red / white) | `695a1f1` | UNIVERSAL | line+pulse ✓, brackets ✗ | POSSIBLE_MATCH (line only) |
| `.../universal/universal_graphite_red_pulse_01.png` | raster 1122×1402, **clean** graphite line + red ECG blip | `695a1f1` | UNIVERSAL | clean ECG blip morphology | **POSSIBLE_MATCH (geometry)** — `production_approved: false`; corroborates the waveform shape |
| `.../universal/universal_graphite_01.png` / `_red_endpoint_01.png` | raster 1122×1402 graphite variants | `695a1f1` | UNIVERSAL | partial | `production_approved: false` |
| `.../universal/overlay_experiment_badge_logo_unverified_branding.png` | raster, "unverified branding" | `695a1f1` | — | — | **WRONG_DIRECTION** (not in any manifest) |
| `.../overlays/breaking/breaking_minimal_01.png` | raster 1122×1402: **BREAKING ribbon badge** + circuit glyph + bottom ECG line + red wordmark | `695a1f1` | BREAKING | ribbon ✗, bottom ECG line ✓ | **WRONG_DIRECTION** — `production_approved: false`, "heavier than the master prototype supports". Only the *pulse line* portion is usable. |
| `.../overlays/data/data_minimal_01.png` | raster 1122×1402: dot+tick + 1 corner bracket + bottom pulse line, **no chart** | `695a1f1` | DATA | pulse line ✓ | POSSIBLE_MATCH (line only) |
| `.../overlays/data/data_minimal_02.png` | raster 1122×1402: small **ascending line+dot mini-chart** merged into the bottom pulse line (bottom-left) | `695a1f1` | DATA | a *decorative* chart motif, bottom-left | POSSIBLE_MATCH — **NOT** the board's right-side hero area chart (manifest: "decorative, not a real data renderer") |
| `.../overlays/data/data_minimal_03.png` | raster 1122×1402: smaller bar+dot motif bottom-left | `695a1f1` | DATA | decorative | POSSIBLE_MATCH (motif only) |
| `.../references/data/data_template_white.png` / `data_template_red.png` | **layout template** 1600×900 (16:9), annotated: source image on graphite ground + key-fact block + full-width bottom pulse + NNJ | `de5ba2e` (v2.20b) | DATA source-preserving | ground + full-width pulse + NNJ ✓ | **STRONG_MATCH** — approved *layout spec* (`production_usage: reference_only`) |
| `.../references/nnj_editorial_visual_system_master_prototype.png` | master prototype board (older) | `695a1f1` | all | superseded by `docs/founder_telegram_board.png` | design-history reference |
| `.../candidate_c_locked/candidate_c_overlay.png` | raster 1280×720 (16:9), **trusted branding**: compact bottom-right white pulse + red NNJ badge | `2bfd69e`-era | UNIVERSAL corner signature | corner signature only (not a full-width breaking pulse) | POSSIBLE_MATCH — geometry in `candidate_c_locked/manifest.json`; build script `scripts/nnj_v2_4f_compact_right_overlay.py` is **deleted from the tree** (`test_v2_4f_compact_overlay.py` fails to collect) |
| `.../vrr1_reconciliation/breaking_old_vs_new_vs_master.png` | comparison artifact | `fd4e006` | — | shows old-band vs corner-signature vs master | design-history |
| `.../v2_10h_master_news_production/*.png` | MASTER NEWS placement proofs | V2.10H | NEWS | — | NEWS proof, out of scope |
| `docs/founder_telegram_board.png` | **the Founder board** | supplied | all — VISUAL AUTHORITY #1 | — | authoritative |

## B. Historical git findings

* `695a1f1 feat(editorial-visuals): add source-faithful image edit infrastructure` — introduced the
  whole `v1/overlays/` + `v1/references/` pack (4:5, 1122×1402).
* `a74f708 feat(presentation): add NINJA PULSE visual system v1` — introduced the procedural
  `_draw_pulse_line()` primitive in `brand_renderer.py`.
* `de5ba2e V2.20C align DATA renderer with canonical NNJ templates` — added `data_template_*` +
  `data_template_manifest.json`.
* `fd4e006 docs(visual): NEWS/BREAKING v2 spec proposal + reconciliation comparison artifacts`.
* `ff458ae` / `577607d` / `d016764` — retired the BREAKING 22 % dark band, moved BREAKING into the
  NEWS family (later re-diverged in FOUNDER-VISUAL-POLISH-2).
* **`git log --all` for every `.svg` ever committed → only `nnj_logo.svg` + `nnj_logo_red.svg`.**
  No vector pulse / ECG / waveform / chart asset has *ever* existed in this repository.
* **`git log --all` for every `.ttf` / `.otf` / `.woff*` ever committed → none.** No font file has
  ever been in the repo; `settings.brand_font_path` is unset by default.

## C. The definitive forensic document already in the repo

`design/reference_manifest.md` (generated from the project's own manifests) states outright:

* **BREAKING** → "REFERENCE_MISSING (production_approved) — only a rejected candidate exists;
  production BREAKING is recreated deterministically from the master prototype's own minimal
  device, no dedicated approved asset."
* **DATA** → "Covered (`data_template_white/red.png`, `data_minimal_01/02/03.png`)."
* every overlay entry: "none of these are literal runtime compositing assets; …recreate the
  approved visual language deterministically in code" + `production_runtime_asset: false`.
* `assets/brand/newsroom_visuals/v1/manifests/overlays.yaml` preamble: *"Do NOT stretch the
  supplied 1122×1402 overlays into 16:9"* — an explicit, recorded V1 product decision.

## D. ASSET_SOURCE resolution (§18)

| Item | Resolution |
|---|---|
| `BREAKING_ASSET_SOURCE` | **KNOWN (geometry)** — the refined ECG waveform of `universal_minimal_01.png` (FOUND_APPROVED) / `universal_graphite_red_pulse_01.png`, morphology measured at native resolution and rendered deterministically (`_draw_recovered_pulse`). The raster itself is not composited (4:5→16:9 migration is forbidden by the recorded product decision). |
| `DATA_SOURCE_TREATMENT_SOURCE` | **KNOWN** — `data_template_{red,white}.png` + `data_template_manifest.json` (v2.20b). Adopting the framed graphite-panel *layout* is deferred (see report §I) because it destabilises the source-signature safety scoring calibrated for cover-fit; the graphite ground + one-mark ≤ 1 rules are already honoured. |
| `DATA_GENERATED_ASSET_SOURCE` | **UNKNOWN — forensic blocker.** No background / technical-grid / hero area-chart asset exists in the repo or its history. Only `docs/founder_telegram_board.png` as a visual target. The graph *curve* is smoothed via monotone-cubic interpolation of the real series (explicitly permitted by §11); the background + grid are **not** reinvented. |
| `FONT_SOURCE` | **UNKNOWN — forensic blocker.** No font file has ever been committed. Closest existing = the OS-provided **bold** companion of the current regular face (Arial Bold on Windows; Liberation Sans Bold / DejaVu Sans Bold on the Linux VPS), same "opportunistically use the OS font" rule already in the code. `_font(bold=True)` was previously a silent no-op and is now wired. A real condensed grotesque still needs a Founder-supplied font asset. |
