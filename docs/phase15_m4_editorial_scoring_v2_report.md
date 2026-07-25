# Phase 15 — Editorial Intelligence — M4 Editorial Scoring V2 — Implementation Report

Status: IMPLEMENTED, TESTED, BACKTESTED. **Cutover to live V2 is deliberately NOT activated** —
see §13. `editorial_scoring_version` remains at its default, "v1"; production behavior is
unchanged by this milestone.

---

## 1. Previous scoring root cause

`capabilities/scoring_capability.py::_build_request()` sends the LLM only `title`/`category`/
`summary`/target language and asks for one holistic `{"score": int, "rationale": str}` — no
freshness, no source reliability, no real or predicted engagement, no novelty signal reaches the
prompt or the final number. That raw LLM output is stored verbatim at
`EditorialTask.workflow["step_results"][i]["result"]["score"]` for the step named `"scoring"`
and read by exactly one downstream consumer, `worker/content_cycle.py::_extract_scoring_result()`
(requires a plain `int`). `EngagementCapability` (Phase 13) runs immediately before scoring in
the same NEWS_ANALYSIS workflow and produces a *predicted* `engagement_potential_score`, but
nothing ever reads it (confirmed structurally by Phase 15 M3's own
`test_engagement_capability_does_not_yet_read_real_engagement_metrics`, and re-confirmed here).
Real, *observed* engagement (Phase 15 M3's `views_count`/`forwards_count`/`replies_count`/
`reactions_count`) was persisted but likewise never read by anything. Editors have no visibility
into why a story received its score beyond one free-text `rationale` string.

## 2. V2 architecture within existing boundaries

No new workflow step, no new Capability, no new LLM/provider call, no new table. V2 is a
deterministic post-processing enrichment of the *existing* `"scoring"` step's already-produced
output, applied at the one seam that already sits between a Capability's raw result and its
persisted `WorkflowStepResult.result`: `capabilities/executor.py::CapabilityExecutor.execute()`.

```
NewsEvent → Research → Intelligence → Engagement (LLM, predicted, still unread)
          → Scoring (LLM, unchanged prompt/schema) → structured_output {"score", "rationale"}
                                                              │
                                     capabilities/executor.py │  (only when step.capability == "scoring")
                                                              ▼
                              services.editorial_scoring.apply_editorial_scoring_v2()
                                 - settings.editorial_scoring_version != "v2" → return unchanged (0 DB queries)
                                 - "v2" → 2 extra indexed reads (NewsSource, same-source engagement
                                   baseline) + pure compute_editorial_score_v2()
                                                              │
                                                              ▼
                    WorkflowStepResult.result = {..original.., "score": <V2 int>, "version": "v2",
                                                  "components": {...}, "coverage": {...}, "reason": "...",
                                                  "legacy_llm_score": <original int>, "weights": {...}}
                                                              │
                                                              ▼
                          worker/content_cycle.py::_extract_scoring_result() — UNCHANGED,
                          still reads step_results[i]["result"]["score"] as a plain int
```

`ScoringCapability` itself, its prompt/schema, `workflows/definitions/news_analysis.py`,
`workflows/runner.py`, `EngagementCapability`, and `worker/content_cycle.py` are all byte-for-byte
unmodified. New files: `services/editorial_scoring.py` (the calculator), 5 weight/version fields
on `core/config.py:Settings`, one `tests/test_editorial_scoring.py`, one read-only backtest
script.

## 3. Formula and weights

```
score = round(100 * clamp01(
    w_semantic     * (legacy_llm_score / 100)
  + w_freshness    * services.freshness.compute_freshness(...).weight
  + w_engagement   * engagement_component
  + w_reliability  * (NewsSource.reliability_score or 0.5)
  + w_novelty      * 0.5   # permanent fallback, see §7
))
```

Default weights (`core/config.py`, `services/editorial_scoring.DEFAULT_WEIGHTS`, both asserted
equal and summing to 1.0 by `tests/test_editorial_scoring.py`):

| Component | Weight | Source |
|---|---|---|
| semantic_editorial | 40% | Existing `ScoringCapability` LLM score, reused verbatim, normalized to 0–1 |
| freshness | 20% | `services.freshness.compute_freshness().weight` — the exact function Triage already uses |
| engagement | 20% | Real M3-persisted metrics, percentile-ranked against the same source's own recent baseline |
| source_reliability | 10% | `NewsSource.reliability_score`, same field and same 0.5-neutral fallback (`services.triage.DEFAULT_RELIABILITY_SCORE`) Triage already uses |
| novelty | 10% | Permanent neutral fallback — no real signal exists (§7) |

