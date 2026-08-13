# POST-ACCEPTANCE FOLLOW-UP CHECKPOINT

Scope: three narrow follow-ups from the NEWS Stability Acceptance Canary Report (`docs/news_stability_acceptance_canary_report.md`), executed against committed HEAD `c308d45f6d55dc895eabe24b1901e1f99f855bbe`. No video work, no source-pack integration, no deploy, no long live canary. Not committed, not pushed.

## A. Multi-crop dedup

### Root cause

The real acceptance-run albums that showed the same underlying photograph 2-3 times (the $70M SF-estate Guardian album and the Apple/iCloud Private Relay CNET album) shared one exact, deterministic signal in every case: **their `final_url`s were byte-identical once the query string was stripped** — the same CDN base path, differing only by resize/crop query parameters (`?width=1200&height=630...` for Guardian's Fastly-based image service; `?resize=1200%2C900` for CNET's WordPress-native resize convention).

`worker/content_cycle.py`'s existing `_compute_within_event_duplicate_flags()` (Case E, from the earlier NEWS Stability Fix phase) already computed this exact normalized origin via `_normalize_image_origin()` — but only ever used it to *gate a relaxed Hamming-distance threshold* (`_SAME_ORIGIN_NEAR_DUPLICATE_MAX_HAMMING_DISTANCE = 10`), never as an independent, sufficient signal on its own. The real measured perceptual-hash Hamming distances between the same-source crop variants were 12-28 — well above that relaxed threshold too (different crop/aspect-ratio params shift the hash more than a same-crop re-encode does), so the gate never fired and every variant survived as a "distinct" candidate.

Exact reconstructed evidence:

| Album | Base file (query stripped) | Candidates sent | Pairwise Hamming distances |
|---|---|---|---|
| SF estate (Guardian) | `i.guim.co.uk/img/media/7d9d381f.../785_0_3702_2962/master/3702.jpg` | rank1 (1200×630), rank2 (1200×1200), rank3 (1200×900) | 1↔2: 28, 1↔3: 26, 2↔3: 14 |
| Apple/iCloud (CNET) | `www.cnet.com/wp-content/uploads/sites/2/7d5d5d73-...jpg` | rank1 (2048×1216, no resize param), rank2 (`?resize=1200,1200`), rank3 (`?resize=1200,900`) | 1↔2: 22, 1↔3: 12, 2↔3: 18 |

### Exact fix

`worker/content_cycle.py::_compute_within_event_duplicate_flags()`: same normalized origin is now an **independent, hash-free** duplicate signal (checked second, after exact sha256, before the general perceptual-hash check) — matching the requested priority order (exact hash → normalized same-source identity → perceptual). The pre-existing origin-AND-hash-gated branch (`_SAME_ORIGIN_NEAR_DUPLICATE_MAX_HAMMING_DISTANCE`) became fully unreachable dead code once the unconditional check was added (any candidate whose origin matches is now caught before the hash loop ever runs) — removed rather than left as confusing dead code; the general, origin-independent perceptual check (existing global threshold, `services/media_ranking.py`, untouched) is unaffected.

`_normalize_image_origin()` also now strips a trailing WordPress "intermediate image size" filename suffix (`-1200x900.jpg` → `.jpg`) from the path itself, in addition to its existing query-string stripping and Jetpack/Photon CDN-proxy unwrapping — a second, real, deterministic same-source-asset pattern the brief explicitly asked to check for (not exercised by either real failure, which both used query-string resize params, but a genuine, common CMS convention worth covering).

**Product invariant preserved exactly as specified**: two candidates only ever collapse to one slot when they share the *same source file* (normalized origin match) — a genuinely different photo at a different path is completely untouched by this check, verified by a dedicated new control test (below). The global cross-story `_NEAR_DUPLICATE_MAX_HAMMING_DISTANCE` constant and `services/media_ranking.py`'s own cross-story reuse mechanism were not touched at all.

### Before/after on the real examples

| | Before | After |
|---|---|---|
| SF estate album | 3 images sent (`send_media_group`, media_count=3) | 1 image sent (`send_photo`) — ranks 2 and 3 now flagged duplicate of rank 1 |
| Apple/iCloud album | 3 images sent (`send_media_group`, media_count=3) | 1 image sent (`send_photo`) — ranks 2 and 3 now flagged duplicate of rank 1 |

