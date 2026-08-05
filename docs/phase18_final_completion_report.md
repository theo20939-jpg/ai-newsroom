# Phase 18 — Meme Intelligence & Generation: Final Completion Report

**Branch:** `feature/phase18-meme-intelligence` (from `feature/phase17-editorial-intelligence` @
`8872624`) · **Commits:** 11 (M0–M9 + this report) · **Checkpoint tags:**
`checkpoint/phase18-m0-discovery` through `checkpoint/phase18-final-complete` · **Status:
engineering scope 100% complete (M0–M9). No live/paid activity of any kind occurred.**

> **Corrected at final acceptance** (`docs/phase18_final_acceptance_report.md`): this report's
> commit count, tag list, and DB/migration status below were updated to match reality as of the
> acceptance pass — see that report for the full, evidence-backed audit, including a real schema
> defect found and fixed, and the migration/DB-integration validation this report originally
> listed as outstanding. Nothing in §1–§4 or §6/§9's own engineering findings changed; only the
> validation-status claims in §5/§8/§10/Appendix were corrected.

## 1. Executive summary

Phase 18 builds a complete, original, editorial meme pipeline for AI Newsroom:
`NewsEvent → Meme Opportunity Detection → Meme Concept → Safety/Originality Gate → Copywriting →
Image Generation → Rendering → Quality Gate → Telegram Editorial Preview → Human Decision`. Every
milestone the brief specified (M0–M9) is implemented, unit-tested, documented, and committed.

Two findings from M0's discovery shaped everything that followed and are worth restating up
front: **no image-generation capability existed anywhere in this codebase before this phase**
(Phase 16 "Image Intelligence" is discovery/validation of *existing* media, not generation), and
`AICapability.CREATIVE` plus `ContentType.MEME` had existed, unused, since before this phase —
both consumed with zero migration. Only **one migration** was needed for the entire phase (a
`meme_candidates` table), introduced early (M2) exactly as M0 planned. It was written during
M0–M9 development but **could not be runtime-validated then** — no Postgres/Redis instance was
reachable in that development environment (docker was not running), disclosed in every milestone
report that touched DB-backed code. **At final acceptance, Docker was started and the migration
was applied, downgraded, and re-applied against a dedicated disposable validation database**
(`docs/phase18_final_acceptance_migration_report.md`) — this found and fixed one real schema
defect (a missing index) before it could ever reach a real environment. The migration has still
never been applied to the project's actual `ai_newsroom` database.

**No live LLM call, no live image-generation call, and no live Telegram send occurred at any
point in this phase.** Every new mode flag defaults to `"off"`; the ones that concern paid/live
activity (`meme_image_generation_mode`, `meme_telegram_preview_mode`) have `Literal` types that do
not even *contain* a `"live"` value yet — a future, separately authorized milestone must add that
value in code before any call path could select it. This is a stronger guarantee than a runtime
flag check alone.

## 2. Architecture changes

All additive; the two production pipelines (`NEWS_ANALYSIS`, `CONTENT_GENERATION`) and Phase 16
image preview are untouched in behavior (verified by regression tests at every milestone, not
merely by inspection).

- **New `WorkflowType.MEME_GENERATION`**, registered in `WorkflowRegistry` as of M4 (research →
  intelligence → meme_concept → meme_copywriting). No automatic caller creates a task for it — an
  operator or a future script must explicitly do so; this remains inert in production today.
- **Two new Capabilities** (`meme_concept`, `meme_copywriting`), following the exact
  `CopywritingCapability` shape used by every Capability since Phase 8/10, mapped to the
  already-existing `AICapability.CREATIVE`/`COPYWRITING` enum values — zero migration.
- **A new, separate `ImageGenerationGateway` Protocol** (`integrations/llm_gateway/
  image_protocol.py`), deliberately *not* an extension of the existing `LLMGateway` Protocol — a
  concrete architectural decision, evaluated and documented in the M5 report, made specifically to
  avoid touching a frozen, widely-implemented seam (`CapabilityCall.gateway_method`, every
  provider adapter, `FakeLLMGateway` across 150+ existing tests) for a fundamentally different
  call shape.
- **`meme_image`/`meme_render` are deliberately *not* wired into `CapabilityRegistry`** —
  `capabilities.registry.build_registry()`'s constructor signature is documented as a
  contractually-frozen boot-order seam; threading a new dependency through it for a feature no
  live workflow reaches yet was evaluated and rejected as unnecessary architecture change. Both
  are plain, directly-inspectable orchestration functions instead, mirroring
  `services/telegram_notifier.py`'s own established non-Capability-Framework pattern.
