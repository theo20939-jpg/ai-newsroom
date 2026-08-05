# Phase 18 M2 — Meme Concept Generation: Implementation Report

Status: complete (engineering). One migration added (the phase's single planned migration, per
`docs/phase18_m0_meme_discovery_report.md` §7) — not yet applied to any database, since no
Postgres instance is reachable in this session (disclosed in the M0/M1 reports; unchanged here).
`WorkflowType.MEME_GENERATION` is declared but not registered in `WorkflowRegistry` — no live
workflow run is possible or attempted from this milestone.

## 1. What was built

| File | Purpose |
|---|---|
| `schemas/workflow.py` | `WorkflowType.MEME_GENERATION` added (declared, unregistered — mirrors `DAILY_DIGEST`) |
| `schemas/meme_concept.py` | `MemeConcept`, `MemeFormat` — frozen Pydantic contract for the brief's own M2 field list |
| `prompts/meme_concept/v1.yaml` | Governed system/rules/output_schema for the new capability |
| `capabilities/meme_concept_capability.py` | `MemeConceptCapability` — one `call_generate()`, mirrors `CopywritingCapability` exactly |
| `capabilities/capability_mapping.py` | `"meme_concept"` → `AICapability.CREATIVE` (reused, zero new enum value) |
| `capabilities/registry.py` | `MemeConceptCapability` registered (real, resolvable, cost-tracked) |
| `capabilities/executor.py` | `_try_reuse()`'s workflow guard extended to also allow `MEME_GENERATION` to reuse a source NEWS_ANALYSIS task's research/intelligence |
| `workflows/definitions/meme_generation.py` | `WorkflowDefinition` (research → intelligence → meme_concept so far; extended per later milestone) |
| `database/models/meme_candidate.py` | `MemeCandidate` ORM model — the phase's one new table, full multi-stage column set (mostly reserved/nullable) |
| `database/migrations/versions/21177d5b859e_add_meme_candidates_table.py` | The migration itself |
| `services/meme_candidate_service.py` | `MemeCandidateService.create_from_concept()` — the only concept-stage writer |
| `tests/test_meme_concept_capability.py` | 12 tests, `FakeLLMGateway`/`FakePromptRepository` |
| `tests/test_phase18_m2_meme_concept_schema_and_registry.py` | 10 tests: schema, capability mapping, workflow declaration, migration-chain validity |

## 2. Design decisions and why

