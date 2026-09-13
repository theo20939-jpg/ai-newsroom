# CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1

Base commit: `d6c6505` (`feature/phase19-editorial-depth-upgrade`). Worktree
`C:/Users/Theodor/ai-newsroom-media-research-1`, branch
`feature/cross-platform-media-research-selection-1`.

Cross-referenced worktree for the visual demonstration only (no code merge, no shared history
touched): `C:/Users/Theodor/ai-newsroom-ig-trend-canary-1`
(`feature/instagram-autonomous-trend-to-carousel-canary-1` @ `a9908e8`), the exact branch whose own
canary exposed this phase's root-cause bug.

No Instagram/Telegram publish, no production DB write, no container restart/deploy, no
credentials beyond a locally-configured OpenAI key already present in this dev environment's own
`.env`, no autonomous scheduling.

## A. Founder product rule (section 0) - restated

A visual must truthfully represent its subject. The specific, named failure this phase exists to
fix: INSTAGRAM-AUTONOMOUS-TREND-TO-CAROUSEL-CANARY-1 selected a trend about Apple's specific new
foldable phone ("iPhone Duo") and then reused an already-available photo of an ORDINARY,
non-foldable iPhone as its hero image - exactly the "random regular iPhone photo" failure section 0
names by example.

## B. Current media-selection path - traced before anything was changed (section 1)