Verified directly against `_compute_within_event_duplicate_flags()` using the real acquisition rows' own recorded URLs/hashes (new unit tests, not simulated data).

### A deliberate, disclosed test-expectation correction

An existing test, `test_genuinely_different_crop_of_the_same_base_file_both_remain`, previously asserted that a same-base-file, different-crop Guardian pair (Hamming distance 36, real fixture from an earlier phase) must remain **distinct**. Under the corrected policy this exact fixture now collapses to one slot too — same base file, just a different crop transform of the identical source photograph, precisely what the new product invariant targets. Renamed to `test_same_base_file_crop_variants_are_now_deduplicated_to_one_slot` with its new expected behavior, and its lost "truly distinct photos at different paths must remain eligible" coverage was replaced by a new, dedicated control test (`test_genuinely_different_images_at_different_paths_both_remain`) using two different base paths with the same (previously-passing) hashes.

### Tests

- `tests/test_router_media_integration.py`: `test_same_base_file_crop_variants_are_now_deduplicated_to_one_slot` (renamed/updated), `test_genuinely_different_images_at_different_paths_both_remain` (new control), `test_compute_within_event_duplicate_flags_guardian_crop_pair_directly` (updated expectation), `test_compute_within_event_duplicate_flags_real_sf_estate_album_directly` (new, real acceptance-run URLs/hashes), `test_compute_within_event_duplicate_flags_real_cnet_apple_album_directly` (new, real acceptance-run URLs/hashes), `test_normalize_image_origin_strips_wordpress_dimension_suffix` (new).
- All pre-existing Honor/Photon-CDN and exact-duplicate/near-duplicate tests re-verified unaffected (unchanged assertions, still passing).

## B. UPDATE cost path

### Exact first point non-deliverability was already known

Traced both real fail-closed candidates (Twitch/Amazon AI-training story, `story_id=eb0fa8fb-...`) end-to-end via their persisted `EditorialTask`/`AIExecution` rows:

- **Story Memory classification** (`NewsEventStoryLink.match_type = STORY_UPDATE`, `story_id`) is set at **TRIAGE time**, inside `services/triage_orchestrator.py::_apply_story_memory()` — part of collection+triage, *before* NEWS_ANALYSIS and *long before* CONTENT_GENERATION.
- **Root resolvability** (`services/story_telegram_delivery.py::get_root_delivery(story_id)`) depends only on `story_id`, already available at that same triage moment.
- Both pieces of information the fail-closed decision needs are therefore structurally knowable **before NEWS_ANALYSIS ever runs**, not just before CONTENT_GENERATION.

### What actually ran anyway, and what was and wasn't waste

Real `AIExecution` rows for both candidates:

| Stage | Candidate 1 (`edb95389...`) | Candidate 2 (`4fe65bba...`) |
|---|---|---|
| NEWS_ANALYSIS: Research | $0.001746 | $0.001246 |
| NEWS_ANALYSIS: Intelligence | $0.001738 | $0.001757 |
| NEWS_ANALYSIS: Engagement | $0.001675 | $0.001866 |
| NEWS_ANALYSIS: Scoring | $0.000833 | $0.000954 |
| CONTENT_GENERATION: Copywriting | $0.006857 | $0.007515 |
| CONTENT_GENERATION: Quality | $0.000794 | $0.001437 |
| **Total** | **$0.013643** | **$0.014775** |

Critically, **NEWS_ANALYSIS is not itself wasted by proceeding regardless of story-update/root status** — it's the same mass eligibility/scoring evaluation every collected event requires before content generation is even considered, independent of what Story Memory later concludes about root-resolvability, and `capabilities/executor.py`'s own existing cost-optimization already **reuses** those NEWS_ANALYSIS Research/Intelligence results for CONTENT_GENERATION rather than paying for them twice (confirmed: no second Research/Intelligence row appears at the later CONTENT_GENERATION timestamp). The genuinely wasted work — spent *after* non-deliverability was already structurally knowable, and *only* because of it — is exactly the CONTENT_GENERATION-stage Copywriting + Quality calls: **$0.007651 + $0.008952 = $0.016603** across the two real candidates, roughly 58-61% of each candidate's total cost.

### New short-circuit

