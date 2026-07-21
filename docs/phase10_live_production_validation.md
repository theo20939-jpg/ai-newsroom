# Phase 10 — Live Production Validation
## OpenAI Smoke + Real End-to-End CLI Run

**Status: CLOSED — validation chronology complete.** This document records all three live
validation attempts, in order, without erasing or softening the two genuine failures that
preceded success:

1. **Attempt 1** (below) — blocked by an OpenAI account quota/billing issue before any pipeline
   call was made.
2. **Attempt 2** (below) — smoke passed, but the real CLI run exposed a genuine, reproducible
   OpenAI Structured Outputs strict-schema incompatibility (`400 Bad Request` at the `research`
   step) — a real defect, not a fluke, root-caused by code inspection and confirmed by a
   dedicated cross-phase remediation effort (`docs/openai_structured_outputs_blocker_audit.md`
   onward).
3. **Cross-phase remediation, M0–M5** — implemented and fully verified offline (see
   `docs/openai_structured_outputs_remediation_m0_m5_completion_report.md`): 727/727 tests
   passing, 0 regressions, exact approved 20-file scope.
4. **Attempt 3 / M6** (§ "M6 — Final Controlled Live Validation" below) — **PASSED**. The exact
   same class of failure that blocked Attempt 2 did not recur; the full pipeline completed for
   real, end to end, with a real `ContentDraft` persisted.

Attempts 1 and 2's original sections are preserved below, unedited, exactly as they were written
at the time — this section only adds the closing summary and status line.

---

## Executive Summary