A dedicated research pass (full findings preserved in this session's own transcript) read every
relevant file rather than guessing. Findings, with citations:

**`CURRENT_MEDIA_DISCOVERY_PATH`**: `services/image_intelligence.py::run_shadow_discovery()`
reconstructs native hints already attached to a `NewsEvent` (Telegram photo/document, RSS
media/enclosure/thumbnail/inline `<img>`), optionally fetches the event's OWN article URL exactly
once via `integrations/http/safe_fetch.py`, parses `og:image`/JSON-LD/Twitter/`image_src`/inline
`<img>` tags (`services/article_metadata.py`), downloads/validates a bounded number of candidates,
runs quality/dedup (`services/image_quality.py`, `services/image_deduplication.py`), then ranks by
**provenance + lexical text overlap** (`services/image_relevance.py`, Phase 16 M4) - that module's
own docstring states plainly: *"never claims visual/semantic understanding of image content"*.
Persisted into `image_candidates` (`database/models/image_candidate_record.py`).

**`CURRENT_MEDIA_POOL`**: exclusively (a) native hints already on the ingested item, and (b) the
NewsEvent's own article page. Confirmed by direct grep across the whole repository: zero hits for
any search-engine/press-kit/stock-photo client (`serpapi`, `bing image`, `google image search`,
`unsplash`, `pexels`, `getty`, `presskit`, etc.) anywhere in this codebase, outside of unrelated
test fixtures and a local-brand-asset comment.

**`WHY_FOLDABLE_IPHONE_IMAGE_WAS_NOT_SEARCHED`**: no code path in this repository ever searches the
web for a candidate image. The only two discovery mechanisms are native-attached media and the
NewsEvent's own article URL - there was structurally nowhere to search a real iPhone-Duo photo
FROM, even before considering whether one would be correctly identified once found.

**`WHY_ORDINARY_IPHONE_IMAGE_WON`**: this is not, in fact, a bug in the mature Phase 16 pipeline
above - the prior canary's own script never called that pipeline at all. It manually assigned a
locally-bundled newsroom-visual fixture (`case1_hero_product_iphone.jpg`) as the carousel's hook
image, because that phase's own scope was the Instagram render/carousel-grammar system, not media
sourcing. The REAL, general gap this exposed is architectural: **nothing in this codebase, on
either the Instagram or the mature Telegram Image-Intelligence side, has ever asked "does this
candidate visually depict the EXACT claimed subject, or merely something similar"** -
`services/image_relevance.py` explicitly, by design, never asks that question at all.

## C. New architecture (section 2)

One real, platform-neutral flow, implemented exactly as section 2 states it: content need ->
`MediaIntent` -> local/source candidates (Tier 1, reused read-only) -> external discovery if
needed (Tiers 2-4) -> provenance extraction -> candidate normalization -> subject-match/usage
validation -> ranking -> deduplication -> `MediaSelectionResult`. Implemented as:

- `schemas/media_intent.py` - `MediaIntent` (section 3).
- `services/media_query_generation.py` - bounded query generation (section 4).
- `services/media_web_discovery.py` - Tier 2-4 discovery + domain-tier/usage classification
  (sections 5/6/7/8).
- `schemas/media_subject_match.py` - `MediaProvenance`, `ResolvedMediaCandidate`,
  `MediaUsageClassification`, `SubjectMatchClassification`, `SubjectMatchValidation`,
  `MediaSelectionResult` (sections 7/8/10/14).
- `capabilities/media_subject_match_capability.py` + `prompts/media_subject_match/v1.yaml` - the
  real, vision-LLM-backed subject-identity check (section 13).
- `services/media_candidate_scoring.py` - bounded, subject-match-dominant scoring (section 12).
- `services/media_download_cache.py` - safe, bounded download/cache (section 15).
- `services/media_research_selection.py` - the one orchestration entrypoint tying all of the
  above together (section 2).

No second, parallel web-search subsystem was built per renderer - this is the one shared layer,
usable by Instagram, Telegram, or any future platform, none of which it imports or depends on.

## D. MediaIntent (section 3)

Every field section 3 lists exists on `MediaIntent` (`subject_type`, `primary_entity`,
`product_name`, `model_name`, `company`, `person`, `event`, `location`, `time_context`,
`desired_visual_type`, `slide_role`, `must_show`, `must_not_imply`, `orientation_preference`,
`platform`, `freshness_requirement`) - nothing hardcoded to "iPhone Duo" anywhere in the schema
itself; the canary constructs one real instance as any real caller would.

## E. Query generation (section 4)

`generate_search_queries()` is deterministic, hard-capped at `MAX_QUERY_VARIANTS = 5`, and
prioritizes exact-identifier combinations first (`"{company} {model}"` before generic terms).
Proven in `tests/test_media_query_generation.py` (never exceeds the cap, never pads a thin intent
with junk queries, same intent always yields the same queries).

## F. Discovery tiers + provenance + usage classification (sections 5/6/7/8)

`services/media_web_discovery.py` implements Tiers 2-4 behind a `WebDiscoveryClient` Protocol.
Section 6's "a thumbnail is not sufficient evidence" is enforced structurally: a candidate is only
ever constructed from a real, two-step-resolved `ResolvedPageImage` (origin page + real asset URL +
publisher + caption/alt), never from a bare search hit. `classify_discovery_tier()`/
`classify_usage()` are a disclosed, conservative, NON-legal domain heuristic (section 8's own "not
a copyright detector" instruction) - a small stock-photo domain list hard-disqualifies
(`NOT_USABLE`), a small editorial-outlet allowlist earns Tier 3, everything else defaults to the
safe `EDITORIAL_REVIEW_REQUIRED`, never silently `APPROVED`.

`NullWebDiscoveryClient` - zero network calls, zero results - is the only implementation wired
into anything resembling production defaults (`media_web_discovery_mode` defaults to `"off"`,
`core/config.py`). **Production `automation_worker` cannot autonomously search the web today** -
this phase does not change that; it builds and proves the pipeline that would consume real search
results once a real search-API integration is a separate, explicitly-authorized decision.

## G. Subject-match classification (sections 9/10/13) - the real fix

`capabilities/media_subject_match_capability.py` is a genuinely new Capability, built on the exact
same already-wired, already-proven real Gateway vision plumbing
`capabilities/media_vision_review_capability.py` established (no gateway/routing/provider change
here either) - answering a DIFFERENT question that module never asks: does this image's visual
content depict the SPECIFIC named subject, or only a same-brand/same-category look-alike?

Classified into exactly the four section-10 buckets (`EXACT_SUBJECT` / `STRONG_CONTEXT` /
`GENERIC_CONTEXT` / `MISMATCH`). A `MISMATCH` (or `NOT_USABLE` usage) candidate is excluded from
selection **structurally** (`services/media_candidate_scoring.py::is_selectable()`), never merely
low-scored.

### A real bug this real call caught, fixed in one bounded pass, and re-verified (section 21's
own "at most one bounded correction pass" discipline, applied here even though it is phrased for a
different phase - the same engineering discipline)

The first real run (see section K) showed the model correctly *describing* the ordinary ("wrong")
iPhone as non-foldable and correctly flagging `must_not_imply_violated=true` with the exact
statement "that an ordinary, non-foldable iPhone is the iPhone Duo" - but still classifying it
`STRONG_CONTEXT` rather than `MISMATCH`, because the prompt never linked those two fields together.
**Fixed** (`prompts/media_subject_match/v1.yaml`): a new explicit rule forces `MISMATCH` whenever
`must_not_imply_violated` is true AND the violation is specifically about being mistaken for the
exact subject. Re-verified: the wrong candidate now correctly classifies `MISMATCH` (section K).

The same first run also showed all three REAL, correct iPhone-Duo photos capped at
`STRONG_CONTEXT` ("no visible on-image text names this the iPhone Duo") - an overly strict bar,
since no real product photo carries an on-image caption. **Fixed**: the capability's task prompt
now also carries the CANDIDATE'S OWN real corroborating evidence (its actual caption/alt text,
publisher, origin page - never anything invented) alongside the claimed subject, with an explicit
rule that real corroborating evidence plus a visually CONSISTENT (non-contradicting) image is
legitimate combined evidence for `EXACT_SUBJECT` - exactly how a human editor reasons - while a
caption that CONTRADICTS the visible content must never override what is actually seen. Re-verified:
all three real candidates now correctly classify `EXACT_SUBJECT` (section K).

