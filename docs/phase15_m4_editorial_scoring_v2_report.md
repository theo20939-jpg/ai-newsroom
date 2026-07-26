# Phase 15 — Editorial Intelligence — M4 Editorial Scoring V2 — Implementation Report

Status: IMPLEMENTED, TESTED, BACKTESTED, **CALIBRATED (M4.1)**. **Cutover to live V2 is
deliberately NOT activated** — see §13 (original) and the M4.1 section's own §14 (final
recommendation). `editorial_scoring_version` remains at its default, "v1"; production behavior
is unchanged by either milestone.

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

---

# M4.1 FAIRNESS CALIBRATION

Status: CALIBRATED, TESTED, BACKTESTED. Cutover still **NOT** activated —
`editorial_scoring_version` remains `"v1"`. This section documents the offline diagnosis and fix
for the source-type bias M4's own backtest found (§13 above), performed entirely read-only
except for the one calibration code change itself (services/editorial_scoring.py) and its
redeployment (still dormant behind the unchanged `v1` default).

## 1. Reproduced bias

Re-ran `scripts/phase15_m4_scoring_backtest.py` (unmodified, read-only) three times over the
course of this milestone as Observation Mode kept running on `v1` in the background — sample
size grew naturally each time (226 → 236 → 241 → 254 clean, malformed/synthetic-excluded rows),
consistent with real ongoing collection, not a data artifact. The bias reproduced at every size,
matching the original M4 report within explainable growth:

| | old (legacy) ≥65 | pre-calibration V2 ≥65 | ratio |
|---|---|---|---|
| Overall (n=241) | 49 (20.3%) | 31 (12.9%) | 63% |
| NEWS_API (n=25) | 3 (12.0%) | 0 (0%) | **0%** |
| TELEGRAM (n=32) | 11 (34.4%) | 2 (6.3%) | **18%** |
| RSS (n=184) | 35 (19.0%) | 27 (14.7%) | 77% |

Confirms the original M4 finding: NEWS_API and Telegram both fall well below the task's own 50%
per-source-type floor, RSS comparatively mild.

## 2. Component-level root cause

Extended diagnostic (per-source-type component means/medians/quartiles, coverage rates) over the
same clean sample:

| Source | n | engagement_available | baseline_available | reliability_available | engagement component (mean) |
|---|---|---|---|---|---|
| NEWS_API | 25 | 0% | 0% | 100% | 0.5 (always neutral) |
| TELEGRAM | 32 | 28% | 12.5% | 100% | 0.5 (mean; individual values ranged 0.0–1.0 on the ~12.5% with a real baseline) |
| RSS | 174 | 0% | 0% | 100% | 0.5 (always neutral) |

`reliability_available_rate = 100%` for every source type in the live data — mechanism **D
(source reliability distribution)** is ruled out; every source already has a configured
`reliability_score`.

`novelty` is neutral 0.5 for **100% of all 241 events, no exceptions** — the single largest,
totally universal, source-agnostic compression source: mechanism **A (engagement neutral
fallback)** applies identically to novelty too, and dominates because it affects every event,
not just engagement-poor ones.

NEWS_API vs. RSS (both 100% engagement-neutral, so mechanism A/B cannot explain their gap from
*each other*): NEWS_API's `semantic_editorial` mean is 0.32 vs. RSS's 0.385, and `freshness`
mean is 0.312 vs. RSS's 0.536 — NEWS_API's disadvantage is mechanisms **F (semantic-score
distribution) and E (freshness distribution)**, not engagement fairness at all. Confirmed by the
calibration's own effect: fixing the engagement/novelty compression barely moves NEWS_API's
eligible count (0 → 0, see §10) because that was never where NEWS_API's problem lived.

Telegram's compression is mechanism **A + H (interaction)**: legacy scores had the widest spread
of any source type (mean 44.2, p75 68, max 88) so blending in ~30% fixed-neutral weight
(engagement + novelty) compresses that spread the most in absolute terms, and therefore costs
Telegram the most *eligible volume* even though the same formula is applied identically to every
source.

## 3. Missing-data analysis

Direct SQL check (`collected_hour` bucketed, Telegram sources only) found a **hard, clean
deployment-timing cutoff**: every Telegram event collected from 2026-07-25 07:00 UTC onward has
100% engagement-field population; every one collected before that (including 190 events from
2026-07-23 10:00 and 195 from 2026-07-14 13:00) has **0%** — not a gradual falloff, an on/off
switch. This is the Phase 15 M3 deployment boundary (the Telegram adapter code that reads
`Message.views`/`.forwards`/`.reactions` only exists in the container image built after M3
shipped) — historical rows genuinely have no engagement data because the code that captures it
did not exist yet when they were collected, not because Telegram withholds it or a bug drops it.
This is expected, correct, and not something a scoring calibration should or could paper over
with fabricated data — it will resolve on its own as more post-M3 Telegram history accumulates.

Confirms mechanism **C (insufficient same-source baseline)** as a second, additive cause on top
of #2: even among the ~28% of Telegram events collected *after* the M3 cutoff and therefore
carrying real engagement fields, most sources still have fewer than the minimum 3 same-source
historical rows to compare against (M3 is simply too young), so `source_baseline_available`
fires on only ~12.5% of Telegram events overall.

