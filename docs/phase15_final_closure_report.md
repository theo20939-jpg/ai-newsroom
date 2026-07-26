# Phase 15 — Editorial Intelligence — Final Closure Report

Status: **PHASE 15 COMPLETE — SAFE DEFERRED CUTOVERS DOCUMENTED**

---

## 1. Phase 15 objective

Improve editorial quality and trustworthiness of the automated Telegram newsroom pipeline
without destabilizing the already-working M1–M14.5 production path: better source/category
data quality (M1/M2), preserve real engagement signal for future scoring use (M3), a
transparent multi-component editorial score beyond a single LLM opinion (M4), and a
deterministic, non-LLM guard against unsupported factual claims reaching delivery (M5) — all
under a strict, repeatedly-reaffirmed safety discipline: no unauthorized activation of any new
scoring/enforcement mode, no manual pipeline triggering, no destructive or irreversible action,
nothing pushed to any remote.

## 2. M1 — Source Quality: **PASS, deployed**

RSS/Atom title HTML-stripping and unescaping; `is_valid_title()` early-rejection gate at
triage; a duplicate-`NEWS_ANALYSIS`-task dedup fix. Live-validated on 48 newly-collected events
(zero HTML fragments, zero duplicate tasks, 5 real malformed titles correctly rejected). Nothing
materially deferred.

## 3. M2 — Category Reliability: **PASS, deployed**