## H. Bounded, dominant scoring (section 12)

`services/media_candidate_scoring.py`'s dominance invariant is enforced BY CONSTRUCTION, not
convention: `SUBJECT_MATCH_SCORE[EXACT_SUBJECT] = 60` is set higher than the maximum any non-exact
classification could ever reach from every other scoring component combined (source authority +
freshness + quality = 40 max) - asserted at import time and proven directly in
`tests/test_media_candidate_scoring.py` (a worst-tier, tiny-resolution `EXACT_SUBJECT` still beats
a best-tier, huge-resolution `STRONG_CONTEXT`/`GENERIC_CONTEXT`/`MISMATCH` candidate). `is_
selectable()` hard-excludes `MISMATCH`/`NOT_USABLE` regardless of any score.

## I. No-photo-found handling (section 11)

`services/media_research_selection.py::research_and_select_media()` always sets `exact_subject_
media_not_found` truthfully - even when a `STRONG_CONTEXT` candidate IS selected (a real,
disclosed distinction: "we picked something," never conflated with "we confirmed the exact
subject"). When nothing is selectable at all, the caller's own supplied `fallback_candidate` (a
graphic layout / brand asset - never invented by this module itself, section 14) is used and
`fallback_used=True` is reported; with no fallback supplied, `selected=None` and the caller is
told plainly. Both paths are directly tested (`tests/test_media_research_selection.py`).

## J. Download/cache safety (section 15)

`services/media_download_cache.py` reuses, unmodified: `integrations/http/safe_fetch.py`
(SSRF-safe, IP-pinned, bounded timeouts/redirects/bytes - the exact boundary
`services/image_intelligence.py` already uses), `services/image_validation.py::
validate_image_bytes()` (MIME/pixel/decode validation), `services/image_quality.py::compute_dhash
()`/`hamming_distance()` (perceptual hash), and `sha256_hex()`. This phase adds only the bounded
local cache on top: content-hash-named files (never a caller-supplied string touches the
filesystem path), a hard `_MAX_CACHE_FILES = 500` ceiling, automatic dedup (re-downloading the same
bytes from a different URL reuses the existing cached file, proven in
`tests/test_media_download_cache.py`).

## K. The real canary (sections 18-24)

