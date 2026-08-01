# Phase 17 M1 — Editorial Brief Shadow — Report

Branch: `feature/phase17-editorial-intelligence`, on top of `77957b2` (Phase 17 M0, checkpoint
`checkpoint/phase17-m0`). Docker: `postgres`/`redis`/`backend` `Up`; `automation_worker`,
`news_analysis_worker`, `content_worker`, `telegram_bot` remained `Exited` throughout this
milestone - never started.

## 1. Objective

Build a structured `EditorialBrief` - the pre-Copywriting editorial plan M0 (§14/§18) designed -
as a **shadow-only** step: computed and persisted for later M2-M6 analysis, never read by
`CopywritingCapability`, never changing `ContentDraft`, never adding production API cost.

## 2. Starting state

M0 (`docs/phase17_m0_output_quality_discovery_report.md`) measured 269 real `ContentDraft` rows
and manually audited 32: median body 33 words, 100% single-paragraph, 18.75-21.9% headline-rewrite
rate, 25% category/relevance issues (Netflix/Walking Dead/Engadget/GADGETS as the canonical case),
`NewsEvent.summary` 0% populated, and traced the root cause to `CopywritingCapability` never
reading `NewsEvent.content` - only Research's already-paraphrased `facts`. No production code was
touched by M0; this milestone starts from that unmodified baseline.

## 3. M0 findings addressed

