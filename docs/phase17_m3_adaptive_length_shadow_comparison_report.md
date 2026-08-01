# Phase 17 M3 — Adaptive Length Shadow and Safe Copywriting Comparison — Report

Branch: `feature/phase17-editorial-intelligence`, on top of `102320e` (Phase 17 M2, checkpoint
`checkpoint/phase17-m2`). Docker: `postgres`/`redis`/`backend` `Up`; `automation_worker`,
`news_analysis_worker`, `content_worker`, `telegram_bot` remained `Exited` throughout this
milestone - never started.

## 1. Objective

Build a deterministic, versioned length/structure policy (`AdaptiveLengthPlan`) that gives
Copywriting room to write a complete, useful post instead of an artificially short one - then
prove, with a small, tightly-controlled, explicitly-confirmed real generation comparison, whether
that extra room actually produces better output without fabrication. Shadow-only for production;
the comparison itself is an isolated, manually-invoked tooling path, never wired into a worker.

## 2. Starting state

Phase 17 M2 (`docs/phase17_m2_channel_topic_relevance_shadow_report.md`) shipped Channel/Topic
Relevance as a shadow step: 269/269 real backtest cases, 0% false accept/reject on the 32-case
gold set, Netflix/Walking Dead correctly `REJECT`. This milestone starts from that unmodified
state, checkpoint `checkpoint/phase17-m2`.

## 3. M0 evidence

`docs/phase17_m0_output_quality_discovery_report.md` §4: median real body 33 words, 100%
single-paragraph, no draft in the entire 269-row population ever reached even the lower bound of
the "Simple" band this report reuses (90 words). §13 item 3: no step anywhere computes an explicit
length/structure target; the only real enforcement is `bot/formatting.py`'s post-hoc,
delivery-time shrink-to-fit.

## 4. M1 EditorialBrief dependency

`services.editorial_brief.build_editorial_brief()` is called directly by this milestone's own
planner (`services/adaptive_length.py::build_adaptive_length_plan()`) - a pure function, zero new
LLM call - rather than depending on `editorial_brief_mode` being `"shadow"`, the same
"independently computable from already-persisted data" pattern M2 already established.

## 5. M2 relevance boundary

Explicitly out of scope and untouched: `channel_relevance_mode` stays at whatever the environment
already has it (default `"off"`), no enforcement was added, and the comparison sample's own pinned
Netflix/Walking Dead case is evaluated for *length/quality* only - its M2 `REJECT` status is
reported separately (§19) and never overridden or re-litigated here (§16's own explicit
instruction: "не смешивай эти оценки").

## 6. Existing Copywriting behavior

Traced directly, not assumed (this milestone's own required discovery, answered before any code
was written):

1. **Where length is actually constrained today**: `capabilities/executor.py`'s
   `_MAX_OUTPUT_TOKENS_BY_CAPABILITY["copywriting"] = 600` (a token cap, not a word/character
   instruction) is the only generation-time constraint; `bot/formatting.py::render_editorial_
   card()`'s post-hoc shrink-to-fit (`SAFE_LIMIT=4096` text / `CAPTION_SAFE_LIMIT=1024` photo
   caption, `bot/image_preview_formatting.py`) is the only other constraint, applied after
   generation, at delivery time.
2. **No explicit length instruction in the prompt**: `prompts/copywriting/v3.yaml` only says "Keep
   the title concise and the body suitable for a short social post" - no word/sentence/paragraph
   count anywhere (confirmed, matches M0 §2).
3. **`max_tokens` truncation risk**: real historical `AIExecution` rows (`capability=COPYWRITING`)
   show current output uses only ~87-122 output tokens against the 600-token cap - never binding
   today, but would become tight for a 220-320-word Complex target (this is exactly why the
   comparison script computes its own generous, plan-derived `max_tokens` rather than reusing the
   fixed 600 constant - §14, zero truncation observed, §18).