- **One new table, `meme_candidates`** (§7 of the M0 report's own reasoning, restated in the M2
  report): a single evolving row per meme attempt, modeled directly on `ImageCandidateRecord`'s
  already-approved shape, with every future-milestone column reserved and documented ahead of the
  milestone that populates it. `EditorialTask.workflow`'s existing JSON step_results mechanism was
  judged insufficient for the same reason it was judged insufficient for image candidates in
  Phase 16 M5 — a multi-stage business record needs to be durable and queryable independent of
  transient workflow execution-state bookkeeping.
- **Five new settings** (corrected from an earlier, inaccurate "eight" — see `docs/
  phase18_final_acceptance_inertness_audit.md` §1): four mode flags, all following the exact
  `Literal["off", ...]`, default-`"off"` convention established in Phases 15–17
  (`meme_opportunity_mode`, `meme_safety_gate_mode`, `meme_image_generation_mode`,
  `meme_telegram_preview_mode`), plus one numeric byte limit (`meme_image_max_bytes`). No existing
  flag was repurposed. Three additional code-level constants (`MAX_CONCEPT_REGENERATIONS`,
  `MAX_IMAGE_REGENERATIONS`, `_MAX_GENERATION_ATTEMPTS`) bound regeneration/retries and are not
  `Settings` fields.

## 3. Milestone history (M0–M9)

| M | Deliverable | LLM calls | New tests | Report |
|---|---|---|---|---|
| M0 | Discovery report: architecture, reuse points, real-data (n=32) taxonomy | 0 | — | `phase18_m0_meme_discovery_report.md` |
| M1 | Meme Opportunity Detection (shadow hook) | 0 | 17 | `phase18_m1_meme_opportunity_report.md` |
| M2 | `MemeConceptCapability` + `meme_candidates` migration | 1 (never live) | 22 | `phase18_m2_meme_concept_report.md` |
| M3 | Meme Safety & Originality Gate (shadow hook) | 0 | 15 | `phase18_m3_meme_safety_originality_report.md` |
| M4 | `MemeCopywritingCapability`; `MEME_GENERATION` registered | 1 (never live) | 16 | `phase18_m4_meme_copywriting_report.md` |
| M5 | Image generation (mock provider only) | 0 (mock) | 12 | `phase18_m5_meme_image_generation_report.md` |
| M6 | Deterministic text-overlay renderer | 0 | 13 | `phase18_m6_meme_rendering_report.md` |
| M7 | Quality Gate combining M1/M3/M5/M6 signals | 0 | 18 | `phase18_m7_meme_quality_gate_report.md` |
| M8 | Telegram preview (dry-run only) | 0 | 25 | `phase18_m8_telegram_editorial_preview_report.md` |
| M9 | Human feedback taxonomy + cost/regen accounting | 0 | 18 | `phase18_m9_human_feedback_report.md` |

**Total: 156 new tests, all passing.** Two real bugs were found and fixed *by* those tests before
they could reach any shared state: M1's gold-set backtest caught the bare keyword `"dead"`
falsely blocking a "The Walking Dead" streaming-rights story; M4's real-prompt-load test caught a
YAML syntax error (`: ` inside an unquoted list item) in `prompts/meme_copywriting/v1.yaml`.

**Two disclosed deviations from the brief's literal milestone order**, both explained in-place
when they happened:
- M1 was implemented as an executor shadow-hook on existing `CONTENT_GENERATION`, not as a
  `MEME_GENERATION` step — it must run *before* any `MEME_GENERATION` task could even be created.
- The one migration landed at M2, not deferred to "if M9 needs it" — M2's own regenerate loop
  needed durable state two milestones before M9's literal placement in the brief's prose.

## 4. What was reused from prior phases (M0's own inventory, confirmed by every later milestone)

- **Capability Framework** (Phases 6–8, 10): `CapabilityRegistry`, `CapabilityExecutor`, the
  entire shadow-hook pattern (`_attach_editorial_brief`/`_attach_channel_relevance`/
  `_attach_editorial_completeness` → now also `_attach_meme_opportunity`/
  `_attach_meme_safety_originality`), `capabilities/capability_mapping.py`,
  `capabilities/gateway_call.py`.
- **Workflow Engine** (Phase 5): `WorkflowRunner`, `WorkflowRegistry`, `EditorialTask` — the
  entire MEME_GENERATION workflow reuses these completely unmodified structurally.
