# RESEARCH REUSE + ENTITY NORMALIZATION CHECKPOINT

Scope: the two narrow corrective items authorized after the Snapdragon C + VK focused forensic report, against committed HEAD `c308d45f6d55dc895eabe24b1901e1f99f855bbe` plus the working tree's post-acceptance follow-up fixes. Part 1 is implemented and tested. Part 2 is calibration only — **not implemented**. No commit, no deploy, no video/source-pack work.

## A. Research reuse

### Exact stale-reuse condition

`capabilities/executor.py::_try_reuse()` → `services/analysis_reuse.py::reuse_prior_result()` reused a NEWS_ANALYSIS task's persisted `research` result for CONTENT_GENERATION whenever that prior result existed and was well-formed — with **no check at all** for whether the event's evidence context had changed since. Under `article_acquisition_mode == "enforce"`, article acquisition happens later, inside CONTENT_GENERATION's own flow (per `services/evidence_package.py`'s own docstring) — so a NEWS_ANALYSIS-stage `research` result is, by construction, always produced *before* acquisition exists. Reusing it silently discarded the freshly-built `article_evidence_text` context `capabilities/executor.py` had already assembled for that exact call. Confirmed as the real root cause of both the Snapdragon C and VK forensic cases.

### Exact fix

`services/analysis_reuse.py::reuse_prior_result()` now takes an optional `event_id` and, for the `"research"` capability specifically, rejects the cached result (forcing a real call) when `_acquisition_postdates()` is true:

