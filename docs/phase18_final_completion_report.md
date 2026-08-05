# Phase 18 — Meme Intelligence & Generation: Final Completion Report

**Branch:** `feature/phase18-meme-intelligence` (from `feature/phase17-editorial-intelligence` @
`8872624`) · **Commits:** 10 · **Checkpoint tags:** `checkpoint/phase18-m0-discovery` through
`checkpoint/phase18-m9-human-feedback` · **Status: engineering scope 100% complete (M0–M9). No
live/paid activity of any kind occurred.**

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
`meme_candidates` table), introduced early (M2) exactly as M0 planned, and it has not been applied
to any database — no Postgres/Redis instance was reachable in this development environment at any
point in this work (docker was not running), which is disclosed in every milestone report that
touches DB-backed code, not glossed over.

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
- **Eight new mode flags**, all following the exact `Literal["off", ...]`, default-`"off"`
  convention established in Phases 15–17: `meme_opportunity_mode`, `meme_safety_gate_mode`,
  `meme_image_generation_mode`, `meme_telegram_preview_mode` (plus supporting settings
  `meme_image_max_bytes`). No existing flag was repurposed.

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

- **59 files changed** since the Phase 17 branch point: **51 new**, **8 modified** (all 8 are
  additive: new registry/hook entries, new enum values, new settings — none rewrites existing
  logic).
- **+7,027 / −4 lines** (the 4 deletions are import-list formatting only).
- **10 commits**, one per milestone, each tagged (`checkpoint/phase18-m{N}-*`).
- **156 new tests**, all passing; **2,299 tests collect cleanly** across the entire repository
  (up from 2,160 immediately before this phase began), confirming zero import/collection
  regressions introduced anywhere.
- **2 real bugs found and fixed** by this phase's own tests before merge (§3).
- **1 migration** (`21177d5b859e_add_meme_candidates_table.py`) — written, syntax- and
  chain-validated (`alembic heads`), **not applied to any database**.
- **2 LLM Capabilities** added (`meme_concept`, `meme_copywriting`) — **0 live calls made**.
- **1 image-generation adapter** shipped (`MockImageAdapter`) — deterministic, zero-network,
  zero-cost. **0 real provider adapters exist or were attempted.**

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
- **Cost visibility exists at two levels**: (1) the two LLM Capabilities are registered exactly
  like every other Capability, so `RedisCostTracker`/`AIExecution` recording applies to them
  automatically the moment a real `MEME_GENERATION` task runs; (2) `MemeCandidate.
  cumulative_cost_usd` (M9's `add_cost()`) accumulates per-candidate total spend across
  concept/copy/image attempts, including regenerations — not yet wired to a live call site, but
  real and tested.
- **No budget enforcement gap**: `RedisBudgetGuard`/`llm_budget_mode` are capability-name-agnostic
  and apply to `meme_concept`/`meme_copywriting` automatically once real calls occur.

## 8. Production readiness

**Not production-active, by design — every new mode flag defaults to `"off"`.** What would be
required to move any single piece toward production, in order of increasing risk:

1. **Apply the migration** (`alembic upgrade head`) — mechanical, no design question remains.
2. **Flip `meme_opportunity_mode`/`meme_safety_gate_mode` to `"shadow"`** — zero cost, zero risk;
   lets real production shadow data validate M1's/M3's thresholds (both disclosed as v1,
   calibrated against small hand-built gold sets, not production volume) before anything further.
3. **Build a task-spawning orchestrator** — nothing in this phase creates a `MEME_GENERATION`
   `EditorialTask` automatically; this is a genuinely new piece of work, not merely a flag flip.
4. **Human-authorize and build a real image-generation provider adapter** — `ImageGenerationRequest`/
   `Response` are already stable and provider-agnostic; this is a contained, additive change.
5. **Human-authorize a live Telegram send** — requires `meme_telegram_preview_mode` to gain a
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
- Cost/decision persistence methods (M2–M9) have no live call site — every one is real and
  independently tested, but none has been exercised end-to-end against a running pipeline, since
  no such pipeline runs live anywhere in this phase.
- **Environment constraint carried through every milestone**: the local Postgres/Redis stack was
  unreachable in this development session (docker not running) — every DB-backed piece
  (executor hooks' live integration, `MemeCandidateService`'s DB methods, the bot handler against
  a real database) was written to mirror an already-proven pattern as closely as possible and
  unit-tested wherever the logic could be isolated from the database, but has not been exercised
  against a live database. This should be the first thing validated once infrastructure is
  available, before any shadow-mode flag is flipped.

## 10. Recommendation: GO / NO-GO

**GO for the engineering merge** (M0–M9 as built) into the main development line, **NO-GO for any
live/paid/production activation** until:

1. The migration is applied and validated against a real database (mechanical).
2. `_attach_meme_opportunity`/`_attach_meme_safety_originality` are exercised at least once
   against a real `CapabilityExecutor`/database run, to confirm the DB-integration shape matches
   the already-proven Phase 17 pattern in practice, not merely by code inspection.
3. A human reviews and explicitly authorizes: (a) building a real image-generation provider
   adapter and making the first paid call, and (b) configuring a real editorial chat and making
   the first live Telegram send. Neither has been built, attempted, or requested in this phase.

Everything else the brief asked for — schemas, services, capabilities, prompts, tests, offline
validation, shadow-safe integration, safety checks, docs, commits, checkpoints — is complete.

## Appendix — Final validation summary

- `python -m pytest tests/ -k "phase18 or meme" -q` → **156 passed**.
- `python -m pytest --collect-only -q` → **2,299 tests collected**, 0 collection errors.
- `python -m pytest tests/test_capability_registry.py tests/test_registry_consistency.py
  tests/test_workflow_registry.py -q` → **20 passed** (confirms `NEWS_ANALYSIS`/
  `CONTENT_GENERATION`/`MEME_GENERATION` registration and every existing capability-registry
  invariant are unaffected).
- `python -m pytest tests/test_bot_router_registration.py -q` → **3 passed** (confirms the bot's
  root-router/dispatcher wiring is unaffected by the two new, inert routers).
- `python -m alembic heads` → single head `21177d5b859e`, confirming a linear, unbranched
  migration chain.
- Visual spot-check of the rendering pipeline (M6): a sample meme was rendered end-to-end (mock
  image → text overlay) and visually inspected during development — correct top/bottom text
  placement, high-contrast white-on-color text with black stroke, center "key object" zone
  completely untouched. The temporary output file was not committed.
- No `.env` file was read, modified, or committed. No secret value was printed at any point. No
  `docker compose config` or equivalent secret-revealing command was run.
- No live LLM call, no live image-generation call, no live Telegram send occurred at any point
  during this phase's development.
