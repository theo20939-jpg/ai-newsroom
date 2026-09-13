# Unified Editorial Pipeline — Runtime Closure 1 — Report

**Phase**: UNIFIED-EDITORIAL-PIPELINE-RUNTIME-CLOSURE-1
**Branch**: `feature/unified-editorial-pipeline-runtime-closure-1`
**Base**: `839edb2` (docs-only on top of `1815433b5`, confirmed zero-diff before starting)
**Scope**: code + tests + review artifacts only. No production deploy, no flag enable, no sends.

This report contains no credential or secret values.

---

## A. Source / base reconciliation

Confirmed `git diff 1815433b5 839edb2` = one file, the production-cutover-1 report (273 insertions,
0 implementation changes). Used `839edb2` as the new worktree base, per §0's own instruction. Fresh
isolated worktree created at a new path via `git worktree add`, never touching the production
checkout or the prior `final-hardening-1` worktree.

## B. Founder audit findings reproduced

All five were confirmed as REAL, then fixed as one coherent chain (never independently):

- **Gap A (same-asset divergence)**: `telegram_integration.py` captured `photo_bytes` via closure
  BEFORE `MediaResearchService.research()` ran, and the render callback used it unconditionally,
  never checking it against `media_selection.selected`. Dormant today only because the candidate
  pool was always exactly 1 (see Gap D) - fixing D alone, without fixing A, would have made this a
  live bug. Fixed together (§D/§F below).
- **Gap B (visual-required silent text-only demotion)**: when a legacy candidate's bytes couldn't
  be read (expired/missing storage) but `media_selection.selected` was still set, the render
  callback returned `(None, html)` - the orchestrator's own `require_media` check had already
  passed (a candidate WAS selected), so this reached `send_to_editorial_destination()` (an ordinary
  text send) instead of `send_photo_to_editorial_destination()`. Reproduced exactly as Case A in
  `tests/test_unified_pipeline_media_asset_resolver.py::
  test_case_a_no_bytes_no_file_id_fails_resolution_never_silently_text_only` before the fix (the
  resolver itself; the end-to-end render-callback proof is
  `tests/test_unified_pipeline_same_asset_invariant.py::
  test_r5_missing_local_storage_no_file_id_holds_never_text_only`).
- **Gap C (weak production MediaIntent/subject verification)**: `_extract_subject_from_title()`'s
  regex (`[A-Z][a-zA-Z]*\s+\d+`) cannot match "iPhone 17" (lowercase leading `i`), "GPT-6" (hyphen,
  not space), "Dario Amodei"/"OpenAI"/"foldable iPhone" (no digit). Reproduced directly in
  `tests/test_unified_pipeline_subject_extraction.py` (each case named after the exact failure).
- **Gap D (candidate pool prematurely reduced)**: `_resolve_single_photo_candidate()` truncated the
  eligible pool to `limit=1` via legacy ranking BEFORE `MediaResearchService`/subject verification
  ever ran - real multi-candidate truthfulness comparison (the entire point of Tier-based
  discovery) was structurally impossible for Tier-1 candidates.
- **Gap E (recovery lacks a coherent execution lifecycle)**: `recovery_jobs` rows could sit in
  `PENDING`/`RETRYING` with a real `next_retry_at` that nothing ever consulted -
  `worker/content_cycle.py` has no logic that calls `RecoveryService.due_for_retry()` or re-enters
  the pipeline for an open recovery job. Confirmed by direct grep (zero matches). Additionally,
  `find_open_recovery()` looked up by `content_draft_id` alone (no platform scoping) and had no
  DB-level concurrency guarantee.

## C. Root causes

1. The render callback was constructed and had its inputs bound BEFORE the orchestrator's own
   media-research stage ran - an architectural inversion (render should never know about media
   before selection decides it).
2. Legacy ranking (`_select_top_ranked_image_candidates(limit=1)`) was applied as if it were the
   final authority, when `MediaResearchService` was supposed to be that authority.
3. `_extract_subject_from_title()` was written and tested against the one shape it was designed
   for (`Word\s+\d+`), never against the broader shape space real titles actually take.
4. `RecoveryJobState`'s own real, tested state machine was built one phase before anything was
   built to consume it - a common, disclosed "shadow the seam before wiring the seam" pattern that
   was never closed.

## D. Final media authority model

