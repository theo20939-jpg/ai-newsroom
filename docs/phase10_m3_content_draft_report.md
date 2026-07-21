# Phase 10 — Milestone M3 Report
## ContentDraft Persistence

**Status: implementation report.** Records what M3 actually built, against the frozen Architecture
Contract (`docs/phase10_production_content_pipeline_architecture_contract.md`, revision 3) and the
frozen Implementation Plan (`docs/phase10_implementation_plan.md`, Milestone 3). M2's output
(`docs/phase10_m2_workflow_integration_report.md`) was treated as accepted and re-verified against
current repository source, not re-derived from scratch. No M4 work was started.

---

## 1. Implementation Summary

`ContentDraftService` — the only component authorized to create a `ContentDraft` row (Contract
§7) — is now implemented, class-based, constructor-injected with the same `AsyncSession` the
caller already used for `WorkflowRunner.run()`, exactly per Contract §7.1 and the Implementation
Plan's own code sketch:

- `schemas/content_draft.py` (new): `ContentDraftRead`, mirroring `schemas/editorial_task.py`'s
  `EditorialTaskRead` pattern exactly. `hashtags: list[str] | None` (not `dict`), matching
  `CopywritingCapability`'s frozen output schema even though the underlying `ContentDraft.hashtags`
  column is typed `Mapped[dict | None]` — a pre-existing ORM type-hint imprecision the M0 report
  already flagged as harmless, not a new issue.
- `services/content_draft_service.py` (new): `ContentDraftService(session)` with one public method,
  `create_from_result(task_id, result) -> ContentDraftRead`. Locates the `"copywriting"` entry in
  `result.step_results` (a `list[WorkflowStepResult]`, per `schemas/workflow.py`), builds one
  `ContentDraft(type=ContentType.POST, version=1, status="draft", ...)`, and commits it in one
  `session.add()` + one `await session.commit()` + one `await session.refresh()` — a separate
  transaction from `WorkflowRunner.run()`'s own already-closed commit, exactly as Contract §7.1
  requires.

No production file outside this two-file list was created or modified. No M1/M2 file
(`capabilities/copywriting_capability.py`, `capabilities/registry.py`,
`workflows/definitions/content_generation.py`, `capabilities/quality_capability.py`,
`prompts/copywriting/v1.yaml`, `prompts/quality/v2.yaml`) was touched.

---

## 2. Exact Files Changed

**Production files created** (both explicitly authorized by Contract §3):
- `schemas/content_draft.py`
- `services/content_draft_service.py`

**Production files modified**: none.

**Test files created**:
- `tests/test_content_draft_service.py` (7 tests) — required by Contract §12's "ContentDraft
  tests" list, assigned to Milestone 3 by the Implementation Plan §10.

**Docs files created**:
- `docs/phase10_m3_content_draft_report.md` (this report).

No file outside this list was created or modified during M3.

---

## 3. Schema/DTO Design

`ContentDraftRead` fields — `id`, `task_id`, `type` (`ContentType`), `title`/`body` (`str | None`),
`hashtags` (`list[str] | None`), `version` (`int`), `status` (`str | None`), `created_at`/
`updated_at` — copied one-for-one from `ContentDraft`'s own existing ORM columns
(`database/models/content_draft.py:33-48`, re-verified this session, unmodified). No field was
invented; no unrelated internal field is exposed. `model_config = ConfigDict(frozen=True,
extra="forbid")`, matching every other read-schema in this codebase (`EditorialTaskRead`).

---

## 4. Service Behavior

