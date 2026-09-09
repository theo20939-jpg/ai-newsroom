# FOUNDER-VISUAL-POLISH-2 — report

**Phase type:** bounded visual correction (renderer + evidence only).
**Visual authority #1:** `docs/founder_telegram_board.png`.
**Production:** NOT TOUCHED. No SSH mutation, no prod DB write, no VisualSpec activation, no
image build, no worker restart, no deployment. `automation_worker` (Story Continuity shadow,
container `2efc4c8b319d`, image `ai-newsroom-automation_worker:c6694b9`) left running, untouched.

**Base:** `f14782f` on `feature/launch-readiness-visual-recap-parallel-1`
(worktree `C:/Users/Theodor/ai-newsroom-launch-visual-recap-1`).

---

## Founder verdicts → what changed

### 1. NEWS = FAIL → restrained brand mark, no decorative red line

The long red pulse/signature in the upper-right corner is gone. `apply_master_news_branding()`
now defaults to `signature_style="mark_only"` (`SIGNATURE_STYLE_MARK_ONLY` in
`services/nnj_master_news_overlay.py`): exactly **one** small canonical NNJ mark
(`_UPPER_MARK_W_FRAC` of canvas width, `rasterize_nnj_mark(red=True)`) placed in the quietest of
the four safe corners via the existing `_evaluate_placements()` subject-aware scorer. No fused
line, no ECG pulse, no BREAKING-style treatment. Headline / category / time stay Telegram-native
(never baked). The fused line+pulse+mark unit is still reachable for explicit callers
(`signature_style="fused"`, used by DATA/RECAP and by the three `test_v2_10h_*` cases that
assert on it).

Canary: `01_NEWS.png` — visually complex trade-show photo, source dominant, one mark in the
dark out-of-focus foreground (does not cover the phone screen / faces).

### 2. BREAKING = FAIL → its own lower-media pulse motif

`render_breaking_frame()` in `services/brand_renderer.py` was rewritten off the MASTER NEWS
path. It now composites the source at native size and draws its own **NINJA PULSE** ECG
waveform (`_draw_pulse()`) across the **lower** portion of the media
(`_BREAKING_PULSE_Y_FRAC = 0.86`, `_BREAKING_PULSE_WIDTH_FRAC = 0.62`, centred), plus one
restrained corner mark in the quieter bottom corner (`_breaking_quieter_bottom_corner()`,
ImageStat stddev, lower-right wins ties). No historical dark lower-third band, no scrim, no
baked BREAKING headline, no banner. Distinction from NEWS is now structural: NEWS = corner mark
only; BREAKING = red pulse crossing the lower media + corner mark.

`RenderEvidence`: `renderer_version = "pulse-breaking-v3"`, `placement_zone = "lower_center"`,
`logo_count = 1`, `logo_zone in {"lower_right","lower_left"}`, scrim `none`, source `preserve`.

Canary: `02_BREAKING.png` — product render, pulse across the lower phones, one mark lower-right.

### 3. DATA source infographic = FAIL (two NNJ marks) → FINAL_VISIBLE_NNJ_COUNT ≤ 1

New invariant enforced in `render_data_card()` / `render_branded_media()`:

* **Known internal NNJ-branded template** — deterministic `sha256` content match against
  `source_carries_canonical_nnj()` (`data_template_white.png`, `data_template_red.png`). On a
  match the source is returned composited-only with **no renderer NNJ added**. No third-party
  publisher logo is ever touched — the rule is about the canonical NNJ mark only.
* **Arbitrary external image** — canonical-NNJ detection is not attempted (not reliable). The
  caller can pass `source_already_branded=True` / suppress explicitly; otherwise exactly **one**
  renderer NNJ is applied and `RenderEvidence.logo_count` reports the renderer-added count
  truthfully (it does not claim to equal the final visible count for unknown inputs).

Canaries:
* `03_DATA_SOURCE_INFOGRAPHIC.png` — **new realistic non-NNJ fixture**
  (`tests/fixtures/external_source_infographic.jpg`, "GLOBAL EV ADOPTION 2025", 5-bar chart
  18/29/41/55/68 %, source-attribution line). Source fully preserved, no second hero metric, no
  data destruction, source numbers unchanged, exactly one renderer NNJ chip.
* `07_INTERNAL_BRANDED_SOURCE.png` — regression canary for `data_template_white.png` (already
  carries a baked NNJ). Renderer adds **no** second mark → one visible NNJ.

### 4. DATA hero metric = PASS_WITH_POLISH → hierarchy / balance only

`render_data_hero_card()` was polished, not redesigned. Two-pass layout: every block
(value / unit / label / evidence / delta-pill / pulse motif) is measured into `total_h`, then
drawn vertically centred in a balanced left column (`0.46 · W − margin`); the real trend line
fills the right column (`0.50 · W … W − margin`); the small red pulse motif sits directly under
the metric block. Retained verbatim: `500` white / `МЛН` red / label / secondary text / `+38%`
pill / factual line drawn **only** from `data_candidate.series` (≥ 2 real points, no synthetic
axes/labels) / technical grid / one NNJ lower-right.

Canary: `04_DATA_HERO_METRIC.png`.

### 5. QUOTE = FAIL (geometric placeholder portrait) → real portrait, dark composition

* **Fixture:** `tests/fixtures/portrait_public_figure.jpg` — an existing in-repo photographic
  asset (Tim Cook, from `assets/brand/newsroom_visuals/v2_recomposition_local_proof/`), light
  background. No image-generation model was used.
