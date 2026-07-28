# API Cost Audit Report — Most Recent 3-Day Period (2026-07-23 → 2026-07-26)

Status: **AUDIT COMPLETE, WITH AN EXPLICIT DATA-AVAILABILITY LIMITATION STATED UP FRONT.**
Read-only. No row mutated, no manual generation triggered, no live provider testing beyond
what Step 2 explicitly separately authorizes.

---

## 0. Critical limitation — no historical per-call cost data exists

Before any attribution: **this codebase currently records zero real per-call cost data
anywhere.** Verified directly, not assumed:

- `ai_executions` (the `AIExecution` table, which has exactly the right schema — `task_id`,
  `capability`, `model`, `input_tokens`, `output_tokens`, `cost`) — **0 rows**. Confirmed via
  `SELECT count(*) FROM ai_executions`.
- `RedisCostTracker` (`services/cost_tracker.py`) writes a daily Redis ledger
  (`phase7:cost_ledger:{date}` + a per-capability variant) — **`KEYS "phase7:cost_ledger:*"`
  returns zero keys.**
- Root cause, confirmed by direct inspection: `integrations/llm_gateway/gateway.py`'s own
  docstring states plainly *"CostTracker.record() is deliberately NOT called by this class."*
  `CostTracker` is fully implemented and tested in isolation but **never wired into the real
  call path** — a pre-existing architectural gap, not something this task's own changes caused.
- `WorkflowStepResult` (what actually gets persisted per step in `EditorialTask.workflow`) has
  no `model`/`usage`/`cost` field at all — only `step_name`/`status`/`attempt`/timestamps/`error`.
- Worker container logs (`docker logs`) do not persist across a container recreation — the
  `news_analysis_worker`/`content_worker` containers were both recreated during the immediately
  preceding Phase 15 closure task, so **all pre-recreation stdout logs, which would have covered
  most of this 3-day window, are gone.** The `latency` log line that does survive per-call
  (`integrations/llm_gateway/providers/openai_adapter.py`) records `provider_id`/`model_id`/
  `attempt_latency_ms` only — never token counts.

**Consequence**: an exact, row-by-row reconstruction of the historical $9 is not possible from
persisted data. Everything below is either (a) a reliable count from durable Postgres data, (b)
a fact derived directly from the current, unmodified routing/pricing code (not a guess — the
routing logic is deterministic and unchanged since these 3 days), or (c) an explicitly-labeled
proportional estimate built from (a) and (b). Nothing here is presented as more precise than it
is.

## 1. Reliable data: task volume (Postgres, durable, exact)

```
day          workflow             status      count
2026-07-23   NEWS_ANALYSIS        COMPLETED   138
2026-07-23   NEWS_ANALYSIS        CREATED     2114
2026-07-23   CONTENT_GENERATION   COMPLETED   6
2026-07-24   NEWS_ANALYSIS        COMPLETED   102
2026-07-24   NEWS_ANALYSIS        FAILED      25
2026-07-24   NEWS_ANALYSIS        CREATED     950
2026-07-24   CONTENT_GENERATION   FAILED      5
2026-07-25   NEWS_ANALYSIS        COMPLETED   181
2026-07-25   NEWS_ANALYSIS        FAILED      128
2026-07-25   NEWS_ANALYSIS        CREATED     190
2026-07-25   CONTENT_GENERATION   COMPLETED   20
2026-07-25   CONTENT_GENERATION   FAILED      34
2026-07-26   NEWS_ANALYSIS        FAILED      75   (partial day, ~7h)
2026-07-26   NEWS_ANALYSIS        CREATED     31
```

**3-day totals: NEWS_ANALYSIS 421 COMPLETED, 228 FAILED, 3285 CREATED-but-never-run.
CONTENT_GENERATION 26 COMPLETED, 39 FAILED.**

**Critical timing fact** (already established in the immediately preceding Phase 15 closure
task, re-confirmed here): the OpenAI account began returning `insufficient_quota` (HTTP 429,
billing/plan, not code) on **every** request starting `2026-07-25 22:04:46 UTC` and remains in
that state as of this audit. This single fact explains the bulk of the FAILED spike on
2026-07-25/26 (162 of 267 total FAILED tasks fall on or after that day) and the **zero**
completions on 2026-07-26. A rejected-for-quota request is not billed by OpenAI (no tokens are
processed), so these FAILED tasks are treated below as **~$0 cost**, not zero call *volume* but
effectively zero call *cost* — an assumption, stated explicitly, not verified against a provider
invoice line.