- **Cost tracking / budget** (Phases 6–7): `RedisCostTracker`/`RedisBudgetGuard`/
  `PricingCatalog`/`record_ai_execution` — automatically available to `meme_concept`/
  `meme_copywriting` the moment those steps run through the ordinary executor path, since both
  are registered exactly like any other Capability.
- **`services/analysis_reuse.py`**: extended (one guard clause, not the underlying query) so
  `MEME_GENERATION`'s own research/intelligence steps reuse a source `NEWS_ANALYSIS` task's
  results, exactly as `CONTENT_GENERATION` already does.
- **Image storage** (Phase 16 M5): `integrations.storage.image_storage.ImageStorage`/
  `LocalImageStorage` — reused verbatim by both M5 (generated images) and M6 (rendered images),
  the first time this abstraction has stored *generated*, not merely *fetched*, bytes.
- **Fact Safety / calibrated safety** (Phase 15/17): consumed as an input signal by M3's safety
  assessment (`calibrated_fact_safety_status` parameter) — not recomputed.
- **Telegram preview pattern** (Phase 16 M6): `bot/handlers/image_preview.py`'s exact interaction
  shape (fresh re-query per callback, terminal-state message editing, dry-run-before-live-send)
  was mirrored file-for-file in `bot/handlers/meme_preview.py`.
- **`ContentType.MEME`** and **`AICapability.CREATIVE`**: both existed, unused, before this phase
  — the schema literally anticipated this work.

## 5. Quantitative results

*(Updated at final acceptance — see `docs/phase18_final_acceptance_report.md` for full detail.)*

- **59 files changed** during M0–M9 development: **51 new**, **8 modified** (all 8 additive). The
  acceptance pass added a further ~9 files (5 new audit docs, 2 new test files, 1 migration fix,
  1 service extension) — see the acceptance report's own git section for the final count.
- **11 commits** through M0–M9 + the original completion report, plus further acceptance-pass
  commits (git audit report has the authoritative table).
- **174 tests** (156 from M0–M9 + 15 new DB-integration + 3 new offline-E2E), all passing
  **against a real PostgreSQL database** (`phase18_validation_db`) — not merely `FakeLLMGateway`-
  isolated as before acceptance. **2,317 tests collect cleanly** across the entire repository.
- **3 real bugs found and fixed** by this phase's own tests: 2 during M0–M9 development (§3), plus
  1 real schema-parity defect (a missing database index) found only once a live database
  validation became possible at acceptance (`docs/phase18_final_acceptance_migration_report.md`
  §4) — a category of bug offline testing structurally cannot catch.
- **1 migration** (`21177d5b859e_add_meme_candidates_table.py`) — written, chain-validated, and
  **now runtime-validated**: applied, downgraded, and re-applied cleanly against a dedicated,
  disposable database. Still never applied to the real `ai_newsroom` database.
- **2 LLM Capabilities** added (`meme_concept`, `meme_copywriting`) — **0 live calls made**, now
  proven correct against a real `FakeLLMGateway`-backed, real-database-persisted execution too.
- **1 image-generation adapter** shipped (`MockImageAdapter`) — deterministic, zero-network,
  zero-cost. **0 real provider adapters exist or were attempted.**
- **Full-suite regression**: 7 pre-existing failures (0 Phase 18 regressions), each proven — not
  assumed — to predate Phase 18 by reproduction at the exact Phase 17 branch point.
- **Static analysis**: 5 Ruff findings + 2 mypy findings in Phase 18 files, all real, all fixed;
  0 remaining in either tool across Phase 18's own files.

## 6. Safety analysis

- **Sensitivity coverage**: a single, shared lexicon (`services.meme_opportunity.
  detect_sensitive_categories`, deliberately not duplicated between M1 and M3) covers the brief's
  own nine categories: death/tragedy, disaster, war, crime-with-victim, minors'-safety, protected
  characteristics, serious illness, legal-jeopardy/unconfirmed-accusation, harassment/stalking.
  Recall is deliberately favored over precision (a false block costs far less than a false pass).
- **Defense in depth**: M1's `SENSITIVE_BLOCK` is checked again independently at M7 (the quality
  gate), so a story that should have been blocked at opportunity-detection but somehow reached the
  quality gate is still caught before `READY_FOR_EDITOR`.
- **Hard-block precedence is absolute and tested**: `test_reject_overrides_even_a_perfect_render`
  (M7) proves a safety `BLOCK` overrides every other signal, including a flawless render — no
  combination of good scores anywhere else can produce a false approval.