| M0 finding | M1 response |
|---|---|
| No explicit length/structure target exists (§13 item 3) | `target_word_range`/`recommended_format` computed, shadow-persisted (§10/§11), not yet applied to Copywriting (M3's job) |
| `research.gaps` exists but is unused (§14 table) | `uncertainties` wires it in directly - zero new cost |
| No completeness/relevance dimension on Quality (§13 item 5) | Out of scope for M1 (that is M5's Completeness Gate); M1 only builds the Brief the gate will eventually read |
| Category is 100% source-inherited (§13 item 6) / no channel-fit gate (§13 item 7) | Explicitly **not** addressed here - M1's `recommended_format` reflects source-material sufficiency only, never topic/channel fit (§10 below); reserved for M2 |
| Thin/headline-only sources are ~31% of real drafts (§10) | `source_sufficiency`/`HEADLINE_ONLY` classification + non-expansive `target_word_range` (§9/§11) |
| Automated proxies (headline-rewrite, unsupported-numeric) are materially uncalibrated vs. real editorial judgment (§6/§9) | This report's own manual audit (§17) is scored by hand against the same discipline, not trusted from a proxy alone |

## 4. Current pipeline integration point

Traced directly in `capabilities/executor.py` (unchanged reading from M0 §2): `CapabilityExecutor.
execute()` builds a `CapabilityContext` per step, runs the step's `Capability`, then applies
zero-or-more deterministic post-processing hooks gated on `step.capability` and a settings flag -
the exact seam Phase 15 M4 (`editorial_scoring`, on `"scoring"`), Phase 15 M5 (`fact_safety`, on
`"quality"`), and Phase 16 M1 (`image_intelligence`, on `"copywriting"`) already established.
`CONTENT_GENERATION`'s four steps (`workflows/definitions/content_generation.py`) run
`research -> intelligence -> copywriting -> quality`, in that fixed order.

At the `"intelligence"` step, `context.business.workflow_state.step_results` already contains
Research's completed `{facts, confidence, gaps}` (research always runs first), and the
just-computed `structured_output` **is** Intelligence's own `{significance, angle,
audience_relevance, recommendation}` - both for free, zero new DB query, zero new LLM call.

## 5. Architecture decision

Attach `EditorialBrief` as an additional `"editorial_brief"` key inside the `"intelligence"`
step's own persisted `result` dict (`capabilities/executor.py:219-220`, gated on
`step.capability == "intelligence" and settings.editorial_brief_mode == "shadow"`). Reasons:

1. **Earliest complete seam** - `"intelligence"` is the first step where both Research's facts
   and Intelligence's own judgment exist; `"research"` alone would be too early.
2. **Before Copywriting, structurally** - attaching to `"intelligence"`'s own result (not
   `"copywriting"`'s) makes it physically impossible for this data to influence
   `CopywritingCapability._build_request()`, which only ever reads `step_results["research"]`/
   `["intelligence"]` by explicit, hand-picked field names (`capabilities/
   copywriting_capability.py:117-118`) - an extra sibling key on the same dict is never touched.
3. **No new table/migration** - `EditorialTask.workflow` (`database/models/editorial_task.py:44`,
   a plain `JSON` column) already persists `WorkflowExecutionState.step_results: list[
   WorkflowStepResult]`, each `result: dict[str, Any]` (`schemas/workflow.py:75-91`) - purely
   additive, matches `fact_safety`'s/`image_intelligence`'s own established persistence path
   exactly.
4. **Backward compatible for free** - an old task's `step_results["intelligence"]` simply lacks
   `"editorial_brief"`; nothing reads for it unless `editorial_brief_mode == "shadow"`, and even
   then a missing key is just "not computed," never an error.
5. **Zero new LLM call** - `services/editorial_brief.py::build_editorial_brief()` is a pure
   function of already-fetched `NewsEventSnapshot` + Research/Intelligence output; it imports no
   `LLMGateway`, no provider SDK (verified both by `scripts/validate_architecture.py`, §21, and a
   dedicated static test, §19 item 18).

Feature flag: `editorial_brief_mode: Literal["off", "shadow"] = "off"` (`core/config.py:275`),
mirroring `image_intelligence_mode`'s exact off/shadow convention - a brand-new capability with no
live validation yet, so it defaults to the fully-inert `"off"`, not `"shadow"`.

## 6. EditorialBrief schema

`schemas/editorial_brief.py` (new, 118 lines). All list/dict fields use `Field(default_factory=
...)` - no mutable default is ever shared between instances (tested, §19 item "mutable defaults").

| Field | Type | Notes |
|---|---|---|
| `schema_version` | `str` | `"v1"` |
| `headline_fact` | `str \| None` | pick, not generation |
| `subject_explanation` | `str \| None` | always `None` in M1 (§8) |
| `event_details` | `list[str]` | from Research's `facts`, deduped |
| `background_context` | `list[str]` | always `[]` in M1 (§8) |
| `difference_or_change` | `str \| None` | always `None` in M1 (no storyline memory) |
| `why_it_matters` | `list[str]` | from Intelligence's `significance`/`angle` |
| `what_next` | `list[str]` | from Intelligence's `recommendation` only (deliberately not Research's `gaps` - see §6a) |
| `uncertainties` | `list[str]` | Research's `gaps` + an honest thin-source note when applicable |
| `recommended_format` | `RecommendedFormat` enum | §10 |
| `target_word_range` | `TargetWordRange` (`min_words`/`max_words`, structured, not a string) | §11 |
| `source_sufficiency` | `SourceSufficiency` enum | §9 |
| `source_sufficiency_reason_codes` | `list[str]` | §9 |
| `evidence_notes` | `dict[str, FieldProvenance]` | §8 |

**6a. Deliberate deviation from the user's own sketch table**: `what_next` is sourced only from
`intelligence.recommendation`, not "partially from `research.gaps`" as originally proposed -
`gaps` (missing information) and `what_next` (predicted future developments) are different
concepts, and conflating them would blur `uncertainties`' own honesty signal. `research.gaps`
feeds `uncertainties` exclusively. Permitted under this task's own "field names/types may be
adjusted if the architecture requires it, meaning preserved" allowance.

## 7. Schema versioning

`EDITORIAL_BRIEF_SCHEMA_VERSION = "v1"` (`schemas/editorial_brief.py:23`), stamped as
`EditorialBrief.schema_version`'s default and asserted present in every persisted brief
(`test_schema_version_is_stamped_and_serializes`). A future M2+ schema change bumps this constant;
readers of persisted JSON key on it rather than assuming a shape. Round-trip losslessness
(`EditorialBrief.model_validate(brief.model_dump(mode="json")) == brief`) is directly tested.

## 8. Evidence and Fact Safety rules

Every field carries a `FieldProvenance` (`confidence: confirmed|inferred|unknown|unavailable`,
`source: news_event|research|intelligence|derived|none`, `reason_codes: list[str]`) - never a
free-text justification that would duplicate source text. Two fields structurally require
pretrained world knowledge an LLM would have to supply - `subject_explanation`/
`background_context` - and M1 is explicitly forbidden from adding that second paid call
(`services/editorial_brief.py` module docstring). Both are **always** `None`/`[]`, tagged
`unavailable`, `reason_codes=["requires_llm_not_available_in_m1"]` - never filled from whatever
text happens to be on hand, tested directly by
`test_unknown_fields_remain_empty_never_fabricated_even_with_rich_source` even against a
deliberately rich, detail-heavy source. `difference_or_change` is likewise always `None`
(`reason_codes=["no_storyline_memory_m1"]`) - M7+'s job.

**Interaction with the existing Fact Safety layer** (`services/fact_safety.py`, Phase 15 M5,
`fact_safety_mode` still `shadow`, unchanged by this milestone): not wired together in M1 - the
Brief is never fed into `apply_fact_safety()`'s evidence packet, and Fact Safety's own claim
extraction never runs against Brief content. This is deliberate scope discipline (M0 §17's own
recommendation to keep `fact_safety_mode=shadow` unchanged through M1-M3); the two systems will
need to meet once `subject_explanation`/`background_context` are actually populated by a future
LLM-backed milestone, at which point Fact Safety's claim classifier will need the new
background-knowledge category M0 §17 already specified.

## 9. Source sufficiency

`services/editorial_brief.py::classify_source_sufficiency()` - pure, deterministic, six states:

- **`EMPTY`**: no content and no Research facts (`reason_codes=["no_content", "no_research_facts"]`).
- **`PARTIAL`**: no content but Research facts exist; or content present but under 30 words / fewer
  than 1 concrete-detail signal.
- **`HEADLINE_ONLY`**: content under 12 words, or a near-duplicate of the title
  (`content_equals_title`, or `content_is_title_plus_suffix` for the Google-News "headline +
  outlet name" pattern M0 §10 documented).
- **`SUFFICIENT`**: content >= 30 words and >= 1 concrete-detail signal (numbers, currency, years,
  percentages, capitalized-token density - the same proxy family M0's own script used).
- **`CONFLICTING`**: `research.gaps` contains an explicit disagreement keyword (`conflict`,
  `contradict`, `discrepan`, `inconsistent`, `disput`, and Russian equivalents) - a narrow,
  testable signal, never a general NLI classifier; an unlisted synonym simply never triggers it.
- **`UNKNOWN`**: defensive fallback (missing title only, in practice).

Length alone is never treated as sufficiency (M0 §10's own explicit warning) -
`test_long_but_thin_content_is_not_automatically_sufficient` proves 40 words of zero-detail filler
still classifies `PARTIAL`, not `SUFFICIENT`.

## 10. Recommended formats

`recommend_format_and_range()` maps sufficiency (plus, for `SUFFICIENT`, content richness) to one
of six `RecommendedFormat` values: `reject_candidate` (EMPTY/UNKNOWN - no material at all),
`insufficient_source` (HEADLINE_ONLY/CONFLICTING - do not force expansion, per M0 §10/§15),
`short_update` (PARTIAL), `standard_news` or `explainer` (SUFFICIENT, split on word/sentence
richness), and `follow_up` (defined for schema completeness, **structurally unreachable in M1** -
it would require `difference_or_change`, which needs storyline memory that does not exist until
M7+). `reject_candidate` reflects source-material insufficiency **only** - never channel/topic
relevance (M0 §11's own "must not conflate" warning) - and, per M1's own explicit instruction,
never blocks a task; it is a shadow recommendation, nothing else.

## 11. Target word ranges

Reuses M0 §15's own four bands unchanged: Simple 90-140 (`short_update`), Normal 140-220
(`standard_news`), Complex 220-320 (`explainer`), Follow-up 180-300 (`follow_up`, unreachable).
Below `insufficient_source`/`reject_candidate`, a fifth, narrower band was added -
**40-90 words for `insufficient_source`**, anchored a little above the real historical median (33
words, M0 §4) rather than forcing the 90-word Simple floor onto a source that cannot responsibly
support it (M0 §10/§15's own "do not force artificial expansion" instruction); **0-0 for
`reject_candidate`** (nothing recommended). Deliberately **not** yet photo-caption-aware (M0 §15's
own recommendation that adaptive length branch on image-candidate presence) - Image Intelligence
only runs at the later `"copywriting"` step, so that data does not exist yet at `"intelligence"`;
flagged as a known M3 design input, not solved here (§20). M1 only computes and persists this
range - `CopywritingCapability`'s own prompt is completely unchanged.

## 12. Shadow persistence

`services/editorial_brief.py::apply_editorial_brief_shadow()` - the same
`apply_fact_safety()`-shaped contract (off-check inside the function, purely additive dict merge:
`{**structured_output, "editorial_brief": brief.model_dump(mode="json")}`). `capabilities/
executor.py::_attach_editorial_brief()` (lines 235-286) is the only call site, gated at
`step.capability == "intelligence" and editorial_brief_mode == "shadow"` (double gating, cheap and
harmless - matches `image_intelligence`'s own existing double-gate precedent). Persisted through
the existing `WorkflowRunner` -> `EditorialTask.workflow` JSON path, no new table, no migration.

## 13. Failure isolation

`_attach_editorial_brief()` wraps the whole call in `try/except Exception`, logging
`editorial_brief_failed` and returning `structured_output` completely unchanged on any error -
mirrors `_attach_image_intelligence()`'s own "must not affect delivery" discipline exactly. Since
the hook runs entirely inside the already-succeeded `"intelligence"` step's own post-processing (never
raising `StepExecutionError`/`PermanentStepFailureError`), a Brief failure can never trigger a
retry and can never fail `CONTENT_GENERATION` -
`test_brief_failure_does_not_fail_content_generation` proves this by monkeypatching
`apply_editorial_brief_shadow` to raise `RuntimeError` and confirming the step still completes
`SUCCESS` with Intelligence's own fields (`significance`, etc.) intact and no `"editorial_brief"`
key present. Structured logging (`editorial_brief_started`/`completed`/`failed`, `schema_version`,
`source_sufficiency`, `recommended_format`, `target_min_words`/`target_max_words`,
`populated_field_count`, `reason_codes`) - never raw news content, the full brief text, or secrets.

## 14. Cost impact

**Zero.** `build_editorial_brief()`/`classify_source_sufficiency()`/`recommend_format_and_range()`
take no `LLMGateway`, make no network call, and the module imports neither
`integrations.llm_gateway` nor any provider SDK - verified two ways: (a)
`scripts/validate_architecture.py` (§21, 0 forbidden-dependency violations across the whole repo,
run after this milestone's changes), (b) a dedicated static test,
`test_editorial_brief_module_imports_no_llm_gateway_or_telegram`, walking the module's own
import graph. The 269-row backtest (§15/§16) and the 32-brief manual audit (§17) both ran entirely
against already-persisted data - zero API calls of any kind.

## 15. Backtest sample

`scripts/phase17_m1_editorial_brief_backtest.py` (read-only: `SELECT`-only, zero `session.add`/
`flush`/`commit`, zero LLM/provider calls, zero Telegram sends). Reuses the **exact 269 real
`ContentDraft` IDs pinned by Phase 17 M0** (`scripts/_phase17_m0_output_quality_samples.json`) for
direct comparability. For each draft: loads its `EditorialTask`, extracts the already-persisted
`"research"`/`"intelligence"` `step_results` from `EditorialTask.workflow` (the real historical
data - reused, never re-run), and calls `build_editorial_brief()` directly - the same pure
function the production shadow hook calls. Manual-audit subset: the same 32 draft IDs M0 manually
audited (`scripts/_phase17_m0_manual_audit_ids.json`), including the pinned Netflix/Walking Dead
case (`fa60525c-fce6-44c1-b8ed-5e2de7e22973`).

## 16. Aggregate results (269 real cases)

| Metric | Value |
|---|---|
| Rows found / build succeeded | 269 / 269 |
| Build success rate | **100.0%** (0 exceptions) |
| `source_sufficiency` distribution | `sufficient` 120 (44.6%), `partial` 123 (45.7%), `headline_only` 26 (9.7%), `empty`/`conflicting`/`unknown` 0 each |
| `recommended_format` distribution | `standard_news` 113 (42.0%), `short_update` 123 (45.7%), `explainer` 7 (2.6%), `insufficient_source` 26 (9.7%), `reject_candidate`/`follow_up` 0 each |
| `target_word_range` distribution | 90-140: 123, 140-220: 113, 220-320: 7, 40-90: 26 |
| `event_details` count | mean 3.32, min 1, max 9 |
| `why_it_matters` empty rate | **0.0%** (0/269) - Intelligence's own `significance`/`angle` are populated in every real case sampled |
| `what_next` empty rate | **0.0%** (0/269) - Intelligence's own `recommendation` likewise always populated |
| `uncertainties` present rate | 96.65% (260/269) |
| `headline_only` rate | 9.67% (26/269) - lower than M0's 31% manual-audit finding because that 31% figure was itself only from the smaller 32-draft *manual* subsample (which deliberately over-represents thin sources); the full 269-row automated `HEADLINE_ONLY` classifier is a stricter, narrower definition than M0's manual "headline-only or content-free in every practical sense" judgment - not a contradiction, a different measurement of a related but not identical thing (flagged explicitly, §20) |
| `false_confidence_case` rate (thin sufficiency + non-empty `why_it_matters`/`what_next`) | 9.67% (26/269) - identical to the headline-only count, since every thin case in this real population was `HEADLINE_ONLY` (no `EMPTY`/`CONFLICTING`/`UNKNOWN` occurred) |
| `no_research_output` / `no_intelligence_output` | 0 / 0 - every real task had both steps' results persisted |
| `populated_field_count` mean | 4.97 of 8 content-bearing fields |

Full per-record output: `scripts/_phase17_m1_editorial_brief_backtest_results.json` (untracked,
reproducible from the pinned sample IDs, matching M0's precedent).

**The "false confidence" finding, read correctly**: in all 26 cases, `why_it_matters`/`what_next`
are non-empty *because* they come from Intelligence's own upstream, source-blind judgment - not
because the Brief invented anything. This is not a defect in this milestone's code; it is a real,
now-measured architectural fact worth flagging for M2/M4: Intelligence's significance/angle/
recommendation are computed without knowing whether Research had thin material to work with, so a
downstream reader must cross-reference `why_it_matters`/`what_next` against `source_sufficiency`
itself rather than trusting either field in isolation.

## 17. Manual review (32 briefs)

Rated by hand against the checklist (main fact, concrete details, no fabrication, correct
`source_sufficiency`, correct format, reasonable range, honest uncertainties, beginner-friendly
potential, suitability for a future Copywriting read) - `GOOD` / `ACCEPTABLE` / `WEAK` /
`MISLEADING`:

| Verdict | Count | Rate |
|---|---|---|
| GOOD | 28 | 87.5% |
| ACCEPTABLE | 3 | 9.4% |
| WEAK | 1 | 3.1% |
| MISLEADING | **0** | **0.0%** |

**Zero misleading/fabricated briefs found** across all 32 - directly confirms M0 §9's own finding
("no case of outright fabrication... found in the 32-draft manual read") extends cleanly to the
new Brief layer: everywhere the underlying source was thin, the Brief said so (`uncertainties`,
`source_sufficiency=headline_only`), rather than inventing texture to compensate.

The 3 `ACCEPTABLE` cases, named for M2/M3 calibration:
- `44381b14` (TikTok/EU) - `concrete_details=0` even though `event_details` (from Research's own
  facts) mentions a real "6%" figure; the deterministic detail-counter only scans raw
  `NewsEvent.content`, not Research's paraphrase, so it undercounts whenever Research's own
  phrasing differs from the source text's exact digits/format - the same class of noisy-proxy gap
  M0 §5/§6 already documented for its own regex proxies.
- `a4e1f1ae` (DOJ/Apple) - `headline_fact` (`facts[0]`) is accurate but vague ("Министерство
  юстиции США попросило суд пересмотреть недавнее решение") - the more specific detail ("Apple",
  "14 federal agencies") only appears in `event_details[1]`. `headline_fact` inherits whatever
  ordering Research's own `facts` list happens to use; picking "most information-dense fact" rather
  than literally `facts[0]` is a candidate refinement for a later milestone, not fixed here.
- `715cf6ed` (Dili funding) - `PARTIAL` sufficiency (25 raw words) with rich, well-populated
  `event_details` (investor names) but an **empty `uncertainties` list** - `PARTIAL` is not in the
  "thin" state set that triggers the honest thin-source note (§9's `HEADLINE_ONLY`/`EMPTY`/
  `CONFLICTING`/`UNKNOWN` only), and no `research.gaps` existed for this draft. Not fabrication -
  everything stated is genuinely supported - but a mild honesty gap worth a design review: should
  `PARTIAL` also default to at least one honest caveat when `research.gaps` is empty.

The 1 `WEAK` case, `acc80872` (AI-divinity doctorate) - matches **M0's own independent WEAK
verdict for this exact draft** (M0 §6, "judged WEAK primarily for source-thinness"), a useful
cross-check: the Brief's `partial` sufficiency and hedged `why_it_matters`/`uncertainties` broadly
reflect the same real limitation M0's human reviewer already flagged, giving some confidence this
milestone's classification is tracking real editorial judgment, not just its own internal logic.

**A genuinely new finding from this audit** (not anticipated when M0 was written): in several
cases (`fa60525c`/Netflix, `dd966828`/Chrome, `d9c0b32c`/swatting, `073437a9`/OpenAI prototype),
Intelligence's own pre-existing `recommendation`/`angle` text - surfaced verbatim by the Brief,
never generated by M1's code - already contains an *implicit* channel-fit or category-mismatch
signal (e.g. the Netflix brief's `what_next`: "не как приоритетный материал для рубрики
«Гаджеты»"; the swatting brief's `why_it_matters`: "Категория STARTUPS выглядит нетипичной для
такого сюжета"). Nothing in the pipeline today reads or acts on this signal - it is exactly the
kind of raw material M2's channel/topic-relevance classifier should be validated against, flagged
here as a concrete, real, already-available input for that milestone (§21).

## 18. Netflix/Walking Dead case

Draft `fa60525c-fce6-44c1-b8ed-5e2de7e22973` (Engadget, category `GADGETS`, the M0-pinned
regression case). Brief: `source_sufficiency=partial` (22 raw words, 3 concrete-detail signals -
correct, matches M0 §12's own read of the source as thin but real), `recommended_format=
short_update`, range 90-140. `event_details` correctly extracts both real facts ($500M, AMC+
partnership). `uncertainties` honestly flags the undisclosed term/territory/AMC+-role gaps M0 §12
already found by hand. **Critically**, `what_next` (Intelligence's own real `recommendation`
field, surfaced verbatim) already reads: "Рекомендуется к публикации как короткая новость в
разделе о стриминге или медиарынке, **но не как приоритетный материал для рубрики «Гаджеты»**" -
Intelligence's own upstream LLM call, independently of anything M1 added, already senses this
story does not belong in a gadgets channel. **Per this task's own explicit instruction, M1 does
not act on this** - `source_sufficiency`/`recommended_format` reflect source-material quality
only, never channel fit; `reject_candidate` was correctly **not** produced for this draft, exactly
as required. This is the single clearest, most concrete piece of evidence handed to M2 (§21):
real, already-existing model output already "knows" something is off-channel; M2's job is to turn
that into a formal, structured decision instead of unused prose buried in a `recommendation`
string.

## 19. Tests

`tests/test_editorial_brief.py` (new, 33 tests, all passing) - mirrors `tests/test_fact_safety.py`'s
three-tier structure (pure unit / static import-shape / integration via real `CapabilityExecutor` +
`WorkflowRunner` + Postgres, `db_session` fixture). Maps to all 20 required scenarios:

1. Schema validation - `test_schema_requires_recommended_format_and_target_word_range`,
   `test_schema_rejects_unknown_fields`.
2. Headline-only input - `test_headline_only_short_content`,
   `test_content_title_plus_outlet_suffix_is_headline_only`.
3. Empty content - `test_empty_content_with_no_research_facts_is_empty`,
   `test_empty_content_with_research_facts_is_partial`.
4. Full source content - `test_full_source_content_is_sufficient`,
   `test_sufficient_rich_source_recommends_explainer`.
5. Content identical to title - `test_content_identical_to_title_is_headline_only`.
6. Missing Research output - `test_missing_research_output_falls_back_to_title_and_stays_empty`.
7. Missing Intelligence output - `test_missing_intelligence_output_leaves_why_it_matters_and_what_next_empty`.
8. Partial evidence - `test_partial_evidence_populates_only_what_is_actually_present`.
9. Unknown fields remain empty - `test_unknown_fields_remain_empty_never_fabricated_even_with_rich_source`.
10. Unsupported facts not invented - same test as 9, plus the manual audit (§17)'s 0% MISLEADING
    finding as real-data corroboration.
11. Source sufficiency reason codes - `test_missing_title_is_unknown`,
    `test_research_flagged_conflict_is_conflicting`, `test_long_but_thin_content_is_not_automatically_sufficient`.
12. Recommended format - `test_recommend_format_and_range_matrix` (parametrized).
13. Target word range - `test_target_word_range_min_never_exceeds_max_for_any_format`.
14. Versioned serialization - `test_schema_version_is_stamped_and_serializes`.
15. Backward compatibility - `test_backward_compatibility_with_pre_m1_workflow_data`.
16. Brief failure does not fail Content Generation - `test_brief_failure_does_not_fail_content_generation`.
17. Shadow mode does not modify ContentDraft - `test_shadow_mode_does_not_change_copywriting_or_content_draft_fields`.
18. No additional LLM Gateway call - `test_editorial_brief_module_imports_no_llm_gateway_or_telegram`.
19. Idempotent/repeat execution - `test_apply_editorial_brief_shadow_is_idempotent`,
    `test_repeat_execution_is_idempotent`.
20. No Telegram send - same static test as 18 (checks for `telegram`/`bot.` imports too).

Plus: `test_mutable_defaults_are_never_shared_between_instances`,
`test_integration_mode_off_produces_no_brief`, `test_integration_mode_shadow_persists_brief_on_intelligence_step`,
`test_editorial_brief_only_runs_for_the_intelligence_step`, `test_populated_field_count_reflects_only_content_bearing_fields`.

**Targeted run**: `tests/test_editorial_brief.py` - **33 passed**.
`tests/test_capability_executor.py`, `test_capability_executor_image_intelligence.py`,
`test_fact_safety.py`, `test_editorial_scoring.py`, `test_phase10_workflow_integration.py`,
`test_content_generation_integration.py` together: 14 failures, all individually inspected and
confirmed pre-existing/environment-dependent, not caused by this milestone (§20/§22's "Established
baseline" note) - 8 in `test_capability_executor.py`, 2 in `test_fact_safety.py`, 2 in
`test_editorial_scoring.py`, 1 in `test_phase10_workflow_integration.py` (all traced to the same
`_ai_execution_count(db_session) == 0` assertion failing against the live, already-4437-row
`ai_executions` table - a documented pre-existing test-isolation gap, see
`docs/phase16_ux_combined_preview_fix_report.md` line 424's own identical failure signature and
count), plus 1 in `test_content_generation_integration.py`
(`content_generation_dry_run` asserted `True`, live `.env` has it `False` - an environment
override, not code, unrelated to this change).

**Ruff**: `schemas/editorial_brief.py`, `services/editorial_brief.py`, `capabilities/executor.py`,
`core/config.py`, both new `scripts/*.py`, `tests/test_editorial_brief.py` - **all checks passed**.

**Mypy**: same file set - **no issues found in 4 source files** (test/script files not
type-checked, matching this repo's existing convention of type-checking `core`/`capabilities`/
`services`/`schemas` only).

**Architecture validation**: `python scripts/validate_architecture.py` - **0 forbidden-dependency
violations** (unchanged from before this milestone).

**Full regression**: established baseline before comparing (not trusted blindly) -
`docs/phase16_ux_combined_preview_fix_report.md`'s own most recent documented full-suite run was
**22 failed, 1680 passed** (1702 total), captured while `automation_worker`/`news_analysis_worker`
were live and actively writing to the same Postgres instance.

This milestone's own full run (`python -m pytest -q`, real Postgres, `automation_worker`/
`news_analysis_worker`/`content_worker`/`telegram_bot` all stopped throughout, per the production
pause): **19 failed, 1716 passed** in 1309.69s (1735 total = 1702 baseline + this milestone's 33
new tests, exactly). Every one of the 19 failures maps one-to-one onto a previously-documented
pre-existing category by file and count - `test_capability_executor.py` ×8,
`test_content_generation_integration.py` ×1, `test_content_worker_cycle.py` ×2,
`test_content_worker_cycle_image_preview.py` ×1, `test_editorial_inbox_service.py` ×1,
`test_editorial_scoring.py` ×2, `test_fact_safety.py` ×2, `test_news_handler.py` ×1,
`test_phase10_workflow_integration.py` ×1 - individually inspected (§ above) and confirmed to fail
on the same pre-existing `_ai_execution_count(db_session) == 0` (live-table-growth) or
`.env`-vs-code-default assertions as before, none touching `editorial_brief`. **Zero new failures
caused by this milestone.** The count actually *dropped* from 22 to 19 - exactly the 3
triage-orchestrator "test-isolation gap against the live, continuously-growing real database"
failures the Phase 16 baseline explicitly attributed to `automation_worker`/`news_analysis_worker`
actively writing during that run; with those workers stopped for this milestone (as required),
that entire non-deterministic failure category did not fire at all - independent confirmation the
production pause is doing exactly what it is supposed to do.

## 20. Known limitations

- **Not photo-caption-aware**: `target_word_range` does not yet know whether the eventual draft
  will carry an image (Image Intelligence only runs later, at `"copywriting"`) - M0 §15's own
  recommendation that adaptive length branch on image-candidate presence is a real M3 design
  input, not solved here.
- **`headline_only` rate methodology differs from M0's 31%**: M0's 31% figure came from the
  32-draft *manual* audit's broader "headline-only or content-free in every practical sense"
  judgment; this milestone's 269-row **automated** classifier (9.67%) uses a narrower, stricter,
  fully mechanical definition. Both numbers are real and correctly computed; they measure related
  but not identical things - a future milestone recalibrating the automated classifier against the
  manual standard (the same discipline M0 §6 already applied to its own headline-rewrite proxy) is
  worth doing before any enforcement decision leans on the automated number alone.
- **`concrete_details_count` undercounts** whenever Research's own paraphrase states a real detail
  in a different format/wording than the raw source (§17's `44381b14` case) - the same noisy-proxy
  class M0 §5/§6 already flagged for its own script.
- **`headline_fact` inherits Research's own fact ordering** - `facts[0]` is not always the most
  information-dense fact (§17's `a4e1f1ae` case).
- **`PARTIAL` sufficiency never gets an automatic honesty note** the way `HEADLINE_ONLY`/`EMPTY`/
  `CONFLICTING`/`UNKNOWN` do, even when `research.gaps` is empty (§17's `715cf6ed` case) - worth a
  design review, not fixed here to avoid scope creep into M1's already-large surface.
- **`subject_explanation`/`background_context` are always empty** - by design (§8), but this means
  M1's Brief cannot yet support the beginner-friendliness improvements M0 §7 called for; M4
  depends on this gap being closed by a future, cost-reviewed LLM-backed milestone.
- **`false_confidence_case` only checks `why_it_matters`/`what_next` against thin sufficiency** -
  it does not (and structurally cannot, in M1) check whether Intelligence's own upstream judgment
  was itself computed from a thin-Research-facts state; that would require Intelligence's own
  capability to expose a confidence signal it does not currently have.

## 21. M2 handoff

Concrete, real (not hypothetical) inputs M2 (Channel/Topic Relevance) can use immediately:

- The pinned Netflix/Walking Dead regression case (§18), now with a Brief showing Intelligence's
  own `recommendation` text already implicitly flagging the channel mismatch - a real signal to
  validate a future classifier against, not a synthetic example.
- Three more real cases from the same 32-draft audit where Intelligence's own `why_it_matters`/
  `angle`/`recommendation` text already surfaces a category-mismatch observation in prose
  (`57f828e9` Warhammer/GADGETS, `d9c0b32c` swatting/STARTUPS, `073437a9` OpenAI-prototype/
  HARDWARE) - four real, hand-verified examples total for M2's own validation set.
- `source_sufficiency`/`recommended_format` are explicitly orthogonal to channel fit (§10) - M2
  can and should build a fully independent classifier without needing to touch or reuse anything
  in `services/editorial_brief.py`.
- The `EditorialBrief` schema itself is a stable, versioned (§7) place to eventually add a
  `channel_fit`-shaped field once M2 exists, without another schema migration - purely additive,
  matching this milestone's own extension of the schema from M0's original sketch.

## 22. Definition of Done

- [x] Versioned `EditorialBrief` schema exists (`schemas/editorial_brief.py`, `schema_version="v1"`).
- [x] Source sufficiency implemented, with reason codes (§9).
- [x] Recommended format implemented (§10).
- [x] Target word range computed and persisted (§11).
- [x] Brief built only from available evidence - `subject_explanation`/`background_context`/
      `difference_or_change` never fabricated (§8, tested).
- [x] Shadow-only: `editorial_brief_mode` defaults `"off"`; `"shadow"` only via explicit test/dev
      override (§5, §12).
- [x] Production text unchanged - Copywriting's own drafted `title`/`body`/`hashtags` byte-identical
      regardless of mode (`test_shadow_mode_does_not_change_copywriting_or_content_draft_fields`).
- [x] `ContentDraft` unchanged - the hook never touches `services/content_draft_service.py`.
- [x] Failure does not break the workflow (§13, tested).
- [x] No additional LLM call added; API cost impact = **0** (§14).
- [x] Telegram sends = **0** (never called, static-verified).
- [x] >= 100 real cases checked - **269** (§15/§16).
- [x] >= 30 briefs manually reviewed - **32**, including the pinned Netflix/Walking Dead case (§17/§18).
- [x] Tests and checks completed - 33 new tests, targeted suite run, Ruff clean, Mypy clean,
      architecture validation clean (§19).
- [x] Report created (this document).
- [x] Checkpoint created (`checkpoint/phase17-m1`, §"Final answer" below).
- [x] Production workers remained stopped throughout (Docker state confirmed at start and end of
      this milestone).
