# API Cost Optimization Report

Status: **IMPLEMENTED, TESTED, DEPLOYED (`news_analysis_worker`/`content_worker`, 2026-07-28).
Budget guard active in `shadow` mode (never blocks). Hard cap (`enforce`) not yet activated —
pending a live natural sample, currently blocked by an ongoing, unrelated OpenAI rate-limit/quota
outage (see §5, §13).**

---

## 1. Original problem

Approximately **$9 spent in 3 days (≈$3/day, ≈$90/30 days)** — too expensive for the project's
current development/Observation-Mode stage. See `docs/api_cost_audit_report.md` for the full
audit; summarized here.

## 2. Exact cost attribution

No historical per-call token/cost data exists anywhere in this codebase — `ai_executions` had 0
rows and the Redis cost ledger had 0 keys, because `CostTracker.record()` was never actually
called by any production code path (confirmed via direct inspection of
`integrations/llm_gateway/gateway.py`'s own docstring: *"CostTracker.record() is deliberately
NOT called by this class"*). This is itself the most consequential finding of the audit — cost
accounting existed as fully-built, tested infrastructure that was simply never wired in. Given
that, attribution below is built from (a) reliable Postgres task-volume counts, (b) the current,
unmodified routing/pricing code (deterministic, not guessed), and (c) an explicitly-labeled
proportional estimate — never an invented number.

**Primary driver — expensive uniform default routing, code-confirmed**: every one of the 6 real
capabilities (Research/Intelligence/Engagement/Scoring/Copywriting/Quality) used
`RoutingCriteria`'s default `objective=BEST_QUALITY`, with zero capability-specific override
anywhere. `BestQualityPolicy` ranks GPT-5.6 Sol first, but the existing 3.0× cost-ceiling
eligibility filter already excludes Sol from the actual attempt sequence in practice ($35 vs. a
$7 cheapest-candidate floor = 5.0×, over the ceiling) — so **Terra** ($2.50/$15 per M tokens,
2.5× Luna's price on both axes), not Sol, was the true default workhorse for essentially every
call, with Luna only used on a Terra failure.

**Secondary driver — unfiltered `NEWS_ANALYSIS` volume**: 94.2% of successful call volume
(1684 of 1788 calls over the 3-day window) came from `NEWS_ANALYSIS`, which ran unconditionally
for every triaged event (only 0.13% of collected events were ever deterministically rejected
before reaching it) — only 6.2% of those analyzed events ever became a delivered
`CONTENT_GENERATION` story.

**Not the primary driver this window**: duplicate Research/Intelligence re-execution across
`NEWS_ANALYSIS`→`CONTENT_GENERATION` is real and structurally guaranteed, but only affects the
26 `CONTENT_GENERATION` completions (5.8% of call volume) — a real, fixable waste (§5), just a
smaller dollar lever than routing/volume for this specific 3-day mix. Retries/failures were not
material (the large `FAILED` count is explained by an OpenAI quota outage, which is not billed).
Smoke tests and cache misses were both negligible/not applicable.

## 3. Previous model routing

`RoutingCriteria.objective` defaulted to `BEST_QUALITY` for every capability — no
capability-specific tuning anywhere in the codebase.

## 4. New model routing

`RoutingCriteria.objective` now defaults to `LOWEST_COST`
(`integrations/llm_gateway/routing/criteria.py`) — a **single field default change**, reusing
100%-already-tested infrastructure (`LowestCostPolicy` was already registered at boot). Combined
with the unchanged 3.0× cost-ceiling filter, every capability's real attempt sequence becomes
**`[gpt-5.6-luna, gpt-5.6-terra]`**, Luna first, Terra as the only cost-eligible fallback,
**gpt-5.6-sol structurally excluded from the ordinary route** (5.0× over the ceiling). A new,
optional `request.metadata["objective"]` hook (matching the established "extend via metadata"
pattern) lets a future caller opt into a different objective without a schema change; nothing in
production sets it today.

`gpt-5.4-nano` (the task's own candidate for Engagement) does not exist in this codebase's model
catalog and could not be safely verified/added (no live-verification capability was available —
see §5); Engagement therefore also routes to `gpt-5.6-luna`, identical to every other capability,
per the task's own explicit fallback instruction.

## 5. Model benchmark

**Live paid validation was not possible**: a single minimal probe (cost: $0, OpenAI does not
bill a rejected request) confirmed the account is still under the same `insufficient_quota`
outage Phase 15's closure task discovered (ongoing since `2026-07-25 22:04:46 UTC`). Every
conclusion is therefore built from static, offline evidence:

- **Schema conformance**: strong confidence, verifiable without a live call — all 3 real
  catalog models declare `supports_structured_output=True` (officially verified against OpenAI
  docs at catalog-authoring time), and every structured-output request already uses OpenAI's
  Structured Outputs `strict: true` mode, which *guarantees* schema conformance for any model
  that supports the feature at all (not probabilistic) — schema risk does not meaningfully
  differ between Sol/Terra/Luna.
- **Semantic quality** (Russian fluency, entity/monetary/date preservation, editorial tone): not
  verifiable without a live call, and no historical evidence substitutes for one (Luna has
  essentially never been dispatched in production, and no `WorkflowStepResult` persists which
  model produced it anyway). **This is a disclosed, real, unresolved risk** — mitigated
  structurally by keeping Terra as the automatic fallback on any hard failure (though that
  safety net does not catch technically-valid-but-lower-quality output). Recommended follow-up,
  not implemented as code: observe the first natural batch of real Luna-routed output once the
  quota outage resolves, the same bounded-natural-sample discipline this project has used for
  every other new-behavior rollout this phase.

Full detail: `docs/api_cost_model_routing_benchmark.md`.

## 6. Duplicate-call removal

`services/analysis_reuse.py` (new) + `capabilities/executor.py`: `CONTENT_GENERATION`'s
`research`/`intelligence` steps now reuse the same event's already-`COMPLETED` `NEWS_ANALYSIS`
task's own persisted results — same `NewsEvent`, same evidence, zero new provider call — instead
of unconditionally re-running both. Falls back to a real call whenever no valid prior result
exists (missing task, malformed/incomplete result, wrong event) — never blocks, never silently
degrades. Original `NewsEvent` evidence, Fact Safety's own evidence packet, and provenance are
all unaffected (they read from `NewsEvent`/`context.business.workflow_state.step_results`
exactly as before — the reused result flows through the identical seam a fresh call's result
would).

**Before/after, one normal story reaching `CONTENT_GENERATION`**: 8 provider calls (4
`NEWS_ANALYSIS` + 4 fresh `CONTENT_GENERATION`) → **6 provider calls** (4 `NEWS_ANALYSIS` + 2
reused + 2 fresh `CONTENT_GENERATION`: copywriting, quality) — a 25% reduction in that story's
own `CONTENT_GENERATION`-side call count.

## 7. Token-limit changes

Centralized in `capabilities/executor.py` (one dict, not six per-capability files) - evidence-
informed, not the task's raw candidate values verbatim, using real historical output sizes
measured from persisted `WorkflowStepResult.result` JSON (never invented):

| Capability | Task's candidate | Real observed max | Set ceiling | Reasoning effort |
|---|---|---|---|---|
| Research | 700 | 197 tokens | **450** | none |
| Intelligence | 500 | 259 tokens | **500** | low |
| Engagement | 250 | 273 tokens (over candidate!) | **350** | low |
| Scoring | (unlisted) | 69 tokens | **250** | low |
| Copywriting | 900 | 128 tokens | **600** | low |
| Quality | 400 | 232 tokens | **400** | low |

Engagement's real observed max (273) already exceeded the task's own 250-token candidate — using
250 verbatim risked truncating a real structured JSON response (an explicit hard requirement:
"do not truncate required structured JSON"); 350 was chosen instead, with real margin. All 6
existing capability test suites (72 tests) still pass unchanged against the new ceilings.

`reasoning_effort` is a new, optional `GenerateRequest`/`ExecutionContext` field
(`"none"|"low"|"medium"|"high"`, translated to OpenAI's `reasoning.effort` payload field) —
`"none"` for Research (deterministic fact extraction, not editorial judgment), `"low"` for every
other capability (real, if modest, editorial judgment).

## 8. Prompt/cache findings

Every one of the 6 active system prompts (96-203 tokens) is **5-10× below** OpenAI's ~1024-token
automatic prompt-caching threshold — no prompt in this codebase is currently long enough for
provider-side prompt caching to help, regardless of call volume. No caching code was added; none
would have any effect at current prompt lengths. Full detail:
`docs/api_cost_prompt_cache_audit.md`.

## 9. Paid-volume findings

Deterministic pre-`NEWS_ANALYSIS` rejection is effectively 0.13% of collected events. The
largest additional lever identified — excluding 6 specific high-volume, low-editorial-specificity
feeds (2 Google News aggregators + 4 arXiv paper feeds, 35.6% of collected volume) — projects to
**~33% of total spend**, but was **deliberately not implemented**: it is a genuine editorial-
scope decision (not a purely technical one) that this task's own evidence cannot validate without
either paid live traffic (blocked by the quota outage) or a human editorial reviewer's judgment
call on what would have been missed. Documented as a proposal for a future, dedicated,
bounded-pilot validation. Full detail: `docs/api_cost_volume_audit.md`.

## 10. Budget-guard design

New settings (`core/config.py`): `llm_budget_mode: Literal["off","shadow","enforce"] = "shadow"`,
`llm_daily_warning_usd: float = 0.50`, `llm_daily_budget_usd: float = 1.00` — the task's own
specified safe defaults, already the code defaults (no `.env` change needed to get this safe
starting state).

`RedisBudgetGuard` (unchanged call site — the existing pre-flight check inside
`FallbackPolicy._run_sequence()`, already wired since Phase 7): `off` never blocks, never logs;
`shadow` computes and logs the exact allow/deny decision `enforce` would make, but never raises;
`enforce` raises `BudgetExceededError` once `spent_so_far + worst_case > llm_daily_budget_usd`,
denying that candidate (the existing `FallbackPolicy` loop then tries the next cost-eligible
candidate, or the workflow step fails cleanly with `AllProvidersFailedError(reason=
"all_candidates_budget_denied")` if none remain — no retry storm, no false-COMPLETED marking).
A separate warning-threshold log fires once `spent_so_far >= llm_daily_warning_usd`, in both
`shadow` and `enforce`. Reservation is the existing pre-flight `worst_case` check (unchanged);
reconciliation is the new real per-call `CostTracker.record()` write, now actually invoked (§11).
The daily ledger key is namespaced by the real UTC calendar date - a new day is structurally a
new, empty key, no explicit reset code needed.

**Known limitation, disclosed rather than silently accepted**: the check-then-increment pattern
across two separate Redis operations (`GET` then, on success, `INCRBYFLOAT`) is not fully atomic
against concurrent callers — a burst of simultaneous calls could each read the same
not-yet-updated spend and all pass, causing a small overshoot bounded by
`(concurrent callers) × (worst_case per call)`, not unbounded. Current production concurrency is
low (each worker processes its batch sequentially, one task at a time), so real-world exposure is
small; a fully atomic implementation (a Lua script or `WATCH`/`MULTI`) was assessed as a larger
engineering change than this task's own "smallest lever" scope called for, and was not built.

## 11. Cost observability

`AIExecution` (Postgres, migration `bbcfd4afc722`, additive-only) gained `event_id`,
`workflow_name`, `retry_number`, `cached_input_tokens`, `reasoning_tokens`, `usage_source`.
`services/cost_recording.py` (new) writes one row per successful `CapabilityCall`, wired into
`capabilities/executor.py` alongside the existing Redis ledger write — both driven by the same
`compute_call_cost()` formula (extracted, not duplicated). `CapabilityUsage` gained
`cached_input_tokens`/`reasoning_tokens`, populated defensively (never invented) from the real
OpenAI response when present. **Cached tokens are recorded but priced at the standard input
rate** — no verified `cached_input` `PricingTier` exists in the catalog, so this is a disclosed,
safe-direction overestimate, not a fabricated cheaper rate. `scripts/api_cost_daily_summary.py`
(new, read-only) reports total spend, spend by workflow/capability/model, cost per analyzed
event, cost per generated draft, and cost per delivered story for any UTC day.

Cost recording is fully **opt-in** at the `CapabilityExecutor` constructor level (`cost_tracker`/
`pricing_catalog`, both default `None` = the old, zero-recording behavior) — every existing test/
caller that doesn't pass them is unaffected; only the two real production entry points
(`worker/analysis_main.py`, `worker/content_main.py`) pass real ones, sourced from
`AIIntegrationLayer.cost_tracker` (already-built, never-wired infrastructure from Phase 7).

## 12. Tests

New/updated test files: `tests/test_routing_criteria.py` (default-objective flip),
`tests/test_ai_integration_layer_e2e.py` (cost-anchor regression re-pinned to `BEST_QUALITY`
explicitly), `tests/test_analysis_reuse.py` (11 tests, new), `tests/test_capability_executor.py`
(+6 token-limit/reasoning-effort tests), `tests/test_openai_adapter.py` (+3: reasoning-effort
payload translation ×2, PermissionDenied reclassification already from Phase 15), `tests/
test_budget_guard_real.py` (rewritten for the 3-state mode, 15 tests), `tests/
test_cost_recording_integration.py` (2, new), `tests/test_api_cost_optimization_checklist.py`
(10, new — real-catalog Luna-first/Terra-fallback/Sol-excluded end-to-end, cached-token pricing
limitation, Collector has no LLM/budget dependency, UTC-date ledger reset,
`resolve_ai_capability` canary), `tests/test_analysis_worker_main.py` / `tests/
test_content_worker_main.py` (fake AI-layer fixture gained `cost_tracker`).

**Full suite: 1193 passed, 4 failed in 1015.53s (0:16:55)** (`python -m pytest -q`, 2026-07-28,
post session-recovery). All 4 failures individually confirmed pre-existing/unrelated, not a
regression from this changeset:

- 3× `content_generation_dry_run` environment-mismatch (`test_content_generation_integration.py::
  test_full_chain_dry_run_creates_draft_and_renders_without_sending`,
  `test_content_worker_cycle.py::test_run_content_cycle_sequential_no_gather_and_notifies_after_
  draft_creation`, `test_content_worker_cycle.py::test_run_content_cycle_dry_run_never_calls_bot_
  send_message`) — reproduced identically with every uncommitted change stashed, HEAD at the
  protected `checkpoint/phase15-complete` (`a99ecd5`): caused by local `.env`'s
  `content_generation_dry_run=False` (set for live/manual testing), not by any code in this diff.
- `test_analysis_worker_cycle.py::test_run_analysis_cycle_lost_race_is_not_fatal_and_not_refilled`
  — a pre-existing ordering-tiebreak flake (`_select_eligible_task_ids`'s `created_at.asc(),
  id.asc()` tiebreak is UUID-order, not creation-order, once two tasks tie on `created_at`'s
  timestamp resolution under full-suite load): passed 5/5 in isolated reruns, and
  `worker/analysis_cycle.py`'s own diff in this changeset only adds the optional
  `cost_tracker`/`pricing_catalog` kwargs - it does not touch `_select_eligible_task_ids` at all.

A prior run (recovered from the session that was interrupted mid-suite, `1192 passed, 5 failed in
1322.04s`) additionally showed `test_settings_phase7.py::test_no_phase13_specific_cost_cap_
setting_was_added` failing - already fixed in the working tree before that run finished (the
test's own outdated `assert "CostTracker" not in source` line, superseded by this task's
explicitly-authorized addition of cost *recording* - not enforcement - to the analysis worker);
confirmed passing on every subsequent run. `test_triage_orchestrator_cycle.py::
test_create_task_duplicate_active_task_outcome_is_not_a_failure` also failed once in that same
prior run and passed on every other run (isolated and full-suite) - the same class of
full-suite-only timing flake as the analysis-cycle one above, in completely untouched code.

`ruff check .`: clean, whole repo. `mypy` (18 changed production files): clean, 0 issues.
`scripts/validate_architecture.py`: 0 forbidden-dependency violations. `git diff --check`: clean.
Secret scan (manual pattern scan across the full diff + all new files): clean.

## 13. Deployment

**Performed 2026-07-28**, after the full suite (§12) passed. Only `news_analysis_worker` and
`content_worker` were rebuilt and restarted (the two entry points that changed - `worker/
analysis_main.py`, `worker/content_main.py`) - `automation_worker` (the Collector, `worker/
main.py` -> `worker/cycle.py`) imports neither `CostTracker`/`BudgetGuard`/`services.
analysis_reuse`/`services.cost_recording` nor any changed capability/gateway code, so it was
deliberately left running its existing image, per this task's own "restart only what changed"
rule. `backend` was also left untouched (not part of this changeset).

Observed over a bounded natural window post-restart:
- Both workers started clean - capabilities registered, no import errors, no schema errors
  against the already-applied `bbcfd4afc722` migration.
- `news_analysis_worker` ran one full batch (5 tasks): every one failed at the `research` step
  against a live `429 Too Many Requests` from OpenAI - the fallback policy retried each
  cost-eligible candidate with backoff, then failed the step cleanly
  (`capability_call_failed` -> required-step-failed -> task `FAILED`, committed) - **no retry
  storm, no false-COMPLETED marking**, each task attempted exactly once per cycle as designed.
  This is the same class of external provider unavailability already disclosed in §5/§12
  (previously observed as `insufficient_quota`; now `429`, still not this changeset's
  regression) - not re-probed further per this task's own "do not repeatedly probe a
  provider with insufficient quota" instruction.
- `content_worker` ran a cycle cleanly (`content_cycle_finished`, 0 eligible - expected, no
  fresh `NEWS_ANALYSIS` `COMPLETED` task existed yet given the above).
- `automation_worker` (Collector) confirmed still running and producing `NewsEvent`s/
  `EditorialTask`s normally throughout, unaffected by the LLM-side outage (`llm_daily_budget_usd`
  exhaustion or provider unavailability never blocks collection - a separate, unconnected
  pipeline stage) - the explicit "Collector remains active when the LLM budget is exhausted"
  requirement holds structurally (Collector's own code has no BudgetGuard/CostTracker
  dependency at all, not merely an untested assumption).
- Redis cost ledger (`phase7:cost_ledger:2026-07-28:research`) shows a real, non-zero recorded
  spend, confirming the recording path is live end-to-end for at least one successful call; no
  corresponding `ai_executions` row was observed for today's date in this same bounded window
  (the 5 observed task failures in the batch above all failed *before* a SUCCESS call, so no
  Postgres write was expected for any of them) - `workflows/runner.py` commits the same session
  on both the success path (end of `run()`) and the failure path (`_fail()`), so a step that
  succeeds earlier in a task that later fails is not silently rolled back; this was not,
  however, directly observed with a live SUCCESS in this bounded window and should be confirmed
  from real data once the account's rate-limit/quota state clears.

## 14. Before/after projection

Using the real 3-day workload (`docs/api_cost_audit_report.md`): 421 `NEWS_ANALYSIS` + 26
`CONTENT_GENERATION` completions over the healthy portion of the window, ~1788 successful calls,
**$9 actual / $3.00 per day / $90 per 30 days** at the current rate.

| | Low | Expected | High |
|---|---|---|---|
| Luna success rate (assumption - no real data exists yet) | 50% | 85% | 97% |
| Routing-only reduction | 30% | 51% | 58% |
| + duplicate-call removal (small: CG is 5.8% of volume) | ~32% | ~54% | ~61% |
| **New daily cost** | $2.04 | **$1.38** | $1.17 |
| **New monthly cost** | $61.20 | **$41.40** | $35.10 |

Token-limit/reasoning-effort changes (§7) are **not separately quantified** in this table -
real observed output sizes were already mostly within the new ceilings, so their main effect is
a safety cap against tail-risk outliers, not a typical-case reduction large enough to estimate
without inventing a number; `reasoning_effort` may deliver a real additional saving but no
historical reasoning-token data exists to size it from.

**Honest result against the 60% target**: the *expected* case (54%) falls short of the "at least
60%" target; only the *high* case (61%, assuming Luna handles 97%+ of calls without falling back
to Terra — an optimistic, unverified assumption) reaches it. **This is reported as-is, not
adjusted to hit the target.** The single largest additional lever that would close the gap with
margin is the volume-reduction proposal (§9, ~33% more) — deliberately not activated this task,
pending editorial review. Calls per analyzed event: 4 (unchanged - NEWS_ANALYSIS is not
shortened). Calls per delivered story: 8 → 6 (§6). Cost per analyzed event and cost per delivered
story will only be measurable from real data once §11's new observability infrastructure has
live traffic to record (currently zero, per the quota outage).

## 15. Quality comparison

No live quality comparison was possible (§5's own disclosed limitation). Structural/schema-level
quality is not expected to change (OpenAI's Structured Outputs strict mode guarantees schema
conformance regardless of model). Editorial/semantic quality risk is real, disclosed, and
deferred to natural post-outage observation - the same discipline this project already applies
to every other new-behavior rollout.

## 16. Active cost settings

`editorial_scoring_version=v1`, `content_generation_min_score=65`, `fact_safety_mode=shadow` -
**all three explicitly unchanged**, per this task's own protected-state instruction.
`llm_budget_mode=shadow`, `llm_daily_warning_usd=0.50`, `llm_daily_budget_usd=1.00` (new, code
defaults, not yet written to `.env`). `RoutingCriteria.objective` default: `LOWEST_COST` (was
`BEST_QUALITY`).

## 17. Rollback instructions

- **Routing**: revert `RoutingCriteria.objective`'s default to `BEST_QUALITY`
  (`integrations/llm_gateway/routing/criteria.py`) - one line, zero DB/migration impact.
- **Duplicate-call reuse**: set `REUSABLE_CAPABILITIES` to an empty frozenset in
  `services/analysis_reuse.py`, or simply revert `capabilities/executor.py`'s `_try_reuse()`
  call site - every `CONTENT_GENERATION` step goes back to always calling its own capability.
- **Token limits/reasoning effort**: revert `capabilities/executor.py`'s two dicts to `{}`/omit
  the kwargs - `ExecutionContext` fields fall back to `None` (provider default), unchanged from
  before this task.
- **Budget guard**: set `llm_budget_mode=off` (env var or `.env`) - immediate, no restart-order
  dependency, no DB change.
- **Cost recording**: stop passing `cost_tracker`/`pricing_catalog` at the two production call
  sites (`worker/analysis_main.py`, `worker/content_main.py`) - `CapabilityExecutor` reverts to
  its old zero-recording behavior; the `ai_executions` schema additions are additive and harmless
  to leave in place either way (downgrade migration exists if ever needed:
  `bbcfd4afc722`'s own `downgrade()`).

## 18. Remaining risks

- Semantic/editorial quality of Luna-routed output is genuinely unverified (§5, §15) - the
  single largest open risk of this entire change set.
- The 60% target is not met in the *expected* case with implemented changes alone (§14) -
  closing the gap requires either the deferred volume-reduction proposal (§9) or a
  better-than-assumed Luna success rate that cannot yet be measured.
- Budget-guard concurrency is approximate, not fully atomic (§10) - low real-world exposure
  given current sequential worker concurrency, but not zero.
- Cached-token pricing is not truly modeled (§11) - a disclosed overestimate, not a precise cost.
- All of the above are blocked from real-world validation by the ongoing OpenAI quota outage,
  unrelated to this task's own changes.

---

**API COST OPTIMIZATION COMPLETE — BUDGET SHADOW VALIDATION REQUIRED**
