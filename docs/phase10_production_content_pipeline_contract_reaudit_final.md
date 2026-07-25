# Phase 10 Architecture Contract — Final Re-Audit After Targeted Revision

**Status: audit document. Does not modify the Contract, production code, tests, or migrations.**
Re-audits `docs/phase10_production_content_pipeline_architecture_contract.md` (post targeted
correction pass, which itself followed `docs/phase10_production_content_pipeline_contract_reaudit.md`)
as untrusted. Every claim below was independently re-derived against the current repository state
this session — `capabilities/registry.py`, `capabilities/quality_capability.py`,
`capabilities/intelligence_capability.py`, `capabilities/research_capability.py`,
`capabilities/executor.py`, `capabilities/capability_mapping.py`, `workflows/runner.py`,
`workflows/registry.py`, `workflows/definitions/content_generation.py`,
`workflows/definitions/news_analysis.py`, `database/models/content_draft.py`,
`database/models/editorial_task.py`, `database/models/__init__.py`, `database/session.py`,
`schemas/workflow.py`, `schemas/editorial_task.py`, `schemas/capability_definition.py`,
`services/workflow_service.py`, `integrations/prompts/file_repository.py`,
`integrations/prompts/protocol.py`, `prompts/quality/v1.yaml`, `prompts/research/v1.yaml`,
`scripts/run_triage.py`, `scripts/validate_architecture.py`, `schemas/__init__.py`,
`services/__init__.py`, `capabilities/__init__.py`, and the relevant test files — none of it taken
on the Contract's, the prior re-audit's, or the correction pass's own word.

---

# Executive Summary

The targeted revision genuinely fixed CRITICAL-1 (`capabilities/registry.py` is now correctly
authorized, and the exact two-line change specified is verified sufficient) and MINOR-1
(`schemas/content_draft.py` is now explicitly named). MINOR-2's fix is present but factually
imprecise about the repository's actual schema, described below.

However, this final re-audit found **one new CRITICAL defect**, of the exact same shape as the one
this revision was written to fix: **§3's own "no other production file — existing or new — is
authorized for editing or creation by this Contract" sentence contradicts §9's own binding
decision that `scripts/run_content_generation.py` must be created.** `scripts/run_content_generation.py`
does not exist anywhere in this repository (confirmed by direct filesystem check) and is not
present in §3's exhaustive new-file list — yet §9 states, in binding language, that this exact file
is "the MVP trigger" and describes its required contents in detail. Read literally — which is the
same literal-reading standard the Contract itself applied when it caught CRITICAL-1 — this Contract
now authorizes everything Phase 10 needs *except* the one file that actually invokes any of it,
repeating Decision Resolution §14's own named "inert code" risk one file short of closing it.

**Verdict: PHASE 10 CONTRACT NOT READY — CORRECTIONS REQUIRED.**

---

# Verified Previous Fixes