Added `services/story_duplicate_guard.py::check_update_would_fail_closed()` (same module/style as the existing pre-generation `check_duplicate_story_delivery()` gate), wired into `worker/content_cycle.py` immediately before the `run_content_generation_for_event()` call — reusing the exact same `NewsEventStoryLink` + `get_root_delivery()` + `determine_reply_target()` the late, real reply-routing check already uses (never a second, divergent rule; extracted the shared `is_story_update_match()` predicate into `services/story_memory.py` so the early and late checks can never silently diverge).

**Fail-closed product policy is completely unchanged** — the late, real reply-routing check in `worker/content_cycle.py` is untouched; this only prevents paying for CONTENT_GENERATION on a candidate that check would have dropped anyway.

**Why moving the check earlier is safe** (the "could later resolve a root" requirement): the root's own resolution is driven entirely by a *separate* event's own asynchronous processing timeline — it does not depend on, and is not accelerated by, whether *this* candidate's own Research/Copywriting happens to run in the meantime. Checking immediately before CONTENT_GENERATION rather than immediately after does not remove any wall-clock time the root would otherwise have had to resolve; if anything it checks *sooner*, which is only ever more conservative, never less. The gate is a no-op (falls through to normal processing) whenever `telegram_story_reply_mode != "enforce"` — "shadow" continues to generate and deliver as a standalone post exactly as before, purely to keep observing the would-be-fail-closed rate, matching the existing documented shadow-mode contract.

### Tests

- `services/story_memory.py`: `is_story_update_match()` — pure predicate, extracted from `services/content_draft_service.py`'s own inline check (now calls the shared function; behavior byte-identical, `NEW_STORY`/`UNCERTAIN_MATCH` excluded, everything else counts as update-equivalent).
- `tests/test_story_duplicate_guard.py`: `test_is_story_update_match_true_for_every_confident_outcome`, `test_is_story_update_match_false_for_new_story_uncertain_and_none`, `test_update_fail_closed_check_is_noop_unless_enforce`, `test_update_fail_closed_check_true_when_no_root_under_enforce`, `test_update_fail_closed_check_false_when_root_resolvable_under_enforce`, `test_update_fail_closed_check_false_for_new_story`, `test_update_fail_closed_check_false_with_no_story_link`.
- `tests/test_content_cycle_story_delivery.py`: `test_enforce_mode_story_update_with_no_root_short_circuits_before_generation` (proves `run_content_generation_for_event` is never called), `test_enforce_mode_story_update_with_resolvable_root_still_generates_and_sends` (control — resolvable root proceeds exactly as before), `test_new_story_never_short_circuited_by_the_update_fail_closed_gate` (control — NEW_STORY unaffected), and the existing `test_enforce_mode_story_update_with_no_root_fails_closed_never_sends` updated to assert the new counter (`update_fail_closed_before_generation`) instead of the old one (`story_fail_closed_review`, now 0 for this case since the late check is never reached).
- Telegram behavior for every other path (resolvable UPDATE, NEW_STORY, shadow mode) verified unchanged — no send-call-site or rendering code was touched, only the pre-generation gate.

## C. Article acquisition / quote architecture

### Exact current mode semantics (reconstructed from `core/config.py` + every real consumer)

- **`off`**: zero network calls, zero processing. No `NewsEventArticleAcquisition` row is ever created.
- **`shadow`**: the article *is* fetched and persisted (real network call, identical to `enforce`) between CONTENT_GENERATION task creation and `WorkflowRunner.run()`. Two, and only two, downstream consumers are active:
  - `capabilities/executor.py`'s `quote_source_text` mechanism (Phase 23.1P) — gated `!= "off"`, so **already active in shadow** — reads `raw_extracted_text` directly, cleans it on the fly via `services/article_cleaning.py::clean_extracted_text()`, and threads it into Copywriting's prompt as the quote-sourcing excerpt.
  - `services/editorial_treatment.py`'s weak-completeness gate — already consults `effective_completeness_status` directly off the acquisition row, independent of evidence_package, unaffected by this mode either way.
  - Everything else — Research's own input, and `content_draft_service.py`'s quote-*verification* source text — stays on the thin `news_event.content` RSS field.
- **`enforce`**: additionally activates `services/evidence_package.py::build_evidence_package()` in two more places: Research's `article_evidence_text`/`article_evidence_completeness` (`capabilities/executor.py`, gated `== "enforce"` specifically), and quote-*verification*'s `source_content` (`content_draft_service.py`, also `== "enforce"`-gated).

### Why quotes were actually starved — a more precise finding than the acceptance report's framing

