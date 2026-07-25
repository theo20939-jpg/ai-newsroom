# Phase 9 — Research / Intelligence Discovery

**Status: exploration document. NOT a specification. NOT binding. Nothing here is frozen.**

This document studies the current repository state and the original project design documents to
determine the smallest coherent next phase after Phase 8 (Capability Layer, frozen and closed —
see `docs/phase8_capability_contract.md`). It does not implement anything, does not modify
production code, and does not redesign Phase 6/7/8. Every claim below is labeled **FACT**
(directly observed in the repository), **INFERENCE** (a conclusion drawn from facts), or
**RECOMMENDATION**/**OPEN QUESTION** (a judgment call left for the reader to decide, not
something this document settles).

---

## 1. Executive Summary

The repository already implements far more of the originally-specified pipeline than "Phase 8 =
Capability Layer" alone suggests: source ingestion (Telegram, RSS/Atom, arXiv, GitHub, Hacker
News — not just Telegram), deterministic cleaning, exact deduplication, the Workflow Engine, and
two real Capabilities (`ScoringCapability`, `QualityCapability`) are all built and tested. What is
**not** built is almost everything the original design called the "AI Intelligence Layer" and,
more surprisingly, the entire **deterministic Ranking Engine** that the original specification
(`docs/05_Scoring_Ranking_Specification.md`) says must run **before** any AI Capability is ever
invoked.

The single most consequential finding is structural, not missing-feature: **`NewsEvent` is a
per-source, per-publication row, not a merged real-world event**, and `EditorialTask` is
hard-wired to exactly one `NewsEvent` (`event_id: Mapped[uuid.UUID]`, a single foreign key). Two
different sources reporting the same real-world happening today produce two unrelated `NewsEvent`
rows. This is not an oversight Phase 9 discovered — it is already called out in the codebase
itself: `WorkflowType.DAILY_DIGEST`'s own docstring says a digest "inherently spans many events"
and is deliberately never registered for exactly this reason (`schemas/workflow.py:17-27`). Any
cross-event responsibility (clustering, source-diversity counting, digesting) does not fit the
current one-task-one-event execution shape without a design decision this document does not make.

The original design also already separates **Research** and **Intelligence** into two distinct,
sequentially-ordered Capabilities inside an already-frozen, already-committed Phase 5 workflow
(`workflows/definitions/news_analysis.py`: `research → intelligence → engagement_analysis →
scoring`). Phase 9 does not get to decide whether they are separate — that was decided in Phase 5.
What Phase 9 must decide is scope, output shape, and whether to build both in one phase.

Recommended reading order for this document: Section 4 (data model), Section 6 (gap analysis +
Q1–Q10), Section 13 (proposed smallest slice), Section 15 (boundary recommendation).

---

## 2. Current System State

**Existing relevant components (FACT, file-cited):**

| Layer | Component | State |
|---|---|---|
| Ingestion | `integrations/sources/{telegram,rss,arxiv,github,hacker_news}_source.py` | Implemented — 5 adapters, not Telegram-only |
| Ingestion orchestration | `services/collector.py` | Implemented — fetch → clean → dedup → store |
| Normalization | `services/cleaning.py` | Implemented — deterministic, no AI |
| Exact deduplication | `services/deduplication.py` | Implemented — single hash equality check |
| Source config | `services/source_registry.py`, `services/source_pack_importer.py`, `services/source_importer.py` | Implemented |
| Workflow engine | `workflows/runner.py`, `workflows/registry.py` | Implemented (Phase 5, frozen) |
| Workflow definitions | `workflows/definitions/{news_analysis,content_generation}.py` | Implemented, but reference unregistered capability names |
| Capability Layer | `capabilities/{registry,executor,gateway_call,errors,capability_mapping}.py` | Implemented (Phase 6–8, frozen) |
| Real Capabilities | `capabilities/{scoring,quality}_capability.py` | Implemented (Phase 8 M3/M7) |
| Prompt storage | `integrations/prompts/file_repository.py` | Implemented (Phase 8 M2) |
| LLM Gateway | `integrations/llm_gateway/` | Implemented (Phase 7, frozen) — `generate()` only; `embed()`/`classify()`/`moderate()`/`rerank()` all raise `UnsupportedGatewayCapabilityError` in the real adapter |
| Cost/audit persistence | `database/models/ai_execution.py` + `services/ai_execution_mapper.py` | Schema exists; **mapping logic exists but nothing writes a row** (Amendment B, deliberately deferred) |
| Deterministic Ranking Engine | — | **Does not exist anywhere in the codebase** |
| Research/Intelligence Capabilities | — | **Do not exist** — only referenced as unregistered string names in `workflows/definitions/news_analysis.py` |
| Event clustering / grouping | — | **Does not exist** — no schema field, no service |
| Vector / embedding infrastructure | — | **Does not exist** — no dependency, no adapter implementation |

**Current data flow (FACT, traced through code):**

```
NewsSource (DB) --[AdapterRegistry.resolve]--> SourceAdapter.fetch() --> RawNewsItem
    --> cleaning.clean_item() --> CleanedItem
    --> deduplication.is_duplicate(hash) --> NewsEvent (status=NEW, category=UNKNOWN)  [services/collector.py]

(manual/external) --> workflow_service.create_task(event_id, workflow_type, priority) --> EditorialTask
    --> WorkflowRunner.run() --> CapabilityExecutor.execute(step)
        --> CapabilityRegistry.resolve(step.capability) --> Capability.execute(CapabilityContext)
        --> CapabilityResult.structured_output --> stored into EditorialTask.workflow (JSON) step_results
```

**Current architectural boundaries (FACT, re-verified against the Phase 8 audit's own findings,
still true):** `Capability` implementations may depend only on `LLMGateway` and `PromptRepository`
(mechanically enforced by `scripts/validate_architecture.py`'s `capability-isolation` rule);
`CapabilityExecutor` bridges `Workflow` and `Capability` and holds a DB session only to re-fetch
`EditorialTask`/`NewsEvent` read-only; no Capability may hold `BudgetGuard`/`CostTracker` directly.
These boundaries are frozen and Phase 9 must design within them, not around them.

---

## 3. Repository Evidence

Exact files/modules inspected for this Discovery (not exhaustive of the whole repo, but every file
cited below was opened and read, not inferred from its name):

**Database models**: `database/models/{news_event,news_source,telegram_channel,editorial_task,ai_execution,content_draft,user}.py` (all 7 models read in full).

**Schemas**: `schemas/{raw_news_item,source_definition,source_import,capability,capability_definition,workflow,editorial_task}.py`.

**Source pipeline**: `services/{collector,cleaning,deduplication,adapter_registry,adapter_keys,source_registry,source_importer,source_pack_importer}.py`, `integrations/sources/{base,rss_source}.py`.

**Workflow layer**: `workflows/definitions/{news_analysis,content_generation}.py`, `workflows/runner.py` (previously audited in Phase 8), `schemas/workflow.py`.

**Capability layer**: `capabilities/{registry,executor,capability_mapping,gateway_call,errors,scoring_capability,quality_capability}.py`, `integrations/prompts/{protocol,file_repository}.py` (all re-confirmed current as of the Phase 8 audit commit `dc35f9f`).

**LLM Gateway / embeddings**: `integrations/llm_gateway/protocol.py`, `integrations/llm_gateway/providers/openai_adapter.py` (embed/classify/moderate/rerank all raise `UnsupportedGatewayCapabilityError`, lines 336-357).

**Cost/audit**: `services/ai_execution_mapper.py`, `services/cost_estimator.py`, `services/cost_tracker.py`, `services/pricing_catalog.py`.

**Dependencies**: `pyproject.toml` (no vector-DB package, no `jsonschema`, `openai>=2.40` is the only provider SDK).

**Original design documents** (pre-Phase-5, never previously read in depth this session):
`docs/05_Scoring_Ranking_Specification.md` (full read), `docs/06_Functional_Specification.md`
(§3.3, §4, §5 read), `docs/08_Database_Schema_Data_Models.md` (§8-16 read), `docs/13_1_Final_Corrections_Before_Development.md`
(§5-11 read), `docs/07_AI_Architecture_Document.md` (prompt-repository structure, previously read
this session).

**Phase 8 documents**: `docs/phase8_capability_contract.md`, `docs/phase8_capability_planning.md`,
`docs/phase8_capability_discovery.md` — all re-read; none contains a forward-looking Phase 9 note
(`grep -rl "Phase 9"` across all `*.md` returns nothing).

**Tests/fakes**: `tests/fakes/{fake_gateway,fake_prompt_repository,fake_provider_adapter,fake_capability,fake_infra}.py`.

What each relevant component currently does is described inline in Sections 2 and 4-6 rather than
repeated here.

---

## 4. Current News Data Model

### Source (`database/models/news_source.py`)

**FACT**: One row per ingestion source (`sources` table). Fields: `id, name, type (TELEGRAM|RSS|
NEWS_API|WEB|SOCIAL), url, category, reliability_score: float|None, active, created_at, updated_at`.

**FACT**: `reliability_score` is populated from `SourceImportItem.reliability_score`
(`schemas/source_import.py:14`) or `SourceDefinition.reliability` (`schemas/source_definition.py:45`,
range 0.0-1.0) at import time — a static, editor-curated confidence value, not a dynamically
computed one. This is a real, already-existing "source-confidence" signal Phase 9 could read, but
**nothing currently reads it** (grep found zero non-import consumers).

**Naming ambiguity (FACT)**: `TelegramChannel` (`database/models/telegram_channel.py`) is a
different thing entirely — it is an **output/publishing** channel ("a Telegram channel AI
Newsroom manages content for," `brand_voice_id`, `settings`), not an ingestion source. A
`NewsSource(type=TELEGRAM)` and a `TelegramChannel` are unrelated tables with no FK between them.
Anyone reading "Channel" in a Phase 9 discussion must disambiguate which one is meant.

### NewsEvent (`database/models/news_event.py`)

**FACT**: Fields: `id, source_id (single FK, non-nullable), title, summary, content, url, category
(EventCategory enum), published_at, collected_at, hash (unique), status (EventStatus enum),
created_at, updated_at`.

**FACT**: `hash = sha256(f"{source_id}:{external_id}")`, computed in
`services/collector.py:173-179`, and is the sole deduplication key
(`services/deduplication.py:12-15` — one `SELECT ... WHERE hash == content_hash`).

**FACT**: `category` is unconditionally set to `EventCategory.UNKNOWN` at creation time
(`services/collector.py:156`). Nothing in the current codebase ever assigns a real category.

**INFERENCE (answers Q2 directly)**: Because the dedup hash is keyed on `(source_id,
external_id)`, **`NewsEvent` represents one deduplicated publication from one specific source —
not a real-world event merged across sources.** Two sources reporting the identical real-world
happening produce two independent `NewsEvent` rows with no relationship between them. The model's
class name ("NewsEvent") does not match its actual dedup semantics ("NewsPublication" would be
more accurate). This is corroborated independently by `schemas/workflow.py:17-27`
(`WorkflowType.DAILY_DIGEST` is declared but deliberately never registered, with the explicit
comment: *"EditorialTask.event_id is a single foreign key, and a digest inherently spans many
events"*) — a second, independent part of the codebase already documents the same structural fact.

**FACT (answers Q1)**: The current unit of intelligence work is **one `NewsEvent`, executed via
one `EditorialTask`**. `EditorialTask.event_id` is a single, non-nullable FK
(`database/models/editorial_task.py:38-40`). `CapabilityContext.business.news_event` is a single
`NewsEventSnapshot`, never a list (`schemas/capability.py`). `WorkflowStepDefinition`/
`WorkflowDefinition.required_input=["event_id"]` (singular) for both existing workflows. There is
**no** unit-of-work anywhere in the system today representing a group/cluster of `NewsEvent`s.

### EditorialTask (`database/models/editorial_task.py`)

**FACT**: Fields: `id, event_id (single FK), priority (TaskPriority: S|A|B|C), workflow (JSON,
holds serialized `WorkflowExecutionState`), status (TaskStatus), retry_count, created_at,
updated_at`.

**FACT**: `priority` is a **caller-supplied input**, not derived from any score
(`services/workflow_service.py:65` — `priority=command.priority`, taken directly from
`EditorialTaskCreate`). No code anywhere computes a priority from event data.

**FACT**: `workflow` (JSON) holds `WorkflowExecutionState.step_results: list[WorkflowStepResult]`,
and `capabilities/executor.py`'s `_build_context()` converts completed, successful step results
into `WorkflowExecutionStateSnapshot.step_results: dict[str, dict[str, Any]]`
(`schemas/capability.py`), passed into each subsequent Capability's `CapabilityContext`. **This
step-chaining mechanism already exists at the schema/executor level** but is **not exercised by
either existing real Capability** — `ScoringCapability`/`QualityCapability` never read
`context.business.workflow_state.step_results` (grep-confirmed: zero references in either file).
Phase 9 would be the first real proof that a later step can actually consume an earlier step's
Capability output.

### Persistence relationships (FACT, diagrammed)

```
NewsSource (1) ──< NewsEvent (many, one per source)
NewsEvent (1) ──< EditorialTask (many, but in practice one-active-task-per-event by convention, not enforced)
EditorialTask (1) ──< AIExecution (many, schema exists, NEVER WRITTEN — Amendment B)
EditorialTask (1) ──< ContentDraft (many)
```

No table links two `NewsEvent` rows to each other. No table links `NewsSource` engagement/metrics
data. No table stores a `research_report`/`intelligence_report`/`content_score`/`source_metrics`
row (see Section 10).

### Ambiguities / gaps (explicit, not hidden)

1. `category` is never classified — any "relevance to audience" work has no category signal to
   start from.
2. `EditorialTask.priority` has no derivation logic — the S/A/B/C tiers exist in the schema and
   drive workflow retry/budget semantics conceptually, but nothing computes them from real event
   data.
3. Whether one `NewsEvent` may have more than one **concurrent** `EditorialTask` is not enforced
   by any constraint (no unique index on `event_id`); this is unresolved, not merely undocumented.
4. `docs/13_1` §5.1 lists `score` as an MVP field of `news_events`, but the actual implemented
   model and the more detailed `docs/08` §8 field table both omit it — an internal inconsistency
   in the original design docs themselves, not something this Discovery resolves.

---

## 5. Existing Intelligence Capabilities

**What already exists**: `ScoringCapability` (`capabilities/scoring_capability.py`, Phase 8 M3/M5)
and `QualityCapability` (`capabilities/quality_capability.py`, Phase 8 M7). Both are real,
registered, tested, LLM-backed Capabilities proving the `CapabilityContext → GenerateRequest →
GenerateResponse → CapabilityResult` shape end to end, including one structured-output correction
retry (`ScoringCapability` only).

**Important honesty check (FACT)**: Phase 8's `ScoringCapability` output shape is `{"score": int,
"rationale": str}` (`prompts/scoring/v1.yaml`). This does **not** match the original
`docs/08_Database_Schema_Data_Models.md` §14 "Scoring Model" spec (`content_scores`:
`audience_fit, virality_score, engagement_prediction, timeliness_score, recommended_format`), and
it does not read the `research`/`intelligence`/`engagement_analysis` step outputs that would
precede it in `workflows/definitions/news_analysis.py`'s real step order. Phase 8's own
documentation is explicit about this: `ScoringCapability` was deliberately "the smallest
well-defined task with no tool dependency," chosen for mechanism-proving purposes, not as a
faithful implementation of the original Scoring Capability spec. **Phase 9 must not assume
"scoring is done" in the full-pipeline sense — only the mechanism is proven.**

**What does not exist**: `ResearchCapability`, `IntelligenceCapability`, any capability named
`"engagement"` for real (only a temporary persistence alias to `AICapability.INTELLIGENCE`, see
`capabilities/capability_mapping.py:9-12`, which its own docstring says "MUST be reconsidered
before any real Engagement Capability is implemented"), any deterministic Ranking Engine, any
clustering/near-duplicate service, any embedding-backed anything.

**What is partial**: the `NEWS_ANALYSIS` `WorkflowDefinition` (`workflows/definitions/news_analysis.py`)
already names and orders all four intended steps (`research → intelligence → engagement_analysis
→ scoring`) and their expected top-level output keys
(`["research_summary", "intelligence_report", "engagement_analysis", "score"]`) — this is a
complete **orchestration skeleton** with **zero real content** behind three of its four steps.
Running this workflow today would fail immediately at the `research` step with
`UnknownCapabilityError` (unregistered capability name), confirmed by tracing
`capabilities/executor.py:86-90`'s `registry.resolve()` call against the actual registered roster
in `capabilities/registry.py:132-133` (only `"scoring"`, `"quality"`).

---

## 6. Gap Analysis

### 6.1 Pipeline: implemented vs missing

```
ingestion            [IMPLEMENTED]  5 source adapters, services/collector.py
   ↓
normalization        [IMPLEMENTED]  services/cleaning.py — deterministic
   ↓
exact dedup           [IMPLEMENTED]  services/deduplication.py — hash equality
   ↓
event representation  [IMPLEMENTED, BUT SEMANTICALLY NARROW] — NewsEvent = per-source publication,
                       not a merged real-world event (Section 4). No clustering exists.
   ↓
deterministic ranking [MISSING ENTIRELY] — docs/05's Popularity/Editorial-Value/Opportunity/
                       Freshness/Authority scores, Raw Score, Editorial Priority derivation: zero
                       implementation (grep-confirmed, zero matches for any of these terms).
   ↓
intelligence (AI)     [MISSING] — research, intelligence, engagement_analysis: unregistered
                       capability names only, no implementation.
   ↓
scoring (AI, final)   [PARTIAL] — ScoringCapability exists but is a minimal proof-of-mechanism,
                       does not consume prior-step output, does not match the original spec shape.
   ↓
editorial workflow    [IMPLEMENTED skeleton] — WorkflowRunner/CapabilityExecutor work; EditorialTask
                       priority is manually supplied, not derived.
   ↓
digest generation     [NOT STARTED, EXPLICITLY BLOCKED] — WorkflowType.DAILY_DIGEST declared but
                       never registered; requires a many-events-per-task shape the architecture
                       does not have.
   ↓
content generation    [PARTIAL] — CONTENT_GENERATION workflow exists (copywriting → quality);
                       QualityCapability implemented (Phase 8 M7), CopywritingCapability does not
                       exist.
```

### 6.2 Key Architectural Questions — Direct Answers

**Q1. Unit of intelligence in the current system?** One `NewsEvent`, via one `EditorialTask`. No
cluster/group unit exists (Section 4).

**Q2. Does NewsEvent represent a publication, a real-world event, or is it ambiguous?** Not
ambiguous once the dedup hash formula is inspected: **one publication from one source** (Section 4).
The name is misleading relative to the actual behavior.

**Q3. Where should intelligence outputs live?** See Section 10 in full. Short answer: for the
first slice, the already-existing `CapabilityResult.structured_output → EditorialTask.workflow`
JSON path (already used by Phase 8's two Capabilities) is sufficient and requires zero new
schema. Dedicated tables (`research_reports`, `intelligence_reports`) are spec'd in
`docs/08_Database_Schema_Data_Models.md` §12-13 but building them now would be premature —
**RECOMMENDATION**, not fact.

**Q4. Capability vs Workflow vs deterministic-service concerns?**
- Research, Intelligence: Capability concerns — identical shape to `ScoringCapability`/
  `QualityCapability`, one `NewsEvent` in, one structured result out, LLMGateway+PromptRepository
  only.
- Exact dedup: already a deterministic service (`services/deduplication.py`) — done.
- Popularity/Opportunity/Freshness/Authority/Raw-Score/Editorial-Priority: a **new deterministic
  service**, analogous in shape to `services/cost_estimator.py` (pure computation, no LLM, no
  Capability machinery needed) — explicitly mandated to be non-AI by `docs/05_Scoring_Ranking_Specification.md`
  §1-2's "Deterministic First" principle.
- Event clustering / source-diversity counting: fits **neither** the Capability shape (no
  per-event `execute()` boundary makes sense for a many-to-many grouping operation) **nor** the
  current Workflow shape (`EditorialTask` is one-event-scoped). This is the one candidate
  responsibility that does not have an obvious home in the existing architecture at all — see
  Section 9.

**Q5. Which operations require LLMs vs stay deterministic?** See the table in Section 8. Short
answer: dedup, source weighting, and the entire Raw Score computation are deterministic by
original design; summarization/fact-analysis/significance-judgment are inherently LLM;
similarity/novelty are a genuine hybrid candidate (deterministic pre-filter, LLM only for
surviving candidates) with no current infrastructure for either half.

**Q6. Is embedding/vector search required for the first Phase 9 slice?** No.
`integrations/llm_gateway/providers/openai_adapter.py:341-343` — the real adapter's `embed()`
raises `UnsupportedGatewayCapabilityError` unconditionally. No vector-DB dependency exists in
`pyproject.toml`. See Section 11 for the full analysis.

**Q7. Boundary between Research and Intelligence — one phase or separate?** They are **already
architecturally separate** (two sequential steps in the frozen `NEWS_ANALYSIS` workflow,
`workflows/definitions/news_analysis.py:20-21`) — this was decided in Phase 5, not something
Phase 9 gets to reopen. Whether to *implement* both in one phase or split into two phases is a
scope decision; see Section 15's recommendation.

**Q8. What data is required for reliable relevance/novelty/significance/confidence, and does it
exist?** Category classification (does not exist — always `UNKNOWN`), event clustering/source-diversity
(does not exist), source reliability (exists, schema-populated, unread), research
fact-confidence (spec'd, not built). None of the four target signals has its full data foundation
today; category and clustering are the two most load-bearing gaps.

**Q9. How should time windows affect novelty/clustering/relevance/significance?** `NewsEvent.published_at`
and `.collected_at` both exist and are indexed, so a time-windowed query is technically trivial —
but no service issues one today, and the actual window sizes (24h? per-category?) are a **product
question this Discovery does not answer** (Section 14).

**Q10. Deterministic vs model-driven, for testability/cost control?** Directly stated in
`docs/06_Functional_Specification.md` §3.3: Deterministic Layer owns "rules, limits, routing,
budget, storage"; AI Layer owns "analysis, generation, context understanding, creative creation."
Section 8 below applies this principle concretely to each Phase 9 candidate.

---

## 7. Candidate Phase 9 Responsibilities

| Candidate | Classification | Basis |
|---|---|---|
| Exact deduplication | **DONE** (not a Phase 9 responsibility) | `services/deduplication.py` already implements it |
| Semantic near-duplicate detection | **DEFER** | No infrastructure exists; deterministic (non-embedding) heuristics untried first; needs real-volume evidence to justify |
| Event clustering (cross-source grouping) | **OUT OF SCOPE for the first slice** | Structurally blocked by the one-event-per-task model (`schemas/workflow.py:17-27`); would require an architecture decision this document does not make |
| Relevance scoring | **SHOULD** (as part of Intelligence Capability output, per `docs/13_1` §6/`docs/08` §13) | Matches "Определение ценности" (value determination) already named as Intelligence's job |
| Novelty scoring | **DEFER** | Depends on clustering/time-window infrastructure that does not exist; a crude category+time-window heuristic could ship later without blocking the first slice |
| Significance/importance scoring | **SHOULD** (Intelligence Capability's `importance` field, `docs/08` §13) | Directly spec'd, no new infra required beyond the Capability itself |
| Source-confidence assessment | **SHOULD (read-only)**, **DEFER (computed/dynamic)** | `NewsSource.reliability_score` already exists and is populated at import time; using it as a Research/Intelligence input is a MUST-adjacent SHOULD; computing a *dynamic* authority score from history is DEFER (needs `source_metrics`, unimplemented) |
| Evidence extraction | **MUST** (core of Research Capability) | `docs/08` §12's `facts`/`sources`/`contradictions` shape names this directly |
| Research enrichment | **MUST** (this *is* the Research Capability) | `docs/13_1` §6 "Анализ фактов" |
| Summarization | **MUST** (implicit inside Research/Intelligence's `generate()` calls) | Already the established Capability shape — no separate summarization Capability needed |
| Ranking | **MUST**, but deterministic, and arguably a separate concern from Research/Intelligence | `docs/05` in full — explicitly pre-AI |
| Embeddings | **OUT OF SCOPE** | Section 11 |
| Vector search | **OUT OF SCOPE** | Section 11 |

---

## 8. Deterministic vs LLM Responsibilities

| Responsibility | Execution type | Reason | Cost/latency implication |
|---|---|---|---|
| Exact dedup | Deterministic | Already implemented; hash equality | Free, O(1) index lookup |
| Category classification | Deterministic (rule/keyword) first, LLM-assist later if needed | `docs/06` §3.3 principle; no evidence yet that keyword rules are insufficient | A rule pass over ~1000 items/day is negligible; an LLM pass would not be |
| Popularity / Freshness / Opportunity / Authority scores, Raw Score, Editorial Priority | Deterministic | `docs/05` §1-2 explicit "Deterministic First" mandate; pure arithmetic over existing/collectible fields | Zero LLM calls; this is the pre-filter that determines *which* events even reach an expensive Capability |
| Exact/near-duplicate pre-filter | Deterministic (hash / trigram / title-similarity) | No embedding infra exists; classic IR techniques are cheap and testable without a fake LLM | Avoids one Research call per near-duplicate item |
| Research (fact analysis, evidence, contradictions) | LLM Capability | Requires judgment/synthesis over unstructured text; matches the already-frozen `research` workflow step | One `generate()` call per surviving `NewsEvent`; the single most expensive step per item |
| Intelligence (importance, angle, audience fit, recommendation) | LLM Capability, consuming Research's output via existing step-chaining | Requires editorial judgment; already the second step in the frozen workflow | One more `generate()` call per surviving item; can be a smaller/cheaper model than Research if `docs/05`'s config-driven-budget principle is honored |
| Source weighting / Authority | Deterministic | `docs/05` §8: "коэффициент доверия" is config/history-driven, not LLM-judged | Zero LLM calls |
| Novelty (if pursued) | Hybrid — deterministic pre-check (time window + category + title overlap), LLM only for ambiguous survivors | No infra for either half exists yet; cheap heuristic should run first regardless of the final design | Determines whether Research/Intelligence even runs at all for a "we've seen this already" item |
| Significance / final scoring | LLM Capability (Intelligence's `importance`) feeding a deterministic final Raw Score | `docs/08` §13 spec's `importance: INTEGER` is LLM-derived input to a deterministic formula, not itself the formula | One value folded into an already-cheap deterministic sum |

---

## 9. Architectural Fit

**Capability Layer**: Research and Intelligence fit the existing `Capability` Protocol exactly as
`ScoringCapability`/`QualityCapability` already prove it — constructor accepts only `LLMGateway`
and `PromptRepository` (contract §4.2), `execute(CapabilityContext) -> CapabilityResult`, no
per-call mutable state, translated errors via the existing centralized `capabilities.gateway_call.call_generate()`
mechanism. **No Capability Layer redesign is implied by anything found in this Discovery.**
Intelligence consuming Research's output is the first real exercise of
`CapabilityContext.business.workflow_state.step_results`, which already exists in the frozen
Phase 6 schema — using it is not new architecture, just a first real user of an existing seam.

**Workflow Layer**: `NEWS_ANALYSIS`'s step order (`workflows/definitions/news_analysis.py`) is
already correct for Research → Intelligence and requires no change. What it does *not* accommodate
is anything cross-event (clustering, digesting) — that would need either a new workflow shape or a
component outside the Workflow Engine entirely (Section 6.2, Q4). This Discovery does not resolve
which.

**services/**: A new deterministic Ranking Engine belongs here, in the same shape as
`services/cost_estimator.py` — pure, config-driven computation, no LLM, no Capability machinery,
callable by (not called from within) the Collector or a future orchestration step, before any
`EditorialTask` is created.

**integrations/**: No new integration is implied unless embeddings are later adopted (Section 11)
or a new source type is added (out of scope — ingestion is already broad).

**Persistence**: See Section 10.

**No architecture redesign is proposed anywhere in this Discovery.** Every fit described above
uses an existing seam.

---

## 10. Persistence Analysis

**Does Phase 9 require new persisted state? RECOMMENDATION: not for the first slice; likely yes
eventually, but not proven yet.**

**Why existing models can plausibly suffice for a first slice**: `CapabilityResult.structured_output`
already flows into `EditorialTask.workflow`'s JSON `step_results` (Section 4) — this is the exact
mechanism Phase 8's two Capabilities already use, and nothing about Research/Intelligence's output
shape requires a different channel to *prove the mechanism works*. A `NewsEvent`'s
`EditorialTask.workflow` blob can hold `research`/`intelligence` step results the same way it
already (structurally) can hold `scoring`/`quality` results.

**Why the original spec's dedicated tables exist and what they'd actually buy**:
`docs/08_Database_Schema_Data_Models.md` §12 (`research_reports`: `facts, sources, contradictions,
confidence_score`), §13 (`intelligence_reports`: `importance, audience, angles, recommendation,
confidence`), and §9 (`source_metrics`: `subscribers, avg_views, avg_reactions, avg_comments,
engagement_rate`) are all **spec'd but unimplemented** (FACT — no matching model exists in
`database/models/`, confirmed by directory listing and grep). They would matter once there is a
real need to **query across tasks/events** (e.g., "show every research report touching topic X in
the last week," or "what's this source's rolling engagement rate") — a need `EditorialTask.workflow`'s
per-task JSON blob cannot serve, since it is not indexed or queryable across rows in any
structured way.

**Precedent for deferring this**: Phase 6's own Amendment B did exactly this for `AIExecution` —
the table exists, the mapping logic exists (`services/ai_execution_mapper.py`), but nothing
writes a row, explicitly "until a future phase reviews the schema against real provider
responses." Building `research_reports`/`intelligence_reports` now, before any real Research
output exists to validate the shape against, risks repeating the same premature-schema mistake
Amendment B was written to avoid.

**If new persistence is added, the concrete gaps to close are**: (1) the `AIExecution` write path
(currently mapping-only, per Amendment B) becomes actually necessary once Research/Intelligence
make real, cost-bearing LLM calls that need auditing — this is a **cost-tracking gap**, distinct
from the research/intelligence-report question; (2) `source_metrics` if the deterministic Ranking
Engine's Popularity/Authority scores need history, not just a static `reliability_score`.

**No migration is proposed by this document.**

---

## 11. Embedding / Vector Analysis

- **Is embedding needed now?** No. `OpenAIAdapter.embed()` raises `UnsupportedGatewayCapabilityError`
  unconditionally (`integrations/llm_gateway/providers/openai_adapter.py:341-343`) — there is no
  working embedding path anywhere in the system, real or fake-backed-by-real-infra.
- **Is vector search needed now?** No. No vector-DB dependency exists in `pyproject.toml`; no
  Qdrant/pgvector/pinecone reference exists anywhere in the codebase (grep-confirmed).
- **What problem would it solve?** Semantic near-duplicate/clustering detection at a quality
  level keyword/hash heuristics cannot reach, and (later) semantic search over accumulated
  research for a given topic (`docs/13_1` §5.2's `vector_memory` — explicitly listed as a
  **Future**, not-MVP table).
- **Can Phase 9 ship without it?** Yes. Deterministic pre-filters (title/URL similarity, exact
  hash, category + time-window overlap) can address the same problem class at the volumes stated
  (~1000 items/day) with zero new infrastructure, and Research/Intelligence Capabilities do not
  need embeddings to function — they need `LLMGateway.generate()`, already fully implemented.
- **What should trigger future adoption?** Concrete, measured evidence that deterministic
  near-duplicate/clustering heuristics under- or over-cluster at real production volume — the
  same "revisit once real evidence exists" discipline Phase 8 itself applied repeatedly
  (`docs/phase8_capability_contract.md` §19.2 Q1/Q3). Not "Qdrant exists as an option," which this
  Discovery was explicitly instructed not to treat as sufficient justification.

---

## 12. Scale / Cost Analysis

Evaluated at the stated target of **~1000 news items/day**.

**Likely LLM call volume if Research+Intelligence ran on every item, no deterministic pre-filter**:
up to 2 `generate()` calls per item × 1000 = **2000 LLM calls/day**, before any retry (Phase 8 M5's
correction-retry can add up to 1 more call per Capability on a schema mismatch, worst case ~4000/day).

**Avoidable LLM calls, if a deterministic Ranking Engine runs first** (per `docs/05`'s own
explicit design intent — this is not a novel optimization, it is what the original spec already
mandates): exact-dup and near-dup items never reach Research at all (already true for exact dups
today); items below a configured Editorial Priority threshold get "Минимальный"/no AI treatment
per `docs/05` §12's Editorial Budget table (Priority C = minimal, explicitly `❌` for Deep
Research). If even a conservative fraction of daily items are filtered this way before any LLM
call, the 2000/day figure drops substantially — but this document does not fabricate a specific
percentage, since no real ingestion-volume or priority-distribution data exists yet to base one on
(**OPEN QUESTION**, not answered here).

**Possible batching/filtering stages (RECOMMENDATION, not yet built)**:
1. Exact dedup (done).
2. Deterministic near-dup/title-similarity filter (not built).
3. Deterministic Popularity/Opportunity/Freshness scoring → Editorial Priority (not built) — this
   is the single highest-leverage missing piece for cost control, since it's what the Editorial
   Budget table (`docs/05` §12) uses to decide whether an item gets AI treatment **at all**.
4. Research (LLM, per surviving item).
5. Intelligence (LLM, per surviving item, consuming Research's output).

**Expensive operations**: any per-item LLM call is the expensive operation; Research is likely
more expensive than Intelligence per call (longer context, fact synthesis vs. shorter judgment
task), but this document does not have provider-pricing evidence in-repo to quantify further
(`services/pricing_catalog.py`'s current catalogue only prices the existing OpenAI GPT-5.6 family
used by Phase 7's own tests — real per-call cost depends on prompt length choices Phase 9 has not
made yet).

**No exact pricing is produced here**, per the task's own instruction, since no repository or
provider configuration currently makes a specific number meaningful for Research/Intelligence
prompts that do not exist yet.

---

## 13. Proposed Smallest Coherent Phase 9

**RECOMMENDATION** (not a decision — see Section 15 for the boundary question this depends on):

**IN SCOPE**:
- A deterministic Ranking Engine service (`services/`, new file(s)) computing Freshness and
  Opportunity scores from already-existing `NewsEvent` fields (`published_at`, `collected_at`),
  and Authority from the already-existing `NewsSource.reliability_score` — explicitly *not*
  Popularity (which needs `source_metrics`/engagement data this repo does not collect yet, see
  Section 10) or the full Raw Score formula, unless engagement data collection is proven trivial
  during Phase 9's own discovery-to-contract step.
- One `ResearchCapability` (`capabilities/research_capability.py`), registered as `"research"`,
  identical shape to `ScoringCapability`/`QualityCapability`, output persisted the same way (via
  `CapabilityResult.structured_output` into `EditorialTask.workflow`).
- One `IntelligenceCapability` (`capabilities/intelligence_capability.py`), registered as
  `"intelligence"`, consuming Research's output via the already-existing (but never-yet-exercised)
  `CapabilityContext.business.workflow_state.step_results` mechanism.
- Wiring both into `build_registry()` and proving `NEWS_ANALYSIS`'s first two steps actually run
  end to end (mirrors Phase 8 M4's boot-wiring proof pattern).

**OUT OF SCOPE**:
- Event clustering / cross-source grouping (Section 6.2 Q4 — no architectural home yet).
- Semantic near-duplicate detection, embeddings, vector search (Section 11).
- `engagement_analysis` as a real Capability (blocked on Amendment A's `AICapability` enum gap —
  a genuine, currently-undecided architecture question, not a Phase 9 implementation task).
- Digest generation (`WorkflowType.DAILY_DIGEST` — structurally blocked, Section 4).
- Dedicated `research_reports`/`intelligence_reports`/`source_metrics` tables (Section 10 —
  deferred until a real cross-task query need is proven).
- Popularity Score / full Raw Score / Editorial Priority auto-derivation (needs engagement-metrics
  collection this repo does not have; candidate for a follow-up slice once Ranking Engine's
  simpler components are proven).
- `CopywritingCapability`, `TrendCapability`, `CreativeCapability` — untouched, not this phase's
  concern.

**DEFERRED** (explicitly, not silently dropped):
- Popularity Score and engagement-metrics collection (needs `source_metrics` or equivalent).
- Novelty scoring (needs either clustering or a cheap time-window heuristic — the latter could be
  a small follow-up, not blocked on anything in this list).
- `AIExecution` real write path (needed once Research/Intelligence make real, cost-bearing calls
  that require audit).

---

## 14. Risks and Open Questions

**Architecture blockers**:
- None found that make Research+Intelligence-as-Capabilities impossible. Event clustering *is*
  currently blocked by the one-event-per-task model, which is why it is excluded from the proposed
  slice.

**Product questions** (this document does not answer these):
- What time window(s) should novelty/freshness use? (Q9 — no answer exists anywhere in the repo
  or docs.)
- Should `EditorialTask.priority` become auto-derived from a Raw Score, and if so, on what
  schedule (at Collector time? at task-creation time?) — this changes who calls the Ranking Engine
  and when.
- Is per-source engagement-metrics collection (subscriber counts, view counts) even feasible for
  every source type today (Telegram channel stats vs. RSS, which typically exposes none of this)?
  This directly gates whether Popularity Score is buildable at all in the near term.

**Data questions**:
- Is `NewsSource.reliability_score` actually populated for the sources currently imported (verify
  against `resources/sources.json`/the real source pack), or only for a subset? This Discovery did
  not verify real data, only schema/import-path capability.
- What does a representative `NewsEvent.content` actually look like across the 5 implemented
  adapters (length, language mix, noise) — this affects Research/Intelligence prompt design, which
  is Contract-phase work, not Discovery.

**Implementation decisions that can safely wait for the Contract phase**:
- Exact `ResearchCapability`/`IntelligenceCapability` output JSON Schema shape.
- Whether Research needs a second Gateway call (e.g. multiple facts) or stays single-call like
  Phase 8's two Capabilities.
- Whether Intelligence's `"engagement"` step name gets resolved now (Amendment A) or stays
  explicitly out of scope.

---

## 15. Recommended Phase 9 Boundary

**B. Phase 9 should be narrower than "Research/Intelligence as one layer," with the deterministic
Ranking Engine treated as a genuinely separate concern from the two LLM Capabilities — but built
in the same phase, not a prerequisite phase, because:**

- `docs/06_Functional_Specification.md`'s own top-level architecture diagram (§4) places "Ranking
  Engine" as a distinct box **before** "AI Intelligence Layer," and `docs/05`'s entire specification
  is written as a standalone, LLM-free system — this is strong, independent, pre-existing evidence
  that Ranking and Research/Intelligence were always meant to be architecturally separate
  concerns (different execution model: deterministic service vs. Capability), not one blob.
- However, splitting them into two *sequential phases* (Ranking Engine now, Research/Intelligence
  later) would delay proving the thing Phase 9's business goal actually cares about (real
  Newsroom intelligence value) for a phase whose main function is cost control — and Phase 8's own
  precedent (Golden Path + extension proof in one phase, M3+M7) suggests building a minimal
  version of both together, with the Ranking Engine gating which events even reach the LLM
  Capabilities, produces a more complete and more honestly cost-tested first Phase 9 slice than
  either piece alone.
- Option A (one merged "Research/Intelligence" layer with no ranking) risks reproducing the
  "one expensive LLM call for every trivial operation" anti-pattern the task explicitly warned
  against, since nothing would gate which of ~1000 daily items reach an LLM call.
- Option C (a wholly different phase before this one) does not fit either — there is no other
  gating architectural gap; the Capability Layer, Workflow Engine, and ingestion pipeline are all
  already sufficient to support the recommended slice.

---

## 16. Architecture Contract Inputs

A future `docs/phase9_research_intelligence_contract.md` would need to freeze, at minimum:

1. `ResearchCapability`'s and `IntelligenceCapability`'s exact `CapabilityDefinition` names,
   versions, and `output_schema` shapes (and whether they match or deliberately diverge from
   `docs/08` §12-13's original field lists).
2. Whether `IntelligenceCapability` reads `context.business.workflow_state.step_results["research"]`
   directly, and the exact key/shape contract between the two Capabilities' outputs.
3. The deterministic Ranking Engine's exact formula, weight-configuration mechanism, and where it
   lives (new `services/` module name, its inputs, and whether it runs inside or adjacent to
   `services/collector.py`).
4. Whether `EditorialTask.priority` becomes derived from the Ranking Engine's output, and if so,
   the exact call site and timing.
5. Explicit resolution of Amendment A's `"engagement"` alias — in scope, deferred, or formally
   dropped from the roster for this phase.
6. Whether any new persisted table (`research_reports`, `intelligence_reports`, `source_metrics`)
   is authorized for this phase, or explicitly deferred again (mirroring Amendment B's pattern).
7. Time-window constants for freshness/novelty, if novelty is included at all.
8. Confirmation (or explicit rejection) that no embedding/vector infrastructure is introduced in
   this phase.
9. Cost/budget gating: whether `AIExecution` gets a real write path in this phase, and how
   Research/Intelligence calls interact with `BudgetGuard` (via `FallbackPolicy`, per the existing
   Amendment C boundary — Capabilities still never hold `BudgetGuard` directly).

---

## 17. Final Discovery Verdict

**PHASE 9 NEEDS PRODUCT CLARIFICATION**

The architecture is ready — no blocker prevents building `ResearchCapability` and
`IntelligenceCapability` using the existing Capability Layer exactly as it stands, and the
deterministic Ranking Engine has a clear, evidence-backed home in `services/`. What is not yet
resolved are the **product questions in Section 14** (time windows, whether/how
`EditorialTask.priority` gets auto-derived, real per-source engagement-data feasibility) and the
**boundary judgment in Section 15**, which this document recommends but does not have the
authority to finalize. A Contract-design pass could reasonably proceed for the Research/Intelligence
Capability pair alone (the least product-ambiguous part of the proposed slice) while the Ranking
Engine's exact formula waits on the open product questions above — but presenting Phase 9 as fully
"ready for contract design" without flagging those open questions would understate real,
repository-evidenced ambiguity this Discovery found.
