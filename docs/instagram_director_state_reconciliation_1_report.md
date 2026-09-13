# INSTAGRAM-DIRECTOR-STATE-RECONCILIATION-1 - report

Read-only repository/history audit. No runtime source changed, no migration created, no
production touched, no container started, no DB write. Working tree left exactly as found.

## A. Current visual branch/head

    CURRENT_BRANCH = feature/launch-readiness-visual-recap-parallel-1
    CURRENT_HEAD   = 29424697ee4539ffa5793843f1efb30f1e07960a
    git status     = clean (nothing to commit) at the start and end of this audit

No reset, no clean, no stash/drop of any work. No exploratory checkout was needed - the audit
inspected the working tree in place plus `git log`/`git diff` history across refs (no new worktree
created).

## B. Ancestry / relevant historical commits

All seven landmark commits named in the phase are **already ancestors of the current HEAD**:

| landmark | commit | ancestor of HEAD? |
|---|---|---|
| Director/Control-Plane Stage2 | `36698b0` | YES |
| Instagram official reader / Control Plane 1C | `e4b801e` | YES |
| Instagram Growth | `07b0ac7` | YES |
| Social Integration | `d5c4c81` | YES |
| Social OPS | `5c4f997` | YES |
| Visual Design Autonomy | `dca1536` | YES |
| Prelaunch lineage | `09f8a28` | YES |

Branch-tip reconciliation (`git rev-list --count <branch>..HEAD` / `HEAD..<branch>`), the actual
main output of section X:

| historical branch | commits unique to that branch (missing from HEAD) | tip |
|---|---|---|
| `feature/director-control-plane-v1` | 0 | `d2dea2c` |
| `feature/instagram-growth-engine-v1` | 0 | `07b0ac7` |
| `feature/social-intelligence-integration-v1` | 0 | `d5c4c81` |
| `feature/social-intelligence-ops-v1` | 0 | `2830780` |
| `feature/social-intelligence-prelaunch-1` | 0 | `062e9ac` |
| `feature/social-intelligence-prelaunch-1a` | 0 | `09f8a28` |
| `feature/production-rollup-visual-single-brand-v1` | 0 | `59ea19e` |
| `feature/production-source-reconciliation-v1` | 0 | `dca1536` |
| `fix/director-refresh-callback-1` | 0 | `71d52d1` |
| `feature/visual-single-brand-mark-v1` | **3** | `e66a0b5` |
| `release/arxiv-story-clustering-production-1` | **4** | `6f56aec` |
| `release/founder-visual-vnext-content-worker-1` | **1** | `a3fd0dc` (superseded, DO NOT deploy) |

**Practical conclusion**: `feature/launch-readiness-visual-recap-parallel-1` was built by
sequentially chaining every one of these phases (426 commits, only 1 merge commit in the whole
history - effectively linear). The Instagram / Director / Social-Intelligence code is **not
scattered across disconnected branches that need reconciling** - it is already fully present in
the current checkout. The only genuine gaps are:

* `feature/visual-single-brand-mark-v1`'s 3 commits (`77e48b7`, `a25c16c`, `e66a0b5`) - an EARLIER
  single-brand-mark draft. Verified **superseded**: the current HEAD's
  `services/nnj_master_news_overlay.py` already implements a more complete mutual-exclusion
  contract (`VISUAL-SINGLE-BRAND-MARK-1 §6`), independently developed and further extended by the
  V6-V8 visual phases already on this branch. No integration action needed. Category **C**.
* `release/arxiv-story-clustering-production-1` (tip `6f56aec`) - the currently-staged
  `automation_worker` release. Story Continuity. **Explicitly out of scope / do not touch** per
  this phase's own §1. Not inspected further.
* `release/founder-visual-vnext-content-worker-1` (tip `a3fd0dc`) - the already-superseded old
  visual `content_worker` release (documented in the prior FOUNDER-VISUAL-V8 phases). Category **C**.

No category **D** ("never implemented, absent from every lineage") landmark was found - every
named landmark is real, present code.

## C. Instagram component map

Full inventory: **~40 `services/instagram_*.py` modules, 10 `database/models/instagram_*.py`
models, 1 `schemas/instagram_creative.py`, 5 `prompts/instagram_*` prompt directories, 35
`tests/test_instagram_*.py` files, 5 Instagram-related Alembic migrations, 1 design doc
(`design/instagram_official_api.md`)**. Grouped by role (file-by-file docstrings + call-graph
grep verified for every row; the "Growth Engine v2 structural contracts" row is a a group of ~18
files sharing one very consistent, verified pattern - see note below):