4. **Copywriting's real inputs**: unchanged since M1 - only `news_event.title`/`.category` +
   Research's `{facts, confidence, gaps}` + Intelligence's `{significance, angle,
   audience_relevance, recommendation}`. Never raw `NewsEvent.content`, never `EditorialBrief`,
   never `ChannelRelevance` - confirmed still true, this milestone changes none of it.
5. **How to pass adaptive length without a direct capability link**: same seam as M1/M2 - read via
   `CapabilityContext`'s already-frozen `step_results` mechanism, never a direct import of one
   Capability by another.
6/7. **Where to store the plan/candidates**: `AdaptiveLengthPlan` -> `EditorialTask.workflow`'s
   existing JSON `step_results` (no new table); comparison candidates -> a local JSON file, never
   the database (§14).
8. **Guaranteeing the baseline `ContentDraft` never mutates**: the comparison script only ever
   `SELECT`s `ContentDraft`/`EditorialTask`/`NewsEvent` rows - zero `session.add`/`flush`/`commit`
   anywhere in the file (verified, §18).
9. **Telegram photo-caption impact**: `CAPTION_SAFE_LIMIT=1024` UTF-16 units when a photo is
   attached (`image_intelligence.candidates_accepted > 0`) vs. `SAFE_LIMIT=4096` for text-only -
   both real, already-live Phase 16 constants, reused unchanged (§12).

## 7. Architecture decision

`AdaptiveLengthPlan` is computed at the **`"copywriting"` step** - unlike M1/M2, both of which run
at `"intelligence"` - specifically **after** Image Intelligence's own attach in that same step
(`capabilities/executor.py:254-255`, gated on `step.capability == "copywriting" and settings.
adaptive_length_mode != "off"`), so `has_image_candidate` reflects real `candidates_accepted` data
rather than being guessed. Stored as an additive `"adaptive_length_plan"` key on that step's own
result - no new table. The comparison candidate uses a brand-new prompt **name**,
`copywriting_adaptive_candidate` (not `copywriting` v4) - `FilePromptRepository.resolve(name,
version=None)` returns the *latest* version per name (verified by reading the real implementation,
`integrations/prompts/file_repository.py`), so reusing the `copywriting` name would risk a future
caller silently resolving to the candidate prompt; a separate name removes that risk structurally,
not by convention. Comparison-mode LLM calls only ever happen via
`scripts/phase17_m3_adaptive_length_comparison.py`, gated by `adaptive_length_mode ==
"comparison"` **and** `--live` **and** `--confirm-paid-calls` (`--dry-run` is the unconditional
default) - never inside the executor/worker path, verified by the static import-shape test
(§18, §24) that this module has no reachable path to a Telegram send or a collector call.

## 8. AdaptiveLengthPlan schema

`schemas/adaptive_length.py`, `schema_version="v1"`, `policy_version="v1"`. Fields:
`recommended_format` (reused from M1's `RecommendedFormat`), `complexity` (new `Complexity` enum:
simple/normal/complex/follow_up/insufficient), `source_sufficiency` (reused from M1's
`SourceSufficiency`), `min_words`/`target_words`/`max_words` (a `model_validator` enforces `min <=
target <= max` structurally, not by convention), `hard_character_limit`, `delivery_mode` (new
`DeliveryMode` enum: photo_caption/text_message/unknown), `paragraph_target`, `detail_target`,
`required_sections`/`optional_sections`/`omitted_sections` (a closed `PlanSection` vocabulary:
headline/lead/subject_explanation/event_details/background_context/why_it_matters/what_next/
uncertainty_note), `reason_codes`, `confidence` (new `LengthConfidence` enum), `safety_
constraints`. No mutable defaults (tested).

## 9. Complexity policy

