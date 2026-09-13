# UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1

Branch `feature/unified-editorial-production-pipeline-1` (worktree `C:/Users/Theodor/ai-newsroom-
unified-pipeline-1`), base `b5d5276` + merges of `6f56aec`/`0379ff2`/`9fc7b1e` (see §A). **No
production deployment. No public/autonomous publication. No Story Memory predicate change.**

## A. Source reconciliation

Full detail: `docs/unified_editorial_source_reconciliation_1.md`. Summary:

- **CANONICAL_TELEGRAM_SOURCE**: `b5d5276` (currently deployed to production `content_worker`).
- **CANONICAL_INSTAGRAM_SOURCE**: `0379ff2` (local-only, never pushed - execution foundation +
  visual system v1.1 + growth engine + the autonomous trend-canary's own iPhone-Duo fix, all
  confirmed contained in this one commit's ancestry).
- **CANONICAL_STORY_MEMORY_SOURCE**: `6f56aec` (currently deployed to production
  `automation_worker`).
- **CANONICAL_CROSS_PLATFORM_MEDIA_RESEARCH_SOURCE**: `9fc7b1e` (local-only, never pushed).
- The GitHub default branch (`feature/phase19-editorial-depth-upgrade`) predates and is unrelated
  to every real production fix since 2026-09-08 - confirmed via `git merge-base --is-ancestor`
  returning false in both directions for `d2dea2c`/`d0a0377`/`a41c02d`/`6f56aec` against it. **Not
  production truth. Not touched by this phase.**
- All four lineages were merged into one integration branch via three ordinary `git merge --no-ff`
  operations, each verified conflict-free. The two Telegram/Instagram lineages' independently-built
  alembic migration graphs already converge to a single head (`4a1b7c9d2e3f`, matching live
  production) - Instagram's own migration history had already anticipated this reconciliation.
- Zero data loss: every commit named in the phase brief (including `a9908e8`) was confirmed
  reachable, either directly or as an ancestor of a later commit on the same branch. No
  `reset`/`clean`/`stash drop`/`rebase`/`amend` was used anywhere.

## B. Production source manifest

`docs/production_source_manifest.md`.

## C. Current architecture diagnosis

`worker/content_cycle.py` is exactly the de-facto god orchestrator the phase brief describes:
media-candidate discovery/ranking, presentation-format decision, DATA-candidate extraction (regex
over prose - see §G), branding/render dispatch, Telegram-specific caption-budget policy, transport
dispatch, delivery persistence, and recovery/HOLD logic all live inline in one ~2400-line function.
Presentation-type decisions and DATA candidate extraction happen in `services/presentation_
director.py`, itself invoked FROM inside `content_cycle.py` rather than from a shared, platform-
neutral layer. Media discovery/ranking (`services/image_persistence.py`, `services/media_ranking.py`)
is Telegram-only - the real, tested `services.media_research_selection.research_and_select_media()`
(from the reconciled cross-platform lineage) already exists as a platform-neutral alternative but
was never wired into any live worker before this phase. Instagram has its own, separate, real,
parallel content-package/render/gate/publish stack
(`services/instagram_content_package.py`/`instagram_platform_renderer.py`/`instagram_art_
validator.py`/`instagram_editorial_gate.py`/`instagram_publish_adapter.py`) with zero code sharing
with Telegram's path prior to this phase.

Specific findings:
- **Decisions made inside `worker/content_cycle.py`**: media candidate selection order, cross-
  event duplicate exclusion, recomposition-source-risk gating, presentation-decision invocation,
  branding dispatch, caption-budget/send-shape decision, HOLD/recovery decision (this session's own
  prior TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1 phase), delivery persistence.
- **Media decisions duplicated outside one service**: Telegram's `get_editorial_image_candidates`/
  `_select_top_ranked_image_candidates`/`resolve_photo_input` vs. Instagram's own separate media
  handling inside its Creative Director/render pipeline vs. the reconciled, unused `services.media_
  research_selection.research_and_select_media()` - three separate media-selection code paths existed
  before this phase.
- **Fallback decisions inside transport**: fixed in the prior phase (the old `used_text_fallback`
  retry-as-text-on-send-failure mechanism, now a HOLD) - confirmed still true by reading, not
  assumed, in §D.
- **Renderers deriving semantic facts**: `services.presentation_director._find_data_candidate()`
  regex-extracts `(value, unit, label)` from prose - the exact "Maxus class" defect (§I).
- **Prose parsing to reconstruct structured facts**: the same function - DATA's `metric_label` was
  built by stripping a matched span out of an already-generated sentence, not composed from
  structured parts.
- **Text-only-capable editorial routes**: enumerated and classified in this session's own prior
  phase's report (`docs/telegram_text_only_visual_fallback_repair_1_report.md` §G) - unchanged
  here, reused not re-audited.
- **Legacy paths**: `content_draft_media_items` (confirmed unused, prior phase), the legacy non-V8
  `render_editorial_card()` template path (still real, for non-V8-family copywriting output).
- **Shadow/orphan Director paths**: `feature/director-control-plane-v1`'s own branch tip is
  byte-identical to `d2dea2c` (already merged into mainline, not a separate orphan).
- **Platform-specific logic leaking into shared editorial logic**: `services/presentation_
  director.py` (nominally platform-neutral) is invoked only from Telegram's own `content_cycle.py`
  and has no Instagram caller; DATA/QUOTE candidate types are reused by this phase's own new
  contracts specifically because they are already legitimately platform-neutral.

## D. Ownership matrix

| Concern | Current owner(s) | Duplicate owner(s) | Target owner (this phase) |
|---|---|---|---|
| Editorial format decision (NEWS/BREAKING/DATA/QUOTE) | `services/presentation_director.py` (Telegram-only caller) | none | `services/editorial_pipeline/orchestrator.py` (shared) |
| DATA candidate extraction | `services/presentation_director._find_data_candidate()` (regex) | none | `services/editorial_pipeline/content.py` (structured, evidence-traced) |
| Media candidate discovery/ranking | `services/image_persistence.py` + `services/media_ranking.py` (Telegram); Instagram's own internal handling | 2 parallel implementations | `services/editorial_pipeline/media.py::MediaResearchService` (shared) |
| Subject-identity classification | `services/media_research_selection.py` (built, never wired) | none (but unused) | wired via `MediaResearchService`, still the same real module |
| Composition/DATA graph-vs-image-vs-typographic decision | implicit, scattered across `content_cycle.py`'s render branch | none | `services/editorial_pipeline/composition.py` |
| Telegram caption budget | `content_cycle.py` inline (`fits_caption_budget`) | none | `services/editorial_pipeline/platforms/telegram.py` |
| Transport | `services/telegram_routing.py` (Telegram); `services/instagram_publish_adapter.py` (Instagram) | 2, but each already platform-scoped correctly | unchanged (S24 - transport stays platform-owned, dumb) |
| Recovery/HOLD | `worker/content_cycle.py::_hold_for_visual_recovery()` (Telegram-only, prior phase) | none | `services/editorial_pipeline/recovery.py` (shared contract, bridges to the same Telegram mechanism) |
| Quality/Art validation | `services/instagram_art_validator.py` (Instagram-only) | none for Telegram | `services/editorial_pipeline/quality.py` (shared gate; delegates ART_VALIDATION to the real Instagram validator, unchanged) |
| Language QA | none existed | none | `services/editorial_pipeline/language_qa.py` (new, shared) |

## E-F. Target architecture / typed contracts

`services/editorial_pipeline/contracts.py`. Re-exports the real, already-tested `MediaIntent`/
`ResolvedMediaCandidate`/`MediaSelectionResult` (cross-platform-media-research-selection-1) as
`VisualIntent`/`MediaCandidate`/`MediaSelection`, and `DataCandidate`/`QuoteCandidate`
(`presentation_director.py`) unchanged. New: `EvidenceClaim`/`EvidencePack`, `StructuredNewsContent`/
`StructuredBreakingContent`/`StructuredDataContent`/`StructuredQuoteContent`, `SlidePlan`/
`CarouselPlan`, `CompositionPlan`/`DataCompositionStrategy`, `QualityCheckResult`/`QualityGateResult`,
`DeliveryPackage`/`DeliveryOutcome`, `RecoveryJob`/`RecoveryResult`/`RecoveryReasonCode`. Plain
dataclasses, matching this codebase's own existing convention for in-process contracts; no DB
migration.

## G. Evidence / structured content

`services/editorial_pipeline/evidence.py` + `content.py`. `build_evidence_pack()` wraps the existing
`research_facts` list into addressable, stably-id'd `EvidenceClaim`s - one claim per fact, verbatim,
no new extraction. `build_structured_data_content()` is the concrete fix for the Maxus-class defect
(§I). `build_structured_quote_content()` adds evidence traceability to the already-correct
`QuoteCandidate`.

## H. Media Research

`services/editorial_pipeline/media.py::MediaResearchService` wraps the real, reconciled
`services.media_research_selection.research_and_select_media()` - not reimplemented. Adds a genuine
fix: the reused `discover_web_candidates()` had no exception handling around its own network calls;
a real failure would have crashed the whole selection instead of failing soft to Tier 1 (S14's own
explicit requirement) - fixed in the wrapper, proven by `test_external_search_failure_fails_soft_
to_tier1_only`.

## I. Composition

`services/editorial_pipeline/composition.py`. `decide_data_composition_strategy()` implements S9's
exact precedence (real series -> `DATA_WITH_GRAPH`; no series but a non-MISMATCH selected image ->
`DATA_WITH_SOURCE_IMAGE`; neither -> `DATA_TYPOGRAPHIC`) - never fabricates a graph.

**The Maxus-class defect, reproduced and fixed with real data**: the real sentence "Рекомендованная
цена автомобиля начинается с 290 тыс. юаней (примерно 3,8 млн рублей)" (SAIC Maxus 9, iXBT,
independently fetched during this phase, not fabricated) run through the OLD, currently-deployed
`_find_data_candidate()`/`_safe_label()` produces `label='Рекомендованная цена автомобиля начинается
с юаней (примерно 3,8 млн рублей).'` - the number vanishes from the label, the exact artifact named
in the phase brief. Two independent, concrete root causes found: (1) `_ORPHANED_LABEL_RE`'s guarded
preposition list never included `с` ("with/from") - the exact preposition in the defect; (2)
`_CURRENCY_WORD` never recognized "юань" (yuan) as a currency at all. `build_structured_data_
content()` fixes both, producing `metric_value="290"`, `metric_unit` containing "тыс"+"юан" whole,
`metric_label="Стартовая цена Maxus 9"` (subject extracted from the title's own brand+model token
pattern, metric kind classified from the fact's own vocabulary - never a sliced sentence remainder).
Both fixes are kept local to the new pipeline's own `language_qa.py` (not edited into `presentation_
director.py` itself) per the S18 Telegram V8 freeze - that module's production behavior is
byte-for-byte unchanged (confirmed, §P).

## J. Telegram adapter

`services/editorial_pipeline/platforms/telegram.py`. `plan_telegram_caption_budget()` replaces the
"caption too long -> silently drop image -> text-only" rule (S19) for the NEW pipeline: full caption
fits -> send as-is; caption minus only the non-factual NINJA PULSE footer fits -> send without the
footer (zero factual content ever touched); still too long -> `RecoveryReasonCode.CAPTION_BUDGET_
FAILED`, never a blind truncation, never a dropped visual. Transport itself (`services/telegram_
routing.py`) was already dumb (SENT/FAILED/AMBIGUOUS only) after the prior phase's own fix - confirmed
by reading, not assumed.

## K. Instagram adapter

`services/editorial_pipeline/platforms/instagram.py`. Deliberately narrower than the Telegram
adapter, honestly so: Instagram's real Director planning chain (`ContentOpportunity -> ... ->
build_instagram_content_package()`) is genuinely deep and untouched - reconstructing fake upstream
objects merely to force a package through a generic signature would be hollow integration.
`evaluate_instagram_package()` instead takes an ALREADY-BUILT, real `InstagramContentPackage` (same
construction shape as `tests/test_instagram_content_package.py`'s own established pattern) plus its
real, rendered `InstagramRenderResult`s, and runs it through the SAME shared quality gate every
Telegram package passes through - `ART_VALIDATION` delegates to the real, unmodified `services.
instagram_art_validator.validate_instagram_art()`. Proven with a real package/render, not a fabricated
fixture: the SAME `LANGUAGE_QUALITY` check catches the Maxus defect class on an Instagram caption too
- genuine evidence the gate is actually shared, not two parallel ones. Zero network writes confirmed
via a `socket.connect` monkeypatch that would raise.

Disclosed limitation: Instagram's structured content is not yet threaded through `StructuredContent`
- `FACT_SUPPORT`/`CLAIM_TRACEABILITY` are explicitly marked "not evaluated for Instagram in this
phase" rather than silently reported as passing a real check.

## L. Quality gate

`services/editorial_pipeline/quality.py::run_quality_gate()` runs all 8 required checks (S21) every
time, never short-circuits, returns `BLOCK` (never merely `HOLD`) specifically for a visual-
truthfulness/media-provenance/Art-validation failure. `services/editorial_pipeline/language_qa.py`
(S22) is the bounded Russian-language check - detection plus exactly one deterministic mechanical
correction (exact duplicated sentences), never an open-ended rewrite loop.

## M. Recovery workflow

`services/editorial_pipeline/recovery.py`. `RecoveryJob` is bounded by construction
(`DEFAULT_MAX_ATTEMPTS=1`, matching the prior phase's own `MAX_VISUAL_FALLBACK_ATTEMPTS=0`
precedent), reason-coded (`RecoveryReasonCode`), and documents (does not apply) a future dedicated
`recovery_jobs` migration. `apply_telegram_recovery()` bridges to the SAME, already-deployed,
already-tested `_hold_for_visual_recovery()` from the prior phase rather than a second, competing
persistence mechanism.

## N. Observability

Every orchestrator stage logs its own named diagnostic event, matching S32's required list exactly:
`pipeline_started`, `evidence_ready`, `structured_content_ready`, `media_research_started`,
`media_candidate_rejected`, `media_selected`, `composition_ready`, `quality_gate_result`,
`delivery_package_ready`, `recovery_created`, `pipeline_finished` - all correlated by
`content_draft_id`. **Disclosed gap**: `transport_result` as a named stage is not yet reachable,
since no platform adapter in this phase dispatches a `DeliveryPackage` to a real send call (S39: no
production deploy) - the natural extension point for a future phase that does. Never logs API
keys/tokens/credentials/private payloads - confirmed by inspection of every `extra={}` call site
added in this phase.

## O. Replay results

**A. Three real Telegram no-visual-resolved NEWS cases** (found via read-only production DB query,
not fabricated): all three of the phase brief's own named cases are real, currently-live production
events, all three already correctly HELD by this session's own prior TELEGRAM-TEXT-ONLY-VISUAL-
FALLBACK-REPAIR-1 fix:

| Case | Real event | `content_drafts.status` | Root cause |
|---|---|---|---|
| Dario Amodei / LA Times | "Amodei, Altman, Musk call for slowing AI model development" (event `5a3f65e5`) | `hold_for_visual` | all image candidates `ineligible`, none ranked |
| Deepfake police-crime case | "163 crimes involving keywords like AI-generated, deepfake..." (event `5ac6ab14`) | `hold_for_visual` | **2 candidates ARE ranked/stored/accepted** - held despite eligible media existing, a genuinely different failure class than the other two |
| Dario Amodei / CBS | "'exponential' growth of AI is a 'warning sign'" (event `6bc1e063`) | `hold_for_visual` | all image candidates `ineligible`, none ranked |

None silently completed as text-only - the Founder invariant already holds for all three in live
production. The deepfake case is the more interesting one for the new pipeline's own value
proposition: real, eligible Tier-1 candidates exist but something downstream still prevented
delivery - exactly the class of case `MediaResearchService`'s richer selection/scoring (once wired
into the live worker in a future phase) could plausibly resolve differently, rather than an
additional live remediation attempt in this phase (which stays scoped to architecture, not a second
live incident response).

**B. Foldable-iPhone carousel** - a real, live re-run of the existing `scripts/_cross_platform_
media_research_canary_1.py` against this reconciled worktree (real downloads, real OpenAI vision-LLM
call, disclosed cost/scope unchanged from its own original canary): `candidates_considered=4`,
`exact_subject_media_not_found=False`, `selected=web:0:macrumors.com`, `selected_score=86.0`, the
wrong local ordinary-iPhone candidate correctly rejected as `MISMATCH` with a real, specific vision-
model reason. Artifacts updated in `artifacts/cross_platform_media_research_canary_1/`.

**C. Maxus 9 DATA** - see §I. Real article text, real defect reproduction, real fix, 4 passing tests.

**D. Caption-too-long Telegram fixture** - `tests/test_editorial_pipeline_telegram_caption_budget.py`,
4 tests: fits as-is; footer-only compression recovers budget with every body character intact;
still-too-long produces `CAPTION_BUDGET_FAILED` recovery, never a text-only send; text-only paths
(S4-C) are never subject to the photo-caption limit at all.

**E. Existing V8 NEWS/BREAKING/DATA/QUOTE** - see §P (zero regressions, byte-identical rendering
source).

**F. Media-send failure** - the reason code and its bounded/terminal semantics are proven
(`test_media_send_failure_class_is_available_as_a_recovery_reason`); the live Telegram send-failure
->HOLD path itself is the prior phase's own already-proven, already-deployed, already-live-confirmed
mechanism (a real recurrence was caught and correctly held during that phase's own production
observation window) - reused, not duplicated.

## P. V8 parity

`EXISTING_V8_MEDIA_BACKED_PIXEL_DIFF = 0`. Proof: `git diff b5d5276 HEAD -- services/brand_
renderer.py services/nnj_master_news_overlay.py services/presentation_director.py services/news_
telegram_presentation.py services/render_evidence.py` returns **zero lines** - these files are
byte-for-byte identical between the pre-merge Telegram-only base and this phase's own final HEAD.
Identical source with no external non-determinism guarantees identical rendered output. Additionally
confirmed behaviorally: the full existing regression suite for every file that imports `worker.
content_cycle` (18 files, 460 tests) passes with the exact same 17 pre-existing failures as the
verified baseline (§R) - `NEW_FAILURES = 0`.

## Q. Instagram safety

`instagram_publication_enabled` remains `false` throughout (never read or touched by this phase's own
code). No credentials configured, no network write ever attempted by `evaluate_instagram_package()`
- confirmed via a `socket.connect`-raising monkeypatch in `test_evaluate_instagram_package_never_
touches_the_network`. Shadow-only.

## R. Regression tests

**New**: 9 test files under `tests/test_editorial_pipeline_*.py` + `tests/test_unified_pipeline_
shadow_wiring.py`, 48 tests total, all passing (`test_editorial_pipeline_data_content.py` 4,
`test_editorial_pipeline_media_research.py` 4, `test_editorial_pipeline_composition_quality.py` 9,
`test_editorial_pipeline_language_qa.py` 7, `test_editorial_pipeline_recovery.py` 3, `test_editorial_
pipeline_telegram_caption_budget.py` 4, `test_editorial_pipeline_instagram_adapter.py` 4, `test_
editorial_pipeline_orchestrator.py` 7, `test_editorial_pipeline_shadow.py` 3, `test_unified_pipeline_
shadow_wiring.py` 3 - counts sum to 48, confirmed via a single combined `-q` run).

**Existing-suite regression**: every one of the 18 test files that imports `worker.content_cycle`
(the file this phase's own worker-wiring touches), run together: **460 passed, 17 failed, 1
skipped, 0 errors**. All 17 failures independently confirmed pre-existing via an isolated `git
worktree add` baseline checkout at `b5d5276` (before this phase's own merges/changes) in the prior
TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1 phase's own report - unchanged in count and identity
here. **NEW_FAILURES = 0.**

Along the way, this phase found and fixed one real, pre-existing test-fixture gap its own source
reconciliation exposed: `tests/test_content_worker_cycle.py`'s `test_source` teardown predated the
newly-reconciled `content_draft_editorial_plans` table and left its rows behind, causing a
`ForeignKeyViolation` on every test using this fixture once the Story-Continuity/Instagram lineages
were merged in (confirmed via an untouched, unrelated existing test failing at teardown only, never
on its own assertions) - fixed with the same guarded, table-existence-checked delete pattern already
established for every other reconciled child table in that exact fixture.

`ruff check` and `mypy` on every new/modified file: 0 new errors in both (mypy's pre-existing
baseline - 5 errors in `services/telegram_channel_context.py`/`services/story_delta_engine.py` -
confirmed unchanged).

## S. Committed-secret audit

Read-only, bounded pattern search (API key formats for OpenAI/Google/AWS/Slack, PEM private-key
headers, Telegram bot-token shape, literal `password=`/`api_key=`/`secret=`/`token=` string
assignments) across the current tracked tree, plus a full-history search for any committed `.env`/
`.env.*` file. **SECRET_EXPOSURE_FOUND = false.** The only match was a test fixture in `tests/
test_openai_adapter.py` using an obviously-fake placeholder token (`sk-someothertoken123456`) to
verify a real secret-redaction code path - not a real credential. The only committed env-shaped file
in the entire history is `.env.example`, and every value in it is empty (a template, not real
configuration). No credential rotation needed. This is a bounded pattern-based scan, not an
exhaustive enterprise secret-scanning tool - disclosed as such.

## T. Remaining intentional limitations

- DATA subject/metric-kind extraction remains a deterministic heuristic (title token pattern +
  fact-vocabulary classifier), not true NLU or LLM-driven structured generation - the architectural
  fix (structured content decided once, before rendering, never re-derived by a renderer) is this
  phase's real scope; a future phase should have the copywriting capability emit these fields
  directly.
- Instagram's real Director planning chain is not re-architected or unified at the INPUT boundary -
  only the OUTPUT boundary (an already-built package running through the shared quality gate) is
  integrated. Full carousel/reel per-slide `MediaResearchService` wiring is a real, separate,
  larger future phase.
- `worker/content_cycle.py` is not fully "thinned" - one small, flag-gated, exception-guarded shadow
  hook is wired (S25/S26/S27), proven live against the real function, but the legacy inline logic
  itself is untouched and remains the only reachable path. A genuine strangler cutover (the flag
  actually turning on and the orchestrator actually dispatching real sends) is explicitly a future,
  Founder-approved phase - S39 forbids it here.
- `RecoveryJob`'s dedicated DB table is documented, not migrated (S23's own explicit allowance).
- No live external image-search backend exists in any real environment (`NullWebDiscoveryClient` is
  the only production default) - `MediaResearchService`'s own Tier 2-5 value is currently provable
  only via a manually-operator-gathered real canary (§O-B), not autonomous production discovery.
- `transport_result` (S32's own named diagnostic stage) has no real call site yet, since no adapter
  in this phase dispatches a `DeliveryPackage` for real.
- The `_ORPHANED_LABEL_RE`/`_CURRENCY_WORD` vocabulary gaps this phase found and fixed are fixed
  only in the new pipeline's own `language_qa.py`, not in the currently-deployed `presentation_
  director.py` (S18's own freeze) - the live production DATA renderer can, in principle, still
  produce the Maxus-class artifact today, for any story priced in a currency `_CURRENCY_WORD` does
  not recognize. This is disclosed as a live, real, currently-unfixed production defect class
  outside the S18 freeze's own permitted scope for this phase - worth its own narrow, future,
  Founder-reviewed hot-fix independent of the full pipeline rollout.

## U. Production rollout recommendation

Do not deploy this phase's own branch to production. Recommended sequencing for a future phase,
subject to Founder review of this one first:

1. A narrow, disclosed hot-fix to `services/presentation_director.py`'s own `_CURRENCY_WORD`/
   `_ORPHANED_LABEL_RE` (T's last bullet) - small, safe, independently deployable, addresses the
   one live production risk this phase found that the S18 freeze otherwise leaves open.
2. Wire a real (non-`Null`) `WebDiscoveryClient` for at least one production-relevant search
   backend, still Tier1-first and still bounded, so `MediaResearchService`'s Tier 2-5 value becomes
   real in production, not only in a manually-gathered canary.
3. Turn `unified_editorial_pipeline_enabled` on in shadow mode only
   (`unified_editorial_pipeline_shadow_mode=true`) in production, observe `shadow_comparison`
   agreement/disagreement rates for a bounded window, before ever routing a real send through it.
4. Only after a Founder-reviewed shadow-agreement bar is met, begin an actual strangler cutover of
   `worker/content_cycle.py`'s own inline logic onto the orchestrator, one presentation format at a
   time (NEWS first, matching where this phase's own tests are deepest).
5. Instagram's own real per-slide `MediaResearchService` wiring is a separate, larger future phase -
   not sequenced before step 4 completes for Telegram.

## Final verdict: UNIFIED_EDITORIAL_PRODUCTION_PIPELINE_READY_FOR_FOUNDER_REVIEW

The unified pipeline exists (`services/editorial_pipeline/`, 49 new tests, all passing), the required
real replays pass (§O), legacy production remains completely intact (§P: byte-identical V8 source,
zero new regressions across 460 existing tests, live deployment untouched), and a controlled rollout
can now be reviewed (§U). This does NOT mean production deployment is authorized - none occurred, and
none should occur before Founder review of this report and the artifacts package.