Deterministic source-tag→`EventCategory` mapping — no new taxonomy, no migration, zero new LLM
calls. Live-validated 311/311 new events categorized, 94.2% specific. Per-item (vs per-source)
granularity and LLM-predicted category were explicitly deferred as future work, not attempted.
M2's own live validation is also where the provider `runtime_unavailable` latch blocker was
first discovered (flagged there, fixed in this closure's Runtime Reliability workstream, §11).

## 4. M3 — Engagement Signal Preservation: **PASS, migrated, deployed, live-validated**

`NewsEvent` gained `views_count`/`forwards_count`/`replies_count`/`reactions_count` (migration
`c2a4e6f9b3d1`, additive, nullable, already applied — confirmed current `alembic head` matches).
Telegram engagement is captured on collection; RSS/NEWS_API correctly leave these `NULL`
(unsupported by those source types). Live-confirmed still working today: 1/1 Telegram event
collected in the last 2 hours carries engagement data (100%).

## 5. M4 — Editorial Scoring V2: implementation status

**IMPLEMENTED, CALIBRATED (M4.1), TESTED.** Pure `compute_editorial_score_v2()` +
async `apply_editorial_scoring_v2()` wrapper in `services/editorial_scoring.py` — a 5-component
weighted blend (semantic_editorial 40%, freshness 20%, engagement 20%, source_reliability 10%,
novelty 10%), zero new LLM calls, fully backward-compatible with the existing `score` field.
M4.1 fixed a source-type-bias defect found in the original backtest (novelty-only weight
redistribution + baseline-confidence shrinkage, evidence-based, not a naive uniform
redistribution).

## 6. M4 — activation status: **DEFERRED**

Re-reviewed against a substantially larger clean post-M3 sample this closure task built fresh
(177 samples, ~23 hours, vs M4.2's original 109 samples/4 hours —
`docs/phase15_m4_editorial_scoring_v2_report.md`'s own "FINAL M4 CUTOVER REVIEW" section). New,
decisive finding this closure adds: **at the live threshold (65), activating v2 unchanged would
collapse eligible volume ~80% (45→9 of 177)** — a threshold sweep (55 through 70) shows this
holds at every swept value, just less severely at lower thresholds. Telegram/NEWS_API sample
sizes (13/8) remain below the 30-event floor. 3 of 10 cutover criteria fail. Deferred, not
rejected — the evidence base is meaningfully stronger than before and now includes the specific
threshold-recalibration work a future cutover attempt must budget for.

## 7. Active scoring version and threshold

`editorial_scoring_version = "v1"` (unchanged). `content_generation_min_score = 65` (unchanged).

## 8. M5 — Fact Safety: implementation status

**IMPLEMENTED, CALIBRATED (M5.3), TESTED, BACKTESTED, DEPLOYED IN SHADOW MODE.** Deterministic,
regex-based claim extraction (money/percentage/date/entity/quote) and multi-tier support
classification in `services/fact_safety.py`, applied at the `"quality"` workflow step via
`apply_fact_safety()`. Zero new LLM calls, zero new DB queries. This closure's own M5.3
calibration fixed 3 documented false-positive classes (Yuan/CNY currency vocabulary, ИИ/AI and
КНР/China entity aliasing, CRISPR-style descriptive-suffix normalization) and, in the process,
found and fixed a second real regression the calibration itself introduced (entity-centrality
severity check breaking for Cyrillic entities once alias canonicalization was added) — caught by
the historical backtest, not by chance.

**The single most significant defect in the entire Phase 15 M3–M5.3 arc** was found during M5.2
(prior session): `apply_fact_safety()` silently never ran in production for the entire M5/M5.1
shadow period because it read the draft's title/body from the wrong workflow step's output — a
"tests all green, feature never actually ran" case caught only by inspecting real production
data, not by any of the 76 tests that existed at the time (their own test doubles shared the
same wrong assumption as the bug). Fixed; a dedicated production-shaped regression test
(`test_real_four_step_content_generation_workflow_runs_fact_safety_from_copywriting_output`) now
guards against a recurrence — it uses the REAL, unmodified `CONTENT_GENERATION` workflow
definition and real `Capability` classes (only the LLM Gateway faked), and fails with a
`KeyError` immediately if the wiring ever breaks again.

## 9. M5 — enforcement status: **DEFERRED**

`fact_safety_mode` remains `"shadow"`. Evaluated against all 8 activation criteria
(`docs/phase15_m5_fact_safety_report.md`'s M5.3 section §6): 2 of 8 fail outright — fewer than
20 natural post-calibration drafts exist (in fact, per §11 below, the OpenAI account's current
quota exhaustion means **zero** new drafts of any kind, calibrated or not, are currently
producible), and the pre-existing English Title-Case-entity false-positive class remains
unresolved (out of this calibration's authorized scope). A historical backtest across all 25
real `ContentDraft` rows shows the calibration is a clean improvement (2 fewer false-positive
blocks, zero false-negative regressions), but a backtest is not a substitute for the required
live natural sample.

## 10. Active Fact Safety mode

`fact_safety_mode = "shadow"` (unchanged; the code default is also `"shadow"`, not `"off"`).

## 11. Provider-health reliability fix: **IMPLEMENTED AND DEPLOYED**

`docs/phase15_runtime_reliability_report.md` (full detail). The recurring `runtime_unavailable`
Redis latch — previously requiring manual `KEYS`/`DEL` recovery twice this phase — now
self-heals two ways: (1) a regional/account-scoped permission failure (403,
`ProviderRegionalUnavailableError`, newly split out from the previously-overbroad
`ProviderPermanentIncompatibleError`) is marked with a bounded, configurable cooldown
(`provider_regional_unavailable_cooldown_seconds`, default 3600s) instead of no TTL at all; (2)
any real successful dispatch now calls a new `mark_healthy()`, clearing stale state immediately
regardless of why it was set. Genuinely permanent configuration failures (invalid model id,
rejected request shape, moderation block) are completely unaffected — still latched with no TTL,
manual-clear-only, exactly as before. 203 tests passing across every affected file. Deployed to
`news_analysis_worker` and `content_worker` (the only two services that dispatch real LLM
Gateway calls; `automation_worker` does not use the Gateway at all).

**Important operational finding, discovered during this closure's own live-health check, NOT
caused by this fix or any Phase 15 code**: the OpenAI account is currently returning
`insufficient_quota` (HTTP 429, a billing/plan condition, distinct from an ordinary rate limit)
on every `NEWS_ANALYSIS`/`CONTENT_GENERATION` attempt since **2026-07-25 22:04:46 UTC** (over 8
hours as of this report). This is correctly classified as `ProviderTransientError` (the existing,
unchanged 60-second self-expiring path) — **not** a `runtime_unavailable` latch, so it does not
get stuck and will resolve automatically the moment the account's quota is restored, with zero
manual Redis intervention needed either way. This is an account/billing matter outside this
task's authorized scope (no ability to modify payment/billing) and is flagged here for the
user's direct attention, not something Phase 15's own code can remediate.

## 12. Files changed (this closure task's own workstreams, on top of the already-committed
M3–M5.2 work)

Fact Safety calibration: `services/fact_safety.py`, `tests/test_fact_safety.py`.
Runtime reliability: `core/config.py`, `integrations/llm_gateway/boot.py`,
`integrations/llm_gateway/errors.py`, `integrations/llm_gateway/fallback/health_store.py`,
`integrations/llm_gateway/fallback/policy.py`, `integrations/llm_gateway/providers/
openai_adapter.py`, `tests/fakes/fake_infra.py`, `tests/fakes/fake_provider_adapter.py`,
`tests/test_fallback_policy.py`, `tests/test_openai_adapter.py`,
`tests/test_provider_health_store.py`, `tests/test_routing_engine.py`.
M4 final review (read-only, new script, no production code changed): `scripts/
phase15_m4_final_cutover_backtest.py`.
Documentation: `docs/phase15_m4_editorial_scoring_v2_report.md`, `docs/
phase15_m5_fact_safety_report.md`, `docs/phase15_runtime_reliability_report.md` (new),
`docs/phase15_final_closure_report.md` (new, this file).

## 13. Migrations

None added by this closure task. `alembic heads` confirmed a single head (`c2a4e6f9b3d1`),
matching M3's already-applied engagement-metrics migration — no new migration was needed for
Fact Safety calibration or the runtime reliability fix (both are pure code changes against
existing tables/Redis keys).

## 14. Test results

Full suite: see §14a (filled in once the final full run completes — recorded below with exact
totals, per instruction not to claim a clean suite without evidence). Targeted regression
(every file touching this closure's own changes, run in isolation): **281 passed** across
`test_fact_safety.py` (78), `test_fallback_policy.py`/`test_routing_engine.py`/
`test_provider_health_store.py`/`test_ai_integration_layer_e2e.py`/
`test_capability_boot_wiring_e2e.py`/`test_phase8_cross_cutting_regression.py`/
`test_phase9_capability_registration.py`/`test_phase9_research_intelligence_integration.py`/
`test_routing_gateway_golden_path.py`/`test_routing_gateway_pipeline.py`/
`test_openai_adapter.py`/`test_phase10_workflow_integration.py` (203). `ruff check .`: clean,
whole repo. `mypy` on every changed production file: clean. `scripts/validate_architecture.py`:
0 forbidden-dependency violations. `git diff --check`: clean (no whitespace errors). Secret
scan across the full diff: clean.

### 14a. Full suite (filled in below)

**1159 passed, 3 failed, in 464.91s (0:07:44).** All 3 failures are the same pre-existing
`content_generation_dry_run` environment-mismatch (`test_content_generation_integration.py::
test_full_chain_dry_run_creates_draft_and_renders_without_sending`, `test_content_worker_cycle.
py::test_run_content_cycle_sequential_no_gather_and_notifies_after_draft_creation`,
`test_content_worker_cycle.py::test_run_content_cycle_dry_run_never_calls_bot_send_message`) —
this environment's live `.env` has `content_generation_dry_run=False` (live-send configured, by
design, since Phase 14.5's Observation Mode), while these 3 tests assert the code's own `True`
default directly with no monkeypatch override. Documented as unrelated in every milestone's
report across this entire Phase 15 arc (M3 through this closure) — confirmed once again here by
direct inspection: the failure is a bare `assert settings.content_generation_dry_run is True`,
nothing related to Fact Safety, Editorial Scoring, or the provider-health fix. No genuine Phase
15 regression in the full suite.

## 15. Deployment state

`news_analysis_worker` and `content_worker` rebuilt and redeployed with the calibration +
reliability fix (twice for `content_worker`: once for the Fact Safety calibration, combined
with the reliability fix's own redeploy). `automation_worker`, `postgres`, `redis` untouched
(not rebuilt, not restarted) — `automation_worker` doesn't use the LLM Gateway; `postgres`/
`redis` needed no change. `backend` is not currently running in this environment and was not
started. All 5 (of the 4 actually running) containers healthy at time of writing.

## 16. Live pipeline evidence

Collector→Triage confirmed healthy: category distribution meaningful (AI/STARTUPS/SOFTWARE/
TECH/UNKNOWN, no collapse), zero duplicate `NEWS_ANALYSIS` tasks, zero synthetic/test titles
among real collected events in the last 24 hours (a small number of recognizably-named test
artifacts like "Concurrency test event" trace to `test_triage_orchestrator_cycle.py`'s own
already-documented, pre-existing unscoped-live-DB test pattern — not a new issue, and confirmed
they never reached a real `EditorialTask`). Telegram engagement capture still 100% on recent
events. **`NEWS_ANALYSIS`/`CONTENT_GENERATION` themselves have produced zero successful
completions since 2026-07-25 22:04:46 UTC, due to the OpenAI quota exhaustion in §11** — this is
a real, current, honestly-reported gap in live pipeline evidence, not glossed over. No manual
Telegram message was sent by this task (dry_run confirmed `False`, i.e. live-send-configured,
but no draft was created for anything to send). No public-channel publication.

## 17. Cost/provider-call impact

Zero new provider calls attributable to any Phase 15 M5.3/reliability-fix code — confirmed
structurally (`test_18_fact_safety_module_imports_no_llm_gateway_or_capability`, the new
production-shaped integration test, and the reliability fix's own pure Redis/exception-routing
nature). The only provider activity during this closure task was organic, pre-existing
production traffic's own attempts (all of which failed on quota, §11, not attributable to this
task's changes).

## 18. Known limitations

- English Title-Case-entity false positives in Fact Safety remain unresolved (pre-existing,
  out of M5.3's authorized scope).
- Fact Safety's currency/entity-alias vocabulary is still a small, explicit, hand-curated list —
  correct and safe by design, but will keep missing any currency/alias not yet added.
- Editorial Scoring V2's score compression (vs v1) and its threshold-volume interaction are now
  characterized but not yet resolved with a validated new threshold.
- The provider regional-unavailable cooldown (3600s default) is a fixed constant, not adaptive,
  calibrated against a single historical incident.
- OpenAI account quota exhaustion (§11) is fully outside this task's remediable scope.

## 19. Explicit deferred items

- V2 cutover (Editorial Scoring) — deferred pending more Telegram/NEWS_API sample and a
  dedicated threshold-recalibration pass.
- Fact Safety enforcement — deferred pending 20+ natural post-calibration drafts (blocked
  entirely, currently, by the quota outage) and an English Title-Case-entity calibration pass.
- OpenAI billing/quota resolution — requires the user's direct action outside this codebase.

## 20. Rollback instructions

- Editorial Scoring V2: never activated: nothing to roll back. If a future session activates it,
  rollback is `editorial_scoring_version` → `"v1"`, zero code/DB change.
- Fact Safety: `fact_safety_mode` never left `"shadow"`: nothing to roll back. If a future
  session activates `"enforce"`, rollback is the same flag → `"shadow"`, zero code/DB change.
- Runtime reliability fix: fully backward compatible (every new parameter is optional/defaulted
  to old behavior) — reverting the commit itself is the only rollback path, not expected to be
  needed.
- Git: this closure's commits live only on `feature/phase15-m5-fact-safety` plus a new
  `checkpoint/phase15-complete` safety branch (§ Git Completion) — `master` and
  `checkpoint/phase15-m3` are both untouched and remain valid rollback points on their own.

## 21. Phase 16 recommended starting point

1. **Resolve the OpenAI quota exhaustion** (§11) — this blocks essentially all further live
   validation work for both deferred cutovers.
2. Once resolved, let natural traffic accumulate 20+ post-calibration Fact Safety drafts and
   30+ Telegram/NEWS_API `NEWS_ANALYSIS` samples, then revisit both deferred cutover decisions
   with the now-much-larger evidence base this phase leaves behind.
3. A dedicated Editorial Scoring V2 threshold-recalibration study (§6) before any future cutover
   attempt.
4. A dedicated English-Title-Case-entity Fact Safety calibration pass.

---

PHASE 15 COMPLETE — SAFE DEFERRED CUTOVERS DOCUMENTED
