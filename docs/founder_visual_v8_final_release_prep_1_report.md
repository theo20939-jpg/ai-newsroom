# FOUNDER-VISUAL-V8-FINAL-RELEASE-PREP-1 - report

Preparation only. **No production mutation.** No deploy. Story Continuity
constrained-enforcement canary untouched. Visual design is FROZEN.

## A. Founder visual approval

The Founder has visually reviewed V8 and APPROVES it. No V9 design phase.

| format | verdict |
|---|---|
| NEWS | APPROVED |
| BREAKING V8 | APPROVED |
| DATA GENERATED V8 | APPROVED |
| DATA SOURCE-PRESERVING | APPROVED |
| QUOTE | APPROVED |
| QUOTE_NO_ROLE | APPROVED |

Founder decisions carried into this release unchanged: generated DATA keeps **one**
restrained canonical NNJ mark (not removed, not made more prominent); optional delta
context (e.g. `рост за 2 месяца`) is supported only when supplied as structured
factual input and is never fabricated.

## B. Base SHA

`d2dea2cd7d5da714988217b1286afb8b96c26bb9` - the proven live `content_worker`
baseline (CONTENT-WORKER-PROVENANCE-RECONCILIATION-1: `PROVENANCE_MODE = EXACT_GIT_COMMIT`,
live source == this commit byte-for-byte).

## C. Approved V8 development HEAD

`8e690c5` on `feature/launch-readiness-visual-recap-parallel-1`
(FOUNDER-VISUAL-CANVAS-COMPOSITION-CORRECTION-8).

## D. Exact runtime delta (`APPROVED_V8_RUNTIME_FILES`)

The V8 dev lineage `d2dea2c..8e690c5` touches 150 files; most are Story Continuity
P0/P0.1, reports, tests, canary scripts and design notes. The V8 visual RUNTIME
dependency graph, traced from `worker.content_main` -> the four renderers, is
**13 files**. Each release blob OID is byte-identical to `8e690c5`.

| file | class | what |
|---|---|---|
| `services/brand_renderer.py` | VISUAL_RUNTIME_REQUIRED | BREAKING full-width lower-media pulse (span 0.795) + right-portion grey watermark (0.47 w, opacity 0.10); DATA hero on its own near-square **1280x1172** canvas (measured board media aspect 1.0915, `DATA_16_9_REQUIRED=false`); bundled Fira Sans Condensed typography (Black value/unit, SemiBold label, Medium secondary); `_segmented_anchor_path` graph (real anchors, no spline); graph-zone-only grid; one restrained NNJ mark; NEWS `mark_only`; QUOTE `_composite_dark_portrait` |
| `services/render_evidence.py` | VISUAL_RUNTIME_REQUIRED | truthful DATA hero evidence (`pulse-data-hero-v4-square`, canvas 1280x1172, `primary_font_size`, `graph_factual_series_count`, `graph_mode`, `grid_mode`, `canvas_aspect`+`DATA_16_9_REQUIRED=false`) and BREAKING evidence (`pulse-breaking-v7-board`, line total span, waveform position, watermark zone/opacity, `logo_count`) |
| `services/nnj_board_metrics.py` | VISUAL_RUNTIME_REQUIRED | **NEW** - frozen dataclasses of pixel measurements of `docs/founder_telegram_board.png` (BREAKING + DATA media rects, every fraction) |
| `services/nnj_master_news_overlay.py` | VISUAL_RUNTIME_REQUIRED | `SIGNATURE_STYLE_MARK_ONLY` (approved restrained NEWS watermark; default) + `_build_corner_mark_image`; `SIGNATURE_STYLE_FUSED` kept for explicit callers |
| `services/presentation_director.py` | VISUAL_RUNTIME_REQUIRED | `DataCandidate.series` / `.delta`, `QuoteCandidate.role` - optional structured inputs; the renderer never fabricates them (12-line dataclass-field addition only) |
| `core/config.py` | FONT_RUNTIME_REQUIRED | optional `brand_font_bold_path` / `brand_font_heavy_path` pins (`str | None = None`, unset by default; the DATA path is fully bundled-font self-contained and never reads them) |
| `assets/brand/fonts/FiraSansCondensed-{Regular,Medium,SemiBold,Bold,Black}.ttf` | FONT_RUNTIME_REQUIRED | 5 weights, SIL OFL 1.1 |
| `assets/brand/fonts/OFL.txt` | FONT_RUNTIME_REQUIRED | license metadata (required in repo) |
| `assets/brand/fonts/README.md` | FONT_RUNTIME_REQUIRED | font provenance / usage note |