Two separate, compounding causes, not one:

1. **A real, confirmed architectural bug, unrelated to the mode setting**: `NewsEventArticleAcquisition.cleaned_text` — the column `build_evidence_package()`'s primary branch reads — is **never populated by any production write path**. Confirmed empirically against the real dev database: **0 of 210** real acquisition rows have `cleaned_text` set, despite **109** having `raw_extracted_text`. The original Phase 19 M2 design (`services/article_cleaning.py`'s own module docstring: "`raw_extracted_text -> clean_extracted_text() -> cleaned_text`, persisted directly on the same row") was never actually wired into the acquisition write path. This means **`article_acquisition_mode = "enforce"` was silently a no-op for its own documented purpose** — flipping it, as currently written, would change nothing for Research or quote-verification, because the one condition that unlocks the "real article" branch could never be true.
2. **In this specific 9-post acceptance sample, the LLM itself likely never had genuinely quotable material to work with** — `prompts/copywriting/v8.6.yaml` deliberately requires a quote to be a verbatim (or verbatim-translated) direct quote, explicitly instructs "when the source contains only indirect or reported speech, set quote to null," and the 9 real stories (a lawsuit filing, a funding round, a corporate appointment, a procedural court ruling, etc.) are exactly the kind of wire-service news that rarely contains a punchy, quotable individual statement. `copywriting_output.get("quote")` was `null` in the raw LLM output for all 9 — before verification was ever reached — so this is very plausibly correct, conservative behavior on this sample, not a pipeline failure. (A genuinely different sample with interview- or press-conference-style sourcing would very likely exercise the quote path successfully even today.)

A related, now-moot finding: even where the LLM *does* propose a genuine quote (via the already-shadow-active `quote_source_text` channel), `content_draft_service.py`'s verification step checks it against `source_content`, which stays the bare RSS excerpt in shadow mode — a real quote extracted from the full article would very likely fail verification there and get silently dropped, logged as `quote_failed_verification_dropped`. `enforce` (once cause 1 above is fixed) closes exactly this mismatch, verifying against the same rich text Copywriting was shown.

### Recommended runtime mode/policy

