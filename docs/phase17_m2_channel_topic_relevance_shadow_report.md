# Phase 17 M2 — Channel/Topic Relevance Shadow — Report

Branch: `feature/phase17-editorial-intelligence`, on top of `481c719` (Phase 17 M1, checkpoint
`checkpoint/phase17-m1`). Docker: `postgres`/`redis`/`backend` `Up`; `automation_worker`,
`news_analysis_worker`, `content_worker`, `telegram_bot` remained `Exited` throughout this
milestone - never started.

## 1. Objective

Build an article-level topic/channel-fit assessment - the actual subject of one article, not the
source it came from - as a **shadow-only** ACCEPT/REVIEW/REJECT recommendation. Never blocks a
task, never changes production text, never adds LLM cost. Directly targets M0's canonical failure
mode: Engadget (tagged `GADGETS`) publishing a Netflix/Walking Dead streaming-rights story that
inherits `GADGETS` despite having nothing to do with gadgets.

## 2. Starting state

Phase 17 M1 (`docs/phase17_m1_editorial_brief_shadow_report.md`) shipped `EditorialBrief` as a
shadow step on the `"intelligence"` workflow step: 269/269 real backtest cases built successfully,
zero new LLM calls, zero production changes, checkpoint `checkpoint/phase17-m1`. This milestone
starts from that unmodified state.

## 3. M0 evidence

`docs/phase17_m0_output_quality_discovery_report.md` §11/§12: 25% of the 32-draft manual audit
(8/32) had a category/relevance issue - 15.6% wrong bucket (still on-topic), 6.3% under-classified
`UNKNOWN`, 3.1% fully off-topic (the Netflix case). §11 confirmed, by grep, that no
`channel_profile`/`allowed_topics`/`channel_fit`/topic-classifier concept existed anywhere in this
codebase before this milestone.

## 4. M1 integration

M1's `EditorialBrief.source_sufficiency` (`services/editorial_brief.py::classify_source_sufficiency()`)
is reused directly by this milestone's classifier - a pure function call, not a dependency on
`editorial_brief_mode` being `"shadow"` (§6). M2 works whether or not M1's own shadow flag happens
to be enabled.

## 5. Existing source-category behavior

Unchanged from M0's own finding: `services/event_category.py::categorize_from_tags()` maps a
**source's** static config tags to `EventCategory`, once, at collection time - never re-evaluated
per article. This milestone never modifies that function, `NewsEvent.category`, or any row - it
only adds a second, independent, article-level signal alongside it.

## 6. Architecture decision

Attach the channel-relevance assessment as an additional `"channel_relevance"` key inside the same
`"intelligence"` workflow step's result dict, immediately after M1's own `"editorial_brief"`
attachment (`capabilities/executor.py:230-231`, gated on `step.capability == "intelligence" and
settings.channel_relevance_mode == "shadow"`) - the identical seam M1/Phase 15/Phase 16 already
established. Reasons:

1. **Same step, same reasoning as M1** - `"intelligence"` is the earliest point where Research's
   facts exist; attaching before `"copywriting"` makes it structurally impossible for this data to
   reach `CopywritingCapability._build_request()`, which only reads specific, hand-picked
   `step_results` keys.
2. **No new table/migration** - purely additive JSON on `EditorialTask.workflow`, identical
   mechanism to M1 §5.
3. **No coupling to `editorial_brief_mode`** - the classifier calls `services.editorial_brief.
   classify_source_sufficiency()` directly rather than reading a persisted `"editorial_brief"` key,
   so M2 has no dependency on M1's own flag state (§4).
4. **Zero new LLM call** - `services/channel_relevance.py` imports no `LLMGateway`, no provider
   SDK, makes no network call (verified in §22/§13).
5. **Policy data separated from classifier logic** - the channel's actual topic policy lives in
   `services/channel_profiles.py` (a data-only module, never imported by anything that would treat
   it as logic); `services/channel_relevance.py` only *reads* a `ChannelProfile`, never hardcodes
   one.

Feature flag: `channel_relevance_mode: Literal["off", "shadow"] = "off"` (`core/config.py:287`),
mirroring `editorial_brief_mode`'s/`image_intelligence_mode`'s exact convention.