- **Concept generation needs an LLM call** — unlike M1, "premise/setup/punchline/humor mechanism"
  is genuinely creative composition, not classification; a deterministic heuristic cannot invent a
  meme premise. This is the first (and, per the M0 report's plan, only other planned) LLM call
  Phase 18 introduces before image generation.
- **One concept per call, no automatic alternative** — the brief allows "1 main + possibly 1
  alternative" but warns against unbounded generation. M2 ships exactly one `MemeConceptCapability`
  call per attempt; a second/alternative concept, if ever wanted, is a second capability call at
  the M7 quality-gate's own bounded-regeneration budget, not a standing per-attempt cost. Not
  implemented in M2 — no alternative-concept code path exists to keep half-finished.
- **`AICapability.CREATIVE` reused, not a new enum value** — confirmed empty/unused before this
  commit (`grep` for `"meme_concept"` or any capability-name → `CREATIVE` mapping returned
  nothing); this is exactly the reuse the M0 report identified.
- **`services/analysis_reuse.py`'s underlying query is untouched** — only `capabilities/
  executor.py::_try_reuse()`'s one-line workflow-name guard was widened from
  `!= CONTENT_GENERATION` to `not in (CONTENT_GENERATION, MEME_GENERATION)`. The module's own
  `find_source_news_analysis_task_id`/`reuse_prior_result` functions were already workflow-agnostic
  (they look up by `event_id` and the *source* task's `NEWS_ANALYSIS` type only, never by which
  downstream workflow is asking) — no change was needed there.
- **`WorkflowType.MEME_GENERATION` stays unregistered** — `WorkflowRegistry` would let a caller
  actually start running this workflow once registered, but only 3 of its eventual steps exist
  (`meme_concept` has no safety gate, no copywriting, no image, no quality gate downstream yet) —
  registering it now would let a task get created and then permanently stall/fail past
  `meme_concept`. Registration is deferred to whichever milestone completes a coherent,
  worth-running chain (assessed again once M4/M7 land — see §5).
- **`MemeCandidate` designed with the full multi-stage column set now, populated by column-owning
  milestone** — per the M0 report's §7 justification (this is the phase's one planned migration,
  introduced early rather than once per milestone), mirroring `ImageCandidateRecord`'s own
  precedent of reserving `content_draft_id` for "future M6+ population." Every reserved column is
  commented with which milestone populates it. Only concept-stage columns are written by
  `MemeCandidateService` as of M2 — no other writer method exists yet (no stub methods for M3-M9
  were added; each milestone adds its own single method when it actually lands, matching this
  codebase's own "no half-finished implementations" discipline).

## 3. Testing

- **`tests/test_meme_concept_capability.py`** (12/12 pass): full-shape execution proving
  Research's facts flow into the built prompt, graceful degradation when `research` step results
  are absent, floor-validation failure raises `ValidationCapabilityError`, constructor-signature
  check (`gateway`, `prompt_repository` only — no `BudgetGuard`/`CostTracker`), independent/
  uncontaminated repeated calls, every Gateway error type translated (never a raw exception
  escapes), failed-call logging before raise, AST-based import check proving no coupling to
  Research/Intelligence Capabilities, and — importantly — a test that loads the **real** published
  `prompts/meme_concept/v1.yaml` (not a test fixture) and asserts its `output_schema`'s required
  keys exactly match `MemeConcept`'s own Pydantic fields, catching any future drift between the
  two.
- **`tests/test_phase18_m2_meme_concept_schema_and_registry.py`** (10/10 pass): `MemeConcept` is
  frozen and rejects unknown fields; `source_fact_links` cannot be empty (enforces "grounded in
  confirmed facts" at the schema level); `"meme_concept"` resolves to `AICapability.CREATIVE`;
  the capability definition's `expected_output_keys` exactly matches the schema; `MEME_GENERATION`
  is declared but raises `UnknownWorkflowTypeError` when resolved from the real, built
  `WorkflowRegistry` (proving it is genuinely not live); the `WorkflowDefinition`'s step list is
  `research → intelligence → meme_concept`; the `MemeCandidate` table's declared column defaults
  are correct; and `alembic heads` (run as a subprocess, no DB connection needed) confirms the new
  migration extends the existing chain linearly to a single head with no branch.
- **Regression checks**: `python -m pytest --collect-only -q` — 2182 tests collected (up from
  2160 after M1, +22 new, 0 collection errors). `tests/test_capability_registry.py`,
  `tests/test_registry_consistency.py`, `tests/test_workflow_registry.py` (20/20) all still pass
  unmodified, including `test_daily_digest_is_not_registered_in_the_real_registry` (the exact
  precedent test whose logic `MEME_GENERATION`'s own non-registration now also satisfies) and
  `test_news_analysis_and_content_generation_are_registered_in_the_real_registry` (proving the
  two production workflows remain registered and unaffected).
- **Not run this session (disclosed, same constraint as M0/M1)**: `MemeCandidateService.
  create_from_concept()` against a real database, and `CapabilityExecutor`'s end-to-end
  `_try_reuse()` behavior for a live `MEME_GENERATION` task (`tests/test_capability_executor.py`'s
  own equivalent tests all require the `db_session` fixture, i.e. a real Postgres connection —
  unavailable, docker not running). The migration file itself was validated as far as possible
  without a DB (`alembic heads`, Python syntax, mirrors the already-applied `image_candidates`
  migration's exact `op.*` call shapes) but has not been run against a live database.

## 4. Risks / limitations carried forward

- The migration is written but unapplied — it must be run (`alembic upgrade head`) against a real
  database before `MemeCandidateService` can be exercised for real; this is a mechanical step, not
  an open design question.
- `MemeConceptCapability` has never made a real (paid) LLM call — its request/response shape is
  proven correct against `FakeLLMGateway` only. The brief's own paid-run authorization boundary
  applies here as much as it does to M5's image generation; no live call was made or attempted.
- Concept quality (is the generated premise/punchline actually funny, on-brand, safe) is
  unassessed until M3 (safety/originality) and M7 (quality gate) exist — M2 only proves the
  *plumbing* is correct, not the *creative output quality*, which cannot be evaluated without a
  real model response.

## 5. Next milestone

M3 (Meme Safety & Originality Gate) — a deterministic executor-style gate over `MemeConcept`'s own
`forbidden_interpretations`/`source_fact_links` plus a reuse of Fact Safety/calibrated safety
output, per `docs/phase18_m0_meme_discovery_report.md` §4.3/§10. `WorkflowType.MEME_GENERATION`
registration is re-assessed once M3+M4 exist (a concept+safety+copy chain is the first point a
human could plausibly review *something*, even without an image yet).