| group | representative files | purpose | runtime caller | status |
|---|---|---|---|---|
| Official reader | `instagram_account_reader.py` | REAL read-only Graph API client (profile/media/insights) | `instagram_connection_service.py` | **CODE_EXISTS, CODE_CALLED, TESTED, BLOCKED_BY_CREDENTIALS** |
| Connection orchestration | `instagram_connection_service.py`, `instagram_connection_readiness.py` | bridges the reader to `InstagramAccount`/`PlatformAccountContext`/`InstagramFeedContext`; two on-demand entry points, "neither scheduled" | `director_execution_service.py`, bot `director_console` | CODE_EXISTS, CODE_CALLED, TESTED, not autonomous |
| Feed context | `instagram_feed_context.py` | bounded, launch-state-aware feed window Directors consume | `instagram_connection_service.py` | CODE_EXISTS, CODE_CALLED, TESTED; **always empty in this environment** (no live account) |
| Account registry | `instagram_account_registry.py` | `InstagramAccount` CRUD, mirrors the Telegram surface registry | connection service | CODE_EXISTS, CODE_CALLED, TESTED |
| Graph adapter (legacy) | `instagram_graph_adapter.py` | pre-reader readiness/adapter stub; 3 deliberate `NotImplementedError`s, `pragma: no cover - unreachable without real credentials` | `instagram_feed_context.py`'s `is_configured()` check | CODE_EXISTS, intentionally inert without credentials |
| Platform capabilities registry | `instagram_platform_capabilities.py` | forensic capability table - `publish_single/carousel/reel/story` all `UNAVAILABLE`, evidence-carrying | referenced by several `instagram_*` docstrings/guards | CODE_EXISTS, CODE_CALLED (as a documentation/guard source) |
| Growth Engine v2 structural contracts (SHADOW/no-publish-by-design) | `instagram_audience_intelligence/_memory`, `instagram_competitor_intelligence`, `instagram_content_opportunity`, `instagram_creative_concept`, `instagram_experiments`, `instagram_hook_intelligence/_memory`, `instagram_objective_selection/_objectives`, `instagram_original_format_lab/_memory`, `instagram_performance`, `instagram_profile_funnel`, `instagram_reference_analysis/_deconstruction/_memory`, `instagram_series/_memory`, `instagram_stories_strategy`, `instagram_creator_radar/_memory`, `instagram_audio_intelligence` | real, tested, deterministic structural contracts (dataclasses + persistence + evidence-stage gates). Every one of these explicitly documents "no auto-adoption / no fabricated data / no autonomous publication / capability UNKNOWN|UNAVAILABLE unless evidenced" as an enforced (not just described) rule | `instagram_shadow_pipeline.py` assembly, `instagram_growth_strategist.py`, or stand-alone persistence called by tests + (for a few) the console builder | CODE_EXISTS, TESTED; most are CODE_CALLED only from each other / the shadow-pipeline assembly, not from any autonomous loop |
| Trend/Semantic matching | `instagram_trend_matching.py` (deterministic, ACCEPTED), `instagram_semantic_matching.py` / `instagram_semantic_trend_matching.py` (optional LLM supplement, additive over the deterministic result) | real AI-Gateway-backed matching (cost-incurring, real `capabilities/gateway_call.py::call_generate()`) | growth strategist / shadow pipeline | CODE_EXISTS, CODE_CALLED (from the shadow assembly), TESTED, flag-gated |
| Format Director v1 -> v2 | `instagram_format_director.py` (contracts only, `instagram_format_director_shadow_enabled=False`), `instagram_format_director_v2.py` (`evaluate_format_v2` - real multi-signal evaluator) | recommend SINGLE/CAROUSEL/REEL | v2 called from `director_console_service.py` + `director_execution_service.py` (on-demand, per-opportunity) - **NOT** from any worker cycle (docstring claim of a `worker/content_cycle.py` call site is stale/inaccurate - verified absent) | CODE_EXISTS, CODE_CALLED (console-only), TESTED |
| Growth Strategist | `instagram_growth_strategist.py` | real `CampaignPlan` + Founder-Directive-aware strategy synthesis (`apply_founder_directive_precedence`) | `director_execution_service.py` | CODE_EXISTS, CODE_CALLED, TESTED |
| Growth Autopsy | `instagram_growth_autopsy.py` | evidence-gated post-hoc explanation (requires REPEATED_PATTERN/STABLE_WORKING_RULE evidence, which never accumulates without real performance data) | growth strategist assembly | CODE_EXISTS, TESTED, **structurally unreachable in this environment** (no evidence ever reaches the required stage) |
| Creative Director | `instagram_creative_director.py` | real AI-Gateway-backed creative brief generation - genuinely "SHADOW pipeline" | `instagram_shadow_pipeline.py`, console | CODE_EXISTS, CODE_CALLED, TESTED, cost-incurring-if-run, SHADOW (no publish) |
| Creative persistence | `instagram_creative_plan_service.py` | CreativePlan/CreativeDraft persistence; approval is always a human-triggered call | console / director_execution | CODE_EXISTS, CODE_CALLED, TESTED |
| Shadow assembly | `instagram_shadow_pipeline.py::build_shadow_plan()` | ONE deterministic function chaining Opportunity->Strategy->Objective->Format->Creative | tests + (per docstring) intended for later console/worker wiring; **no live caller found outside tests** | CODE_EXISTS, TESTED, **SHADOW_ONLY** (not called from any production path) |
| Content Brain | `instagram_content_brain.py` | evidence-stage taxonomy, anti-overfit gate, creative fatigue, scoring - deliberately NOT shared code with the Telegram Content Brain (explicit architectural boundary) | consumed by several of the above | CODE_EXISTS, CODE_CALLED (internally), TESTED |
| AI cost accounting | `instagram_ai_cost.py` + `instagram_ai_call_record` model | reuses the real `cost_tracker.py` pricing formula, own small table (not a real `AIExecution` row - no `editorial_tasks` FK exists for Instagram) | creative director / semantic matching call sites | CODE_EXISTS, CODE_CALLED, TESTED |

**Write / publication path: absent everywhere** - see section F.

