# Phase 17 M6.1 — Production Cutover Runbook

**This is a runbook for a future, separately-authorized human decision. Nothing in this document
has been executed. No Phase 17 component is active in production as of this writing.**

## Prerequisites

- `checkpoint/phase17-cutover-ready` (or later) checked out, `git status` clean.
- `scripts/phase17_cutover_preflight.py` run and shows `OVERALL: PASS`.
- `docs/phase17_m6_human_acceptance_packet.md` reviewed by a human editor.
- Explicit, separate human authorization for the specific stage being entered (§"Staged rollout"
  below) — this runbook does not grant that authorization itself.

## Backup / checkpoint

Before any config change: `git log -1` to record the exact commit; confirm the current
`docker compose ps -a` state (workers/`telegram_bot` Exited) as the known-good rollback baseline.
No database migration is introduced by Phase 17 M0-M6 (all state lives in existing
`EditorialTask.workflow` JSON) — there is nothing to back up beyond the normal DB backup cadence.

## Staged rollout

| Stage | What changes | Config |
|---|---|---|
| 0 (current) | Nothing. All Phase 17 modes off. | All defaults. |
| 1 | Deterministic planning/assessment only, shadow. | `editorial_brief_mode=shadow`, `channel_relevance_mode=shadow`, `adaptive_length_mode=shadow`, `beginner_copywriting_mode=shadow`, `editorial_completeness_mode=shadow`. Zero production behavior change — every one of these is purely additive to `step_results`, verified by this milestone's own byte-identical-output tests (M1-M6). |
| 2 | A new Copywriting candidate is produced (comparison mode) for controlled tasks, never delivered. | `beginner_copywriting_mode=comparison` (or `adaptive_length_mode=comparison`), gated by the existing `--confirm-paid-calls` discipline already proven in M3/M4/M4.1 — **real cost per call, human-approved batch only**. |
| 3 | Human-selected canary delivery to a preview scope only. | Requires new code not built in M0-M6 (routing a specific candidate to a specific chat) — **not implemented**; flagged as the next real engineering task before Stage 3 can happen. |
| 4 | Broader production rollout. | Requires Stage 3 results first. |
| 5 | Optional relevance REJECT enforcement, after separate calibration. | Requires a dedicated calibration milestone — M5's own report already shows the completeness/Fact-Safety gate is not ready for enforcement (0% READY rate, disclosed gap). |

**This milestone (M6.1) only prepares readiness for Stage 1.** Stages 2-5 each need their own
separate human authorization and, for 3-5, additional engineering not yet built.

## Exact config changes (Stage 1 only)

Manual `.env` edits (never automated by this runbook or by Claude):
```
EDITORIAL_BRIEF_MODE=shadow
CHANNEL_RELEVANCE_MODE=shadow
ADAPTIVE_LENGTH_MODE=shadow
BEGINNER_COPYWRITING_MODE=shadow
EDITORIAL_COMPLETENESS_MODE=shadow
```

## Exact Docker commands (Stage 1)

```
docker compose restart backend automation_worker news_analysis_worker content_worker
```
`telegram_bot` does not need a restart for Stage 1 (no Telegram-facing behavior changes).

## Canary scope (Stage 3, future, not yet authorized or built)

5-10 fresh real `NewsEvent`s, preview chat only, one candidate per event, manual human
verification per M6's own human acceptance packet format, explicit user confirmation required
before any single message is sent.

## Expected logs (Stage 1)

`editorial_brief_started`/`_completed`, `article_topic_assessment_started`/`_completed`,
`adaptive_length_plan_started`/`_completed`, `beginner_friendly_plan_started`/`_completed`,
`completeness_assessment_started`/`_completed` — all `INFO` level, metadata only (no raw
content/secrets, verified by each milestone's own tests).

## Validation queries (Stage 1)

Spot-check a handful of recent `EditorialTask.workflow` rows for the new keys
(`editorial_brief`, `channel_relevance`, `adaptive_length_plan`, `beginner_friendly_plan`,
`editorial_completeness`, `calibrated_fact_safety`) under `step_results["intelligence"]`/
`["copywriting"]`/`["quality"]` as appropriate — confirm `ContentDraft.updated_at` is unchanged
for the same rows (no mutation).

## Rollback triggers

Any of: unexpected error rate increase in worker logs; any `*_failed` log line volume spike;
CPU/latency regression on `backend`/workers.

## Rollback commands

Revert the five env vars to `off`, `docker compose restart backend automation_worker
news_analysis_worker content_worker`. No migration to roll back (none exists). No data to restore
(`step_results` additions are additive JSON, harmless if left in place after rollback).

## Post-cutover acceptance (Stage 1)

Confirm: zero change in `ContentDraft` creation rate/content; zero new LLM calls (compare
`AIExecution` row counts before/after); zero Telegram send-path change; new `step_results` keys
present and well-formed on a sample of new tasks.

## Cost monitoring

Stage 1 is zero-cost by construction (all five modes are deterministic-only in shadow). Stage 2+
must use the same `--confirm-paid-calls` + real-cost-estimate-then-confirm discipline M3/M4/M4.1
already established — never a silent, un-budgeted paid call.

## Incident handling

Any Stage 1 anomaly → rollback (above) → file a blocker note in
`docs/phase17_final_engineering_completion_report.md`'s own "Known limitations" section → resume
only after root cause is understood.