- **Originality is honestly scoped, not oversold**: M3 can only detect a named-existing-meme-
  template reference or a headline-restated-as-punchline — it cannot and does not claim to detect
  similarity to memes already circulating on the internet. This is documented as a **permanent**
  limitation in three places (M0 §8, M3 report, this report), not a "TODO."
- **Bounded regeneration is enforced, not advisory**: `apply_regeneration_bounds()` (M7) is a
  required second call that downgrades a regenerate recommendation to `REJECT` once
  `MAX_CONCEPT_REGENERATIONS`/`MAX_IMAGE_REGENERATIONS` (both `1`) is reached — tested in both
  directions.
- **No content published, ever, anywhere in this phase**: `MemeCandidate.published` has no setter
  in this phase's entire codebase — enforced by absence of code, not merely policy.

## 7. Cost analysis

- **Two LLM calls per meme attempt** (`meme_concept`, `meme_copywriting`) — never made live in
  this phase. M1's zero-LLM opportunity gate exists specifically to keep this bounded: only
  events M1 recommends should ever reach these two calls.
- **Image generation cost today is $0** — the only wired adapter (`MockImageAdapter`) is free and
  local. `MemeImageGenerationResult.cost_usd`/`provider`/`model_used` fields already exist and are
  exercised by tests, ready for a real provider's pricing the moment one is authorized and built.