- `article_acquisition_mode != "enforce"` → never true (byte-identical to today whenever `enforce` isn't active — no new evidence context could exist to make anything stale).
- No acquisition exists, or it didn't reach a trusted completeness tier (`TRUSTED_FULL_ARTICLE_STATUSES = {FULL_TEXT, PARTIAL_TEXT}`, now a public constant shared with `services/evidence_package.py` rather than a second, divergent definition) → never true (a failed/weak acquisition adds no richer evidence; reuse stays exactly as safe as before).
- Otherwise: true only when the acquisition's own `created_at` is strictly after the source NEWS_ANALYSIS task's own `updated_at` — a safe, conservative cutoff (`research` always finishes before the rest of that same task, so real staleness can only be understated by this comparison, never overstated).

No new cache subsystem, no prompt/input hash, no change to Research's or Copywriting's own semantics, no second acquisition-text transport path — the fix reuses exactly the metadata that already existed (`EditorialTask.updated_at`, `NewsEventArticleAcquisition.created_at`/`effective_completeness_status`, both already read elsewhere) and the already-existing `get_effective_acquisition()` call.

### Files changed

- `services/analysis_reuse.py` — `_acquisition_postdates()` added; `reuse_prior_result()` gains the optional `event_id` parameter and the staleness check.
- `capabilities/executor.py` — `_try_reuse()`'s one call site now passes `event_id=task.event_id`.
- `services/evidence_package.py` — `_TRUSTED_FULL_ARTICLE_STATUSES` renamed to the public `TRUSTED_FULL_ARTICLE_STATUSES` (now a shared constant, two real consumers, never a second divergent "trusted enough" definition).
- `tests/test_analysis_reuse.py` — 6 new tests plus a shared `_make_acquisition()` fixture helper.

### Snapdragon C before/after

| | Before the fix | After the fix |
|---|---|---|
| CONTENT_GENERATION `research` step | Reused the NEWS_ANALYSIS-stage result (100ms, no LLM call), produced 23 minutes before acquisition completed — `facts`/`gaps` reflect only the 227-character bare RSS excerpt | A real, fresh capability call — receives `article_evidence_text` built from the acquired, spec-rich article |
| Copywriting's evidence | Same stale `facts`/`gaps` Research never updated | The fresh Research output, itself now grounded in the real article |
| Real regression proof | — | `tests/test_analysis_reuse.py::test_reuse_5_snapdragon_shape_forces_fresh_research_with_full_article_evidence` reproduces this exact shape (stale pre-acquisition result cached, acquisition completes 23 minutes later, `enforce` active) and asserts the CONTENT_GENERATION `research` step is the fresh, spec-bearing result, never the stale one |

### Tests

All 6 required cases added to `tests/test_analysis_reuse.py`, all passing:

1. `test_reuse_1_stale_result_not_reused_when_acquisition_postdates_it` — NEWS_ANALYSIS research exists, acquisition (`FULL_TEXT`) completes afterward under `enforce` → rejected.
2. `test_reuse_2_result_still_reused_when_acquisition_predates_it` — acquisition already existed before the cached result → still reused.
3. `test_reuse_3_no_acquisition_or_weak_acquisition_keeps_existing_safe_reuse` — no acquisition row, and a `HEADLINE_ONLY` (untrusted-tier) acquisition newer than the task → both still reused.
4. `test_reuse_4_no_duplicate_paid_call_when_reuse_genuinely_valid` — full `WorkflowRunner` path, `article_acquisition_mode` at its real `"off"` default, research/intelligence wired as raising capabilities → still correctly skipped (reused), proving no behavior change for the unaffected, ordinary case.
5. `test_reuse_5_snapdragon_shape_forces_fresh_research_with_full_article_evidence` — the exact real failure shape end-to-end through `WorkflowRunner`, asserting the `research` step result is the fresh, spec-bearing one.
6. `test_reuse_6_copywriting_receives_the_fresh_research_result` — same shape, asserts specifically on what `CapabilityContext.business.workflow_state.step_results["research"]` contains when the `copywriting` step actually runs (via a context-capturing fake capability) — proving propagation all the way to Copywriting's real input, not merely that Research itself was fresh.

Plus all 11 pre-existing `test_analysis_reuse.py` tests re-verified passing unchanged (17/17 total). `tests/test_evidence_package*.py` re-verified byte-identical pass/fail/skip signature after the constant rename (3 pre-existing, already-confirmed-unrelated failures; 6 passed, including the 4 tests added during the prior checkpoint phase). `tests/test_content_generation_integration.py`/`test_capability_executor.py` re-verified: the one failure + one error present are confirmed byte-identical on the unmodified working tree too (a pre-existing `.env`/`CONTENT_GENERATION_DRY_RUN` environment mismatch, already documented earlier this session, unrelated to this change). Ruff, mypy (all 3 touched production files), and `scripts/validate_architecture.py` all clean.

### Cost/latency impact

Only under `article_acquisition_mode == "enforce"`, and only for an event whose acquisition completes *after* its own NEWS_ANALYSIS-stage research ran (the exact condition that was previously silently producing wrong/stale evidence): one additional real Research LLM call per such event during CONTENT_GENERATION (~$0.0013–0.0018 per real observed Research call this session, ~2-3 seconds latency). This is strictly the cost of the `enforce` mode's own intended purpose actually being realized for the `research` step — not a new, additional cost category. Zero cost/latency change for every other case (acquisition already existed before NEWS_ANALYSIS ran, acquisition failed/weak, or `enforce` not active).

## B. Entity calibration

**Not implemented — calibration only, per explicit instruction.**

### Real calibration dataset

Built entirely from the real, persisted `stories` table (1,280 real `Story` rows in the working database) — no synthetic data:

- 960 unique multi-word entities across all stories; 602 unique 2-word entities examined in detail.
- **26 real, concrete positive-pattern matches** for a candidate 5-word lexicon extension (see Strategy A) — every one manually reviewed, spanning geographic place names (Румыния, Китай, Россия, Германия, Хошимин, Каспийск, Оренбуржье, Балашиха), institutions (МГУ, МАИ, ЮФУ, Госдума), a platform/game (Steam, Genshin Impact), and companies (Apple, Anthropic) — **including the exact real VK case** (`"отчёт vk"` → `"vk"`, the event 2 `NewsEvent` from the VK forensic case itself).
- **Real negative controls verified**, drawn from the same corpus: `"ai"` appears as its own standalone single-word entity **149 times** across the corpus (by far the most frequent token checked) — confirms it is a stable, load-bearing entity, never a candidate for stripping, despite superficially "feeling" generic. Real company-prefixed product names (`"google pixel"`, `"apple watch"`, `"amazon bedrock"`, `"github copilot"`, `"gemini titan"`, etc.) — none touched by any candidate lexicon considered, since Google/Apple/Amazon/GitHub are proper nouns, never part of a generic-noun lexicon. Real outlet names (`"the guardian"`, `"the new york times"`, `"the daily upside"`, `"the motley fool"`, etc.) surfaced a related, **pre-existing, already-shipped** risk unrelated to this calibration's own scope (see note below).
- The user's own additional suggested patterns (результаты/results, заявление/statement, исследование/research, презентация/presentation) had **no real hits** in this corpus — noted honestly as unconfirmed-by-data, not fabricated.

**Related finding, disclosed but out of this calibration's scope**: the already-shipped CD Projekt fix's `_GENERIC_DETERMINER_ENTITIES` set already includes `"the"` unconditionally. Real corpus evidence shows this already strips `"The"` from genuine outlet names appearing as their own entity (`"the guardian"` → `"guardian"`, `"the new york times"` → `"new york times"`, etc.) — a real, pre-existing over-stripping pattern from a prior, already-authorized phase, not introduced or worsened by anything evaluated here. Flagged for awareness, not proposed for correction this phase.

### Strategies compared

**Strategy A — small generic-prefix lexicon.** Extend the existing `_strip_leading_determiner()` mechanism with a narrow, real-evidence-backed set: the two Russian prepositions `"в"`/`"от"` (closed grammatical class — structurally impossible for a real proper name to legitimately begin with a bare preposition as its own capitalized word) and three institutional/document common nouns confirmed by real data — `"отчёт"`, `"компани"`, `"правительств"` (the last two already in their post-case-stripped form, matching exactly what `_extract_entities()`'s own normalization pipeline actually produces before the determiner check runs — a real precision requirement: any lexicon addition must be defined in stemmed form or it will silently never match).

**Strategy B — structural/frequency-based normalization.** Reusing the corpus itself as a signal: does a candidate leading word ever appear as its own standalone single-word entity elsewhere in the corpus? Computed for real for every candidate word (table below). Works cleanly for `"в"`, `"the"`, `"отчёт"`, `"правительств"` (0 standalone occurrences each) but is **noisy** for `"компани"`/`"от"`/`"китайск"` (each appears standalone a small number of times too, from real extraction edge cases — e.g. a title whose *only* capitalized run was the bare word itself). No existing infrastructure computes or maintains this table today; building and refreshing it is a real, non-trivial addition, not a narrow fix.

| Word | Standalone single-word entity? | Total occurrences (any position) |
|---|---|---|
| `отчёт` | No | 1 |
| `компани` | **Yes** | 4 |
| `правительств` | No | 3 |
| `в` | No | 22 |
| `от` | **Yes** | 4 |
| `китайск` | **Yes** | 4 |
| `ai` | Yes | 149 |
| `the` | No | 50 |
| `google` | Yes | 42 |
| `apple` | Yes | 31 |
| `amazon` | Yes | 14 |
| `github` | Yes | 3 |

**Strategy C — existing LLM/entity-extraction prompt correction.** **Not applicable.** `services/story_memory.py::_extract_entities()` is confirmed 100% deterministic (a regex-based capitalized-run heuristic) — there is no existing LLM-based entity/NER capability anywhere in the codebase to correct (confirmed by search: no capability, no prompt file, references it). Building one would be a genuinely new capability (new prompt, new cost, new latency, new failure modes) — not a fix to something that already exists, and explicitly out of scope ("do not introduce a new NLP dependency").

### Measured outcomes

| | Strategy A | Strategy B | Strategy C |
|---|---|---|---|
| VK case result | **Fixed** — `"отчёт vk"` → `"vk"`, matches event 1's story exactly | Fixed for `"отчёт"` specifically (0 standalone occurrences, clean signal) — but the underlying mechanism doesn't yet exist | N/A — nothing to correct |
| Real entity pairs changed | **26** (5-word extension, whole corpus) | Not implemented/measured as a system — only the diagnostic table above was computed | N/A |
| False-merge risk | Low — every one of the 26 real changes reviewed is a correct improvement; 0 violations found among real negative controls (AI, company-prefixed products, CD Projekt/"the witcher") | Unknown/unproven at scale — the signal itself is noisy for 3 of 12 real candidate words checked | N/A |
| False-split reduction | 26 real cases where two mentions of the same real entity would now normalize identically (directly enables correct matching for all 26, not just VK) | Same 26, if the noisy cases were resolved by a real threshold — unproven | N/A |
| Negative controls preserved | Yes — `"ai"` (149 standalone hits), all company-prefixed products, all confirmed untouched (none are in the candidate lexicon's semantic category at all) | Yes for the words with a clean signal; ambiguous for the 3 noisy words | N/A |
| Effect on CD Projekt / already-good cases | **None** — `"the"` handling is completely unchanged; the new candidates are a disjoint word set | Same, if implemented | N/A |

### Recommended strategy

**Strategy A**, scoped to exactly the two prepositions (`в`, `от`) plus the three real, corpus-confirmed institutional nouns (`отчёт`, `компани`, `правительств`) — not a broader, uncalibrated "strip any common noun" rule, and not the user's additional suggested words (`результаты`/`заявление`/`исследование`/`презентация`), which have no real corpus confirmation yet and should wait for their own evidence before inclusion.

### False-positive/over-merge risk

Assessed as **low** for the recommended scope specifically: prepositions are a small, closed, unambiguous grammatical class in Russian (structurally cannot be part of a real proper name), and the three institutional nouns showed zero false positives across all 26 real corpus occurrences, are semantically narrow (organizational/document-type wrappers only, not general adjectives or content nouns), and mirror the exact reasoning already accepted for the shipped CD Projekt fix. The risk would rise materially if the lexicon were broadened casually (e.g., adding arbitrary common nouns without the same per-word corpus check this calibration applied) — any future addition should get the same treatment (real corpus search + explicit standalone-entity check) before inclusion, not be added by inference alone.

## C. Decision request

### `IMPLEMENT GENERIC-PREFIX NORMALIZATION`

Scope: extend the existing `_strip_leading_determiner()` mechanism (or an equivalent, clearly-labeled sibling set applied at the same step) with exactly `{в, от, отчёт, компани, правительств}` in post-case-stripped form. Calibration evidence is real, sourced from the full working database (not synthetic), shows 26/26 correct real-world corrections with zero false positives against verified negative controls, directly resolves the real VK forensic case, and leaves the CD Projekt case and every other already-shipped behavior untouched.

**Not implemented this phase.** Awaiting explicit authorization before making this change. No commit, no deploy, no video/source-pack work.