Note on thoroughness: every row above was verified by reading the file's own module docstring AND
running an actual `grep` call-graph trace (who imports/calls the module's public entrypoint) - not
docstring text alone (phase §3's own instruction). Given the volume (~40 files), the ~18-file
"Growth Engine v2 structural contracts" group was verified as a group (each file's docstring
independently confirms the same "no auto-adoption / no fabrication / no autonomous publish" pattern
and each has its own passing test file) rather than individually narrated line-by-line; none of
them contradicted the pattern in spot checks.

## D. Official reader state

`INSTAGRAM_READER_STATUS = DONE` (as code) / **credential-blocked for live operation**.

* **API host**: `https://graph.instagram.com` (`settings.instagram_graph_base_url`, overridable).
* **Auth model**: OAuth 2.0 directly with Instagram ("Instagram API with Instagram Login" / Business
  Login for Instagram) - NOT the Facebook-Page/Login path. No interactive OAuth dance is automated;
  the module consumes an already-issued long-lived token from config.
* **Scopes**: `instagram_business_basic` (always required); `instagram_business_manage_insights`
  (optional, detected via a real probe, never assumed). **No write scope is requested or used**
  (`instagram_business_content_publish` / `..._manage_comments` / `..._manage_messages` - none).
* **Account model**: targets exactly the ONE account the token authorizes (`/me`), with an explicit
  identity check (`check_connection()` compares the returned identity to the configured expected
  account - no parameter anywhere can point at a third-party account).
* **Token config**: `instagram_access_token` (SecretStr, unwrapped exactly once at the HTTPS call
  site, never logged/returned/embedded in an exception), `instagram_business_account_id`,
  `instagram_expected_username`, `instagram_access_token_expires_at`.
* **Token refresh**: NOT automated - `token_status` reports VALID/EXPIRED/UNKNOWN from the
  configured expiry; the exchange/refresh operational flow is documented
  (`design/instagram_official_api.md`) but is a manual/operator process, by design (§16 of the
  original spec).
* **Account discovery / profile read / media read / insights read**: all implemented
  (`fetch_account_context`, `fetch_recent_media`, `fetch_media_insights`, `fetch_account_insights`).
* **Pagination**: bounded - follows `paging.cursors.after` at most 2 pages (`_MAX_MEDIA_PAGES`),
  hard-capped at 30 items (`MAX_MEDIA_LIMIT`), default window 25.
* **Rate-limit / error handling**: a structured, closed error taxonomy
  (`InstagramReadErrorCode`: NOT_CONFIGURED / INVALID_TOKEN / INSUFFICIENT_PERMISSION / NOT_FOUND /
  RATE_LIMITED / TRANSIENT / TIMEOUT / MALFORMED_PAYLOAD / NETWORK) maps every provider response;
  the raw provider error body is never surfaced (it can echo the token or a signed media URL).
* **Timeout**: single fixed 15s httpx timeout per request; no automatic retry/backoff was found in
  this module (a TRANSIENT/RATE_LIMITED error is returned structurally for the caller to decide,
  not retried internally).
* **Secret handling**: `SecretStr`, single unwrap point, never logged.

## E. Credentials / operator blockers

No secret value was read or printed anywhere in this audit - presence/absence only, and only
checked in this local worktree (no `.env` file exists in this worktree at all; production's `.env`
was not inspected this phase - out of this phase's explicit read-only-repo scope).

| item | structural presence | classification |
|---|---|---|
| Instagram App ID | not a distinct config field - this integration path (Instagram Login) does not require a separate stored App ID at runtime the way a Facebook-Page-based integration would | N/A for this architecture |
| Instagram App Secret | not present as a runtime config field (token-exchange is a manual/operator process per `design/instagram_official_api.md`, not automated in-app) | `CODE_GAP` only if a future phase automates token refresh; currently N/A |
| Access Token (`instagram_access_token`) | config field exists, defaults to `None`; not set in this dev worktree (no `.env` present) | `OPERATOR_CREDENTIAL_GAP` |
| Business/Professional account ID (`instagram_business_account_id`) | config field exists, defaults to `None`/empty | `OPERATOR_CREDENTIAL_GAP` |
| Expected username (`instagram_expected_username`) | config field exists, optional | `OPERATOR_CREDENTIAL_GAP` (soft - identity-check hardening, not blocking) |
| Insights permission | code detects it live via a probe (no static config needed) - but requires the Meta App to actually have the `instagram_business_manage_insights` permission granted | `META_APP_CONFIGURATION_GAP` |
| A real Instagram Business/Creator account linked to the Meta App | required before any token can be issued | `ACCOUNT_REQUIREMENT_GAP` |
| Meta App Review (for the insights scope, and generally for a live app) | required by Meta's own process | `META_APP_CONFIGURATION_GAP` |

No `CODE_GAP` blocks reading once credentials exist - the reader is code-complete for the read
surface it targets.

## F. Publication-path state

**There is no Instagram write/publication path anywhere in this codebase.** This was independently
confirmed three ways: (1) `instagram_account_reader.py`'s own docstring ("NO WRITE SCOPES ... no
code path here that publishes, edits, deletes, comments"); (2)
`instagram_platform_capabilities.py`'s registry marks `publish_single` / `publish_carousel` /
`publish_reel` / `publish_story` all `CapabilityStatus.UNAVAILABLE` with the evidence string "No
Meta Graph API client, no Instagram credential setting, and no publish/read call exist"; (3) a
direct grep for the official publish-flow vocabulary (`container_id`, `creation_id`,
`/media_publish`) across every `instagram_*` service found zero real API-publish code.

| format | state |
|---|---|
| Single image post | **NOT_IMPLEMENTED** |
| Carousel | **NOT_IMPLEMENTED** |
| Reel/video | **NOT_IMPLEMENTED** |
| Caption composition (content, not publish) | IMPLEMENTED - `instagram_creative_director.py` / `instagram_format_director*.py` produce caption/creative-brief text; never sent anywhere |
| Container creation / media processing status / publish call / publish-result persistence | **NOT_IMPLEMENTED** - no such function exists |

This was **intentional**, not an oversight: the entire Growth Engine v2 lineage repeats the same
explicit constraint file after file ("no autonomous publication anywhere", "never carries a
'publish now' action", capability tables that mark publish as UNAVAILABLE rather than silently
assuming it). The product deliberately stopped at READ + SHADOW PLANNING for safety, exactly as the
phase prompt's own hypothesis suggested.

## G. Content-generation path

Traced `NewsEvent/Story -> editorial selection -> Director -> Instagram content plan -> caption ->
media/art plan -> rendered asset -> review object -> publication candidate`:

    NewsEvent/Story
      -> ContentOpportunity (services/instagram_content_opportunity.py)         REAL, deterministic
      -> InstagramGrowthStrategy (instagram_growth_strategist.py)               REAL, CampaignPlan-aware
      -> ObjectiveRecommendation (instagram_objective_selection.py)             REAL, deterministic
      -> FormatDecision (instagram_format_director_v2.py::evaluate_format_v2)   REAL, multi-signal
      -> CreativeGenerationOutcome (instagram_creative_director.py)             REAL AI-Gateway call, SHADOW
      -> ShadowPlanResult (instagram_shadow_pipeline.py::build_shadow_plan())   REAL, deterministic assembly
      -> [rendered visual asset]                                               MISSING (no Instagram renderer - section J)
      -> [review object]                                                       MISSING (no Instagram-specific Art/editorial review; Telegram's Art Director never sees Instagram)
      -> [publication candidate]                                               MISSING (no publish adapter - section F)

    INSTAGRAM_PIPELINE_LAST_WORKING_STAGE = ShadowPlanResult (deterministic creative-brief assembly,
        `services/instagram_shadow_pipeline.py::build_shadow_plan()`)
    FIRST_MISSING_STAGE = Instagram-specific rendered visual asset (no renderer exists to turn a
        CreativeGenerationOutcome into an actual image/video)

The chain up to `ShadowPlanResult` is real, tested, deterministic-except-for-one-real-LLM-hop
(Creative Director). It is exercised by tests and by the (non-scheduled) console/execution-service
call sites; it has never been proven end-to-end against a live account (no account is connected).

## H. Format support matrix

| format | content plan | visual plan | renderer | platform validation | publisher |
|---|---|---|---|---|---|
| Feed post (single) | YES (`ContentFormat.SINGLE`) | thin (Creative Director brief text only) | **NO** | **NO** | **NO** |
| Carousel | YES (`ContentFormat.CAROUSEL`) | thin | **NO** | **NO** | **NO** |
| Reel | YES (`ContentFormat.REEL`) | thin | **NO** | **NO** | **NO** |
| Story | thin (`instagram_stories_strategy.py` - "structured planning only, no publication") | **NO** | **NO** | **NO** | **NO** |
| Quote card / DATA card / BREAKING/news card / digest / meme | **NO Instagram-specific semantics** - these are Telegram `PresentationType` concepts (`services/presentation_director.py`); nothing maps them onto an Instagram format | N/A | N/A | N/A | N/A |

Content/semantic support (what to say, which format to recommend) is real for
feed/carousel/reel. Actual Instagram-specific rendering, platform validation (aspect
ratio/duration/caption-length rules) and publishing do not exist for any format. Do not
infer Instagram capability from the Telegram-side format catalogue - they are separate,
unconnected systems (confirmed - section J).

## I. Instagram visual-system state

`INSTAGRAM_VISUAL_SYSTEM = MISSING`.

Direct verification: `services/brand_renderer.py`, `services/render_evidence.py`,
`services/design_spec_registry.py`, `services/nnj_master_news_overlay.py`,
`schemas/declarative_visual_parameters.py` - **zero** mentions of "instagram" in any of them. No
`instagram_*render*` / `instagram_*visual*` / `instagram_*export*` module exists.
`instagram_platform_capabilities.py` and the format directors contain no aspect-ratio, canvas,
export-format, or Reel-cover concept at all.

Consequently:
* No Instagram canvas/aspect ratios are defined anywhere (feed 1080x1350/1080x1080, Reels/Stories
  1080x1920, etc. - none of these exist in code).
* No Instagram safe zones, typography rules, or brand-placement rules exist.
* No carousel-composition support (multi-slide layout/pagination) exists.
* No image/video export requirements are encoded.
* No Reel cover support exists.
* No platform-specific VisualSpec scope exists for Instagram in `design_spec_registry.py` - only
  `telegram_news` / `telegram_breaking` / `telegram_data` / `telegram_quote` scopes exist anywhere.
* The Founder-approved Telegram V8 visual system (this same branch's own recent work) is
  **entirely Telegram-native** (1280x720 NEWS/BREAKING, 1280x1172 DATA hero, bundled Fira Sans
  Condensed sized to Telegram-card proportions) and is **not reusable as-is** for Instagram - it
  would need its own canvas geometry, safe zones and possibly its own VisualSpec scope(s). This
  phase does NOT redesign it (per instruction).

## J. Instagram Growth Director state

Traced `services/instagram_growth_strategist.py::generate_growth_strategy()` (real caller:
`services/director_execution_service.py`, on-demand via the bot's `/plan`-style console commands -
never autonomous):

| capability | status |
|---|---|
| consumes CampaignPlan | **REAL_RUNTIME** (`services/campaign_planner.py::CampaignPlan` passed in) |
| consumes BusinessContextSnapshot | **REAL_RUNTIME** (`director_execution_service.py` fetches it via `get_business_context_snapshot()` before calling) |
| receives platform account/feed state | **REAL_RUNTIME** wiring (`sync_instagram_feed_context()`), but the feed is **structurally always empty** without a connected account |
| receives performance metrics | **MISSING** - `instagram_performance.py`'s contract exists but nothing populates it anywhere (no collector) |
| understands campaign goals | **REAL_RUNTIME** (phase/goal fields of CampaignPlan feed the strategy) |
| selects content format | **REAL_RUNTIME** (`instagram_format_director_v2.py::evaluate_format_v2`) |
| proposes posting cadence | **NOT FOUND** as an explicit capability in the strategist/format director - not part of the current contract |
| chooses topic/content angle | **REAL_RUNTIME** (`ContentOpportunity` + growth-strategy ideas) |
| creates briefs | **REAL_RUNTIME** but **SHADOW** (`instagram_creative_director.py` - a genuine AI Gateway call, never published) |
| generates experiments | **REAL_RUNTIME**, structural only (`instagram_experiments.py` - no automatic assignment) |
| consumes previous post performance | **MISSING** (same root cause as above - no data ever exists to consume) |
| learns/adapts from results | **MISSING** - `instagram_growth_autopsy.py` exists and is tested, but its own evidence-stage gate (`REPEATED_PATTERN`/`STABLE_WORKING_RULE`) can structurally never be reached without real accumulated performance evidence |

Founder Directive precedence (`apply_founder_directive_precedence()`) is a REAL, enforced safety
mechanism (Growth data can never override an explicit Founder directive) - this is not a shadow
contract, it is exercised by real tests and real code paths whenever the strategist runs.

## K. Social Integration state

Traced `Campaign Director -> CampaignPlan -> BusinessContextSnapshot -> platform Director ->
platform output -> editorial/review gate`:

* **Telegram and Instagram Directors share the SAME execution layer**: `services/
  director_execution_service.py` is "the ONLY place a Telegram Strategy/Growth or Instagram
  Growth advisory is computed AND (flag-gated) persisted" - both platforms are literally the same
  function family (`run_*`), fed the same `BusinessContextSnapshot`/`CampaignPlan`. This is a real,
  wired shared control plane, not mere coexistence.
* `services/director_console_service.py` is the read-only console layer both platforms render
  through (`/plan`, `/opportunities`, `/calendar`, `/performance`) - it never computes, only reads
  the latest persisted `DirectorRun`.
* **Missing edge**: neither platform's Growth/Strategy Director is wired into any AUTONOMOUS
  worker cycle. `worker/content_cycle.py` wires exactly ONE Director autonomously -
  `telegram_channel_director_shadow.py::run_channel_director_shadow()` (a genuinely per-Story,
  no-write-path, try/except-isolated shadow call). Telegram Growth Director, Telegram Strategy
  Director, and every Instagram Director are on-demand-only (bot command triggered).
* **Missing edge (platform-specific)**: after a platform Director produces output, there is no
  shared "editorial/review gate" downstream for Instagram - the Telegram-side editorial gate
  (`director_editorial_gate_shadow.py`) and Art Director (`telegram_art_director*.py`) are wired
  only into the Telegram NEWS/BREAKING/DATA/QUOTE generation path in `worker/content_cycle.py`;
  Instagram's creative-brief output never reaches either gate.

## L. Director Control Plane map

| component | file(s) | state |
|---|---|---|
| Stage1 (deterministic pre-generation gate, current) | `services/director_editorial_gate_shadow.py` | CODE_EXISTS, CODE_CALLED (real per-event loop in `worker/content_cycle.py`, before generation), TESTED |
| Stage1 (older, superseded) | `services/director_editorial_gate.py` | superseded in call order by the shadow module (still imported by the shadow module for its deterministic core logic and by its own tests) |
| Stage2 (bounded real LLM escalation) | `services/director_editorial_gate_llm.py` + `director_editorial_gate_budget.py` | CODE_EXISTS, CODE_CALLED (genuinely wired into `worker/content_cycle.py` - `gate_stage2_llm_used`/`_fell_back`/`_budget_exhausted` counters are real, live metrics), budget-capped at 100/day (`director_editorial_gate_max_llm_reviews_per_day`, default 100), fail-soft on provider failure |
| Campaign Director | `services/campaign_planner.py`, `services/campaign_service.py` | CODE_EXISTS, CODE_CALLED, deterministic (zero LLM calls), TESTED |
| Telegram Channel Director | `services/telegram_channel_director.py` + `_shadow.py` | CODE_EXISTS, CODE_CALLED (real, autonomous, per-Story, no write path), TESTED |
| Telegram Growth Director | `services/telegram_growth_director.py` | CODE_EXISTS, CODE_CALLED (on-demand via `director_execution_service.py`), pure advisory, no publication authority, TESTED |
| Telegram Strategy/Platform Director | `services/telegram_strategy_director.py` | `telegram_strategy_director_enabled=False`; not wired to any call site found (its own docstring: "neither has any wired publication/generation call anywhere") - **FLAG_DISABLED / not connected** |
| Instagram Director(s) | Format Director v2, Growth Strategist, Creative Director (section J) | on-demand via `director_execution_service.py` / console; no autonomous loop |
| Art Director / visual evaluation | `services/telegram_art_director.py` + `_spec_evaluation.py` + `_vision.py` | CODE_EXISTS, CODE_CALLED (gated by `presentation_director_mode`, default `"off"`), SHADOW-capable, `"enforce"` mode exists in code but is never the default; **Telegram-only, no Instagram coupling found anywhere** |
| Editorial gate (see Stage1/2 above) | | |
| Research/context | `services/business_context_snapshot_service.py`, `services/founder_directive_policy.py`, `services/product_context_service.py` | CODE_EXISTS, CODE_CALLED by both platforms' directors |
| Budget control | `director_editorial_gate_budget.py`, `services/social_advisory_budget_service.py` | CODE_EXISTS, CODE_CALLED, real daily caps enforced |
| Platform context | `services/platform_account_context.py`, `services/instagram_feed_context.py`, `services/telegram_feed_window.py` | CODE_EXISTS, CODE_CALLED |
| Feedback loop | see section R | mostly MISSING |
| Learning/evaluation | `services/social_learning_boundary.py` (IGNORE/LEGACY_CONTEXT_ONLY/INCLUDE_IN_LEARNING policy) | CODE_EXISTS, CODE_CALLED for launch-state gating; not closed into an actual ranking/experiment loop |
| Audit logs / decision persistence | `database/models/director_run.py`, `director_editorial_decision.py`, `director_editorial_task.py` | CODE_EXISTS; persistence flag-gated OFF by default (`director_run_persistence_enabled=False`) |

## M. Stage2 Director state

| feature | PRESENT | CALLED | TESTED | ACTIVE_BY_DEFAULT | PRODUCTION_PROVEN |
|---|---|---|---|---|---|
| real bounded Stage2 Director (LLM escalation) | YES | YES (`worker/content_cycle.py`) | YES | **NO** (requires `telegram_editorial_gate_enabled=True`, default False) | not verified this phase (would require live production inspection, out of scope) |
| live Telegram platform feed context | YES (`telegram_feed_window.py`) | YES | YES | context is always computed; whether it is ever non-empty depends on real channel data | not verified |
| Art active spec/reference enforcement | YES (`presentation_director_mode`) | YES, gated | YES | **NO** (`"off"` default; `"enforce"` exists but is opt-in) | prior visual phases confirmed prod control-plane specs exist but enforcement was never turned on |
| editorial gate before generation | YES | YES | YES | **NO** (`telegram_editorial_gate_enabled=False` default) | not verified |
| fail-soft behavior | YES - Stage2 provider failure falls back to the Stage1 deterministic outcome; gate-context/channel-director exceptions are caught so a bug there cannot break the main content cycle | YES | YES | YES (fail-soft is unconditional, not flag-gated) | consistent with design |
| gate enforcement OFF by default | YES | n/a | YES (tests exercise both flag states) | YES (confirmed default False) | n/a |
| Stage2 budget max 100/day | YES (`director_editorial_gate_max_llm_reviews_per_day: int = Field(default=100, ge=0)`) | YES (real counter, `instagram_ai_cost.py`-style discipline reused) | YES | YES (the cap itself is always enforced once Stage2 runs at all) | not verified live |

## N. Director real-input audit

| input | classification |
|---|---|
| news/feed context | REAL (Story/NewsEvent pipeline is the production content engine) |
| Story context | REAL |
| CampaignPlan | REAL (deterministic phase derivation, real DB-backed `LaunchCampaign`) |
| BusinessContextSnapshot | REAL (assembled from real underlying state) |
| Founder Directives | REAL (`founder_directive_policy.py`, precedence enforced) |
| Product Intelligence | REAL (`product_context_service.py`) |
| Telegram account/feed metrics | REAL when `telegram_performance_collection_enabled=True` (default **False**) - otherwise **EMPTY_IN_PRODUCTION** by default |
| Instagram account/feed metrics | **NOT_CONNECTED** - no live account; structurally always empty |
| historical engagement | STATIC/EMPTY - depends on the same performance-collection flag (Telegram) or is simply absent (Instagram) |
| performance/insights | see above |
| content inventory | REAL (Story/EditorialTask backed) |
| visual spec | REAL for Telegram (`design_spec_registry.py`); **NOT_CONNECTED** for Instagram (no scope exists) |
| brand rules | REAL for Telegram (`nnj_board_metrics.py` + brand renderer); **NOT_CONNECTED** for Instagram |

A Director can absolutely exist in code and still reason from an empty/default context today -
this is true for BOTH platforms' performance/insights inputs, and entirely for Instagram's
account/feed/visual inputs, in this environment.

## O. Director output / actionability

| stage | Telegram | Instagram |
|---|---|---|
| decide | YES (real, deterministic/advisory) | YES (Format/Growth/Creative, on-demand) |
| brief | YES (channel director evidence, growth advisory text) | YES (Creative Director brief) |
| generate | YES (real NEWS/BREAKING/DATA/QUOTE copy + Telegram-native visual render, in `worker/content_cycle.py`) | Creative brief only - no Instagram-specific asset generation |
| render | YES (Telegram V8 visual system, this branch's own recent work) | **NO** (section I) |
| send to editor | YES (`director_editorial_gate_shadow.py`, `EditorialTask`) | **NO** Instagram-specific editor path found |
| schedule | YES (`instagram_calendar_service.py` / `telegram_content_calendar_item.py` both exist - Instagram's calendar model exists and is tested) | YES for the CALENDAR ROW ITSELF (not for an actual send) |
| publish | YES (real production Telegram send path, `bot`/`worker`) | **NO** (section F) |
| measure results | Telegram: flag-gated, on-demand only | **NO** (no collector) |
| feed results back | Telegram: not closed into an automatic loop (advisory-only, human reads `/performance`) | **NO** |

**Last real working stage - Telegram**: full publish (production-proven, this is the live product).
**Last real working stage - Instagram**: `ShadowPlanResult` / calendar-row scheduling metadata -
never an actual send.

## P. Editorial gate

* **Signals used**: category/topic rarity tier, novelty, source trust/quality signals, and (Stage2)
  a bounded LLM escalation for the ambiguous/high-value minority (`director_editorial_gate.py` /
  `_shadow.py` / `_llm.py`).
* **Where it runs**: `worker/content_cycle.py`, once per ingested event, BEFORE
  `run_content_generation_for_event()` - genuinely pre-generation (the earlier `director_editorial_gate.py`
  ran too late, at the presentation-decision point, and is superseded in call order).
* **Can it block generation?** YES, but only when `telegram_editorial_gate_enabled=True` (default
  **False**) AND the decision is DROP or HOLD (`suppress_generation`).
* **Can it block publication?** NO - it is pre-generation only; nothing downstream re-checks its
  verdict at the publish step.
* **Current default flags**: `telegram_editorial_gate_enabled=False`,
  `director_editorial_gate_max_llm_reviews_per_day=100`.
* **Fail-soft**: YES - a Stage2 provider failure falls back to the Stage1 deterministic decision
  (never "drop everything" on an infra fault); the whole per-event gate call is wrapped so a bug
  cannot break the cycle.
* **Audit persistence**: `DirectorEditorialDecision` rows are written (unconditional, independent
  of the enable flag per the code comments - "computed and persisted regardless of whether
  telegram_editorial_gate_enabled is [true]"), giving a real historical record even while
  enforcement is off.
* **Does Instagram use the same gate correctly?** NO - the gate has no Instagram call site at all;
  Instagram content never passes through it (there is no Instagram "generation" step for it to
  gate ahead of, since there is no Instagram render/publish pipeline).

## Q. Art / Visual Director

`ART_DIRECTOR_STATUS`:

* **What it decides**: SPEC_MATCH (declared VisualSpec parameters vs RenderEvidence),
  duplicate-brand-mark / NUMBER_MISMATCH / INFOGRAPHIC_DESTROYED hard-BLOCK conditions, and
  (`telegram_art_director_vision.py`) an optional vision-model pass.
* **What it validates**: Telegram render evidence only - canvas, margin, logo zone, scrim,
  source-image treatment, per-format declarative parameters (`telegram_news/breaking/data/quote`).
* **Telegram-only?** YES - confirmed by direct grep: zero references to "instagram" anywhere in
  `telegram_art_director.py`, `_spec_evaluation.py`, `_vision.py`, or `design_spec_registry.py`.
* **Does Instagram pass through it?** NO.
* **Platform-specific specs?** Only `telegram_*` scopes exist in `design_spec_registry.py`; there is
  no `instagram_*` VisualSpec scope.
* **On BLOCK**: `ArtDirectorDecision.BLOCK` - the merged decision the Telegram content path already
  respects (verified in the FOUNDER-VISUAL-* phases on this same branch).
* **Regeneration on BLOCK?** Not itself - BLOCK is a gate, not an auto-retry loop (no evidence of an
  automatic regenerate-on-BLOCK cycle was found).
* **Max retry/budget**: N/A for Art Director itself (its cost model is the underlying render, which
  is deterministic and free; the OPTIONAL vision pass is a separate, own-budgeted concern not
  audited in depth this phase).
* **Did the current V8 renderer change any assumptions the Art Director makes?** NO structural
  change - V8 changed DATA's canvas geometry (near-square 1280x1172) and BREAKING's pulse/watermark
  geometry, but the `DeclarativeVisualParameters` schema has no canvas/aspect field to begin with
  (confirmed across the whole V8 lineage on this branch), so the Art Director's SPEC_MATCH
  evaluation was never coupled to a 16:9 assumption in the first place - only the font-range
  candidate values needed updating (done in FOUNDER-VISUAL-V8-FINAL-RELEASE-PREP-1, this branch).

## R. Performance feedback loop

| metric | Telegram | Instagram |
|---|---|---|
| views | collectible (`telegram_performance_collection.py`, PASSIVE ONLY, flag `telegram_performance_collection_enabled=False` default) | not collectible - no account |
| reactions | same | not collectible |
| forwards | same | not collectible |
| comments (if available) | same | not collectible |
| reach / impressions / views | N/A (Telegram concept differs) | contract exists (`instagram_performance.py`), never populated |
| likes/comments/shares/saves | N/A | contract exists, never populated |
| watch/reel metrics | N/A | contract exists, never populated |
| followers/account context | N/A | `instagram_account_reader.py` CAN read this live; never exercised without a real account |

**Collected?** Telegram: only if the flag is turned on (default off), and only passively (no write
calls). Instagram: never - no collector process exists to call the (working) reader's insight
methods on a schedule.
**Persisted?** Telegram: yes, when collected (`telegram_post_performance.py`). Instagram: the model
(`instagram_performance.py`) exists but nothing ever calls it in a real flow.
**Normalized?** Yes for both, structurally (nullable-metric discipline, "unavailable != 0").
**Consumed by Director?** Telegram Growth Director/Autopsy read whatever exists (structurally
correct, practically starved of data by default). Instagram Growth Autopsy: same, but with an
extra, currently-unreachable evidence-stage gate.
**Used for future ranking/experiments?** No closed loop was found on either platform - both are
advisory-display-only today (`/performance` reads a persisted advisory; nothing automatically
re-ranks or re-weights future decisions from measured results).

**Missing links (both platforms)**: (1) no scheduled collector job exists anywhere (`worker/`
contains no performance-collection entrypoint); (2) no automatic re-weighting of Director advisory
logic from observed results; (3) Instagram additionally lacks the account connection itself, which
is the actual root blocker.

## S. Campaign Intelligence chain

`Product Intelligence -> Founder Directives -> Campaign Director -> CampaignPlan ->
BusinessContextSnapshot` is a real, complete runtime chain (`product_context_service.py`,
`founder_directive_policy.py`, `campaign_planner.py`/`campaign_service.py`,
`business_context_snapshot_service.py`) - verified by the fact that both
`director_execution_service.py` (Telegram Growth/Strategy AND Instagram Growth) and
`instagram_growth_strategist.py` consume it directly.

**Does Instagram Growth get the SAME authoritative campaign context, or a local/static one?**
**The SAME.** `director_execution_service.py` is the one place both platforms' advisories are
computed, and it fetches ONE `BusinessContextSnapshot`/`CampaignPlan` pair and threads it through
to whichever platform's `run_*` function is invoked. There is no separate/static Instagram-only
context path.

## T. Launch-state semantics

`LaunchState` (`database/models/social_launch_context.py`): `PRE_LAUNCH`, `TRANSITION`, `LIVE`,
`PAUSED` - all four present, defaulting to `PRE_LAUNCH`. `services/social_launch_context_service.py`
implements the COLD_START predicate (`PRE_LAUNCH` or `TRANSITION`) exactly as historically
described. Policy modes `IGNORE` / `LEGACY_CONTEXT_ONLY` / `INCLUDE_IN_LEARNING` are present in
`database/models/social_launch_context.py`, `services/platform_account_context.py`,
`services/social_launch_proposal_service.py`, and `services/social_learning_boundary.py`.

**Is Instagram integrated into this semantics?** YES - `services/instagram_connection_service.py`
explicitly fetches `SocialLaunchContext` for `SocialLaunchPlatform.INSTAGRAM` and threads
`launch_context` into `build_instagram_feed_context()`; `instagram_creative_director.py` also
carries an optional `launch_context_note`. This is real, wired integration, not a stub.

## U. Unfinished-code search

Searched `services/instagram_*.py`, `services/director_*.py`, `services/campaign_*.py`,
`services/social_*.py`, `services/telegram_growth_director.py`,
`services/telegram_strategy_director.py`, `services/telegram_channel_director*.py` for
TODO/FIXME/NotImplemented/placeholder/mock/disabled/temporary/hardcoded/stub markers.

**Result: remarkably clean.** The only real hits are 3 deliberate `raise NotImplementedError(...)`
calls in `services/instagram_graph_adapter.py`, each explicitly annotated
`# pragma: no cover - unreachable without real credentials` - these are intentional readiness
guards (the module's own docstring: "never fabricates a live API call result"), not unfinished
work. No stray `TODO`/`FIXME`/bare `pass`-as-a-stub/mock-standing-in-for-real-logic was found in
this surface. This matches the consistent architectural discipline observed throughout section C.

## V. DB / migration support

Local `alembic heads` = **`4a1b7c9d2e3f` (single head)** - matches the previously-recorded
production control-plane DB head from the FOUNDER-VISUAL phases on this same branch. The Instagram
+ Director migration lineage is a single connected chain, not a divergent branch:

    647aa0fe8a5a -> 495d8c5b408e (instagram content calendar items)
                 -> 12c560efce40 (instagram persistent intelligence memory)
                 -> 075d1af8dc10 (instagram creative plan + AI cost tables)
                 -> 2fb7d650c68b  \
    c0021dea34a5                  }-> b3817f7c6074 (merge: telegram directors + instagram growth engine heads)
                 -> ... -> b548f44f0f85 -> 4a1b7c9d2e3f (add instagram account read metadata) [head]

**Every Instagram/Director feature that has real persistent state also has a migrated table** -
`InstagramAccount`, `InstagramContentCalendarItem`, `InstagramCreativePlan`/`CreativeDraft`,
`InstagramAICallRecord`, the various `Instagram*Memory` tables, `DirectorRun`,
`DirectorEditorialDecision`/`DirectorEditorialTask`, `Campaign`/`CampaignMilestone`,
`SocialLaunchContext`/`SocialLaunchProposal`. No Instagram/Director feature was found with code but
no backing table. (Whether the LIVE production database is actually at this same alembic head was
not re-verified this phase - out of this audit's read-only-repo scope; the prior FOUNDER-VISUAL
phases recorded it as such as of their own last check.)

## W. Test coverage

| component | status |
|---|---|
| Instagram reader (`instagram_account_reader.py`) | TESTED (`test_instagram_account_reader.py`, 2 tests confirmed passing this session) |
| Instagram account handling / connection | TESTED (`test_instagram_connection_service.py`, `test_instagram_read_security.py`, `test_instagram_director_read_integration.py` - all passing this session) |
| Instagram metrics/insights | PARTIALLY_TESTED - `test_instagram_performance.py` exists and tests the (unpopulated) contract; no test exercises a real collector because none exists |
| Instagram Director(s) | TESTED (`test_instagram_format_director_v2.py` 10 tests, `test_instagram_creative_director.py`, `test_instagram_growth_strategist_v2.py`, `test_instagram_shadow_pipeline.py` - all confirmed passing) |
| Social Integration | TESTED (`test_director_console_service.py` 32 tests - 31 passing, 1 failing this session, see below) |
| Campaign Director | TESTED (implicit via `test_director_execution_service.py`, `test_director_console_service.py`) |
| Stage2 Director | TESTED (gate/budget/shadow test files exist for `director_editorial_gate*`; not individually re-run this phase) |
| Editorial gate | TESTED (same) |
| Art Director | TESTED (extensively, via the whole FOUNDER-VISUAL-* lineage on this branch - Telegram-only) |
| Instagram render/export | **UNTESTED** - no such code exists to test |
| Instagram publication | **UNTESTED** - no such code exists to test |

A bounded, non-production-connected confirmation run of the core Instagram/Director test surface
(11 files, 131 tests) was executed this session:

    130 passed, 1 failed

The one failure - `tests/test_director_console_service.py::test_no_campaign_no_story_notes_are_honest`
- asserts an empty `Story`-derived opportunity list but this dev database already contains real
ingested Story rows (e.g. "Meta ships Muse agent to GA") from actual pipeline activity in this
environment; the test is not properly isolated against a non-empty `stories` table. This reproduces
in isolation (not order-dependent) and is a **test-isolation gap**, not a functional defect in the
Director/console code itself. No production database was touched to reach this conclusion.

## X. Branch reconciliation

See section B for the full ancestry matrix. Summary:

* **A. Already present in current visual branch**: essentially everything named in this phase's own
  landmark list - the entire Instagram Growth Engine (v1 + v2 + v3/persistence), the Director
  Control Plane (Stage1/1A/1B/1C), Social Integration, Social OPS, Visual Design Autonomy, and the
  Prelaunch lineage. HEAD is ancestor-superset of every one of those named branches except the two
  noted below.
* **B. Missing from visual branch but exists elsewhere (requires integration)**: **none found** of
  substantive size. The only branch-unique commits are (i) 3 superseded single-brand-mark commits
  and (ii) the unrelated Story-Continuity/old-visual-release branches explicitly out of this
  phase's scope.
* **C. Superseded by a newer implementation**: `feature/visual-single-brand-mark-v1`'s 3 commits
  (superseded by the mainline's own further-developed mutual-exclusion implementation, verified
  present and tested); `release/founder-visual-vnext-content-worker-1` (superseded by the
  Founder-approved V8 release, already handled in the prior phase).
* **D. Never implemented, absent from every lineage**: Instagram publish/write path (section F),
  Instagram visual/render system (section I), any autonomous Instagram/Growth/Strategy scheduling
  loop, any performance collector for either platform.

No cherry-pick is proposed or needed - there is nothing on another lineage to bring over.

## Y. Gap register (P0/P1/P2/OPERATOR)

| priority | component | current state | missing piece | why it matters | files/modules | code work? | credential/account work? | scope |
|---|---|---|---|---|---|---|---|---|
| OPERATOR_BLOCKER | Instagram account connection | reader/connection code complete | real access token + business account id + Meta App w/ Instagram Login product configured + (if insights wanted) app review | nothing Instagram-real can be observed/tested against a live account without this | `core/config.py`, ops/Meta developer console | NO | YES (Meta App setup + token issuance, operator-side) | N/A |
| P0_BLOCKER | Instagram publish adapter | NOT_IMPLEMENTED | container-create -> status-poll -> publish call -> result persistence for single/carousel/reel, official `instagram_business_content_publish` scope | without this Instagram can never become an operational publishing channel - it is a structural precondition, not an enhancement | new `services/instagram_publish_adapter.py`-shaped module + `instagram_platform_capabilities.py` flip to AVAILABLE + new persistence for publish results | YES | YES (write scope must be requested/approved by Meta) | L |
| P0_BLOCKER | Instagram visual/render system | MISSING | Instagram-specific canvas geometry, safe zones, aspect ratios (feed/carousel/reel/story), an Instagram renderer, and (likely) its own VisualSpec scope(s) | there is no way to produce an actual postable image/video for any format today | new `services/instagram_brand_renderer.py`(-shaped), `design_spec_registry.py` new scopes, `render_evidence.py` extension | YES | NO | L |
| P1_REQUIRED | Instagram performance collector | MISSING | a scheduled (or on-demand, flag-gated) job calling `instagram_account_reader.py`'s existing insight methods and persisting into `instagram_performance.py`'s contract | growth strategy/autopsy/experiments are structurally starved of real evidence without this - even after publish exists, the loop stays open | new `services/instagram_performance_collection.py` (mirror of the Telegram one) + a worker cycle entrypoint | YES | YES (needs a connected account to produce real data) | M |
| P1_REQUIRED | Autonomous Instagram scheduling | MISSING | some worker/cron entrypoint that periodically drives the shadow pipeline (or the post-publish-adapter real pipeline) forward, analogous to `worker/content_cycle.py`'s Telegram Channel Director wiring | today Instagram Directors only run when a human issues a bot command - there is no autonomous cadence at all | new `worker/instagram_cycle.py`-shaped entrypoint or an extension of `worker/content_cycle.py` | YES | NO (can be built and tested entirely in shadow before any account exists) | M |
| P1_REQUIRED | Instagram <-> editorial/Art gate integration | MISSING | route Instagram creative output through an editorial-safety gate and (once a renderer exists) an Art-Director-equivalent check before any future publish | without this, Instagram would ship its first real publish with zero of the safety machinery the Telegram path already has | `director_editorial_gate_shadow.py` extension or an Instagram-specific gate; a new/extended Art Director scope | YES | NO | M |
| P1_REQUIRED | Telegram Strategy/Platform Director wiring | flag-disabled, no call site | either wire it into `director_execution_service.py`'s `run_*` family (like Growth) or explicitly retire it | dead code with a flag is a documentation/maintenance risk and a "done but actually isn't" trap for the Founder | `services/telegram_strategy_director.py` | YES (small) | NO | XS |
| P2_LATER | Instagram posting-cadence advisory | not part of the current strategist contract | an explicit cadence recommendation capability | nice-to-have refinement, not a blocker to a first live post | `instagram_growth_strategist.py` | YES | NO | S |
| P2_LATER | Instagram Growth Autopsy real activation | code complete but structurally unreachable | real accumulated performance evidence (depends on the P1 collector) | autopsy only becomes useful once real evidence exists | none (already correct) - just needs data | NO | YES | - |
| P2_LATER | Director learning/ranking loop closure | advisory-display only on both platforms | actual re-weighting of future Director decisions from measured results | genuine "learns and adapts" capability the phase asked about | new logic in growth strategist / autopsy consumers | YES | NO (can design against synthetic data first) | L |
| OPERATOR_BLOCKER | Test-isolation gap | 1 test fails against a non-empty dev Story table | either an isolated test DB/schema per test run, or a query-scoping fix in the test itself | not a blocker to Instagram/Director launch, but a real, currently-red test in the suite | `tests/test_director_console_service.py::test_no_campaign_no_story_notes_are_honest` | YES (small) | NO | XS |

## Z. Recommended finish plan

Proposed as 3 coherent phases (not 10 micro-phases), explicitly separating what needs Instagram
credentials from what does not:

**Phase 1 - Instagram Render + Publish Foundation** (NO credentials required to build/test in
shadow; credentials required only for the final live-account validation step)
* Build the Instagram-specific visual system (canvas geometry, safe zones, aspect ratios for
  feed/carousel/reel/story; reuse the V8 board-measurement discipline and bundled-font approach,
  new geometry only).
* Build the official publish adapter (container-create -> status-poll -> publish -> result
  persistence) as a SHADOW-first implementation (structurally complete, gated behind a flag
  defaulting False, exactly like every other module in this codebase) so it can be fully unit- and
  contract-tested without a live account.
* Wire Instagram creative output through an editorial-safety gate before any future publish call
  (extend or mirror `director_editorial_gate_shadow.py`); define (does not need to activate) an
  Art-Director-equivalent check for the new renderer.
* Can run almost entirely in parallel with Phase 2.

**Phase 2 - Instagram Performance Loop + Autonomous Cadence** (code work needs no credentials; real
data needs a connected account)
* Build the Instagram performance collector (mirror `telegram_performance_collection.py`'s
  passive-only, flag-gated pattern) targeting the already-real reader's insight methods.
* Build an autonomous scheduling entrypoint (a `worker/`-level cycle, or an extension of
  `worker/content_cycle.py`) that periodically advances the shadow pipeline (and, once Phase 1
  lands, the real publish-shadow pipeline) - same fail-soft/try-except isolation discipline as the
  existing Telegram Channel Director wiring.
* Retire or wire `services/telegram_strategy_director.py` (small, XS cleanup, can be folded into
  either phase).

**Phase 3 - Live Validation** (REQUIRES real Instagram credentials + a connected Business/Creator
account + Meta App configuration/review)
* Connect a real account; run the reader/connection/feed-context path against it for the first
  time; confirm `check_connection()` identity match, insights availability detection, and the
  publish adapter's live status-polling behaviour end-to-end on a single test post.
* Turn on the performance collector against the real account; confirm the Growth
  Autopsy/Experiments evidence-stage gate can now actually advance.
* Founder review + explicit authorization before any public/production publish is enabled.

Work that can proceed WITHOUT Instagram credentials: essentially all of Phase 1 and Phase 2's code
(renderer, publish-adapter shape, editorial-gate wiring, performance-collector shape, scheduling
entrypoint) - the existing codebase's own discipline (shadow-first, flag-gated, structurally
truthful about UNKNOWN/UNAVAILABLE) makes this straightforward to build and fully test without any
live account, exactly as every other Instagram module in this codebase was already built. Only the
FINAL validation step (Phase 3) requires the real account and Meta App configuration.

---

`INSTAGRAM_DIRECTOR_STATE_RECONCILIATION_COMPLETE`

INSTAGRAM_STATUS = PARTIAL
DIRECTOR_STATUS = PARTIAL

INSTAGRAM_FIRST_MISSING_STAGE = Instagram-specific rendered visual asset (no renderer exists to
turn a CreativeGenerationOutcome into an actual postable image/video)

DIRECTOR_FIRST_MISSING_STAGE = autonomous scheduling (every Director beyond the Telegram Channel
Director shadow call is on-demand/bot-triggered only, never run on a cadence)

OPERATOR_BLOCKERS = [Instagram access token + business account id (real Meta App with Instagram
Login product configured, a linked Business/Creator account, and - for insights - app review);
the test-isolation gap in test_director_console_service.py requires no operator, listed for
completeness]

CODE_BLOCKERS = [no Instagram publish adapter (any format); no Instagram visual/render system; no
Instagram performance collector; no autonomous Instagram/Growth/Strategy scheduling entrypoint; no
Instagram <-> editorial/Art gate integration; telegram_strategy_director.py has no call site]

RECOMMENDED_NEXT_PHASES = [Phase 1: Instagram Render + Publish Foundation (shadow-first, no
credentials needed to build/test); Phase 2: Instagram Performance Loop + Autonomous Cadence
(credentials needed only for real data); Phase 3: Live Validation (requires real Instagram
credentials + Meta App configuration + Founder authorization)]
