# Production Source Reconciliation V1

Branch: `feature/production-source-reconciliation-v1`
Base: `feature/social-intelligence-ops-v1` @ `28307800cdb9a2c1c94cbfb166cc6d0affc9df53`
Worktree: `C:\Users\Theodor\ai-newsroom-prod-reconciliation`

## Purpose

Before any Social Intelligence / Visual Design Autonomy deployment, this branch reconciles the
accepted development history against currently-live and recently-prepared-but-undeployed
production behavior, so no production-only correctness fix is silently lost when this branch
eventually ships. This is a source-reconciliation phase, not a feature phase: no new product
capability was added except where explicitly noted (visual observability logging, deferred - see
Remaining Work).

## Method

1. **Forensic snapshot (read-only).** Inspected `docker inspect`/`docker cp` output for every
   app container (`ai_newsroom_telegram_bot`, `ai_newsroom_content_worker`,
   `ai_newsroom_automation_worker`, `ai_newsroom_backend`) to extract the actual running source,
   independent of git. `content_worker`'s image no longer exists (`docker image inspect` fails)
   but its container filesystem was still extractable via `docker cp` on the stopped container.
2. **Branch inventory.** Confirmed two real, non-ancestor git branches carry additional
   production-track work beyond dev's own history: `feature/prod-content-recap-release` and
   `feature/prod-telegram-recap-release`. Neither is an ancestor of the other or of dev - they are
   parallel production-track branches with overlapping but not identical scope.
3. **Two-tier authority check.** Per this phase's own explicit rule, the RUNNING CONTAINER is
   authoritative for currently-live behavior; a git branch is only evidence of *prepared*
   production-track work. Critically, this reconciliation found real, confirmed cases where the
   two tiers disagree in **both directions**, and treated them differently:
   - **Branch ahead of the running container, dev also missing it -> RECOVER.** E.g.
     `services/media_finalizer.py` exists in neither running container (the deployed images
     predate it) but is real, tested, incident-driven work absent from dev too. Recovered.
   - **Branch behind dev's own later, independent work -> LEAVE ALONE.** E.g.
     `worker/cycle.py`'s RECAP-scheduler wiring: the production branch snapshot is *older* than
     dev's own `94edb97 feat(recap): add flag-gated automation scheduler` commit, which already
     implements equivalent-or-better functionality under different wording. An initial pass
     mistakenly overwrote this file with the older branch content; caught by a semantic diff
     against dev's own committed history and the real running container (both agreed dev's
     version was correct) and reverted before commit. See Errors Caught, below.
4. **Content-level diffing, not file-inventory diffing.** An earlier pass in this phase compared
   `git ls-tree` file lists only and concluded the meme pipeline was "already reconciled" because
   the file *names* matched between dev and production. This was wrong: several files had
   identical names but materially different content (see Meme Production Fix Chain, below). This
   phase's real methodology is, per file common to both trees: diff content, not just presence;
   classify every production-unique line as either a genuine gap (recover) or dev's own
   superseding evolution (leave alone, confirmed via git history / running-container cross-check).

## Recovered (real production-only correctness fixes, absent from dev)

