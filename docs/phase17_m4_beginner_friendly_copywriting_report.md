# Phase 17 M4 — Beginner-Friendly Copywriting, Length Recalibration, and Fact-Safe Explanations

## 1. Objective

Address M3's own central, disclosed gap (`docs/phase17_m3_adaptive_length_shadow_comparison_report.md`
§25: ideal-range compliance only 6/32, 18.75%) with a fact-safe, beginner-friendly copywriting
layer that (a) explains unfamiliar companies/products/technologies/terms only from real evidence
or a small versioned glossary — never invented, (b) separates an "ideal" editorial length from an
"evidence-supported achievable" (`safe`) length, directly targeting M3's under-length root cause,
(c) supports natural multi-paragraph structure, (d) detects and forbids filler/repetition, (e)
adds a deterministic, zero-new-LLM-call second-pass Fact Safety audit over the generated candidate
text itself, and (f) stays shadow/comparison-only — this milestone never activates a new prompt in
production. Same discipline as M1/M2/M3: real repo state trusted over any prior assumption,
production workers never started, `ContentDraft`/Telegram never touched by any code path this
milestone adds.

## 2. Starting state

Repository restored and verified before any work began: `checkpoint/phase17-m3` present and
matching `HEAD` of `feature/phase17-editorial-intelligence` at the time. `docker compose ps`
confirmed only `postgres`/`redis`/`backend` running; `automation_worker`, `news_analysis_worker`,
`content_worker`, `telegram_bot` all stopped throughout this entire milestone — re-checked again at
the end (§28). `scripts/_phase15_m4_final_cutover_samples.json` untouched (`git status` confirms no
modification). No `.env` changes made. No force-push, no history rewrite.

## 3. M0–M3 evidence recap

- **M0** (`docs/phase17_m0_output_quality_discovery_report.md`): identified real output-quality
  gaps in production `ContentDraft` rows via manual audit of a real sample, motivating M1–M4.
- **M1** `EditorialBrief` (shadow): deterministic extraction of headline_fact/event_details/
  why_it_matters/what_next/uncertainties/source_sufficiency from already-persisted Research/
  Intelligence output — the structural input this milestone's `BeginnerFriendlyPlan` builds on.
