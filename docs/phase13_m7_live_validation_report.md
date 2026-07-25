# Phase 13 — M7 Live Validation Report

## Status: SUCCESS

Executed exactly per `docs/phase13_m7_live_validation_plan.md` with the refined creation
mechanism from `docs/phase13_m7_authorization_check.md` (`workflow_service.create_task()` →
fresh `NEWS_ANALYSIS` `EditorialTask` UUID → direct `WorkflowRunner.run(task_id)`), under the
human authorization granted in this session.

## Procedure followed

1. **Baseline recorded** (before creation): `EditorialTask` counts — CREATED 4723, RUNNING 0,
   COMPLETED 3, FAILED 1; `CONTENT_GENERATION` task count 3; `ContentDraft` count 2.
2. **Controlled artifact created**: one real, uniquely-named, clearly-labeled `NewsSource`
   (`phase13-m7-live-validation-<uuid>`) and `NewsEvent` (title explicitly states "synthetic,
   not real news... see docs/phase13_m7_authorization_check.md"; content explicitly and
   repeatedly labeled as synthetic validation content, not a real news item), then one
   `EditorialTask` via `workflow_service.create_task()` with the **default** registry (the real,
   unmodified `NEWS_ANALYSIS` `WorkflowDefinition`) — confirmed by a fresh read: `status ==
   CREATED`, `workflow_name == "NEWS_ANALYSIS"`.
3. **Live execution**: real `assemble_ai_integration_layer(settings, prompt_repository)` (no
   `redis_client` override, matching the established production pattern), real
   `CapabilityExecutor`/`WorkflowRunner`, direct `runner.run(session, TASK_ID)` for exactly the
   one created `task_id` — no eligibility query, no `run_analysis_cycle()`, no batch worker
   started at any point.
4. **Post-execution verification**: fresh DB reads, diffed against the recorded baseline.

## Created task ID

`d48f870d-f36f-41c4-9dd0-471eee699cdb`
(event: `a3c74eac-2bc1-447d-beb0-80179cf85205`, source: `f752541e-0045-4843-b365-6a3c710a0ada`)

## Workflow execution result

**`COMPLETED`**, 1 iteration used, zero retries needed on any step.

## Step results (all `SUCCESS`, attempt 1, in order)

| Step | Status | Attempt | Notes |
|---|---|---|---|
| `research` | SUCCESS | 1 | Real `ResearchCapability` output — facts/confidence/gaps, in Russian (the configured `default_content_language`) |
| `intelligence` | SUCCESS | 1 | Real `IntelligenceCapability` output — `significance: 0.01` |
| `engagement_analysis` | SUCCESS | 1 | Real `EngagementCapability` output — `engagement_potential_score: 0.01`, `audience_fit`/`reasoning` present and schema-valid |
| `scoring` | SUCCESS | 1 | Real `ScoringCapability` output — `score: 0` |

All four scores are near-zero. This is **expected and correct**, not a defect: the synthetic
`NewsEvent` content was explicitly and repeatedly labeled, in its own text, as fabricated
validation material with no real news value ("Synthetic content generated solely for Phase 13 M7
live pipeline validation - not a real news event"). The real model correctly recognized this and
scored accordingly low, rather than fabricating enthusiasm about placeholder content — evidence
the pipeline's real judgment is working as intended, not evidence of a bug.

## Provider call count

**4** — one real `call_generate()` invocation per step (research, intelligence, engagement,
scoring), each succeeding on its first attempt. Well within the disclosed maximum of 12
(structural ceiling if every step had needed its full `max_attempts=3` retry budget) and at the
absolute best-case floor of 4.

## Final task state

`EditorialTask.status == COMPLETED`, `retry_count == 0`.

## `CONTENT_GENERATION` boundary verification

`CONTENT_GENERATION` task count: **3 → 3, zero delta.** Direct query for any other
`EditorialTask` row attached to this same `NewsEvent`: **zero rows.** No `CONTENT_GENERATION`
task was created, directly or indirectly, as a result of this execution.

## `ContentDraft` verification

`ContentDraft` count: **2 → 2, zero delta.** Direct query for any `ContentDraft` row referencing
this task: **zero rows.**

## Full count diff (baseline → after)

| Metric | Before | After | Delta |
|---|---|---|---|
| `EditorialTask [CREATED]` | 4723 | 4723 | 0 net (task created then left this state) |
| `EditorialTask [RUNNING]` | 0 | 0 | 0 (never left stuck mid-claim) |
| `EditorialTask [COMPLETED]` | 3 | 4 | **+1 (exactly this task)** |
| `EditorialTask [FAILED]` | 1 | 1 | 0 |
| `CONTENT_GENERATION` tasks | 3 | 3 | 0 |
| `ContentDraft` rows | 2 | 2 | 0 |

Every delta is exactly what the plan required: the one target task moved from nonexistent →
`CREATED` → `COMPLETED`; nothing else in the 4,723-deep real backlog, and nothing in the
`CONTENT_GENERATION`/`ContentDraft` boundary, was touched.

## Cleanup / preservation

Per the approved policy (`docs/phase13_m7_authorization_check.md` §4): **preserved, not
deleted.** The `NewsSource`/`NewsEvent`/`EditorialTask` created in this validation remain in the
database, clearly and permanently labeled in the event's own title/content as a Phase 13 M7
synthetic validation artifact, not real news — this report and the created row together are the
durable evidence that M7 was performed and succeeded.

## Unexpected occurrences

None. No step deviated from the plan; no `TaskAlreadyRunningError`/`TaskAlreadyCompletedError`;
no gateway error; no schema-validation failure; no unexpected count delta. Nothing required
stopping or escalation.

## Git status

```
 M capabilities/registry.py
 M core/config.py
 M docker-compose.yml
 M tests/test_capability_registry.py
 M tests/test_openai_strict_schema_compliance.py
 M tests/test_phase10_capability_registration.py
 M tests/test_phase9_cross_cutting_regression.py
 M tests/test_phase9_research_intelligence_integration.py
 M tests/test_settings_phase7.py
 M tests/test_workflow_runner.py
 M workflows/runner.py
?? capabilities/engagement_capability.py
?? prompts/engagement/
?? tests/test_analysis_worker_cycle.py
?? tests/test_analysis_worker_main.py
?? tests/test_engagement_capability.py
?? tests/test_news_analysis_integration.py
?? worker/analysis_cycle.py
?? worker/analysis_main.py
```

Unchanged from the M6 gate — the live validation touched only the database (one new
`NewsSource`/`NewsEvent`/`EditorialTask` row set, real provider calls) and made zero changes to
any repository file. Nothing staged, nothing committed.

---

PHASE 13 M7 LIVE VALIDATION COMPLETE