### 1. MEDIA-PROD-1 canonical branding choke-point (`003e7fd`)
`services/media_finalizer.py::finalize_photo_input()` - the single choke-point every non-router
photo-delivery path must call to get the same mandatory NNJ branding
`worker/content_cycle.py`'s own router already applies for NEWS sends. Recovered verbatim plus
wired into `bot/handlers/image_preview.py`, `services/image_preview_notifier.py`,
`services/event_recap_review_notifier.py`, and `services/final_post_review_notifier.py`
(replacing a duplicate, admittedly-broken inline reimplementation dev had written independently
after this helper was unavailable in that branch's history - see that commit's own "R2.10-
FINALIZATION-2" comment).

Also fixed in the same commit: `bot/keyboards/image_preview.py::build_editorial_send_keyboard()`'s
default button label was `"🔗 Open source"` in dev vs. production's `"🔗 Источник"` - a real,
previously undetected live-path bug (2 call sites relied on the English default without passing
`label=` explicitly). `tests/test_final_post_review_notifier.py` had encoded the bug as an
expected assertion; corrected.

### 2. Video quality gate + media vision review diagnostics (`8576c43`)
`services/video_quality_gate.py` (new) - shadow/enforce deterministic advertisement-keyword text
gate for video hints, wired into `worker/content_cycle.py` alongside dev's own independent
Channel Director shadow addition (confirmed non-overlapping insertion points). New
`video_quality_gate_mode` setting, off by default.

`scripts/media_vision_review_diagnostics.py` (new) - read-only manual diagnostics harness,
requiring `get_media_vision_review_calibration_summary()` (new) appended to
`services/media_vision_review_persistence.py`.

### 3. MEME-PROD-2.1 / 3 / 3.1 production fix chain (`f795f3e`)
The single largest recovered domain. Dev's meme pipeline had identical file *names* to production
but materially stale *content* - a coherent, evidence-driven incident-fix chain never merged back:
- **Watermark**: switched from a flat PNG raster to the SVG rasterizer (`nnj_master_news_mark.py`)
  already used elsewhere for brand consistency, adaptive red/white by background luminance -
  production evidence showed the old PNG-sourced watermark reading as "the wrong logo variant."
  MEME-PROD-3.1 additionally halved the mark's size.
- **Render**: real Cyrillic-capable font resolution. Pillow's built-in default font has **no
  Cyrillic glyphs** - dev's memes would have rendered Russian on-image text as tofu boxes.
  Also: watermark-clearance reservation so wrapped caption lines never overlap the mark, and
  typography tuning (2 lines/band max, ~17% smaller fonts).
- **Language enforcement**: a deterministic Cyrillic-presence backstop
  (`_meme_overlay_text_is_russian`) in `services/meme_generation_orchestrator.py`, plus the
  matching prompt-level rule in `prompts/meme_copywriting/v1.yaml` - the mandatory-Russian-
  on-image-text product rule, code and prompt halves both recovered.
- **Pseudo-text hardening**: `capabilities/meme_concept_capability.py` bumped
  `PROMPT_VERSION` 2 -> 3 (new `prompts/meme_concept/v3.yaml`), and the matching
  `services/meme_image_generation.py` prompt-builder changes, closing a real gpt-image-2 canary
  issue (garbled on-image scribble text / fake UI chrome).
- **Localization**: `bot/keyboards/meme_preview.py` button labels and
  `bot/meme_preview_formatting.py`'s Telegram preview caption ("😂 Мем", was "😂 MEME") -
  MEME-PROD-2.1's RU localization.

One additional stale-assertion fix beyond production's own diff, same class of bug as the keyboard
label above: `tests/test_phase18_meme_pipeline_offline_e2e.py` still hardcoded the pre-fix "MEME"
caption. Corrected.

Verified via a full meme-pipeline test sweep (461 tests) - 4 failures, all independently confirmed
pre-existing on the accepted dev branch baseline, unrelated to this recovery.

### 4. MEDIA-PROD-1 guaranteed-branding fallback for DATA cards (`eef6e56`)
`services/brand_renderer.py::render_data_card()` had no `else` branch when
`_select_data_signature()` returns `None` (both bottom corners fail the scored safety search) - a
DATA card could ship with **zero NNJ branding**, silently violating this codebase's own "every
image receives final branding layer" requirement. This was missed by the prior phase's own
top-level-definition-superset check because the deleted content was a *call site* (an `else`
branch), not a `def` - a real gap the def-name comparison methodology cannot see. Recovered
`_build_data_signature_fallback()` and its two dedicated regression tests verbatim.

## Investigated and confirmed already reconciled (no action needed)

- **Story Memory V2 / RECAP domain** (`worker/cycle.py`, `services/story_memory.py`,
  `services/content_draft_service.py`, `services/story_duplicate_guard.py`,
  `services/fact_safety.py`, `services/presentation_director.py`, `services/recap_event.py`,
  `database/models/story_link.py`, `database/models/story_telegram_delivery.py`): every
  content-level difference against both production branches traced to dev's own later, deliberate,
  dated evolution (e.g. `content_draft_service.py`'s explicit "PHASE STORY-MEMORY-V2-2 Phase 1
  safety fix (2026-09-02)" comment narrowing `is_update` on purpose) - never a case of production
  having something dev lacks.
- **Automation worker domain**: `b04fac8` (fix(safety): avoid false compound entities in
  final-post fact check) confirmed still an ancestor of dev HEAD after all reconciliation commits.
- **Canonical logo assets**: SHA256-identical across dev and both production images
  (`assets/brand/nnj_logo.png/.svg`, `nnj_logo_red.svg`).
- **Canonical overlay assets** (`assets/brand/newsroom_visuals/`): confirmed absent from both
  production images, but traced via reachability analysis to belong exclusively to
  `services/nnj_overlay_contract.py` -> `nnj_candidate_c_contract.py` ->
  `services/editorial_recomposition.py`, gated by `editorial_recomposition_mode="off"` (default,
  not overridden anywhere in production). Non-live experimental "Candidate C" code, not a
  production asset gap.
- **RECAP flag safety**: `event_recap_scheduler_enabled`, `event_recap_generation_enabled`,
  `final_post_publication_enabled` all confirmed `False` by default in `core/config.py`, matching
  every production container's env (none override these).
- **Alembic migration lineage**: single head (`7176e2997b8b`) confirmed via `alembic heads`. The
  real production database (`ai_newsroom_postgres`, live query) is stamped at `afcd869550a7` - the
  direct parent of dev's head in a single linear chain. No divergent/production-only migration
  exists; upgrading production to `7176e2997b8b` is a clean, purely additive single step.

## Deliberately deferred (out of this phase's scope)

- **MEME-PROD-4 "Meme Director" evolution** (`feature/prod-telegram-recap-release` only, not an
  ancestor of the content-release branch, not present in any running container): adds a new
  required `visual_punchline` schema field, `panel_count`/`panel_beats` multi-panel support, a new
  `services/meme_shape_gate.py` module, and a bounded-retry correction loop
  (`PROMPT_VERSION` 3 -> 4). This is structural feature evolution of the meme concept itself, not
  an incident-driven correctness preservation like the MEME-PROD-2.1/3/3.1 chain above, and falls
  under this phase's own explicit "No feature redesign. No changes to meme behavior" constraint
  (§11). Not implemented. Flagged for a future, explicitly-scoped feature phase.
- **Visual observability lifecycle events** (§26 of the phase spec: `visual_brief_candidate_
  created`, `_validated`, `_promoted`, `_rejected`, `_rolled_back`, `_frozen`, `_unfrozen`) - the
  phase spec explicitly permits adding this now since it closes an operational visibility gap
  without changing visual behavior, but it was not implemented in this pass given time budget.
  Genuinely additive (log-only) and low-risk; good candidate for the very next small commit.
- **Visual safe-zone context wiring** (§27: `VisualDirectorContext.renderer_constraints_summary`
  from real `nnj_master_news_overlay.py` placement-zone data instead of caller-supplied text) -
  not implemented, same reason.
- **Docker build matrix / build provenance** (§29-30) and **parity harness** (§31-35): not
  attempted. Building and comparing real images for telegram_bot/content_worker/
  automation_worker/backend/news_analysis_worker against this branch is a substantial,
  infrastructure-heavy effort outside a single reconciliation session's realistic budget, and this
  phase's own rules forbid building "production replacement images" as a side effect of casual
  investigation. Recommend a dedicated, explicitly-scoped follow-up phase.

## Errors caught during this phase (self-corrected, no user intervention)

- Two files (the keyboard-label fix and the video-quality-gate wiring) were initially edited in
  the wrong worktree (`ai-newsroom-social-ops`, the accepted dev branch) before this reconciliation
  worktree existed as the intended target. Caught before committing; reverted via patch-and-
  reapply into the correct worktree.
- `worker/cycle.py` was briefly, incorrectly overwritten with the *older* production-branch
  snapshot during the telegram-branch content sweep, before recognizing that dev's own committed
  RECAP-scheduler wiring (`94edb97`) already superseded it. Caught via a semantic diff against
  both dev's own git history and the real running automation-worker container (both agreed dev's
  version was correct); reverted before commit.

## Verification performed

- `ruff check` and `mypy`: full-repo sweep on the reconciliation worktree. Zero new errors versus
  the accepted dev branch baseline (23 pre-existing ruff findings, 9 pre-existing mypy environment/
  config findings - both confirmed identical on `feature/social-intelligence-ops-v1`).
- Full `pytest` suite (5857 collected, excluding 4 files that fail to collect identically on the
  accepted dev branch - see below): **5788 passed, 41 failed, 28 skipped** - matching the prior
  phase's own documented baseline (5751 passed, 41 pre-existing failures, 28 skipped) exactly on
  failed/skipped counts; the higher pass count is this phase's own added tests (media_finalizer,
  video_quality_gate, media_vision_review calibration, two brand_renderer fallback tests).
  Cross-checked the exact 41 failing node IDs by re-running them as a fixed subset on both branches:
  identical result on both (38 failed, 3 passed - the 3 are order-dependent/shared-Postgres-state
  flakiness that also disappears when the same 3 are run in isolation on *either* branch, not a
  reconciliation-branch regression). No new failures were introduced by this phase.