The 3285 (+3130 more, older than 3 days — 6415 total) never-run `CREATED` `NEWS_ANALYSIS` tasks
cost **exactly $0** (zero LLM calls made) — a large processing backlog, not a cost driver. It is
a symptom of the same recurring provider-availability instability Phase 15's own runtime
reliability report already documents, not a new finding.

## 2. Reliable data: real workflow step sequences (code, not assumed)

Confirmed directly from `workflows/definitions/*.py` (not the "Quality" 4th step this task's own
prompt assumed — the real step is **Scoring**):

- `NEWS_ANALYSIS`: **research → intelligence → engagement → scoring** (4 real LLM-calling steps)
- `CONTENT_GENERATION`: **research → intelligence → copywriting → quality** (4 real LLM-calling steps)

A story that reaches delivery therefore uses up to **8** provider calls (4 + 4), confirming the
task's own framing, just with the corrected 4th `NEWS_ANALYSIS` step name.

**Estimated successful-step call volume**: `421 × 4 = 1684` (NEWS_ANALYSIS) + `26 × 4 = 104`
(CONTENT_GENERATION) = **1788 successful calls** over the 3-day window (excludes same-candidate
retries within a successful call, which the current schema also does not record).

## 3. Reliable data: routing is 100% uniform, and GPT-5.6 Sol is structurally excluded already

Verified directly from the unmodified routing code (`integrations/llm_gateway/gateway.py::
_build_routing_criteria()`, `integrations/llm_gateway/routing/criteria.py`,
`integrations/llm_gateway/routing/policy.py`, `integrations/llm_gateway/fallback/policy.py`):

- **No capability anywhere overrides `RoutingCriteria`** — every one of Research, Intelligence,
  Engagement, Scoring, Copywriting, Quality gets the identical default:
  `objective=RoutingObjective.BEST_QUALITY`, `fallback=FallbackEligibility()` (default
  `max_cost_multiplier=3.0`, `allow_cost_ceiling_override_on_exhaustion=False`).
- `BestQualityPolicy` ranks candidates strictly by `quality_tier` descending: **Sol (100) >
  Terra (70) > Luna (40)**.
- **But** `FallbackPolicy._build_attempt_sequence()` then filters that ranked list to within
  `max_cost_multiplier` (3.0×) of the cheapest survivor's `standard_combined_price`
  (input+output price per million, summed): Sol = $35.00, Terra = $17.50, Luna = $7.00. Sol/Luna
  = **5.0× > 3.0×** — **Sol is excluded from the attempt sequence under normal conditions
  (Terra and Luna both healthy)**, which is the common case. The actual attempt sequence in
  practice is **`[Terra, Luna]`**, Terra tried first, Luna only on Terra's failure.
- Sol would only ever be dispatched if it were the sole surviving *healthy* candidate (e.g. a
  simultaneous Terra+Luna outage) — rare, and the opposite of what happened during this phase's
  documented incidents (all 3 models tend to fail together, being one shared OpenAI account).