**CRITICAL-1 (`capabilities/registry.py` never authorized) — genuinely fixed, independently
re-verified.**
- Read `capabilities/registry.py` directly this session. `build_registry()` (lines 116-139)
  contains exactly four `registry.register(...)` calls (`SCORING_CAPABILITY_DEFINITION` line 134,
  `QUALITY_CAPABILITY_DEFINITION` line 135, `RESEARCH_CAPABILITY_DEFINITION` line 136,
  `INTELLIGENCE_CAPABILITY_DEFINITION` line 137), confirming the Contract's `capabilities/
  registry.py:134-137` citation is accurate.
- The Contract's prescribed fix — one new import line plus one new `registry.register(
  COPYWRITING_CAPABILITY_DEFINITION, CopywritingCapability(gateway, prompt_repository))` call — is
  mechanically identical in shape to the four existing calls and is genuinely sufficient:
  `CapabilityRegistry.resolve("copywriting")` (registry.py:103-113) looks up `self._definitions`/
  `self._capabilities` dicts keyed by `definition.name`; once `COPYWRITING_CAPABILITY_DEFINITION`
  (with `name="copywriting"`) is registered, `resolve("copywriting")` succeeds. No other change to
  `registry.py` is required — `CapabilityRegistry`, `Capability` Protocol, and `seal()` are
  independent of which definitions are registered.
- Also independently verified: `capabilities/capability_mapping.py` (read this session) **already**
  maps `"copywriting" → AICapability.COPYWRITING` (line 22) — this mapping is consumed by
  `CapabilityExecutor.execute()` (`capabilities/executor.py:81`) via `resolve_ai_capability(step.
  capability)`, called *before* `self._registry.resolve(step.capability)`. Had this mapping been
  missing, it would be a second required file the Contract failed to authorize — it is not missing,
  so no additional correction is needed here, confirming the Contract's implicit assumption (§1)
  that this mapping "already exists" holds.
- `scripts/validate_architecture.py`'s `capability-isolation` rule (lines 112-146) applies to any
  new file under `capabilities/` other than five explicitly excluded infrastructure files
  (`registry.py`, `executor.py`, `errors.py`, `capability_mapping.py`, `__init__.py`) — confirmed
  `capabilities/copywriting_capability.py` needs zero validator change, exactly as the Contract
  claims.

**MINOR-1 (`schemas/content_draft.py` not explicitly authorized) — genuinely fixed.** §3's new-file
list and §7.1 both now explicitly name `schemas/content_draft.py`/`ContentDraftRead`. Verified
`schemas/editorial_task.py` (the cited precedent) is a real, existing DTO module with exactly the
shape (`XCreate`/`XRead` frozen Pydantic models) the Contract says `ContentDraftRead` should mirror.

**MINOR-2 (discoverability of a `COMPLETED`-with-no-`ContentDraft` gap) — fix present, but
imprecise about the actual schema (see MINOR finding below).** The Contract's new §7.1 clarification
paragraph does correctly establish that post-hoc discovery is possible without a scheduler or
recovery engine — that much is true. But its specific mechanism description does not match the real
schema; see the MINOR finding.

---

# Findings

## CRITICAL

### CRITICAL-NEW-1 — §3's exhaustive file-authorization list omits `scripts/run_content_generation.py`, which §9 requires in binding form

**Location**: Contract §3 ("No other production file — existing or new — is authorized for editing
or creation by this Contract") vs. §9 ("**DECISION, binding — MVP trigger**: `scripts/
run_content_generation.py`...").

**Evidence**: `scripts/run_content_generation.py` does not exist in this repository (confirmed:
`ls scripts/run_content_generation.py` → "No such file or directory"; `ls scripts/ | grep -i
content` → no match). §9 is written in exactly the same binding, mandatory register as every other
`DECISION, binding` in this Contract: it names the file, mirrors it explicitly to `scripts/
run_triage.py`'s shape (confirmed real and read this session — a ~20-line script wrapping one
`services/`-layer call), and specifies its required behavior in detail (create task, run it, invoke
`ContentDraftService`, distinguish three outcomes). This is unambiguously a new production file
Phase 10 requires. Yet §3's new-file list — introduced by this very revision specifically to be
"distinct... equally binding and equally exhaustive — no other new production file is authorized" —
does not include it, and its closing sentence explicitly forecloses any file beyond the five named.

**Impact**: read literally — the same reading discipline this Contract's own §3 uses to bind an
implementer — creating `scripts/run_content_generation.py` is simultaneously commanded by §9 and
forbidden by §3. This is not a hypothetical ambiguity: an implementer following §3's text alone
would build `CopywritingCapability`, register it, wire the workflow, and build `ContentDraftService`
— and then have no authorized way to actually invoke any of it, precisely the "ships inert code"
risk `docs/phase10_decision_resolution.md` §14 names explicitly. This is the same class of defect as
the immediately-prior CRITICAL-1 (a file the Contract's own body requires but its own authorization
list omits), reintroduced in this revision's replacement text for a different file.

**Required correction**: add `scripts/run_content_generation.py` as a sixth entry to §3's new-file
authorization list, cross-referencing §9 exactly as the list's other four new-file entries
cross-reference their own owning sections.

---

## MAJOR

None. No MAJOR-severity defect was found in this pass.

---

## MINOR

### MINOR-NEW-1 — §7.1's discoverability query describes `EditorialTask.workflow_type` as a filterable, already-indexed column; no such column exists

**Location**: Contract §7.1 ("Clarification... corrects MINOR-2") — "conceptually, `EditorialTask`
rows where `workflow_type = CONTENT_GENERATION AND status = COMPLETED` LEFT JOINed against
`ContentDraft` on `task_id`... Because `EditorialTask.status` and `ContentDraft.task_id` are both
ordinary, already-existing, already-indexed columns..."

**Evidence**: `database/models/editorial_task.py` (read directly this session) has no
`workflow_type` column at all — its columns are `id`, `event_id`, `priority`, `workflow` (a JSON
blob), `status` (indexed, `index=True`), `retry_count`, `created_at`, `updated_at`.
`services/workflow_service.py::_find_active_task()` states this explicitly in its own docstring,
confirmed by direct read: *"workflow_type is matched against the JSON snapshot's `workflow_name`
field, since `EditorialTask` has no dedicated column for it."* A real query for this state must
therefore filter on a JSON path expression (e.g. `EditorialTask.workflow["workflow_name"].astext ==
"CONTENT_GENERATION"` in SQLAlchemy/Postgres terms), not a plain column equality. Separately,
`ContentDraft.task_id` (`database/models/content_draft.py:34-36`) has no `index=True` on its column
definition either — only `EditorialTask.status` is actually indexed among the three fields the
Contract's sentence groups together as "already-indexed."

**Impact**: this does not block implementability — the query is still genuinely possible with zero
migration, exactly as the Contract's core claim asserts, since Postgres JSON operators require no
schema change. But the specific phrasing overstates precision in a document whose own stated
discipline (§ header: "Every statement is tagged FACT... repository evidence") is to cite real,
verified structure — "already-indexed columns" is inaccurate for two of the three fields named, and
"`workflow_type = CONTENT_GENERATION`" reads as a plain column filter when it is actually a JSON
path expression against an unindexed blob. At the row counts Phase 10's MVP CLI trigger will
produce, this has no practical performance consequence — but the prose should describe the real
mechanism, since a future reader (or M3/M4's own implementer) taking this sentence literally would
look for a column that isn't there.

**Required correction**: revise §7.1's clarification sentence to say the `workflow_type` filter
reads `EditorialTask.workflow`'s JSON `workflow_name` field (not a dedicated column, matching
`_find_active_task()`'s own documented precedent), and drop or correct the "already-indexed"
characterization of `ContentDraft.task_id`.

### MINOR-NEW-2 — §12 has no test proof obligation naming registry resolution directly

**Location**: Contract §12 (Testing Requirements).

**Evidence**: §12's "Workflow tests" require the four-step chain to reach `TaskStatus.COMPLETED`
through the real, unmodified `WorkflowRunner`/`CapabilityExecutor`/`CapabilityRegistry` — which does
*imply* `CapabilityRegistry.resolve("copywriting")` succeeded (were it unregistered,
`CapabilityExecutor.execute()`, confirmed at `capabilities/executor.py:86-90`, would catch
`UnknownCapabilityError` and raise `PermanentStepFailureError`, which `WorkflowRunner._run_step()`
would turn into a `FAILED` outcome, contradicting the test's own `COMPLETED` assertion). But no
`§12` bullet directly and explicitly names "`build_registry()` registers `\"copywriting\"`" or
"`CapabilityRegistry.resolve(\"copywriting\")` succeeds" as its own proof obligation, unlike how
explicitly §12 already names the AST non-coupling check, the durability test, and the session-reuse
test as their own standalone obligations.