These are the task's own "reasonable starting hypothesis," kept unchanged: no historical outcome
data exists to fit weights against (confirmed again during this milestone — same finding as
Phase 15 M0 discovery §9), so there was no repository evidence to justify a different split
*before* backtesting. The backtest (§12) is exactly the evidence-gathering step that could
justify a change, and §13 documents what it found and why weights/threshold, not the
architecture, are the open item.

All five weights are `core/config.py` `Settings` fields (`editorial_scoring_weight_*`), not
hardcoded — tunable without a code change, validated by test to sum to 1.0 (mirrors
`content_generation_scan_limit`'s own established tested-not-cross-field-validated convention;
this `Settings` class has no cross-field-validator precedent).

## 4. Missing-data semantics

| Signal | Missing case | Behavior |
|---|---|---|
| Semantic | N/A — guarded: a non-int/malformed legacy score short-circuits the whole function back to the unmodified v1 output (never fabricates a semantic component) |  |
| Freshness | `published_at` is `None` | Falls back to `collected_at`, exactly as `services.freshness` already does for Triage — no fabricated precision, documented existing convention |
| Freshness | future timestamp | Clamped to zero age (freshest tier) — `services.freshness`'s own existing, tested, approved behavior; never raises |
| Engagement | all four metrics `None` | Neutral component (0.5), `coverage.engagement_available = False` — never fabricated, never zero |
| Engagement | all four metrics `0` | Real, valid low-engagement observation — ranked against baseline normally, `engagement_available = True` |
| Engagement | baseline sample < 3 same-source rows | Neutral component (0.5), `coverage.source_baseline_available = False` |
| Source reliability | `NewsSource.reliability_score is None` | Falls back to 0.5, `coverage.source_reliability_available = False` — literally `services.triage.DEFAULT_RELIABILITY_SCORE`, not a new magic number |
| Novelty | always | Permanent neutral fallback (§7), `coverage.novelty_available` always `False` |

Every fallback is a documented **neutral** value (0.5), never a zero and never a fabricated
precise number — an event is never punished merely because a signal happens to be structurally
unavailable for its source type.

## 5. Engagement baseline method