**Excluded** (verified absent from `d2dea2c..d0a0377`): `services/story_continuity.py`,
`services/story_identity_guard.py`, `services/story_delta_engine.py`,
`services/story_memory.py`, `services/triage_orchestrator.py`,
`database/models/story_link.py`, the Story-Continuity additions to
`services/text_normalization.py`, `design/proposed_*.md`, all `tests/`, `docs/`,
`artifacts/`, `scripts/`.

Transitive deps of the 13 files that are already in `d2dea2c` and **unchanged** by
V8: `services/data_source_classification.py`, `services/nnj_master_news_mark.py`,
`services/editorial_treatment.py`, `services/channel_relevance.py`,
`database/models/news_event.py`, `schemas/topic_taxonomy.py`.

## E. Bundled font dependency

`V8_FONT_RUNTIME_SELF_CONTAINED = true` for the DATA path.

`_data_font()` -> `data_font_path(weight)` resolves **repo-relative**
(`assets/brand/fonts/FiraSansCondensed-<weight>.ttf`) and is tried FIRST; the OS
`_font(bold=/heavy=)` fallback fires only on `OSError` (font file missing).
Verified inside the built Linux image: all 5 weights resolve, `_data_font(120,"black")`
reports `('Fira Sans Condensed', 'Black')`, the DATA hero renders at 1280x1172 with
real Cyrillic - **no Windows Arial, no Linux DejaVu on the V8 DATA path**.

NEWS / QUOTE body type still uses the OS face via `_resolve_font_path()` ->
`/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` (shipped by the `fonts-dejavu-core`
apt package already in the Dockerfile). That is the **frozen, Founder-approved**
NEWS/QUOTE treatment - unchanged by this release. BREAKING bakes no typography.

The `.ttf` files are runtime assets only; they are NOT exposed as Founder-facing
artifacts.

## F. Dependency pinning strategy

The provenance phase found `python:3.12-slim` (floating), `>=` constraints in
`pyproject.toml`, no lock. This rollout does **not** accept arbitrary drift.

* Re-captured the RUNNING `content_worker` `pip freeze` on 2026-09-10 and diffed it
  against the provenance manifest
  (`/opt/ai-newsroom-ops/content-worker-provenance-reconciliation-1/manifests/pip_freeze_content_worker.txt`):
  **identical** (`FREEZE_IDENTICAL_TO_PROVENANCE = true`), 56 packages, all exact pins.
* Built `artifacts/founder_visual_v8_final_release_prep_1/constraints-content-worker-live.txt`
  from that freeze (the app package `ai-newsroom @ file:///app` omitted).
* Rollout build uses `pip install --no-cache-dir -c constraints-content-worker-live.txt .`
  so every application dependency version is pinned equal to the running
  `content_worker`; the ONLY intentional delta is the V8 visual source.
* `pyproject.toml` is **not** rewritten - the constraints file is a build-time input,
  not a project-policy change.
* **Base image**: the running image reports `PYTHON_VERSION=3.12.14` +
  `PYTHON_SHA256` and a Debian **trixie** snapshot (`debian.sh ... 'trixie' '@1787529600'`,
  built 2026-08-24). The rollout Dockerfile pins `FROM python:3.12.14-slim-trixie`
  (used successfully in the section-M verification build). A registry `sha256:` digest
  for that tag could not be recovered from this environment (no separate
  `python:3.12-slim` image or RepoDigest on the VPS) ->
  **`BASE_IMAGE_REPRODUCIBILITY_LIMITATION`**: the Python interpreter build (3.12.14)
  and Debian suite (trixie) are pinned; the exact OS-package snapshot digest is not.
  No newer Python packages are installed regardless (constraints file governs).

## G. Clean release construction

Fresh worktree `C:/Users/Theodor/ai-newsroom-v8-release`, branch
`release/founder-visual-v8-content-worker-1` created from `d2dea2c`. The 13
`APPROVED_V8_RUNTIME_FILES` applied via `git checkout 8e690c5 -- <file>` (exact
reviewed blobs, nothing retyped). One release commit `d0a0377`. Line endings verified
to match `8e690c5` (all LF). No `tests/`, no `docs/`, no scripts in the release
commit - the same minimal shape as the superseded `a3fd0dc`.

## H. Release diff (HARD DIFF GATE)