**Impact**: low — the workflow-completion test already covers this transitively, and this is the
weakest of the findings here. But since this Contract's own governing standard (§ header) is that
proof obligations should be named explicitly, not left to transitive inference, this is worth a
one-line addition for the same precision discipline the rest of §12 already holds itself to.

**Required correction**: add one bullet to §12's Workflow tests naming registry resolution as its
own explicit assertion (e.g., a direct `registry.resolve("copywriting")` call succeeding against the
real, boot-built registry, independent of the full-chain test).

---

# Observations

**OBS-1**: `ContentDraft.task_id` has a `ForeignKey("editorial_tasks.id")` but no `UNIQUE`
constraint (confirmed: `database/models/content_draft.py:34-36`) and no application-level check
preventing two `ContentDraft` rows for the same `task_id`. This is consistent with the Contract's
own stated design (§7.1: `version` is always `1`, no re-versioning in Phase 10) and is not a defect
— `ContentDraftService.create_from_result()` is only ever called once per task in the described
flow (from a single CLI invocation, per task) — but it is worth naming that nothing in the schema
itself would prevent a duplicate row if `create_from_result()` were ever accidentally called twice
for the same `task_id` (e.g., a retried CLI invocation after a prior partial failure). Not a
required correction — Phase 10's CLI is manual and single-shot per the Contract's own design — but a
natural candidate note for whichever future phase adds recovery/retry.