See `artifacts/unified_pipeline_runtime_closure_1/01_runtime_authority_diagram.md` and
`02_media_ownership_diagram.md`. Summary: `MediaResearchService` remains the SOLE final-selection
authority (§3.4, unchanged architecture from final-hardening-1); this phase's fixes ensure it
actually receives a real, bounded, multi-candidate pool (§F) and that its decision is what every
downstream stage actually uses (§E/§K).

## E. MediaIntent production extraction

New module `services/editorial_pipeline/subject_extraction.py` - deliberately separate from
`content._extract_subject_from_title()` (which stays untouched, avoiding any DATA-label
regression risk - R7 verified clean, see §W). Two-tier extraction: a versioned-model pattern
(brand token + digit/version suffix, handles "iPhone 17"/"GPT-6"/"Maxus 9"/"PlayStation 6") and a
proper-noun-run/bare-brand-token fallback (handles "Dario Amodei"/"OpenAI"/"foldable iPhone"). No
brand/company/person name is hardcoded anywhere in the module (verified by a dedicated test using
invented names: "Zorblex"/"Nyquora-8"). `build_visual_intent_from_evidence()` now uses this
extractor to populate `model_name`/`product_name`/`person`/`primary_entity` truthfully.

**§32 production-shaped tests** (not hand-built ideal `MediaIntent` objects - built through the
REAL entrypoint): `tests/test_unified_pipeline_subject_extraction.py` covers foldable iPhone,
iPhone 17, GPT-6, Dario Amodei, Maxus 9, PlayStation hardware, an automotive model, and a
concept-only fallback (never fabricates a subject when none exists).

## F. Candidate pool / discovery

`_resolve_single_photo_candidate()` renamed to `_resolve_photo_candidate_pool()`, bound removed
from `limit=1` to `limit=MAX_CANDIDATE_POOL_SIZE` (10 - chosen to match `MediaResearchService`'s
own existing `max_web_candidates_to_classify=8` cost characteristic, documented in-code). Legacy
ranking still orders the pool; it no longer decides the winner alone.

## G. Subject verification

`services/editorial_pipeline/subject_match.py::classify_subject_match()` is unchanged (already the
real, central, deterministic, evidence-based authority from final-hardening-1). This phase adds an
honest gap disclosure: it is text-evidence-only (`caption_or_alt`), and legacy Tier-1 candidates
never carry that text - see §X for the disclosed limitation and §H for why a real vision-based
second tier was not wired into the live path this phase.

## H. Web/official discovery