For the event being scored, `engagement_magnitude = sum of whichever of {views_count,
forwards_count, replies_count, reactions_count} are non-None` (a documented simplification —
equal-weighted, not a new metrics taxonomy; out of M4's scoring-only scope to refine further).
`services.editorial_scoring.fetch_engagement_baseline()` reads up to the 20 most recent *other*
NewsEvent rows from the *same* `source_id` that have at least one non-null engagement field
(using the existing `ix_news_events_source_id` index — no new index/migration), and computes each
one's own magnitude the same way.

The event's component is its **percentile rank** within that baseline sample
(`count(baseline ≤ current) / len(baseline)`, clamped to [0, 1]) — bounded by construction, so a
1M-subscriber channel's raw view count is only ever compared against *that channel's own*
typical performance, never against a small channel's raw numbers (tested: §"Cross-source
fairness" below), and a single extreme outlier in the baseline cannot blow up the result the way
a raw ratio could.

## 6. Freshness decay

Reused exactly as-is: `services.freshness.compute_freshness()` — the same 6-tier
(`0-2h`/`2-6h`/`6-12h`/`12-24h`/`24-48h`/`48h+`), pre-tested, `services.triage`-approved decay
curve, called with `reference_now = datetime.now(UTC)` at scoring time (not Triage's earlier
`reference_now`). No second, competing decay curve was introduced.

## 7. Novelty handling

No reliable novelty/similarity signal exists anywhere in the current architecture — confirmed by
direct inspection: `services/deduplication.py::is_duplicate()` is an exact-content-hash gate
evaluated once, at collection time, before a `NewsEvent` even reaches `NEWS_ANALYSIS` (it cannot
be re-read at scoring time as a graded signal); grepping `capabilities/intelligence_capability.py`,
`capabilities/research_capability.py`, and every `prompts/{research,intelligence}/*.yaml` for
`novelty|duplicate|similar|unique` returns zero matches. Per the task's own instruction ("use a
conservative documented fallback rather than pretending precise novelty is available"), novelty
is a **permanent** neutral 0.5 for M4, `coverage.novelty_available` always `False` — not a
placeholder silently guessing, and not disguised as a real signal. Its 10% weight is therefore
currently inert (adds the same constant 0.05 to every score, changing no ranking) — noted
honestly in §14 as a real gap for a future milestone, not hidden.

## 8. Score output contract

```json
{
  "score": 74,
  "version": "v2",
  "components": {
    "semantic_editorial": 0.8, "freshness": 1.0, "engagement": 0.75,
    "source_reliability": 0.7, "novelty": 0.5
  },
  "coverage": {
    "engagement_available": true, "source_baseline_available": true,
    "source_reliability_available": true, "novelty_available": false
  },
  "reason": "High semantic relevance, very fresh, above-normal engagement for this source, medium source reliability.",
  "legacy_llm_score": 80,
  "weights": {"semantic_editorial": 0.4, "freshness": 0.2, "engagement": 0.2, "source_reliability": 0.1, "novelty": 0.1},
  "rationale": "<original ScoringCapability LLM rationale, preserved verbatim>"
}
```

`score` is always a Python `int` in `[0, 100]` — the one field `worker/content_cycle.py` reads,
unchanged. In v1 mode the stored result is `{"score": int, "rationale": str}`, byte-identical to
today's output (proven by `test_v1_mode_leaves_scoring_step_result_completely_unchanged`).

## 9. Explainability rules

`services.editorial_scoring._build_reason()` is pure string formatting over three deterministic
bands per component (`low` <0.33, `medium` <0.66, `high` ≥0.66) — never an LLM call. Produces
exactly the task's own worked example shape: *"High semantic relevance, very fresh, above-normal
engagement for this source, medium source reliability."* Logged once per scoring step
(`editorial_score_v2_computed`, only when v2 is active) with `event_id`, `task_id`, `score`,
`version`, `components`, `coverage` — no content, no secrets.

## 10. Files changed

Production:
- `core/config.py` — `editorial_scoring_version` (`"v1"`/`"v2"`, default `"v1"`), 5
  `editorial_scoring_weight_*` fields.
- `services/editorial_scoring.py` (new) — pure `compute_editorial_score_v2()`, async
  `fetch_engagement_baseline()`, async orchestration `apply_editorial_scoring_v2()`.
- `capabilities/executor.py` — 1 import + a 7-line conditional call after the existing
  `structured_output = result.structured_output or {}` line, only for `step.capability ==
  "scoring"`.

Diagnostics (not part of the runtime path):
- `scripts/phase15_m4_scoring_backtest.py` (new) — read-only backtest, §12.

Tests:
- `tests/test_editorial_scoring.py` (new) — 39 tests, §11.

No other file was modified for M4 — in particular `capabilities/scoring_capability.py`,
`prompts/scoring/*.yaml`, `workflows/definitions/news_analysis.py`, `workflows/runner.py`,
`capabilities/engagement_capability.py`, and `worker/content_cycle.py` are all untouched.

## 11. Tests and exact results

Focused: `tests/test_editorial_scoring.py` — **39/39 passed**, covering all required groups
A–M (score bounds; weight contract; freshness incl. future/missing timestamps; engagement
baseline incl. insufficient-sample/unsupported/observed-zero/extreme-outlier; cross-source
fairness; RSS-neutral-not-zero; source reliability known/missing; novelty fallback; backward
compatibility via `worker.content_cycle._extract_scoring_result`; full score-breakdown key/
version contract; structural "no LLM/provider import" proof; structural "hard gate files don't
reference editorial_scoring" proof; integration-level v1-byte-identical and v2-enriched
`CapabilityExecutor` + `WorkflowRunner` runs with zero `AIExecution` rows either way).

Full regression suite (`python -m pytest tests/`, 1053 collected — 1014 from the Phase 13–15 M3
checkpoint + 39 new M4 tests): **1050 passed, 3 failed**, 16m7s. All 3 failures are the identical,
already-documented pre-existing `content_generation_dry_run` environment/test-assumption mismatch
from the Phase 15 M3 checkpoint report (`docs/phase15_m3_engagement_signal_preservation_report.md`
§9) — this environment's `.env` has `content_generation_dry_run=False`, while
`tests/test_content_generation_integration.py::test_full_chain_dry_run_creates_draft_and_renders_without_sending`
and `tests/test_content_worker_cycle.py::test_run_content_cycle_sequential_no_gather_and_notifies_after_draft_creation`/
`test_run_content_cycle_dry_run_never_calls_bot_send_message` assert it defaults to `True`.
Confirmed unrelated to M4: grepping all three failing test files for `editorial_scoring` returns
zero matches, and no M4 file touches `content_generation_dry_run`. The two timing-flaky tests
that failed transiently in the M3 checkpoint run (`test_enabled_loop_survives_ordinary_exception_and_continues`
×2) passed cleanly in this run — consistent with them being wall-clock-race flakiness under
concurrent CPU load, not deterministic failures. **Zero M4-attributable regressions.**

Static checks (this session):
- `ruff check .` (full repo): **All checks passed.**
- `python scripts/validate_architecture.py`: **clean — 0 forbidden-dependency violations.**
- `mypy` on `capabilities/executor.py core/config.py services/editorial_scoring.py
  scripts/phase15_m4_scoring_backtest.py`: **Success: no issues found in 4 source files.**
- Manual secret-pattern scan (API keys, tokens, PEM headers, embedded-credential connection
  strings) across every M4-changed/new file: **zero matches.**

## 12. Backtest dataset and distributions

`scripts/phase15_m4_scoring_backtest.py`, fully read-only (no row ever mutated, no LLM/provider
call), run twice against the live Observation Mode database:

**Raw population**: all 287 real, `COMPLETED` `NEWS_ANALYSIS` tasks with a successful `"scoring"`
step (1 excluded: no int score found) → 286 samples.

**Clean population** (the one the threshold decision in §13 is based on): the raw population
further excluding 96 events with a malformed title (`services.cleaning.is_valid_title()` —
raw-HTML-fragment or bare-URL titles that the Phase 15 M1 gate, live since the Phase 13–15 M3
checkpoint, would reject *before* a `NEWS_ANALYSIS` task is ever created today) and 3 known
synthetic validation-run events (`"synthetic, not real news"` in the title, from Phase 13
M7/Phase 14 M6's own live-validation exercises) → **187 samples**. These 99 rows are historical
artifacts from before M1/M2 were deployed or from deliberate test runs — including them would
compare V2 against data that structurally cannot occur in the live pipeline going forward, so
they are excluded from every distribution and bias judgment below (raw-population numbers are
in the script's own JSON output for transparency, not repeated here).

Clean population (187), old (legacy LLM-only) vs. V2:

| | old | v2 |
|---|---|---|
| min | 1 | 27 |
| max | 88 | 74 |
| avg | 37.93 | 47.42 |
| median | 38 | 46 |
| p75 | 61.0 | 58.0 |
| p90 | 78.0 | 66.0 |
| count ≥ 65 | 40 (21.4%) | 25 (13.4%) |
| count ≥ 70 | 32 (17.1%) | 12 (6.4%) |

By source type, count ≥ 65 (the live threshold):

| Source type | n | old ≥65 | v2 ≥65 | v2/old ratio | v2 max score |
|---|---|---|---|---|---|
| RSS | 135 | 28 (20.7%) | 22 (16.3%) | 79% | 74 |
| TELEGRAM | 27 | 9 (33.3%) | 3 (11.1%) | **33%** | 66 |
| NEWS_API | 25 | 3 (12.0%) | 0 (0%) | **0%** | 61 (never reaches 65) |

`top10_overlap = 1/10`, `top20_overlap = 10/20` — V2 substantially reorders which stories rank
highest, not merely rescaling the same ordering.

Top upward movers (old → v2): a Russian-language Telegram post (+36: 5→41), an RSS dev-tooling
post (+35: 7→42), an RSS release-notes post (+34: 18→52) — all previously scored very low by the
LLM alone but freshness/engagement/reliability pulled them toward the middle.

Top downward movers: two duplicate RSS entries for the same "ЦБ РФ снизил ключевую ставку" story
(-22 each: 88→66) and an Uber/Atoms funding story (-22: 82→60) — high-LLM-score stories pulled
down by average freshness/engagement/reliability; an ICE/Palantir story (-20: 78→58, appears
twice as duplicate task rows).

Full per-event sample (`event_id`, source, category, both scores, components, coverage, reason)
was written locally to `scripts/_phase15_m4_backtest_samples.json` for this analysis and reviewed
in full; not committed (a 187-row dump of real historical titles/scores is a generated diagnostic
artifact, not source code — regenerable at any time by rerunning the script).

## 13. Threshold recommendation

**Recommendation: do not activate V2 at the live threshold (`CONTENT_GENERATION_MIN_SCORE=65`)
today.** Per the task's own explicit stop condition — *"obvious source-type bias... do NOT
silently activate V2"* — the clean-population backtest shows exactly that:

- **NEWS_API**: 0 of 25 clean historical events would have cleared 65 under V2 (was 3); the
  highest V2 score any NEWS_API event reached was 61 — structurally below threshold for this
  entire sample.
- **TELEGRAM**: eligible volume falls to 33% of its old rate (9 → 3 of 27) — below the task's own
  50% floor on a per-source-type basis, even though the *aggregate* ratio (62.5%, 40→25 of 187)
  does not itself cross that floor.
- **RSS** alone is comparatively mild (79% of its old eligible volume).

A likely, though not fully confirmed, contributing factor for Telegram specifically: Phase 15 M3
(real engagement persistence) only went live very recently — as of the Phase 13–15 M3 checkpoint,
only 3 of 516 Telegram-sourced `NewsEvent` rows carried any real engagement value at all. Most
Telegram rows in this backtest therefore hit `source_baseline_available = False` (fewer than 3
prior same-source rows with real engagement yet) and fall back to a *neutral* engagement
component rather than a genuinely differentiated one — which, blended with the also-often-neutral
`source_reliability` component, compresses what used to be a single, sometimes very high (max 88)
LLM score toward the middle. This should improve on its own as more real engagement history
accumulates under normal operation, independent of any weight change — but that is a hypothesis
based on today's sparse baseline data, not a proven fix, so it is not treated as a reason to
activate now regardless. NEWS_API's gap looks more structural (its LLM scores were already lower
on average in this sample, `avg=32.04` vs. RSS's `37.3`) and is not explained by the same
baseline-sparsity mechanism (NEWS_API has no engagement fields by design, same as RSS, yet its
ceiling is markedly lower than RSS's).

Concretely, per the task's explicit instruction to *"stop before cutover and recommend a
calibrated threshold based on backtest evidence"* rather than silently pick one: the clean-
population V2 distribution's p75 is 58 and median is 46 — a threshold in roughly the 50–58 range
would restore an eligible volume closer to today's, but the source-type-bias question (especially
NEWS_API's near-total exclusion) is a *distributional shape* problem a single threshold number
cannot fix by itself. This needs an explicit decision from the user/product owner — not something
this milestone should decide unilaterally by editing `.env`, per the task's own constraint.

**`.env` was not modified. `editorial_scoring_version` stays at its code default, `"v1"`, in
every environment.**

## 14. Rollout/rollback mechanism

`core/config.py:Settings.editorial_scoring_version: Literal["v1", "v2"] = "v1"` — the sole flag,
reusing this codebase's own established "explicit safe default, opt-in via env var" convention
(`news_collection_enabled`, `news_analysis_enabled`, `content_generation_enabled`,
`verify_capabilities_at_boot` are all the same shape). Rollback to v1 requires zero DB change (no
migration exists or is needed — see below) and zero code change — flipping the env var back is
sufficient, and `apply_editorial_scoring_v2()`'s very first line (`if
settings.editorial_scoring_version != "v2": return structured_output`) makes v1 mode a true,
zero-DB-query no-op, not merely "the weights happen to reduce to the old formula." Config
validity (weights sum to 1.0, version is one of the two literals) is tested
(`test_settings_weights_sum_to_one_and_match_defaults`; Pydantic's `Literal` type itself rejects
any third value at process startup).

No DB migration was added or is needed: `EditorialTask.workflow` is a plain `JSON` column
(confirmed by inspection of `database/models/editorial_task.py`), already proven sufficient by
`worker/content_cycle.py::_extract_scoring_result()` successfully reading the *existing* v1
`score` field from it in production today. Per the task's own explicit instruction ("do not add a
DB migration merely for score visibility unless repository evidence proves the current
step_results boundary is insufficient... if a migration appears necessary, STOP and report why"):
no such evidence exists — the boundary already works, so no migration was created.

## 15. Deployment details

`capabilities/executor.py` is imported by every worker that runs a workflow through
`CapabilityExecutor`, but the `"scoring"` step exists only in the `NEWS_ANALYSIS` workflow
definition (`workflows/definitions/news_analysis.py`) — `CONTENT_GENERATION`
(`workflows/definitions/content_generation.py`) has no step named `"scoring"`, so the new
conditional in `execute()` is inert there regardless of code version. The only service whose
*behavior* the M4 code touches is therefore `news_analysis_worker` (`python -m
worker.analysis_main`, `docker-compose.yml`) — matching the task's own prediction. `collector`
(`automation_worker`, `python -m worker.main`) is completely untouched (no code path change) and
was not restarted.

Sequence performed: (1) `docker compose ps` recorded the pre-deployment state — all 5 containers
already `Up`/healthy; (2) no unapplied migration existed (§14 — none was created), so there was
no code/schema-compatibility window to protect and no worker needed stopping first; (3) `docker
compose build news_analysis_worker` built cleanly; (4) `docker compose up -d --no-deps
news_analysis_worker` recreated only that one container from the new image — `--no-deps`
deliberately left `postgres`/`redis`/every other service untouched; (5) verified inside the
running container that `settings.editorial_scoring_version == "v1"` and that
`capabilities.executor`'s loaded source now contains the `apply_editorial_scoring_v2` call —
confirming the new code is live and still dormant, not merely committed. `automation_worker` and
`content_worker` were left on their pre-M4 image — both provably unaffected by this milestone's
code (§2), so rebuilding/restarting them would have been an unnecessary touch of unrelated
infrastructure.

## 16. Live validation evidence

V2 was **not** activated in production (§13), so there is no live V2-scored
`NEWS_ANALYSIS` completion to observe — this is the direct, honest consequence of the threshold-
safety stop condition, not an oversight. What was validated live instead: the unchanged v1 path
continues to run correctly after this milestone's (behavior-neutral) code deployment.

Within 10 minutes of redeploying `news_analysis_worker`, **7 real NEWS_ANALYSIS tasks completed
naturally** (no manual trigger, no backlog processed, normal poll-interval cadence) — every one
queried directly from the live database:

| Event | Score | Rationale (truncated) |
|---|---|---|
| "This Artificial Intelligence (AI) Stock May Be..." | 32 | "One analyst's opinion... limited significance without company name" |
| "Южная Корея продвигает свои амбиции..." | 62 | "South Korea's AI ambitions are important..." |
| "stinkpot: sqlite-backed shell history" | 18 | "Niche developer release... limited news value" |
| "Гениальная ОС, которую никто не помнит..." | 12 | "Nostalgic review... low public significance" |
| "Следим за новостями:" | 0 | "No factual content... cannot assess newsworthiness" |
| "Universities ask for $24.5 million to launch..." | 58 | "Notable EdTech investment... limited without more detail" |
| "Robert Morris University infuses AI into MBA..." | 42 | "Local education news... limited significance" |

Every one of the 7 `step_results["scoring"]["result"]` values is the exact `{"score": <int>,
"rationale": <str>}` shape — **no `"version"`, `"components"`, `"coverage"`, or `"reason"` key
present** — direct, live proof (not just a unit test) that this deployment changed zero observable
behavior. Confirmed alongside:
- No duplicate `NEWS_ANALYSIS` or `CONTENT_GENERATION` tasks created.
- No backlog surprise (`docker logs --since 5m` across all three workers: zero
  error/exception/traceback lines).
- No new provider-call pattern — the same one `POST .../v1/responses` per capability step
  observed before this deployment.
- No malformed title reached scoring (M1's gate, unrelated to and unaffected by M4, still holds).
- `content_generation_min_score` threshold comparison logic in `worker/content_cycle.py`
  untouched and still operating on these same-shaped `int` scores.

## 17. Editorial review sample

Derived from the clean-population backtest (§12; full detail in the reviewed-but-uncommitted
`scripts/_phase15_m4_backtest_samples.json`).

**Top 5 by V2 score** (of 187 clean samples; component reasons are each event's own
deterministic `reason` string): the four ≥70-scoring TECH/GADGETS category stories plus one
AI-category story — all "high semantic relevance, very fresh" with above-normal or unavailable-
but-neutral engagement, matching their high legacy scores too (see `top20_overlap=10/20` in §12
— roughly half of the pre-existing best stories remain top-ranked under V2).

**5 near the 65 threshold** (V2 score 60–67): a mix of RSS/TELEGRAM stories where the deciding
factor was consistently the `freshness`/`engagement` bands rather than `semantic_editorial` alone
— i.e. exactly the intended effect of blending signals, visible directly in each one's `reason`
string.

**5 rejected by V2 score** (<65, previously ≥65 under v1): dominated by NEWS_API and TELEGRAM
events per §12/§13's bias finding — the concrete evidence behind the threshold recommendation,
not an abstract statistic.

**Strongest upward mover**: "Мужчины, общий сбор" (Telegram), 5 → 41 (+36) — a very fresh,
low-legacy-score post whose freshness/neutral-baseline components pulled it up substantially.

**Strongest downward mover**: "ЦБ РФ снизил ключевую ставку до 14%" (RSS, duplicate rows), 88 → 66
(-22) — a high-legacy-score story pulled toward the middle by average freshness/neutral
engagement/reliability; still clears a plausible recalibrated threshold (~58), illustrating why a
single-number threshold fix without addressing source-type bias is only a partial answer.

## 18. Cost/latency impact

**Provider calls: 0 added**, in both v1 and v2 mode — proven structurally
(`test_editorial_scoring_module_imports_no_llm_gateway_or_capability`) and at runtime (every
`CapabilityExecutor`/`WorkflowRunner` integration test in `tests/test_editorial_scoring.py`
asserts `AIExecution` row count stays 0 regardless of scoring version). `EngagementCapability`'s
own existing call is unchanged — M4 does not touch it or wire its output in (that remains a
documented, honest gap, §14/§19).

**DB queries added, v2 mode only**: exactly 2 extra, both on already-indexed columns —
`NewsSource` fetched by primary key (`session.get`), and up to 20 `NewsEvent` rows filtered by
the existing `ix_news_events_source_id` index (`fetch_engagement_baseline`, `LIMIT 20`). **v1
mode: 0 extra queries** — `apply_editorial_scoring_v2()`'s first line returns immediately.

**Caching**: none added or needed — two cheap, indexed, single-row/bounded-limit queries per
scoring step is not a scaling concern at current volume (news_analysis_batch_size=5 events per
cycle, poll_interval=300s in Observation Mode).

**Deterministic compute latency**: `compute_editorial_score_v2()` itself is pure Python
arithmetic over five already-fetched scalar/short-list inputs — sub-millisecond, not separately
benchmarked (no meaningful cost to measure).

**Monetary cost**: not fabricated. Since 0 new provider calls are added, M4 introduces no new LLM
spend in either scoring version.

## 19. Remaining limitations

- Novelty has no real signal (§7) — its 10% weight is currently inert (constant across every
  event). A future milestone would need an actual duplicate/similarity signal to make this
  component meaningful.
- Engagement baselines for Telegram sources are still thin (§13) — this is expected to improve
  organically as more Phase 15 M3 engagement history accumulates, not something M4 can fix by
  itself.
- NEWS_API's lower V2 ceiling in this backtest is only partially explained (§13) — worth a
  focused follow-up look at whether NEWS_API's legacy LLM scores are systematically lower for a
  content-shape reason, before any weight rebalancing is attempted.
- The engagement magnitude formula (§5) sums the four raw metrics unweighted — a documented
  simplification, not a considered metrics taxonomy.
- No live V2 delivery has been observed (§16) — only the backtest and local test suite validate
  V2's behavior; a future milestone should re-run the backtest and reconsider cutover once (a)
  more Telegram engagement history exists and (b) a threshold/weight recalibration decision has
  been made.
- `bot/formatting.py` was deliberately not touched — the V2 breakdown is not yet surfaced on the
  delivered Telegram card, only in `EditorialTask.workflow` JSON (matches the "no Telegram
  destination change" constraint; optional future enhancement, not required by M4).

## 20. M5 Fact Safety handoff

M4 leaves `capabilities/quality_capability.py`, `ContentDraft`, and the delivery/Telegram path
completely untouched — Fact Safety (M5, per
`docs/phase15_editorial_intelligence_implementation_plan.md`) can proceed independently of
whether/when V2 scoring is eventually activated, since M5's scope (entity/claim-overlap checking
inside `QualityCapability.execute()`) has no dependency on the scoring formula. The one thing M5
should be aware of: if V2 is activated in the future, `EditorialTask.workflow["step_results"]`'s
`"scoring"` entry will carry additional keys (`version`, `components`, `coverage`, `reason`,
`legacy_llm_score`, `weights`) beyond the `"score"`/`"rationale"` shape M5 might otherwise assume
— any future code reading that step's `result` should key off `"score"` specifically (as
`worker/content_cycle.py` already does), not assume the dict has exactly two keys.
