# CONTENT-WORKER-PROVENANCE-RECONCILIATION-1 — report

Establish a provable clean baseline for the currently running production `content_worker`, then
prepare (not deploy) a visual-only release branch.

**Outcome: `CONTENT_WORKER_PROVENANCE_RECONCILIATION_PARTIAL`.** The source baseline is **exact
and proven** (`d2dea2c`, 1617/1617 byte-identical), the visual-only release branch is clean and
tested and pushed to `origin`, and **zero production runtime was mutated**. PARTIAL only because
build-input reproducibility is not guaranteed (no dependency lockfile, floating base image) — the
running image's exact dependency set is captured, but a rebuilt image's dependency layer may
drift; not "rollout-ready" until that is settled (§AB).

---

## A. Production safety proof

Everything against production was **read-only**:

- `docker ps / inspect / image inspect / history / logs` (read-only)
- `docker exec ai_newsroom_postgres psql … SELECT …` (read-only), `docker exec ai_newsroom_content_worker sh -c "grep/cat/pip freeze/ls"` (read-only)
- `docker cp b416b1c03f77:/app/. → forensic dir` — copies **out of** the running container; container not modified
- `docker run --rm --entrypoint sh <image> …` and `docker create <image>` + `docker rm` — ephemeral inspection containers off the **already-built** image `content_worker:d2dea2c`; the running container `b416b1c03f77` and its image `2117583c` were never touched
- `git status / log / show / rev-parse / reflog / fsck / cat-file / bundle verify / for-each-ref` in `/opt/ai-newsroom` — all read-only

**No** container start / stop / rm / recreate / build on the VPS. **No** DB write. **No** file,
branch, index, stash, or checkout change in `/opt/ai-newsroom`. **No** `.env` / `docker-compose.yml`
change. `git fetch origin --prune` was run in the *previous* phase (remote-tracking refs only);
**this phase added no VPS-side change at all.**

All 7 containers are byte-identical before and after (§Z). `AUTOMATION_WORKER_TOUCHED = false`.

## B. Dirty production tree state (`/opt/ai-newsroom`) — informational, NOT cleaned