`git diff --name-only d2dea2c..d0a0377` = the **13 files** in section D, nothing else.

* `UNRELATED_RUNTIME_FILES = 0`
* No `story*/continuity/identity/delta/triage/text_normalization/memory` file.
* No Story-Continuity P0.1 file enters this `content_worker` release.
* Every staged blob OID == the corresponding `8e690c5` blob OID (verified per-file).

## I. Dependency closure

`V8_RELEASE_DEPENDENCY_CLOSURE = PASS`.

In the release worktree: `core.config`, `services.nnj_board_metrics`,
`services.nnj_master_news_mark`, `services.nnj_master_news_overlay`,
`services.data_source_classification`, `services.presentation_director`,
`services.brand_renderer`, `services.render_evidence` all import cleanly. All 5
bundled font weights resolve and exist. `brand_renderer` imports no Story-Continuity
module and no new `text_normalization` function. Repeated inside the built Linux
image (section M): `IMPORT_SMOKE = PASS`.

## J. Baseline tests (`BASELINE_*`)

Clean `d2dea2c` (runtime + tests), the 16-file existing visual/render/spec/director
surface, `pytest -p no:randomly`:

    BASELINE_PASSED  = 268
    BASELINE_FAILED  = 1     tests/test_presentation_director_mode_contract.py::test_enforce_gate_actually_assigns_every_mutating_target_at_least_once
    BASELINE_SKIPPED = 1

The one baseline failure is a pre-existing stale contract test (`assert not {'keyboard'}`),
unrelated to visual rendering.

## K. Release tests

V8 runtime + the V8 visual test surface (the 5 `test_founder_visual_*` suites + the
V8 revisions of `test_brand_renderer` / `test_design_spec_enforcement` /
`test_kirin_data_regression` / `test_render_evidence_parity` /
`test_v2_10h_master_news_production` + the unchanged director/spec/mark tests), 21
files:

    RELEASE_PASSED  = 349
    RELEASE_FAILED  = 4
    RELEASE_SKIPPED = 1

Explicit V8 render checks (release worktree AND inside the Linux image) all pass:
NEWS (mark placed / adaptively suppressed, one mark); BREAKING dark + bright
(`pulse-breaking-v7-board`, `logo_count=1`, deterministic); DATA generated
`500/МЛН`, `68/%`, `1,4 млрд` (real Cyrillic, **dedicated 1280x1172 canvas**,
bundled font, 9 real graph anchors, graph-zone grid, restrained fill, one NNJ,
deterministic); DATA source light/dark (source preserved, 1280x720, no
pulse/frame); QUOTE + QUOTE-no-role; RenderEvidence truthful; single-NNJ invariant.

The 4 failures, each **failing identically on the Founder-approved `8e690c5`**:

| test | why | status |
|---|---|---|
| `test_visual_single_brand_mark_contract.py::test_news_light_photo_has_exactly_one_mark` | encodes the pre-V8 "`apply_master_news_branding` always places exactly 1 mark" contract; the approved V8 `MARK_ONLY` NEWS treatment allows `logo_count ∈ {0,1}` (brand suppression on a low-contrast light photo, the same principle approved for DATA source). Covered for V8 by `test_founder_visual_polish_2.py::test_news_evidence_placement_zone_not_applicable` (`logo_count in (0,1)`). | **stale, superseded by approved V8** |
| `test_visual_single_brand_mark_contract.py::test_breaking_places_exactly_one_brand_mark` | monkeypatches `brand_renderer.select_master_news_branding` to assert BREAKING routes through the NEWS fused signature. Approved V8 BREAKING (`render_breaking_frame` rewritten in FOUNDER-VISUAL-POLISH-2) has its OWN lower-media pulse and does not import that symbol. Covered by `test_founder_visual_polish_2.py::test_breaking_is_distinct_from_news_lower_media_pulse`. | **stale, superseded by approved V8** |
| `test_visual_spec_v2_activation.py::test_final_matrix_all_pass_no_placement_zone_partial` | evaluates the V8 hero card against the **stale production `telegram_data` v1** font range; V8's board-proportional hero font is 270. Resolved by `FINAL_V8_SPEC_SET` (section O) - a truthful `telegram_data` candidate with `font_size_max 300`. | **stale spec, resolved by section O** |
| `test_presentation_director_mode_contract.py::test_enforce_gate_actually_assigns_every_mutating_target_at_least_once` | the section-J baseline failure - pre-existing on clean `d2dea2c`, unrelated to visual. | **pre-existing** |