- The 4 pre-existing collection errors (`test_phase20_m1_harness_fixes.py`,
  `test_v2_3a_editorial_recomposition_canary.py`, `test_v2_4d_overlay_contract.py`,
  `test_v2_4f_compact_overlay.py` - missing local-only `scripts/` files and the confirmed-non-live
  overlay manifest) confirmed identical on `feature/social-intelligence-ops-v1`.
- Secret scan (grep for API-key/token/password/private-key patterns) run against every diff before
  each commit; clean in all five commits.
- No binary/media assets were committed by this phase - all recovered content is `.py`/`.yaml`
  source, so the asset-review gate (§40) was not triggered.

## Addendum: PRODUCTION-SOURCE-RECONCILIATION-1B (build provenance, functional parity, visual completion)

Continues directly from the PASS/PARTIAL boundary above. Branch, worktree, and commit range are
unchanged; this addendum covers commits `2bfd69e` (safe-zone adapter + observability) and later.

### Provenance re-verification

The prior report said "COMMITS=5" while listing 6 SHAs - a simple counting error, not an integrity
problem. Re-verified directly: `git rev-list --count 28307800..HEAD` = 6 at the start of this
addendum (7 after the observability commit), all 6/7 are real ancestors of HEAD in the stated
order, `git merge-base --is-ancestor` confirms the base commit is an ancestor, and the worktree was
clean before every commit.