After the operator resolved the OpenAI account's billing/quota issue, the live smoke test
(`scripts/smoke_test_openai_adapter.py`) was re-run exactly once and **succeeded** — a real
response was returned from `gpt-5.6-terra`. Per instruction, the pipeline then proceeded to a real,
default-production-path invocation of `scripts/run_content_generation.py` against a real, existing
`NewsEvent` already in the database. This run also made real API calls — `CapabilityRegistry`
resolved all five Capabilities, a real `EditorialTask` was created, and `WorkflowRunner` began the
real, four-step `CONTENT_GENERATION` chain. The `research` step's real Gateway call, however, was
rejected twice by OpenAI with **HTTP 400 Bad Request** (both the primary candidate and the
fallback), so the step — and therefore the whole task — ended `FAILED`. No `ContentDraft` was
attempted (correct, per Contract §7.1/§9's design). Code inspection (no further API calls) points
to a specific, reproducible, pre-existing cause: this repository's `OpenAIAdapter` always sends
`strict: true` in the Structured Outputs payload for every `response_mode="json_schema"` request,
but none of this codebase's prompt `output_schema` YAML files (Research, Intelligence, Copywriting,
Quality, Scoring — all of them, not something Phase 10 introduced) declare
`additionalProperties: false`, which OpenAI's Structured Outputs feature requires under `strict:
true`. This defect predates Phase 10 (it lives in Phase 6-8's prompt-authoring convention and
Phase 7's adapter payload construction) but was never previously exercised against the real API —
`scripts/run_content_generation.py` is this repository's first production code path to ever make a
real, structured-output OpenAI call, exactly as the Implementation Plan's own Risk R1 anticipated.
No fix was attempted (out of scope for this session; no code was modified).

---

## OpenAI Live Smoke (re-run)

**Command executed**:
```
python scripts/smoke_test_openai_adapter.py
```

**Result**: **SUCCESS**
```
Requesting model: gpt-5.6-terra (no substitution will occur if unavailable)
SUCCESS
resolved model: gpt-5.6-terra
token usage: input=16 output=9
response preview: "I'm online and ready."
```

One real network call, no retry needed. This confirms the credential, `ENABLED_PROVIDERS` gating,
and `OpenAIAdapter`'s plain-text (non-structured-output) request path are all correctly configured
and reach the real OpenAI API successfully.

---

## Test NewsEvent

Per instruction ("if the repository already contains a suitable NewsEvent, prefer using it"), an
existing, real `NewsEvent` row already in the database was selected — no new row was created:

- **id**: `cf8eaaab-4499-48ed-9bfb-3b6b593adec2`
- **title**: "Welcome Gemma 4: Frontier multimodal intelligence on device"
- **category**: `UNKNOWN`
- **content length**: 59 characters
- **Pre-existing state checked before use**: one prior `EditorialTask` existed for this event
  (`NEWS_ANALYSIS` workflow, status `CREATED`) — since `EditorialTask` uniqueness is enforced per
  `(event_id, workflow_type)` (Contract §4, unchanged), this does not block a `CONTENT_GENERATION`
  task for the same event. **No `CONTENT_GENERATION` task and no `ContentDraft` existed for this
  event before this run** — confirmed by direct query before proceeding, so the run's outcome
  could be attributed unambiguously to this one invocation.

---

## Real CLI Invocation

**Command executed**:
```
python -m scripts.run_content_generation cf8eaaab-4499-48ed-9bfb-3b6b593adec2
```

Default production behavior throughout — no `capability_registry` injected, no provider
monkeypatched, `assemble_ai_integration_layer()` not bypassed. Confirmed by the log output itself:
`capabilities.registry` logged all five real registrations (`scoring`, `quality`, `research`,
`intelligence`, `copywriting`) before any task work began — the real, production boot path.

**Full log output**:
```
2026-07-21 13:22:10,089 | INFO | capabilities.registry | Registered capability scoring version 1
2026-07-21 13:22:10,089 | INFO | capabilities.registry | Registered capability quality version 1
2026-07-21 13:22:10,089 | INFO | capabilities.registry | Registered capability research version 1
2026-07-21 13:22:10,089 | INFO | capabilities.registry | Registered capability intelligence version 1
2026-07-21 13:22:10,089 | INFO | capabilities.registry | Registered capability copywriting version 1
2026-07-21 13:22:10,335 | INFO | services.workflow_service | Created EditorialTask 2213def3-90ec-4d86-a527-21785438fa0f: event=cf8eaaab-4499-48ed-9bfb-3b6b593adec2 workflow=CONTENT_GENERATION priority=B
2026-07-21 13:22:10,350 | INFO | workflows.runner | Workflow CONTENT_GENERATION starting for task 2213def3-90ec-4d86-a527-21785438fa0f
2026-07-21 13:22:10,385 | INFO | integrations.llm_gateway.routing.engine | routing_decision
2026-07-21 13:22:12,824 | INFO | httpx | HTTP Request: POST https://api.openai.com/v1/responses "HTTP/1.1 400 Bad Request"
2026-07-21 13:22:12,828 | INFO | integrations.llm_gateway.fallback.policy | fallback
2026-07-21 13:22:13,079 | INFO | httpx | HTTP Request: POST https://api.openai.com/v1/responses "HTTP/1.1 400 Bad Request"
2026-07-21 13:22:13,082 | INFO | integrations.llm_gateway.fallback.policy | fallback
2026-07-21 13:22:13,082 | INFO | capabilities.research_capability | capability_call_failed
2026-07-21 13:22:13,082 | ERROR | workflows.runner | Workflow CONTENT_GENERATION: required step research failed for task 2213def3-90ec-4d86-a527-21785438fa0f
2026-07-21 13:22:13,093 | ERROR | __main__ | content_generation_task_failed
```

---

## End-to-End Execution Result

**FAILED at step 1 of 4 (`research`)** — real Gateway request made, real `400 Bad Request`
returned twice (primary candidate + one fallback candidate), then `AllProvidersFailedError` →
`PermanentCapabilityError` → `PermanentStepFailureError`, exactly per the frozen error-translation
chain (`capabilities/gateway_call.py`, unmodified). `intelligence`/`copywriting`/`quality` never
ran. `ContentDraftService` was never invoked — correct: `run_content_generation_for_event()`'s
three-outcome branch correctly identified `result.status != "COMPLETED"` and logged
`content_generation_task_failed` without attempting persistence.

**Root cause (code-inspection only, no further API calls made to confirm)**:
`integrations/llm_gateway/providers/openai_adapter.py:227-236`'s `_build_payload()`
unconditionally sets `"strict": True` inside `text.format` whenever `request.response_mode ==
"json_schema"`:
```python
payload["text"] = {
    "format": {
        "type": "json_schema",
        "name": "structured_output",
        "schema": request.response_schema,
        "strict": True,
    }
}
```
OpenAI's Structured Outputs feature requires, under `strict: true`, that every object in the
schema declare `"additionalProperties": false`. Confirmed by direct grep: **no prompt file in this
repository's `prompts/` tree sets `additionalProperties` anywhere** — `prompts/research/v1.yaml`'s
`output_schema` (the one the failing `research` step actually sent) is a representative example:
```yaml
output_schema:
  type: object
  properties:
    facts: {type: array}
    confidence: {type: number}
    gaps: {type: array}
  required: [facts, confidence, gaps]