**This refines, rather than confirms verbatim, the task's own hypothesis (A) "GPT-5.6 Sol
usage"**: Sol itself is not the driver (it's structurally filtered out already) — the real
driver is that **every single capability call, unconditionally, defaults to the most expensive
*cost-eligible* model (Terra, 2.5× Luna's price on both input and output) with no
capability-specific override ever narrowing this down**, even for capabilities whose output is
short/simple (e.g. Quality's `{passed, issues}`, Engagement's structured signal) where a cheaper
model would very plausibly perform identically. This is category **A** in spirit (expensive
default model routing) with a precise, code-verified correction: **Terra, not Sol**, is the
actual workhorse.

## 4. Proportional cost estimate (explicitly labeled — not a precise reconstruction)

Given (1) the real, dashboard-reported 3-day total (**$9**, as stated in this task — not
independently re-derived, no dashboard access exists from this environment), (2) the reliable
1788-call estimate split 1684 (NEWS_ANALYSIS, 94.2%) : 104 (CONTENT_GENERATION, 5.8%), and
assuming failed/quota-rejected calls cost ~$0 (§1):

| | share of successful calls | proportional spend estimate |
|---|---|---|
| NEWS_ANALYSIS (research+intelligence+engagement+scoring) | 94.2% | **≈ $8.48** |
| CONTENT_GENERATION (research+intelligence+copywriting+quality) | 5.8% | **≈ $0.52** |

This proportional split assumes uniform per-call cost across both workflows, which is an
approximation — `CONTENT_GENERATION`'s `copywriting` step almost certainly produces longer
output (a full Telegram post) than `NEWS_ANALYSIS`'s shorter steps, so CONTENT_GENERATION's true
share is likely somewhat higher than 5.8% and NEWS_ANALYSIS's somewhat lower — directionally
noted, not corrected for, since no real per-call token data exists to correct it with (§0).

**Cost per analyzed event** ≈ $8.48 / 421 ≈ **$0.020**.
**Cost per delivered draft**, including the amortized NEWS_ANALYSIS cost of the ~16.2 events
(421/26) it took on average to find one CONTENT_GENERATION-eligible story: ≈ ($0.020 × 16.2) +
($0.52/26) ≈ $0.324 + $0.020 ≈ **≈ $0.34**.

## 5. Cost driver determination

**Do not guess** was the instruction — here is what the evidence actually supports, ranked:

1. **(A-refined) Expensive uniform default routing — confirmed by code, not inferred.** Every
   capability, regardless of output complexity, routes to Terra ($2.50/$15 per M) by default,
   with zero capability-specific tuning. This is the single largest lever available: it affects
   100% of the 1788 successful calls uniformly.
2. **(D) NEWS_ANALYSIS volume is the dominant *call count* driver** (94.2% of successful calls,
   1684 of 1788) simply because every triaged event — regardless of how likely it is to ever
   become a delivered story — receives the full 4-call treatment. Only 26 of 421 (6.2%)
   NEWS_ANALYSIS completions ever became a CONTENT_GENERATION draft.
3. **(F) Retries/failures are not a material cost driver** in dollar terms for this window — the
   large FAILED count (267) is explained almost entirely by the quota outage (§1), which OpenAI
   does not bill for. Genuine mid-workflow paid retries (a real transient failure after partial
   token consumption) cannot be quantified from available data (§0) but are structurally bounded
   (`max_same_candidate_retries=1`, `max_fallback_attempts=3`) and not believed to be large.
4. **(G) Smoke tests are negligible** — only 3 total minimal-probe calls exist in this project's
   entire history (Phase 15's own recovery report), each a few dozen tokens.
5. **(H) Cache misses**: `CacheCoordinator`/`RedisCacheStore` exist and are wired into
   `FallbackPolicy._run_sequence()` (checked before every dispatch), but every `NewsEvent` is
   distinct content, so a cache hit on the *content-bearing* request is structurally rare
   regardless of routing — not a material factor for this workload shape. Not further
   investigated this pass (Step 5 covers prompt-level caching separately, a different
   mechanism).
6. **(B) Long model outputs**: plausible but **not verifiable** from current data (§0) — flagged
   for Step 4's token-limit work as a precautionary ceiling regardless of whether it's already
   the dominant factor.
7. **(C) Duplicate Research/Intelligence execution across NEWS_ANALYSIS→CONTENT_GENERATION**:
   real and structurally guaranteed (every CONTENT_GENERATION task re-runs Research+Intelligence
   from scratch even though the same NewsEvent's NEWS_ANALYSIS task already ran them) — but only
   affects the 26 CONTENT_GENERATION completions (5.8% of call volume), so it's a real, fixable
   waste (Step 3) but not the dominant *dollar* driver this specific window, by volume share.

**Bottom line**: the largest, most confidently-supported lever is **A-refined (routing)**,
followed by **D (volume)**; **C (duplicate work)** is real and worth fixing but smaller in
dollar terms than A/D for this specific 3-day mix, given how few events currently reach
`CONTENT_GENERATION`.

## 6. What this audit could NOT determine

- Exact input/output/cached/reasoning token counts for any historical call (§0).
- Whether any individual FAILED task's partial attempts (before hitting the quota wall) consumed
  billable tokens.
- The true CONTENT_GENERATION-vs-NEWS_ANALYSIS cost split (§4's 94.2%/5.8% is a call-count
  proportion, not a token-weighted one).

These gaps are exactly what Step 7/8's new cost-accounting infrastructure (this same task) is
built to close going forward — this audit is necessarily retrospective-estimate-only for the
period before that infrastructure exists.

---

**AUDIT COMPLETE — PRIMARY DRIVER: UNIFORM EXPENSIVE DEFAULT ROUTING (TERRA), SECONDARY:
UNFILTERED NEWS_ANALYSIS VOLUME**
