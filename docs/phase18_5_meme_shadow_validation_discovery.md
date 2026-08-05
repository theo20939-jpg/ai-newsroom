# Phase 18.5 M0 — Meme Intelligence Shadow Validation: Discovery Report

Status: complete. Read-only audit only — no production code path was enabled, no row was
written, no LLM/image/Telegram call was made.

## 1. Sources reviewed

`docs/phase18_final_acceptance_report.md`, `docs/phase18_final_completion_report.md`,
`docs/phase18_m1_meme_opportunity_report.md`, `docs/phase18_m3_meme_safety_originality_report.md`,
`docs/phase18_m7_meme_quality_gate_report.md`, plus the actual current source of
`services/meme_opportunity.py`, `services/meme_safety.py`, `capabilities/executor.py`,
`core/config.py`, and a **read-only** query pass against the real, live `ai_newsroom` database
(Postgres was already up from the Phase 18 acceptance session; `SELECT`-only statements, no
writes, confirmed by `git status`/DB row-count checks before and after).

## 2. Where the meme opportunity hook is wired today

`capabilities/executor.py::_attach_meme_opportunity()` runs at the `"quality"` step of any
workflow whose step is literally named `"quality"` (i.e., today, only `CONTENT_GENERATION` — no
`workflow_name` check exists, the hook only checks `step.capability == "quality"`), gated by
`settings.meme_opportunity_mode == "shadow"`. It calls `services.meme_opportunity.
apply_meme_opportunity_shadow()`, which is a **pure, zero-LLM, zero-network function** of
`(title, content, category, published_at, research_output)` — `assess_meme_opportunity()` itself
never touches the database, the Gateway, or Telegram.

**Confirmed by direct query**: `meme_opportunity_mode` still defaults to `"off"`
(`core/config.py:331`, unchanged since Phase 18 acceptance), and a full-table scan of the real
`editorial_tasks.workflow` JSON column (`SELECT COUNT(*) FROM editorial_tasks WHERE workflow::text
LIKE '%meme_opportunity%'`) returns **0 rows** out of 12,990 real `EditorialTask` rows. **The
shadow hook has never once run against real production traffic.** This is the central fact this
phase exists to change, safely.

## 3. What data is actually available, read-only, without enabling anything