**`NEW_FAILURES` (release `d0a0377` vs the Founder-approved `8e690c5`) = 0.** Every
test behaves identically between the release worktree and the approved dev HEAD.
Recommended for the rollout phase (not this one): a test-accuracy commit updating
`test_visual_single_brand_mark_contract.py` to the approved V8 contract so the
rollout's own gate is green without annotation.

## L. Static checks

`ruff check` + `mypy` on all 6 changed `.py` runtime files in the release worktree:
clean. **`NEW_STATIC_ERRORS = 0`.**

## M. Non-production image proof

Built `ai-newsroom-content_worker:v8-verify-d0a0377` locally (Docker Desktop, linux
containers) from the release worktree with a transient verification Dockerfile:
`FROM python:3.12.14-slim-trixie`, `fonts-dejavu-core ffmpeg`, `COPY . .`,
`pip install --no-cache-dir -c constraints-content-worker-live.txt .`. Not run as a
service; production container untouched.

Verified inside the image:

* `IMAGE_SOURCE_MATCH = true` - all 6 V8 `.py` runtime files at `/app/...` sha256-match the `d0a0377` git blobs.
* `FONT_ASSETS_PRESENT = true` - all 5 `FiraSansCondensed-*.ttf` + `OFL.txt` + `README.md` at `/app/assets/brand/fonts/`.
* `IMPORT_SMOKE = PASS` - every V8 module imports; fonts resolve repo-relative **in the Linux container** (`Fira Sans Condensed / Black`); DATA hero renders 1280x1172 with Cyrillic.
* Dependency set installed exactly per the constraints file (pillow 12.3.0, pydantic 2.13.5, SQLAlchemy 2.0.52, aiogram 3.31.0, ... == live freeze).

## N. Clean-release visual parity

`CLEAN_RELEASE_VISUAL_PARITY = PASS`.

Same-platform (Windows dev): every V8 canary - `data_500`, `data_68`, `data_14`,
`brk_dark`, `brk_bright`, `quote_role`, `news_bright` - renders **byte-identical
(sha256)** between the release worktree (`d2dea2c` + 13 files) and the approved dev
HEAD `8e690c5`. The runtime is functionally exact.

Cross-platform (Windows dev vs the Linux image, both Pillow 12.3.0 / FreeType 2.14.3):

* BREAKING dark, BREAKING bright, NEWS bright - **byte-identical** Windows <-> Linux.
* DATA hero cards - **visually equivalent** (same 1280x1172 layout, same bundled font,
  same glyphs and geometry; decoded-RGB mean abs difference ~1.0/255, 97.5% of pixels
  identical) but **not byte-identical**: the images differ only at anti-aliased glyph
  edges because the JPEG encoder differs (`libjpeg-turbo` 6.2 in the Linux base vs 8.0
  in the Windows Pillow wheel). The Linux render is **deterministic** (identical output
  on repeat) and Linux is the production target. Founder approval is of the design,
  which is identical on both platforms.

`CROSS_PLATFORM_NOTE`: production renders on Linux; the Founder-review images were
produced on Windows; expect glyph-edge JPEG-encoder-level byte differences, no layout
or typography difference.

## O. Final VisualSpec set

`FINAL_V8_SPEC_SET` - LOCAL candidate parameters only. **No production DB write, no
`create_candidate_spec()`, no `promote_candidate()` in this phase.** Prior candidate
work (news v3 / breaking v3 / data v3 / quote v2) predates
FOUNDER-VISUAL-FINAL-BOARD-MATCH-7 and -CANVAS-COMPOSITION-CORRECTION-8; two scopes
no longer describe V8 truthfully.