* `render_quote_card()` rewritten with `_composite_dark_portrait()`: cover-crop to the right
  region, graphite blend (`Image.blend(…, 0.34)`), brightness `0.78`, a left→right graphite
  gradient over the inner 72 %, a right-edge fade, and a bottom vignette — so a light-background
  portrait integrates into a deep-graphite (`_QUOTE_BG = (14,14,16)`) composition with no crude
  hard 50/50 split. Big red `“` glyph, quote dominant on the left in white, author name red,
  role smaller grey (`_QUOTE_ROLE_COLOR`) only when supplied. One restrained NNJ lower-right, no
  baked Telegram chrome.

Canary: `05_QUOTE.png` (real portrait + role).

### 6. QUOTE without role = FAIL (light right half) → same dark language

When `role` is absent the role line is simply omitted — **identical** background, portrait
treatment, typography and composition. No light-panel fallback, no fabricated role.

Canary: `06_QUOTE_NO_ROLE.png` — same composition as `05`, role line gone.

---

## §11 tests

New: `tests/test_founder_visual_polish_2.py` (17 tests, all passing). `_mad()` pixel helper
uses `PIL.ImageChops` / `ImageStat` (no numpy in the env).

| Requirement | Test |
| --- | --- |
| NEWS visual primitive (mark-only, no fused line/pulse) | `test_news_is_mark_only_no_fused_line_or_pulse` |
| NEWS evidence placement_zone N/A | `test_news_evidence_placement_zone_not_applicable` |
| fused style still available for explicit callers | `test_fused_style_still_available_for_explicit_callers` |
| BREAKING distinct treatment / lower-media pulse | `test_breaking_is_distinct_from_news_lower_media_pulse` |
| BREAKING evidence v3 / lower_center | `test_breaking_evidence_is_v3_lower_center` |
| no retired dark band | `test_breaking_no_retired_dark_band` |
| internal pre-branded source detected | `test_internal_branded_source_is_detected` |
| internal pre-branded source → no renderer NNJ | `test_internal_branded_source_gets_no_renderer_nnj` |
| explicit `source_already_branded` suppression | `test_explicit_source_already_branded_flag_suppresses_mark` |
| external source → exactly one renderer NNJ, data preserved | `test_external_source_infographic_gets_exactly_one_renderer_mark_and_preserves_data` |
| DATA number preservation / no synthetic data | `test_hero_card_retains_every_element_and_no_synthetic_data` |
| DATA hero metric verbatim | `test_hero_card_metric_is_verbatim` |
| QUOTE real composition (deep graphite, integrated portrait) | `test_quote_card_is_deep_graphite_and_integrates_the_portrait` |
| QUOTE missing-role dark fallback | `test_quote_missing_role_uses_the_same_dark_language_no_light_panel` |
| QUOTE no fabricated role | `test_quote_never_fabricates_a_role` |
| QUOTE body verbatim + font-fitted | `test_quote_body_is_verbatim_and_font_fitted` |
| RenderEvidence truthfulness | `test_render_evidence_reports_actual_zones_truthfully` |

Updated to match the corrected renderers: `test_design_spec_enforcement.py` (5),
`test_render_evidence_parity.py`, `test_brand_renderer.py`,
`test_founder_visual_board_alignment_1.py`, `test_v2_10h_master_news_production.py`.

### Regression

Focused visual + spec + evidence + presentation surface: **396 passed, 6 skipped, 0 new
failures** (two runs: 249p/1s and 130p/5s + the polish-2 17p; overlapping files counted once).

Pre-existing on base `f14782f` (NOT introduced here, verified by `git stash`):
* `tests/test_v2_4d_overlay_contract.py` — collection error (missing fixture file)
* `tests/test_v2_4f_compact_overlay.py` — collection error (`scripts.nnj_v2_4f_compact_right_overlay` missing)
* `tests/test_presentation_director_mode_contract.py::test_enforce_gate_actually_assigns_every_mutating_target_at_least_once` — `assert not {'keyboard'}`
* `tests/test_recap_story_integrity.py` (5) — pre-existing

**NEW_FAILURES = 0. NEW_STATIC_ERRORS = 0** (`mypy services/brand_renderer.py
services/render_evidence.py services/nnj_master_news_overlay.py` → clean; `ruff check` on the
full changed-file set → clean; `ruff format` applied to the two new files).

---

## §10 review package

`C:/Users/Theodor/Desktop/NINJA_PULSE_VISUAL_REVIEW_V2/`

| File | Content |
| --- | --- |
| `00_CONTACT_SHEET_V2.png` | Founder board (both panels) on top + all 7 renders labelled, large |
| `01_NEWS.png` | NEWS — restrained corner mark, no red line, source dominant |
| `02_BREAKING.png` | BREAKING — red pulse across lower media + one mark |
| `03_DATA_SOURCE_INFOGRAPHIC.png` | external non-NNJ infographic preserved, one renderer NNJ |
| `04_DATA_HERO_METRIC.png` | generated hero metric, polished hierarchy / balance |
| `05_QUOTE.png` | real portrait + role, deep-graphite composition |
| `06_QUOTE_NO_ROLE.png` | same dark composition, role line omitted |
| `07_INTERNAL_BRANDED_SOURCE.png` | internal NNJ template → no second NNJ added |

---

## §12 production safety attestation

No SSH to `31.77.219.165`. No production DB write. No VisualSpec activation
(`telegram_news`/`telegram_breaking`/`telegram_data`/`telegram_quote` remain as they were).
No Docker image build. No worker restart or recreate. No deployment. No public publication.
All work confined to the isolated dev worktree.

## §13 verdict

**FOUNDER_VISUAL_POLISH_2_READY_FOR_REVIEW**

This is a visual-review package only. Production readiness is **not** claimed. The Founder must
visually review V2 before any rollout. Work stops here — no provenance, dependency, spec, or
production-rollout work follows.