```
— no `additionalProperties: false`. This shape (and the identical pattern in every other prompt:
`intelligence/v1.yaml`, `copywriting/v1.yaml`, `quality/v1.yaml`, `quality/v2.yaml`,
`scoring/v1.yaml`) is exactly what OpenAI's API rejects with `400 Bad Request` under `strict:
true`. This is consistent with, though not empirically re-confirmed by, the observed failure (no
additional live call was made solely to prove this hypothesis further, per the instruction to
minimize real API calls — the code-level evidence is unambiguous enough to report with high
confidence without spending another billed call).

**This is not a Phase 10 defect** in the sense of something M0-M4 introduced: `openai_adapter.py`
is Phase 7 code (unmodified by Phase 10, confirmed via `git diff --name-only` showing no change to
it), and every existing prompt schema (Phase 6/8/9's Research/Intelligence/Quality/Scoring, not
just Phase 10's new Copywriting one) shares the same gap. It was never caught before because, per
the Implementation Plan's own Risk R1 and the Final Architecture Re-Audit's MINOR-1 finding,
**no production code path in this repository had ever made a real, structured-output OpenAI call
before this session** — every prior test used `FakeLLMGateway`/`FakeProviderAdapter`, which never
enforces OpenAI's real schema constraints. `scripts/run_content_generation.py` (M4) is the first
to do so for real, and immediately surfaced it.

---

## Database Verification

```
status: TaskStatus.FAILED
research step: status=FAILED, attempt=1,
  error="All candidates exhausted for capability 'unknown' (objective=best_quality,
         reason=all_candidates_failed)"
```
- **EditorialTask exists**: yes — `id=2213def3-90ec-4d86-a527-21785438fa0f`.
- **Correct workflow**: yes — `CONTENT_GENERATION`.
- **Final task status**: `FAILED` (not `COMPLETED` — the run did not succeed).
- **Step results for research/intelligence/copywriting/quality**: only `research` has an entry
  (`FAILED`); the other three never ran, per `WorkflowRunner`'s own required-step-failure semantics
  (unchanged, frozen).
- **ContentDraft rows created by this run**: **zero** — correct, since the task never reached
  `COMPLETED`.
- No `ContentDraft.task_id` association to verify (none was created).
- No title/body/hashtags to verify (never generated).

---

## LLM Call / Retry Summary

- **Smoke test**: 1 real call, 1 success.
- **Pipeline run**: 2 real calls (primary `research` attempt + 1 fallback candidate attempt, both
  rejected with `400`), 0 successes, 0 further steps reached. `FallbackPolicy`'s own retry/fallback
  mechanics (frozen, unmodified) accounted for the second call — this script made no manual retry
  itself.
- **Total real API calls this session**: 3 (1 smoke + 2 pipeline-internal fallback attempts).
- No additional diagnostic call was made beyond what the pipeline itself triggered, per the
  instruction to minimize real API calls.

---

## Observed Warnings or Anomalies

- **Provider errors**: yes — two `400 Bad Request` responses from `POST
  https://api.openai.com/v1/responses`, both for the `research` step's structured-output request.
- **Retries**: one automatic fallback-to-second-candidate retry, itself governed by the frozen
  `FallbackPolicy` (Phase 7, unmodified) — not a manual retry by this session.
- **Timeouts**: none observed.
- **Malformed structured output**: not reached — the request itself was rejected before any
  response body could be validated.
