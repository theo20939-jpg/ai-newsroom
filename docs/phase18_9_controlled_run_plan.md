# Phase 18.9 M4 — Controlled Execution Design

Status: design only, not executed. No paid call has been made to produce this document.

## 1. Method selection (brief's own priority order)

1. Explicit task IDs in an isolated queue - no isolated-queue infrastructure exists in this
   codebase (M0 §1) - not available as-is.
2. **Explicit NewsEvent/EditorialTask IDs through an existing bounded script/tool - CHOSEN.**
   `scripts/run_content_generation.py::run_content_generation_for_event(event_id)` already exists,
   already production-proven, already Telegram-free (M0 §10). For analysis, no equivalent
   ready-made single-task script exists, but the exact same underlying primitives
   (`WorkflowRunner(executor).run(session, task_id)`) that `run_analysis_cycle()` itself uses can
   be invoked directly against an explicit, pre-selected `task_id` - this is priority 5's own
   "minimal additive bounded runner using existing workflow contracts," used for exactly the reason
   the brief anticipates: no ready-made single-task analysis script exists yet.
3-4. Not needed - method 2 is sufficient and safer than a dedicated-queue or
   concurrency-1-worker-restart approach, since it touches zero shared eligibility query at all.

**No parallel architecture created.** Both paths reuse `CapabilityExecutor`, `WorkflowRunner`,
`WorkflowRegistry`, `ContentDraftService`, `CostTracker`, `PricingCatalog` exactly as production
does - the only new code is a thin, explicit-ID-list driver for the analysis side (M5), mirroring
`run_content_generation_for_event()`'s own shape.

## 2. Selected records

**Analysis batch (10 explicit, pre-existing, real `EditorialTask` IDs - already `CREATED`, already
eligible, no new task creation needed):**

```
5373e9be-32cf-4ff0-adbb-3175dfdf0bf4  (event 1caf5414-8909-473e-8147-9172ca9f989c)
cfd2c02c-3563-4eb1-b4b8-f6048f9cccd8  (event 23313337-3b49-43f3-9391-11a7dbd15950)
637a5884-bce6-495a-b7d1-2d6abc651db9  (event 30db1433-159e-4b4a-8f84-bb85e88ac1b8)
feebc2f5-f937-4548-88b0-6a5271bc7a60  (event 3af00a36-3a5a-4ab1-b7c7-5639938e2d2b)
30265780-87ec-4291-b6cf-78afbcef5640  (event 4b0342f3-3e4e-495d-b155-8f188ec474fc)
9b025ae1-61fb-4a09-96c8-422fc2d8e5b0  (event 7490f7fb-97a7-4ff9-812a-26c017f4554d)
3f8b0426-8d47-4907-bbb6-7e83e3492544  (event aa647b8d-bb9a-4e3c-9d46-637ba907284b)
cb38e8aa-5fb0-49e0-8341-5f1619f8970e  (event 563b450b-f815-4d6d-b798-a8600b8b74c5)
9048af9d-dc43-45b0-ae7d-2d6ad845c147  (event d7796377-9ba8-4605-91c3-f6911852c4bc)
65410222-5e99-459b-8470-078b2379b867  (event 028165b1-274c-4bcc-a58b-2fbfeb3b8641)
```

Selection criterion: the 10 oldest `CREATED` `NEWS_ANALYSIS` tasks among the 68 currently within
the 2-hour freshness window (deterministic `ORDER BY created_at ASC, id ASC LIMIT 10`) - real,
already-collected news, no synthetic data.

**Content-generation batch (up to 5, source depends on M9's real results - this is the honest,
disclosed part of this plan):**

Primary source: up to 5 events from *this run's own* analysis batch (§ above) that reach
`COMPLETED` with `score >= 65` (M9 decides). Reserve pool (real, already-`COMPLETED`,
already-analyzed, already-qualifying, already-backlogged - used only if the primary source yields
fewer than 5):

```
8c5a7ed0-580c-4636-80dc-e615a0a96be1  (score 68, "ChatGPT Health is rolling out to users in the US...")
2aaf8e29-b726-49a6-95e5-86e371108195  (score 68, "Amazon accused of poaching HBO employees in Warner...")
a53e25a9-473d-4e05-8088-738f0d2b731a  (score 68, "Android May Soon Restrict On-Device ADB...")
e8120095-23db-407c-a3d7-df0a4bb08f96  (score 72, "xAI ... Grok Build ... SSH ...")
2cc431ac-5894-4ceb-8b6c-00e696c7081f  (score 78, "The OpenAI Models That Hacked Hugging Face Were...")
```