| scope | version intent | parameters | vs prior candidate |
|---|---|---|---|
| `telegram_news` | **next CANDIDATE** (v4) | `{safe_margin_frac: 0.019, scrim_treatment: "none"}` | **drop `source_image_treatment`** - V8 NEWS fits the source to 1280x720, so a non-16:9 photo truthfully evidences `crop`; declaring `preserve` is a falsification for that case. `crop` (soft, mechanical centre-crop) vs `recompose` (hard) is still governed by the separate SOURCE_PRESERVATION dimension; the single-NNJ invariant is always on. |
| `telegram_breaking` | **reuse** v3 CANDIDATE | `{safe_margin_frac: 0.019, scrim_treatment: "none", source_image_treatment: "preserve"}` | none - V8 BREAKING draws the pulse + watermark on the **native** photo (no canvas fit), so `preserve` is always truthful. |
| `telegram_data` | **next CANDIDATE** (v3's 200 is superseded) | `{font_size_max: 300, font_size_min: 100, max_line_count: 2, safe_margin_frac: 0.019}` | `font_size_max` 200 -> **300**, `font_size_min` 88 -> **100**. CANVAS-COMPOSITION-CORRECTION-8: the DATA hero is the near-square 1280x1172 board-media aspect (not 16:9), so the board-proportional primary value font (`0.163 h` cap) fits at ~270. No `placement_zone`/`logo_zone`/`scrim_treatment` - source-dependent (generated hero vs source-preserving MINIMAL) so declaring hero-only values would lie about the infographic render. No canvas/aspect/renderer_version field exists in `DeclarativeVisualParameters` -> **no false 16:9 requirement is possible**. |
| `telegram_quote` | **reuse** v2 CANDIDATE | `{safe_margin_frac: 0.019, logo_zone: "lower_right", scrim_treatment: "none", source_image_treatment: "preserve"}` | none - V8 QUOTE (dark composition, optional role, deterministic `lower_right` mark) matches v2 exactly. |

`VISUAL_SPEC_SCHEMA_GAP = false` - no schema change, no migration. The exact
candidate integer versions are resolved by `create_candidate_spec()`'s
auto-increment at materialization time in the rollout phase; the substance above is
frozen.

## P. Spec replay

`SPEC_REPLAY_ALL_PASS = True`. `_evaluate_spec_match()` run against `FINAL_V8_SPEC_SET`
using evidence from the CLEAN RELEASE renderer:

| render | SPEC_MATCH | hard? |
|---|---|---|
| NEWS bright (portrait source) | PASS | no |
| NEWS 16:9 source | PASS | no |
| BREAKING dark | PASS | no |
| BREAKING bright | PASS | no |
| DATA generated hero `500/МЛН` (font 270) | PASS | no |
| DATA generated hero `42/%` (font 270) | PASS | no |
| DATA source-preserving MINIMAL light | PASS | no |
| DATA source-preserving MINIMAL dark | PASS | no |
| QUOTE (role + no-role) | PASS | no |

No SPEC_MATCH FAIL, no hard failure. No false fixed-zone requirement, no false 16:9
DATA requirement, no stale font-range assumption.

## Q. Art replay

`ART_REPLAY = PASS`. Evaluator behaviour verified (no production Art enforcement
enabled):

* `logo_count > 1` (duplicate NNJ) -> hard BLOCK
* `NUMBER_MISMATCH` -> BLOCK
* `INFOGRAPHIC_DESTROYED` -> BLOCK
* single-brand-mark / one-NNJ invariant enforced structurally
* every approved V8 canary (NEWS, BREAKING dark/bright, DATA generated, DATA source,
  QUOTE, QUOTE-no-role) -> no BLOCK

`tests/test_art_director_number_mismatch_blocks.py` +
`tests/test_director_control_plane_1a_art_director.py` +
`tests/test_director_control_plane_1b_art_director_live.py` (19) plus 22 V8
BLOCK/invariant cases in `test_design_spec_enforcement.py` /
`test_founder_visual_polish_2.py` / `test_brand_renderer.py` /
`test_kirin_data_regression.py` - all pass.

## R. V8_RELEASE_SHA

    V8_RELEASE_SHA = d0a03773bebc98c6b71edb67fe368b85472e2d6b
    branch         = release/founder-visual-v8-content-worker-1
    parent         = d2dea2cd7d5da714988217b1286afb8b96c26bb9

## S. Remote availability

Pushed normally (no force):

    git ls-remote origin release/founder-visual-v8-content-worker-1
    d0a03773bebc98c6b71edb67fe368b85472e2d6b  refs/heads/release/founder-visual-v8-content-worker-1

Production can `git fetch origin release/founder-visual-v8-content-worker-1`.
The superseded `a3fd0dc` release must NOT be deployed.

Production `content_worker` re-verified READ-ONLY (section B did not re-open a broad
provenance investigation): container `ai-newsroom-content_worker:d2dea2c`, image
`sha256:2117583c744514...`, **up 44h, 0 restarts**, created 2026-09-08 - predates
the provenance capture; the running `pip freeze` is identical to the provenance
manifest. `CONTENT_WORKER_UNCHANGED_SINCE_PROVENANCE = true`.

## T. Exact production rollout plan

See `docs/founder_visual_v8_production_rollout_1_plan.md` (prepared, NOT executed).
Summary of the ordered gate:

1. **Story Continuity canary complete/stable first** - do not proceed while the
   constrained-enforcement canary on `automation_worker` is mid-window.
2. Production read-only preflight (SSH): control-plane spec rows, alembic head,
   container states, health endpoints, disk.
3. Verify `content_worker` still `d2dea2c` (image id `2117583c...`, freeze == manifest).
4. Fresh backups: `pg_dump` of the control-plane DB, `.env`, `docker-compose.yml`,
   the current `ai-newsroom-content_worker:d2dea2c` image saved as a rollback tag.
5. Rollback image tag recorded (`ai-newsroom-content_worker:rollback-d2dea2c`).
6. Materialize `FINAL_V8_SPEC_SET` as CANDIDATE rows via `create_candidate_spec()`
   (dev-then-prod control-plane, still CANDIDATE - never auto-promote).
7. Verify exact candidate fields against section O; abort on any mismatch.
8. Build/fetch `d0a0377` on a clean checkout; build the image with
   `FROM python:3.12.14-slim-trixie` + `-c constraints-content-worker-live.txt`;
   verify `IMAGE_SOURCE_MATCH` / `FONT_ASSETS_PRESENT` / `IMPORT_SMOKE` as in section M.
9. Activate the specs **transactionally** (`promote_candidate()` in one DB
   transaction; `--print-rollback` captured first).
10. Recreate **only** `content_worker` (`docker compose up -d --no-deps
    --force-recreate content_worker`). `automation_worker` NOT touched.
11. Health gate: container healthy, no error loop, DB reachable, worker heartbeat.
12. Internal newsroom canaries only - render NEWS / BREAKING / DATA generated / DATA
    source / QUOTE into the internal review channel; no public channel.
13. Founder-approved visual classes only.
14. **No public publication** during the canary window.
15. `automation_worker` untouched throughout; Story Continuity code/flags untouched.
16. Rollback trigger: any runtime error, any RenderEvidence/Art invariant failure,
    any factual (`NUMBER_MISMATCH` / `INFOGRAPHIC_DESTROYED`) or single-NNJ violation,
    or any Founder-visible visual regression -> `promote` the prior spec versions
    from `--print-rollback` + recreate `content_worker` from
    `ai-newsroom-content_worker:rollback-d2dea2c`.

## U. Remaining launch blockers

1. **Story Continuity constrained-enforcement canary must complete and be declared
   stable** before the rollout phase runs (explicit ordering constraint).
2. **Founder go for the rollout phase** (this phase is preparation only).
3. `BASE_IMAGE_REPRODUCIBILITY_LIMITATION` (section F): Python 3.12.14 + Debian
   trixie are pinned; the exact OS-package snapshot digest is not recoverable from
   this environment. Acceptable (constraints file governs all Python deps; no newer
   packages possible) but recorded.
4. Test-accuracy debt (section K): `test_visual_single_brand_mark_contract.py` carries
   2 pre-V8 assertions superseded by the approved V8 NEWS/BREAKING redesign (they fail
   identically on `8e690c5`). Recommend a test-only catch-up commit before the rollout
   so its gate is green without annotation. Not a runtime blocker.
5. Production control-plane still has `telegram_data v1` / `telegram_quote v1` ACTIVE
   and `telegram_news v2` / `telegram_breaking v2` ACTIVE with NO vNEXT rows - the
   rollout must materialize + promote `FINAL_V8_SPEC_SET` (section O) transactionally.

---

`FOUNDER_VISUAL_V8_RELEASE_PREP_PASS`

Clean `d2dea2c`-based visual release (`d0a0377`, 13 runtime files,
`UNRELATED_RUNTIME_FILES = 0`); V8 visual parity byte-exact on-platform and
visually equivalent on the Linux target; bundled Fira Sans Condensed present and
self-contained on Linux; deterministic dependency strategy (live-freeze constraints
+ pinned Python build); `FINAL_V8_SPEC_SET` truthful and `SPEC_REPLAY_ALL_PASS`;
tests/static clean (`NEW_FAILURES = 0` vs the approved `8e690c5`,
`NEW_STATIC_ERRORS = 0`); release SHA pushed and fetchable by production; no
production mutation, `automation_worker` and Story Continuity untouched.

NOT deployed. Awaits Story Continuity canary completion + Founder authorization for
FOUNDER-VISUAL-V8-PRODUCTION-ROLLOUT-1.