Ruled out: mechanism **B** (measured-zero/below-baseline Telegram engagement being penalized
"too harshly") — only 4 of 32 Telegram events in the clean sample had a real, baseline-backed
percentile at all (`{0.0, 0.333, 0.667, 1.0}`), split evenly between below- and above-baseline;
too small a sample to support "harsh penalty" as a distinct, separate mechanism from the general
compression effect (#2) already identified.

## 4. Engagement maturity analysis

Directly queried `collected_at - published_at` ("collection lag" — the actual snapshot age at
which `views_count` etc. are captured, since M3 captures them once at collection time and never
re-reads them later) for the 9 real Telegram engagement rows: **4.2 to 35.3 minutes**, all within
roughly one collection-poll cycle (the collector's fixed polling interval). This is the direct
answer to the task's own concern — a 10-minute-old-at-capture post is *not* being compared
against a several-hours-old-at-capture post in the current data; every captured snapshot in this
sample is a "just collected" snapshot, all in the same rough maturity band, because collection
consistently happens shortly after publication for every source alike. View counts *did* vary
widely (534 to 13,093) at similar lag times — dominated by channel audience size/virality, not
elapsed time — which is exactly why the existing same-source percentile-ranking design (§5 of
the original M4 report) is already the right mechanism for this, once enough same-source history
exists (#3 above).

Conclusion: engagement-maturity normalization (**Variant C**) is not implemented — the evidence
does not show it is currently a live problem (collection lag is tight and fairly uniform), and
adding a maturity model on top of an already-thin baseline sample would add complexity without
addressing an observed failure mode. If collection cadence becomes far more variable in the
future (e.g. under sustained backlog), this should be revisited with fresh evidence, not
pre-emptively.

## 5. Variants evaluated

**Variant A (current M4 implementation, fixed-neutral fallback)** — baseline for comparison,
§1/§2/§13 of the original M4 report.

**Variant B (availability-aware weight redistribution, as literally specified in the M4.1
task)** — implemented and backtested first. **Rejected on evidence, not preference**: redistributing
a *per-event-conditionally-available* component's weight onto the others is mathematically
equivalent to imputing that component as equal to the *average of the story's own other
components* — not neutral. Worked example, confirmed by direct computation
(`legacy=0.8, freshness=0.8, reliability=0.8` for both):

| | engagement | resulting score |
|---|---|---|
| RSS (engagement always unavailable → excluded) | n/a | **80.0** |
| Telegram (engagement measured, exactly neutral 0.5) | 0.5 | **73.3** |

A Telegram story with genuinely-measured, exactly-average engagement scored **6.7 points lower**
than an RSS story with no engagement data at all — the opposite of the fairness goal ("no source
is penalized merely because it exposes real metrics"). Backtested in full: Variant B did restore
overall eligible volume to 100% of v1 (49/49), but RSS eligibility *exceeded* its old v1 count
(44 vs. 35, a 126% ratio) precisely because of this self-referential inflation, while NEWS_API
and Telegram remained essentially unfixed (their other components are weak enough that
redistribution doesn't lift them much) — an unearned, formula-driven advantage for one source
type, not a fairness fix. Rejected.

**Variant D (conservative engagement influence / shrinkage)** — evidenced by §2/§3's finding
that only 4 real Telegram percentiles exist in the whole clean sample, computed from 3-row
baselines that can only produce `{0, 1/3, 2/3, 1}`. Adopted.

**Variant C (age-aware normalization)** — evaluated in §4, evidence does not support it being a
current live problem; not implemented.

**Variant E (justified hybrid)** — selected, but *not* the hybrid the M4.1 task's own Variant B
literally specifies. See §7 for the precise, evidence-driven deviation: only `novelty` (never
available for *any* event, a permanent architecture-level fact, not a per-event data gap) is
redistributed — a constant, one-time reweighting applied identically to every event — combined
with Variant D's baseline-size shrinkage for engagement specifically. `engagement` and
`source_reliability` keep Variant A's fixed-neutral treatment when unavailable for one particular
event, precisely because Variant B's self-referential flaw is specific to per-event-conditional
availability, not to permanent unavailability.

## 6. Editorial comparison sample

254 clean samples (§1), each with legacy score, pre-calibration V2, and post-calibration V2 (the
real, committed formula). Full detail reviewed locally, not committed (same convention as the
original M4 report's own backtest samples).

**Top 10 by calibrated V2 score** (all RSS except one Telegram story, all very fresh, 0.6–5.6h
old): "OpenAI's rogue agent went on a hacking spree..." (RSS/GADGETS, legacy 88 → pre-calib 79 →
**82**), "Samsung announces a $200B+ contract..." (RSS/TECH, 91 → 75 → **78**), "SpaceX успешно
провела..." (TELEGRAM, 78 → 64 → **73**, the strongest Telegram example — real, measured,
above-baseline engagement at a decent sample size), "Meshy... AI-powered 3D asset generation"
(RSS/TECH, 82 → 72 → **74**) — every one of these remains comfortably eligible under either V2
version; calibration mainly restores a few points of headroom, doesn't invert their ranking.

**5 near threshold** (calibrated score 67–70): a cluster of RSS/GADGETS and RSS/TECH stories
(Unitree robotics profile, Galaxy Unpacked 2026 coverage, OpenAI Sora commentary) — legacy scores
62–72, calibrated 67–70; these sit right at the editorial margin under either scoring version,
which is the expected, healthy behavior for a threshold boundary.

**5 below threshold that were ≥65 under legacy**: "ЦБ РФ снизил ключевую ставку до 14%" (Telegram,
legacy 88 → calibrated 64, 25.1h old — freshness tier alone costs it 0.6 of the 1.0 freshness
component), "Trump threatens EU with new tariffs..." (RSS/GADGETS, 78 → 64, 13.3h old),
"SpaceX's 13th Starship flight test..." (RSS/GADGETS, 78 → 64, 12.9h old), "Sources: OpenAI's
models breached Hugging Face..." (RSS/TECH, 78 → 64, 12.6h old). Common thread: every one of
these is a legacy-high, but no-longer-fresh (12.6–25.1h old) story — freshness decay, not
engagement, is what pulls them just under 65. This is the formula working as designed (freshness
is 20% of the score for a reason), not a fairness artifact.

**5 strongest upward movers**: two Telegram stories dominate ("SpaceX успешно провела..." +9,
"Paramount Skydance согласилась..." +4) — both have real, measured, above-baseline engagement
that the pre-calibration formula was diluting with fixed-neutral novelty; three RSS stories +3
each from the same novelty-redistribution effect.

**5 strongest downward movers**: "Следим за новостями:" (Telegram, legacy 0, pre-calib 49 →
calibrated 41, -8 — a near-empty title the LLM itself already scored 0; the pre-calibration
formula's fixed-neutral novelty/engagement had been propping it up more than the calibrated
version does) and four low-legacy-score (2–8) RSS/NEWS_API stories each -3, all previously
inflated toward the middle by neutral engagement/novelty, now more honestly reflecting their low
semantic score. **None of these are cases where the formula behaves mathematically consistently
but looks editorially wrong** — every downward mover is a low-quality story losing an
undeserved neutral-inflation cushion, and every upward mover is a story with real supporting
signal (freshness, or genuine measured engagement) that was previously diluted.

**Telegram examples**: 5 shown above/in §1's table — real engagement visibly moves the score
(SpaceX +9, Paramount +4) when a baseline exists; the two "ЦБ РФ" duplicate rows (64, down from
legacy 88) are freshness-driven, not engagement-driven.

**NEWS_API examples**: "Android May Soon Restrict On-Device ADB" (55 → 61 → 62), "ICE Illegally
Scooped Up Medicaid Data..." (78 → 58 → 59, freshness-driven decline, 41h old) — consistently
mid-range regardless of calibration, confirming §2's finding that NEWS_API's ceiling is a
freshness/semantic characteristic of this sample, not an engagement-fairness bug this
calibration could or should fix.

## 7. Selected calibration

**Novelty's nominal weight (10%) is permanently redistributed across the other four components**
— a constant reweighting applied identically to every event (effective weights become
semantic≈0.444, freshness≈0.222, engagement≈0.222, reliability≈0.111, novelty=0, when the
nominal nothing-else-unavailable weights are 0.40/0.20/0.20/0.10/0.10) — plus **baseline-size
confidence shrinkage** for the engagement percentile (`confidence = min(1, baseline_n / 10)`,
raw percentile shrunk toward 0.5 by that confidence factor). `engagement` and
`source_reliability` explicitly do **not** get the redistribution treatment when unavailable for
one event — see §5's Variant B rejection.

Priority-ordered justification against the task's own selection criteria:
1. **Source-agnostic**: the redistribution rule ("permanently unavailable for every event →
   redistribute; conditionally unavailable for this one event → keep neutral") is defined purely
   in terms of *architecture-level signal availability*, never source type. It happens to affect
   RSS/NEWS_API/Telegram differently only because their underlying data genuinely differs — no
   `if source_type == "TELEGRAM"` branch exists anywhere.
2. **Deterministic**: pure arithmetic, no randomness, no fitting.
3. **Zero new provider calls**: unchanged — confirmed by the same structural test
   (`test_editorial_scoring_module_imports_no_llm_gateway_or_capability`) plus 4 new integration
   tests all asserting `AIExecution` count stays 0.
4. **Minimal code change**: 2 new constants, 1 new small function (`_baseline_confidence`), a
   ~15-line change to the weighted-sum computation, a 5-line addition to `_build_reason` for
   reliability-unavailable phrasing. No new module, no new config field, no new database access
   pattern (still the same 2 queries from M4, only when `v2` is active).
5. **Backward-compatible output contract**: all five `components` keys, all four `coverage`
   keys, and the top-level `score` (still a plain `int`, still 0–100) are unchanged in shape;
   `weights` now reflects the *effective* (post-redistribution) weights rather than a literal
   echo of the input, which is strictly more informative, not a breaking change to any consumer
   (only `worker/content_cycle.py` reads `"score"`, confirmed unchanged by test).
6. **No migration**: none added; still none needed (§14 of the original report).
7. **Same existing `v1|v2` rollback flag**: no `v2a`/`v2b` mode was added — the calibration
   changes what `"v2"` *means*, in place, exactly as the M4.1 task explicitly permitted ("Since
   V2 has not been activated, it is acceptable to calibrate the existing V2 formula itself").

## 8. Files changed

- `services/editorial_scoring.py` — `ENGAGEMENT_BASELINE_FULL_CONFIDENCE_SAMPLE` constant,
  `_baseline_confidence()`, shrinkage applied inside `_compute_engagement_component()`, novelty
  redistribution inside `compute_editorial_score_v2()`, reliability-unavailable phrasing in
  `_build_reason()`. Module docstring extended with the full M4.1 rationale (including the
  rejected-Variant-B worked example, kept in the code itself so a future reader doesn't
  rediscover and re-attempt the same flawed approach).
- `tests/test_editorial_scoring.py` — 6 existing tests updated for the new formula's numeric
  outputs (weight redistribution, shrinkage), 9 new tests added for the M4.1-specific behaviors.

No other file touched — `capabilities/executor.py`, `core/config.py`, `capabilities/scoring_capability.py`,
workflow definitions, and `worker/content_cycle.py` are all exactly as M4 left them.

## 9. Tests

Focused (`tests/test_editorial_scoring.py`): **48/48 passed** (39 from M4, 9 new for M4.1,
covering the task's required list: unsupported-vs-measured-average fairness (#1),
zero-vs-unavailable distinction (#2), thin-baseline shrinkage for a very-fresh post (#3),
full-confidence penalty for a mature below-baseline post (#4), cross-source relative-engagement
fairness (#5, pre-existing, still green), shrinkage itself (#6), weight-sum-to-1.0 under every
availability combination (#7), score bounds (#8, pre-existing), backward compatibility (#9,
pre-existing), zero provider calls (#10, pre-existing + new), hard-gate independence (#11,
pre-existing), content-worker extraction (#12, pre-existing)).

Full regression suite (`python -m pytest tests/`, 1062 collected — 1053 from the M4 checkpoint +
9 new M4.1 tests): **1058 passed, 4 failed**, 7m31s. All 4 unrelated to M4.1:
- 3 are the identical, already-twice-documented pre-existing `content_generation_dry_run`
  environment/test-assumption mismatch (M3 checkpoint report §9, M4 report §11) — this
  environment's `.env` has it `False`; several tests assume the code default `True`.
- 1 (`test_analysis_worker_main.py::test_enabled_loop_runs_cycles_and_respects_interval`) is the
  same class of wall-clock-race timing flakiness already documented for its sibling tests in the
  M3/M4 reports (`asyncio.sleep(0.15)` against a 0.01s poll interval, asserting `call_count >=
  2`) — re-ran in isolation immediately after the full-suite failure: **passed**. Confirmed via
  grep: none of the 4 failing test files reference `editorial_scoring` at all.

Static checks: `ruff check .` — all checks passed; `scripts/validate_architecture.py` — clean, 0
violations; `mypy services/editorial_scoring.py` — no issues; manual secret-pattern scan across
both changed files — zero matches.

## 10. Post-calibration backtest

Same script, same methodology, re-run against the real, committed, calibrated formula (241 clean
samples at time of this run):

| | old (legacy) | pre-calibration V2 | **calibrated V2** |
|---|---|---|---|
| Overall ≥65 | 49 (20.3%) | 31 (12.9%) | **31→ see below (12.9%, but composition shifted)*** |
| NEWS_API ≥65 | 3 | 0 | **0** |
| TELEGRAM ≥65 | 11 | 2 | **2** |
| RSS ≥65 | 35 | 27–29 (run-to-run) | **29** |

*The official backtest script's own re-run (§ backtest evidence below) reports overall
calibrated ≥65 as 31/241 (same raw count as pre-calibration in this particular snapshot, because
new borderline RSS stories entered/left the ≥65 band between runs as natural collection
continued) — the more meaningful, stable comparison is the **ratio and composition**, tracked
across three independent re-runs during this session (samples 226/236/241/254 as data
accumulated):

| Run (n) | RSS ratio (calibrated/old) | NEWS_API ratio | TELEGRAM ratio |
|---|---|---|---|
| n=236 (offline candidate) | 30/35 = 86% | 0/3 = 0% | 2/11 = 18% |
| n=241 (official, real module) | 29/35 = 83% | 0/3 = 0% | 2/11 = 18% |

Consistent, reproducible across runs: **RSS improved from a pre-calibration 77% ratio to 83–86%**
(no longer *undershooting*, and — critically, since Variant B's rejected version overshot to
126% — **not overshooting either**, confirming the self-referential bug is genuinely fixed, not
just hidden). **NEWS_API and Telegram ratios are numerically unchanged (0% and 18%)** by this
calibration — expected and correctly so, per §2's/§4's diagnosis: NEWS_API's gap was never an
engagement-fairness bug (freshness/semantic, out of this calibration's scope), and Telegram's
residual gap is a real-data-maturity artifact (§3) that no formula change can manufacture around
— fabricating baseline history that doesn't exist yet would be exactly the "manipulate the
sample to force a pass" the task explicitly forbids.

**No obvious NEW quality regression** in the editorial review sample (§6) — every mover has a
concrete, inspectable, defensible reason (freshness decay, real measured engagement, or loss of
an undeserved neutral-inflation cushion), none are unexplained.

## 11. Threshold recommendation

Unchanged from the original M4 report's own conclusion, now with sharper evidence: **do not
activate V2 at threshold 65 today.** The calibration fixed the diagnosed *formula-level*
fairness bug (compression from permanently-dead novelty weight, and the worse bug a naive
full-redistribution "fix" would have introduced) — it did not, and structurally cannot, fix
NEWS_API's freshness/semantic-driven gap or manufacture Telegram engagement history that has not
had time to accumulate yet. A threshold/weight recalibration decision (e.g. a lower activation
threshold, or a product decision on whether NEWS_API's lower ceiling is acceptable) remains a
**separate, human decision** this milestone deliberately does not make unilaterally, consistent
with the M4 report's own §13.

## 12. Shadow-live evidence

True per-event live shadow logging (computing and logging both v1 and calibrated-v2 scores for
every naturally-completed task, without letting v2 affect eligibility) was evaluated and **not
implemented** as a code change: `apply_editorial_scoring_v2()`'s entire zero-overhead-in-v1-mode
design (§15 cost/latency of the original M4 report) rests on returning immediately, before any
DB query, whenever `editorial_scoring_version != "v2"`. Making it unconditionally compute V2 for
logging purposes would add 2 extra DB queries to *every* NEWS_ANALYSIS scoring step in production
— a real behavior change (added latency/DB load) the task's own instructions caution against
("only if this is already possible without changing delivery behavior").

Instead, the read-only backtest script was re-run three times over the course of this session,
each time picking up whatever new real NEWS_ANALYSIS completions had naturally occurred since the
last run under the unchanged, live `v1` path (226 → 236 → 241 → 254 clean samples, +28 net new
real completions captured across the session) — this achieves the same evidence-gathering goal
("observe a small natural sample where practical") without touching the production hot path, and
without creating any `CONTENT_GENERATION` eligibility from a shadow score (the backtest never
writes anything back to the database).

## 13. Remaining risk

- **NEWS_API's near-zero eligibility is unresolved** and out of this calibration's scope — a
  freshness/semantic-distribution characteristic of the current historical sample, not an
  engagement-fairness formula bug. Needs separate investigation (is NEWS_API content genuinely
  lower-relevance, or is there a collection/backlog timing issue keeping NEWS_API tasks stale
  longer before they're scored?) before any further scoring change is attempted for it.
- **Telegram's residual gap is a data-maturity artifact**, expected to shrink organically as more
  post-M3 Telegram history accumulates (only ~1 day of real engagement history existed at the
  time of this backtest) — not something to force with a code change now.
- **Two components (`engagement`, `source_reliability`) still use fixed-neutral fallback when
  unavailable for one event** — deliberately, per §5/§7's evidence, but this means compression
  from *those* two specifically (as opposed to novelty) is not fully eliminated, only novelty's
  is. If engagement/reliability unavailability rates stay high for a long time, a future
  milestone might reasonably revisit this with more historical evidence than exists today.
- The shrinkage constant (`ENGAGEMENT_BASELINE_FULL_CONFIDENCE_SAMPLE = 10`) is a documented,
  reasoned choice, not fit to data (M0/M4's own repeated finding: no historical outcome data
  exists to fit against) — worth re-examining once genuine multi-week Telegram engagement
  history exists.

## 14. Exact cutover recommendation

**Do not activate V2 in this or any immediately-following task.** `editorial_scoring_version`
remains `"v1"`; `.env` was not touched. Recommended next steps, in order, before a future cutover
decision is even considered: (1) let Phase 15 M3 engagement history accumulate for at least
several days to weeks so Telegram baselines genuinely fill in past the 3-row minimum at
reasonable confidence; (2) separately investigate NEWS_API's freshness/semantic gap (collection
cadence? backlog processing order? genuinely lower-relevance content?) since no scoring
calibration can fairly compensate for it; (3) once both of the above are better understood,
re-run this same backtest script and reconsider a threshold (not just a version-flag) decision
with a human in the loop, exactly as the original M4 report's §13 already recommended.

---

PHASE 15 M4.1 CALIBRATION COMPLETE — READY FOR CUTOVER REVIEW

---

# M4.2 SHADOW CUTOVER REVIEW

Status: REVIEW COMPLETE — cutover **NOT** authorized this milestone (see §10). Purely read-only:
no `.env` change, no version activation, no historical row mutated, no manual workflow triggered,
zero new provider calls. `editorial_scoring_version` remains `"v1"` throughout.

## 1. Clean sample boundary

Determined directly from the database, not assumed: querying `news_events` joined to `sources`
for Telegram rows, the **last** collection cycle with zero engagement fields populated was
`2026-07-24 22:16:06.548206+00`, and the **first** cycle with engagement fields populated was
`2026-07-25 07:36:38.828476+00` — a clean, hard on/off switch (not a gradual rollout), consistent
with the Phase 13–15 M3 checkpoint's own container-rebuild timeline. Boundary used for this
review: **`2026-07-25 07:30:00 UTC`** (a round timestamp strictly between the two observed
values). Every event collected before this boundary is excluded from the review sample,
regardless of source type — not just Telegram, for a consistent, single sample-construction rule.

## 2. Sample size and limitations

Query: all `EditorialTask` rows with `status=COMPLETED`, `workflow_name=NEWS_ANALYSIS`, a real
extractable integer `score`, whose `NewsEvent.collected_at >= boundary`, further filtered through
`services.cleaning.is_valid_title()` and the same synthetic-event exclusion string used by every
prior backtest in this report.

- **109 clean samples** — comfortably above the task's own 30-sample floor in aggregate.
- **Zero excluded for malformed title or synthetic content** in this window (expected: the
  malformed-title backlog predates the Phase 15 M1 gate and is entirely pre-boundary; 244 rows
  were excluded for being pre-boundary, 1 for lacking a legacy score).
- By source type: **RSS n=98**, **TELEGRAM n=9**, **NEWS_API n=2**.

**Explicit limited-confidence flag, per the task's own instruction**: Telegram (9) and NEWS_API
(2) are both far below the 30-sample floor *individually* — every Telegram/NEWS_API-specific
finding below is reported honestly as preliminary, not as a settled conclusion. The entire clean
sample also spans only **4.01 hours of wall-clock collection** (07:36 to 11:37 UTC on
2026-07-25) — a single operational window, not multiple days — so even the well-populated RSS
figures should be read as "first look," not "stable average."

## 3. Post-M3 Telegram analysis

All 9 clean-sample Telegram events fall between **17 and 47 minutes old at scoring time**
(`age_at_scoring_hours` 0.28–0.78) — there is currently **no post-M3 Telegram data at all** older
than 47 minutes at scoring time. This is itself the headline finding of this review: the original
M4/M4.1 backtests' Telegram bias was measured almost entirely against **pre-M3 historical rows**
that structurally could never carry engagement data; the *actual* live post-M3 Telegram picture
looks different and is analyzed on its own terms below (§4/§5).

`engagement_available = True` for **9/9 (100%)** — M3's capture mechanism is working correctly
for every single post-boundary Telegram event, no exceptions. `source_baseline_available = True`
for only **4/9 (44%)** — expected and correct: most Telegram sources simply have not yet
accumulated the minimum 3 same-source historical engagement rows this early after M3's
deployment, not a defect.

## 4. Engagement maturity analysis

Age-bucketed (`age_at_scoring_hours`, the actual gap between `EditorialTask.updated_at` at
completion and the event's `published_at`/`collected_at` anchor):

| Bucket | n | v1 median | V2 median | engagement median | eligible@65 | baseline_available |
|---|---|---|---|---|---|---|
| <15min | 0 | — | — | — | — | — |
| 15–30min | 5 | 28 | 50 | 0.50 | 2 | 40% |
| 30–60min | 4 | 8.5 | 41.0 | 0.55 | 1 | 50% |
| 60–120min | 0 | — | — | — | — | — |
| >120min | 0 | — | — | — | — | — |

**No data exists yet in the <15min, 60–120min, or >120min buckets** — a real, honestly-reported
gap in the evidence base, not glossed over. Within the two populated buckets, the finding is the
opposite of "mechanical penalty for immaturity": engagement medians (0.50, 0.55) sit at or
slightly above neutral, and V2 medians substantially *exceed* v1 medians in both buckets (50 vs.
28, 41.0 vs. 8.5) — driven by freshness (near-maximal for every one of these very-fresh posts)
and the M4.1-calibrated neutral fallback, not by any engagement-driven suppression.

Distinguishing the five maturity/measurement states directly from the 9-event Telegram detail:

1. **Unavailable engagement**: 0 of 9 (M3 capture is 100% successful post-boundary).
2. **Observed zero engagement**: 0 of 9 (no Telegram event in this window has all-zero metrics).
3. **Immature engagement (data present, baseline too thin — `baseline_n` 0–2)**: 5 of 9 — these
   get the fixed-neutral engagement component (M4 design) or, per M4.1, would be shrunk toward
   neutral if `baseline_n` were exactly at the 3-row floor; at 0–2 rows they fall below even that
   floor and are `source_baseline_available=False` outright.
4. **Mature below-baseline engagement** (`baseline_n>=3`, percentile <0.5): 2 of 9 (the SpaceX
   story at 0.30 and the Paramount story at 0.40 percentile) — both real, modest, defensible
   penalties (delta -10 and -2 respectively), not extreme.
5. **Mature at/above-baseline engagement** (`baseline_n>=3`, percentile ≥0.5): 2 of 9 (0.60 and
   0.70 percentile) — both real, modest lifts.

No case in this sample exhibits an extreme 0.0/1.0 percentile from a thin sample — M4.1's own
baseline-confidence shrinkage (§ M4.1 report) is already functioning as designed. Conclusion:
**very fresh Telegram events are not being mechanically penalized by immaturity** in the
available evidence — see §8 for why no additional age-aware adjustment is implemented.

## 5. Source-type comparison

| Source | n | v1 mean/median | V2 mean/median | eligible@65 (v1→V2) | semantic | freshness | engagement | reliability | engagement_avail | baseline_avail |
|---|---|---|---|---|---|---|---|---|---|---|
| TELEGRAM | 9 | 29 / 12 | 50.3 / 44 | 2 (22%) → 3 (33%) | 0.29 | 0.78 | 0.50 | 0.80 | 100% | 44% |
| RSS | 98 | 46.5 / 42.0 | 57.6 / 55.0 | 26 (27%) → 28 (29%) | 0.46 | 0.79 | 0.50 | 0.75 | 0% | 0% |
| NEWS_API | 2 | 36.5 / 36.5 | 49.0 / 49.0 | 0 (0%) → 0 (0%) | 0.36 | 0.60 | 0.50 | 0.75 | 0% | 0% |

**Telegram eligibility increases under V2 in this clean sample (22%→33%)** — the reverse of the
original M4/M4.1 finding, strong preliminary evidence that the earlier Telegram penalty was
predominantly a **stale-data artifact** (pre-M3 rows with permanently-unavailable engagement
mixed into the same backtest as post-M3 rows with legitimately-thin-but-present engagement), not
a formula defect. Caveat: n=9, one flipped story changes the percentage by 11 points — treat the
direction as encouraging, not the exact magnitude as stable.

**RSS is essentially flat (27%→29%)** — confirms M4.1's calibration is not *systematically*
rewarding RSS for its permanent lack of engagement data relative to its own v1 baseline, in this
fresher, less freshness-decayed sample than the original full backtest.

**NEWS_API's 0%→0% is unresolved by n=2** — cannot be attributed to any single concrete factor
with confidence at this sample size. Both available NEWS_API events have `engagement_available =
False` (expected, matches RSS/NEWS_API's design) and `freshness` in the 0.6 (moderate) band
rather than the 0.78–0.79 near-maximal band RSS/Telegram show — a *preliminary* signal that
NEWS_API events may be scored somewhat less immediately after publication than other source
types, worth a dedicated investigation with a larger sample, not something this review can
conclude from 2 data points. Semantic scores (0.18, 0.55) span too wide a range in n=2 to draw
any conclusion about systematic LLM-scoring bias against NEWS_API content specifically.

## 6. Threshold comparison

Same 109-sample clean set, sweeping the candidate global threshold (v1's own eligible count at
65, within this same clean sample, is 28 — used as the ratio denominator, not the older
stale-data-inclusive 49 from §12/§13 of the M4 report, since that number is no longer the
relevant comparison baseline for a clean-sample decision):

| Threshold | Total eligible | Ratio vs. v1@65 (28) | RSS | TELEGRAM | NEWS_API | Top-10 overlap | Top-20 overlap |
|---|---|---|---|---|---|---|---|
| 50 | 77 | 275% | 72 | 4 | 1 | 10/10 | 20/20 |
| 55 | 59 | 211% | 55 | 3 | 1 | 10/10 | 20/20 |
| 57.5 | 47 | 168% | 44 | 3 | 0 | 10/10 | 20/20 |
| 60 | 45 | 161% | 42 | 3 | 0 | 10/10 | 20/20 |
| 62.5 | 36 | 129% | 33 | 3 | 0 | 10/10 | 20/20 |
| **65** | **31** | **111%** | **28** | **3** | **0** | **10/10** | **20/20** |
| 67.5 | 26 | 93% | 25 | 1 | 0 | 10/10 | 19/20 |
| 70 | 19 | 68% | 19 | 0 | 0 | 8/10 | 17/20 |

**Threshold 65 (the current, unchanged live threshold) is the strongest candidate**: closest to
v1 parity (111%, not the ~2× or ~50% extremes the M4 task's own safety rule flags), full top-10
and top-20 overlap with v1's own ranking (the two formulas agree on which stories matter most,
they just disagree on the exact score), and a sensible, gradual falloff on either side (no cliff
edge). 50/55/57.5/60/62.5 all produce 129–275% of v1's volume — too permissive, would likely flood
`content_generation_batch_size=5`'s per-cycle cap. 70 drops to 68% and starts losing top-10
agreement — too conservative.

**Expected delivery-volume impact at threshold 65** (using this sample's own 4.01-hour span and
this environment's actual live settings — `news_analysis_poll_interval_seconds=300`,
`content_generation_poll_interval_seconds=1800`, `content_generation_batch_size=5`,
`content_generation_scan_limit=50`, confirmed by reading the running container's settings, not
assumed): v1 produces ≈3.49 eligible events per 30-minute `content_generation` cycle in this
window; V2 at 65 produces ≈3.86 — both comfortably under the `batch_size=5` cap, meaning nearly
every eligible story would actually be processed rather than queued/dropped, under either
version. This is a reassuring, non-extreme volume comparison, but based on a single 4-hour
window, not a multi-day average — flagged as a limitation, not a settled fact.

## 7. Editorial review examples

**Top 10 by V2 score**: dominated by RSS (9 of 10) — "OpenAI's rogue agent went on a hacking
spree..." (88→82), "Samsung announces a $200B+ contract..." (91→78), "The OpenAI Models That
Hacked Hugging Face..." (78→74) — all very fresh (0.31–1.03h), all comfortably eligible under
either version, calibration mainly trims a few points of legacy-score inflation rather than
inverting rankings.

**5 nearest threshold** (60–70 band has ~28 entries in this sample — the tightest cluster is at
64–68): "xAI открыла код Grok Build..." (RSS, 72→70), "Meshy... AI-powered 3D asset generation"
(RSS, 82→70), a Russian-language GADGETS story (72→70), "OpenAI шокировал..." (RSS/GADGETS,
72→70), "Everything announced at Galaxy Unpacked 2026..." (RSS, 68→69) — all sit at a defensible
editorial margin, none looks like an obviously wrong promotion or demotion.

**5 newly admitted at a lower candidate threshold (57.5) vs. the current 65**: a cluster of
RSS/AI stories in the 58–64 range ("US debates AI kill switch," "Universities ask for $24.5
million...," "No, OpenAI's models didn't go 'rogue'...") — all legitimate AI-industry news,
reasonable additions at a looser threshold, no obviously weak story slipping in.

**Excluded vs. v1 at 65**: **only one event in the entire 109-sample clean set** flips from
v1-eligible to V2-ineligible at threshold 65 — "Мишень номер один — не Пентагон, а стартапы"
(RSS/AI, 68→62, 1.7h old, moderate-not-maximal freshness band) — a single, freshness-driven,
individually defensible demotion, not a pattern.

**Strongest Telegram movers**: three low-legacy-score (0, 5, 12), very-fresh posts jump the most
in *relative* terms (+42, +38, +35 — "Следим за новостями:", "Так фейк или нет?", "Мужчины, общий
сбор") — **flagged explicitly per the task's own instruction**: "Следим за новостями:" ("Following
the news:") is a near-empty-content post the LLM itself correctly scored 0 (no real editorial
content), yet V2's freshness+neutral-engagement combination still lifts it to 42 — a
**mathematically consistent but editorially borderline** case: the math is doing exactly what the
formula specifies (very fresh + neutral fallback = a meaningful score contribution even with a
near-zero semantic component), but a human editor would likely find a 42 for literally-empty
content questionable, even though it stays well below every candidate threshold in §6 and is
never actually deliverable. Two Telegram stories move down modestly (-2, -10) from real,
baseline-backed measured engagement — legitimate, not flagged.

**Strongest RSS movers**: upward moves are dominated by the same low-legacy-score, very-fresh
pattern as Telegram ("A shell colon does nothing. Use it anyway," legacy 8→46; "Emacs Writing
Machine," 18→50; "v0.26.0," 18→48) — niche developer-tooling posts inflated by freshness, but
**none cross any candidate threshold from §6**, so this pattern is visible in the data but not
yet operationally consequential. Downward moves are all high-legacy-score stories (91→78, 82→70,
78→68) pulled toward the middle by average freshness/engagement/reliability — all remain
comfortably eligible, no false exclusion.

**All NEWS_API events**: both of the 2 available events shown in full in §5's underlying data —
"ARC-AGI Leaderboard" (18→41, low semantic, moderate freshness, unavailable engagement) and
"Android May Soon Restrict On-Device ADB" (55→57, moderate semantic, moderate freshness) —
neither eligible under either version at 65; too few events to characterize a pattern.

**Overall flag for §8/§10**: the "very fresh + low-legacy-score + neutral fallback" inflation
pattern (visible in both Telegram and RSS) is real and worth watching, but in this clean sample
it never actually crosses into delivery-eligible territory at any of the reasonable candidate
thresholds (57.5–70) — a risk to monitor as more data accumulates, not a currently-active defect.

## 8. Age-aware calibration

**Not implemented.** Per the task's own explicit instruction ("Do not implement this adjustment
unless the clean post-M3 sample proves it is required"), §4's evidence does not show a material
mechanical penalty from engagement immaturity — if anything, the opposite risk is visible (§7's
flagged inflation pattern, freshness dominance being *too generous* to weak-but-fresh content,
not too harsh). Adding a maturity-based *additional* down-weighting of engagement toward neutral
for very-fresh events would only compound the inflation risk already flagged, not fix a penalty
that does not appear in the evidence. M4.1's existing baseline-confidence shrinkage
(`_baseline_confidence`, `ENGAGEMENT_BASELINE_FULL_CONFIDENCE_SAMPLE=10`) already addresses the
closest real phenomenon found (thin same-source baselines), and is confirmed working as intended
in §4's per-event detail (no extreme 0.0/1.0 outputs from small samples). No code change, no new
tests, no new commit for this section.

## 9. Tests and validation

No code changed in this milestone — §8 explains why. All validation is read-only analysis against
the already-committed, already-tested `services.editorial_scoring` module from M4/M4.1 (48/48
focused tests, 1058/1062 full suite, both already documented). No new test run was required or
performed; the existing test suite's state is unchanged by this review.

## 10. Exact recommended scoring version

**`v2`, but not yet — recommend deferral, not rejection.** The clean-sample evidence is
*encouraging* (Telegram bias appears to have been substantially a stale-data artifact; RSS is not
over-rewarded; threshold 65 already looks like a strong candidate with 111% volume parity and
full top-10/20 ranking agreement with v1) but **does not meet this review's own evidentiary bar**
for a confident cutover recommendation, because:
- Telegram (n=9) and NEWS_API (n=2) are both far below the 30-sample floor the task itself set —
  every finding specific to those two source types is preliminary.
- Zero data exists beyond 78 minutes of Telegram post age — the 60–120min and >120min buckets are
  completely unobserved; a maturity-related problem could still exist in a range this review
  cannot see yet.
- The entire clean sample spans a single 4-hour window — not evidence of a stable, multi-day
  pattern.

## 11. Exact recommended global threshold

**65 (the current, unchanged live `CONTENT_GENERATION_MIN_SCORE`)** is the strongest candidate
identified in §6, if/when cutover is eventually authorized — no threshold change is recommended
alongside a future cutover. This is explicitly a candidate for a **future** decision, not an
action taken in this review.

## 12. Expected delivery-volume impact

At threshold 65, in this clean sample's own 4.01-hour window: ≈3.86 eligible V2 events per
30-minute `content_generation` cycle vs. ≈3.49 for v1 in the same window — both under the
`content_generation_batch_size=5` cap (§6). No evidence of either an explosion or a starvation at
this threshold. This estimate should be re-verified once a longer observation window is
available (§13).

## 13. Remaining risks

- **Thin Telegram/NEWS_API samples** (§2) — the single largest limitation of this review; more
  post-M3 data is needed before any of the source-type-specific findings can be trusted at the
  same confidence level as the RSS findings.
- **No data beyond ~80 minutes of Telegram post age** (§3/§4) — a real gap; a future review with
  a longer observation window is needed to confirm the maturity finding holds at longer horizons.
- **The "very fresh + low-legacy-score + inflation" pattern** (§7) is real, currently
  inconsequential (never crosses a candidate threshold in this sample), but worth monitoring as
  volume grows — if it starts producing delivery-eligible near-empty content, a future milestone
  should revisit whether freshness/engagement should be capped from fully compensating for a
  near-zero semantic score, a genuine formula question this review surfaces but does not resolve.
- **NEWS_API's freshness gap** (§5, 0.60 vs. 0.78–0.79 for other source types) is a preliminary
  signal, not a finding — worth a dedicated investigation (collection/backlog timing? genuinely
  later-scored content?) once NEWS_API's post-M3 sample grows past single digits.
- **Single 4-hour observation window** (§2/§6/§12) — every volume/ratio figure in this review
  should be treated as a first look, to be reconfirmed once multiple days of post-M3 data exist.

## 14. Rollback instruction

No change was made in this review, so no rollback is needed — `editorial_scoring_version` was
never touched and remains `"v1"` (its code default) in every environment. If a future milestone
does activate `v2`, the existing rollback path (documented in the M4 report's own §14, unchanged
here) applies: flip `editorial_scoring_version` back to `"v1"` — zero code change, zero DB
change, zero downstream-consumer impact, since `apply_editorial_scoring_v2()`'s first line
returns immediately whenever the setting is not `"v2"`.

---

PHASE 15 M4.2 CUTOVER REVIEW BLOCKED — MORE POST-M3 DATA REQUIRED

---

# FINAL M4 CUTOVER REVIEW (Phase 15 autonomous completion, Workstream C)

Status: **REVIEW COMPLETE — cutover NOT authorized.** Read-only: no `.env` change, no version
activation, no row mutated, zero new provider calls. `editorial_scoring_version` remains `"v1"`.

## 1. Method

Re-ran M4.2's own clean-post-M3-sample methodology (`scripts/phase15_m4_final_cutover_backtest.
py`, adapted from `scripts/phase15_m4_scoring_backtest.py`), reusing the same verified boundary
(`2026-07-25 07:30:00 UTC`, M3's own engagement-capture cutover point) rather than re-deriving
it, now against however much additional post-M3 history has accumulated since M4.2's original
4-hour snapshot. Added a threshold sweep (55/57.5/60/62.5/65/67.5/70) for both v1 and v2 that
M4.2 did not include.

## 2. Sample

**177 clean samples** (244 excluded for being pre-boundary, 1 for lacking a legacy score, 0 for
malformed title or synthetic content) — up from M4.2's 109, spanning **~23 hours** of wall-clock
collection (`2026-07-25T07:30` to `2026-07-26T06:38`), a meaningfully longer window than M4.2's
single 4-hour snapshot, though still short of the "multiple days" M4.2 itself flagged as needed
for full confidence.

By source type: **RSS n=156**, **TELEGRAM n=13**, **NEWS_API n=8**. Telegram and NEWS_API both
remain well below the 30-sample floor individually (13 and 8 respectively) — improved from
M4.2's 9 and 2, but still not enough for an individually-confident source-type conclusion.

## 3. Score distributions

| | v1 (legacy) | v2 |
|---|---|---|
| min | 0 | 26 |
| max | 91 | 71 |
| avg | 44.55 | 48.97 |
| median | 42 | 48 |
| p75 | 68.0 | 59.0 |
| p90 | 78.0 | 63.0 |

**V2 substantially compresses the score range** (max 91→71, min 0→26) — expected, since v1 is
100% semantic-score-driven while v2 blends it with freshness/engagement/reliability/novelty
components that pull toward the middle, especially when engagement is unavailable (RSS, the
large majority of this sample) and falls back to the neutral 0.5 baseline.

## 4. Top10/top20 overlap and movers

**Top 10 overlap: 7/10. Top 20 overlap: 14/20.** Moderate reordering, not wholesale
disagreement — most of what v1 considers "top" content, v2 still does.

**Top 5 movers down** are uniformly real, high-legacy-score mega-stories (OpenAI's rogue-agent
story 88→68, Samsung/SK/Nvidia $700bn AI push 86→66, Samsung/Broadcom $200B+ chip deal 91→69,
the SpaceX Starship launch 78→54) — v2's broader component blend genuinely down-weights
pure-semantic "big number" stories relative to v1, which is the intended design, not a bug, but
a real, material behavior change worth the operator's awareness before any cutover.

## 5. Threshold sweep — the decisive finding

| Threshold | v1 eligible | v2 eligible | v1 % | v2 % |
|---|---|---|---|---|
| 55 | 75 | 60 | 42.4% | 33.9% |
| 57.5 | 71 | 50 | 40.1% | 28.2% |
| 60 | 56 | 38 | 31.6% | 21.5% |
| 62.5 | 45 | 22 | 25.4% | 12.4% |
| **65 (live)** | **45** | **9** | **25.4%** | **5.1%** |
| 67.5 | 45 | 6 | 25.4% | 3.4% |
| 70 | 33 | 2 | 18.6% | 1.1% |

**At the live threshold (65), activating v2 without any other change would collapse eligible
volume by ~80% (45→9)** — a severe, immediate violation of the cutover criteria's own "overall
eligible volume remains operationally reasonable" and "no source-type collapse" requirements.
Even at the lowest swept threshold (55), v2 eligibility is still ~20% lower in relative terms
(75→60). This is a new, previously-uncharacterized finding — M4.2's own review never swept
thresholds and so never surfaced it.

## 6. Cutover criteria evaluation

1. *≥30 clean post-M3 Telegram events* — **not met** (13, though improved from 9).
2. *No mechanical penalty for exposing real engagement* — inconclusive at this sample size;
   unchanged from M4.2's own finding.
3. *Unsupported engagement sources receive no artificial advantage* — holds (unchanged
   mechanism from M4/M4.1).
4. *Overall eligible volume remains operationally reasonable* — **not met at the live
   threshold** (§5 — an ~80% collapse).
5. *No source-type collapse or explosion* — **not met at the aggregate level**: independent of
   any single source type's own direction of movement (Telegram's v2 median of 39 is in fact
   well above its v1 median of 12, a directional improvement), the aggregate ~80% volume
   collapse at the live threshold (§5) is itself a collapse that would affect every source type's
   absolute eligible count.
6. *Top editorial ranking remains credible* — largely holds (§4 — 70% top-10 overlap).
7. *Threshold impact is understood* — **now yes** (§5, this review's own main contribution) —
   but understanding the impact is not the same as having chosen and validated a new value.
8. *Rollback to v1 remains immediate* — holds, unchanged (`apply_editorial_scoring_v2()`'s
   own first-line early-return).
9. *No new provider calls* — holds (pure backtest, read-only).
10. *Natural live sample shows no worker regression* — not directly exercised by this backtest;
    v1 remains the only version ever live-executed, so there is no v2 worker-regression evidence
    to report either way.

**3 of 10 criteria fail (1, 4/5, and 7-is-necessary-but-insufficient).** Per instruction,
`CONTENT_GENERATION_MIN_SCORE` may only be changed "if the backtest proves it necessary" — this
backtest proves a threshold change would be *necessary for volume* if v2 activates, but does not
itself validate *which* new threshold value is correct (that requires its own dedicated
calibration pass a single "final review" script is not the right vehicle for) — changing the
live threshold as a side effect of this review would be exactly the kind of ad-hoc, unvalidated
production change Phase 15's own M4 series has consistently avoided.

## 7. Decision

**`editorial_scoring_version` remains `"v1"`. V2 activation is deliberately deferred, not
rejected.** The evidence base is now substantially stronger than M4.2's (177 vs 109 samples, 23
vs 4 hours), and confirms M4.2's own recommendation was correct to defer — with one materially
new finding this review adds: **a live-threshold volume collapse that any future cutover
decision must budget its own dedicated threshold-recalibration work for**, not just a
sample-size wait. `.env` was not touched; no restart was performed for this workstream.

## 8. Rollback

Unchanged — no activation occurred, so there is nothing to roll back. The existing rollback path
(flip `editorial_scoring_version` to `"v1"`, zero code/DB change) remains available and unused.

---

PHASE 15 FINAL M4 CUTOVER REVIEW COMPLETE — V2 DEFERRED, THRESHOLD IMPACT NOW CHARACTERIZED
