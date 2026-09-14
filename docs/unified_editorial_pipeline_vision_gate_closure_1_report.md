# Unified Editorial Pipeline — Vision Gate Closure 1 — Report

**Phase**: UNIFIED-EDITORIAL-PIPELINE-VISION-GATE-CLOSURE-1
**Branch**: `feature/unified-editorial-pipeline-vision-gate-closure-1`
**Base**: `e38989a02cf698f89fc497b934c108a544b7dea5` (runtime-closure-1, verdict PARTIAL)
**Scope**: close exactly one Founder HIGH (`ACTUAL_IMAGE_VERIFICATION_WIRED = false`). No redesign,
code + tests + report only. No production deploy, no migration, no Telegram/Instagram writes.

This report contains no credential or secret values.

---

## Audit of `capabilities/media_subject_match_capability.py` (first step, as instructed)

Confirmed unchanged since RUNTIME-CLOSURE-1: a real, LLM-Gateway-backed capability answering "does
this image's visual content depict the specific claimed subject" - completely separate from
`media_vision_review` (publish-safety triage). `execute()` requires
`context.business.media_subject_match_image_data_uri` (raises `ValidationCapabilityError`
otherwise - a loud, structural guarantee against being called with no image). Registered
unconditionally by `capabilities/registry.py::build_registry()` (confirmed by direct read - line
191: `registry.register(MEDIA_SUBJECT_MATCH_CAPABILITY_DEFINITION, MediaSubjectMatchCapability(...))`).
The gap was never the capability itself - it was that **nothing in any live path ever populated its
required context fields or called it**. Only one place in the whole repo had ever done so before
this phase: `scripts/_cross_platform_media_research_canary_1.py`, a manually-invoked, never-auto-run
harness - its `CapabilityContext`-construction pattern is reused verbatim by the new module below,
not reinvented.

## What was built

**New module**: `services/editorial_pipeline/subject_match_vision_gate.py` -
`build_vision_gate_subject_match_classifier()` returns a real `SubjectMatchClassifier` (the exact
same shape `classify_subject_match` already implements) that wraps it:

1. Runs the existing, unmodified deterministic `classify_subject_match()` first - cheap, always.
2. Escalates to the real vision capability ONLY when `deterministic.subject_match ==
   GENERIC_CONTEXT` (metadata/text evidence insufficient) AND the intent requires an exact/narrow
   subject depiction (`model_name`/`must_show` non-empty, OR `person` set - a named person is, by
   its own nature, already maximally narrow, unlike a bare `company`/`event` category hint).
3. MISMATCH and EXACT_SUBJECT deterministic verdicts NEVER escalate (nothing to gain: a rejected
   candidate cannot become more rejected; a confirmed-exact candidate needs no further confirmation).
4. The vision call is bounded (`asyncio.wait_for`, default 8s, no retry), cached by
   `candidate.sha256` (or a hash of the resolved bytes when unset) so the identical media identity
   is never vision-checked twice, and fully fail-soft: a timeout, a Gateway error, a malformed
   response, or an `image_bytes_provider` failure all return the **deterministic verdict unchanged**
   - never an invented upgrade, never a raised exception.
5. Combining verdicts: vision MISMATCH -> reject; vision EXACT_SUBJECT/STRONG_CONTEXT -> upgrade;
   vision GENERIC_CONTEXT (ran, but still inconclusive) -> deterministic verdict stands unchanged.

**Wiring** (the only production-code change beyond the new module):
- `services/editorial_pipeline/telegram_integration.py::run_unified_telegram_delivery()` gained one
  new optional parameter, `capability_registry: CapabilityRegistry | None = None`. When it can
  resolve `media_subject_match`, the vision-gate-wrapped classifier replaces the plain deterministic
  one for that call; any resolve-time error (unconfigured registry, etc.) fails soft back to the
  plain classifier - never a hard crash. `image_bytes_provider` reuses the SAME
  `legacy_candidates_by_id` pool already built for asset resolution (RUNTIME-CLOSURE-1) - no second
  candidate-lookup mechanism.