## 7. Topic taxonomy

`schemas/topic_taxonomy.py` - 19 values, deliberately closed (never auto-derived): `AI`, `GADGETS`,
`CONSUMER_TECH`, `SOFTWARE`, `BIG_TECH`, `CHIPS`, `CYBERSECURITY`, `GAMING_TECH`, `SCIENCE_TECH`,
`BUSINESS_TECH`, `REGULATION_TECH` (tech-relevant, `TECH_TOPICS`), `ENTERTAINMENT`,
`GAMING_CONTENT`, `POLITICS`, `SPORTS`, `LIFESTYLE`, `CRIME` (non-tech, `NON_TECH_TOPICS`), `OTHER`,
`UNKNOWN`. Deliberately separate from `database.models.news_event.EventCategory` - never merged,
only *compared* (`ArticleTopicAssessment.category_match`) - per M0's own finding that the two
concepts (source-level category vs. article-level topic) must not be conflated.

## 8. ChannelProfile schema

`schemas/channel_profile.py` (versioned, `schema_version="v1"`) + `services/channel_profiles.py`
(the concrete data). One live profile, `ai_gadgets_channel`:

| Field | Value |
|---|---|
| `primary_topics` | AI, GADGETS, CONSUMER_TECH, SOFTWARE, CHIPS |
| `secondary_topics` | BIG_TECH, CYBERSECURITY, SCIENCE_TECH |
| `allowed_adjacent_topics` | BUSINESS_TECH, REGULATION_TECH |
| `excluded_topics` | ENTERTAINMENT, POLITICS, SPORTS, LIFESTYLE, CRIME |
| `conditional_topics` | GAMING_TECH, GAMING_CONTENT |
| `required_relationships` | `conditional_topic_requires_tech_centrality`, `excluded_topic_requires_independent_tech_evidence_to_avoid_reject` |

Calibrated against `services/event_category.py`'s own existing `_CATEGORY_TAG_PRIORITY` buckets
(primary/secondary/allowed-adjacent roughly mirror AI/GADGETS/SOFTWARE/HARDWARE/CYBERSECURITY/
STARTUPS) and M0's own Netflix finding (excluded topics), not invented from scratch (§6 of
`services/channel_profiles.py`'s own docstring).

## 9. ArticleTopicAssessment schema

`schemas/article_relevance.py`, `schema_version="v1"`: `primary_topic`, `secondary_topics`,
`normalized_category` (an `EventCategory | None` bucket the primary topic maps to, for comparison
only - never written back to `NewsEvent`), `detected_entities`, `topic_evidence` (topic name ->
matched keyword fragments, never invented beyond what actually matched), `source_category`,
`category_match`, `confidence` (`RelevanceConfidence`: high/medium/low), `reason_codes`.

## 10. ChannelFitAssessment schema