`assess_meme_opportunity()`'s full input signature is `(news_event_title: str, news_event_content:
str | None, news_event_category: EventCategory, news_event_published_at: datetime | None,
research_output: dict, *, has_image_candidate: bool | None = None)`. Every one of these is a
plain column already sitting on the real, live `NewsEvent` table:

| Field | Source | Real-data availability (queried, read-only) |
|---|---|---|
| `title` | `NewsEvent.title` | Always present |
| `content` | `NewsEvent.content` | 12,426 / 12,430 non-NULL (99.97%); 0 empty strings among those |
| `category` | `NewsEvent.category` | Always present (8-value `EventCategory` enum) |
| `published_at` | `NewsEvent.published_at` | Present on ingested events |
| `research_output` | Would come from a completed `NEWS_ANALYSIS` task's `research` step — **not required**: `assess_meme_opportunity()` already degrades gracefully to `{"facts": [], "gaps": []}` (M1's own tested "Research did not run" path) | Optional; this phase does not join against `EditorialTask` for it (§5) |
| `has_image_candidate` | Would come from Phase 16's `image_intelligence` shadow result — optional keyword-only parameter | Not used in this phase's read-only audit (§5) |

**Real production volume** (read-only `SELECT COUNT(*)`/`GROUP BY`, no row printed beyond
aggregate counts): **12,430 total `NewsEvent` rows**, category breakdown:

| Category | Count | Share |
|---|---|---|
| UNKNOWN | 6,301 | 50.7% |
| AI | 3,235 | 26.0% |
| GADGETS | 980 | 7.9% |
| STARTUPS | 766 | 6.2% |
| SOFTWARE | 621 | 5.0% |
| TECH | 290 | 2.3% |
| HARDWARE | 214 | 1.7% |
| CYBERSECURITY | 23 | 0.2% |

`UNKNOWN` being the single largest category (a known, pre-existing fact - not a Phase 18/18.5
finding; `services/event_category.py`'s own source-tag-based categorization leaves many sources,
especially Telegram channels, uncategorized) is itself a relevant input to M2's category
distribution metric.

## 4. What can be collected without changing architecture

Per this phase's own explicit constraints (no new LLM calls, no `CapabilityExecutor`/
`WorkflowRunner` changes, no `ContentDraft`/`NewsEvent` mutation, no automatic `MEME_GENERATION`
task creation), the only safe mechanism is: **read already-persisted `NewsEvent` rows directly,
call the existing pure `assess_meme_opportunity()` function in-process, and record the result
externally to the database** — never touching `CapabilityExecutor`, never flipping
`meme_opportunity_mode` in the real environment, never creating an `EditorialTask`.

This is a deliberately *separate* code path from the production shadow hook, not a modification
of it — `_attach_meme_opportunity()` and `capabilities/executor.py` are untouched by this phase.
The only reused production code is the pure function itself
(`services.meme_opportunity.assess_meme_opportunity`), exactly as instructed ("Использовать
существующий services.meme_opportunity. Добавить только сбор аналитики").

## 5. Storage decision

The brief asks to evaluate, in order: (A) `EditorialTask.workflow` JSON, (B) existing analytical
infrastructure, (C) only if neither works, a new table.

- **(A) rejected**: `EditorialTask.workflow` is owned exclusively by `WorkflowRunner` and is only
  ever populated during a real workflow execution it drives end-to-end (Phase 17/18's own
  established discipline — every `_attach_*` hook writes into the *current* step's own
  `structured_output`, never retroactively into an unrelated, already-`COMPLETED` task's JSON from
  an external batch process). Writing into it here would mean either (a) mutating historic,
  already-`COMPLETED` `EditorialTask` rows from outside the workflow engine — a real, if narrow,
  "production behavior change" the brief explicitly forbids — or (b) creating new `EditorialTask`
  rows just to hold shadow data, which the brief also explicitly forbids ("не создавать
  MemeGeneration задачи автоматически," and more generally, no new task rows for a validation
  exercise). Both are rejected.
- **(B) — this project's own actual "existing analytical infrastructure" is local, versioned JSON
  artifacts, not a database table.** Every prior shadow-validation/backtest/gold-set exercise in
  this codebase (Phase 15 M4's cutover samples, every Phase 17 M1–M7 backtest/gold-set/comparison
  result, Phase 18 M0's own 32-item real-news audit) was persisted as a local
  `scripts/_phaseNN_*.json` artifact plus a narrative `docs/` report — never a new database table.
  This phase adopts that exact, already-proven convention: `services/meme_shadow_analytics.py`
  produces plain, JSON-serializable result records; a companion script writes them to
  `scripts/_phase18_5_shadow_collection_results.json`. This satisfies "используй существующую
  аналитическую инфраструктуру" literally, using the infrastructure this project actually has.
- **(C) not needed.** No migration, no new table.

## 6. Constraints and risks carried into M1–M4

- The read-only production audit uses `research_output={"facts": [], "gaps": []}` for every event
  (no `EditorialTask`/`research` join) — this means `source_sufficiency` is judged from
  `NewsEvent.content` alone, which is exactly the same degradation path M1's own tests already
  cover, not a new untested code path.
- `UNKNOWN`-category dominance (50.7% of real volume) will materially affect the category-
  distribution metric (M2) — flagged now so it is not mistaken for a bug when the M2 report shows
  a large `UNKNOWN` slice.
- This phase's own collection script performs `SELECT`-only queries against the real `ai_newsroom`
  database. No `INSERT`/`UPDATE`/`DELETE` statement appears anywhere in Phase 18.5 code — verified
  directly in every milestone's own tests (§ M1 report).
- Per the brief's own stop conditions, if at any point this phase were to require a new external
  API, a paid LLM call, image generation, a Telegram send, a new production migration, or a change
  to `CapabilityExecutor`/`WorkflowEngine`/the Telegram pipeline/`ContentDraft` schema, work stops
  and confirmation is requested. None of these were required for M0.

## 7. Recommended milestone approach (confirms the brief's own M1–M4 order)

1. **M1**: `services/meme_shadow_analytics.py` (pure normalization + a thin, explicitly read-only
   collection script) — no business logic beyond what M1 (Phase 18) already built.
2. **M2**: metrics computed from the collection script's own output — opportunity rate, category
   distribution, safety block rate, pattern/evidence-code frequency, a false-positive-tracking
   schema (not yet populated — that requires human review, M3).
3. **M3**: a stratified, human-reviewable sample (≥50 real events across HIGH/MEDIUM/LOW/BLOCKED)
   with every `human_decision`/`human_notes` field left genuinely blank.
4. **M4**: the final validation report, synthesizing M0–M3, with an explicit GO/NO-GO
   recommendation for enabling `meme_opportunity_mode="shadow"` in real production (the *next*
   phase's own concern, not something this phase enables itself).