**`enforce` is the already-intended, already-designed finished architecture** for this exact purpose (`core/config.py`'s own docstring: `"enforce"`: Research/quote-verification read the persisted evidence via `services.evidence_package` instead) — not a new direction. Every consumer already has a SAVEPOINT-guarded, broad-except degradation path back to the pre-Phase-19 `news_event.content` behavior (`tests/test_evidence_package_call_sites.py` structurally enforces this for every caller), so the "preserve existing safe fallback for failed/low-quality acquisition" requirement is already met by the existing implementation once cause 1 is fixed.

**Recommendation: fix cause 1 (done below, code-level, mode-independent), then flip `article_acquisition_mode` to `enforce`** as a deliberate, separate rollout decision — not automatically executed this phase (`.env` untouched; this is a "do not deploy" phase).

### Small wiring change implemented (why, before doing it)

Rather than wire `cleaned_text` persistence into the acquisition write path (a larger, riskier change touching the fetch/write pipeline itself, effectively completing a different, unstarted Phase 19 M2 milestone), `services/evidence_package.py::build_evidence_package()` now mirrors the exact, already-proven, already-shadow-active `quote_source_text` pattern: when `acquisition.cleaned_text` is empty (the real, universal case today) but `raw_extracted_text` exists at a trusted completeness tier, it computes the cleaned text on the fly via the same `clean_extracted_text()` call `capabilities/executor.py` already uses — same function, same already-tested cleaning rules, no new capability, no new transport path, still reading the exact same already-persisted `raw_extracted_text` column via the exact same already-existing `get_effective_acquisition()`. If `cleaned_text` ever does start being persisted directly, that branch is checked first and used as-is with zero further changes needed.

"Trusted completeness tier" reuses `FULL_TEXT`/`PARTIAL_TEXT` — the exact same two statuses `quote_source_text`'s own already-proven condition already trusts (not `SUBSTANTIAL_TEXT`, matching that existing precedent exactly rather than introducing a third, slightly different definition of "good enough"). `HEADLINE_ONLY`/`REDIRECT_UNRESOLVED`/`FETCH_FAILED`/`PAYWALLED`/`UNSUPPORTED_CONTENT_TYPE` acquisitions never have their `raw_extracted_text` (if any exists at all) trusted as "full article" evidence — they fall back to the `rss_excerpt`, exactly as before this fix.

### What changes, precisely, if `enforce` is flipped (with this fix applied)

- **Research inputs**: `article_evidence_text` becomes populated (real acquired+cleaned article text) instead of staying `None`. Practical effect varies by source: for RSS feeds with already-rich description fields (confirmed real example: Techmeme's `news_event.content` already ran 795 characters and already contained the same key facts a full acquisition would add — Sequoia Capital, Wellington Management, $750M, $40B valuation), the marginal uplift is small; for thin-RSS sources (bare headline only), the uplift is a genuine, likely-meaningful improvement in factual grounding.
- **Copywriting inputs**: unchanged. `quote_source_text`'s own gate (`!= "off"`) is untouched by `enforce` specifically — Copywriting already sees the same quote-sourcing excerpt in shadow mode today.
- **Quote extraction/verification**: real, meaningful change — `source_content` used for `verify_quote()` upgrades from the thin RSS excerpt to the same rich text Copywriting saw, closing the shadow-mode verification mismatch described above.
- **Evidence completeness/gating**: unchanged — `editorial_treatment.py`'s weak-completeness SKIP/downgrade gate already reads the acquisition row directly, independent of this mode.
- **Latency**: one additional `build_evidence_package()` call (a couple of in-process DB reads: `NewsSource` lookup, `get_effective_acquisition()`, an optional story-link lookup) for the Research step only (already scoped to `step.capability == "research"`) — no new external network fetch.
- **External fetch/network behavior**: **completely unchanged**. The actual article fetch is gated on `article_acquisition_mode != "off"` — identical in shadow and enforce. Enforce changes only whether the *already-fetched* result is read downstream, never whether or how often the fetch itself happens.
- **Cost**: no new LLM calls (same call count for Research/Copywriting/Quality); a likely modest increase in input tokens (and therefore marginal cost) per Research call when a real, longer article was acquired, bounded by the existing `article_acquisition_max_extracted_chars = 20,000` cap.
- **Fallback/failure behavior**: unchanged — every consumer already degrades to the pre-Phase-19 path on a missing/failed acquisition or a missing migration, in both shadow and enforce, before and after this fix.

### Risks

- Never live-validated: `enforce` has never been exercised against real natural traffic (this phase's own wiring fix is untested live, only via focused unit/integration tests against real DB rows) — the proposed §E follow-up canary exists specifically to close this gap before treating it as fully proven.
- Marginal cost increase for Research calls on acquisition-success events, not yet quantified against a live sample.
- The completeness-tier gate (`FULL_TEXT`/`PARTIAL_TEXT` only) intentionally excludes `SUBSTANTIAL_TEXT` for consistency with the pre-existing `quote_source_text` precedent — worth revisiting later with real data on whether that asymmetry is itself correct, not addressed this phase (out of scope, avoids widening this fix beyond mirroring the already-proven pattern).

### Tests

- `tests/test_evidence_package_degradation.py`: `test_evidence_package_uses_raw_text_on_the_fly_when_cleaned_text_column_is_empty` (the real, confirmed shape), `test_evidence_package_prefers_persisted_cleaned_text_when_present` (future-proofing control), `test_evidence_package_does_not_trust_raw_text_from_a_weak_completeness_tier` (HEADLINE_ONLY control), `test_evidence_package_falls_back_when_raw_text_is_empty_even_at_trusted_tier` (defensive control).
- All pre-existing `tests/test_evidence_package*.py` tests re-verified byte-identical pass/fail/skip signature before and after this change (3 pre-existing failures/8 pre-existing skips confirmed unrelated - present identically on unmodified HEAD).

## D. Validation

**Focused test suite** (image dedup/ranking, UPDATE short-circuit, article acquisition, quote extraction/selection, copywriting context, routing/presentation regressions) — `tests/test_router_media_integration.py`, `tests/test_content_cycle_story_delivery.py`, `tests/test_story_duplicate_guard.py`, `tests/test_evidence_package.py`, `tests/test_evidence_package_call_sites.py`, `tests/test_evidence_package_degradation.py`, `tests/test_article_acquisition.py`, `tests/test_article_acquisition_fetch.py`, `tests/test_quote_lookup.py`, `tests/test_copywriting_v6_context_seam.py`, `tests/test_telegram_editorial_routing.py`, `tests/test_news_telegram_presentation.py`, `tests/test_content_quality_gates.py`:

**221 passed, 3 failed, 8 skipped, 51 errors.**

- **3 failed**: all 3 confirmed pre-existing and unrelated to this phase's changes — reproduced with byte-identical pass/fail signature on unmodified `git stash`-restored HEAD before any Goal 3 edit (`scripts/phase19_overnight_abc_harness.py` has an undocumented, unguarded `build_evidence_package()` call site the regression guard doesn't know about; the local dev test database has migration `a3f7c9e15d02` applied when `test_build_evidence_package_raises_when_table_missing`'s own fixture assumes it isn't).
- **8 skipped**: `tests/test_evidence_package.py`'s own fixture self-skips on a migration-presence check that disagrees with the actually-applied local dev DB state — a pre-existing environment quirk, unrelated to this phase.
- **51 errors**: exclusively the same pre-existing "teardown-only FK cleanup" pattern already root-caused and repeatedly confirmed earlier this session (`content_draft_editorial_plans_event_id_fkey` and siblings) — every one of the 51 is an `ERROR` (fixture teardown), never a `FAILED` (assertion), confirmed by `grep`: 0 `AssertionError` occurrences anywhere in the run's output, and every new/modified test in this phase independently re-verified passing in isolation (see Sections A-C's own "Tests" subsections) before this combined run. This pattern is a real, disclosed, pre-existing characteristic of this test suite's real-Postgres-DB/no-transactional-rollback design for a subset of fixtures (`factory`-based, not `db_session`-based) - not something this phase introduced or is in scope to fix; DB pollution left behind by these teardown errors was cleaned up after verification, each time, via direct FK-ordered `DELETE`s scoped to this session's own test-title pattern.

**Ruff** (`worker/content_cycle.py`, `services/story_duplicate_guard.py`, `services/story_memory.py`, `services/content_draft_service.py`, `services/evidence_package.py`, plus every touched test file): clean except one pre-existing, unrelated finding already flagged during the earlier commit-preparation audit (`services/story_duplicate_guard.py`'s own `gate_delta_by_identity` unused import, present before this phase, not touched).

**mypy** (same 5 production files): `Success: no issues found in 5 source files`.

**Architecture validation** (`scripts/validate_architecture.py`): `clean - 0 forbidden-dependency violations`.

## E. Next validation proposal

A **short, targeted live validation** — not another general stability canary — with exactly four pass/fail checks, none of which require forcing anything:

1. **Same-source crop duplicates no longer reach albums.** Watch for any real media-group send during the window; for each, confirm (via the same real-URL/hash reconstruction used in this checkpoint's §A) that no two sent images share a normalized origin.
2. **Unresolved UPDATEs short-circuit before paid downstream work.** Watch the new `update_fail_closed_before_generation` counter and its `story_update_fail_closed_no_root_message_before_generation` log line; for any that fire, confirm (via `AIExecution` rows for that event) that no CONTENT_GENERATION-stage Copywriting/Quality cost was incurred, mirroring this checkpoint's §B reconstruction.
3. **Successfully acquired article text reaches quote extraction.** Run with `article_acquisition_mode = "enforce"` (in-process override only, never `.env`, restored on exit — the established convention every canary script in this repository already follows) and confirm, for at least one real `FULL_TEXT`/`PARTIAL_TEXT` acquisition, that `build_evidence_package()`'s `extraction_method` is `full_article_acquisition`, not `rss_excerpt_fallback`.
4. **At least one real quote renders, if natural traffic provides one.** Not forced — if the natural sample happens to contain no genuinely quotable material (a real possibility, per §C), report `QUOTE RENDERING: NOT LIVE-VALIDATED` again honestly rather than treating an absence as failure; if one does appear, confirm it survives `verify_quote()` against the now-`enforce`-upgraded `source_content`.

Suggested shape: reuse the existing bounded-canary harness convention (hard delivery cap ~10-15, cost cap ~$1.00, runtime ~45-60 minutes — shorter than the full acceptance run, since this only needs to catch these four specific mechanisms, not re-establish a GOOD/severe-failure baseline). `video_discovery_mode` stays `off`; the source pack stays uninstalled; `article_acquisition_mode = "enforce"` is the one deliberate, disclosed, in-process-only deviation from the prior acceptance run's configuration, scoped to this validation only.

**Not started automatically. Not committed automatically.** STOP at this checkpoint, per the phase brief.