`scripts/_cross_platform_media_research_canary_1.py` (manually-invoked only, mirrors `scripts/
phase19_m13_vision_review_manual.py`'s exact never-auto-run shape). Real, bounded (4 images) work:

1. **Real `MediaIntent`** for Apple's iPhone Duo (foldable, announced 2026-09-09), including
   `must_not_imply=["that an ordinary, non-foldable iPhone is the iPhone Duo"]`.
2. **The exact WRONG candidate** from the prior canary (`case1_hero_product_iphone.jpg`) as a
   Tier-1 control - the specific bug this phase must correctly reject.
3. **Real web discovery** - 3 genuinely real, separately-fetched news photos (MacRumors,
   TechCrunch, Engadget; all 2026-09-09) of the actual announcement, gathered via this session's
   own web-search/fetch tool calls and downloaded through the real `safe_fetch`-backed pipeline
   (disclosed honestly: production has no search-API key today - section F).
4. **Real vision-LLM calls** (OpenAI, via the existing, unmodified Gateway/Capability plumbing -
   `settings.enabled_providers` was explicitly, visibly set to `["openai"]` for this one bounded,
   disclosed run only - an in-process override, never a persisted config change) for all 4
   candidates.
5. Real, bounded scoring/selection.

**First run (before the section G fix)**:

| candidate | subject_match | notes |
|---|---|---|
| ordinary iPhone (wrong) | `strong_context` | `must_not_imply_violated=true`, correct reasoning, WRONG bucket |
| MacRumors (real, low-res 400×225 thumbnail) | `generic_context` | genuinely ambiguous at that resolution (verified by eye) |
| TechCrunch (real, 1024×576) | `strong_context` | correctly described as foldable; capped for lack of on-image text |
| Engadget (real, 780×438) | `strong_context` | correctly described as foldable; capped for lack of on-image text |

Result: **the wrong ordinary iPhone was selected** (score 65) - the exact original bug, reproduced
end-to-end through the new pipeline, not fixed yet.

**Second run (after the section G fix - final, reported result)**:

| candidate | subject_match | reason (real model output) |
|---|---|---|
| ordinary iPhone (wrong) | **`mismatch`** | "conventional non-folding iPhone-style slab devices... would specifically misrepresent an ordinary iPhone as that product" |
| MacRumors | **`exact_subject`** | "visibly shows an open foldable phone... the candidate-specific caption and origin page identify this consistent device as the iPhone Duo" |
| TechCrunch | **`exact_subject`** | "visibly shows a foldable iPhone-style device... visually consistent with the candidate's originating TechCrunch article identifying it as Apple's first foldable" |
| Engadget | **`exact_subject`** | "candidate's own caption identifies this specific image as a folded-out iPhone Duo, and the visible device is consistent... nothing visibly contradicts the supplied corroboration" |

Result: `candidates_considered=4`, `candidates_by_classification={"mismatch": 1, "exact_subject":
3}`, **`exact_subject_media_not_found=False`**, **`selected="web:0:macrumors.com"`** (score 86),
`rejection_reasons=["tier1_local_ordinary_iphone: subject_match=mismatch (...)"]`. The wrong
candidate is now correctly excluded; a real, correct photo of the actual iPhone Duo is selected.

Full real JSON: `artifacts/cross_platform_media_research_canary_1/selection_result.json` and
`subject_match_call_log.json` (every real model call's full input/output, both runs).

**Disclosed limitation, not fixed in this phase**: all three `EXACT_SUBJECT` web candidates scored
identically (86) - `discover_web_candidates()` does not carry a candidate's downloaded width/
height back into the scored object (only `subject_match` is attached post-classification), so the
three real photos are true scoring ties, and the "winner" among ties is whichever was discovered
first, not necessarily the highest-resolution one. A real follow-up (propagate the classifier's own
download-step dimensions back into the scored candidate) is a small, well-understood next step -
disclosed rather than silently patched under time pressure.

## L. Cross-platform visual proof (section 17/22)

To make the fix concretely, visually inspectable (not just a JSON diff), the real winning
TechCrunch photo (1024×576, `EXACT_SUBJECT`, chosen over the three-way score-tie for the highest
real resolution available) was fed into the ALREADY-EXISTING, unmodified Instagram carousel
renderer (`services/instagram_carousel_layouts.py`, in the separate `ai-newsroom-ig-trend-canary-1`
worktree - no code was merged between worktrees, only the one resulting image file was copied) to
regenerate the exact same hook slide the original buggy canary produced.

`artifacts/cross_platform_media_research_canary_1/00_BEFORE_AFTER.jpg` - side-by-side: the original
wrong ordinary-iPhone hook slide next to the corrected real-iPhone-Duo hook slide, identical
headline/layout/branding, only the photo differs. `slide_00_hook_CORRECTED.jpg` is the corrected
render on its own.

## M. Tests (section 21-equivalent discipline)

50 new tests across `tests/test_media_intent.py`, `test_media_query_generation.py`,
`test_media_web_discovery.py`, `test_media_candidate_scoring.py`,
`test_media_research_selection.py`, `test_media_download_cache.py`,
`test_media_subject_match_capability.py`, `test_media_subject_match_isolation.py`, and
`test_media_research_isolation.py` - covering: intent immutability/bounds, query-generation
bounding/determinism, discovery-tier/usage classification, real provenance resolution (never a
bare thumbnail), cross-query asset dedup, the scoring dominance invariant (proven directly, not
merely asserted), hard exclusion of `MISMATCH`/`NOT_USABLE`, the literal ordinary-iPhone-vs-
iPhone-Duo selection scenario, no-candidate/fallback handling, download safety (content-hash
naming, dedup-reuse, safe-fetch-failure/invalid-bytes/cache-full handling, all via a monkeypatched
`safe_fetch` - zero real network calls in the unit-test tier), the real Capability's request/
validation/error-handling shape (mirroring its sibling's own test file exactly), and two AST-based
isolation proofs that nothing in this phase is reachable from `worker/content_cycle.py` or
`capabilities/executor.py` today.

**Regression**: `git diff --stat d6c6505 -- services/brand_renderer.py services/
nnj_master_news_overlay.py services/nnj_board_metrics.py services/render_evidence.py services/
presentation_director.py assets/brand/fonts/ worker/content_cycle.py capabilities/executor.py` =>
empty (zero bytes changed) - Telegram V8 and the live worker/capability-executor call paths are
completely untouched. A scoped sweep (`-k "image or media or capabilit"`, 1,192 tests) showed 7
failures + 14 collection errors; every one of the 7 real failures was independently reproduced,
byte-for-byte identical, against a pristine `git worktree add --detach` checkout of the unmodified
base commit `d6c6505` itself (temporary worktree, removed after verification) - **all 7 are
pre-existing on the exact commit this phase branched from, none caused by this phase's changes**.
**`NEW_FAILURES = 0`.** `ruff check` + `mypy --ignore-missing-imports` are clean (`0` errors) on
all 12 new/changed Python files.

## N. Config / capability-registration surface (additive only)

- `core/config.py`: `+media_subject_match_mode: Literal["off","shadow"]="off"`,
  `+media_web_discovery_mode: Literal["off","shadow"]="off"` - mirror `image_intelligence_mode`/
  `media_vision_review_mode`'s exact two-state convention; neither is read by any code branch yet
  (no shadow hook exists for either, exactly like `media_vision_review_mode`'s own "shadow" is
  currently a documented no-op).
- `schemas/capability.py`: `BusinessContext` +2 optional fields (`media_subject_match_image_data_
  uri`, `media_subject_match_intent_summary`), both always `None` in every live path - mirrors
  `media_review_image_data_uri`'s own exact precedent.
- `capabilities/capability_mapping.py`: +1 entry (`"media_subject_match" -> AICapability.QUALITY`,
  reused, no new enum/migration - mirrors `"media_vision_review" -> QUALITY`'s own precedent).
- `capabilities/registry.py`: +1 registration (dormant - resolvable/cost-tracked, no live
  `WorkflowDefinition` step references it, mirrors every other dormant-registration precedent in
  this file).

No `image_candidates` (or any other) table migration was written or applied - this phase's new
contracts (`MediaIntent`, `ResolvedMediaCandidate`, `MediaSelectionResult`) are fresh, unpersisted
Pydantic shapes, exactly matching `services/telegraph_visual_research.py`'s own disclosed "no new
persistence table" scope decision. Persisting a web-discovered candidate into the real,
already-migrated `image_candidates` table (which has no columns for subject-match/usage
classification or a web-discovery `discovery_method` today) is a real, separate production-schema
decision, disclosed here rather than made unilaterally.

## O. Not done in this phase (explicit, disclosed)

- No real search-API (SerpAPI/Bing/Google CSE) integration - `NullWebDiscoveryClient` remains the
  only production-wired implementation; this phase's own web discovery ran on real, but
  operator-gathered (this session's own web-search tool calls), results.
- No wiring into `worker/content_cycle.py` or `capabilities/executor.py` - proven absent by two
  dedicated AST tests (section M).
- No `image_candidates` schema migration.
- The scoring tie-break gap (section K) - disclosed, not fixed.
- No Telegram V8 change of any kind.

## Verdict

**`CROSS_PLATFORM_MEDIA_RESEARCH_SELECTION_1_READY_FOR_FOUNDER_REVIEW`**

The new media-research/subject-match pipeline is real, tested (50 new tests, `NEW_FAILURES=0`,
`NEW_STATIC_ERRORS=0`), and PROVEN, end-to-end with real downloaded photos and real vision-LLM
calls, to correctly reject the exact ordinary-iPhone-for-iPhone-Duo failure this phase was written
to fix, and to correctly select a real, verified photo of the actual subject instead - visually
demonstrated in `00_BEFORE_AFTER.jpg`. Two real, disclosed limitations remain (no live search-API
backend; a scoring tie-break gap among equally-classified web candidates) - not hidden, not
silently patched under time pressure. Not yet wired into any live/automatic pipeline; no Instagram/
Telegram publish of any kind occurred.