`services/adaptive_length.py::determine_complexity()` - a base tier from M1's own already-
calibrated `recommended_format` (`SHORT_UPDATE->SIMPLE`, `STANDARD_NEWS->NORMAL`,
`EXPLAINER->COMPLEX`, `INSUFFICIENT_SOURCE`/`REJECT_CANDIDATE->INSUFFICIENT`,
`FOLLOW_UP->FOLLOW_UP`), then an **upgrade-only** enrichment pass (why_it_matters present,
what_next present, a regulation/legal keyword signal, a technical-jargon signal (2+ ALLCAPS
3+-letter tokens), 3+ distinct entities - each worth one point) that can push `SIMPLE->NORMAL`
(score >= 3) or `NORMAL->COMPLEX` (score >= 4), never downgrades, and never applies at all when
the base is `INSUFFICIENT`/`FOLLOW_UP` - thin-source safety always wins (M3's own "length never
outranks Fact Safety" rule). Fact count alone never forces `COMPLEX` (tested directly - M3's own
explicit "do not treat every AI story as complex" instruction). `FOLLOW_UP` is structurally
unreachable today - no storyline memory, the identical M7+ limitation M1's own `RecommendedFormat.
FOLLOW_UP` already carries - kept in the schema for forward compatibility only.

## 10. Source-sufficiency policy

`SUFFICIENT`: full range, no target reduction. `PARTIAL`: target lowered to the midpoint between
min and the original target (`no_padding_partial_source` safety constraint), min/max unchanged.
`HEADLINE_ONLY`/`EMPTY`/`CONFLICTING`/`UNKNOWN` all force `complexity=INSUFFICIENT` (the 40-90-word
band, never an artificial 90-word floor from a richer band - tested directly). `EMPTY` additionally
sets `empty_source_skip_comparison_candidate` (the comparison script honors this - §14).
`CONFLICTING` additionally sets `do_not_amplify_conflicting_claims`. Every thin-sufficiency plan
carries `no_fabrication_thin_source` and `do_not_repeat_single_idea_to_reach_length`.

## 11. Word-range policy

Recalibrated bands (M0 §15's own four bands, with an explicit target added - M0 only gave
min/max): Simple 90/115/140, Normal 140/180/220, Complex 220/270/320, Follow-up 180/230/300
(unreachable), Insufficient 40/65/90. Targets sit near each band's own lower third, matching M0's
own finding that real output clusters far below every band's ceiling.

## 12. Telegram character-budget policy

`determine_delivery()` - real, measured reserve: header emoji+category+date (~39 chars) +
`NewsEvent.title` (real DB max observed across 2000 rows: 120 chars, p95/p99 118/119) + a
`"\n\n"` separator (2) + draft title wrapped in `<b></b>` (real max observed 84 chars + 7 markup)
+ two more `"\n\n"` separators (4) + hashtags line (real max observed 83 chars) = 339, rounded to
**360** for HTML-escaping expansion headroom. `hard_character_limit` is always this
reserve-adjusted **body-only** budget, never the raw Telegram constant. When a candidate's own
*target* would not fit `CAPTION_SAFE_LIMIT` even with an eligible image candidate, the policy
recommends `TEXT_MESSAGE` outright rather than shrinking the word range to force a caption fit -
resolving M0 §15's own open "make has-image an input... so a genuinely complex story is allowed to
drop the image rather than truncate the text" recommendation as a concrete product decision. When
Image Intelligence has not run (`has_image_candidate=None`), `delivery_mode=UNKNOWN` and the
smaller, conservative (caption-sized) budget is used defensively.

## 13. Shadow integration

`apply_adaptive_length_shadow()` mirrors M1's/M2's own off-check-inside-the-function, purely
additive merge convention exactly. `_attach_adaptive_length_plan()` (`capabilities/executor.py:415+`)
wraps the call in `try/except Exception`, logs `adaptive_length_plan_failed`, and returns
`structured_output` unchanged on any error - proven directly by
`test_plan_builder_failure_does_not_fail_content_generation` (Copywriting's own real fields stay
intact, step still `SUCCESS`, no retry).

## 14. Comparison tooling

`scripts/phase17_m3_adaptive_length_comparison.py` - a separate, manually-invoked script, never
imported by any worker. Safety, enforced in code, not just by convention:

- Defaults to `--dry-run` (verified: zero LLM Gateway calls in that mode, §18/§24 test).
- A real call requires **all three**: `--live`, `--confirm-paid-calls`, and `settings.
  adaptive_length_mode == "comparison"` (an environment-level opt-in this script never sets
  itself - `.env` was never touched).
- Hard cap of 32 candidate calls per run (`_MAX_CANDIDATE_CALLS`), enforced in code regardless of
  `--max-cases`.
- Exactly one candidate call per case - no extra retries beyond the existing bounded
  `LLMGateway`/`FallbackPolicy` machinery already in place.
- `EMPTY`-sufficiency cases are skipped (`empty_source_skip_comparison_candidate`) - none occurred
  in the real 32-case sample (§16).
- Read-only against `ContentDraft`/`EditorialTask`/`NewsEvent` - zero mutation, verified (§6 item
  8, §18).
- No import of anything under `bot/` or `services.collector`/`integrations.sources` - Telegram
  sends and new event collection are structurally unreachable from this file, not merely avoided
  by discipline (static test, §18).
- A per-case failure is logged and the run continues (`records.append(...)` inside a narrow
  `except`) - never aborts the batch.
- Output is a local, untracked JSON artifact (`scripts/_phase17_m3_comparison_results.json`) -
  never written to `EditorialTask.workflow`, never linked to `ContentDraft`.

## 15. Cost controls

Before any paid call: planned sample size (32, reusing the pinned M0/M1/M2 gold-set IDs) and call
count (1 candidate per case, 32 total) were fixed, the existing LLM Gateway's own routing was used
unmodified (no `preferred_model` override - `reasoning_effort="low"`, matching production
Copywriting's own routing exactly), and a cost estimate was computed from **real historical
`AIExecution` data** (`gpt-5.6-luna`, $1/$6 per M tokens, real production copywriting measured at
~600 input / ~87-122 output tokens) before requesting confirmation: ~48K input + ~8.1K output
tokens (generous multipliers) -> **~$0.10 estimated**. The user explicitly confirmed running all
32 cases. **Actual result: 32/32 calls succeeded, $0.081706 actual cost, model `gpt-5.6-luna`
throughout, zero errors.**

## 16. Comparison sample

Reused the exact 32 draft IDs Phase 17 M0/M1/M2 already used (`scripts/_phase17_m0_manual_audit_
ids.json`) - already stratified across `source_sufficiency` (14 sufficient, 12 partial, 6
headline_only), category (AI, GADGETS, TECH, STARTUPS, HARDWARE, SOFTWARE, UNKNOWN), and M2's own
ACCEPT/REVIEW/REJECT gold labels, and already includes the pinned Netflix/Walking Dead case
(`fa60525c`). Dry-run distribution: complexity `normal` 18, `complex` 7, `insufficient` 6,
`simple` 1 - zero `EMPTY`-sufficiency cases, so all 32 received a real candidate call.

**Known limitation on this sample**: `delivery_mode` came out `unknown` for all 32 cases - these
are historical tasks whose `"copywriting"` step never ran with `image_intelligence_mode="shadow"`
(most predate Phase 16 or ran with it off), so no real `candidates_accepted` data exists for them.
The delivery-mode/photo-caption-fit logic (§12) is exercised and unit-tested (§24) but not
validated against a real photo-eligible case in this particular comparison run - a real gap,
disclosed rather than hidden, for a future comparison batch to close once more recent
Image-Intelligence-shadow tasks exist.

## 17. Baseline metrics

n=32 real, already-delivered `ContentDraft` bodies. **Median 35 words, mean 34.0 words** - matches
M0 §4's own corpus-wide figures (median 33, mean 33.4) closely, confirming this 32-case sample is
representative of the real population, not cherry-picked toward unusually short or long drafts.

## 18. Candidate metrics

n=32 real generated candidates (`gpt-5.6-luna`, `copywriting_adaptive_candidate` v1).
**Median 71 words, mean 79.4 words** - roughly **2.3x** the baseline median. Zero truncation (no
response ended mid-sentence; all well under their own `max_tokens` budget). Zero responses
exceeded their own plan's `max_words` (0/32 above-range). **Within-range rate (candidate word
count landing inside `[min_words, max_words]`): 6/32 (18.75%)** - low overall, but sharply
bimodal by complexity tier: **`insufficient` 6/6 (100%) within range**; **`normal` 0/18 (0%)** and
**`complex` 0/7 (0%)**, all under their own `min_words` floor (`below-range`). No case landed
*above* its range in any tier. See §25 for what this means for production readiness.

## 19. A/B manual evaluation

32/32 cases reviewed (baseline vs. candidate), scored on factual correctness, unsupported claims,
completeness, clarity, beginner-friendliness, useful specifics, why-it-matters grounding,
naturalness, repetition, length appropriateness, and Telegram suitability
(`scripts/_phase17_m3_manual_ab_evaluation.json`):

| Preference | Count | Rate |
|---|---|---|
| ADAPTIVE_BETTER | 29 | 90.6% |
| TIE | 3 | 9.4% |
| BASELINE_BETTER | **0** | 0.0% |
| BOTH_WEAK | **0** | 0.0% |

Adaptive-preferred-or-tie: **32/32 (100%)** - well above the 80% target. **Zero cases where the
longer candidate was worse** (this report's own explicit "do not hide cases where longer text got
worse" instruction - none were found to hide). Quality: **31/32 GOOD, 1/32 ACCEPTABLE, 0 WEAK, 0
MISLEADING**. The one `ACCEPTABLE` case (`9997dca9`, Modi/Reels) added "Meta Platforms Inc." as
Instagram's owner - true and well-known, but not literally present in the given evidence, a minor
violation of the candidate prompt's own rule 5 ("explain only with evidence") despite being
factually correct - disclosed here, not hidden.

**Concrete quality improvements observed, not just length**: several candidates *corrected* a real
precision gap in their own baseline - `dd966828` (Google/Chrome) explicitly flags that available
material does *not* confirm the update-without-restart claim the baseline's own title implied more
directly; `ec89cf07` (OpenAI hack) explicitly separates the confirmed hack from the unconfirmed
four-company attempts; `eae93502` (Moonshot AI) explicitly avoids conflating the completed $3.5B
round with a hypothetical future $50B one. None of these were requested by the prompt directly -
they emerged from the model actually using the fuller evidence budget honestly.

## 20. Fact Safety results

**Unsupported-claim rate (manual read): 1/32 (3.1%)** - the single `9997dca9` case above (true,
but not evidence-grounded). **Misleading rate: 0/32 (0.0%)** - no candidate stated anything false
or fabricated a number/date/quote/entity not present in the real evidence (title, Research facts,
Intelligence output, or the baseline's own already-published claims). This is a manual holistic
read, not directly comparable to M0 §5's own automated `unsupported_numeric_flag` proxy (10.4%
raw, ~5% real after spot-check) - different methodology, not a like-for-like number - but the
observed rate is not worse than baseline's own historical rate by either measure. Fact Safety
itself (`services/fact_safety.py`, still `shadow` mode, unchanged) was not run as a second
automated pass over the 32 candidates in this milestone - a disclosed limitation (§25), not a
gap this report pretends doesn't exist.

## 21. Headline-only results

All 6 `headline_only`-sufficiency cases (`7acf32e8`, `b0d0f1f3`, `d9c0b32c`, `073437a9`,
`f0a6ec38`, `4f5e589e`) landed within their own 40-90-word `INSUFFICIENT` range (§18), stayed
appropriately hedged, and **none introduced a fabricated fact to compensate for the thin source** -
the exact target this milestone's own acceptance criteria required. Three of the six were rated
`TIE` rather than `ADAPTIVE_BETTER` (§19) - a thin source caps how much genuine improvement is
possible, which is itself the correct, honest outcome (matches M0 §7's own "no draft fabricated an
explanation to compensate for missing background" finding, now confirmed to hold for the adaptive
candidates too).

## 22. Photo-caption suitability

Not validated against a real photo-eligible case in this comparison batch (§16's own disclosed
limitation - all 32 historical tasks show `delivery_mode=unknown`). As a bound: at the real
7.5 chars/word ratio, 23/32 (71.9%) of the actual candidate word counts produced would fit even
the smaller, conservative (caption-sized) character budget (664 chars after reserve) had an image
been eligible - the remaining 9/32 (all `complex`-tier, richer candidates) would correctly trigger
this milestone's own "recommend text over truncation" rule (§12). This is an indicative estimate
from real word counts, not a live-tested photo-caption render.

## 23. Failure isolation

Proven at two layers: (a) the deterministic shadow plan builder inside `capabilities/executor.py`
(`test_plan_builder_failure_does_not_fail_content_generation` - a monkeypatched `RuntimeError`
leaves the `"copywriting"` step `SUCCESS` with Copywriting's own real output untouched, no retry);
(b) the comparison script's own per-case `try/except` (zero errors occurred in the real 32-case
run, §15, but the code path exists and is exercised by unit coverage of the skip-reason branches).

## 24. Tests

`tests/test_adaptive_length.py` (new, 35 tests, all passing) - mirrors M1's/M2's own three-tier
structure (pure unit / static import-shape / integration via real `CapabilityExecutor` +
`WorkflowRunner` + Postgres). Maps to all 40 required scenarios (schema validation/versioning:
1-2, 19-20; complexity: 3-7, 14-18; sufficiency: 8-13, 21; delivery/budget: 22-25; mode/
idempotency: 26-29, 38; mutation/Telegram/failure safety: 31-34, 39-40; backward compatibility/
interaction: 36-37) - comparison-tooling-specific scenarios (28-30, 35) are covered by the
script's own code-level guards (§14) plus the real dry-run/live executions performed in this
milestone (§15/§16) rather than separate pytest cases, since they require the real prompt
repository/gateway boot path already exercised end-to-end.

**Targeted run**: `tests/test_adaptive_length.py` (35), combined with `test_editorial_brief.py`,
`test_channel_relevance.py`, `test_copywriting_capability.py`, `test_capability_executor.py`,
`test_capability_executor_image_intelligence.py`, `test_fact_safety.py`, `test_editorial_
scoring.py`, `test_phase10_workflow_integration.py`, `test_content_generation_integration.py`:
**14 failures, byte-for-byte identical to M1's/M2's own already-documented pre-existing
categories** (`_ai_execution_count(db_session) == 0` against the live-growing `ai_executions`
table, plus one `.env`-vs-code-default override) - zero new failures, zero overlap with any Phase
17 M3 code.

**Ruff**: all new/changed files - all checks passed. **Mypy**: `schemas/adaptive_length.py`,
`services/adaptive_length.py`, `capabilities/executor.py`, `core/config.py`, `scripts/
phase17_m3_adaptive_length_comparison.py` - no issues found in 5 source files. **Architecture
validation**: 0 forbidden-dependency violations.

**Full regression**: established baseline first - Phase 17 M2's own most recently documented
full-suite run (`docs/phase17_m2_channel_topic_relevance_shadow_report.md` §23) was **19 failed,
1752 passed** (1771 total).

This milestone's own full run (`python -m pytest -q`, real Postgres, all four production workers
stopped throughout): **20 failed, 1786 passed** in 2537.61s (1806 total = 1771 baseline + this
milestone's 35 new tests, exactly). **19 of the 20 failures are byte-for-byte identical** to the
already-documented M1/M2 baseline categories (`test_capability_executor.py` ×8, `test_content_
generation_integration.py` ×1, `test_content_worker_cycle.py` ×2, `test_content_worker_cycle_
image_preview.py` ×1, `test_editorial_inbox_service.py` ×1, `test_editorial_scoring.py` ×2,
`test_fact_safety.py` ×2, `test_news_handler.py` ×1, `test_phase10_workflow_integration.py` ×1) -
same root cause (`_ai_execution_count(db_session) == 0` against the live-growing `ai_executions`
table, one `.env`-vs-code-default override).

**One genuinely new failure**: `tests/test_content_worker_main.py::test_enabled_loop_survives_
ordinary_exception_and_continues`. Investigated immediately, not masked: this test asserts a
content-worker polling loop completes >= 2 iterations within `asyncio.sleep(0.15)` wall-clock
seconds at a mocked `content_generation_poll_interval_seconds=0.01` - a tight, real-time timing
assertion, structurally unrelated to any Phase 17 M3 code path (`adaptive_length_mode`, `services/
adaptive_length.py`, `capabilities/executor.py`'s new hook - none of it is imported or exercised
by this test). Re-run in isolation immediately after: **passed cleanly in 12.43s**. This is the
same general class of flake the M0/M7 report and this arc's own §"triage-orchestrator" precedent
already documented (shared real infrastructure + a tight timing/state assumption gets disturbed
under the CPU/IO contention of running 1800+ tests in one process) - a timing flake surfaced by
system load during this particular run, not a deterministic regression caused by this milestone's
changes. Not re-run as a second full 42-minute suite pass to confirm non-recurrence, to avoid
unnecessary additional runtime; the isolated clean pass plus the complete absence of any code-path
overlap is the disclosed evidence for this conclusion, not a claim of certainty.

## 25. Known limitations

- **Word-range calibration is not yet reliably hit** (§18): `normal`/`complex` tiers landed
  0% within their own `min_words` floor across all 25 such cases - the candidate prompt's own
  "stop naturally, don't pad" instruction (correctly) prevents padding, but as calibrated, the
  model consistently stops well short of `min_words` even with real additional evidence available
  and genuine quality improvement happening (§19). This is the central, honest finding of this
  milestone: **quality improved dramatically and safely; the specific numeric target/min/max bands
  did not.** Two credible fixes for a future pass, neither attempted here to avoid re-spending
  budget mid-milestone: (a) recalibrate `min_words` downward for `normal`/`complex` toward what
  real single-call generation with real evidence actually produces (roughly 70-110 words judging
  by this sample); (b) strengthen the candidate prompt's own encouragement to use more of the
  available real evidence before stopping, without weakening its "never pad" rule.
- **Photo-caption suitability not live-tested** (§16, §22) - every case in this sample predates or
  ran without Image Intelligence shadow data.
- **Fact Safety was not re-run as a second automated pass** over the 32 candidates (§20) - the
  manual read is real but single-layer; a future milestone should feed candidate title/body
  through `services.fact_safety.evaluate_fact_safety()` directly (zero new cost - already
  deterministic) as a second, independent check.
- **`FOLLOW_UP` complexity remains structurally unreachable** - unchanged from M1, still blocked
  on M7+ storyline memory.
- **The single ACCEPTABLE-not-GOOD case** (§19, `9997dca9`) shows the candidate prompt's own
  evidence-only rule is not perfectly self-enforcing for extremely well-known general-knowledge
  facts - worth a small prompt refinement, not a fundamental issue (n=1/32).
- **Regulation/jargon/entity complexity signals are coarse heuristics** (§9), not a general NLP
  parser - calibrated against this report's own real cases, not exhaustively validated.

## 26. Recommendation for M4

M4 (Beginner-Friendly Copywriting) explicitly depends on M1's `EditorialBrief` (its own hallucination-
prevention discipline must exist before beginner-friendly prose leans on it - `docs/
phase17_m0_output_quality_discovery_report.md` §18's own ordering). This milestone adds: (a) real
evidence (§19, §21) that even the *current*, uncalibrated adaptive-length instruction already
improves clarity, hedging precision, and specificity - beginner-friendliness improved as a
side-effect in most of the 29 `ADAPTIVE_BETTER` cases, not just raw length; (b) the `6612ee70`
(arXiv MLIP) case is a concrete, real illustration of §25's own "specialist-source ceiling" -
useful as M4's own first hard test case once `subject_explanation` gets a real, cost-reviewed LLM
path; (c) the calibration gap in §25 should be closed *before* M4 builds on top of specific word
targets, or M4 risks inheriting numbers that don't match real model behavior.

## 27. Production activation decision

**Not activated.** `adaptive_length_mode` stays at its code default (`"off"`) - this milestone
changed no `.env` value and made no attempt to. The shadow computation (`AdaptiveLengthPlan`
construction/persistence) is production-safe today (zero cost, zero behavior change, tested
failure isolation) and could reasonably move to `"shadow"` in a live environment at the
operator's discretion without any further validation - it changes nothing observable. Feeding the
plan into real Copywriting (a future, not-yet-built `"enforce"`-equivalent mode) should **not**
happen until §25's calibration gap is closed and Fact Safety is run as a second check per-candidate
(§20) - this report's own honest recommendation, not a blocker imposed externally.

## 28. Definition of Done

- [x] Versioned `AdaptiveLengthPlan` created (`schemas/adaptive_length.py`, `schema_version="v1"`,
      `policy_version="v1"`).
- [x] Complexity determined deterministically (§9), with reason codes.
- [x] Source sufficiency accounted for (§10).
- [x] Target word range computed (§11).
- [x] Telegram character budget accounted for (§12).
- [x] Photo-caption vs. text-message recommendations differ (§12, §22 - logic tested; real-data
      validation disclosed as a limitation, §16/§25).
- [x] Shadow mode does not change production output (§13, tested:
      `test_shadow_mode_does_not_change_copywriting_output_off_vs_shadow`).
- [x] Comparison mode isolated from the production worker (§14 - a separate script, never
      imported by any worker; static-verified).
- [x] Dry-run is the default (§14, §15 - verified: the smoke/dry runs in this milestone made zero
      LLM calls until explicit `--live --confirm-paid-calls` was passed).
- [x] Paid calls require an explicit flag - **and** the env-level `adaptive_length_mode=
      "comparison"` opt-in this script never sets itself (§14).
- [x] <= 32 candidate calls - **exactly 32**, hard-capped in code (§15).
- [x] `ContentDraft` never mutated (§6 item 8, §18 - verified against real `updated_at`
      timestamps post-run).
- [x] Telegram messages sent = **0** (structurally unreachable - no `bot`/aiogram import
      anywhere in the comparison path).
- [x] Baseline and candidates compared (§17-§19).
- [x] Misleading rate measured - **0.0%** (§19, §20).
- [x] Unsupported-claim rate measured - **3.1%** (1/32, disclosed) (§20).
- [x] Headline-only cases separately checked - **0% fabrication, 100% within their own modest
      range** (§21).
- [x] Tests completed (§24).
- [x] Report created (this document).
- [x] Checkpoint created (`checkpoint/phase17-m3`, see final answer).
- [x] Production workers remained stopped throughout (Docker state confirmed at start and end of
      this milestone).
- [x] Activation decision made on real metrics (§27) - **not activated**, shadow-ready with a
      disclosed, specific tuning gap (§25).