- `worker/content_cycle.py`'s one real call site now passes `capability_registry=capability_registry`
  (a parameter the enclosing `run_content_cycle()` already receives and the real production registry
  already configures with this exact capability) - a single added line, inside the branch that is
  already unreachable unless `unified_editorial_pipeline_enabled=True`.
- `tests/test_media_subject_match_isolation.py` updated to reflect this as the ONE deliberate,
  reviewed, three-way-gated production import (flag must be on; registry must resolve; the
  escalation policy itself must decide to fire) - `capabilities/executor.py` and
  `worker/content_cycle.py` themselves still never import the capability directly (both of those
  isolation assertions are unchanged and still pass).

## Policy compliance (verbatim requirements)

| Requirement | Status |
|---|---|
| deterministic metadata/text classification remains first and cheap | met - always runs first, unconditionally |
| MISMATCH from deterministic evidence remains rejected without vision | met - `test_deterministic_mismatch_never_escalates_to_vision` |
| clearly supported EXACT may avoid unnecessary vision | met - `test_deterministic_exact_never_escalates_to_vision` |
| ambiguous GENERIC/UNKNOWN exact-subject candidates go through vision | met - `test_ambiguous_exact_subject_intent_escalates_and_vision_confirms_{exact,mismatch}` |
| vision-confirmed mismatch => rejected | met |
| vision-confirmed exact/strong context => upgraded | met |
| vision unavailable/error/timeout => no EXACT upgrade | met - `test_vision_timeout_never_upgrades_to_exact`, `test_vision_error_never_upgrades_to_exact`, `test_image_bytes_provider_failure_returns_deterministic_verdict_never_raises` |
| fallback remains truthful alternate composition or HOLD | met - unchanged: `is_selectable()`/`require_media`/`MediaResolutionFailure` (RUNTIME-CLOSURE-1) still own that decision; this phase only changes the CLASSIFICATION a candidate receives, never how a HOLD/fallback is chosen |
| never accept unknown simply because vision failed | met - `test_vision_generic_result_leaves_deterministic_verdict_unchanged` |
| bounded / timeout-protected / no unbounded retries / no recursive search | met - one `asyncio.wait_for()` call, no retry loop |
| cacheable/deduplicated by media identity/hash | met - `test_same_media_candidate_encountered_twice_is_cached_and_bounded` (cache hit, `call_count == 1`) |
| observable | met - `vision_subject_match_called`/`_result`/`_cache_hit`/`_failed_soft`/`_skipped_no_bytes` structured log events |
| no real external network dependency in tests | met - every test uses `_FakeVisionCapability`/`_ScriptedVisionCapability`, never a real Gateway |

## Critical production-shaped test results

| # | Case | Result |
|---|---|---|
| 1 | Foldable iPhone story + standard iPhone, weak/no metadata | PASS - rejected (`test_case1_standard_iphone_weak_metadata_rejected_via_vision`) |
| 2 | Foldable iPhone story + true foldable, weak/no metadata | PASS - accepted (`test_case2_true_foldable_weak_metadata_accepted_via_vision`) |
| 3 | Named person, wrong person | PASS - rejected (`test_named_person_wrong_person_rejected_via_vision`) |
| 4 | Named person, correct image | PASS - accepted (`test_named_person_correct_person_accepted_via_vision`) |
| 5 | Product/model, visually similar wrong model | PASS - rejected (`test_case5_visually_similar_wrong_model_rejected_where_vision_can_distinguish`) |
| 6 | Generic concept, exact depiction not required | PASS - vision never called (`test_case6_generic_concept_story_never_calls_vision`, `test_concept_intent_with_no_required_terms_never_escalates`) |
| 7 | Vision backend timeout | PASS - no false EXACT upgrade (`test_vision_timeout_never_upgrades_to_exact`) |
| 8 | Same media candidate encountered twice | PASS - single call, cached (`test_same_media_candidate_encountered_twice_is_cached_and_bounded`) |
| 9 | SAME-ASSET invariant (selected == rendered == QA == transport) | PASS - unaffected; `tests/test_unified_pipeline_same_asset_invariant.py` re-run green (the vision gate only changes candidate CLASSIFICATION before selection, never touches resolution/render/transport identity) |
| 10 | Existing runtime-closure-1 tests remain green | PASS - full combined regression, see below |