- **Schema validation failure**: not reached, for the same reason (the failure occurred at OpenAI's
  request-validation layer, before this repository's own `_floor_validate()` ever ran).
- **Persistence errors**: none — `ContentDraftService` was never invoked.
- **Duplicate drafts**: none — zero drafts were created.
- **Swallowed exceptions**: none — the failure was logged distinctly
  (`content_generation_task_failed`) exactly as designed, never silently absorbed.

---

## Git and Secret Hygiene

```
git status --short
```
shows only the pre-existing Phase 10 M1-M4 implementation diff (the same four modified tracked
files as before) plus the already-present Phase 9/9.5/10 process documents, including this
session's report files. **No production code, test, or architecture file was modified by this
live-validation session.** `.env` does not appear in `git status` output (still ignored, still
untracked). No secret was printed or written to any tracked file at any point in this session.

---

## Definition of Done Closure

| Item | Status |
|---|---|
| Real OpenAI live smoke succeeds | **PASS** — re-run after the operator resolved billing; one real call, real success. |
| Full manual CLI run against a provisioned real environment produces an observable `ContentDraft` row | **FAIL** — the run was real (not faked, not simulated) and reached the real production path, but ended `TaskStatus.FAILED` at the `research` step due to a real OpenAI `400 Bad Request`, before any `ContentDraft` could be attempted. |

The second Definition-of-Done item remains unsatisfied. This is not a case of the validation
attempt being skipped or faked — it is a genuine, reproducible failure of the real pipeline against
the real API, with a specific, credible root cause identified by code inspection (see above). No
fix was applied (out of scope for this session).

---

## Final Verdict (Attempt 2)

PHASE 10 LIVE VALIDATION BLOCKED — REAL CLI RUN FAILED

---

# M6 — Final Controlled Live Validation

**Status: PASSED.** Performed after cross-phase remediation M0–M5 (schema-compatibility Track A +
observability Track B) was implemented and fully verified offline. Authorized for exactly one
smoke check and one real CLI run — no exploratory calls, no manual retries beyond what the
production `FallbackPolicy` itself would do automatically.

## Pre-flight

`OPENAI_API_KEY`/`ENABLED_PROVIDERS`/`REDIS_UNAVAILABLE_POLICY` confirmed configured (boolean-only
checks, no values printed); Postgres and Redis confirmed reachable; migrations confirmed current
(single head, `8941ebf13fb0`); `tests/test_openai_strict_schema_compliance.py` re-confirmed
16/16 passing immediately before the live call; git state confirmed identical to M5's closing
state (HEAD `89e111d`, same 13-file tracked diff, same remediation files untracked) — zero scope
drift.

## OpenAI Smoke

`python scripts/smoke_test_openai_adapter.py` — **SUCCESS**. Model `gpt-5.6-terra`, input=16/
output=9 tokens, one real network call.

## Validation Event

The previously-used event (`cf8eaaab-4499-48ed-9bfb-3b6b593adec2`) was inspected, not blindly
reused: it already carried a `FAILED` `CONTENT_GENERATION` `EditorialTask` from Attempt 2. To keep
this validation's evidence unambiguous, one new, minimal, clearly-marked `NewsEvent` was created
instead, via the same repository-native ORM path a real collector would use — no schema change,
no bulk data:
- `event_id = 6ada5600-a08a-40a2-b918-99b3b470ab1d`
- title: `"[M6 VALIDATION] OpenAI GPT-5.6 family adds native multimodal reasoning to enterprise tier"`
- category: `AI`; zero prior `EditorialTask` rows confirmed before the run.

## Real CLI Invocation

```
python -m scripts.run_content_generation 6ada5600-a08a-40a2-b918-99b3b470ab1d
```
Full default production path — real `Settings`, real `assemble_ai_integration_layer()`, real
`OpenAIAdapter`/`RoutingGateway`/`BudgetGuard`/`CapabilityRegistry`, real `WorkflowRunner`, real
`ResearchCapability`/`IntelligenceCapability`/`CopywritingCapability`/`QualityCapability`, real
`ContentDraftService`, real Postgres, real Redis. No fakes, no monkeypatches, no bypasses, no
manual `step_results`/`ContentDraft` insertion.

**Result: `TaskStatus.COMPLETED`.** All four `POST https://api.openai.com/v1/responses` calls
returned `200 OK` (research 15:08:44→15:08:50, intelligence →15:08:58, copywriting →15:09:01,
quality →15:09:08). `content_generation_succeeded` logged. Task id
`5d76b9ce-fa60-43ec-8582-99e14f987895`.

## Capability Execution

| Capability | Invoked | Result | Structured output parsed |
|---|---|---|---|
| Research | Yes | SUCCESS | Yes — `facts`/`confidence`/`gaps` |
| Intelligence | Yes | SUCCESS | Yes — `significance`/`angle`/`audience_relevance`/`recommendation` |
| Copywriting | Yes | SUCCESS | Yes — `title`/`body`/`hashtags` |
| Quality | Yes | SUCCESS (API call) — editorial judgment `passed=False` | Yes — `passed`/`issues`; the Capability call itself succeeded, its *content judgment* flagged the draft as needing revision, which is a normal, correctly-functioning outcome, not a failure |

## Structured Output Verification (§8 of the M6 mission)

- Did Research's real structured-output request now pass the exact schema-validation boundary
  that previously caused the `400`? **Yes** — `200 OK`, valid parsed output.
- Did Intelligence structured output succeed? **Yes.**
- Did Copywriting structured output succeed? **Yes.**
- Did Quality structured output succeed? **Yes** (as an API/schema matter; its editorial verdict
  was `passed=False`, an intended, correctly-functioning outcome).
- Did any provider return a strict-schema rejection? **No** — zero `400`s anywhere in this run,
  in direct contrast to Attempt 2's two consecutive `400`s at the very first call.
- Did any fallback occur? **No** — every candidate succeeded on its first attempt; no `"fallback"`
  log line appears anywhere in this run's output. Track B's enrichment logic was therefore not
  exercised live in this run (nothing failed for it to enrich) — its correctness rests on M4's
  offline unit tests (4/4 passing, plus all 13 pre-existing `FallbackPolicy` tests unmodified),
  not on live confirmation here. This is disclosed plainly, not glossed over.

## EditorialTask Database Evidence (independently queried, not inferred from logs)

```
event_id: 6ada5600-a08a-40a2-b918-99b3b470ab1d
status: TaskStatus.COMPLETED
workflow_name: CONTENT_GENERATION
completed_steps: ['research', 'intelligence', 'copywriting', 'quality']
iteration_count: 1
```
All four `step_results` entries present, each `status: SUCCESS`, each with a non-empty `result`
dict of the correct shape. Same-pass propagation evidence, from result content correlation (the
underlying mechanism itself — `WorkflowRunner`'s per-step commit — was already mechanically
proven by `tests/test_phase10_workflow_integration.py`'s request-content inspection; this live run
re-exercises the identical, unmodified code path): Intelligence's `angle` specifically discusses
the same workflow-consolidation theme only present in Research's extracted facts; Copywriting's
title/body reflect the same facts and Intelligence's framing; Quality's `issues` specifically
critique claims present only in Copywriting's draft — each step's output is substantively
downstream of the previous ones', not independent or hallucinated in isolation.

## ContentDraft Database Evidence (independently queried)

Exactly **one** `ContentDraft` row for this task:
```
id: 2190d42d-e6e6-4f10-bc94-2a20520d1382
task_id: 5d76b9ce-fa60-43ec-8582-99e14f987895  (matches the completed EditorialTask)
type: ContentType.POST
version: 1
status: 'draft'
title: 'OpenAI GPT-5.6 Unifies Enterprise Multimodal Workflows'
body: (non-empty, matches Copywriting's result verbatim)
hashtags: ['#AI', '#OpenAI', '#EnterpriseAI', '#MultimodalAI']  (a real Python list — the
  JSON column round-trip proven live, matching Phase 10 M3's offline durability proof)
```
No duplicate. No manual repair or insertion — this row was created exclusively by
`ContentDraftService.create_from_result()` as part of the one authorized CLI invocation.

## API Calls / Retry Accounting

- **Top-level live validations intentionally initiated this M6 session**: 2 — one smoke call, one
  CLI invocation.
- **Application-internal calls made by the CLI invocation**: 4 (one per Capability: research,
  intelligence, copywriting, quality) — each a first-attempt success, zero
  `FallbackPolicy`-internal retries or candidate-fallback calls.
- **Total real OpenAI API calls this M6 session**: 5.
- **Manual retries by the operator/session**: 0.

## Git / Security Hygiene

`git status --short` immediately after the live run is byte-identical to the pre-run state (same
13 tracked-modified files, same untracked remediation files) — the live run wrote only to the
database, never to the filesystem/git tree. No secret printed, no `.env` change, no credential or
log artifact entered git scope. Per instruction, the full 727+ suite was not re-run, since no
repository file was touched by the live run.

## Remaining Issues

None found in this run. The one disclosed, pre-existing limitation: Track B's live-path
enrichment was not exercised (no failure occurred to enrich) — this is a coverage note, not a
defect, and does not block Phase 10 closure.

## Phase 10 Definition of Done — Final Reassessment

| Item | Status |
|---|---|
| Real OpenAI live smoke succeeds | **PASS** |
| Full manual CLI run against a provisioned real environment produces an observable `ContentDraft` row | **PASS** — `TaskStatus.COMPLETED`, exactly one `ContentDraft` persisted, independently verified in the database. |

Both previously-outstanding Definition-of-Done items are now satisfied.

## Final Verdict (M6)

M6 PASSED — CROSS-PHASE REMEDIATION LIVE-VALIDATED — PHASE 10 READY FOR CLOSURE