`ContentDraftService.__init__(self, session: AsyncSession)` stores the session only —
constructor injection, no new session or connection opened anywhere in this file. `PromptRepository`
constructor-injection precedent (`services/budget_guard.py`'s `RedisBudgetGuard`) confirmed once
more as this class-shape's genuine precedent, per Contract §7.1.

`create_from_result(task_id, result)`:
1. `_copywriting_output(result)` scans `result.step_results` for the entry with
   `step_name == "copywriting"` and `status == "SUCCESS"`, returning its `.result` dict. Raises
   `ValueError` — loudly, not silently — if no such entry exists (§7 below covers why this matters).
2. Builds one `ContentDraft` ORM instance with `task_id`, `type=ContentType.POST`, `title`/`body`/
   `hashtags` copied verbatim, `version=1`, `status="draft"`.
3. `session.add(draft)` → `await session.commit()` → `await session.refresh(draft)` → returns
   `ContentDraftRead` via `_to_read_schema()` (mirrors `services/workflow_service.py`'s own
   `_to_read_schema()` shape exactly).

No repository-pattern redesign, no Unit of Work abstraction, no new transaction manager, no new
database dependency, no migration logic — the entire file is 89 lines, two functions plus one
two-method class.

---

## 5. Copywriting → ContentDraft Field Mapping

| Copywriting output key | `ContentDraft` column | Type at runtime | Notes |
|---|---|---|---|
| `title` | `title` | `str` | copied verbatim |
| `body` | `body` | `str` | copied verbatim |
| `hashtags` | `hashtags` | `list[str]` | copied verbatim into a `JSON` column — no serialization needed; SQLAlchemy's `JSON` type accepts a Python `list` directly, confirmed by the passing durability test (§9) round-tripping a `list[str]` through a genuinely independent connection |

`type` is always `ContentType.POST` (§13 excludes `MEME`/`SHORT`/`ANALYSIS`/`VIDEO_SCRIPT`).
`version` is always `1`. `status` is always `"draft"`. No content is reformatted, truncated, or
silently discarded — `CopywritingCapability`'s own floor-validation (Contract §5) already
guaranteed `title`/`body`/`hashtags` were present and correctly typed before this step's result was
ever persisted.

---

## 6. Transaction Semantics

- **Session ownership**: the same `AsyncSession` the caller already used for `WorkflowRunner.run()`
  — proven directly (`test_session_reuse_after_workflow_runner_commit_succeeds`), not assumed by
  analogy to Phase 9.5's `expire_on_commit=False` precondition (`database/session.py:14`,
  re-verified this session).
- **Commit boundary**: exactly one `session.add()` + one `await session.commit()` — a separate
  transaction from `WorkflowRunner.run()`'s own already-closed final commit
  (`workflows/runner.py:207`).
- **Failure semantics**: no `try/except` around the commit anywhere in `ContentDraftService` — a
  commit failure propagates uncaught to the caller (M4's future CLI script), which Contract §7.1
  requires MUST NOT swallow it. Not exercised by a dedicated test in M3 (there is no way to force a
  real commit failure against a healthy test database without faking the session, which would not
  prove anything about the real `AsyncSession`/Postgres commit path) — the guarantee here is the
  *absence* of any exception-swallowing code, confirmed by direct read of the 89-line file.

---

## 7. Duplicate/Idempotency Semantics

The frozen Contract defines **no** idempotency or duplicate-prevention mechanism for M3, and this
implementation adds none: `create_from_result()` unconditionally creates a new `ContentDraft` row
on every call, with no uniqueness check against `task_id`, no new unique constraint, and no
migration. Calling it twice for the same `task_id` would produce two `ContentDraft` rows — this is
accurate to the Contract's own scope (§7.1's "statuses this phase writes, frozen" section defines
`version` as "always `1` — Phase 10 never regenerates or re-versions a draft," which describes what
this phase *writes*, not a database-enforced constraint against being called twice). Duplicate
prevention, if ever needed, is explicitly out of scope for Phase 10 and is not invented here.

The one guard this implementation *does* add — `_copywriting_output()`'s loud `ValueError` when no
successful `"copywriting"` step exists — is not an idempotency mechanism; it is the misuse guard
Contract §7.1 implies by restricting the calling convention to "only after `COMPLETED`" (§8 below).

---

## 8. Tests Added/Modified

**`tests/test_content_draft_service.py`** (7 new tests, zero existing tests modified):

1. `test_create_from_result_persists_expected_fields` — every field (`task_id`, `type`, `title`,
   `body`, `hashtags`, `version`, `status`, `id`, `created_at`, `updated_at`) asserted correct.
2. `test_create_from_result_creates_exactly_one_row` — no duplicate/partial write.
3. `test_session_reuse_after_workflow_runner_commit_succeeds` — the session-reuse proof (§6).
4. `test_failed_workflow_run_never_produces_a_content_draft` — the misuse guard (§9 below).
5. `test_capabilities_never_import_content_draft` — mechanical AST-based check, every file under
   `capabilities/` scanned for any import naming `content_draft`.