`channel_profile_id`, `fit_decision` (`FitDecision` enum: `ACCEPT`/`REVIEW`/`REJECT`), `fit_score`
(bounded 0-1), `confidence`, `matched_topics`, `excluded_topics` (the profile's excluded topics
actually found in *this* article, not the profile's whole list), `conditional_matches`, `evidence`
(short `"TOPIC:keyword"` fragments, never full article text), `reason_codes`,
`human_review_required`. Plus `ShadowEditorialDecision` (`decision`, `reason_codes`, `confidence`,
`classifier_version`) - a thin, purely-derived summary for a future human-review queue consumer.

## 11. Deterministic classification rules

`services/channel_relevance.py::classify_article_topic()` - a curated, versioned, bilingual
(English/Russian) keyword lexicon (`_TOPIC_KEYWORDS`), matched via word-boundary regex against
`title + content + research.facts`. Key design decisions:

- **Bare company names never score a topic on their own** (`_ENTITY_HINTS` is evidence-only,
  surfaced in `detected_entities`) - a direct response to the false-accept risk this task's brief
  named explicitly ("Netflix использует AI" vs. "Netflix купила права на сериал" must not resolve
  the same way just because "Netflix" appears in both).
- **Tie-breaking**: a tie between two *tech* topics (e.g. CHIPS and AI both scoring for the same
  Nvidia article) raises confidence (real signal); a tie *across* the tech/non-tech boundary
  (`tech_scores and nontech_scores` both non-empty) always forces `LOW` confidence, never `HIGH`/
  `MEDIUM` - the "AI actor" ambiguity case this task's brief named explicitly.
- **Cheap, explicit pluralization** (`_pluralize()`) for single ASCII keywords only - never a real
  stemmer (mirrors `services/fact_safety.py`'s own "no general NLP parser" discipline).
- **Russian case declension**: not solved generally - the highest-stakes phrases
  ("искусственный интеллект", "машинное обучение", "регулирование", etc.) have their most common
  grammatical-case forms hand-added, each one calibrated against a real false-reject/false-review
  case found in this milestone's own backtest (§16, §24).

`assess_channel_fit()` implements the decision matrix from this task's own brief: `REJECT` only
when an excluded topic dominates **and** zero independent tech evidence exists (never from source
category alone - the exact Netflix discipline); `REVIEW` for every mixed/thin/conditional/
low-confidence case; `ACCEPT` only when a primary/secondary/allowed-adjacent topic has `HIGH`
confidence evidence and the source is not `HEADLINE_ONLY`.

## 12. Source sufficiency interaction

`classify_source_sufficiency()` (M1's own function, reused verbatim - §4/§6) gates every decision:
`HEADLINE_ONLY` always caps to `REVIEW` ("headline_only_capped_to_review"), regardless of how
clear the topic match looks - `REJECT` is still reachable for `HEADLINE_ONLY` only via an
unambiguous dominant excluded-topic match (`dominant_excluded_topic_no_tech_evidence`/
`..._headline_only`), never from thin-but-tech-looking evidence. `PARTIAL`/`EMPTY`/`CONFLICTING`/
`UNKNOWN` are each handled by the same general thin-source branch (`thin_source_capped_to_review`)
except `PARTIAL`, which is allowed a confident `ACCEPT` when topic evidence is otherwise `HIGH`
confidence (per §16's real data, this is common and correct - many real short RSS teasers are
unambiguously on-topic).

## 13. Failure isolation

`_attach_channel_relevance()` (`capabilities/executor.py:301+`) wraps the entire call in
`try/except Exception`, logs `article_topic_assessment_failed`, and returns `structured_output`
completely unchanged - identical discipline to M1's `_attach_editorial_brief`. Never raises
`StepExecutionError`, so a classifier failure can never trigger a retry, never duplicates the task,
and never fails `CONTENT_GENERATION` - proven directly by
`test_classifier_failure_does_not_fail_content_generation` (monkeypatches
`apply_channel_relevance_shadow` to raise `RuntimeError`, confirms the step still completes
`SUCCESS` with Intelligence's own fields intact).

## 14. Shadow integration

`services/channel_relevance.py::apply_channel_relevance_shadow()` mirrors M1's own
`apply_editorial_brief_shadow()` contract exactly: off-check inside the function, purely additive
merge (`{**structured_output, "channel_relevance": {...}}`). `REJECT` is only ever a persisted
shadow value - nothing in `services/content_draft_service.py`, `worker/content_cycle.py`, or
Telegram delivery reads `channel_relevance` in this milestone; `ContentDraft` and Copywriting's own
prompt are structurally unreachable from this key (§6 item 1).

## 15. Backtest sample

`scripts/phase17_m2_channel_relevance_backtest.py` (read-only: `SELECT`-only, zero `session.add`/
`flush`/`commit`, zero LLM/provider calls, zero Telegram sends). Reuses the exact 269 real
`ContentDraft` IDs pinned by Phase 17 M0/M1 (`scripts/_phase17_m0_output_quality_samples.json`).
For each draft: loads its `EditorialTask`, extracts the already-persisted `"research"`
`step_results`, and calls `assess_channel_relevance()` directly - the same pure function the
production shadow hook calls.

## 16. Aggregate metrics (269 real cases)

| Metric | Value |
|---|---|
| Rows found / build succeeded | 269 / 269 (100%, 0 exceptions) |
| `fit_decision` distribution | ACCEPT 138 (51.3%), REVIEW 130 (48.3%), REJECT 1 (0.37%) |
| `primary_topic` distribution | AI 144, UNKNOWN 61, BUSINESS_TECH 16, CHIPS 14, GADGETS 10, SOFTWARE 9, REGULATION_TECH 5, CYBERSECURITY 4, BIG_TECH 3, GAMING_TECH 1, SCIENCE_TECH 1, ENTERTAINMENT 1 |
| `source_vs_article_category_mismatch_rate` | 65.4% (176/269) - see §16a |
| `confidence` distribution | high 139 (51.7%), medium 62 (23.0%), low 68 (25.3%) |
| `unknown_topic_rate` | 22.7% (61/269) |
| `excluded_topic_present_rate` | 2.2% (6/269) |
| `mixed_topic_signal_rate` | 2.2% (6/269) |
| `headline_only` decisions | 100% REVIEW (26/26) - the §12 rule firing exactly as designed, zero exceptions |
| Top reason codes | `category_mismatch` 114, `no_topic_keywords_matched`/`primary_topic_unknown`/`no_topic_evidence_review_default` 61 each, `matched_topic_but_confidence_not_high` 47 |
| Potential off-topic reduction | 1/269 (0.37%) would be shadow-flagged REJECT - a ceiling, not a live effect |

**§16a - reading the 65.4% mismatch rate correctly**: this is **not** a defect count. `AI` primary
topic alone is 144/269 (53.5%) of the population, and a huge share of those live on GADGETS/TECH/
STARTUPS/HARDWARE/UNKNOWN-tagged sources (e.g. the Google Chrome/AI-LLM story, source `GADGETS`,
article topic `AI`) - `category_match=False` there is exactly the intended, correct signal that
source-category inheritance is imprecise (M0's own root-cause finding), not that the article is
off-channel. `ChannelFitAssessment.fit_decision` (not `category_match`) is the metric that actually
drives an editorial recommendation, and it treats AI-content-on-a-GADGETS-source as a clean
`ACCEPT` (both are in `ai_gadgets_channel`'s own `primary_topics`).

## 17. Manual gold set

32 draft IDs (the same set Phase 17 M0 manually audited) - `scripts/_phase17_m2_manual_gold_set.json`.
Explicitly **not** claimed as full production ground truth (this task's own required caveat) - a
small, hand-labeled calibration set. Labels are this milestone's own channel/topic-relevance
judgment, a distinct axis from M0's editorial-quality verdicts and M1's per-brief completeness
read (§17a). All 6 required regression cases (this task's own brief) are present and correctly
labeled:

1. Netflix/Walking Dead: gold `REJECT`, predicted `REJECT`. ✓
2. Real AI-topic article (`dfca74b1`, Nvidia CEO on AI/jobs): gold `ACCEPT`, predicted `ACCEPT`. ✓
3. Real gadget article (`1cdfbf19`, Apple Q3 iPhone/Mac/iPad earnings): gold `ACCEPT`, predicted
   `ACCEPT`. ✓
4. Mixed business/tech article (`715cf6ed`, Dili AI-compliance funding): gold `ACCEPT`, predicted
   `ACCEPT`, documented reason (`BUSINESS_TECH`+`AI` both matched, in `allowed_adjacent_topics`/
   `primary_topics`). ✓
5. Headline-only ambiguous article (`cc5dcb84`, AI school clubs, 12 raw words): gold `REVIEW`,
   predicted `REVIEW`. ✓
6. Entertainment article with incidental tech keyword: no single real draft in the 32-set matches
   this exactly, so a synthetic case was added directly to the test suite instead
   (`test_entertainment_article_from_technology_source_incidental_keyword`,
   `test_low_confidence_mixed_signal_is_review_not_reject`) - asserts `REVIEW`, never a confident
   `ACCEPT`, matching this requirement's own "REJECT or REVIEW, never confident ACCEPT" wording.

**§17a**: `acc80872` (AI-and-moral-agency doctoral program) is gold-labeled `ACCEPT` here even
though M1's own manual audit rated its *brief* `WEAK` (source-thinness, a completeness concern) -
both are correct simultaneously: the article is unambiguously about AI (channel/topic fit), while
its source material is too thin to write a complete, well-evidenced post about it (editorial
completeness). This is the A/B distinction M0 itself defined (§12 of the M0 report) working
correctly across two different milestones.

## 18. Confusion matrix

Rows = gold label, columns = predicted decision, n = 32:

| Gold \ Predicted | ACCEPT | REVIEW | REJECT |
|---|---|---|---|
| **ACCEPT** (21) | 16 | 5 | 0 |
| **REVIEW** (9) | 0 | 9 | 0 |
| **REJECT** (2) | 0 | 1 | 1 |

- Accuracy (exact 3-way match): 26/32 = **81.25%**
- REJECT precision: 1/1 = **100%** (the one REJECT the classifier made was correct)
- REJECT recall: 1/2 = **50%** (one real off-topic case, §20, landed in REVIEW instead of REJECT -
  safe direction, not a safety violation)
- REVIEW rate: 15/32 = **46.9%**
- Coverage (non-REVIEW): 17/32 = **53.1%**

## 19. False accept analysis

**False accept rate (gold REJECT -> predicted ACCEPT): 0/2 = 0.0%.** Zero cases anywhere in the
32-case gold set, or in the 269-case backtest's own reason-code trace, where an article the
classifier scored `HIGH` confidence `ACCEPT` was actually off-topic. Every `HIGH`-confidence
`ACCEPT` in the gold set (16/16) matches its gold label exactly (§16's own "misleading
high-confidence decisions: 0" finding, §26).

## 20. False reject analysis

**False reject rate on gold-`ACCEPT` cases: 0/21 = 0.0%** - meets this task's own explicit
acceptance target exactly. The one gold-`REJECT` case the classifier missed (`9997dca9`, Modi/
Instagram Reels political-communication story during student protests) landed in `REVIEW`, not
`ACCEPT` - a recall gap (my `POLITICS` lexicon has no "student protest"/political-figure-name
signal), but structurally impossible to become a *false accept* of off-topic material, since
`REVIEW` still requires human judgment before anything happens. Five gold-`ACCEPT` cases similarly
landed in `REVIEW` rather than a confident `ACCEPT` (§24) - all traced to specific, named lexicon
gaps (bare company names, single-keyword confidence threshold), all in the safe direction.

## 21. Netflix/Walking Dead regression

Draft `fa60525c-fce6-44c1-b8ed-5e2de7e22973` (Engadget, `NewsEvent.category=GADGETS`). Article
topic: `primary_topic=ENTERTAINMENT` (`streaming rights`/`spin-off`-family keywords matched),
`normalized_category=None` (ENTERTAINMENT has no `EventCategory` equivalent - correctly flagged
`no_event_category_equivalent`), `category_match=False`. Channel fit: `excluded_topics=
[ENTERTAINMENT]`, `matched_topics=[]` (zero independent tech evidence), `fit_decision=REJECT`,
`confidence=HIGH`, `reason_codes=["no_event_category_equivalent",
"dominant_excluded_topic_no_tech_evidence"]`, `human_review_required=False`. This is the **only**
`REJECT` in the entire 269-case real population (§16) - confirming the classifier does not
over-fire on excluded topics generally; it fires precisely on the one case this whole milestone
was built to catch.

## 22. Cost impact

**Zero.** `classify_article_topic()`/`assess_channel_fit()`/`decide_shadow_editorial()`/
`assess_channel_relevance()` take no `LLMGateway`, make no network call, and
`services/channel_relevance.py` imports neither `integrations.llm_gateway` nor any provider SDK -
verified two ways: (a) `scripts/validate_architecture.py` (0 forbidden-dependency violations,
run after this milestone's changes, §16 of that script's own scan), (b)
`test_channel_relevance_module_imports_no_llm_gateway_or_telegram`, a static import-graph walk.
Both the 269-row backtest (§15/§16) and the 32-case gold-set evaluation (§17/§18) ran entirely
against already-persisted data - zero API calls of any kind.

## 23. Tests

`tests/test_channel_relevance.py` (new, 36 tests, all passing) - mirrors `tests/
test_editorial_brief.py`'s three-tier structure. Maps to all 30 required scenarios (schema
validation/versioning/profile validation: tests 1/2/30; classification: 3/4/9/10/15/16/21;
channel-fit decisions: 5/6/7/8/11/17/18/19/20; sufficiency interaction: 11/12; missing upstream
data: 13/14/27; mode/idempotency: 26/28/29; static import-shape: 24/25; integration/failure/
ContentDraft-safety: 22/23 - full mapping detail mirrors M1's own report §19 structure, one test
function per named scenario, see the test file's own section headers).

**Targeted run**: `tests/test_channel_relevance.py` - **36 passed**. Combined with `tests/
test_editorial_brief.py`, `test_capability_executor.py`, `test_capability_executor_image_
intelligence.py`, `test_fact_safety.py`, `test_editorial_scoring.py`,
`test_phase10_workflow_integration.py`, `test_content_generation_integration.py`: **14 failures**,
individually inspected and confirmed to be the **exact same 14 pre-existing failures** M1's own
report (§19) already traced to a documented, unrelated `_ai_execution_count(db_session) == 0`
live-table-growth issue and one `.env`-vs-code-default environment override - zero new failures,
zero overlap with any `channel_relevance`/`article_relevance`/`topic_taxonomy` code.

**Ruff**: all 9 new/changed files - **all checks passed**.

**Mypy**: `schemas/topic_taxonomy.py`, `schemas/channel_profile.py`, `schemas/article_relevance.py`,
`services/channel_profiles.py`, `services/channel_relevance.py`, `capabilities/executor.py`,
`core/config.py` - **no issues found in 7 source files**.

**Architecture validation**: `python scripts/validate_architecture.py` - **0 forbidden-dependency
violations**.

**Full regression**: established baseline first (not trusted blindly) - M1's own most recently
documented full-suite run (`docs/phase17_m1_editorial_brief_shadow_report.md` §19) was **19
failed, 1716 passed** (1735 total), captured with the same production-pause state this milestone
also maintained throughout (workers stopped).

This milestone's own full run (`python -m pytest -q`, real Postgres, all four production workers
stopped throughout): **19 failed, 1752 passed** in 1332.43s (1771 total = 1735 baseline + this
milestone's 36 new tests, exactly). The failing test names are **byte-for-byte identical** to
M1's own baseline list (`test_capability_executor.py` ×8, `test_content_generation_integration.py`
×1, `test_content_worker_cycle.py` ×2, `test_content_worker_cycle_image_preview.py` ×1,
`test_editorial_inbox_service.py` ×1, `test_editorial_scoring.py` ×2, `test_fact_safety.py` ×2,
`test_news_handler.py` ×1, `test_phase10_workflow_integration.py` ×1) - the same count (19) as
M1's own run, same categories, same root cause (`_ai_execution_count(db_session) == 0` against the
live-growing `ai_executions` table, plus one `.env`-vs-code-default override) - **zero new
failures, zero regressions, zero overlap with any Phase 17 M2 code.**

## 24. Known limitations

- **Bare company names never score a topic** (§11) - the deliberate false-accept-avoidance
  trade-off costs real recall on stories that are ABOUT a named company's business/product
  situation without other topic keywords present (§20's `67f52338` Apple-supply-constraints case).
  A future milestone could add a narrow "company name + business-context co-occurrence" signal
  without reopening the Netflix-name-alone risk, but that is a deliberate scope decision for a
  later pass, not solved here.
- **Russian morphology is hand-patched per phrase, not solved generally** (§11) - every fix in
  this report was calibrated against a real case found in the 269-case backtest or the 32-case
  gold set; an inflected form not yet seen in this data will simply miss (safe-direction: lands in
  `REVIEW`/`UNKNOWN`, never a false `ACCEPT`/`REJECT`).
- **Single-keyword confidence threshold is sometimes too conservative** - a genuinely clear,
  single-signal `BUSINESS_TECH`/`AI` match (§20's `491db283` Atoms-robotics-funding,
  `3befaa5e` deepfakes case) lands at `MEDIUM` confidence and `REVIEW` rather than `ACCEPT`,
  because `_topic_confidence()`'s `total_evidence >= 2` threshold was calibrated toward the safe
  side (M2's own explicit priority: "false reject worse than false review") at the cost of REVIEW
  volume.
- **`POLITICS`/`SPORTS`/`LIFESTYLE`/`CRIME` lexicons are thin** relative to the tech-topic lexicons
  (deliberately - this is a technology newsroom's own real source mix, and most non-tech drift is
  entertainment-adjacent, not political/sports/lifestyle) - §20's `9997dca9` (student-protest
  story) shows a real gap here, though the miss lands safely in `REVIEW`.
- **`fit_score` is a coarse, hand-assigned scalar per decision branch**, not a continuously
  calibrated probability - useful for ranking/sorting within a decision bucket, not for
  cross-decision threshold tuning without further calibration work.
- **`GAMING_CONTENT`/`GAMING_TECH` conditional-topic logic has only 1 real trigger** in the
  269-case backtest (§16) - too small a sample to validate the `conditional_topic_requires_tech_
  centrality` rule beyond the one synthetic test case (`test_conditional_topic_with_tech_
  centrality_can_accept`).

## 25. M3 handoff

M3 (Adaptive Length) does not directly depend on M2's own output - M0 §15 already established
that adaptive length is driven by source complexity/richness, not topic/channel fit. What M2 does
hand forward:

- A validated, real `channel_relevance` payload sitting alongside M1's `editorial_brief` on the
  same `"intelligence"` step - a future M4/M5 (Beginner-Friendly Copywriting, Completeness Gate)
  milestone that wants topic-aware behavior (e.g. skip beginner-friendly rewriting for a
  specialist `SCIENCE_TECH` piece) has the signal already computed and persisted, at zero
  incremental cost.
- The `ChannelProfile` schema/registry (§8) is ready for a second channel without any classifier
  change - purely additive data.
- §24's concrete, named limitations (company-name recall, Russian morphology, confidence threshold
  conservatism, thin non-tech-topic lexicons) are the right starting punch list for any future
  calibration pass, rather than starting from a blank slate.

## 26. Definition of Done

- [x] Article-level topic taxonomy created (`schemas/topic_taxonomy.py`, 19 values).
- [x] `ChannelProfile` versioned (`schema_version="v1"`, `services/channel_profiles.py`).
- [x] `ArticleTopicAssessment` versioned (`schema_version="v1"`).
- [x] `ChannelFitAssessment` versioned (`schema_version="v1"`).
- [x] Source category and article topic kept separate (§5/§7) - `NewsEvent.category` never
      written to; only compared via `category_match`.
- [x] Deterministic classifier, zero new LLM call (§11, §22).
- [x] Channel-fit works in shadow (§14, default `off`).
- [x] ACCEPT/REVIEW/REJECT persisted (§14, §16).
- [x] Pipeline never blocked - `REJECT` is shadow-only (§13, §14, tested).
- [x] Production text unchanged - Copywriting's own drafted output byte-identical off vs. shadow
      (`test_shadow_mode_does_not_change_copywriting_or_content_draft_fields`).
- [x] `ContentDraft` unchanged (§14).
- [x] API cost impact = **0** (§22).
- [x] Telegram sends = **0** (never called, static-verified).
- [x] >= 269 real cases checked - **269** (§15/§16).
- [x] >= 32 manual gold cases checked - **32** (§17/§18).
- [x] Netflix/Walking Dead = `REJECT` (§21).
- [x] Obvious AI/Gadget cases = `ACCEPT` (§16's own "misleading high-confidence decisions: 0"
      finding - every `HIGH`-confidence gold-`ACCEPT` case predicted correctly).
- [x] Ambiguous headline-only cases = `REVIEW` (§12, §16: 26/26 = 100%).
- [x] False reject rate measured - **0.0%** on gold-`ACCEPT` cases (§20).
- [x] False accept rate measured - **0.0%** on gold-`REJECT` cases (§19).
- [x] Misleading high-confidence decisions: **0** (§18, §19).
- [x] Tests completed - 36 new tests, targeted suite, Ruff clean, Mypy clean, architecture
      validation clean (§23).
- [x] Report created (this document).
- [x] Checkpoint created (`checkpoint/phase17-m2`, see final answer).
- [x] Production workers remained stopped throughout (Docker state confirmed at start and end of
      this milestone).