### Old service-specific production branches, and why they were not blindly copied

`b04fac8` (automation), `250da40` (`feature/prod-content-recap-release`'s tip), and `6046c04`
(`feature/prod-telegram-recap-release`'s tip) are the three service-specific "preserve-and-patch"
production lineages this reconciliation had to reconcile against. `b04fac8` was already a direct
ancestor of dev HEAD - no work needed there. `250da40` and `6046c04` are NOT ancestors of dev or of
each other (confirmed via `git merge-base --is-ancestor` both ways returning false) - two parallel,
overlapping-but-not-identical production-track branches.

Neither was blindly merged or copied wholesale, for two confirmed reasons found during this
addendum's own content-level diffing:

1. **A production branch can be *behind* dev's own later, independent work.** `worker/cycle.py`'s
   RECAP-scheduler wiring exists in both `feature/prod-content-recap-release` (older, simpler
   version) and dev's own committed history (`94edb97 feat(recap): add flag-gated automation
   scheduler`, newer, equivalent-or-better). A first pass in this addendum mistakenly overwrote
   dev's file with the older branch snapshot before recognizing this from a semantic diff against
   both dev's own git log and the real running automation-worker container (both agreed dev's
   version was correct) - reverted before commit. `services/presentation_director.py` and
   `services/fact_safety.py` showed the same pattern (dev's own dated, documented DATA-CARD-1 /
   R2.10-FINALIZATION-3 evolution superseding the production branch snapshot) and were likewise
   left untouched.
2. **A production branch can contain real, still-unrecovered incident fixes even though it was
   never actually deployed.** The single largest finding of this whole reconciliation (the
   MEME-PROD-2.1/3/3.1 fix chain - SVG watermark, Cyrillic font support, Russian-language
   enforcement, pseudo-text prompt hardening) was recovered from `feature/prod-content-recap-
   release` despite that exact code never having shipped to the currently-running
   `ai_newsroom_automation_worker` container (confirmed via `docker cp` extraction - the running
   image, dated 2026-08-24, predates it). It was recovered anyway because it is real,
   already-authored, already-tested, evidence-driven production-track work that dev's own history
   never received - a deploy freeze (the very reason this reconciliation phase exists) is the most
   likely explanation for why an already-fixed incident never reached the running container, not a
   reason to leave the fix behind.

`feature/prod-telegram-recap-release` additionally carries a "MEME-PROD-4 Meme Director" evolution
(panel-format support, `PROMPT_VERSION` 4, a new shape-gate module) layered on top of the same
MEME-PROD-2.1/3/3.1 base already recovered. This is structural feature work, not incident
preservation, and was deliberately NOT implemented (violates the "no feature redesign" constraint)
- confirmed via diffing the two production branches against each other, not just against dev.

### Canonical build

One Dockerfile (`build: .` in `docker-compose.yml`) serves `telegram_bot`, `content_worker`,
`automation_worker`, `backend`, and `news_analysis_worker` alike - they differ only by the
`command:` override, never the image contents. Building once from the final canonical SHA
(`2bfd69e8987fd7abe9fb524d1d2d190922da5fb4`) and tagging it three ways therefore proves
buildability for all three primary services simultaneously; all three tags resolved to the same
image ID (`961098cd6f1a...`), as expected.

Source provenance: SHA256 of 26 critical recovered/touched files (the full MEDIA-PROD-1/meme-chain/
DATA-fallback/RECAP/visual-safe-zone/observability set) matched byte-for-byte between the
reconciliation worktree and the built image. All three entrypoints (`bot.main`,
`worker.content_main`, `worker.main`) import cleanly against fake, unreachable Postgres/Redis/
Telegram config - no model call, no public send, no automatic migration at import time.

### Migration proof against the real production database

Read-only query against the real, running `ai_newsroom_postgres` container: production's
`alembic_version` is stamped at `afcd869550a7` (add director runs table) - the direct parent of
dev's single head, `7176e2997b8b` (add visual design autonomy tables). Exactly one migration
separates them, entirely additive (4 `ADD_TABLE`, several `ADD_INDEX`, one
`ALTER TYPE ... ADD VALUE IF NOT EXISTS` enum extension) - zero destructive operations. Proven on
two disposable local databases (never production): a fresh empty DB upgrades cleanly all the way
to head (44 migrations, including one real multi-head `MERGE`), and a DB brought to the exact
production revision first upgrades cleanly through just the one remaining production-to-head step.
Both disposable databases were dropped immediately after.

### Safe-zone / renderer-constraint resolution

`services/nnj_overlay_contract.py` is confirmed NOT the live overlay source - its own module
docstring says so ("NOT YET wired into services/brand_renderer.py or worker/content_cycle.py -
this is proof-phase infrastructure only"), and its manifest asset is absent from both production
images (already established in the base report). It is reachable only through
`nnj_candidate_c_contract.py` -> `editorial_recomposition.py`, gated by
`editorial_recomposition_mode="off"` (default, never overridden in production).

The real, confirmed-live geometry lives in code: `services/nnj_master_news_overlay.py::
apply_master_news_branding()` ("the ONE production compositing entry point", called from
`worker/content_cycle.py` for every NEWS/BREAKING send) and `services/brand_renderer.py::
render_data_card()` for DATA. New `services/visual_renderer_constraints.py::
get_current_renderer_constraints()` derives a truthful, read-only summary directly from those
modules' own live constants - wired as the real default for `VisualDirectorContext.
renderer_constraints_summary` in `services/visual_design_loop.py`, replacing the literal
`"unknown"` that shipped in VISUAL-DESIGN-AUTONOMY-1. **SAFE_ZONE_CONTEXT_BLOCKED=false** -
resolved, not blocked.

### Visual brief lifecycle observability (closed)

`services/visual_brief_observability.py` (new) emits one `logger.info()` event per lifecycle
transition (`visual_brief_candidate_created/_validated/_promoted/_rejected/_rolled_back/_frozen/
_unfrozen`), wired into every mutation in `services/visual_designer_brief_service.py` and the
validation outcome in `services/visual_regression_service.py`. Never logs raw `brief_text` - only
scope/version/parent version/reason code/evidence stage/result/cost. Proven via 8 tests using real
`caplog` capture against the actual wiring (not mocks), including an explicit "raw brief text never
appears in any log payload" proof and a "normal read emits zero lifecycle events" proof.

### Feature flag audit

Enumerated every new runtime-impacting flag across Business Context/Console, Telegram Directors,
Telegram Performance, Instagram Growth, Visual Design Director/Autonomy/Auto-Revision, Brief
Adaptation/Auto-Promotion, Regression Validation, and DirectorRun Persistence (22 boolean flags,
plus `video_quality_gate_mode` from this same reconciliation's first pass) - all default `False`/
`"off"`. The 4 flags found defaulting `True` (`watermark_enabled`, `pulse_line_enabled`,
`editorial_code_enabled`, `presentation_breaking_enabled`) are pre-existing, already-live
production behaviors unrelated to the new Social/Visual systems, not something this reconciliation
introduced.

### What remains (see the final report for the complete gap list and verdict)

Behavioral parity harness (side-by-side runtime comparison of the new image against the current
production image under live-shaped traffic) and a dedicated pixel-level visual regression corpus
artifact were not built this addendum - covered instead by the existing brand_renderer.py/
meme_render.py/meme_watermark.py test suites, which already assert the relevant pixel-level
invariants directly (branding presence, safe-zone non-intrusion, contrast, fallback engagement).
MEME-PROD-4 remains deliberately deferred.