(130 real qualifying reserve candidates exist in total; only the first 5 are listed/proposed.)
**Any deviation from these exact IDs - substituting reserve-pool members, or drawing from the
primary batch instead - counts as a plan change requiring new authorization**, per the brief's own
explicit rule.

## 3. Execution parameters

| Parameter | Value |
|---|---|
| Analysis task count | ≤ 10, explicit allowlist only |
| Content task count | ≤ 5, explicit allowlist only |
| Concurrency | 1 (sequential `for` loop - matches production's own existing shape, M0 §7) |
| Prefetch | N/A (no broker); the allowlist itself is fixed-size, never re-queried mid-run |
| Retry behavior | Existing per-step `max_attempts=3` (unchanged, reused as-is - not disabled, not modified) |
| Maximum runtime | No hard wall-clock cap proposed beyond natural completion of 15 tasks at ~2-5s/task observed historically (M0 §2's own real avg latency data) - expected well under 5 minutes total: stop condition is task-count/budget, not a timer |
| Budget stop condition | Cumulative `AIExecution` cost (read after every task, M8/M10) must not exceed $1.00; **recommend** also setting `LLM_BUDGET_MODE=enforce` for the run's duration as a real, existing, code-level backstop (M3 §6) - a `.env` change requiring its own explicit authorization, listed separately in the checkpoint |
| Manual stop command | `Ctrl+C` / process kill on the bounded runner script (single-process, single-threaded execution - no background worker to separately stop) |
| Automatic stop condition | After the last allowlisted ID is processed; also stop immediately on: budget ceiling reached/would be exceeded, an unexpected model/provider in a call's `AIExecution.model`, 2 consecutive task failures (a conservative "stop on repeated failure" threshold, since 0 historical retries/failures were expected) |
| Telegram sends | Zero - structurally impossible via this path (M0 §10) |
| Meme generation | Zero - no meme capability is in either workflow's step list |
| Publication | Zero - `ContentDraft` creation is not publication; nothing in this plan calls any publish path |

## 4. Expected database records

- Up to 10 `EditorialTask` rows transition `CREATED → RUNNING → COMPLETED`/`FAILED` (no new
  `NEWS_ANALYSIS` tasks created - all 10 already exist).
- Up to 5 new `CONTENT_GENERATION` `EditorialTask` rows created (via
  `run_content_generation_for_event()`'s own `workflow_service.create_task()` call) plus up to 5
  new `ContentDraft` rows.
- Up to (10×3 + 5×4) = 50 new `AIExecution` rows in the typical/expected case (10 analysis tasks ×
  3 paid capabilities + 5 content tasks × up to 4 paid capabilities, though content-generation
  research/intelligence are usually skipped per M0 §2 - realistically closer to 10×3 + 5×2 = 40).

## 5. Success criteria

- Every processed ID is one of the explicitly listed IDs above (or, for content, the disclosed
  primary-then-reserve selection rule) - zero unrelated rows touched.
- Cumulative real `AIExecution` cost for the run ≤ $1.00.
- Zero Telegram messages sent (verified post-run against `telegram_bot` logs / no
  `send_editorial_card`/`send_news_with_image_preview` call in the execution path at all).
- Both `news_analysis_worker` and `content_worker` remain `stopped` throughout and after (the
  bounded runner is a separate, one-shot script invocation, never the worker container).
- `meme_opportunity_mode`/`meme_safety_gate_mode` still `off`; calibration versions still `v1`.
- Pending migration still unapplied.

## 6. Rollback / recovery behavior

- **Analysis tasks**: if a task fails partway (a step exhausts `max_attempts`), `WorkflowRunner`
  itself already persists it as `FAILED` cleanly (M0 §5) - no manual rollback needed, and (per M0
  §6) it will never be silently retried or duplicated. If the *runner script itself* crashes
  mid-batch (e.g., killed), any task already claimed (`RUNNING`) would become a new instance of the
  known "stuck `RUNNING`" gap (M0 §6) - **mitigation**: process one task fully (through to
  `COMPLETED`/`FAILED`, committed) before starting the next, so at most one task could ever be left
  `RUNNING` by an interruption, and its `task_id` would be known/logged immediately for manual
  follow-up (not a silent loss).
- **Content tasks**: same per-task durability via `WorkflowRunner`; a `ContentDraft` is only ever
  created after `COMPLETED` (M0 §10) - a crash before that point leaves no partial `ContentDraft`.
- **No destructive rollback is ever needed** - nothing in this plan deletes or overwrites existing
  rows; "rollback" here means "stop cleanly and report exactly what state was reached," not "undo."