## Test results

- New tests: `tests/test_unified_pipeline_vision_gate.py` (13 passed), `tests/test_unified_pipeline_vision_gate_replays.py` (5 passed).
- One pre-existing isolation test intentionally updated (`test_media_subject_match_isolation.py`) to
  recognize `telegram_integration.py` as the new, deliberate, reviewed importer - its two OTHER
  assertions (`capabilities/executor.py` and `worker/content_cycle.py` never import the capability
  directly) are unchanged and still pass.
- **Full combined regression** (every runtime-closure-1 test file + all new files, 34 files): **215
  passed, 0 failed.**
- Legacy flag-off path (`tests/test_router_media_integration.py`, re-run in full after touching
  `worker/content_cycle.py`): 68 passed, the same 2 pre-existing, unrelated failures already present
  before this phase (a keyboard-count assertion in the NINJA PULSE CTA path - confirmed by identical
  failure signature to the prior phase's own baseline check). **FLAG_OFF_REGRESSION = ZERO_DIFF.**
- `ruff check`: clean (one pre-existing unused-import in a new test file, fixed).
- `mypy --ignore-missing-imports`: clean on every new/modified file except pre-existing, unrelated
  errors in `services/story_delta_engine.py` (untouched by this phase). One real new type error
  (`subject_match_classifier`'s inferred type) was found and fixed during this check.

## Forbidden-area compliance

Changed files this phase: `services/editorial_pipeline/subject_match_vision_gate.py` (new),
`services/editorial_pipeline/telegram_integration.py` (one new optional parameter + wiring),
`worker/content_cycle.py` (one added kwarg at the existing call site),
`tests/test_media_subject_match_isolation.py` (updated to reflect the deliberate new import),
`tests/test_unified_pipeline_vision_gate.py` + `tests/test_unified_pipeline_vision_gate_replays.py`
(new tests). Nothing under Story Memory, arXiv guards, Telegram V8 renderers, recovery service/
model, `services/telegram_routing.py`, Instagram publication, `services/media_web_discovery.py`,
`services/editorial_pipeline/composition.py`, or DATA-content extraction was touched.

## Remaining known limitations (disclosed, not blockers)

- No real web-discovery backend still exists (out of this phase's scope, unchanged from
  RUNTIME-CLOSURE-1) - vision escalation for a Tier 2-5 web-discovered candidate is therefore only
  possible once that candidate's bytes are actually resolved somewhere in the pipeline; today, the
  candidates that reach this classifier in production are Tier-1 (already-downloaded) candidates,
  which is exactly the case class the Founder audit's original bug (wrong ordinary photo reused for
  a new distinct product) came from.
- The vision gate changes CLASSIFICATION only; it does not and must not change `is_selectable()`,
  `require_media`, or any HOLD/recovery decision logic (untouched, per the phase's own explicit
  "do not modify recovery architecture" instruction).

## Final metrics

| Metric | Value |
|---|---|
| ACTUAL_IMAGE_VERIFICATION_WIRED | **true** |
| WRONG_SUBJECT_CAN_WIN | false |
| GENERIC_UNKNOWN_CAN_MASQUERADE_AS_EXACT | false |
| SELECTED_ASSET_EQUALS_RENDERED_ASSET | true |
| SELECTED_ASSET_EQUALS_QA_ASSET | true |
| SELECTED_ASSET_EQUALS_TRANSPORT_ASSET | true |
| TEXT_ONLY_VISUAL_DEMOTION_FOUND | false |
| AMBIGUOUS_AUTO_RESEND | false |
| FLAG_OFF_REGRESSION | ZERO_DIFF |
| STORY_MEMORY_CHANGED | false |
| ARXIV_GUARD_CHANGED | false |
| TELEGRAM_V8_CHANGED | false |
| INSTAGRAM_PUBLICATION_ENABLED | false |
| UNIFIED_FLAG_DEFAULT | false |
| NEW_FAILURES | 0 |

## Verdict

`UNIFIED_PIPELINE_VISION_GATE_CLOSURE_READY_FOR_FOUNDER_REVIEW`