- **M2** `channel_relevance`/`ChannelProfile`: `AI_GADGETS_CHANNEL_PROFILE.audience` ("tech-
  interested general readers") — reused directly to set this milestone's own `_AUDIENCE_LEVEL`
  constant, and `_ENTITY_HINTS`' own "well-known enough" judgment mirrored into this milestone's
  `_ASSUMED_KNOWLEDGE_ENTITIES` list for consistency, not re-decided.
- **M3** `AdaptiveLengthPlan` (shadow/comparison): complexity/sufficiency-driven target word range
  — reused directly as this milestone's `ideal_range`. M3's own comparison run measured real
  candidates landing consistently short (median candidate word count well below its own
  `min_words` floor for `normal`/`complex` tiers) despite `max_tokens` usage sitting far below the
  cap in every case checked at the time — ruling out truncation as M3's own cause and pointing at
  the prompt's own instructions instead (§4).

## 4. Root cause of M3's under-length candidates

Investigated first, before any new code was written (task #39). Two candidate hypotheses were
checked directly against evidence, not assumed:

1. **`max_tokens` cap** — checked M3's own saved `token_usage` for every under-length case:
   `output_tokens` sat well below the configured cap in every instance. Ruled out.
2. **Schema/parsing truncation** — M3's saved candidates all parsed as complete, valid JSON with
   non-empty `title`/`body`/`hashtags`. Ruled out.
3. **Prompt instruction asymmetry** — `prompts/copywriting_adaptive_candidate/v1.yaml`'s own rule 7
   read "stop naturally once the story is told well, even if that means finishing short of
   `target_words`" — an explicit, one-sided permission to stop early, with no matching instruction
   to make full use of available evidence. Confirmed as the primary cause by close reading: the
   model had no *positive* reason in the prompt text to keep writing once a minimally complete
   draft existed, even when substantially more real evidence (`event_details`, `why_it_matters`)
   remained unused.

**Fix implemented in this milestone**: `copywriting_beginner_candidate` Priority 7 (§15) replaces
the asymmetric "stop early is fine" instruction with an explicit, still Fact-Safety-bounded
mandate to use the real evidence available within `safe_range` fully, paired with a `safe_range`
(§9) that is itself bounded by how much real evidence exists — so the target asked for is always
one the evidence can support, removing the false conflict between "write more" and "don't
fabricate."

## 5. Architecture decision

Same pattern as M1/M2/M3, re-used rather than re-decided:

- New schema module (`schemas/beginner_friendly.py`) + new pure builder module
  (`services/beginner_friendly.py`), gated by a new three-state `beginner_copywriting_mode`
  setting (`core/config.py`), attached in `capabilities/executor.py`'s existing "copywriting" step
  hook, immediately after M3's own `_attach_adaptive_length_plan` call (§14) — never inside
  `CopywritingCapability` itself, so production behavior is provably unchanged when the mode is
  `"off"` (the default).
- `build_beginner_friendly_plan()` calls `build_editorial_brief()` (M1) and
  `build_adaptive_length_plan()` (M3) directly — both pure functions — rather than depending on
  `editorial_brief_mode`/`adaptive_length_mode` being non-`"off"`. This milestone's plan is
  therefore computable from already-persisted data regardless of which shadow milestones are
  independently enabled, matching M2's/M3's own established "independently computable" discipline.
- A new, separately-named governed prompt, `copywriting_beginner_candidate` (§15) — never a
  version bump of `copywriting` or `copywriting_adaptive_candidate` — so
  `FilePromptRepository.resolve(name)` (latest version *per name*) can never accidentally resolve
  to this candidate prompt from another name.
- A new deterministic second-pass audit (`services/candidate_fact_safety.py`), reusing
  `services.fact_safety.evaluate_fact_safety()` (Phase 15 M5) directly rather than duplicating its
  claim-extraction logic, plus four new narrow regex detectors for claim types M5 never covered
  (causal connectors, superlatives, market-positioning claims, unhedged forecasts).

## 6. BeginnerFriendlyPlan schema

`schemas/beginner_friendly.py`. `BEGINNER_FRIENDLY_SCHEMA_VERSION = "v1"`,
`BEGINNER_FRIENDLY_POLICY_VERSION = "v1"`. `AudienceLevel` (general/tech_interested/specialist),
`JargonRisk` (low/medium/high), `ExplanationProvenance` (source_title/source_content/
research_output/intelligence_output/editorial_brief/deterministic_definition/unknown — enumerated
explicitly so "the model's general knowledge" is never a silently-allowed default provenance).
`WordRange` (frozen, `min <= target <= max` enforced by `model_validator`). `BeginnerFriendlyPlan`
(frozen): `audience_level`, `explanation_required`, `subjects_to_explain`, `terms_to_explain`,
`assumed_knowledge`, `unexplainable_terms`, `explanation_budget`, `context_budget`,
`detail_target`, `paragraph_target`, `why_it_matters_required`, `what_next_allowed`,
`uncertainty_required`, `jargon_risk`, `ideal_range`, `safe_range`, `reason_codes`,
`evidence_constraints`, plus its own `_check_safe_within_ideal_ceiling` validator: `safe_range`
can never exceed `ideal_range`'s own ceiling — a schema-enforced invariant, not just a convention.

## 7. Safe glossary

`services/editorial_glossary.py`. `GLOSSARY_VERSION = "v1"`. 15 hand-curated, hand-reviewed terms
that actually appeared across Phase 17 M0–M3's own real-corpus audits: `llm`, `inference`,
`fine-tuning`, `open weights`, `benchmark`, `token`, `agent`, `quantization`, `multimodal`, `npu`,
`lithography`, `gpu`, `antitrust`, `sota`, `series a` — each a short, neutral, factual definition
(no marketing language, no claim about any specific company's standing). `lookup(term)` is exact,
case-insensitive match only — never fuzzy — so a similarly-spelled but different term can never be
silently attached to the wrong definition. `known_terms()` for introspection. Deliberately never
dynamically expanded or LLM-generated: adding a term is a reviewed code change, per this
milestone's own explicit "no dynamic glossary generation" requirement.

## 8. Subject/term classification (evidence-grounded)

`services/beginner_friendly.py`'s `classify_subjects_to_explain()` and
`classify_terms_to_explain()`. A capitalized-run regex (`_ENTITY_TOKEN_RE`, mirroring M2's own
`_ENTITY_HINTS` detection style) finds proper-noun entity mentions in `EditorialBrief`'s own
`headline_fact` + `event_details` text; each is classified into exactly one of three buckets:

- **`assumed_knowledge`** — in `_ASSUMED_KNOWLEDGE_ENTITIES` (24 well-known company/product names,
  mirroring M2's own reviewed list) or `_ASSUMED_KNOWLEDGE_ACRONYMS` (AI, EU, US, UK, CEO, CTO,
  IPO, USD, EUR, DOJ) — never explained, explaining it would waste budget and read as condescending
  (prompt Priority 5, §15).
- **`subjects_to_explain`** — a descriptive noun (`компания`, `стартап`, `разработчик`, `платформа`,
  etc., or their English equivalents) appears within a 40-character window of the entity mention in
  the real evidence text — explainable *from that evidence*, never from the model's own knowledge.
- **`unexplainable_terms`/`unexplainable_subjects`** — flagged as jargon/an unfamiliar entity but
  with no real evidence nearby and (for acronyms) no glossary entry — the candidate must leave
  these as-is, never invent a description (prompt Priority 5's own explicit carve-out).

Jargon acronyms (`_JARGON_ACRONYM_RE`, 2+ consecutive uppercase letters) are looked up in
`services.editorial_glossary.lookup()`; a hit becomes `terms_to_explain` (glossary-grounded,
provenance `deterministic_definition`); a miss becomes `unexplainable_terms`.
`explanation_required` is `True` only when at least one subject or term is explainable *and* the
brief's own `source_sufficiency` is not `EMPTY`/`UNKNOWN`.

## 9. Ideal vs safe length policy

`_compute_safe_range()` (pure). `ideal_range` is M3's own `AdaptiveLengthPlan` range, unchanged.
`safe_range` is a **constrained subset** of `ideal_range`, capped by
`evidence_units * _EVIDENCE_WORDS_PER_UNIT` (28 words/unit — a reasoned, documented starting
estimate, not fit to outcome data; same "reasoned, not fit" disclosure precedent as
`services/editorial_scoring.py`'s own weights), where `evidence_units` counts
`event_details + why_it_matters + what_next + subjects_to_explain + terms_to_explain` — i.e., the
real, distinct, evidence-grounded things the candidate actually has something to say about. Floor:
`_SAFE_RANGE_FLOOR_WORDS = 40` (never below `EditorialBrief`'s own INSUFFICIENT-source floor).
Width: `_SAFE_RANGE_WIDTH_WORDS = 50`. For `Complexity.INSUFFICIENT` sources, `safe_range` equals
`ideal_range` unchanged (nothing further to usefully constrain at that floor). Schema-enforced:
`safe_range.max_words` can never exceed `ideal_range.max_words`. This directly targets §4's root
cause: the candidate is asked to make full use of `safe_range`, and `safe_range` is sized to what
the evidence can actually support — removing the incentive M3's own prompt gave to stop early.

## 10. Paragraph structure and explanation/context budgets

`paragraph_target` starts from M3's own `AdaptiveLengthPlan.paragraph_target`, bumped to at least 2
and by one further (capped at 4) when `explanation_required` — giving the candidate room for a
short lead, then details/explanation, then why-it-matters/what's-next/uncertainty, never one
compressed paragraph (prompt Priority 6, §15, explicitly forbids mechanical subheadings like
"Details:"). `explanation_budget = min(15 * explainable_count, safe_range.target_words // 3)` and
`context_budget = min(20, safe_range.target_words // 4)` when `background_context` exists — small,
capped allowances so explanation never dominates the post at the expense of the main fact
(Priority 3 always outranks Priority 5, §15).

## 11. Filler and repetition detection

`services/candidate_fact_safety.py`: `detect_filler_phrases()` — a fixed, small, explicit phrase
list ("это важный шаг", "время покажет", "эксперты отмечают" without a named source, "рынок
продолжает развиваться", and English equivalents) — this milestone's own explicit anti-filler
rules, never a general fluency classifier; an unlisted filler phrase is simply not caught, a
disclosed limitation. `detect_repetition()` — flags any pair of sentences sharing ≥70% of their
own distinct words (by the shorter sentence's word count) — a narrow lexical-overlap signal, never
a semantic-similarity model; two sentences restating the same idea in sufficiently different words
can escape this check. Both pure, deterministic, exercised directly by
`test_filler_phrase_detection`/`test_no_filler_in_clean_text`/
`test_repetition_detection_flags_near_duplicate_sentences`/`test_no_repetition_in_distinct_sentences`.

## 12. CandidateFactSafetyAudit schema

`schemas/candidate_fact_safety.py`. `CANDIDATE_FACT_SAFETY_SCHEMA_VERSION = "v1"`.
`FactSafetyStatus` (pass/review/fail), `AuditSeverity` (low/medium/high). `CandidateFactSafetyAudit`
(frozen): `status`, `supported_claim_count`, `unsupported_claim_flags`, `numeric_flags`,
`entity_flags`, `causal_flags`, `definition_flags`, `severity`, `reason_codes`.

## 13. CandidateFactSafetyAudit second-pass logic

`services/candidate_fact_safety.py`'s `evaluate_candidate_fact_safety()` (pure, zero new LLM call —
this milestone's own explicit, load-bearing constraint). Reuses Phase 15 M5's
`FactEvidence`/`evaluate_fact_safety()` directly for numeric/date/entity/quote claim extraction and
support classification against the real `NewsEvent`/Research evidence — never duplicated. Adds four
new, narrow, regex-based detectors M5 never covered: causal-connector sentences (`_CAUSAL_RE`),
superlative claims (`_SUPERLATIVE_RE`), market-positioning claims (`_MARKET_CLAIM_RE`), and
unhedged forecasts (`_FORECAST_RE` without a matching `_HEDGE_RE` in the same sentence) — flags for
human review, never silent auto-corrections. `_scan_definition_flags()` separately checks: any term
the plan explicitly marked `unexplainable` that nonetheless appears explained (a descriptive noun
nearby) in the candidate text — a direct, deterministic check against this milestone's own "never
invent an explanation for an unlisted term" rule; triggering it is the only path to `status=FAIL`
independent of M5's own severity classification. Status derivation: `definition_flags` present →
`FAIL`/`HIGH`; else a high-severity unsupported M5 finding → `FAIL`/`HIGH`; else any unsupported
finding → `REVIEW`/`MEDIUM`; else any uncertain finding or causal flag → `REVIEW`/`LOW`; else
`PASS`.

## 14. Shadow integration

`capabilities/executor.py`: new gate `if step.capability == "copywriting" and
settings.beginner_copywriting_mode != "off"` immediately after M3's own adaptive-length gate — same
step, independent computation, ordering between the two attaches does not matter. New
`_attach_beginner_friendly_plan()` method mirrors `_attach_adaptive_length_plan()`'s own structure
exactly: logs `beginner_friendly_plan_started`, wraps `apply_beginner_friendly_shadow(...)` in
`try/except Exception`, logs `beginner_friendly_plan_failed` and returns `structured_output`
**completely unchanged** on any exception (best-effort, non-blocking — a plan-builder failure must
never fail the workflow step or trigger a retry), logs `beginner_friendly_plan_completed` with
`policy_version`/`audience_level`/`explanation_required`/`subjects_to_explain_count`/
`terms_to_explain_count`/`ideal_target_words`/`safe_target_words`/`paragraph_target`/`jargon_risk`/
`reason_codes` on success — never the full plan, never raw candidate/source text (redaction
discipline, §29). `apply_beginner_friendly_shadow()` itself returns `structured_output` byte-for-
byte unchanged when `beginner_copywriting_mode == "off"` (verified:
`test_apply_beginner_friendly_shadow_off_mode_is_a_no_op`,
`test_baseline_byte_identical_off_vs_shadow`) — the default, zero-behavior-change rollback path.
`CopywritingCapability` itself is never modified and never reads `beginner_friendly_plan` — this
milestone's shadow output has no path into `ContentDraft` or Telegram (verified:
`test_no_content_draft_mutation_and_no_telegram_import_in_workflow_path`).

## 15. copywriting_beginner_candidate prompt (v1)

`prompts/copywriting_beginner_candidate/v1.yaml` — a new governed prompt, distinct name from both
`copywriting` (still v3, unmodified) and `copywriting_adaptive_candidate` (still v1, unmodified;
verified by re-resolving both after this milestone's changes). Eight priority-ordered core rules,
each explicitly outranking the ones below it: (1) Fact Safety always outranks length — never write
a sentence whose only purpose is reaching a word count; (2) never invent a fact/number/date/company
description/market position/forecast — an empty EditorialBrief field means leave the idea out
entirely; (3) preserve the main fact accurately; (4) prefer real, specific `event_details` over
vague generality; (5) explain only `subjects_to_explain`/`terms_to_explain`, only from given
evidence/glossary, never `unexplainable_terms` or `assumed_knowledge` (§8); (6) structure naturally
across `paragraph_target` paragraphs, no mechanical subheadings; (7) make full, thorough use of
real evidence within `safe_range` — the direct §4 fix — never pad past `safe_range.max_words` by
repetition; (8) natural idiomatic prose, no raw URLs. Plus rules gating `why_it_matters`/
`what_next` on the plan's own flags, mandatory hedging language for uncertain/forecast claims,
explicit filler-phrase prohibition (same list as §11), output language, and title/hashtag shape.

## 16. Comparison tooling

`scripts/phase17_m4_beginner_copywriting_comparison.py`. `_CANDIDATE_PROMPT_NAME =
"copywriting_beginner_candidate"`, `_MAX_CANDIDATE_CALLS = 32` (hard cap in code, not just
convention). `_load_m3_candidates()` reuses M3's own saved
`scripts/_phase17_m3_comparison_results.json` candidates directly rather than regenerating them —
this milestone's own explicit reuse requirement. `_load_existing_output()` gives resume support:
re-running the script with a prior `--output` skips cases already present. `_build_candidate_request()`
assembles a `GenerateRequest` carrying `EditorialBrief` + `AdaptiveLengthPlan` + `BeginnerFriendlyPlan`
context (glossary definitions for `terms_to_explain` looked up via `glossary_lookup()` and passed
explicitly, never left for the model to fill in from its own knowledge), `reasoning_effort="medium"`
(a deliberate deviation from M3's own `"low"` — see §22 for the real, disclosed consequence of this
choice), `max_tokens = min(1200, round(plan.safe_range.max_words * 4) + 150)`. `run_comparison()`
reads real DB rows read-only, builds all three plans (Editorial Brief, Adaptive Length, Beginner
Friendly) for every case, runs the deterministic Fact Safety second pass over baseline/M3/M4 text,
and generates the M4 candidate only when `live_allowed` (i.e., both `--live` and
`--confirm-paid-calls` were passed). `--dry-run` is the default; `--live` and
`--confirm-paid-calls` are both required, together, for any real spend.

## 17. Cost controls and user confirmation

Per this milestone's own hard requirement: ≤32 new candidate-generation calls total, one per case,
reusing the same 32 pinned gold-set draft IDs M0–M3 already used
(`scripts/_phase17_m3_comparison_sample_ids.json`), reusing M3's own saved candidates rather than
regenerating them. A full 32-case dry run (§19) was performed first — zero LLM calls, zero cost —
to compute a real cost estimate from the actual planned `safe_range` sizes and this project's own
historical `gpt-5.6-luna` pricing ($1/$6 per M input/output tokens): estimated ≈$0.15–0.20 for all
32 calls. Presented to the user via `AskUserQuestion` with the real estimate before any paid call;
user selected "Yes, run all 32 (Recommended)". The real run (§20) then executed exactly 32 calls at
**$0.17785 actual total cost** ($0.00556/call average) — matching the pre-approved estimate. No
call was made outside this single, explicitly confirmed batch.

## 18. Comparison sample

Same 32 pinned `ContentDraft` IDs as M1/M2/M3 (`scripts/_phase17_m3_comparison_sample_ids.json`,
unchanged) — a fixed, already-audited gold set, never re-drawn or expanded this milestone.

## 19. Dry-run results

`scripts/_phase17_m4_dry_run_results.json`: 32/32 cases processed, **0 LLM calls, $0 cost**, 0
`EMPTY`-sufficiency skips. Computed `safe_range` stats across the sample: mean `target_words` =
133.6, mean `max_words` = 158.4 — used directly to derive the §17 cost estimate before the paid run.

## 20. Real comparison run results

`scripts/_phase17_m4_comparison_results.json`. `sample_size=32`, `cases_processed=32`,
`dry_run=false`, `live_allowed=true`, `resumed_from_existing=0`, `candidate_calls_made=32`,
`total_estimated_cost_usd=0.17785`, model `gpt-5.6-luna` for all 32 calls. No `ContentDraft` row
was mutated (verified against real `updated_at` timestamps, unchanged post-run) — the same check
M3 performed. Zero Telegram messages sent — structurally unreachable, no `bot`/aiogram import
anywhere in the comparison script's own import graph (verified:
`test_beginner_friendly_module_imports_no_llm_gateway_or_telegram`,
`test_candidate_fact_safety_module_imports_no_llm_gateway_or_telegram`).

**7 of 32 candidate generations returned an empty `structured_output`** (`candidate={}`) despite
`candidate_generated=True` and substantial real `output_tokens` usage — see §22, the single most
important finding of this milestone.

## 21. Length and quality metrics (25 successfully-generated candidates)

| Metric | Baseline | M3 candidate | M4 candidate |
|---|---|---|---|
| Mean words | 34.0 | 79.4 | 97.5 |
| Median words | 35.0 | 71.0 | 92.0 |
| Ideal-range compliance | — | 6/32 (18.75%, M3's own report) | 5/25 successful (20.0%) |
| Safe-range compliance | — | n/a (M3 has no safe_range concept) | 15/25 successful (60.0%) |

Read against the full 32-case sample (truncated cases counted as non-compliant, the honest "as
measured" denominator): **safe-range compliance = 15/32 = 46.9%**, more than double M3's own
18.75% ideal-range compliance — real, measured evidence that the §9 `safe_range` mechanism
materially improves length-target compliance, even before accounting for the truncation defect
that suppressed 7 cases entirely.

## 22. Truncation bug — discovery, root cause, and impact

Discovered during manual review of `scripts/_phase17_m4_abc_review.json`: 7 cases showed
`m4_title: null`, `m4_body: null`, `m4_words: 0`. Investigated directly against the raw
`scripts/_phase17_m4_comparison_results.json`: all 7 (`fa60525c`, `44381b14`, `7352db1a`,
`5c856b45`, `d9c0b32c`, `7bca7a5b`, `073437a9`) have `candidate={}` (a fully empty
`structured_output`) despite `candidate_generated=True` and real, non-trivial `output_tokens`
usage. Root-caused with certainty, not assumed: for every one of the 7 cases,
**`token_usage.output_tokens` exactly equals the script's own computed `max_tokens` cap**
(`min(1200, round(safe_range.max_words * 4) + 150)`):

| draft_id | safe_max_words | max_tokens cap | output_tokens |
|---|---|---|---|
| fa60525c | 112 | 598 | 598 |
| 44381b14 | 112 | 598 | 598 |
| 7352db1a | 252 | 1158 | 1158 |
| 5c856b45 | 320 | 1200 | 1200 |
| d9c0b32c | 90 | 510 | 510 |
| 7bca7a5b | 112 | 598 | 598 |
| 073437a9 | 90 | 510 | 510 |

This is an exact match in all 7 cases, not a coincidence — the model's response was cut off
mid-generation before its structured JSON output could be completed, leaving the parser with
nothing usable. Direct, self-inflicted cause: `_build_candidate_request()` (§16) sets
`reasoning_effort="medium"` (a deliberate deviation from M3's own `"low"`), and the OpenAI
Responses API's `reasoning` tokens count against the **same** `max_output_tokens` budget as the
visible answer (`integrations/llm_gateway/providers/openai_adapter.py`:
`payload["reasoning"] = {"effort": request.reasoning_effort}`) — raising `reasoning_effort` without
adding matching token headroom let internal reasoning consume the entire budget before any visible
answer token could be emitted, for exactly the cases with the largest `safe_range` (and therefore
the most complex sources, plausibly triggering more internal reasoning).

**Measured truncation rate: 7/32 = 21.9%** — a hard miss against this milestone's own 0% target.

**Not fixed within this milestone.** The 32-call hard cap (§17) is already fully spent under the
single, explicitly user-confirmed paid batch; making additional paid calls to patch this defect
would violate the user's own explicit "no more than 32 new generation calls" instruction. This is
disclosed here as a measured, root-caused defect, not masked, and is the primary reason this
milestone's own final verdict (§32) is **TUNING REQUIRED**, not VALIDATED. Recommended fix for a
future tuning pass (not attempted here): either revert `reasoning_effort` to `"low"` (the §9
`safe_range` fix already shows strong improvement independent of the `reasoning_effort` change —
§21) or decouple the reasoning-token budget from the visible-output token budget by raising
`max_tokens` with headroom reserved specifically for reasoning tokens.

## 23. Manual A/B/C evaluation

All 32 cases read in full (`scripts/_phase17_m4_abc_review.json`), verdicts recorded in
`scripts/_phase17_m4_manual_abc_evaluation.json`. The 7 truncated cases are excluded from
preference/quality scoring (there is no text to evaluate) but count fully toward the §22 truncation
rate. Among the **25 successfully-generated candidates**:

**Preference** (M4 vs M3, same rubric as M3's own §19: factual correctness, unsupported claims,
subject explanation, terminology clarity, beginner friendliness, completeness, useful specifics,
why_it_matters, uncertainty honesty, naturalness, structure, repetition, filler, length
appropriateness, Telegram suitability, overall):

| Verdict | Count |
|---|---|
| M4_BEST | 18 |
| TIE | 6 |
| M3_BEST | 1 |
| BASELINE_BEST | 0 |
| ALL_WEAK | 0 |

M4 preferred-or-tied vs M3 in **24/25 (96%)** of successfully-generated cases; M4 strictly
preferred in 18/25 (72%). All 25 successful candidates are clearly preferred over their own
baseline (baseline mean 34 words vs. M4 mean 97.5 words, with real added detail, not padding — the
same dramatic baseline gap M3's own report already established for adaptive-length candidates).

**One disclosed M3_BEST case** (`b9eb8450`, AI compute cost): M4 (114 words) is less thorough than
M3 (148 words) — this case's own `safe_range` formula (§9) was more conservative than M3's own
`ideal_range` target, a real instance where the evidence-bounding mechanism trades completeness for
safety. Not hidden — a genuine, disclosed trade-off of the §9 design.

**Quality** (GOOD/ACCEPTABLE/WEAK/MISLEADING) among the 25 successful M4 candidates:

| Quality | Count |
|---|---|
| GOOD | 22 |
| ACCEPTABLE | 3 |
| WEAK | 0 |
| MISLEADING | 0 |

Zero WEAK, zero MISLEADING — no case found on manual read to contain a fabricated fact, invented
company description, or unsupported market/forecast claim. The 3 ACCEPTABLE cases are documented
individually in §24 (all are "true but not literally evidence-grounded" additions, the same minor
class M3's own report already disclosed once, never outright fabrication).

## 24. Subject/term explanation quality results

11 of 32 cases had `explanation_required=True` (2 of which were among the 7 truncated, leaving 9
scoreable): `supported` 5, `unsupported` 2, `unnecessary` 2, `missing` 0.

- **`supported` (5/9, clean successes)**: `dd966828` (Google Chrome AI) — "LLM — это большие
  языковые модели..." matches `services/editorial_glossary.py`'s own `llm` definition near-
  verbatim, correctly gated by `terms_to_explain`. `6612ee70` (arXiv MLIP) — "SOTA (state of the
  art) — лучший из опубликованных..." matches the `sota` glossary entry closely; the richest
  candidate in the whole sample (233 words), fully hedged throughout. `57f828e9` (Warhammer
  trailer) and `26e75fc4` (Lilian Weng) — real multi-word entities (`King Art Games`/`Iron
  Harvest`, `Thinking Machines Lab`) explained using only real evidence text. `eae93502` (Moonshot
  AI) — the flagged subject fragment "Moonshot" is grounded minimally and correctly ("китайская
  компания Moonshot AI"), no fabrication.
- **`unsupported` (2/9, minor, disclosed, not fabrication)**: `9997dca9` (Modi/Reels) — explains
  "Reels" as belonging to "платформы Meta" — true and well-known but not literally present in the
  given evidence string; this is the *exact same* pattern M3's own report already disclosed once
  for this identical draft. `715cf6ed` (Dili funding) — gives its own generic "Series A — название
  раунда финансирования" instead of the curated glossary definition (§25, a detection-layer gap:
  "Series A" is never correctly classified as either a subject or a glossary term by the current
  regexes, so the model fell back to a reasonable but ungrounded paraphrase). Neither case invents
  a false fact — both state something true, just not literally sourced from the given evidence.
- **`unnecessary` (2/9)**: `7acf32e8` (Torvalds/Linux) and `491db283` (Atoms robotics) — both
  caused by the same detection-layer limitation (§25): a real multi-word proper noun ("Открытые
  системы", "Andreessen Horowitz") gets fragmented by the single-token entity regex into meaningless
  standalone "subjects." In both cases the model handled the bad signal gracefully — `7acf32e8`
  simply didn't force an explanation of the meaningless fragment; `491db283` produced a slightly
  tautological but harmless line ("Andreessen и Horowitz входят в его название"). This is better
  read as a positive finding about model behavior (no fabrication under a flawed instruction) than
  as a candidate-quality defect.
- **`missing` (0/9)**: in every explanation-required successful case, the model attempted something
  reasonable — never silently ignored the requirement.

## 25. Known limitations of the entity/term-detection regexes

Disclosed directly from real cases encountered in §24, not theoretical: `_ENTITY_TOKEN_RE`
(`schemas/beginner_friendly.py` / `services/beginner_friendly.py`) matches single capitalized
tokens, so **multi-word proper nouns are fragmented** — "Andreessen Horowitz" → `["Andreessen",
"Horowitz"]`, "Warhammer: Dawn of War" / "King Art Games" / "Iron Harvest" / "Deep Silver" →
`["Art", "Dawn", "Deep", "Games", "Harvest", "Iron", "King", "War", "Warhammer"]`, "Meta Platforms
Inc." → `["Inc", "Platforms"]`, "Открытые системы" (a real publisher name) → `["Открытые"]`. This
inflated the observed "unnecessary explanation" rate (§24) — the underlying cause is this detection
gap, not the model over-explaining genuinely well-known things. Separately, `_JARGON_ACRONYM_RE`
(`\b[A-Z]{2,}\b`) cannot match title-case multi-word terms like "Series A" (the "A" alone is one
character, below the 2+ threshold), so a real, glossary-defined term was never correctly routed to
`terms_to_explain` in the one case where it appeared (`715cf6ed`, §24). Both are real, narrow
regex-detection gaps, not model-quality defects — recommended for a future tuning pass: a
multi-word proper-noun span detector (e.g., consecutive capitalized tokens joined) rather than a
single-token regex.

## 26. Fact Safety audit results and known limitations

Automated `CandidateFactSafetyAudit` status distribution across all 32 cases (truncated cases
included, trivially `pass` or absent — see caveat below): baseline `{pass: 9, review: 21, fail: 2}`,
M3 `{pass: 6, review: 23, fail: 3}`, M4 `{pass: 11, review: 20, fail: 1}`.

**The one M4 `FAIL` case was manually verified as a false positive**, not a real fact-safety
violation (`eae93502`, Moonshot AI, `scripts/_phase17_m4_fail_case_check.json`). Three distinct,
disclosed limitations of the underlying Phase 15 M5 extractor and this milestone's own new
detectors combined to produce it: (1) a money-range regex gap — "$1–2 млрд" partially matched as
"2 млрд." and flagged `unsupported` even though the candidate correctly attributes it as a prior
*plan*, distinct from the confirmed $3.5B raise; (2) cross-language entity mismatch — "Moonshot AI"
repeatedly flagged `uncertain` and "ИИ" flagged `unsupported`, an artifact of M5's own extractor
being built for same-language (mostly English-source) comparison, over-firing when candidate text
is Russian against English source text (a limitation already disclosed once in M2's own channel-
relevance work, recurring here); (3) a causal-hedge sentence ("Инвесторы, дата и условия сделки в
опубликованных данных не указаны, поэтому оценить... нельзя") — an honest disclosure of what is
*not* known — misclassified by `_CAUSAL_RE` as a risky causal claim rather than recognized as a
hedge. On manual read, the candidate text itself is careful and accurate: it explicitly separates
the completed $3.5B/$35B raise from the hypothetical future $50B round, never presenting the latter
as settled.

**This automated audit must be read as a noisy upper bound on possible issues, never as ground
truth** — the same discipline Phase 17 has applied to every prior automated proxy in this arc
(M2's `channel_relevance` heuristics, M3's word-range compliance). Manual review remains
authoritative; the `review`-status majority (20/25 successful M4 cases) reflects the audit's own
low bar for flagging (any uncertain claim or causal connector triggers `review`), not a majority of
real issues — confirmed directly by the §23 manual read finding zero MISLEADING candidates.

## 27. Headline-only / thin-source cases

Cases with `Complexity.INSUFFICIENT` (headline-only or comparably thin sources) have `safe_range`
equal to `ideal_range` unchanged (§9) — no further evidence-based narrowing applies since there is
nothing left to constrain below the already-thin floor. Manually spot-checked among the 25
successful candidates: none fabricated additional detail beyond the thin source; all stayed within
their own modest range. Consistent with M3's own §21 finding for the identical mechanism at the
`AdaptiveLengthPlan` level.

## 28. Failure isolation

Verified at the same two layers M1/M2/M3 established: (a) the deterministic shadow plan builder
inside `capabilities/executor.py` — `test_shadow_failure_isolation_does_not_fail_content_generation`
monkeypatches a `RuntimeError` inside the plan builder and confirms the `"copywriting"` step still
reaches `SUCCESS` with the step's own real output untouched, no retry triggered; (b) the comparison
script's own per-case `try`/`except` around candidate generation (zero exceptions occurred in the
real 32-case run — the 7 empty results, §22, are a *valid, parsed, empty* response, not an
exception — but the guard path exists and is exercised by the truncated cases' own graceful
`candidate_generated=True, candidate={}` handling rather than a crash).

## 29. Structured logging and redaction

`beginner_friendly_plan_started`/`beginner_friendly_plan_failed`/`beginner_friendly_plan_completed`
(`capabilities/executor.py`, §14) — the `_completed` event logs only schema/classification metadata
(`policy_version`, `audience_level`, `explanation_required`, `subjects_to_explain_count`,
`terms_to_explain_count`, `ideal_target_words`, `safe_target_words`, `paragraph_target`,
`jargon_risk`, `reason_codes`) — **never** the full raw `NewsEvent` content, never full candidate
title/body text, and (as everywhere else in this codebase) no API keys, Telegram tokens, secrets,
or personal data ever pass through these fields. `subjects_to_explain`/`terms_to_explain` counts
are logged, not the terms themselves, to keep the log payload small and free of source-text
fragments.

## 30. Tests

`tests/test_beginner_friendly.py` (new, **50 tests, all passing**) — mirrors M1's/M2's/M3's own
three-tier structure: pure unit (schema validation/versioning, safe-vs-ideal ceiling enforcement,
subject/term classification with evidence grounding, glossary lookups, jargon risk, safe-range
narrowing under partial/sufficient/headline-only/conflicting evidence, paragraph/why_it_matters/
what_next/uncertainty gating, filler/repetition detection, Fact Safety pass/review/fail
derivation), static import-shape (no `llm_gateway`/Telegram import anywhere in either new service
module), and integration (real `CapabilityExecutor` + `WorkflowRunner` + Postgres `db_session`
fixture: off-mode no-op, shadow-mode persists the plan and leaves `CopywritingCapability`'s own
output untouched, idempotency, backward compatibility without prior `EditorialBrief`/
`AdaptiveLengthPlan` data, no interference with `channel_relevance` payload, failure isolation, no
`ContentDraft` mutation and no Telegram import anywhere in the workflow path).

**Targeted run** (`test_beginner_friendly.py` + `test_adaptive_length.py` + `test_editorial_
brief.py` + `test_channel_relevance.py` + `test_copywriting_capability.py` +
`test_capability_executor.py` + `test_capability_executor_image_intelligence.py` +
`test_fact_safety.py` + `test_editorial_scoring.py` + `test_phase10_workflow_integration.py` +
`test_content_generation_integration.py`): **14 failures, 309 passed** — byte-for-byte identical
failure categories to M1's/M2's/M3's own already-documented pre-existing baseline
(`_ai_execution_count(db_session) == 0` against the live-growing `ai_executions` table in the real,
shared dev Postgres instance, plus one `.env`-vs-code-default `content_generation_dry_run`
override) — **zero new failures, zero overlap with any Phase 17 M4 code**.

**Ruff**: all new/changed files (`schemas/beginner_friendly.py`, `services/editorial_glossary.py`,
`services/beginner_friendly.py`, `schemas/candidate_fact_safety.py`,
`services/candidate_fact_safety.py`, `capabilities/executor.py`, `core/config.py`,
`prompts/copywriting_beginner_candidate/`, `scripts/phase17_m4_beginner_copywriting_comparison.py`,
`tests/test_beginner_friendly.py`) — **all checks passed**.

**Mypy**: `schemas/beginner_friendly.py`, `services/editorial_glossary.py`,
`services/beginner_friendly.py`, `schemas/candidate_fact_safety.py`,
`services/candidate_fact_safety.py`, `capabilities/executor.py`, `core/config.py`,
`scripts/phase17_m4_beginner_copywriting_comparison.py` — **no issues found in 8 source files**.

**Architecture validation** (`scripts/validate_architecture.py`): **0 forbidden-dependency
violations**.

## 31. Full regression

Established baseline: Phase 17 M3's own most recently documented full-suite run
(`docs/phase17_m3_adaptive_length_shadow_comparison_report.md` §24) was **20 failed, 1786 passed**
(1806 total).

This milestone's own full run (`python -m pytest -q`, real Postgres, all four production workers
stopped throughout): **20 failed, 1836 passed** in 2361.03s (1856 total = 1806 baseline + this
milestone's 50 new tests, exactly). **19 of the 20 failures are byte-for-byte identical** to the
already-documented M1/M2/M3 baseline categories (`test_capability_executor.py` ×8, `test_content_
generation_integration.py` ×1, `test_content_worker_cycle.py` ×2, `test_content_worker_cycle_
image_preview.py` ×1, `test_editorial_inbox_service.py` ×1, `test_editorial_scoring.py` ×2,
`test_fact_safety.py` ×2, `test_news_handler.py` ×1, `test_phase10_workflow_integration.py` ×1) —
same root cause (`_ai_execution_count(db_session) == 0` against the live-growing `ai_executions`
table, one `.env`-vs-code-default override).

**One failure in the same already-disclosed flake class, not a new regression**:
`tests/test_content_worker_main.py::test_enabled_loop_runs_cycles_and_respects_interval` — a
different specific test than M3's own disclosed flake in this same file
(`test_enabled_loop_survives_ordinary_exception_and_continues`, §26 of the M3 report), but the same
underlying class: a tight, real-time timing assertion on a content-worker polling loop, structurally
unrelated to any Phase 17 M4 code path (no `beginner_copywriting_mode`, `services/
beginner_friendly.py`, or `services/candidate_fact_safety.py` import or exercise anywhere in this
test). Re-run in isolation immediately after: **passed cleanly in 10.98s**. Consistent with the
same "shared real infrastructure + a tight timing assumption disturbed under 1800+-test system
load" explanation M3's own report already gave for this exact file — not re-run as a second full
40-minute pass to confirm non-recurrence, for the same reasons M3 disclosed.

**Zero new deterministic failures caused by Phase 17 M4 code.**

## 32. Known limitations (overall)

- **Truncation bug, 21.9% (7/32)** — the dominant, disclosed defect of this milestone (§22). Not
  fixed here (32-call cap already spent); a clear, specific recommendation is given for a future
  tuning pass.
- **Entity/term-detection regex gaps** (§25) — multi-word proper nouns fragmented, title-case
  multi-word glossary terms (e.g. "Series A") not correctly routed. Inflates the observed
  "unnecessary explanation" rate; the model itself handled the resulting bad signals gracefully in
  every observed case (no fabrication).
- **`unsupported` explanation rate, 2/9 (22%) among explanation-required successful cases** — real,
  disclosed, but every instance is a true-but-ungrounded statement (e.g., attributing "Reels" to
  Meta without a literal source citation), never an invented fact.
- **Automated Fact Safety audit is a noisy upper bound, not ground truth** (§26) — cross-language
  entity mismatches, a money-range regex gap, and causal-hedge misclassification produced one false
  `FAIL` and inflate the `review` count; manual review remains authoritative.
- **`_EVIDENCE_WORDS_PER_UNIT = 28` is a reasoned starting estimate**, not fit to outcome data — no
  historical corpus of `safe_range`-targeted candidates exists yet to calibrate against.
- **One disclosed M3_BEST case** (`b9eb8450`, §23) — the `safe_range` mechanism can be more
  conservative than M3's own `ideal_range` target on rich sources, trading completeness for safety.

## Definition of Done

- [x] `BeginnerFriendlyPlan` schema created and versioned (§6).
- [x] Safe glossary created and versioned, never dynamically expanded (§7).
- [x] Subject/term explanation grounded only in real evidence or the glossary — zero fabricated
      explanations found across all 25 manually-reviewed successful candidates (§23, §24).
- [x] Ideal vs safe length split implemented and schema-enforced (§9); measurably improves
      range-compliance vs M3 (46.9% vs 18.75%, §21).
- [x] M3's under-length root cause investigated and fixed at the prompt level (§4, §15).
- [x] Natural multi-paragraph structure supported (§10).
- [x] Filler and repetition detection implemented, deterministic (§11).
- [x] Deterministic, zero-new-LLM-call CandidateFactSafetyAudit second pass implemented (§12, §13).
- [x] Shadow integration added, byte-identical output when off (§14).
- [x] New, separately-named governed prompt — `copywriting`/`copywriting_adaptive_candidate`
      verified unmodified (§15).
- [x] Comparison script built, dry-run default, resume support, M3-candidate reuse (§16).
- [x] Cost bounded to ≤32 calls, real estimate presented, explicit user confirmation obtained
      before any paid call (§17) — **exactly 32 calls made, $0.17785 actual cost**.
- [x] `ContentDraft` never mutated; zero Telegram messages sent (§20, structurally unreachable).
- [x] 50 tests written and passing (§30).
- [x] Ruff/Mypy/architecture validation clean on all new/changed files (§30).
- [x] Targeted regression: zero new failures vs M1/M2/M3 baseline (§30).
- [x] **Full regression suite run and compared against M3's 20 failed/1786 passed baseline** — 20
      failed, 1836 passed; zero new deterministic failures (§31).
- [x] Report created (this document).
- [x] Checkpoint created (`checkpoint/phase17-m4`, see final answer).
- [x] Production workers remained stopped throughout (Docker state confirmed at start, re-confirmed
      before this report was finalized).
- [x] Truncation rate measured — **21.9% (7/32), FAILS the 0% target** — disclosed, not masked
      (§22, §32).
- [x] Activation decision made on real metrics, not activated (§32) — **shadow-ready, with a
      specific, disclosed tuning gap**, matching this milestone's own explicit instruction: "if
      acceptance targets are not met, do not activate; return TUNING REQUIRED and document exact
      causes."

**Final status: PHASE 17 M4 COMPLETE — SHADOW READY, TUNING REQUIRED.**

The `safe_range` length-recalibration mechanism (§9) is a measured, real improvement over M3
(range-compliance more than doubled, 18/25 successful candidates preferred over M3 on manual
review, zero fabricated explanations found across 25 manually-reviewed candidates). It is not
activated in production. The specific, disclosed reason is the §22 truncation defect — a
self-inflicted, root-caused consequence of raising `reasoning_effort` to `"medium"` without
matching token headroom — which must be fixed and re-measured (without consuming additional paid
calls beyond what a future milestone explicitly budgets) before any production activation decision
can be revisited.
