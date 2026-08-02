# Phase 17 M6.1 — Production Cutover Readiness

Status: **READINESS PACKAGE PREPARED — CUTOVER NOT EXECUTED.** No production behavior has been
changed. This report documents what is ready, what explicitly is not, and the exact human actions
still required.

## What is ready

- Real, passing preflight check (`scripts/phase17_cutover_preflight.py`, `OVERALL: PASS` against
  the actual current repository/DB state): all Phase 17 feature modes confirmed at their safe
  `off` default, all 6 required prompt files present, the fallback (production) Copywriting prompt
  (`prompts/copywriting/v3.yaml`) confirmed present, all Phase 17 schema modules import cleanly,
  DB connectivity confirmed, Telegram bot token configured (value never logged).
- A documented, staged rollout plan (`docs/phase17_m6_1_production_cutover_runbook.md`) — Stage 0
  (current) through Stage 5 (relevance enforcement, explicitly deferred pending separate
  calibration), each stage's exact config/Docker commands, rollback trigger conditions, and
  rollback commands.
- A versioned `RolloutPolicy`/`FallbackBehavior` schema (`schemas/phase17_rollout_policy.py`) -
  documentation/planning metadata only, not wired to any enforcement path.
- A canary plan outline (runbook, Stage 3) - explicitly marked as requiring new engineering not
  yet built, and requiring separate future human authorization.
- 9 targeted tests, all passing (`tests/test_phase17_cutover_readiness.py`): rollout policy schema
  validation/bounds/ordering, no-mutable-default sharing, a real (not mocked) invocation of the
  preflight checks against this repository, and a static no-LLM/no-Telegram-import guard on the
  preflight script itself.

## What is NOT activated

- No `.env` value has been changed.
- No Phase 17 feature mode is non-default in the running configuration.
- No production worker was started; `automation_worker`/`news_analysis_worker`/`content_worker`
  remain `Exited`; `telegram_bot` remains `Exited`.
- No canary delivery code exists yet (Stage 3 requires new engineering, explicitly deferred).
- No relevance-REJECT enforcement exists or is planned before a separate calibration milestone.

## Exact required human actions before any activation

1. Read `docs/phase17_m6_human_acceptance_packet.md` in full.
2. Explicitly decide, in writing, which stage (if any) to authorize - this report and its runbook
   grant no authorization on their own.
3. For Stage 1 specifically: manually edit the 5 env vars listed in the runbook, restart the 4
   listed services, re-run `scripts/phase17_cutover_preflight.py` once more post-restart, then
   follow the runbook's own "Validation queries" section.
4. For Stage 2+: budget and pre-approve real LLM spend using the same `--confirm-paid-calls` +
   cost-estimate-then-confirm discipline M3/M4/M4.1 already established - never silently escalate
   from shadow-only to a paid comparison mode.

## Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Stage 1 shadow assessment throws an unexpected exception on unusual real data | Low (every attach point has its own try/except, tested) | Failure isolation already verified for M1-M6 (each milestone's own `test_shadow_failure_isolation` equivalent); rollback is a config revert + restart |
| M5's own 0%-READY calibration gap gets mistaken for "the pipeline found nothing good" | Medium | Explicitly disclosed in the M5/M6 reports and this readiness report; no stage before 3+ reads `overall_decision`/`editorial_recommendation` to gate anything |
| A future Stage 3 canary sends to the wrong scope | N/A yet - code doesn't exist | Explicitly deferred; must be built and reviewed before Stage 3 is even possible |
| Relevance REJECT enforced before calibrated | N/A yet | Stage 5 explicitly requires a separate, not-yet-started calibration milestone |

## Fallback

Documented in the runbook: `fail_open=True` by default (revert to the stable production
Copywriting path on any new-path error), never a duplicate send, never an infinite retry loop, a
serious Fact Safety `FAIL` routes to human review rather than silently falling back to "safe to
publish" (the runbook's own explicit "never fabricate publication readiness" rule).

## Rollback

Documented in the runbook: revert 5 env vars, restart 4 services, no migration exists to roll
back, no data needs restoring (all Phase 17 additions are additive `step_results` JSON).

## Preflight results

See "What is ready" above - `OVERALL: PASS`, 9/9 checks, real run against the actual repository.

## Test results

9/9 `tests/test_phase17_cutover_readiness.py` passing. Ruff/Mypy clean on both new files
(`schemas/phase17_rollout_policy.py`, `scripts/phase17_cutover_preflight.py`).

## Canary plan

Outlined in the runbook (Stage 3) - explicitly not executable today (requires new routing code
and a separate human authorization); included here for planning continuity only.

## Cost controls

Stage 1 (the only stage this package prepares for immediate authorization) is zero-cost by
construction - all 5 gated components are deterministic-only in `shadow` mode, zero LLM calls.
Any later stage's cost controls are inherited unchanged from M3/M4/M4.1's own already-proven
`--confirm-paid-calls` discipline.

## Acceptance checklist

- [x] Feature-mode inventory complete and confirmed safe-by-default.
- [x] Rollout policy schema created, versioned, no mutable defaults.
- [x] Preflight script created, read-only, passes on real current state.
- [x] Runbook created with exact stage/config/Docker/rollback detail.
- [x] Canary plan outlined (not executable yet, by design).
- [x] Fallback and rollback both explicit and documented.
- [x] Tests passing, Ruff/Mypy clean.
- [ ] Human authorization for Stage 1 — **pending, requires the user**.