6. `test_completed_content_generation_tasks_without_drafts_are_discoverable` — the discoverability
   proof (§9 below).
7. `test_content_draft_is_durable_to_a_genuinely_independent_connection` — the mandatory
   independent-connection durability test (Contract §12), isolated in its own section, reusing
   `tests.test_triage_orchestrator_claims.independent_session_factory()`/`real_committed_event()`
   (Phase 9 M2's own precedent) rather than the `db_session` fixture's SAVEPOINT semantics.

No test exceeds M3's scope — no CLI test was added.

---

## 9. Discoverability Proof

`test_completed_content_generation_tasks_without_drafts_are_discoverable` creates two `NewsEvent`s,
runs `CONTENT_GENERATION` to `COMPLETED` for both, creates a `ContentDraft` for only one, and then
runs the discovery query Contract §7.1 describes conceptually, against the real schema:

```python
completed = select(EditorialTask).where(EditorialTask.status == TaskStatus.COMPLETED)  # indexed column
completed_content_generation_tasks = [
    t for t in completed if t.workflow.get("workflow_name") == WorkflowType.CONTENT_GENERATION.value
]  # JSON field, filtered in Python - mirrors services/workflow_service.py::_find_active_task()'s
   # own established convention for this exact field, not a new SQL JSON operator
drafted_ids = {row for row in select(ContentDraft.task_id).where(ContentDraft.task_id.in_(candidate_ids))}
missing_ids = {t.id for t in completed_content_generation_tasks} - drafted_ids
```

The task with no `ContentDraft` is found in `missing_ids`; the task with one is not. No new column,
index, or migration was introduced — `EditorialTask.status` (already indexed,
`database/models/editorial_task.py:45-46`), `EditorialTask.workflow` (JSON, already existing), and
`ContentDraft.task_id` (already existing FK) are the only fields touched, exactly as Step 7 required.

**Misuse guard, proven directly** (`test_failed_workflow_run_never_produces_a_content_draft`): a
workflow that fails at `"research"` (before `"copywriting"` ever runs) produces a `FAILED`
`WorkflowRunResult` with no `"copywriting"` entry. Calling `create_from_result()` on it raises
`ValueError` (not a silently-created, wrong `ContentDraft`); following the correct calling
convention (never invoking it for a non-`COMPLETED` result) leaves zero `ContentDraft` rows for that
task. "Never mid-run" is structural, not separately tested: `WorkflowRunner.run()` (frozen,
unmodified) only ever returns a `WorkflowRunResult` once terminal — there is no way to construct a
"mid-run" `WorkflowRunResult` to call `create_from_result()` with.

---

## 10. Focused Validation Results

```
tests/test_content_draft_service.py ... 7 passed
```
Plus re-run, unmodified, of every M1/M2 test file plus `EditorialTask`/`workflow_service` tests
identified as potentially relevant in Step 1: `test_editorial_task_db_integration.py`,
`test_workflow_service.py`, `test_phase10_workflow_integration.py`, `test_quality_capability.py`,
`test_copywriting_capability.py`, `test_phase10_capability_registration.py` — **37/37 passed**, zero
modification required to any of them.

---

## 11. Full Regression Results

```
python -m pytest -q
701 passed in 322.44s (0:05:22)
```
701 = the 694 baseline from the M2 report plus the 7 new tests this milestone added. Zero
failures, zero regressions.

---

## 12. Ruff Result

```
python -m ruff check .
All checks passed!
```

---

## 13. Mypy Result

```
python -m mypy schemas/content_draft.py services/content_draft_service.py tests/test_content_draft_service.py
Success: no issues found in 3 source files
```
One targeted `# type: ignore[arg-type]` was added in `_to_read_schema()` for `hashtags=
draft.hashtags`, with an inline comment explaining the pre-existing `ContentDraft.hashtags:
Mapped[dict | None]` ORM type-hint imprecision (already flagged, harmless, by the M0 report) — a
type-annotation-only marker, not a behavior change.

---

## 14. Architecture Validator Result

```
python -m scripts.validate_architecture
validate_architecture: clean - 0 forbidden-dependency violations under C:\Users\Theodor\ai-newsroom
```

---

## 15. Scope Audit

`git diff --name-only` (tracked files modified) — **identical to M2's own list, unchanged by M3**:
```
capabilities/quality_capability.py
capabilities/registry.py
tests/test_quality_capability.py
workflows/definitions/content_generation.py
```
Zero additional tracked files modified by M3.

`git status --short` (new files, M3-relevant subset):
```
?? schemas/content_draft.py
?? services/content_draft_service.py
?? tests/test_content_draft_service.py
?? docs/phase10_m3_content_draft_report.md
```
Exactly the two Contract §3-authorized new production files, one new test file, and this report.

M1's files (`capabilities/copywriting_capability.py`, `prompts/copywriting/`,
`tests/test_copywriting_capability.py`, its report) and M2's new files (`prompts/quality/v2.yaml`,
`tests/test_phase10_capability_registration.py`, `tests/test_phase10_workflow_integration.py`, its
report) all appear unchanged in `git status` and were not modified. Every other untracked entry is a
pre-existing Phase 9/9.5/10 process document from earlier sessions, unrelated to and untouched by
M3.

