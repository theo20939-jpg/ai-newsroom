# INSTAGRAM-EXECUTION-FOUNDATION-1 - report

Completes the missing execution foundation identified by
INSTAGRAM-DIRECTOR-STATE-RECONCILIATION-1: the existing Instagram planning/intelligence chain
(Opportunity -> Growth Strategy -> Format Decision -> Creative Director -> `build_shadow_plan()`)
is real and reused unchanged; this phase extends its output into an executable content package,
an Instagram-native renderer, a review/editorial/Art path, and a fully shadow-safe official
publish adapter. **No real Instagram credentials used. No production deployment. No live
Instagram publication. No production DB mutation. Telegram Visual V8 untouched.**

## A. Base SHA

`c2ecc6f` on `feature/launch-readiness-visual-recap-parallel-1`
(INSTAGRAM-DIRECTOR-STATE-RECONCILIATION-1). Isolated worktree
`C:/Users/Theodor/ai-newsroom-ig-exec-1`, branch `feature/instagram-execution-foundation-1`.

## B. Final SHA

The commit carrying this report on `feature/instagram-execution-foundation-1` (parent `c2ecc6f`)
- see `git log`.

## C. Existing architecture reused (section 1)

Reused verbatim, never redesigned:

* `services/instagram_content_opportunity.py::ContentOpportunity` (+ `build_content_opportunity`)
* `services/instagram_objective_selection.py::recommend_objective` -> `ObjectiveRecommendation`
* `services/instagram_format_director.py::evaluate_format_shadow` -> `FormatDecision`,
  `ContentFormat` (SINGLE/CAROUSEL/REEL), `validate_package_claims`/`ClaimViolationError`
* `services/instagram_creative_director.py::CreativeGenerationOutcome` +
  `schemas/instagram_creative.py` (`InstagramSingleCreative`/`InstagramCarouselCreative`/
  `InstagramReelCreative`)
* `services/instagram_shadow_pipeline.py::build_shadow_plan()` -> `ShadowPlanResult` (section 23:
  wired directly into the new `InstagramContentPackage` assembler - see section D)
* `services/instagram_account_reader.py`'s own official architecture (Instagram API with
  Instagram Login, `graph.instagram.com`) - reused as the shape for the NEW publish adapter
  (section L), never replaced with a Facebook-Page-token design
* `services/nnj_master_news_mark.py::rasterize_nnj_mark()` - the canonical NNJ mark, reused
  read-only (never redrawn) for the Instagram brand mark
* `assets/brand/fonts/FiraSansCondensed-*.ttf` (SIL OFL 1.1) - reused read-only, repo-relative

Nothing in `services/instagram_growth_strategist.py`, `services/instagram_content_brain.py`, or
any of the other ~30 Instagram Growth Engine modules was modified.

## D. Execution contract

`services/instagram_content_package.py::InstagramContentPackage` (+ `build_instagram_content_package()`):
a frozen, fully JSON-serializable (`to_dict()`) dataclass built purely from the real upstream
Director objects - `platform`, `account_key` (logical only), `content_format`, `caption` (the
Creative Director's own `caption_direction` for SINGLE/REEL, or the hook slide's copy for
CAROUSEL - always `caption_is_draft=True`, never invented polished prose), `on_image_copy`, `cta`,
`hashtags` (always `[]` - no schema in this codebase produces them, never fabricated),
`media_plan` (format-shaped: asset requirements / slide list / scene sequence),
`external_video_asset_ref` (the ONLY way a REEL carries video), reference-only
`opportunity_id`/`story_id`/`trend_id`/`campaign_id`/`campaign_name`/`campaign_phase` (never a
wholesale CampaignPlan/BusinessContextSnapshot copy), propagated `approved_claims`/
`restricted_claims`/`product_mention_allowed`, `director_evidence` (the real evidence/confidence
trail), and `render_profiles`/`slide_count` (derived, consumed by the renderer). 9 tests in
`tests/test_instagram_content_package.py`.

## E. Format support (section 5)

