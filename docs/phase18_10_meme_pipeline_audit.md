# Phase 18.10 M8 — Meme Pipeline Audit

Status: diagnosis only, per explicit instruction. No meme mode was enabled, no `MEME_GENERATION`
task was created, no migration was applied, and the meme workflow was not modified. All findings
below are from direct, read-only inspection of the current codebase.

## Question

Phase 18.9's 2-hour live production test produced **0 memes**. Why, given that a meme pipeline
(concept generation, safety/originality gating, image generation, rendering, Telegram preview)
visibly exists in the codebase?

## Stage-by-stage diagnosis

| Stage | Verdict | Why |
|---|---|---|
| 1. Trigger (a `MEME_GENERATION` task ever gets created) | **FAIL — this is the root cause** | No live code path creates one. See below. |
| 2. Candidate creation (`MemeCandidateService`) | **NOT REACHED** (would also fail if reached) | Never called by any live orchestrator; would additionally crash on the missing `meme_candidates` table if it were ever called. |
| 3. Opportunity scoring | **NOT REACHED / inert by design** | Gated by `meme_opportunity_mode`, currently `"off"`; even `"shadow"` never creates a task. |
| 4. Safety gate | **NOT REACHED / inert by design** | Gated by `meme_safety_gate_mode`, currently `"off"`; its hook point (`meme_concept` step) never runs live anyway. |
| 5. Generation trigger (image generation + render) | **NOT REACHED / inert by design** | `meme_image_generation_mode="off"`; no live call site for `generate_meme_image()`/`render_meme()` exists regardless. |

### 1. Trigger — the root cause

`workflows/definitions/meme_generation.py` registers the `MEME_GENERATION` workflow (research →
intelligence → meme_concept → meme_copywriting), but its own module docstring states plainly:
*"Registering the workflow only makes `WorkflowRunner.run()` able to execute it if some caller
explicitly creates a MEME_GENERATION `EditorialTask` — no such caller exists yet."*

Confirmed directly: `services/workflow_service.py::create_task()` is the only place any
`EditorialTask` is ever inserted, but the only live caller in the running system,
`services/triage_orchestrator.py`, hardcodes `WorkflowType.NEWS_ANALYSIS` — never
`MEME_GENERATION`. A repo-wide search for `MEME_GENERATION` turns up only: the workflow
definition itself, its own registry entry, its capability schemas/tests, and
`bot/handlers/meme_preview.py` — whose own docstring explicitly confirms it does **not** trigger
generation ("do NOT yet re-run any generation step — no live MEME_GENERATION..."). No worker
(`worker/analysis_cycle.py`, `worker/content_cycle.py`), no script reachable in production, and no
orchestrator ever instantiates one.

**This alone fully explains 0 memes** — every downstream stage is fully implemented and
independently tested, but structurally unreachable from any live process.

### 2. Candidate creation — not reached, and would fail if it were

`services/meme_candidate_service.py::MemeCandidateService.create_from_concept()` does a bare
`session.add(...)`/`commit()`/`refresh()` with no `try`/`except` around the insert. The
`meme_candidates` table does not yet exist in the database (`alembic current` is one revision
behind `head`; the pending migration `21177d5b859e_add_meme_candidates_table.py` creates it) — if
this method were ever called, it would raise an unhandled `sqlalchemy.exc.ProgrammingError`
(`UndefinedTableError`) on the very first insert. This is a real, independent, latent second
failure mode — but moot today, since the service is never called by any live path (its own module
docstring says the same: "no orchestrator calls these in a live run yet").

### 3–4. Opportunity scoring and safety gate — inert by design

`core/config.py` settings, current values:

| Setting | Values available | Current | Effect |
|---|---|---|---|
| `meme_opportunity_mode` | `off`, `shadow` | `off` | `off`: zero processing. `shadow`: computes and persists a JSON annotation on the `quality` step's own output — **never creates a task**, by design. |
| `meme_safety_gate_mode` | `off`, `shadow` | `off` | Same shape, hooks the `meme_concept` step — which only exists inside `MEME_GENERATION`, itself never triggered (§1). |

**No `"enforce"`/live mode exists for either setting anywhere in the codebase yet** — even fully
enabling `shadow` mode on both could never, by itself, produce a meme; it can only annotate JSON
for later human/calibration review.

### 5. Generation trigger — inert by design, and unwired regardless

`meme_image_generation_mode` (`off`/`dry_run`, currently `off`) gates
`services/meme_image_generation.py::generate_meme_image()` — deliberately not registered in
`capabilities/registry.py::build_registry()` ("a feature no live workflow run yet reaches", per
its own module docstring). `services/meme_render.py::render_meme()` (pure Pillow text-overlay
logic) has no live call site either. `meme_telegram_preview_mode` (`off`/`dry_run`, currently
`off`) gates `services/meme_preview_notifier.py::send_meme_preview()`, also with no live trigger.

### Shadow tooling — what it does and doesn't prove

`scripts/phase18_5_shadow_collection.py` backtests only the opportunity classifier (§3) offline
against historical `NewsEvent` rows, writing results to a local JSON file only — zero database
writes, and it explicitly does not import `capabilities.executor`, `workflows.runner`, or `bot`
(enforced by an import-boundary test), so it cannot exercise candidate creation, the safety gate,
image generation, or Telegram delivery even accidentally. A "successful" shadow-collection run
says nothing about whether the actual generation chain would work end-to-end.

## Summary

The meme pipeline is a fully-built, fully-tested-in-isolation feature that is **entirely unwired
to any live trigger**. Every module's own docstrings describe this as an intentional, disclosed
deferral, not an accident. Even if the missing trigger were added, three more independently
sufficient blockers would need to be resolved first: the `off`-mode settings (by design — this
audit does not recommend changing them), the missing `meme_candidates` migration, and the absence
of any live/enforce mode for the opportunity and safety gates (they only support `shadow`
annotation today).

## Recommended fix (for a future phase — not implemented here)

1. Apply the pending `meme_candidates` migration.
2. Add a real trigger call site (e.g., in `triage_orchestrator.py` or a dedicated meme-candidate
   selection cycle) that creates a `MEME_GENERATION` task under an explicit, separately-gated
   condition — never unconditionally.
3. Introduce a genuine `"enforce"`/live mode for `meme_opportunity_mode`/`meme_safety_gate_mode`
   (neither currently offers one), with the same staged shadow-bake-then-enforce discipline used
   elsewhere in this codebase.
4. Only then would `meme_image_generation_mode`/`meme_telegram_preview_mode` need a live value to
   actually produce and deliver a meme.

None of the above is proposed for implementation in this phase — meme modes remain `off`,
untouched, per explicit instruction.