**Verified**: M3 production changes are limited to exactly `schemas/content_draft.py` and
`services/content_draft_service.py` — the authorized scope, no more, no less. No unauthorized
production file was required.

---

## 16. Self-Audit Answers

1. **Does the `ContentDraft` schema match the existing ORM model and frozen Contract?** Yes —
   `ContentDraftRead`'s fields map one-for-one onto `ContentDraft`'s existing columns.
2. **Can the service persist a `ContentDraft` successfully?** Yes — confirmed by 5 of the 7 new
   tests, including cross-connection durability.
3. **Is `task_id` associated correctly?** Yes — confirmed directly.
4. **Are `title`/`body`/`hashtags` preserved correctly?** Yes — copied verbatim, confirmed by
   direct field assertions and by the durability test's independent-connection re-read.
5. **Was any database migration required or created?** No.
6. **Was any existing ORM model modified?** No — `database/models/content_draft.py` and
   `database/models/editorial_task.py` are both untouched (confirmed: neither appears in
   `git diff --name-only`).
7. **Are completed `CONTENT_GENERATION` tasks without drafts still discoverable as described by the
   Contract?** Yes — proven directly against the real schema, no new column/index.
8. **Did M3 modify any unauthorized production file?** No — scope audit confirms exactly the two
   authorized new files, zero existing-file modifications.
9. **Did M3 introduce CLI, scheduler, Telegram, meme/image, or workflow redesign work?** No — none
   of these appear anywhere in M3's diff.
10. **Did any frozen architecture decision change?** No —
    `docs/phase10_production_content_pipeline_architecture_contract.md` was not modified (confirmed
    via `git status`: still untracked/unchanged, not `M`).

No defect was discovered requiring a stop.

---

## 17. Deferred Work — Explicitly Deferred to M4

- **M4 (Manual CLI)**: `scripts/run_content_generation.py`. Not started, not created. No production
  AI provider was wired. No trigger of any kind was implemented.

---

## 18. Limitations

- **Commit-failure path is untested** (§6): there is no way to force a real `AsyncSession.commit()`
  failure against a healthy test database without faking the session in a way that would prove
  nothing about the real commit path — the "propagates uncaught" guarantee rests on the absence of
  any `try/except` in the 89-line service file, confirmed by direct read, not by a failure-injection
  test.
- **No idempotency mechanism exists or was added** (§7) — calling `create_from_result()` twice for
  the same `task_id` would create two rows. This matches the Contract's own scope exactly (no
  duplicate-prevention requirement is stated anywhere in Contract §7/§7.1), not an oversight.
- Every other limitation already disclosed by M0/M1/M2 (the M4-caller-discipline dependency, the
  reused, unvalidated `120`s timeout, the accepted `COMPLETED`-with-no-`ContentDraft` gap this
  milestone's own discoverability test exercises) remains unchanged and is not repeated here.

---

## Final Verdict

M3 COMPLETE — READY FOR REVIEW