`services/media_web_discovery.py::discover_web_candidates()` already implements bounded Tier 2-4
discovery (max query variants, max results per query, dedup by asset_url). This phase found and
fixed a real bounds gap during testing: the function trusted `client.search()` to honor
`max_results` rather than enforcing it itself (`hits[:max_results_per_query]` added - proven by
`tests/test_unified_pipeline_bounded_web_discovery.py::
test_results_per_query_are_bounded_even_when_the_client_returns_more`, which failed before the
fix). `run_unified_telegram_delivery()` now accepts an injectable `web_discovery_client` parameter
(defaults `None` -> `NullWebDiscoveryClient`, zero network calls, unchanged behavior) - structural
wiring only. **No real, automated search-API backend exists anywhere in this codebase** (confirmed
by direct audit, matching the module's own pre-existing docstring) - building one was out of this
phase's safe scope (a genuinely new external-service integration, not a runtime-ownership fix).
See §Y/§46 for the honest `WEB_DISCOVERY_WIRED` determination.

## I. Provenance / rights

`services/media_candidate_scoring.py::is_selectable()` now excludes `EDITORIAL_REVIEW_REQUIRED` in
addition to `NOT_USABLE`/`MISMATCH` (previously only the latter two were hard-excluded - a
rights-unverified third-party photo could win automatic selection on subject-match/score alone).
`services/media_research_selection.py` now logs a real, observable rejection reason for this
exclusion (previously silent). Proven at three levels: the scoring unit test
(`test_media_candidate_scoring.py::test_editorial_review_required_is_not_selectable_...`), the
selection-integration test (`test_media_research_selection.py::
test_editorial_review_required_never_wins_automatic_selection`), and the real production-shaped
truthfulness replay (`test_unified_pipeline_media_truthfulness_replay.py::
test_exact_subject_but_rights_unclear_does_not_auto_publish` - a GENUINELY exact-subject candidate
still loses to a rights-clear truthful fallback, proving rights and truthfulness are independent
gates, neither overriding the other, matching §14's explicit instruction).

## J. Final SelectedMediaAsset contract

New `services.editorial_pipeline.contracts.SelectedMediaAsset` (frozen dataclass) - the one object
carrying candidate identity, provenance, rights, subject-match verdict, and resolution
method/telegram_file_id/resolved_bytes from resolution through render/QA/transport. New
`MediaResolutionFailure` sentinel distinguishes "selected but unresolvable" from both a generic
render failure (`None`) and a legitimate text-appropriate composition.

## K. Exact asset resolution

New `services/editorial_pipeline/media_asset_resolver.py::resolve_selected_media_asset()`.
Priority: cached Telegram file_id (reuses `bot/image_preview_media.py`'s own proven policy) ->
local storage bytes -> bounded download (off by default, `allow_bounded_download=False`) ->
failure. Resolves EXACTLY `media_selection.selected` via `legacy_candidates_by_id`, keyed by the
SAME pool the tier1 candidates were built from - structurally impossible to resolve a different
candidate. Proven by `tests/test_unified_pipeline_media_asset_resolver.py` (5 tests, Cases A/B) and
the explicit same-asset test (§ below).

## L. Renderer ownership

`RenderCallable` (orchestrator.py) now takes `media_selection` as a required third argument -
every render callback (including the two test-double sets and `shadow.py`'s passthrough) was
updated. The Telegram renderer (`telegram_integration._make_render_callback`) no longer closes
over any candidate/bytes computed before the orchestrator ran; it resolves the asset at render
time from `media_selection` alone. The frozen V8 renderers themselves
(`apply_master_news_branding`, `render_branded_media`) are byte-for-byte unmodified - only what
feeds them changed.

## M. Quality Gate semantics

`QualityCheckName.FACT_SUPPORT` (which only ever checked "is `content` not None") renamed to
`STRUCTURED_CONTENT_PRESENT` (§20 Option B - semantic honesty, no new checker built).
`CLAIM_TRACEABILITY` (the check that genuinely verifies EvidenceClaim traceability) is unchanged
and remains the real fact-traceability check. `VISUAL_TRUTHFULNESS`/`MEDIA_PROVENANCE` unchanged
(defense-in-depth MISMATCH/NOT_USABLE exclusion at the gate level, on top of `is_selectable()`'s
own exclusion). `selected_candidate_id == rendered_candidate_id == qa_candidate_id` holds
structurally now because all three stages read from the SAME `media_selection`/`SelectedMediaAsset`
- proven by the same-asset invariant test, never a separate diagnostic field needed to detect
divergence (there is no code path left that could produce one).

## N. Telegram transport invariant

Transport (`services.telegram_routing`) is unchanged - still reports SEND/FAIL/AMBIGUOUS only,
never an editorial decision. `AMBIGUOUS_TRANSPORT_RESULT` still forces `TERMINAL_HOLD` on first
occurrence (unchanged, already proven in `test_replay_h_ambiguous_transport_timeout_never_auto_resent`).

## O. Text-only demotion proof

Swept `services/editorial_pipeline/` and `telegram_integration.py` for `except Exception: <text
send>` / `photo is None: <text send>` patterns (§37). Exactly one dangerous instance existed (the
Gap A/B render-callback path); it is now fixed (§K/§L). The three remaining `except Exception:`
blocks in the package (`media.py`'s web-discovery fail-soft, `shadow.py`'s never-surface guard,
`telegram_integration.py`'s branding-exception-to-recovery mapping) all route to a real recovery or
a documented shadow-only no-op, never to a silent text send. `TEXT_ONLY_VISUAL_DEMOTION_FOUND =
false` (see §46).

## P. Recovery lifecycle

`RecoveryJobState` (PENDING/RETRYING/RECOVERED/TERMINAL_HOLD), bounded attempts, deterministic
backoff - all unchanged, already real from the cutover-1 phase. `ContentDraft.status` vs
`recovery_jobs` dual-authority question (§21): this phase did NOT unify them onto one field -
`content_drafts.status` remains the legacy Telegram-only `hold_for_visual` marker (frozen, still in
production), while `recovery_jobs` is the real, durable state for the unified path specifically.
Merging them would touch the legacy `content_drafts.status` handling this phase's own hard freeze
rules discourage touching without a dedicated review - disclosed as a known limitation (§X), not
silently left implicit.

## Q. Recovery concurrency/platform identity

`find_open_recovery()` now takes `platform` and filters by it (previously
`content_draft_id`-only - a Telegram recovery could have found/incremented an Instagram recovery
row for the same draft). New DB-level partial unique index
`ix_recovery_jobs_open_lifecycle_identity` on `(content_draft_id, platform)` WHERE state is
open - real concurrency safety, not merely a Python-side check.
`create_or_retry()` uses a SAVEPOINT (`begin_nested()`) around the insert path and recovers from a
genuine `IntegrityError` by re-reading and incrementing the row that won the race. Both proven with
real Postgres behavior (migration applied to the isolated test DB only) - see §46/artifacts.

## R. Replay results

| Replay | Result |
|---|---|
| R1 foldable iPhone, exact present | PASS (exact wins - pre-existing test, still passes) |
| R2 wrong-only iPhone | PASS (never rendered/sent - pre-existing test) |
| R3 exact ranked second (lower legacy score) | PASS (`test_low_quality_exact_candidate_beats_high_quality_mismatch_at_selection`) |
| R4 missing local storage, valid file_id | PASS (NEW - delivers via same selected asset) |
| R5 missing local storage, no file_id | PASS (NEW - HOLD, never text-only) |
| R6 caption too long | PASS (pre-existing `test_replay_f_caption_too_long_never_completes_text_only`) |
| R7 Maxus DATA | PASS (pre-existing `test_editorial_pipeline_data_content.py` + `test_replay_d`, unaffected by this phase's subject-extraction changes - verified by rerun) |
| R8 named person (Dario Amodei vs wrong exec) | PASS (NEW) |
| R9 GPT/model (GPT-6 vs generic company photo, vs earlier generation) | PASS (NEW) |
| R10 transport ambiguity | PASS (pre-existing `test_replay_h_ambiguous_transport_timeout_never_auto_resent`) |
| R11 recovery concurrency | PASS (NEW) |
| R12 cross-platform recovery identity | PASS (NEW) |

## S. Flag-off zero-diff

Zero legacy-path files touched (`worker/content_cycle.py`, `bot/*`, `services/telegram_routing.py`,
`services/brand_renderer.py`, `services/presentation_director.py` all unmodified - confirmed via
`git status`). `services/media_candidate_scoring.py`/`media_research_selection.py` are used ONLY by
the unified `MediaResearchService` (confirmed: zero references in `worker/content_cycle.py`).
`tests/test_router_media_integration.py` (the real legacy-path suite) re-run in full: 68 passed, 2
pre-existing failures unrelated to this phase (a keyboard-count assertion, present before this
phase's changes, in a file this phase never touched). **FLAG_OFF_REGRESSION = ZERO_DIFF.**

## T. Story Memory/arXiv freeze

Not touched. No file under `services/story_memory.py`, `services/story_identity_guard.py`, or any
arXiv-identity module was read for modification purposes (only referenced in an earlier
exploratory grep, never edited). `STORY_MEMORY_CHANGED = false`, `ARXIV_GUARD_CHANGED = false`.

## U. Telegram V8 freeze

`services/brand_renderer.py`, `services/nnj_master_news_overlay.py`, `services/news_telegram_presentation.py`
were NOT modified. Only their call sites' INPUTS changed (real resolved bytes/file_id instead of a
pre-captured value) - the renderers themselves are byte-for-byte identical.
`TELEGRAM_V8_CHANGED = false`.

## V. Instagram/publication safety

`services/instagram_publish_adapter.py` untouched. `services/editorial_pipeline/platforms/instagram.py`
received only the mechanical `FACT_SUPPORT` -> `STRUCTURED_CONTENT_PRESENT` rename (same behavior,
new name). No Instagram publication code path was enabled or exercised.
`INSTAGRAM_PUBLICATION_ENABLED = false` (unchanged code default).

## W. Test results

See `artifacts/unified_pipeline_runtime_closure_1/04_changed_files_and_test_summary.md` for the
full batch-by-batch breakdown. Headline: **197 passed / 0 failed** across every touched-or-new test
file in one combined run; **68 passed / 2 pre-existing-unrelated failures** on the legacy
flag-off path. `ruff`/`mypy` clean on every new/modified source file (one real new mypy error and
one real new test-bounds gap were found and fixed DURING this phase's own verification, not left
in place - see artifact 04).

Fixture note: several pre-existing tests (`test_media_candidate_scoring.py`,
`test_media_research_selection.py`, `test_unified_pipeline_media_truthfulness_replay.py`) had a
default `usage_classification=EDITORIAL_REVIEW_REQUIRED` fixture that inadvertently relied on the
exact gap this phase closes (§I) to keep passing - each was fixed to use a rights-clear default
where the test's actual purpose is unrelated to rights, with a NEW, dedicated test added alongside
proving the rights-exclusion behavior explicitly (never simply "loosened" to make the old test
pass).

## X. Remaining known limitations (disclosed, not blockers unless noted)

1. **`ACTUAL_IMAGE_VERIFICATION_WIRED = false`.** `capabilities/media_subject_match_capability.py`
   (real vision-LLM subject verification) is still never invoked from any live production path
   (`capabilities/executor.py::_build_context()` never populates the fields it needs - confirmed,
   unchanged from before this phase). `classify_subject_match()` remains text-evidence-only; a
   Tier-1 legacy candidate with no `caption_or_alt` text can only ever reach `GENERIC_CONTEXT`,
   never `EXACT_SUBJECT` or `MISMATCH`. Wiring the real vision capability into the live call site
   requires passing a `CapabilityRegistry`/gateway into `run_unified_telegram_delivery()` - a
   `worker/content_cycle.py` call-site change this phase deliberately did not make (that file is
   the legacy/unified dispatch boundary; expanding its blast radius for this needs its own
   dedicated, reviewed phase, not a rider on this one). **This is the one item genuinely short of
   full closure against §47's literal bar** - disclosed honestly rather than claimed done.
2. **`WEB_DISCOVERY_WIRED` is structural-only, not backend-connected.** No automated search-API
   client exists anywhere in this codebase (confirmed by direct audit). The injection point exists
   (`web_discovery_client` parameter, §H); nothing is plugged into it. The truthful fallback that
   prevents false depiction in its absence: `is_selectable()`/`require_media` now correctly HOLD
   rather than falsely depict when no verified candidate exists, closing the actual safety gap even
   without richer discovery.
3. **Recovery execution is Option B (no automatic consumer)**, disclosed and justified in
   `services/editorial_pipeline/recovery_execution_policy.py` - the concrete, specific reason is
   that `recovery_jobs` does not yet persist enough state to safely re-enter the pipeline
   (`copywriting_output`/`treatment`/etc. are not stored). Not a blocker per §47 (which requires a
   policy, and permits either option; Option A was explicitly gated on "genuinely safe and fully
   tested", which building an unsolved re-entry mechanism this phase would not have been).
4. **NEWS's file_id-only resolution path skips re-branding.** When only a cached Telegram file_id
   is available (no local bytes), NEWS delivers that cached asset directly without re-applying the
   master-news corner-mark overlay this specific call (disclosed trade-off, §K/L) - a real, correct-
   subject photo is judged preferable to a HOLD here, matching Case B's own explicit priority.
5. **KNOWN_SAFE_LIMITATION_DATA_TYPOGRAPHIC_FALLBACK** - unchanged, not touched, per §27's explicit
   instruction. Verified no change made it less truthful (R7 DATA replay unaffected).
6. **`content_drafts.status` vs `recovery_jobs` dual authority** (§21) not unified this phase -
   disclosed in §P above, not silently left ambiguous.

## Y. Production cutover recommendation

Do not cut over yet. Item X.1 (`ACTUAL_IMAGE_VERIFICATION_WIRED=false`) means Tier-1 legacy
candidates with no descriptive text still cannot be positively confirmed EXACT or rejected as
MISMATCH by anything beyond text evidence - the truthfulness improvements this phase makes are real
and structural (bounded pool, rights exclusion, same-asset invariant, no silent text-only
demotion), but the SPECIFIC "wrong ordinary photo reused for a new distinct product" failure class
the whole lineage was founded on is only closed when real descriptive text exists for a candidate
(true for Tier 2-5 web-discovered candidates once a real backend exists; NOT yet true for the
common Tier-1-only case with no web discovery). Recommend: (a) Founder reviews and either approves
Option B's recovery-execution disclosure or requests the schema work Option A needs; (b) a follow-
up phase wires a real, bounded, cached vision-verification call for the Tier-1-no-caption case
specifically (the concrete, narrow gap X.1 describes) before any further production cutover
attempt.