- **Cost visibility exists at two levels, each now proven independently against a real database**:
  (1) the two LLM Capabilities are registered exactly like every other Capability, so
  `RedisCostTracker`/`AIExecution` recording applies to them automatically the moment a real
  `MEME_GENERATION` task runs (unmodified Phase 17 mechanism); (2) `MemeCandidate.
  cumulative_cost_usd` (M9's `add_cost()`) accumulates per-candidate total spend across
  concept/copy/image attempts, including regenerations — proven via real Postgres transactions at
  acceptance (exact accumulation, negative-value rejection). **These two systems are not yet wired
  to fire together automatically** — confirmed and explicitly classified as deferred
  live-orchestrator work, not an acceptance blocker, in `docs/
  phase18_final_acceptance_db_integration_report.md` §4 (no code triggers a real capability call
  today, so there is no live call site this wiring could attach to yet).
- **No budget enforcement gap**: `RedisBudgetGuard`/`llm_budget_mode` are capability-name-agnostic
  and apply to `meme_concept`/`meme_copywriting` automatically once real calls occur.

## 8. Production readiness

**Not production-active, by design — every new mode flag defaults to `"off"`.** As of final
acceptance, step 1 below is complete (against a disposable validation database; the real
`ai_newsroom` database still awaits it) and step 2 is validated as safe to flip (executor-hook
DB integration now proven). What remains, in order of increasing risk:

1. ~~Apply the migration~~ — **done against a disposable validation database**
   (`docs/phase18_final_acceptance_migration_report.md`); applying it to the real `ai_newsroom`
   database remains a mechanical, no-design-question-remaining step.
2. **Flip `meme_opportunity_mode`/`meme_safety_gate_mode` to `"shadow"`** — zero cost, zero risk;
   now validated end-to-end against a real database (`docs/
   phase18_final_acceptance_db_integration_report.md` §1), not merely by code inspection. Lets
   real production shadow data validate M1's/M3's thresholds (both disclosed as v1, calibrated
   against small hand-built gold sets, not production volume) before anything further.
3. **Build a task-spawning orchestrator** — nothing in this phase creates a `MEME_GENERATION`
   `EditorialTask` automatically; this is a genuinely new piece of work, not merely a flag flip.
4. **Close the M8 live-Bot-dispatch test gap** — `bot/handlers/meme_preview.py`'s own callback
   routing remains untested against a real Telegram `Bot`/`Dispatcher` (every piece it depends on
   is independently validated) — recommended before step 6.
5. **Human-authorize and build a real image-generation provider adapter** — `ImageGenerationRequest`/
   `Response` are already stable and provider-agnostic; this is a contained, additive change.
6. **Human-authorize a live Telegram send** — requires `meme_telegram_preview_mode` to gain a
   `"live"` value in code first (does not exist), plus a real `editorial_chat_id` for memes.

## 9. Known limitations (consolidated from every milestone report)

- Irony/contrast detection (M1) and the safety/originality/quality heuristics (M3, M7) are
  lexical/keyword-based, not LLM-based, by explicit design (the brief's own "0 additional LLM
  calls if possible") — all disclosed as coarse, all versioned (`v1`), all expected to need
  recalibration against real shadow-mode volume before any future enforce-style mode.
- Originality detection cannot see the outside internet — permanent, not fixable within this
  architecture (M3, M0 §8).
- The renderer's "don't cover the key object" guarantee is convention-based (subject assumed
  centered), not vision-based — a real provider that ignores composition guidance could break
  this assumption (M6 §5).
- No bundled display font — Pillow's built-in default font is used; legible but not styled like a
  classic meme font (M6 §5).
- Regenerate/fallback preview actions (M8) are recognized and acknowledged but do not yet
  re-trigger any generation step — no live orchestrator exists to re-run a pipeline step for an
  existing candidate.
- Cost/decision persistence methods (M2–M9) have no live call site — every one is real and now
  DB-integration-tested (`docs/phase18_final_acceptance_db_integration_report.md`), but none has
  been exercised end-to-end against a running, automatically-triggered pipeline, since no such
  pipeline runs live anywhere in this phase (§8's own remaining step 3).
- ~~Environment constraint: local Postgres/Redis stack unreachable~~ — **resolved at final
  acceptance**: Docker was started, a dedicated disposable database was created, and every
  DB-backed piece except one was validated against it (`docs/
  phase18_final_acceptance_db_integration_report.md`). The one remaining gap:
  `bot/handlers/meme_preview.py`'s own callback-dispatch logic still has not been exercised
  against a real Telegram `Bot`/`Dispatcher` object (no Telegram network connection was made or
  attempted, per the operating rules) — every piece it depends on (keyboards, formatting,
  `MemeCandidateService`, the dry-run-proven `send_meme_preview()`) is independently validated.
- **New, found during final acceptance**: `record_editor_decision()` does not merge `reasons`/
  `notes` across repeated calls (consistent with its own documented contract, flagged for a future
  caller's awareness); `MemeCandidateStatus` needed an explicit, documented mapping for M7's
  `REGENERATE_CONCEPT`/`REGENERATE_IMAGE` decisions (no dedicated status value existed for either -
  resolved, not a blocker). Full detail: `docs/phase18_final_acceptance_db_integration_report.md`.

## 10. Recommendation: GO / NO-GO

**Updated at final acceptance** — see `docs/phase18_final_acceptance_report.md` §17 for the full,
per-capability GO/NO-GO matrix. Summary: **GO for the engineering merge** (now DB-validated, not
merely offline-tested), **GO for enabling `meme_opportunity_mode`/`meme_safety_gate_mode` shadow
modes** (zero cost/risk, now DB-integration-proven), **NO-GO for any paid or live-send activation**
until a human explicitly authorizes it — nothing in this phase attempted a paid or live call at
any point, during development or during acceptance.

Everything the brief asked for — schemas, services, capabilities, prompts, tests, offline
validation, shadow-safe integration, safety checks, docs, commits, checkpoints, **and now real
database validation** — is complete.

## Appendix — Final validation summary

**Superseded by `docs/phase18_final_acceptance_report.md`'s own Appendix/§10-§13** — retained here
for historical record of what was verifiable during M0–M9 development, before Docker was
available:

- `python -m pytest tests/ -k "phase18 or meme" -q` → 156 passed (development-time; **174 passed**
  as of acceptance, against a real database).
- `python -m pytest --collect-only -q` → 2,299 tests collected (development-time; **2,317** as of
  acceptance).
- `python -m pytest tests/test_capability_registry.py tests/test_registry_consistency.py
  tests/test_workflow_registry.py -q` → **20 passed** (confirms `NEWS_ANALYSIS`/
  `CONTENT_GENERATION`/`MEME_GENERATION` registration and every existing capability-registry
  invariant are unaffected) — re-verified unchanged at acceptance.
- `python -m pytest tests/test_bot_router_registration.py -q` → **3 passed** (confirms the bot's
  root-router/dispatcher wiring is unaffected by the two new, inert routers) — re-verified
  unchanged at acceptance.
- `python -m alembic heads` → single head `21177d5b859e` (development-time, syntax-only; **runtime
  upgrade/downgrade/re-upgrade validated** at acceptance).
- Visual spot-check of the rendering pipeline (M6): a sample meme was rendered end-to-end (mock
  image → text overlay) and visually inspected during development — correct top/bottom text
  placement, high-contrast white-on-color text with black stroke, center "key object" zone
  completely untouched. The temporary output file was not committed.
- No `.env` file was read, modified, or committed. No secret value was printed at any point. No
  `docker compose config` or equivalent secret-revealing command was run — true throughout
  development and acceptance.
- No live LLM call, no live image-generation call, no live Telegram send occurred at any point
  during this phase's development **or its acceptance validation**.