`HEAD = 324a57a9413c…` on `feature/phase19-editorial-depth-upgrade` ("feat: upload discovered
videos natively to Telegram", 2026-08-30). **46 modified tracked files, 2 stashes, ~20 untracked.**
`git fsck --full` → **0 dangling/unreachable commits**. Reflog: only
`pull --ff-only origin feature/phase19-editorial-depth-upgrade` + fast-forward merges,
2026-08-23 → 2026-08-30; HEAD was **never** on a `d2dea2c` / director-control-plane lineage here.

Modified-file classification:

| category | count | examples |
|---|---|---|
| historical feature development (meme pipeline / telegraph / image-preview) | ~40 | `services/meme_render.py` (+183), `services/meme_image_generation.py` (+93), `services/telegraph_article_review_notifier.py` (+107), `bot/*meme*`, `capabilities/meme_*`, `schemas/meme_*`, `tests/test_meme_*` ×~12, `tests/test_phase18_*`, `worker/content_cycle.py`, `integrations/llm_gateway/providers/openai_image_adapter.py` |
| operator config | 2 | `core/config.py`, `docker-compose.yml` (matches stash@{0} `127.0.0.1:8000` bind + stash@{1} `NEWS_COLLECTION_*` env passthrough) |
| a divergent local `brand_renderer.py` edit | 1 | `services/brand_renderer.py` = **+45 lines** (`_build_data_signature_fallback` variant) — a different change from the deployed `d2dea2c`; **NOT in the running content_worker** |
| generated / backup artefacts (untracked) | ~20 | `.env.bak.*` ×5, `backups/`, `artifacts/`, `r2_eval/`, `r2_test_output/`, `prompts/meme_concept/v{2,3,4}.yaml`, a migration file, `services/media_finalizer.py`, `services/meme_diversity.py` |

**None of this affects the running `content_worker`**, which runs purely from image `d2dea2c`
(no source bind-mount — §C). Stashes untouched. This is an operator working tree on an unrelated
branch; cleanup is a Founder decision for a separate step.

## C. Live content_worker identity

| field | value |
|---|---|
| `CONTENT_WORKER_CONTAINER_ID` | `b416b1c03f777a2b75ffed2aa59af368c0b28b8f48dca1d955918e9fa2dbe3d0` |
| `CONTENT_WORKER_IMAGE_ID` | `sha256:2117583c744514d19ac4c3f74f3a90a163476167f64e2b21cccf0d72c59ea281` |
| `CONTENT_WORKER_IMAGE_TAGS` | `ai-newsroom-content_worker:d2dea2c` (RepoDigest `@sha256:2117583c…`) |
| `CONTENT_WORKER_CREATED` | `2026-09-08T21:47:15Z` (container started `2026-09-08T21:53:02Z`) |
| `CONTENT_WORKER_RESTART_COUNT` | `0` |
| `CONTENT_WORKER_COMMAND` | `["python","-m","worker.content_main"]` |
| `CONTENT_WORKER_ENTRYPOINT` | `null` |
| `CONTENT_WORKER_WORKDIR` | `/app` |
| `CONTENT_WORKER_MOUNTS` | only `ai-newsroom_image_storage_data` → `/data/image_storage` (no source bind-mount) |
| env keys | 78 captured by name, no values (`.../image_metadata/env_keys_*.txt`) |

## D. Image labels / history

`Labels = null`. **No** `GIT_SHA` / `GIT_COMMIT` / `SOURCE_VERSION` / `VCS_REF` /
`org.opencontainers.image.revision` label or build ARG. **No** `/app/GIT_SHA`, `/app/VERSION`, or
`/app/.git` inside the image (`docker run --rm … sh -c "…"` → `NOFILE`).

`docker history` (top layers): base `python:3.12-slim` → a custom CPython **3.12.14** build (8-day
layers: `wget python.tar.xz … configure … make install`) → `WORKDIR /app` → `COPY . .` (34.3 MB)
→ `RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .` (236 MB). So the
image was built by `COPY`ing a build context and `pip install .`-ing it — with **no** recorded
source SHA.

## E. Live application root

`LIVE_APP_ROOT = /app`. Confirmed: `docker inspect` WorkingDir `/app`; entrypoint
`python -m worker.content_main` → `worker/content_cycle.py::run_content_cycle`; `/app` contains
the repo packages (`worker/ services/ core/ database/ schemas/ capabilities/ integrations/ bot/
app/ config/ workflows/ prompts/`) + `pyproject.toml`, `alembic.ini`, `Dockerfile`, `.gitignore`.
Python **3.12.14**, pip **26.2.1**, **56** installed packages.

## F. Live source snapshot path

`/opt/ai-newsroom-ops/content-worker-provenance-reconciliation-1/live_source_snapshot/app/` —
copied via `docker cp b416b1c03f77:/app/. → …` (container not modified). After stripping
`__pycache__` / `*.pyc` / `.git`: **1617 files, 30,415,168 bytes**. Manifests in `…/manifests/`;
`pip freeze` in `…/manifests/pip_freeze_content_worker.txt`.

## G. LIVE_RUNTIME_MANIFEST

`…/manifests/LIVE_RUNTIME_MANIFEST.sha256` — **645** repo-owned runtime files
(`<sha256>  <relpath>`, sorted):

| dir | files | | dir | files |
|---|---|---|---|---|
| services | 250 | | capabilities | 19 |
| database | 115 | | workflows | 12 |
| prompts | 57 | | worker | 7 |
| bot | 50 | | core | 5 |
| integrations | 48 | | app | 2 |
| schemas | 42 | | resources | 1 |
| config | 33 | | pyproject.toml / .gitignore / Dockerfile / alembic.ini | 4 |

manifest-of-manifest sha256 = `fce2df5997a13a334fd4482535e0af9ffad8bd1b98100c2539f5e7723e4f321a`.
Full (1617-file) manifest sha256 = `9f34ab82b4a0168f54dbf2a84fcb1651043289ece276ec4909b2a89339e1269f`.

## H. Runtime import / file set

`CONTENT_WORKER_RUNTIME_FILE_SET` = the 645 repo-owned files under the app packages + the four
build-input files (§G). Bounded by the packages the entrypoint transitively imports
(`worker.content_main` → `content_cycle` → `services/*`, `presentation_director`,
`brand_renderer`, `nnj_master_news_overlay`, …). `tests/`, `docs/`, `scripts/`, `design/` are
**excluded** from the runtime set (present in the image via `COPY . .` but never imported /
installed).

## I. Git object / reflog findings (`/opt/ai-newsroom`, read-only)

- `git fsck --full --no-progress` → **0** dangling commits, **0** unreachable commits.
- `git rev-parse --disambiguate=d2dea2c` (and `c6694b9`, `70cbce7`, `ae0232c`) → **empty** — those
  objects **do not exist** in this repo's object store.
- Reflog (20 entries): exclusively `pull --ff-only` / FF merges from
  `origin/feature/phase19-editorial-depth-upgrade`, 2026-08-23 → 2026-08-30.
- Local branches: `feature/phase19-editorial-depth-upgrade` (`324a57a`),
  `feature/r2-shadow-preparation` (`648af48`). `packed-refs` remote:
  `refs/remotes/origin/feature/phase19-editorial-depth-upgrade` → `a357e6a5…`.
- `/opt/ai-newsroom-ops/p01_c6694b9.bundle`: `git bundle list-heads` shows
  `c6694b9… refs/tags/p01-release`, but `git bundle verify` **FAILS** —
  `Repository lacks these prerequisite commits: b45e384d3aa9…`. Unusable.
- `/opt/ai-newsroom-ops/docker-compose.yml.bak-pre-visual-rollup-1` (2026-09-07 11:09) — a prior
  aborted visual-rollup attempt.

**Conclusion:** `d2dea2c` was never present in `/opt/ai-newsroom`; the `content_worker:d2dea2c`
image was built elsewhere (a transient checkout / another machine) and its tag was applied by
the build command.

## J. Origin findings

- On the VPS, `git fetch origin` did **not** retrieve `d2dea2c` / `c6694b9` / `70cbce7` /
  `ae0232c` — still unresolvable afterward. `origin/feature/director-control-plane-v1` tip is a
  `phase19`-lineage commit, **not** the local `d2dea2c` (the branch diverged on origin).
- From the local workstation repo: `d2dea2c`, `c6694b9`, `70cbce7`, `ae0232c` exist as commits
  but are on **0 remote branches** — they lived only in the local object store until this phase
  pushed the `d2dea2c` ancestry as part of the release branch (§Y).

## K. Candidate commit comparisons

`LIVE_RUNTIME_MANIFEST` (645 files) vs `git archive <sha>` (repo-owned runtime paths), computed
from the local workstation repo:

| candidate | MATCH | DIFF | MISSING | EXTRA | % | notes |
|---|---|---|---|---|---|---|
| **`d2dea2c`** | **645** | **0** | **0** | **0** | **100%** | exact |
| `c6694b9` | 640 | 5 | 0 | 0 | 99% | the 5 DIFF = Story-Continuity P0.1: `story_link.py`, `story_delta_engine.py`, `story_memory.py`, `text_normalization.py`, `triage_orchestrator.py` |
| `324a57a` (VPS HEAD) | 380 | 42 | 223 | 0 | 58% | different lineage |
| `f557b60` | 373 | 48 | 224 | 0 | 57% | different lineage |
| `fe35ca9` | 373 | 48 | 224 | 0 | 57% | different lineage |

**FULL** manifest (1617 files, incl. `tests/`, `docs/`, `scripts/`, `design/`) vs `d2dea2c`:
**MATCH 1617 / DIFF 0 / MISSING 0 / EXTRA 0.** (Three entries initially flagged as
"missing" — `dockerignore`, `env.example`, `gitignore` — were a manifest-parser dotfile artefact;
they are `.dockerignore` / `.env.example` / `.gitignore`, byte-identical.)

`c6694b9` matching at 99% (all but the 5 Story-Continuity files) independently confirms the live
content_worker is `d2dea2c` — the commit **before** `c6694b9` — and does **not** carry the
Story-Continuity P0.1 changes.

## L. Provenance mode

**`PROVENANCE_MODE = EXACT_GIT_COMMIT`.**

## M. Baseline SHA

**`CONTENT_WORKER_BASELINE_SHA = d2dea2cd7d5da714988217b1286afb8b96c26bb9`**
(`feat(design-spec): activate Founder-approved telegram_news v2 / telegram_breaking v2`).

## N. Reconstruction method

Not used — exact commit match (§12 path A).

## O. Source-manifest parity

**`SOURCE_MANIFEST_MATCH = true`** — 1617/1617 files byte-identical between the running
`content_worker` `/app` and `git archive d2dea2c` (the 645-file runtime subset is 645/645).

## P. Build-input parity

| input | classification |
|---|---|
| `pyproject.toml` | **MATCHED** (byte-identical in `d2dea2c`) |
| `Dockerfile` | **MATCHED** (byte-identical in `d2dea2c`) |
| Python interpreter | KNOWN — CPython 3.12.14 in the running image; Dockerfile base `python:3.12-slim` is a **floating tag** |
| pip-resolved dependencies | **KNOWN_DIFFERENCE** — `pyproject.toml` uses lower-bound (`>=`) pins, **no lockfile** (`requirements-lock.txt` / `uv.lock` / `poetry.lock` all absent). The running image's exact **56-package** set is captured: `…/manifests/pip_freeze_content_worker.txt`, sha256 `eb20405c16823e7fda8defd26e989db20760f515d9f5602eda65d8c752384ca4`. A fresh `pip install .` re-resolves and may drift. |
| apt system packages (`fonts-dejavu-core`, `ffmpeg`) | **KNOWN_DIFFERENCE** — unpinned apt, resolved at build time |

Nothing is **UNKNOWN** (§14's hard STOP does not fire). But the unpinned deps + floating base are
a **non-critical build-reproducibility uncertainty** → `BASELINE_CONFIDENCE = PARTIAL` on the
*build* axis. The *source* axis is **FULL / EXACT**.

## Q. Baseline rebuild parity

`docker build` from the release branch (local, **non-running**, image `6382f49b031a`, discarded
after) → extracted `/app` source manifest = **1617/1617** match against the expected tree
(`d2dea2c` for 1614 files + `70cbce7` for the 3 visual files). **`BUILT_RUNTIME_SOURCE_MANIFEST_MATCH = true`.**
The image ID differs from the running one — irrelevant per §15; the `COPY . .` mechanism
reproduces the source deterministically.

## R. Live visual foundation

**`LIVE_VISUAL_FOUNDATION = PASS`** — all 8 markers present on `d2dea2c`:

| marker | evidence |
|---|---|
| NEWS current renderer | `services/nnj_master_news_overlay.py :: def apply_master_news_branding` |
| BREAKING heavy band retired | `services/brand_renderer.py` — "the retired treatment - a ~22%-tall dark-gradient lower-third band" |
| single-NNJ invariant | `services/telegram_art_director.py :: DUPLICATE_NNJ_BRAND_MARK` |
| DATA existing-infographic preservation | `services/brand_renderer.py :: MINIMAL_SOURCE_PRESERVING` |
| NUMBER_MISMATCH hard block | `services/telegram_art_director_spec_evaluation.py :: NUMBER_MISMATCH` |
| INFOGRAPHIC_DESTROYED hard block | `services/telegram_art_director_spec_evaluation.py :: INFOGRAPHIC_DESTROYED` |
| RenderEvidence foundation | `services/render_evidence.py :: class RenderEvidence` |
| Art / VisualSpec evaluation integration | `services/telegram_art_director_spec_evaluation.py :: evaluate_against_spec_and_references` |

## S. Approved visual delta extraction

Recomputed `d2dea2c..70cbce7`. Runtime changes = 10 files: the **3 visual** +
**7 Story-Continuity P0.1** (`services/story_continuity.py`, `story_identity_guard.py`,
`story_memory.py` (+456), `story_delta_engine.py`, `triage_orchestrator.py`,
`text_normalization.py`, `database/models/story_link.py`).

**`APPROVED_VISUAL_RUNTIME_DELTA_FILES = [services/brand_renderer.py, services/render_evidence.py, services/presentation_director.py]`**
— the 7 Story-Continuity files **excluded**. The 3 visual files import only pre-existing
`d2dea2c` helpers (`_fit_single_line`, `_fit_wrapped_block`, `rasterize_nnj_mark`,
`_draw_pulse_line`, …) — **no** dependency on the excluded set (§7 STOP not triggered).

## T. Visual release branch construction

Worktree from `d2dea2c`; `git checkout 70cbce7 -- services/brand_renderer.py
services/render_evidence.py services/presentation_director.py`; the 3 files' sha256 verified
identical to `70cbce7`'s blobs (`d3ec8b6a…`, `aec3fbf6…`, `ad7527db…`); committed as **`a3fd0dc`**
on branch **`release/founder-visual-vnext-content-worker-1`**. Test files were **not** committed
to this branch (kept as a pure runtime delta).

## U. Exact release diff

`git diff --name-status d2dea2c a3fd0dc`:

```
M  services/brand_renderer.py         (+215 / -15)
M  services/presentation_director.py  (+12)
M  services/render_evidence.py        (+73)
3 files changed, 285 insertions(+), 15 deletions(-)
```

**`UNRELATED_RUNTIME_FILES = 0`.** No Story-Continuity, control-plane, docs, tests, scripts,
or other-feature file. Every changed file is a reviewed visual-runtime file, required for: the
generated DATA hero-metric card (`render_data_hero_card` + `DataCandidate.series/delta`), the
Founder-board QUOTE composition (`render_quote_card` rewrite + `QuoteCandidate.role`), and the
matching RenderEvidence (`_derive_data_hero_evidence`).

## V. Baseline tests

`BASELINE_TEST_RESULT` — `d2dea2c` checkout, its own test files, focused surface
(`test_brand_renderer`, `test_render_evidence_parity`, `test_design_spec_enforcement`,
`test_v2_10h_master_news_production`, `test_visual_renderer_constraints`,
`test_presentation_director`, `test_art_director_number_mismatch_blocks`):
**194 passed, 1 skipped, 0 failed.**

## W. Release tests

Release worktree + the vNEXT visual test files **overlaid** from `70cbce7`
(`test_founder_visual_board_alignment_1.py` [new] + updated `test_brand_renderer.py` /
`test_render_evidence_parity.py` / `test_design_spec_enforcement.py`) — **test-only overlay, not
committed** — same surface: **210 passed, 1 skipped, 0 failed** (194 baseline + 16 new visual).

Covers: NEWS parity, BREAKING parity, DATA hero metric, DATA source-preserving infographic,
`NUMBER_MISMATCH`, `INFOGRAPHIC_DESTROYED`, DATA RenderEvidence, QUOTE full-role, QUOTE
missing-role fallback, quote attribution integrity, single NNJ, RenderEvidence parity, Art
evaluation.

**`NEW_FAILURES = 0`.**

## X. Static checks

`ruff check` → **All checks passed**; `mypy` → **Success: no issues found** — on
`services/brand_renderer.py`, `services/render_evidence.py`, `services/presentation_director.py`
at `a3fd0dc`. **`NEW_STATIC_ERRORS = 0`.**

## Y. Remote release availability

`git push -u origin release/founder-visual-vnext-content-worker-1` — **new branch, no force, no
rewrite of any existing branch**. Confirmed on origin:
`a3fd0dcab034b01a22e86f6f8480bedfb5bf2cc1  refs/heads/release/founder-visual-vnext-content-worker-1`.

**`VISUAL_RELEASE_SHA = a3fd0dcab034b01a22e86f6f8480bedfb5bf2cc1`.**

The push also published `d2dea2c` and its ancestry (the visual-reconciliation lineage — the
**true provenance of the running `content_worker`**), which `origin` previously lacked. It did
**not** publish `c6694b9` / `70cbce7` / `ae0232c` or the Story-Continuity P0.1 lineage — those
are not ancestors of `a3fd0dc`. Production can now `git fetch origin
release/founder-visual-vnext-content-worker-1`.

## Z. Production containers before / after

| container | container ID | image ID | tag | restarts | startedAt | changed? |
|---|---|---|---|---|---|---|
| automation_worker | `2efc4c8b319d…` | `f592398ca237…` | `:c6694b9` | 0 | 2026-09-09T11:22:52Z | **NO** |
| content_worker | `b416b1c03f77…` | `2117583c7445…` | `:d2dea2c` | 0 | 2026-09-08T21:53:02Z | **NO** |
| news_analysis_worker | `a722b21fdfb4…` | `75ed4b0e3779…` | `:d2dea2c` | 0 | 2026-09-08T22:48:56Z | **NO** |
| telegram_bot | `aff0902c0ff4…` | `ac8fd866dbf8…` | `:d2dea2c` | 0 | 2026-09-08T21:51:58Z | **NO** |
| backend | `bcdbab62156a…` | `ddc9cc52b6ba…` | — | 0 | 2026-09-02T21:51:52Z | **NO** |
| postgres | `6d7c65f7db5c…` | `44c4ee9810ef…` | `postgres:16-alpine` | 0 | 2026-09-07T11:10:17Z | **NO** |
| redis | `db6fc18c1f3e…` | `e7723ff73d96…` | `redis:7-alpine` | 0 | 2026-09-06T19:25:02Z | **NO** |

`AUTOMATION_WORKER_TOUCHED = false` (`automation_worker` healthy — `phase9_triage_cycle_finished`
/ `event_recap_scan_finished` / `automation_cycle_finished` in recent logs). `content_worker`
running container, image, and restart count **unchanged**.

## AA. Remaining provenance uncertainty

1. **Build-input reproducibility** — no dependency lockfile; `Dockerfile` base is the floating
   `python:3.12-slim` and `pip install .` uses `>=` bounds. The running image's exact 56-package
   set is captured (`pip_freeze_content_worker.txt`), but a rebuilt `content_worker` image's
   dependency layer may differ from the running one. `BASELINE_CONFIDENCE = PARTIAL` (build axis).
2. The running `content_worker:d2dea2c` image carries **no embedded source SHA / build
   attestation** — provenance was established by full-content manifest match (1617/1617), not by
   a build-time record.
3. **Where/how the `content_worker:d2dea2c` image was originally built is not recorded** on the
   VPS (it was not built from `/opt/ai-newsroom`, which never contained `d2dea2c`).

## AB. Exact prerequisites for rerunning FOUNDER-VISUAL-VNEXT-PRODUCTION-ROLLOUT-1

1. On the VPS: `git fetch origin` in a **clean** checkout (NOT the dirty `/opt/ai-newsroom` tree);
   `git rev-parse origin/release/founder-visual-vnext-content-worker-1` must equal
   `a3fd0dcab034b01a22e86f6f8480bedfb5bf2cc1`; `git diff --name-status d2dea2c a3fd0dc` must show
   **only** the 3 visual files.
2. **Dependency strategy — decide one:**
   (a) pin the rollout `content_worker` image build to the captured
   `pip_freeze_content_worker.txt` (add a constraints/lock file so the dependency layer is
   reproducible), **or**
   (b) Founder explicitly accepts a possible dependency drift (deps were last resolved
   2026-09-08, ~2 days stale — low risk, not zero).
3. Build the rollout `content_worker` image from **`a3fd0dc`** via a fresh clone or a clean
   checkout — **never** `docker compose build` in `/opt/ai-newsroom` (its dirty `324a57a` tree
   would build the wrong source).
4. Then proceed through the rollout phase's §9–§22: read production spec state → `pg_dump`
   backup → materialise `telegram_news v3` / `telegram_breaking v3` / `telegram_data v3` /
   `telegram_quote v2` candidates → `scripts/activate_visual_spec_vnext.py` (dry-run then commit)
   → recreate **only** `content_worker` from the `a3fd0dc` image → health gate → internal-only
   Telegram canaries.
5. Do **not** touch `automation_worker`, the dirty `/opt/ai-newsroom` tree, or the 2 stashes.

---

## Verdict

`PROVENANCE_MODE = EXACT_GIT_COMMIT`; `CONTENT_WORKER_BASELINE_SHA = d2dea2cd7d5da714988217b1286afb8b96c26bb9`
(1617/1617 byte-identical source, independently corroborated by the 99%/5-file `c6694b9` delta).
`LIVE_VISUAL_FOUNDATION = PASS`. Clean visual-only release branch
`release/founder-visual-vnext-content-worker-1` @ `a3fd0dc` — `UNRELATED_RUNTIME_FILES = 0`,
baseline 194 passed → release 210 passed, `NEW_FAILURES = 0`, `NEW_STATIC_ERRORS = 0`,
`BUILT_RUNTIME_SOURCE_MANIFEST_MATCH = true` — **pushed to `origin`**. **Zero production runtime
mutation; `automation_worker` untouched.**

Not `PASS` only because build-input reproducibility is not guaranteed (no lockfile / floating
base image); the running dependency set is captured but a rebuild may drift — resolve per §AB.2
before the rollout.

**CONTENT_WORKER_PROVENANCE_RECONCILIATION_PARTIAL**

Do not deploy. Wait for Founder review.