**OBS-2**: `EditorialTask.status`'s index (`index=True`) plus a JSON-path filter on `workflow` would
still need a full-table scan of `COMPLETED` rows to extract `workflow_name` at Phase 10's data
volumes — acceptable for an ad hoc manual query at MVP scale (the Contract's own explicitly accepted
scope), but worth the same "not automated, ad hoc only" framing the Contract already applies,
reinforcing MINOR-NEW-1's correction rather than contradicting it.

**OBS-3**: this re-audit re-confirms (independently, not merely re-citing the prior audit) that
`prompts/quality/v1.yaml` and `prompts/research/v1.yaml`'s real, on-disk `output_schema.required`
lists equal their Capabilities' real `expected_output_keys` exactly (`["passed","issues"]` and
`["facts","confidence","gaps"]` respectively) — the convention §6 asks `prompts/copywriting/v1.yaml`
to follow is a real, currently-unbroken pattern, not an aspirational one.

---

# Authorized Scope Verification

Every file genuinely required for a correct Phase 10 implementation, independently derived from the
Contract's own design plus direct repository verification:

**Existing files requiring edits:**
1. `workflows/definitions/content_generation.py` — step list + `timeout_seconds` (authorized, §3).
2. `capabilities/quality_capability.py` — `_build_request()` + `PROMPT_VERSION` (authorized, §3,
   §5.1).
3. `capabilities/registry.py` — one import + one `register()` call (authorized, §3 — verified
   sufficient above).

**New files required:**
1. `capabilities/copywriting_capability.py` (authorized, §3, §5).
2. `prompts/copywriting/v1.yaml` (authorized, §3, §5, §6).
3. `prompts/quality/v2.yaml` (authorized, §3, §5.1, §6).
4. `schemas/content_draft.py` (authorized, §3, §7.1).
5. `services/content_draft_service.py` (authorized, §3, §7).
6. **`scripts/run_content_generation.py` — required by §9's own binding text, NOT present in §3's
   new-file list.**

**Confirmed NOT required (checked directly, not assumed):**
- No `__init__.py` under `schemas/`, `services/`, or `capabilities/` needs any change — all three
  are docstring-only with no explicit re-export list (confirmed by direct read).
- `database/models/__init__.py` already imports `ContentDraft` — no change needed.
- `capabilities/capability_mapping.py` already maps `"copywriting"` — no change needed (a real risk
  this audit specifically checked for and ruled out).
- `workflows/registry.py` needs no change — it imports `content_generation.DEFINITION` directly by
  reference, so editing the `steps` list inside `content_generation.py` is automatically reflected;
  no re-registration call is needed.
- `scripts/validate_architecture.py` needs no change — the `capability-isolation` rule already
  applies generically to any new file under `capabilities/`.
- No migration is required — `ContentDraft`'s existing columns are sufficient (confirmed by direct
  model read).

**Verdict: INSUFFICIENT** — the authorized list is missing `scripts/run_content_generation.py`
(CRITICAL-NEW-1). Every other file the implementation genuinely needs is present and correctly
scoped.

---

# Contract Score

**7 / 10** — the targeted revision correctly, verifiably fixed the prior CRITICAL and MINOR-1
finding, and every citation re-checked in this pass held up against real source. But the same
class of defect recurred once more, in a different section, in this same revision — an
authorization list built to be "exhaustive" that is not, missing the one file that turns the rest of
this Contract's design into anything an operator can actually run. This is narrower in scope than
the prior CRITICAL-1 (five of six required new files are present and correct, one is missing) but is
the same kind of self-contradiction this repository's audit process exists to catch before
implementation begins.

---

# Final Verdict

PHASE 10 CONTRACT NOT READY — CORRECTIONS REQUIRED