Source of truth: the existing Director's own `ContentFormat` enum (`services/
instagram_format_director.py`) - `SINGLE`, `CAROUSEL`, `REEL`. There is **no `STORY` format** in
the Director's semantics (`instagram_stories_strategy.py` is a separate, thin, "no publication"
module) - honestly excluded from MVP rather than pretended.

| format | CONTENT_SUPPORTED | RENDER_SUPPORTED | PUBLISH_ADAPTER_SUPPORTED | MVP_INCLUDED |
|---|---|---|---|---|
| FEED_IMAGE (SINGLE) | YES | YES (this phase) | YES (shadow; live gated) | YES - priority 1 |
| CAROUSEL | YES | YES (this phase) | YES (shadow; live gated) | YES - priority 2 |
| REEL | YES | **cover image only** (this phase) - no video generator (section 11/26 explicit instruction) | YES (shadow; live gated) - requires `external_video_asset_ref` | YES - priority 3, cover + external-video-contract only |
| STORY | **NO** - not a Director `ContentFormat` | NO | NO | **NOT_INCLUDED** - no truthful content-planning semantics to build on |

## F. Instagram visual system (section 6)

`services/instagram_visual_profiles.py` - the ONE centralized profile/geometry registry, Instagram's
OWN aspect ratios (never a resized Telegram card):

| profile | dimensions | aspect | safe zones (top / bottom / side) |
|---|---|---|---|
| `PORTRAIT_FEED` | 1080x1350 | 4:5 | 3% / 3% / 5% |
| `SQUARE_FEED` | 1080x1080 | 1:1 | 3% / 3% / 5% (defined, not used by an MVP format this phase) |
| `CAROUSEL_SLIDE` | 1080x1350 | 4:5 | 3% / 3% / 5% - identical to `PORTRAIT_FEED` so every slide in one carousel shares one visual system |
| `REEL_COVER` | 1080x1920 | 9:16 | 14% / 22% / 6% - materially larger, matching the Reels/Stories app-chrome overlay zone |

No Instagram UI chrome (progress bars, account chips, action icons) is ever drawn into the image -
the safe zones exist only so this renderer's own content never collides with Instagram's own
chrome later. `services/instagram_platform_renderer.py`'s own source imports nothing from
`services/brand_renderer.py` / `nnj_master_news_overlay.py` / `nnj_board_metrics.py` /
`render_evidence.py` - verified both by direct `git diff` (section T) and by an AST-based import
check (`test_no_import_of_the_frozen_telegram_v8_renderer`).

Brand rules (section 7) enforced structurally, not by convention: exactly one canonical NNJ mark
per render (`_draw_brand_mark()` called exactly once per composited image; `InstagramArtValidationResult`
hard-blocks 0 or >1); the mark is the SAME `rasterize_nnj_mark()` every other NINJA surface uses,
never regenerated; content is primary (the mark occupies ~9% of canvas width, corner-placed,
safe-zone respecting); typography is deterministic Fira Sans Condensed (Black headline / Medium
secondary), repo-relative, no host font; no Telegram pulse/grid/graph motif appears anywhere in
this renderer.

## G. Render profiles / renderer (sections 8-11)

`services/instagram_platform_renderer.py`:

* `render_instagram_feed_image()` - SINGLE -> one `PORTRAIT_FEED` image. Headline = the Creative
  Director's own `on_image_copy` (never invented) or the caption as fallback.
* `render_instagram_carousel()` - CAROUSEL -> one `CAROUSEL_SLIDE` image per PLANNED slide
  (bounded at 10, Instagram's own platform ceiling - `_MAX_CAROUSEL_SLIDES`), same visual system,
  a small in-frame "N / M" slide indicator (content this renderer draws itself, not Instagram's
  own pagination chrome), one caption/source linkage across the set.
* `render_instagram_reel_cover()` - REEL -> the COVER IMAGE ONLY, never a claim of video
  generation (evidence `notes["video_asset"]` explicitly records `external_video_asset_ref` or
  "NONE - cover image only, no video generated"). No video-generation infrastructure was built
  (section 11's own explicit instruction) - a REEL package without `external_video_asset_ref`
  fails, honestly, at the publish-adapter stage (section L), never silently proceeds.

Deterministic text-fit (`_fit_text`): shrinks font size, then wraps, then (only if it still does
not fit at the minimum size) truncates with an ellipsis and marks the region `clipped=True` - never
silent overflow. A clipped HEADLINE is an Art-validation hard BLOCK; a clipped secondary line is a
warning only (still legible). `InstagramRenderEvidence` (`services/instagram_render_evidence.py`,
a standalone dataclass - NOT a reuse of Telegram's `RenderEvidence`, whose vocabulary encodes
Telegram-corner/placement assumptions) reports canvas size, brand-mark count, every text region +
clip state, source-image treatment, slide index/count, caption linkage (the producing package's
own id), a content-identity hash (of the CONTENT, never pixels), and `render_version`.

10 tests in `tests/test_instagram_platform_renderer.py` - deterministic byte-identical re-renders,
brand-mark invariant, clean-headline-never-clips, extreme-length-headline-clips-with-a-signal,
carousel slide count/consistency, the platform bound, Reel-cover-never-claims-video, and the AST
import-boundary check.

## H. Review package (section 12)

`services/instagram_review_package.py::InstagramReviewPackage` (+ `build_instagram_review_package()`):
assembled purely from already-computed results (never re-derives Director reasoning, never
re-renders) - `director_reasoning_summary` (objective/format/confidence/hook/why/evidence, all
real), `campaign_context`, `source_refs`, `media_render_evidence` (one entry per rendered asset,
slide-ordered), `art_validation`, `risk_warnings`, `validation_failures`, `publish_ready`. Fully
JSON-serializable. 2 tests in `tests/test_instagram_review_package.py`.

## I. Editorial integration (section 13)

`services/instagram_editorial_gate.py::evaluate_instagram_editorial_gate()` -> `InstagramGateDecision`
(`READY_FOR_EDITOR` / `HOLD` / `BLOCK`) - a NEW, Instagram-native gate, deliberately NOT a reuse of
`services/director_editorial_gate.py::EditorialGateInput` (that contract's `story_facts_summary` /
`is_potential_breaking` / `feed_topic_distribution` fields are News-ingestion-shaped, not a Growth
creative-package concept - section 13's own explicit instruction). It DOES reuse the one genuinely
platform-neutral piece that already existed: `services/instagram_format_director.py::
validate_package_claims()` / `ClaimViolationError` for restricted-claim re-checking.

Routing, in order: Art validation failure -> BLOCK; restricted-claim violation across every
free-text field (`InstagramContentPackage.text_fields_for_claim_check`) -> BLOCK; a disallowed
product mention -> BLOCK; `launch_state in (pre_launch, transition)` -> HOLD (content is safe, only
timing is uncertain - never auto-blocked for that reason); otherwise READY_FOR_EDITOR (non-blocking
Art warnings are disclosed, not gated). `InstagramGateOutcome.permits_publication` is the ONE
predicate the publish adapter checks (section L) - BLOCK/HOLD never reach it. 8 tests in
`tests/test_instagram_editorial_gate_routing.py`.

## J. Art integration (section 14)

`services/instagram_art_validator.py::validate_instagram_art()` -> `InstagramArtValidationResult`.
Instagram never passes through `services/telegram_art_director*.py` (confirmed Telegram-only in
the prior audit; unchanged here). Checks, all structural/deterministic (no vision-model call, no
autonomous redesign loop): correct format/canvas per profile; brand-mark count == 1 (0 or >1 both
BLOCK); headline text overflow (BLOCK) vs secondary text overflow (warning only); empty/missing
media (BLOCK); unreadable/no-text-region content (BLOCK); source-image treatment (disclosed,
not-yet-applicable - this renderer never composites a source photo); caption/media package-linkage
consistency (BLOCK on mismatch); carousel slide-count/index consistency (BLOCK on mismatch). A
bounded re-render hook (`attempt_bounded_rerender`, `MAX_ART_RERENDER_ATTEMPTS = 1`) exists but
never loops on its own - with no caller-supplied `revise_fn` it is exactly one attempt, fail-soft,
editor-visible; with a revision strategy supplied it retries at most the explicit bound, never
unbounded. 11 tests in `tests/test_instagram_art_validator.py`.

## K. VisualSpec / evidence (section 15)

`services/instagram_visual_spec.py::InstagramVisualSpec` (+ `default_instagram_visual_spec()`) - a
plain, LOCAL, non-persisted dataclass, deliberately NOT a `database/models/design_spec_version.py::
DesignSpecVersion` row and NOT an extension of `schemas/declarative_visual_parameters.py`
(Telegram's own production VisualSpec schema/registry - `design_spec_registry.py` creates only
`telegram_*` scopes; this phase creates none, activates nothing). `platform` is always
`"instagram"`; canvas geometry comes directly from `services/instagram_visual_profiles.py` (no
borrowed Telegram 16:9/4:5 assumption - it IS 4:5 for feed/carousel, but because that is
Instagram's own recommended feed ratio, independently derived, not copied from Telegram).
`matches_evidence()` only asserts what the renderer can truthfully measure - no fake hard
constraint like an exact text-region count.

## L. Official publish adapter (section 16)

`services/instagram_publish_adapter.py`. Uses the SAME official architecture
`services/instagram_account_reader.py` already established - Instagram API with Instagram Login,
`graph.instagram.com` - never the Facebook-Page-token architecture. Models the real Graph API
media-publish flow: `POST {ig_user_id}/media` (container create, `image_url`/`video_url`,
`is_carousel_item` for CAROUSEL children, `media_type=CAROUSEL`/`REELS` where applicable) ->
`GET {container_id}?fields=status_code` (bounded poll, `_MAX_STATUS_POLLS = 5`, capped backoff) ->
`POST {ig_user_id}/media_publish` (`creation_id`).

`HttpInstagramPublishClient` is the REAL adapter (present, complete, real `httpx` calls, the SAME
timeout/error-mapping discipline as the reader) - **never instantiated by any test or by the
canary in this phase.** `ShadowInstagramPublishClient` implements the identical
`InstagramPublishClient` Protocol deterministically, in memory, with configurable poll-count
simulation - the orchestration function (`publish_instagram_content()`) is IDENTICAL for shadow and
(future) live; only the injected client differs.

## M. Write-scope requirements (section 17)

Kept explicitly separate from the reader's read scopes:

    READ_SCOPES  (unchanged, services/instagram_account_reader.py): instagram_business_basic,
                 instagram_business_manage_insights (optional, probe-detected)
    WRITE_SCOPES (new, settings.instagram_write_scopes, documented not requested):
                 instagram_business_content_publish

No live OAuth flow requests the write scope; no code silently adds it to the read path.

## N. Publication safety flag (section 18)

`core/config.py::instagram_publication_enabled: bool = False` (additive only - `git diff` shows 15
insertions, 0 deletions in `core/config.py`). `publish_instagram_content()` fails CLOSED, in order,
before ANY client call: (1) `InstagramGateOutcome.permits_publication` must be True; (2) for a LIVE
(`shadow=False`) attempt, `settings.instagram_publication_enabled` must be True AND the caller must
pass `editor_approved=True` - missing either returns `PublicationStatus.BLOCKED` with no client
call at all; (3) shadow publish (`shadow=True`) always works, regardless of the flag, for testing/
simulation. Two PRE-EXISTING tests (`test_instagram_growth_engine_foundation.py::
test_no_publication_flag_exists_at_all`, `test_instagram_safety.py::test_all_new_feature_flags_default_false`)
asserted the OLD invariant "no publication flag exists at all" - both were updated (section R) to
the current, correct invariant: the flag now exists BY DESIGN as the hard-disabled safety gate
itself, still defaults False, and `instagram_ad_spend_enabled` still does not exist (unaffected,
out of scope).

## O. Shadow publish (section 19)

`ShadowInstagramPublishClient` never imports or calls `httpx` - a full shadow publish (container
create -> poll -> publish, single/carousel/reel) is provably network-free
(`test_zero_real_network_writes_in_shadow_mode` monkeypatches `httpx.AsyncClient.post`/`.get` to
raise `AssertionError` on any call, then runs a full shadow publish successfully).
**`SHADOW_INSTAGRAM_PUBLISH_NETWORK_WRITES = 0`** (verified, not assumed). Every shadow result is
logged via `services/instagram_publication_audit.py::append_publication_audit_record()` (see
section P).

## P. Persistence decision (section 22)

Inspected the existing 10 Instagram/Social DB models. **No migration was created.**
`database/models/instagram_calendar_item.py::InstagramContentCalendarItem` is scheduling metadata
with no container/media-id/publish-status/shadow-marker field at all; `database/models/
instagram_creative_plan.py::InstagramCreativeDraft.payload` stores the CREATIVE CONTENT proposal
(a `SinglePostPackage`/`CarouselPackage`/`ReelPackage`-shaped dict), not a publish attempt/result.
Neither table can truthfully represent a `PublicationResult` (container ids, publish status,
retryability, shadow/live marker) without adding fields it was never designed for.

Instead: `services/instagram_publication_audit.py::append_publication_audit_record()` provides a
deterministic, dependency-free, append-only JSON-lines audit log
(`artifacts/instagram_execution_foundation_1/*_publication_audit.jsonl` for the canary; the default
path is `artifacts/instagram_execution_foundation_1/publication_audit.jsonl`) - works everywhere,
fully testable, satisfies section 19's "persist/log intended publication result if architecture
supports it" without a schema change.

**Proposed future migration (documented, NOT created, NOT applied - `alembic heads` in this
worktree is unchanged at `4a1b7c9d2e3f`):** a new `instagram_publication_records` table shaped
directly after `PublicationResult.to_dict()` - `id`, `platform`, `account_key`, `package_id`,
`content_format`, `status`, `shadow` (bool), `container_ids` (JSON list), `media_id` (nullable),
`failure_class` (nullable), `retryable` (bool), `attempts_used` (int), `requested_at`,
`completed_at` (nullable), all additive/nullable-safe. Deferred to a future phase (Phase 2/3, once
DB-backed publication history is actually needed for live operation) rather than created
speculatively now.

## Q. Director handoff (section 23)

`services/instagram_shadow_pipeline.py::build_shadow_plan()` is called UNCHANGED and its
`ShadowPlanResult` is threaded directly into `build_instagram_content_package()` (section D) -
verified end-to-end in the canary (section T) and in `tests/test_instagram_execution_e2e_shadow.py`.
Remains on-demand/shadow; **no autonomous scheduler was added** (section 24 - explicitly deferred
to a future Phase 2, per this phase's own instruction).

## R. Tests (section 27)

New: 58 tests across 7 files (`test_instagram_content_package.py` 9,
`test_instagram_platform_renderer.py` 10, `test_instagram_art_validator.py` 11,
`test_instagram_review_package.py` 2, `test_instagram_editorial_gate_routing.py` 8,
`test_instagram_publish_adapter.py` 17, `test_instagram_execution_e2e_shadow.py` 2 - includes the
required success/container-creation-failure/processing-timeout/publish-failure/invalid-media/
auth-error/rate-limit/retryable-server-error matrix, the publication-flag-OFF and BLOCK/HOLD
fail-closed cases, and the zero-real-network-writes proof).

Updated (2 pre-existing tests, both now reflect the corrected, current invariant - see section N):
`test_instagram_growth_engine_foundation.py` (renamed `test_no_publication_flag_exists_at_all` ->
`test_no_ad_spend_flag_exists_at_all` + added
`test_instagram_publication_flag_defaults_false_and_gates_real_writes`),
`test_instagram_safety.py::test_all_new_feature_flags_default_false`.

Existing suites re-run (Instagram: 35 files; Growth/Social Integration/Campaign/Director/Art/
Presentation/Control Plane: 29 files), combined with the 58 new tests in one final sweep (71
files total):

    555 passed, 2 failed in 135.94s

**NEW_FAILURES = 0** - the only 2 residual failures
(`test_director_console_service.py::test_no_campaign_no_story_notes_are_honest`,
`test_presentation_director_mode_contract.py::test_enforce_gate_actually_assigns_every_mutating_target_at_least_once`)
reproduce identically on the clean base `c2ecc6f` (`git stash` verified) - the same test-isolation
gap and pre-existing stale contract test the prior audit phase already recorded.

## S. Static checks (section 28)

`ruff check` on every new/changed `.py` file (11 `services/`, 1 `core/config.py`, 9 `tests/`, 1
`scripts/`): clean. `mypy` on every new/changed `services/`/`core/` file (11 files): clean.
**NEW_STATIC_ERRORS = 0.**

## T. End-to-end shadow canary (section 29)

`tests/test_instagram_execution_e2e_shadow.py::test_end_to_end_instagram_shadow_execution` - the
FULL chain, offline: synthetic `ContentOpportunity` -> `recommend_objective()` (real Objective
Director) -> `evaluate_format_shadow()` (real Format Director) -> a FIXTURE
`CreativeGenerationOutcome` (no live AI Gateway call in a test) -> `build_shadow_plan()` (real,
unchanged) -> `InstagramContentPackage` -> `render_instagram_feed_image()` -> `InstagramReviewPackage`
-> `validate_instagram_art()` + `evaluate_instagram_editorial_gate()` -> shadow
`publish_instagram_content()` -> `PublicationResult` + audit record. A second test
(`test_end_to_end_shadow_execution_makes_zero_real_network_writes`) monkeypatches `httpx` to raise
on any call and re-runs the same chain successfully.

    END_TO_END_INSTAGRAM_SHADOW_EXECUTION = PASS
    REAL_NETWORK_WRITES = 0

`scripts/_instagram_execution_foundation_1_canary.py` runs the same chain for all three MVP
formats (FEED_IMAGE, CAROUSEL x4 slides, REEL cover) and writes the review package (section U).

## U. Generated review assets (section 30)

`artifacts/instagram_execution_foundation_1/` (local only, nothing published):

    01_feed.jpg / 01_feed_shadow_plan.txt / 01_feed_review_package.json / 01_feed_publication_audit.jsonl
    02_carousel_slide{0,1,2,3}.jpg / 02_carousel_shadow_plan.txt / 02_carousel_review_package.json / 02_carousel_publication_audit.jsonl
    03_reel_cover.jpg / 03_reel_cover_shadow_plan.txt / 03_reel_cover_review_package.json / 03_reel_cover_publication_audit.jsonl

All three formats: `gate=ready_for_editor`, `art_passed=True`, `publish=shadow_success`. No secret
appears in any artifact (shadow container/media ids are content hashes, never real Meta ids).
Total size ~390KB.

## V. Remaining credential blockers

Unchanged from the prior audit - this phase required none of them and used none:

* Real `instagram_access_token` / `instagram_business_account_id` (both still unset in this
  environment - `OPERATOR_CREDENTIAL_GAP`).
* A real Meta App with the Instagram Login product configured, and a linked Business/Creator
  account (`META_APP_CONFIGURATION_GAP` / `ACCOUNT_REQUIREMENT_GAP`).
* App Review for the `instagram_business_manage_insights` scope (unaffected by this phase - no
  new read scope requested) and, for a FUTURE live-write phase, for
  `instagram_business_content_publish` (documented in section M, never requested here).

## W. Remaining Phase 2 work

Not started, per this phase's own explicit boundary (sections 24-25):

* Autonomous Instagram scheduling entrypoint (a `worker/`-level cycle akin to
  `worker/content_cycle.py`'s Telegram Channel Director wiring).
* Instagram performance collector (mirror `services/telegram_performance_collection.py`'s
  passive-only, flag-gated pattern) - feeds Growth Autopsy/Experiments, which today are
  structurally starved of real evidence.
* Live validation against a real connected account (Phase 3 in the prior audit's recommended
  sequence) - requires real credentials and Founder authorization; the publish adapter is ready
  for this (flag flip + `HttpInstagramPublishClient` + `editor_approved=True`) but nothing in this
  phase enables it.
* `services/telegram_strategy_director.py` remains flag-disabled with no call site - documented
  as separate Director cleanup/debt (section 25), NOT touched by this phase.
* The proposed `instagram_publication_records` migration (section P) - deferred until DB-backed
  publication history is actually needed.

---

`INSTAGRAM_EXECUTION_FOUNDATION_PASS`

Existing Director planning chain reaches an executable package; an Instagram-specific renderer
exists (feed/carousel/Reel-cover, its own geometry, brand rules, deterministic typography); a real
review package exists; platform-aware Art + editorial validation exist; the official publish
adapter exists (real architecture, hard-disabled by default); live publishing is fail-closed;
the complete shadow publish path works end-to-end with zero network writes; no real Instagram
credential was used or required; tests/static clean (`NEW_FAILURES = 0`, `NEW_STATIC_ERRORS = 0`);
Telegram V8 unchanged (`TELEGRAM_V8_RUNTIME_CHANGED = false`); no production mutation.
