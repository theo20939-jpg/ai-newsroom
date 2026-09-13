# VISUAL-SPEC-VNEXT-PRODUCTION-ALIGNMENT-1 — report

Prepare the Founder-approved NINJA PULSE visual system for production alignment: promote the
approved vNEXT specs in a controlled way, prove the new DATA / QUOTE renderer semantics against
the board, determine the minimum runtime deploy scope, and prepare a rollback-safe rollout plan.

**No runtime services deployed. No `automation_worker` touch. Story Continuity shadow observation
untouched.** Production control-plane VisualSpec was **not** mutated (see §K).

---

## A. Base / final SHA

- **Base:** `70cbce7bd9a6ab5028168c7b86c6e3d7d35c4bc0` — `feat(visual): FOUNDER-VISUAL-BOARD-ALIGNMENT-1 - DATA hero-metric + QUOTE board composition`
  (branch `feature/launch-readiness-visual-recap-parallel-1`, worktree
  `C:/Users/Theodor/ai-newsroom-launch-visual-recap-1`). Proven at start; working tree clean; no
  reset/clean/rebase/amend; runtime code matched the reviewed phase.
- **Final:** `4410d8c` (this report + the design doc + the vNEXT candidate/activation
  scripts + one test-constant alignment. **Zero `services/` runtime changes this phase.**

## B. Founder decisions applied

| decision | encoding this phase |
|---|---|
| **DATA generated = HERO_METRIC**, existing infographic stays MINIMAL_SOURCE_PRESERVING, never forced to hero | renderer already shipped in `70cbce7`; `telegram_data` **v3 CANDIDATE** `{font_size_max:200, font_size_min:88, max_line_count:2, safe_margin_frac:0.019}` — truthful for BOTH DATA modes (see §E) |
| **QUOTE** = red quote marks, dominant body, portrait right, author name red, role grey/optional/never fabricated, one NNJ, no redundant baked Telegram metadata | renderer already shipped in `70cbce7`; `telegram_quote` **v2 CANDIDATE** (params byte-identical to v1 — the change is compositional) |
| **BREAKING text colour** — do NOT bake the headline into the image; Telegram text stays native; use bold hierarchy + BREAKING label + media-side red urgency + pulse | **no code change needed** — `render_breaking_frame()` already bakes no headline text (band/wordmark retired in VISUAL-RENDERER-RECONCILIATION-1). Confirmed by `test_founder_visual_board_alignment_1.py::test_breaking_render_evidence_unchanged_no_band_no_scrim` and the source-introspection guards in `test_brand_renderer.py`. |
| **Adaptive logo placement** approved — exactly one NNJ mark, deterministic, bounded safe zones, RenderEvidence reports the ACTUAL zone; VisualSpec must describe adaptive-safe behaviour truthfully; do not falsify a constant `lower_right` | `telegram_news` / `telegram_breaking` **v3 CANDIDATE** drop `logo_zone` (see §E/§F). DATA hero + QUOTE place their one mark deterministically at `lower_right`, so those keep `logo_zone` truthfully (DATA v3 drops it only because the MINIMAL mode is adaptive). |

## C. DEV_SPEC_STATE (dev control-plane DB, read directly)

| scope | versions |
|---|---|
| `telegram_news` | v1 SUPERSEDED · **v2 ACTIVE** `{safe_margin_frac, logo_zone:lower_right, scrim:none, source:preserve}` · **v3 CANDIDATE** `{safe_margin_frac, scrim:none, source:preserve}` (adaptive — no logo_zone) |
| `telegram_breaking` | v1 SUPERSEDED · **v2 ACTIVE** (same as news v2) · **v3 CANDIDATE** (same as news v3) |
| `telegram_data` | **v1 ACTIVE** `{font 48–88, max_line_count 2, safe_margin, logo_zone:lower_right, scrim:none, source:preserve}` · v2 REJECTED (hero-only lie) · **v3 CANDIDATE** `{font 88–200, max_line_count 2, safe_margin}` · v4 REJECTED (accidental duplicate of the v2 lie) |
| `telegram_quote` | **v1 ACTIVE** `{safe_margin, logo_zone:lower_right, scrim:none, source:preserve}` · **v2 CANDIDATE** (params byte-identical to v1) |

`ACTIVE/FROZEN count per scope = 1` for all four (invariant holds). No candidate promoted.

## D. PROD_SPEC_STATE

**NOT REACHABLE from this environment.** `core.config.database_url` resolves to the local dev
DB (`postgresql+asyncpg://…@localhost:5432/ai_newsroom`); there is no production control-plane DB
URL in config, no `.env`, and no SSH / deploy tooling in the repo. The production control-plane
DB lives on the VPS and is reached only through deploy tooling (consistent with the prior
phases' recorded no-SSH constraint).

Per §3's instruction ("Do not assume production state from prior reports"): production
`telegram_news` / `telegram_breaking` / `telegram_data` / `telegram_quote` lifecycle state is
**UNKNOWN** and must be read read-only on the VPS as step 1 of the rollout phase
(`SELECT scope, version, status FROM design_spec_versions ORDER BY scope, version`). Prior-phase
notes *suggested* production is still on v1 for all scopes (the v2 news/breaking activation was
applied to the dev DB only), but that is not relied on here.

## E. Spec semantic review

| format | renderer behaviour | truthful spec (v3/v2 CANDIDATE) |
|---|---|---|
| **NEWS** | `apply_master_news_branding` → `select_master_news_branding()`: one canonical NNJ mark, adaptively placed among 4 bounded safe corners (LOWER_RIGHT→LOWER_LEFT→UPPER_RIGHT→UPPER_LEFT, bottom preferred) by real per-photo edge-density scoring; source fit to 1280×720 (mechanical crop for non-16:9, never AI recompose); no scrim | `{safe_margin_frac:0.019, scrim_treatment:none, source_image_treatment:preserve}` — **no `logo_zone`** (adaptive), no `placement_zone` (pulse fused into the one signature). RenderEvidence reports the actual zone + `source_image_treatment` (preserve / crop). |
| **BREAKING** | identical family to NEWS; retired band / baked wordmark / red rule are gone; bakes no headline text | same as NEWS v3 |
| **DATA — generated hero** | `render_data_hero_card()`: dominant number, red unit, grey secondary, optional red delta pill, optional red trend line plotted verbatim from a real series, technical grid; metric block `upper_left`; **fixed** `lower_right` NNJ mark; no scrim; font-fitted `[88,200]`, label ≤2 lines | governed by `telegram_data` v3's `font_size_min/max` + `max_line_count` + `safe_margin_frac` |
| **DATA — existing infographic** | `MINIMAL_SOURCE_PRESERVING`: source kept, no stat block ("42 stays 42"), adaptive bottom pulse+NNJ signature (`lower_right`/`lower_left`), an occasional guaranteed-branding fallback `strong` scrim on a fully-busy infographic, may crop a non-16:9 source | **not** field-matched on placement/scrim/source (those are mode-dependent); governed by the SOURCE_PRESERVATION dimension (PASS for a source-preserving mode) + the always-on single-NNJ `logo_count>1` hard check. NUMBER_MISMATCH / INFOGRAPHIC_DESTROYED stay hard BLOCK. |
| **QUOTE** | `render_quote_card()`: red quote-mark motif; verbatim font-fitted body; portrait right; author name red; author role grey (drawn only when supplied, never fabricated); **fixed** `lower_right` NNJ mark; portrait pasted at own aspect (no crop); the dark left panel is the card's own ground, not a source scrim | `telegram_quote` v2 `{safe_margin_frac:0.019, logo_zone:lower_right, scrim_treatment:none, source_image_treatment:preserve}` — every field truthful (deterministic mark, `scrim_treatment` recorded not-applicable-with-evidence) |

**`telegram_data` conflates two render contracts** under one scope. A single field-by-field spec
that declared the hero card's `placement_zone: upper_left` / `logo_zone: lower_right` /
`scrim_treatment: none` would be a **falsification of the MINIMAL infographic render** (which is
adaptive on zone and can carry a fallback scrim). The v3 candidate therefore declares only what
is true for **both** modes. The earlier `telegram_data` v2 candidate (which did carry the
hero-only fields) is REJECTED.

## F. Adaptive safe-zone verdict

**`VISUAL_SPEC_SCHEMA_GAP = false`.**

`DeclarativeVisualParameters.logo_zone` is `PlacementZone | None`. `telegram_art_director_spec_evaluation.py::_zone_check()`
**skips the comparison entirely when the field is absent** (`if spec_zone is None: return`). So
**omitting `logo_zone`** is the schema's own neutral/derived mode (§5 option B): a truthful "no
zone constraint — adaptive safe placement" statement, with RenderEvidence carrying the actual
chosen zone for observability. No new schema field, no migration, no ad-hoc SQL. NEWS/BREAKING
v3 omit `logo_zone`; DATA v3 omits it (MINIMAL is adaptive); QUOTE v2 keeps it (deterministic).

## G. Local final replay matrix (`scripts/_visual_spec_vnext_replay.py`)

Each candidate's params evaluated as if ACTIVE (real CANDIDATE rows never change acceptance —
§17), against the real accepted renders + renderer-truthful RenderEvidence:

| render | actual mark zone | SPEC_MATCH | checked fields | merged Art |
|---|---|---|---|---|
| NEWS clean | lower_right | **PASS** | safe_margin_frac, scrim_treatment, source_image_treatment | pass_with_notes |
| NEWS busy-bottom (adaptive) | **upper_right** | **PASS** | same | pass_with_notes |
| BREAKING clean | lower_right | **PASS** | same | pass_with_notes |
| BREAKING busy-bottom (adaptive) | **upper_right** | **PASS** | same | pass_with_notes |
| DATA generated hero | lower_right | **PASS** | font_size, max_line_count, safe_margin_frac | pass_with_notes |
| DATA existing infographic (MINIMAL) | lower_right | **PASS** | max_line_count, safe_margin_frac | pass_with_notes |
| QUOTE full-role | lower_right | **PASS** | safe_margin_frac, logo_zone, source_image_treatment | pass_with_notes |
| QUOTE missing-role fallback | lower_right | **PASS** | same | pass_with_notes |

**No SPEC_MATCH FAIL, no PARTIAL_EVIDENCE, no soft REWORK, no hard failure** against the vNEXT
candidates. §6 satisfied — no soft REWORK remains solely from a stale spec. (Non-16:9 source
note: a NEWS/BREAKING render of a non-16:9 photo produces a truthful `source_image_treatment=crop`
— a mechanical centre-crop, classified **soft**, never `recompose`; pre-existing Founder-approved
semantics, unchanged.)

## H. Art matrix

`evaluate_against_spec_and_references` + `merge_spec_evaluation_into_result` on the same 8 renders:

| format | one NNJ (`logo_count`) | duplicate mark | clipping | fact / number | infographic destroyed | quote attribution | merged |
|---|---|---|---|---|---|---|---|
| NEWS ×2 | 1 | no | no | n/a | n/a | n/a | pass_with_notes |
| BREAKING ×2 | 1 | no | no | n/a | n/a | n/a | pass_with_notes |
| DATA hero | 1 | no | no (`text_clipped=False`) | verbatim | n/a | n/a | pass_with_notes |
| DATA infographic | 1 | no | no (0 stat lines) | verbatim | **no** (SOURCE_PRESERVATION PASS) | n/a | pass_with_notes |
| QUOTE ×2 | 1 | no | no (font-fit) | n/a | n/a | verbatim, role only when supplied | pass_with_notes |

Hard-failure enforcement (BLOCK, never downgraded by an optimistic vision decision) is proven for
the negative cases in `tests/test_founder_visual_board_alignment_1.py` +
`tests/test_design_spec_enforcement.py` + `tests/test_art_director_number_mismatch_blocks.py`:
`NUMBER_MISMATCH` → BLOCK; `EXISTING_INFOGRAPHIC` + non-preserving mode → `INFOGRAPHIC_DESTROYED`
→ BLOCK; `logo_count > 1` → BLOCK; `TEXT_CLIPPING` → BLOCK.

## I. Migration / schema verdict

**No schema change. No migration. No ad-hoc SQL.** All spec changes go through the canonical
registry lifecycle (`create_candidate_spec()` / `reject_candidate()` / — for the rollout —
`promote_candidate()`). `DeclarativeVisualParameters` is unchanged. `VISUAL_SPEC_SCHEMA_GAP = false`.

## J. DB backup

**Not executed** (no production DB access from this environment). The rollout phase must, before
any production spec mutation:

```
pg_dump --format=custom --no-owner --no-privileges \
  "$CONTROL_PLANE_DATABASE_URL" > backup_control_plane_pre_visual_vnext_$(date +%Y%m%dT%H%M%SZ).dump
pg_restore --list backup_control_plane_pre_visual_vnext_*.dump | head   # validate the dump
```

plus a readable export of the four scopes' current rows:

```
psql "$CONTROL_PLANE_DATABASE_URL" -c \
  "\copy (SELECT scope,version,status,parameters,notes,active_from FROM design_spec_versions
          WHERE scope IN ('telegram_news','telegram_breaking','telegram_data','telegram_quote')
          ORDER BY scope,version) TO 'visual_spec_rows_pre_vnext.csv' CSV HEADER"
```

(No secrets in `design_spec_versions`.)

## K. Production activation result — NOT EXECUTED

Production control-plane VisualSpec was **not** mutated. Three independent gates blocked it, any
one of which is sufficient:

1. **No production DB access** from this environment — §8's read-only preflight and §10's fresh
   backup cannot be performed here.
2. **§9 "candidate semantics byte/field-equivalent to reviewed approved specs" is NOT met.**
   `telegram_news` / `telegram_breaking` v3 **drop `logo_zone`** versus the earlier-reviewed
   `telegram_news v2` / `telegram_breaking v2`; `telegram_data` v3 is a further correction of the
   FOUNDER-VISUAL-BOARD-ALIGNMENT-1 data candidate. These are the **truthful consequence of THIS
   phase's Founder adaptive-logo decision**, but they are not the exact specs previously reviewed
   field-for-field, so they need an explicit Founder confirm before production promotion.
3. Mutating the production control-plane DB while the Story Continuity shadow observation is live
   warrants an explicit go on the exact final spec set.

The activation tooling is **prepared and dev-verified**: `scripts/activate_visual_spec_vnext.py`
— idempotent, `--dry-run` (transaction rolled back; verified: dev DB unchanged), a STOP guard if
a scope has no CANDIDATE matching the target params, a post-activation `ACTIVE_COUNT == 1` per
scope re-assertion, and `--print-rollback`.

## L. Production post-state

N/A (not executed). Target lifecycle after the rollout phase's activation:

```
telegram_news     v3 ACTIVE   (v2, v1 -> SUPERSEDED)
telegram_breaking v3 ACTIVE   (v2, v1 -> SUPERSEDED)
telegram_data     v3 ACTIVE   (v1 -> SUPERSEDED)
telegram_quote    v2 ACTIVE   (v1 -> SUPERSEDED)   [no-op if prod v2 params == v1]
```

## M. Rollback proof

- **Dev dry-run:** `python scripts/activate_visual_spec_vnext.py --dry-run` promoted news v3 /
  breaking v3 / data v3 inside a transaction, re-asserted the one-ACTIVE-per-scope invariant, then
  **rolled the transaction back** — dev `design_spec_versions` verified unchanged afterward
  (news/breaking still v2 ACTIVE, data/quote still v1 ACTIVE).
- **Spec-lifecycle rollback:** the registry marks the prior ACTIVE **SUPERSEDED**, never edited
  or deleted. Rollback = clone the SUPERSEDED prior row's params to a fresh CANDIDATE, then
  `promote_candidate()` — `scripts/activate_visual_spec_vnext.py --print-rollback` emits the
  exact per-scope operation.
- **Outer safety net:** `pg_restore` of the pre-mutation `pg_dump` (§J).
- No deletion at any layer.

## N. Runtime service call-path analysis

Transitive import trace from each container entrypoint (`python -c "import <entry>"` then
inspect `sys.modules`):

| service | entrypoint | brand_renderer | nnj_master_news_overlay | presentation_director | render_evidence |
|---|---|---|---|---|---|
| `automation_worker` | `worker.main` | **—** | **—** | **—** | — |
| `content_worker` | `worker.content_main` | **loaded** | loaded | loaded | (lazy, used by Art Director) |
| `news_analysis_worker` | `worker.analysis_main` | — | — | — | — |
| `telegram_bot` | `bot.main` | — | loaded (via `final_post_review_notifier` → `apply_master_news_branding` only) | — | — |

- **`content_worker`** runs `worker/content_cycle.py::run_content_cycle()` → `render_branded_media()`
  (→ `render_data_card` → **`render_data_hero_card`**, **`render_quote_card`**, `render_breaking_frame`)
  and `apply_master_news_branding()`. It is the **sole runtime home** of the new DATA/QUOTE
  renderer code and the new `DataCandidate.series/delta` / `QuoteCandidate.role` fields.
- **`automation_worker`** (the Story Continuity shadow-observation target) loads **none** of the
  visual modules — the new renderer code is genuinely unused there.
- **`telegram_bot`** loads only `nnj_master_news_overlay` (unchanged this lineage) for the Final
  Post Review WYSIWYG preview; it does not import `brand_renderer` / `presentation_director` and
  does not re-render DATA/QUOTE (the media bytes are produced once in `content_worker` and
  forwarded). It does **not** need the new code for the visual changes.

## O. Minimum deployment scope

**`RUNTIME_DEPLOY_SCOPE_REQUIRED = [content_worker]`.**

Explicitly **not** `automation_worker` (Story Continuity), **not** `news_analysis_worker`, **not**
`telegram_bot` (unless a future change touches `nnj_master_news_overlay` or adds a bot-side
DATA/QUOTE re-render). `backend` / `postgres` / `redis` unaffected.

## P. Runtime diff / split-brain risk

The visual branch HEAD `70cbce7` sits on base `c6694b9` (Story-Continuity P0.1 lineage:
`story_identity_guard.py`, entity-tier changes in `story_memory.py`, clustering guards).

- **A. visual runtime changes** — exactly **one** runtime commit vs `c6694b9`: `70cbce7`, which
  touches only `services/brand_renderer.py` (+~215), `services/render_evidence.py` (+73),
  `services/presentation_director.py` (+12). `0175dc3` (the launch-readiness audit) added **zero**
  tracked runtime source. This phase adds **zero** `services/` runtime changes (spec-candidate
  scripts + one test constant only).
- **B. report / docs / tests / scripts** — everything else on the branch.
- **C. unrelated Story Continuity lineage differences** — `c6694b9`'s Story-Continuity P0.1
  changes. `content_worker`'s **current production baseline SHA is UNKNOWN from this environment**
  and must be read on the VPS (`docker exec <content_worker> git rev-parse HEAD`, or the image
  label). If it is **behind `c6694b9`** (e.g. at `d2dea2c`), deploying the raw visual branch to
  `content_worker` would **also** roll it forward through the Story-Continuity P0.1 changes — a
  split-brain risk, and exactly what §13 warns against.

## Q. Recommended clean release strategy

**Do not deploy the raw visual branch to `content_worker`.** Build a rollup release branch:

```
git fetch --all
git switch -c release/visual-vnext-content-worker <CONTENT_WORKER_PROD_SHA>
git checkout 70cbce7 -- services/brand_renderer.py services/render_evidence.py services/presentation_director.py
git commit -m "release(visual-vnext): DATA hero-metric + QUOTE composition renderer onto the content_worker baseline"
```

This carries **only** the three visual `services/` files onto `content_worker`'s own baseline —
no Story-Continuity P0.1 code, no docs/tests/scripts. Tag the currently-running image
(`pre-visual-vnext-content-worker`) for rollback. If `<CONTENT_WORKER_PROD_SHA> == c6694b9`, the
rollup is identical to `70cbce7`'s runtime delta and a direct build of `70cbce7` is also safe;
confirm on the VPS first.

## R. Tests

Run (`-p no:randomly`):

```
tests/test_founder_visual_board_alignment_1.py + test_brand_renderer.py + test_render_evidence_parity.py
  + test_design_spec_enforcement.py + test_design_spec_registry.py + test_v2_10h_master_news_production.py
  + test_visual_renderer_constraints.py + test_presentation_director.py + test_art_director_number_mismatch_blocks.py
  + test_director_control_plane_1a/1b_art_director.py
  -> 240 passed, 1 skipped, 0 failed
full relevant sweep (adds visual_brand_core, news_telegram_presentation x3, content_draft_quote,
  recap_event, event_recap x3)
  -> 500 passed, 4 skipped, 0 failed
```

Covered per §15: vNEXT proposal idempotency (all 3 propose scripts re-run → skip, no new rows);
activation lifecycle (`--dry-run` promote + rollback on dev); one ACTIVE per scope
(post-activation re-assertion in the script + verified in dev); rollback lifecycle
(`--print-rollback`); DATA hero SPEC_MATCH; DATA infographic source-preserve; QUOTE SPEC_MATCH;
NEWS/BREAKING parity; adaptive safe-zone evidence (replay: `logo_zone` reported as the actual
corner, PASS against the zone-less v3); Art enforcement.

- **KNOWN_FAILURES (pre-existing on base `70cbce7`, reproduced on a pristine checkout, unrelated
  to visual specs — this phase touched none of that code):** `tests/test_recap_story_integrity.py`
  ×5 (empty `pair_entity_exclusions` diagnostic; the integrity gate still rejects correctly) and
  `tests/test_presentation_director_mode_contract.py::test_enforce_gate_actually_assigns_every_mutating_target_at_least_once`
  (an AST-parse guard on `worker/content_cycle.py`).
- **NEW_FAILURES: 0** ✅

## S. Static checks

- `services/` (repo-normal mypy scope): `brand_renderer.py`, `render_evidence.py`,
  `presentation_director.py` → **mypy Success, no issues** (unchanged from `70cbce7` — no
  `services/` runtime change this phase).
- `ruff check` on every new / changed file → **All checks passed**.
- `ruff format`: new files formatted; the pre-existing `services/*.py` were already not
  `ruff format`-clean at base (repo has no `[tool.ruff]` config), left as-is; line endings on
  the one edited test file normalised to LF.
- **NEW_STATIC_ERRORS: 0** ✅

## T. Exact next rollout prompt / scope

> **PHASE FOUNDER-VISUAL-VNEXT-PRODUCTION-ROLLOUT-1**
>
> Deploy the DATA hero-metric + QUOTE composition renderer and activate the truthful vNEXT visual
> specs in production. **Minimum scope: `content_worker` only.** Do NOT touch `automation_worker`,
> Story Continuity, Recap generation, or public publication.
>
> 1. **Preflight (read-only):** on the VPS, read `content_worker`'s deployed SHA and
>    `SELECT scope,version,status,parameters FROM design_spec_versions ORDER BY scope,version` on
>    the production control-plane DB. Record PROD_SPEC_STATE.
> 2. **Backup:** `pg_dump --format=custom` of the production control-plane DB + validate with
>    `pg_restore --list` + CSV export of the four visual scopes (commands in
>    `docs/visual_spec_vnext_production_alignment_1_report.md` §J). Tag the running `content_worker`
>    image `pre-visual-vnext-content-worker`.
> 3. **Founder confirm** the exact vNEXT spec set (news v3 / breaking v3 / data v3 / quote v2 —
>    `design/proposed_visual_spec_vnext_production_alignment.md`), specifically the `logo_zone`
>    removal for the adaptive formats.
> 4. **Spec activation:** run `scripts/propose_visual_spec_adaptive_candidates.py` then
>    `scripts/propose_visual_spec_vnext_candidates.py` against the production control-plane DB
>    (creates the CANDIDATE rows idempotently), then `scripts/activate_visual_spec_vnext.py --dry-run`,
>    inspect, then without `--dry-run`. Verify `ACTIVE_COUNT == 1` per scope; no unrelated scope promoted.
> 5. **Runtime deploy:** build the rollup branch `release/visual-vnext-content-worker`
>    (`<CONTENT_WORKER_PROD_SHA>` + the 3 visual `services/` files from `70cbce7` — report §Q),
>    rebuild the `content_worker` image, recreate **only** the `content_worker` container. Do not
>    recreate any other service.
> 6. **Canary + internal validation:** local canary renders (`scripts/_founder_visual_board_alignment_canary.py`,
>    `scripts/_visual_spec_vnext_replay.py`); one internal-only Telegram editorial-channel post per
>    format (NEWS, BREAKING, DATA generated, DATA infographic, QUOTE) via the Final Post Review
>    path — **no public channel send, no publication gate change**.
> 7. **Rollback on any failure:** `pg_restore` the backup (or `activate_visual_spec_vnext.py --print-rollback`
>    then re-promote), redeploy `content_worker` at `pre-visual-vnext-content-worker`.
> 8. Report: PROD_SPEC_STATE pre/post, backup path, deploy SHA, canary results, verdict.

---

## Verdict

- Approved v2/v3 semantics verified against the board and the renderer — **truthful, no schema
  lie** (`VISUAL_SPEC_SCHEMA_GAP = false`).
- Local replay: **8/8 SPEC_MATCH PASS**, zero soft REWORK, zero hard failure, zero Art BLOCK.
- **`RUNTIME_DEPLOY_SCOPE_REQUIRED = [content_worker]`** — proven by import trace;
  `automation_worker` genuinely unaffected.
- Split-brain risk identified; clean rollup-branch release strategy specified.
- **NEW_FAILURES = 0. NEW_STATIC_ERRORS = 0.** No runtime service deployed. Story Continuity
  observation untouched.
- Production control-plane VisualSpec **not** reachable / not mutated this phase; the corrected
  adaptive candidates need an explicit Founder confirm before production promotion.

**VISUAL_SPEC_VNEXT_PROD_ALIGNMENT_PARTIAL**

Do not deploy runtime services. Proceed to FOUNDER-VISUAL-VNEXT-PRODUCTION-ROLLOUT-1 after Founder
confirmation of the vNEXT spec set.
