# Phase 9 Architecture Contract — Research / Intelligence MVP

**Status: Final design specification. Single source of truth for Phase 9, once approved.**

This document converts `docs/phase9_final_decisions.md` — reconciled against
`docs/phase9_precontract_audit.md`, `docs/phase9_decision_resolution.md`, and
`docs/phase9_research_intelligence_discovery.md` — into binding form. Where an older Phase 9
document conflicts with `phase9_final_decisions.md`, this Contract follows the Final Decisions
document, per the stated priority of authority. Every load-bearing factual claim below (enum
values, field types, method signatures, existing behavior) was re-verified against the current
repository while drafting this Contract, not copied from a prior document without checking.

This Contract governs Phase 9 only. It does not amend, redefine, or reopen any Phase 5, 6, 7, or 8
Architecture Contract. Where this document references frozen behavior from those phases, it cites
the exact source rather than restating it as new authority.

No genuine contradiction between Final Decisions and frozen architecture or current code was found
while drafting this Contract. Three real, non-hypothetical limitations were found and are documented
plainly, not hidden: a narrow, bounded, self-healing concurrency window that remains even after the
DB-level claim guarantee below (§7.5); the fact that a legitimately in-flight claim must remain
younger than the configured staleness threshold or it becomes eligible for recovery-ownership
contention (§7.6, an honestly-disclosed operational constraint, not a silent gap); and the fact
that the Research→Intelligence `step_results` handoff is valid only within one uninterrupted
`WorkflowRunner.run()` call, not across a process crash/restart (§14.1).

**Revision note**: this Contract was revised twice. The first revision responded to
`docs/phase9_architecture_contract_audit.md`'s three MAJOR findings — crash/restart semantics
(§14.1, new), `TaskPriority`'s native-comparison hazard (§3), and the `NewsEvent.status` claim
mechanism (§7, substantially reworked to add a DB-level atomic guarantee). The second, narrower
revision responded to `docs/phase9_architecture_contract_reaudit.md`'s one new MAJOR finding: the
first revision's `PROCESSING`-with-no-active-task recovery-candidate mechanism had no staleness
qualifier and could race a legitimately in-flight, healthy claim. §7 gained a new §7.6 ("Stale-Claim
Recovery"), adding a required staleness gate and an atomic, migration-free
recovery-ownership-acquisition mechanism, verified empirically against the real repository database
before being frozen here. The Phase 9 boundary itself (Triage + Research + Intelligence,
`Capability`/`CapabilityExecutor`-level proof, no `NEWS_ANALYSIS` completion claim, no new
persistence) is unchanged by either revision.

---

## 0. Phase 9 Purpose

Phase 9 delivers the first real Research / Intelligence layer for Newsroom, on top of the
already-collected publication pipeline (Phase 5 ingestion, Phase 6 Capability framework, Phase 7
AI Integration Layer, Phase 8 Capability Layer). The intended logical boundary is:

```
publication already ingested (NewsEvent, status=NEW)
    ↓
deterministic Triage
    ↓
EditorialTask priority decision / task creation
    ↓
ResearchCapability
    ↓
IntelligenceCapability
```

**Phase 9 does not complete the full frozen `NEWS_ANALYSIS` workflow.** The real, frozen workflow
(`workflows/definitions/news_analysis.py`) remains:

```
research → intelligence → engagement_analysis → scoring
```

Phase 9 implements only the first two of these four Capability responsibilities. Its integration
proof stops at the `Capability`/`CapabilityExecutor` boundary, or uses synthetic test workflow
definitions where a `WorkflowRunner`-level proof is useful. **This Contract prohibits claiming that
the real `NEWS_ANALYSIS` `WorkflowType` reaches `TaskStatus.COMPLETED` in Phase 9** — see §13.

---

## 1. Architectural Principles

Normative, binding for all Phase 9 implementation.

- **P1.** Triage MUST be deterministic application logic. It MUST NOT be an LLM Capability, MUST
  NOT hold or call `LLMGateway`, and MUST NOT be registered in `CapabilityRegistry`.
- **P2.** Triage MUST NOT perform Final Editorial Ranking. It determines processing priority, not
  the editorial importance of a fully-analyzed story.
- **P3.** Triage MUST NOT require `ResearchCapability` or `IntelligenceCapability` output as an
  input. It runs strictly before either exists for a given `NewsEvent`.
- **P4.** `ResearchCapability` and `IntelligenceCapability` MUST be ordinary Phase 8 `Capability`
  implementations and MUST obey `docs/phase8_capability_contract.md` in full, without exception or
  fork — see §11.
- **P5.** No provider-specific logic MAY enter Triage, `ResearchCapability`, or
  `IntelligenceCapability`. Provider-specific code exists only inside
  `integrations/llm_gateway/providers/`, unchanged.
- **P6.** No component introduced by Phase 9 MAY import a provider SDK directly. All AI calls MUST
  cross the frozen `LLMGateway` boundary exactly as Phase 6/7 require.
- **P7.** Phase 9 MUST NOT introduce a second Workflow Engine, a parallel orchestration framework,
  or any mechanism that duplicates `WorkflowRunner`'s responsibility for executing a
  `WorkflowDefinition`'s step sequence.
- **P8.** Phase 9 MUST NOT introduce a new database model or a migration.
- **P9.** Phase 9 MUST NOT implement semantic event clustering, embeddings, vector search, a true
  cross-source novelty engine, an Opportunity Score (under any name), `EngagementAnalysisCapability`,
  or Final Editorial Ranking / full Scoring.
- **P10.** The frozen `NEWS_ANALYSIS` `WorkflowDefinition` (`workflows/definitions/news_analysis.py`),
  `WorkflowRunner`, and `WorkflowRegistry` semantics remain unchanged by Phase 9 — no edit, no new
  `WorkflowType` enum member, no step-`required` flag change.
- **P11.** Phase 9 MUST NOT register a placeholder/fake Capability under `"engagement_analysis"` or
  `"scoring"` merely to make the real `NEWS_ANALYSIS` workflow reach `COMPLETED`.
- **P12.** Every Phase 9 component MUST remain compatible with a future phase adding
  `EngagementAnalysisCapability` and a real Final Scoring implementation without requiring a
  breaking change to Triage's contract, `ResearchCapability`'s contract, or
  `IntelligenceCapability`'s contract.

---

## 2. Component Model

Exactly five new conceptual components. No additional abstraction is introduced without a named
consumer.

| Component | Kind |
|---|---|
| Freshness computation | Pure function |
| Triage | Pure function (composes Freshness + Authority) |
| Triage Orchestrator | `services/` application function + thin `scripts/` entry point |
| `ResearchCapability` | Phase 8 `Capability` implementation |
| `IntelligenceCapability` | Phase 8 `Capability` implementation |

### 2.1 Freshness

| | |
|---|---|
| Responsibility | Compute a recency signal for one `NewsEvent`, relative to an explicit reference timestamp. |
| Inputs | `published_at: datetime \| None`, `collected_at: datetime`, `reference_now: datetime` |
| Outputs | A recency value plus the tier/bucket it falls into, plus whether the `collected_at` fallback was used |
| Reads | Nothing beyond its inputs (no DB access) |
| Writes | Nothing |
| May depend on | Nothing beyond the Python standard library |
| Must NOT depend on | `LLMGateway`, any `services/` module, any ORM model, the system clock (`datetime.now()`/`.utcnow()` MUST NOT be called internally — §5) |
| Side effects | None |
| Failure behavior | MUST NOT raise for any well-typed input, including a `published_at` in the future (§5) |

### 2.2 Triage

| | |
|---|---|
| Responsibility | Recommend a `TaskPriority` for one `NewsEvent`, from Freshness and source Authority only. |
| Inputs | The `NewsEvent` fields Freshness needs, plus `NewsSource.reliability_score`, plus `reference_now` |
| Outputs | A `TaskPriority` recommendation plus an explanation value (§4, §15) |
| Reads | Nothing beyond its inputs (no DB access — the caller loads and passes data) |
| Writes | Nothing — never persists, never creates an `EditorialTask` |
| May depend on | Freshness (§2.1); read-only `NewsSource`/`NewsEvent` field values passed in by its caller |
| Must NOT depend on | `LLMGateway`, `PromptRepository`, `CapabilityRegistry`, `WorkflowRegistry`, `WorkflowRunner`, any embedding/vector infrastructure, `ResearchCapability`/`IntelligenceCapability` output |
| Side effects | None |
| Failure behavior | MUST NOT raise for any `NewsEvent`/`NewsSource` pair satisfying their existing schema constraints |

### 2.3 Triage Orchestrator

| | |
|---|---|
| Responsibility | Find eligible `NewsEvent` rows, atomically claim each one (§7.2, §7.5), call Triage, and create the corresponding `EditorialTask`. |
| Inputs | A DB session (existing `AsyncSession` pattern) |
| Outputs | None returned beyond an operational summary (mirrors `services/collector.py`'s `CollectionReport` shape) |
| Reads | `NewsEvent` rows with `status == EventStatus.NEW`, plus `PROCESSING` rows with no active `EditorialTask` **and a stale processing claim** (recovery candidates, §7.2, §7.6); their `NewsSource` rows |
| Writes | `NewsEvent.status` (atomic claim, first); `NewsEvent.updated_at` (atomic recovery-ownership refresh, stale candidates only, §7.6); `EditorialTask` (via the existing, unmodified `workflow_service.create_task()`, second/third) |
| May depend on | Triage (§2.2); `services.workflow_service.create_task()`, unmodified; `WorkflowType.NEWS_ANALYSIS`, unmodified |
| Must NOT depend on | `LLMGateway`, any provider adapter/SDK, `CapabilityRegistry`, `CapabilityExecutor`, `WorkflowRunner` internals, `IntelligenceCapability`/`ResearchCapability` |
| Side effects | Database writes (§7) |
| Failure behavior | §7.5, §18 |

### 2.4 `ResearchCapability` / `IntelligenceCapability`

Ordinary Phase 8 `Capability` implementations — see §8, §9, §11 for their full contracts. Not
re-tabulated here beyond noting they hold exactly `LLMGateway` and `PromptRepository`, per §4.2 of
the frozen Phase 8 contract, unchanged.

### 2.5 Canonical Ownership Table

| Component | Owns | Must NOT depend on |
|---|---|---|
| Freshness | Recency computation | DB, system clock, `services/`, `LLMGateway` |
| Triage | Priority recommendation | DB, `LLMGateway`, `CapabilityRegistry`, Research/Intelligence output |
| Triage Orchestrator | Selecting eligible events, atomically claiming `NewsEvent.status`, invoking Triage, calling `create_task()` | `LLMGateway`, provider SDKs, `CapabilityExecutor`, `WorkflowRunner` internals |
| `ResearchCapability` | Fact extraction from one `NewsEvent` | `BudgetGuard`, `CostTracker`, provider SDKs, `IntelligenceCapability`, another `Capability` |
| `IntelligenceCapability` | Editorial-significance judgment from Research's output | Same as above, plus: MUST NOT re-extract facts from raw content |

---

## 3. Deterministic Triage Contract

Triage MUST:
- Be a pure function: identical `(inputs, configuration, reference_now)` MUST produce identical
  output, every time.
- Execute with zero LLM calls, zero provider calls, zero web requests, zero embedding/vector
  operations.
- NOT perform semantic clustering.
- NOT perform Final Editorial Ranking.
- NOT compute anything named or described as an Opportunity Score, in whole or in part.

**Allowed input signals — the complete, closed list, per `docs/phase9_final_decisions.md` §5,
re-verified against the schema while drafting this Contract**:

| Signal | Verified field |
|---|---|
| Publication timestamp | `NewsEvent.published_at: Mapped[datetime \| None]` (`database/models/news_event.py:52-54`) |
| Collection timestamp | `NewsEvent.collected_at: Mapped[datetime]`, `server_default=func.now()`, never null (`database/models/news_event.py:55-57`) |
| Source reliability | `NewsSource.reliability_score: Mapped[float \| None] = mapped_column(Float, nullable=True)` (`database/models/news_source.py:33`) |

Triage MUST NOT use, in this phase: `NewsEvent.title`, `NewsEvent.content`, `NewsEvent.summary`
(always `None` today — no writer exists), `NewsEvent.category` (always `EventCategory.UNKNOWN`
today), `NewsSource.category`/`SourceDefinition.tags`, engagement metrics of any kind, cross-source
event counts, spread velocity, or any embedding/clustering-derived signal. None of these MAY be
added to the Triage formula without a Contract amendment (§19.1-equivalent process, mirroring
Phase 8's own).

**Output — decision, frozen**: Triage returns `TaskPriority` (`S`/`A`/`B`/`C`), the existing,
frozen enum already used by `EditorialTask.priority` (`database/models/editorial_task.py:13-19`,
values verified: `S="S"`, `A="A"`, `B="B"`, `C="C"`). Triage MUST NOT define a parallel priority
enum.

**Ordering — binding, frozen**: `TaskPriority` is declared as `class TaskPriority(str,
enum.Enum)` (`database/models/editorial_task.py:13`), which inherits Python `str`'s native
lexicographic comparison. **Empirically verified**: `TaskPriority.S < TaskPriority.A` evaluates to
`False`, and `sorted([TaskPriority.S, TaskPriority.A, TaskPriority.B, TaskPriority.C])` yields
`[A, B, C, S]` — alphabetical order. This coincidentally places `S` correctly (both alphabetically
last and editorially highest) but **inverts** the intended `A`/`B`/`C` relative order against
`docs/05_Scoring_Ranking_Specification.md` §11's canonical semantic order, which this Contract
freezes as:

```
S = highest urgency
A = next
B = next
C = lowest urgency
```

Triage's implementation, and any future code, **MUST NOT** rely on any of the following for a
business-priority decision:
- Python's native `<`/`>`/`<=`/`>=` comparison applied to `TaskPriority` values;
- `sorted()`/`min()`/`max()` applied over `TaskPriority` members;
- `TaskPriority`'s declaration order in `database/models/editorial_task.py`, which is not
  deliberately encoded as a ranking and MUST NOT be treated as one.

Any threshold mapping, comparison, or ranking logic involving `TaskPriority` MUST use an explicit,
deliberately-authored ordinal mapping (e.g., a dict assigning each of `S`/`A`/`B`/`C` an explicit
integer rank matching the canonical order above), never the enum's inherited string behavior.
`TaskPriority` itself remains exactly the existing, frozen four values — this rule constrains how
it is *compared*, not what it *is*; no parallel or replacement enum is introduced.

**Output shape — decision**: Triage returns a small, immutable value object containing the
`TaskPriority` recommendation plus a deterministic explanation (which signals contributed, and
their values) for observability (§15). This value object:
- MUST NOT be persisted as its own database row (§14) — it exists only in memory and in structured
  logs.
- MUST be JSON-serializable, for logging.
- MUST NOT introduce a new persistence requirement of any kind. Adding this value object is
  justified by observability need (§15) and by the explainability principle
  `docs/05_Scoring_Ranking_Specification.md` §2 states for the whole Ranking system; it is not
  over-engineering, since a bare `TaskPriority` alone cannot satisfy that principle.

---

## 4. No-Hard-Drop Invariant

**Binding rule**: Triage MUST NOT cause a publication to be permanently excluded from processing.
Every `NewsEvent` that reaches Triage (i.e., every `NewsEvent` that survived ingestion-level exact
deduplication and reached `status == EventStatus.NEW`) MUST result in exactly one `EditorialTask`
being created, at the priority Triage recommends — including `TaskPriority.C`, which
`docs/05_Scoring_Ranking_Specification.md` §12 defines as minimal processing, never zero
processing.

**Explicit distinction, binding**:
- **Ingestion rejection / deduplication** (`services/cleaning.py` dropping items with no usable
  text; `services/deduplication.py`'s exact-hash check) happens **before** a `NewsEvent` row
  exists at all, and is entirely outside Triage's authority. A `NewsEvent` that never gets created
  is not a Triage decision.
- **Triage prioritization** happens **after** a `NewsEvent` row exists, in `status == NEW`, and
  only ever affects which `TaskPriority` its `EditorialTask` receives — never whether one is
  created.

Triage MUST NOT introduce a third category ("accepted but not yet processed," "silently skipped")
between these two. If Triage runs on an eligible `NewsEvent`, an `EditorialTask` MUST result.

---

## 5. Freshness Contract

### 5.1 Architectural invariants (frozen, not product-tunable)

1. Freshness MUST accept its reference "now" as an **explicit parameter**. It MUST NOT call
   `datetime.now()`/`datetime.utcnow()`/any system-clock read internally. This is required for
   deterministic tests and replay.
2. **`published_at` present**: it is the freshness anchor.
3. **`published_at` missing (`None`)**: `collected_at` (never null) is used as the anchor instead,
   and the computed result MUST flag that the fallback was used.
4. **Future timestamps**: if the computed age (relative to `reference_now`) would be negative
   (clock skew, a malformed feed, a pre-dated post), the age MUST be clamped to zero — treated as
   maximally fresh. Freshness MUST NOT produce a negative age or raise an error for this case.
5. **Missing/invalid timestamps**: `published_at` being `None` is handled by rule 3.
   `collected_at` is a non-nullable, server-defaulted column — Freshness MAY assume it is always
   present and valid for any persisted `NewsEvent`.
6. **Timezone normalization**: both `published_at` and `collected_at` are stored as
   `DateTime(timezone=True)` (`database/models/news_event.py:52,55`). All comparisons MUST be
   timezone-aware. `reference_now` MUST be supplied as a timezone-aware `datetime`.
7. **Deterministic replay/testing**: "deterministic" means *reproducible given a fixed
   `reference_now`*, not *idempotent across time*. Recomputing Freshness for the same `NewsEvent`
   at a later `reference_now` legitimately yields a different result — this is the correct,
   intended behavior of a recency signal, not a violation of determinism.

### 5.2 Product configuration (explicitly not frozen here)

- The exact tier boundaries (candidate windows: 0–2h / 2–6h / 6–12h / 12–24h / 24–48h / 48h+) and
  their numeric weights.
- Whether the underlying computation is bucketed, continuous, or hybrid, provided rule 1-7 above
  hold regardless of the chosen shape.

---

## 6. Source Reliability

**Field, re-verified**: `NewsSource.reliability_score: Mapped[float | None] = mapped_column(Float,
nullable=True)` (`database/models/news_source.py:33`). Populated at import time from
`SourceImportItem.reliability_score` (`schemas/source_import.py:14`, range 0.0–1.0 when present)
or `SourceDefinition.reliability` (`schemas/source_definition.py:45`, `Field(ge=0.0, le=1.0)`) —
**static**, editor/config-curated, never computed or updated by any runtime process.

**Binding rules**:
1. Triage MAY read `NewsSource.reliability_score` exactly as it exists today — a static, per-source
   float.
2. Phase 9 MUST NOT compute a dynamic/historical authority score (e.g. tracking a source's
   prediction accuracy, publication frequency, or original-content ratio over time,
   per `docs/05` §8's fuller original concept). That remains explicitly deferred — it would
   require new persisted history this Contract does not authorize (§14).
3. Phase 9 MUST NOT derive authority from engagement data (none exists, §13 of
   `docs/phase9_research_intelligence_discovery.md`) or from clustering (does not exist).
4. **Missing value (`reliability_score IS NULL`)**: Triage MUST treat a null reliability score
   with a defined, deterministic default (a fixed neutral value, e.g. the midpoint of the
   configured range) — it MUST NOT raise, MUST NOT treat null as zero (which would silently
   penalize any source whose reliability was never configured), and MUST NOT skip the `NewsEvent`.
   The exact default value is product configuration (§16), not frozen here; that a defined,
   documented default MUST exist is frozen.

---

## 7. Triage Orchestration Ownership

### 7.1 Precedent

`scripts/run_collector.py` is the established, existing pattern for triggering periodic backend
work in this codebase: a thin (~20-line) script that wires logging and calls exactly one
`services/` function (`services.collector.run_collection_cycle()`), invoked as
`python -m scripts.run_collector`. The Triage Orchestrator MUST follow this exact, already-proven
shape — a new `services/` function plus a thin `scripts/` entry point — not a new kind of
component.

### 7.2 Responsibilities

**Eligible-event selection, including recovery**: the orchestrator's "find work" query MUST select
every `NewsEvent` with `status == EventStatus.NEW`, **and MUST additionally select** any
`NewsEvent` with `status == EventStatus.PROCESSING` that has no active
(`CREATED`/`RUNNING`) `EditorialTask` — using the same active-task definition
`_find_active_task()` already implements (`services/workflow_service.py:89-106`) — **AND whose
processing claim is stale**, per the explicit staleness test defined in §7.6. **`PROCESSING` +
no-active-task, by itself, is NOT sufficient to select an event as a recovery candidate** — see
§7.6 for why, and for the exact staleness condition. A `PROCESSING`+no-active-task event that is
not yet stale is a legitimate, healthy, in-flight claim and MUST be left alone by every other
orchestrator instance. The selection query MUST carry forward each stale candidate's observed
`updated_at` value — it is required as the guard condition for the ownership-acquisition step
below (§7.6).

For each selected `NewsEvent`, the orchestrator:
1. **Acquires the right to process the event**, via exactly one of two mutually-exclusive atomic
   mechanisms, depending on which selection bucket the event came from:
   - **If the event is `NEW`**: attempts to **atomically claim** it via a conditional update —
     `NewsEvent.status` transitions from `EventStatus.NEW` to `EventStatus.PROCESSING` **only if
     its current status is still `NEW`** (a single, atomic conditional `UPDATE ... WHERE status =
     'NEW'` statement, or an equivalent database-enforced conditional write — never a `SELECT`
     followed by a separate `UPDATE`). If this claim affects zero rows, another orchestrator
     instance already claimed it in the interim; this event MUST be skipped entirely, with no
     further action.
   - **If the event is a stale `PROCESSING`-with-no-active-task recovery candidate** (§7.6):
     attempts to **atomically acquire recovery ownership** via a conditional update guarded by the
     exact `updated_at` value observed during selection (§7.6's ownership-acquisition mechanism).
     If this update affects zero rows, another orchestrator instance already acquired ownership (or
     otherwise advanced the row) in the interim; this event MUST be skipped entirely, with no
     further action, exactly as for a lost `NEW` claim.

   Both mechanisms share the same shape — a single atomic conditional `UPDATE` plus an
   affected-row-count check, never a `SELECT` followed by a separate `UPDATE` — and identical
   handling for a lost race (silent skip, not an error).
2. Loads the (now-claimed, or now-ownership-acquired) event's `NewsSource` and calls Triage (§3)
   with the required fields plus a `reference_now`.
3. Calls the existing, **unmodified** `workflow_service.create_task(session,
   EditorialTaskCreate(event_id=..., workflow_type=WorkflowType.NEWS_ANALYSIS,
   priority=<Triage's recommendation>))`. See §7.5 for exact handling of every outcome of this
   call. `create_task()`'s own existing, internal `_find_active_task()` check (the very first thing
   it does, before any write) is the load-bearing re-check that no active task was created for this
   event between selection and this call — for both the `NEW`-claim path and the stale-recovery
   path alike. Phase 9 does not add a second, separate re-check, because this one, already-frozen
   check already closes the gap (§7.6).

`NewsEvent.status`'s `NEW`→`PROCESSING` transition reuses the existing, fully-defined `EventStatus`
enum (`database/models/news_event.py:26-33`), confirmed by grep to be currently unused beyond its
`NEW` default (`services/collector.py:159` is the only writer in the codebase today).
`NewsEvent.updated_at`'s recovery-ownership use (§7.6) reuses the existing, already-present column
(`database/models/news_event.py:65-67`) — **no new column, table, or migration is introduced for
"has this event been triaged," for recovery tracking, or for staleness detection — all three are
expressed entirely through the existing `EventStatus` enum, the existing `updated_at` column, and
the existing active-task check.**

The orchestrator MUST NOT:
- Become a second `WorkflowRunner`, or execute `NEWS_ANALYSIS`'s step sequence itself.
- Call any provider adapter or SDK directly.
- Contain `ResearchCapability`/`IntelligenceCapability` logic.
- Invent new persistent workflow state beyond reusing `EventStatus`, `updated_at`, and the existing
  active-task check.
- Require new scheduling infrastructure to exist before it can be built and tested (§7.4).
- Claim a `NewsEvent`, or acquire recovery ownership of one, via anything other than the atomic
  conditional update mechanisms in step 1 — a read-then-write (`SELECT` then separate `UPDATE`)
  implementation does not satisfy this Contract for either mechanism, even if it "usually works."
- Treat `PROCESSING` + no-active-task, by itself, as sufficient grounds for recovery — staleness
  (§7.6) MUST also hold.
- Introduce a heartbeat, lease, or distributed-lock subsystem to detect claim liveness — staleness
  is derived entirely from `updated_at` (§7.6).

### 7.3 Precise responsibility answers

- **Who calls Triage?** The orchestrator, and nothing else, and only after successfully claiming
  the `NewsEvent`, or, for a stale recovery candidate, successfully acquiring recovery ownership of
  it, per §7.2 step 1 / §7.6.
- **Who creates `EditorialTask`?** The orchestrator, via the existing, unmodified
  `workflow_service.create_task()`. Triage itself never does.
- **Who changes `NewsEvent.status`?** The orchestrator, exclusively — via the atomic conditional
  claim (§7.2 step 1) for the `NEW`→`PROCESSING` transition. No other component transitions
  `NewsEvent.status` (mirroring the existing rule that only `WorkflowRunner` changes
  `EditorialTask.status`, per `workflows/runner.py:95-96`'s own stated invariant — the orchestrator
  is the equivalent sole owner for `NewsEvent.status`).
- **Who advances `NewsEvent.updated_at` while an event is `PROCESSING`, and why?** The
  orchestrator, exclusively, in exactly two cases: implicitly, as a side effect of the initial claim
  (§7.2 step 1, via the existing `onupdate=func.now()` behavior — empirically confirmed to fire for
  a Core-level conditional `UPDATE`, §7.6); and explicitly, as the recovery-ownership-acquisition
  mechanism itself (§7.6). No other write to `updated_at` occurs while an event is `PROCESSING` —
  `create_task()` never touches `NewsEvent`.

### 7.4 Production scheduling

Building and testing the orchestrator function and its script entry point is **IN** Phase 9
scope. **Scheduling it** to run automatically (cron, systemd timer, task queue, or any other
trigger) is explicitly **OUT** of Phase 9 scope and MAY remain a later integration milestone — the
same status `scripts/run_collector.py` itself has today (nothing in this repository confirms it is
wired into any scheduler either).

### 7.5 Concurrency guarantee, ordering, and failure recovery

**Binding invariant, DB-level, not merely operational**: two concurrent orchestrator executions
MUST NOT both successfully claim the same `NewsEvent`. This is enforced by the atomic conditional
claim in §7.2 step 1 — a single `UPDATE ... WHERE status = 'NEW'` (or an equivalent
database-enforced conditional write) is atomic under Postgres's normal transactional semantics: of
two concurrent attempts against the same row, at most one affects a row and succeeds; the other
affects zero rows and MUST be treated as "already claimed by another instance." **This is a real,
database-enforced guarantee — it does not depend on deployment or scheduling discipline.** The
identical guarantee, via the identical mechanism shape (atomic conditional `UPDATE` plus
affected-row-count check), extends to stale-recovery ownership acquisition — see §7.6.

**Why this does not extend to full end-to-end atomicity — stated precisely, not hidden**:
`workflow_service.create_task()` takes the caller's `session` but commits internally
(`services/workflow_service.py:71`, `await session.commit()`), ending whatever transaction was open
at that point. The atomic claim (§7.2 step 1) and the subsequent `create_task()` call (§7.2 step 3)
therefore cannot be combined into one indivisible database transaction **without modifying
`create_task()` itself, which this Contract does not authorize.** Verified: a `SELECT ... FOR
UPDATE`-based row lock, held from the claim through to `create_task()`'s own commit, would also be
*released* by that same commit before the status is confirmed — so row-locking alone does not
close this gap either, for the same underlying reason. **Consequently, one residual, bounded
failure mode remains**: if the claim (step 1) succeeds but `create_task()` (step 3) subsequently
fails, the `NewsEvent` is left at `status == PROCESSING` with no corresponding active
`EditorialTask` — a **transiently false** `PROCESSING` state.

**This residual state is explicitly detected and recovered, not silently tolerated, and not
recovered prematurely either**: §7.2's eligible-event selection query treats this state
(`PROCESSING` + no active task) as a recovery candidate on a subsequent orchestrator pass **only
once it is stale** (§7.6) — never merely because no task exists yet, since a healthy, legitimately
in-flight claim also transiently has no active task. This staleness qualifier is the correction
this revision makes; see §7.6 for the full mechanism and its own concurrency guarantee.

**Precise required handling of every `create_task()` outcome** (identical for both the `NEW`-claim
path and the stale-recovery path — `create_task()` itself does not distinguish them):
1. **Success**: the claim/ownership-acquisition (already committed in step 1) and the new
   `EditorialTask` are both now correct and consistent. Nothing further is required.
2. **`DuplicateActiveTaskError`**: not a failure. `create_task()`'s own internal
   `_find_active_task()` check (§7.2 step 3) is what raises this — an active task already exists
   for this event by the time `create_task()` actually runs. Two structurally different, both-benign
   reasons this can happen: (a) a genuine retry of an event this same instance already handled; or
   (b) the narrow, honestly-disclosed residual case in §7.6 where a legitimately in-flight claim was
   "stolen" by a stale-recovery attempt because the original claim's own processing exceeded the
   staleness threshold before reaching `create_task()` — in which case whichever of the two callers
   reaches `create_task()` first wins, and the other correctly receives this error. Either way, the
   orchestrator MUST treat the event as successfully handled and move on — the event's `PROCESSING`
   status is now genuinely accurate, requiring no further action.
3. **Any other exception** (`NewsEventNotFoundError`, `UnknownWorkflowTypeError`, or an unexpected
   error): the event remains `PROCESSING` with no active task — the residual state described
   above — and is automatically eligible for recovery on a future orchestrator pass, once stale
   (§7.6). **The event MUST NOT be treated as successfully processed**, and this failure MUST be
   logged (§15).

**Explicit distinction, binding, per this Contract's own requirement**:
- **DB-level atomic guarantee**: no two concurrent orchestrator executions can both successfully
  claim the same `NEW` `NewsEvent` (§7.2 step 1), and no two concurrent orchestrator executions can
  both successfully acquire recovery ownership of the same stale `PROCESSING` `NewsEvent` (§7.6).
  Both hold unconditionally, regardless of deployment or scheduling discipline — together they are
  the *primary* safety mechanism against duplicate claims and duplicate recovery, not an assumption
  about how the orchestrator is invoked.
- **Not DB-level — bounded and self-healing instead**: the window between a successful claim (or
  ownership acquisition) and a successful `create_task()` call is not atomic, for the structural
  reason above. A failure in this window leaves a detectable, recoverable state (§7.2's recovery
  selection, gated by §7.6's staleness test), never a silent duplicate `EditorialTask` and never a
  silent, permanently-lost claim.
- **§7.4's production-scheduling deferral remains a relevant, secondary safeguard**, but it is no
  longer, and this Contract no longer treats it as, the *sole or primary* safety mechanism for
  either the claim or the recovery path — that role belongs to the two DB-level atomic mechanisms
  above. The one place this Contract still relies on an *operational*, not DB-enforced, assumption
  is the staleness threshold itself being calibrated longer than legitimate claim-to-`create_task()`
  latency — stated honestly as such in §7.6, not disguised as a stronger guarantee.

**No migration is introduced by this section.** The atomic claim is a query-time conditional
statement against the existing `NewsEvent.status` column; recovery-ownership acquisition (§7.6) is
a query-time conditional statement against the existing `NewsEvent.updated_at` column; the
active-task check reuses `create_task()`'s own existing, unmodified `_find_active_task()` logic.

### 7.6 Stale-Claim Recovery — eligibility, ownership, and time semantics

This section closes a gap `docs/phase9_architecture_contract_reaudit.md` found in this Contract's
first revision: `PROCESSING` + no-active-task, by itself, cannot distinguish a legitimately
in-flight claim (a healthy worker between §7.2 step 1 and step 3) from a genuinely abandoned one
(§7.5's residual `create_task()`-failure state). Both look identical at a single point in time. The
distinguishing signal is *time*: a legitimate claim reaches `create_task()` quickly; an abandoned
one does not.

**Repository facts, empirically verified against the real repository database, not assumed**:
- `NewsEvent.updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
  server_default=func.now(), onupdate=func.now(), nullable=False)`
  (`database/models/news_event.py:65-67`) — already exists, already non-nullable, already
  timezone-aware, requires no migration.
- **Verified empirically, against the real Postgres dev database** (a disposable script performing
  inserts, a Core-level conditional `UPDATE`, and cross-connection reads, cleaned up afterward — not
  reasoned about abstractly): a targeted, Core-level (`sqlalchemy.update(...)`) conditional `UPDATE`
  against `NewsEvent` — the exact same construct §7.2 step 1 already uses for the
  `NEW`→`PROCESSING` claim — **does** trigger `onupdate=func.now()` and advance `updated_at`, even
  though `updated_at` is never named in the `UPDATE`'s `.values(...)`. This is not
  ORM-flush-only behavior; it applies to a bare Core `update()` construct too.
- **Verified empirically**: an update made by one connection, uncommitted, is invisible to a
  concurrent connection's read of the same row (standard `READ COMMITTED` isolation) — a competing
  orchestrator cannot observe a claim or an ownership acquisition until it is actually committed.
- **Verified empirically**: a second conditional `UPDATE` attempted against a row whose guard
  condition (`status = 'NEW'`, or, for recovery, `updated_at = <a specific previously-observed
  value>`) no longer matches affects **zero rows**, reported as such via the result's row count —
  confirmed for both the existing `NEW`-claim guard and the new `updated_at`-equality guard this
  section introduces.
- **Verified**: the `updated_at` column has no `CHECK` constraint; a future timestamp (clock skew,
  or a manually forced value) is accepted by the database without error. This does not create a
  safety problem here — see the reference-time rules below.
- Confirmed by reading `services/workflow_service.py::create_task()` in full: it never writes to
  `NewsEvent` at all (only to `EditorialTask`). Nothing except this section's own mechanisms, and
  the original claim itself, ever advances a `PROCESSING` event's `updated_at`.

**Recovery eligibility invariant — binding, frozen**:

```
recovery candidate =
    NewsEvent.status == EventStatus.PROCESSING
    AND no active (CREATED/RUNNING) EditorialTask exists for it (_find_active_task())
    AND (reference_now - NewsEvent.updated_at) > staleness_threshold
```

`PROCESSING` + no-active-task **alone** MUST NOT be treated as sufficient. All three conditions are
required. An event with an active task is never a recovery candidate regardless of how old
`updated_at` is (states D/F, the partial-failure matrix below) — the active-task check takes
precedence over staleness entirely, and is evaluated first.

**Time semantics — frozen**:
1. **Claim age** is `reference_now - NewsEvent.updated_at`, using the same caller-supplied,
   timezone-aware `reference_now` parameter already required elsewhere in this Contract (§5.1 rule
   1) — no internal wall-clock read inside the selection logic, for the same testability/determinism
   reason Freshness requires it.
2. **Timezone**: `updated_at` is `DateTime(timezone=True)` (verified above); the comparison MUST be
   timezone-aware, exactly mirroring §5.1 rule 6's requirement for `published_at`/`collected_at`.
3. **Boundary**: an event is stale if and only if its age is **strictly greater than** the
   configured `staleness_threshold`. An event whose age exactly equals the threshold is treated as
   **not yet stale** (the safe, non-recovery direction) — deterministic, frozen.
4. **Future `updated_at` (clock skew, or the residue of a manually corrected row)**: yields a
   negative age, which is always less than a non-negative threshold, and is therefore always
   correctly classified as **not stale**, with no special-case clamping required — the ordinary
   arithmetic already produces the safe outcome.
5. **The staleness threshold itself is a positive, non-zero, configured duration** — see §22. Its
   *existence as a required, non-bypassable guard* is frozen; its *exact value* is product
   configuration.

**Atomic recovery-ownership acquisition — binding, frozen mechanism**:

Selecting a stale candidate is not itself sufficient to act on it — exactly as `NEW` selection alone
was never sufficient without the atomic claim (§7.2 step 1), a second, symmetric atomic step is
required here. When the orchestrator selects a stale recovery candidate, it MUST record the exact
`updated_at` value observed at selection time, then attempt a single atomic conditional `UPDATE`
guarded by that exact value — conceptually:

```
UPDATE ... WHERE id = <event_id>
            AND status = 'PROCESSING'
            AND updated_at = <the exact value observed during selection>
   (setting a value that causes updated_at to advance -- e.g. relying on the
    existing onupdate=func.now() behavior verified above, or setting it explicitly)
```

- If this affects **zero rows**: another orchestrator instance already acquired ownership of this
  candidate (or the row otherwise changed) since it was selected; this event MUST be skipped
  entirely for this pass, with no error — identical to the "lost the race, skip silently" handling
  already frozen for the `NEW`-claim path (§7.2 step 1).
- If this affects **exactly one row**: ownership is acquired. The orchestrator proceeds to §7.2
  steps 2–3 (Triage, then `create_task()`) for this event, exactly as for a freshly-claimed `NEW`
  event.

**Why this is sufficient — the TOCTOU re-check is structural, not a separate step**: the guard
condition (`status = 'PROCESSING' AND updated_at = <observed value>`) is re-evaluated by the
database atomically, as part of the single `UPDATE` statement, at the moment it executes — so a
successful acquisition *is* the proof that status was still `PROCESSING` and `updated_at` had not
moved since selection (nothing else — no competing recovery attempt, and no further activity by the
original claimant — touched this row in between). This closes exactly the TOCTOU pattern this
Contract has, elsewhere, needed a re-check for. **Empirically confirmed** (see above): a second
attempt using the same, now-superseded `updated_at` value correctly affects zero rows. The remaining
check — no active task — is re-verified by `create_task()`'s own existing, internal
`_find_active_task()` call in §7.2 step 3, which already runs before any write; Phase 9 does not add
a second, separate re-check for this, since the existing one is load-bearing and sufficient.

**At-most-one-winner guarantee — binding, frozen**: of any number of concurrent orchestrator
instances attempting recovery-ownership acquisition against the same stale candidate, **at most one
succeeds**; this is enforced by the same DB-level, unconditional guarantee the primary claim path
already relies on (a single-row conditional `UPDATE`'s atomicity), not by scheduling discipline.
This directly closes the finding in `docs/phase9_architecture_contract_reaudit.md`.

**Healthy-worker safety — proof, not assertion**: immediately after a claim or a prior ownership
acquisition, `updated_at` is fresh (`age ≈ 0`). As long as the actual duration between claim and
`create_task()` (steps 1→3: ordinary Triage plus one `create_task()` call — no I/O beyond loading
one `NewsSource` row, no LLM call, no network call, per §2.2/§2.3) remains below
`staleness_threshold`, the event cannot appear in any recovery-candidate selection during that
window, by construction of the eligibility invariant above. **The orchestrator SHOULD proceed from
a successful claim directly through Triage to `create_task()` with no unrelated intervening work or
artificial delay**, minimizing this window — this is already the existing §7.2 step ordering; this
section adds no new sequencing requirement, only this rationale for why the existing ordering
matters.

**Honest operational constraint, stated plainly, not hidden**: this guarantee depends on
`staleness_threshold` being configured comfortably longer than genuine claim-to-`create_task()`
latency ever plausibly is. If a legitimate claim's own processing takes longer than the threshold
(e.g., an unexpectedly slow Triage computation), a concurrent recovery attempt MAY successfully
acquire ownership and "steal" the event from the still-working original claimant. **This is not a
new, unbounded failure mode** — its consequence is exactly the already-disclosed, already-accepted
`create_task()`-level race (§7.5 point 2b): whichever of the two callers reaches `create_task()`
first succeeds, and the other receives `DuplicateActiveTaskError` and stands down. No silent
duplicate `EditorialTask` is possible from this scenario beyond what §7.5 already accepts for the
general case. Configuring the threshold with a wide safety margin over Triage/`create_task()`'s
actual observed latency is an operational responsibility, not something this Contract's mechanism
can enforce architecturally — stated here explicitly rather than left implicit.

**No new infrastructure introduced by this section**: no heartbeat, no lease table, no distributed
lock (Redis or otherwise), no new database column, no new database model, no migration. The entire
mechanism is one additional `AND` clause in the selection query (§7.2) and one additional atomic
conditional `UPDATE` (this section), against columns (`status`, `updated_at`) that already exist.

**Partial-failure matrix — every `PROCESSING`-adjacent state, deterministic**:

| State | Behavior |
|---|---|
| A. `NEW`, no task | Normal claim, §7.2 step 1 |
| B. Fresh `PROCESSING`, no task | Excluded from recovery selection entirely (age ≤ threshold) — MUST NOT be recovered |
| C. Stale `PROCESSING`, no task | MAY become a recovery candidate; subject to the ownership-acquisition race below |
| D. `PROCESSING`, active task exists | Excluded from recovery selection entirely, regardless of `updated_at` age — the active-task check takes precedence (§7.2's existing `_find_active_task()` filter) |
| E. Stale `PROCESSING`, no task, two+ concurrent recovery attempts | At most one acquires ownership (proven above); the rest observe zero rows affected and skip silently |
| F. Task created successfully, a later orchestration step (`WorkflowRunner`) has not finished | = state D — an active (`CREATED`/`RUNNING`) task exists, so the event is excluded from recovery regardless of `updated_at`'s age, however old it grows |
| G. Claim succeeds, `create_task()` fails | Transient state B immediately after the failure (fresh, not yet a candidate); becomes state C once `reference_now - updated_at` exceeds the threshold on a later pass |

---

## 8. `ResearchCapability` Contract

| | |
|---|---|
| **Capability name** | `"research"` (matches `workflows/definitions/news_analysis.py`'s existing step name and `capabilities/capability_mapping.py`'s existing `"research": AICapability.RESEARCH` entry — zero change needed to that mapping file) |
| **Construction** | `__init__(self, gateway: LLMGateway, prompt_repository: PromptRepository)` — exactly the Phase 8 §4.2 shape, no additional dependency |
| **Input** | `CapabilityContext` for one `NewsEvent`: title, category (always `UNKNOWN` today), content, language. No data beyond what `CapabilityContext` already carries. |
| **Output** | Structured extraction of what the given text actually says: organized factual claims, and a confidence signal on the extraction itself (not on external verification). Exact field names are implementation-plan detail, not frozen here; the conceptual shape — facts, confidence, optionally flagged gaps/ambiguity — is frozen. |
| **Responsibility** | Turn one `NewsEvent`'s unstructured text into structured, reviewable factual content. |
| **MUST NOT** | Verify facts against any external source; browse the web; invoke a tool or an agent loop of any kind; judge importance, audience fit, or editorial angle (Intelligence's responsibility, §9); call another `Capability` (forbidden by Phase 6 P4, unchanged, cited in `docs/phase8_capability_contract.md` §2); hold per-call mutable state (Phase 6 §3.2, unchanged). |

**Binding scope clarification**: no external research tool exists anywhere in this architecture
(Phase 8's contract explicitly, permanently defers tool integration in this delivery — Discovery
§5 already confirmed no partial implementation exists). `ResearchCapability` MUST operate solely
from the `CapabilityContext` it receives. It MUST NOT be named or documented as performing
external fact-checking or verification it structurally cannot perform. "Research" in this phase
means **structured fact extraction**, precisely.

---

## 9. `IntelligenceCapability` Contract

| | |
|---|---|
| **Capability name** | `"intelligence"` (matches the existing workflow step name and the existing `"intelligence": AICapability.INTELLIGENCE` mapping entry — zero change needed) |
| **Construction** | Identical shape to `ResearchCapability`: `__init__(self, gateway: LLMGateway, prompt_repository: PromptRepository)`. |
| **Input** | `CapabilityContext` for the same `NewsEvent`, **plus** `context.business.workflow_state.step_results["research"]` — see §9.1. |
| **Output** | Editorial-significance judgment: importance/significance, an editorial angle, audience relevance, and a recommendation. Exact field names are implementation-plan detail; the conceptual shape is frozen, inspired by (not required to literally match) `docs/08_Database_Schema_Data_Models.md` §13. |
| **Responsibility** | Given Research's already-extracted facts, assess what they mean editorially and why they matter. |
| **MUST NOT** | Re-extract or re-summarize facts from raw `NewsEvent.content` (it consumes Research's structured output, not the raw text a second time); compute a final, cross-event-comparable ranking score (Final Ranking/Scoring's job, explicitly deferred, §13); decide AI processing priority or budget (Triage's job, upstream and unrelated — P3); invoke a tool or agent loop; call another `Capability` directly. |

### 9.1 How Intelligence consumes Research's output — the mechanism, verified, not invented

**Binding rule**: `IntelligenceCapability` MUST NOT hold a direct reference to
`ResearchCapability`, import it, or call it. Direct Capability-to-Capability coupling is forbidden
by the frozen Phase 6 contract (P4, restated in `docs/phase8_capability_contract.md` §2's
forbidden-edges table: *"`Capability` → another `Capability` — FORBIDDEN"*).

Instead, `IntelligenceCapability` MUST read Research's output through the **existing, already-frozen
Phase 6 mechanism**: `CapabilityContext.business.workflow_state.step_results: dict[str,
dict[str, Any]]` (`schemas/capability.py`'s `WorkflowExecutionStateSnapshot`), populated by
`CapabilityExecutor._build_context()` from the previously-completed step results of the *same*
`WorkflowExecutionState` — regardless of which `WorkflowDefinition` (real or synthetic, §13) is
driving execution. This mechanism already exists, is already frozen, and has simply never had a
real consumer before Phase 9. Phase 9 does not invent it; it is the first real user of it.

**This mechanism's scope is bounded — see §14.1.** It is valid within one uninterrupted
`WorkflowRunner.run()` execution context only; it is not a durable, crash-safe, cross-process
handoff.

---

## 10. Research vs Intelligence Call Semantics

**Frozen**: Research and Intelligence are two distinct `Capability` responsibilities. Intelligence
depends on Research's output via §9.1's mechanism. Neither may be merged into the other, and
neither may be registered under both `"research"` and `"intelligence"` names simultaneously as a
cost-saving shortcut — doing so would produce two `WorkflowStepResult`s (and, once `AIExecution`
is ever wired, two implied audit records) for one actual LLM call, a misleading double-count this
Contract forbids.

**Not frozen**: the Contract does not mandate that every accepted `NewsEvent` MUST always incur
exactly two sequential Gateway calls, unconditionally, forever. It is legitimate for a future
orchestration- or Triage-level decision to skip Research for some subset of accepted items, or for
a future optimization to reuse structured Research output across multiple downstream consumers —
**provided each Capability's own observable contract (§8, §9) is unchanged when it does run.**
Phase 9 itself does not implement any such optimization (no evidence justifies it yet); this
Contract only avoids forbidding it by accident.

---

## 11. Capability Execution / Error Model

`ResearchCapability` and `IntelligenceCapability` MUST obey `docs/phase8_capability_contract.md`
in full, without a fork or a variant rule, specifically including — cited, not restated:

- The `Capability` Protocol and `CapabilityDefinition`/`CapabilityContext`/`CapabilityResult`
  shapes (`docs/phase8_capability_contract.md` §4, §5).
- The centralized Gateway-call mechanism (`capabilities/gateway_call.py`'s `call_generate()`) for
  `CapabilityCall` bookkeeping, observability-metadata stamping, and `GatewayError`→
  `CapabilityError` translation (§6.4-§6.8, §11 — unchanged, reused exactly as `ScoringCapability`/
  `QualityCapability` already do).
- `PromptRepository.resolve()` for all prompt content — no embedded prompt strings (§7).
- The §9.1 structured-output validation floor before any `SUCCESS` result.
- The §10 correction-retry rule, if either Capability chooses to implement it (optional, per §10.2
  — not mandatory, `ScoringCapability` is the only Phase 8 Capability that implements it and
  `QualityCapability` correctly does not).
- Full observability-metadata compliance (§12 — `trace_id`/`capability_execution_id`/`request_id`,
  Phase 7 §16.1's formula, unchanged).
- No per-call mutable state on the singleton Capability instance (§3.2).

**Phase 9 specializes content and prompts, never execution mechanics.** No part of this Contract
introduces a new Capability execution rule, a new retry rule, or a new error-classification rule.

---

## 12. Registration

`ResearchCapability` and `IntelligenceCapability` enter `CapabilityRegistry` via `build_registry()`
(`capabilities/registry.py`), following exactly the pattern Phase 8 M7 already proved: one new
import, one new `registry.register(DEFINITION, Capability(gateway, prompt_repository))` line per
Capability, added to `build_registry()`'s existing body. No other line in `capabilities/registry.py`
changes.

Binding constraints, unchanged from Phase 8's own precedent:
- No registry redesign, no runtime discovery, no plugin framework.
- No change to `ProviderRegistry` or `ModelRegistry` (Phase 7, frozen, untouched).
- `budget_guard`/`tool_registry` continue to be accepted by `build_registry()` and passed to
  neither new Capability, unchanged (Phase 8 contract §5.3, §18 rule 19).

**Explicit statement, binding**: registering `ResearchCapability` and `IntelligenceCapability`
MUST NOT be described, documented, or tested as making `NEWS_ANALYSIS` "now executable" or
"complete." See §13.

---

## 13. Workflow Compatibility

**Frozen fact, re-verified**: `workflows/definitions/news_analysis.py`'s four
`WorkflowStepDefinition`s (`research`, `intelligence`, `engagement_analysis`, `scoring`) each use
`required: bool = True` (the schema default, `schemas/workflow.py:52`; no step in this file passes
an override). Mechanically, per `workflows/runner.py:163-172`, a required step's failure ends the
task as `TaskStatus.FAILED` — there is no partial-completion state.

**Binding consequence**: after Phase 9, `research` and `intelligence` are registered and
independently executable, but `engagement_analysis` remains unregistered.
**`workflow_service.create_task(workflow_type=WorkflowType.NEWS_ANALYSIS, ...)` followed by
`WorkflowRunner.run()` will still end that task as `FAILED`, at the `engagement_analysis` step,
after Phase 9 exactly as it does today** (only the failing step number changes, from the first
step to the third). This is not a regression Phase 9 introduces; it is a pre-existing condition
Phase 9 does not resolve.

**The existing `ScoringCapability` (Phase 8) MUST NOT be assumed to satisfy `NEWS_ANALYSIS`'s
final `scoring` step responsibility.** It is a minimal Golden-Path proof of mechanism
(`docs/phase8_capability_planning.md`'s own stated M3 scope), does not consume
`research`/`intelligence`/`engagement_analysis` step output, and does not match
`docs/08_Database_Schema_Data_Models.md` §14's originally-specified Scoring Model shape. A future
phase must explicitly prove/implement Final Scoring before this claim can change.

**Binding rule**: the real `NEWS_ANALYSIS` `WorkflowType`, run through `WorkflowRunner`, MUST NOT
be used as Phase 9's completion proof, for any test or documentation purpose.

**Allowed Phase 9 integration proof** (§16 testing detail expands this):
- Direct `Capability` unit tests (fakes only).
- `CapabilityRegistry`/`build_registry()` reachability tests.
- `CapabilityExecutor`-level integration tests.
- A **synthetic, test-local `WorkflowDefinition`** (e.g. two steps named `"research"`,
  `"intelligence"` only, never registered in the real `WorkflowRegistry`), run through the real,
  unmodified `WorkflowRunner`, to prove step-chaining (§9.1) works for real — mirroring exactly
  how every Phase 8 end-to-end test already builds its own synthetic `WorkflowDefinition` rather
  than importing `workflows.definitions.*` (confirmed: zero existing tests do the latter).
- A real `RoutingGateway` + `FakeProviderAdapter` proof of both Capabilities together, against the
  same synthetic definition, mirroring `tests/test_capability_boot_wiring_e2e.py`/
  `tests/test_phase8_cross_cutting_regression.py`.

All of the above exercise a single, uninterrupted `run()` call — the case this Contract requires
to work. They do not, and are not required to, prove crash-safety across a process restart
mid-workflow — see §14.1.

**The frozen `NEWS_ANALYSIS` definition MUST NOT be weakened (no `required=False`), extended, or
duplicated under a new `WorkflowType` to make any test pass.**

---

## 14. Persistence Contract

Phase 9 introduces **NO new database model, NO migration, NO vector store schema, NO event-cluster
table, NO intelligence-graph table.**

| Result | Home | Mechanism |
|---|---|---|
| Triage recommendation (`TaskPriority`) | `EditorialTask.priority` | Existing column, existing `create_task()` parameter — unchanged |
| Triage explanation | Structured log only | Not a persisted row — see §3, §15 |
| "Has this `NewsEvent` been triaged" | `NewsEvent.status` | Existing `EventStatus` enum, `NEW`→`PROCESSING`, previously unused — reused, not extended |
| `ResearchCapability` `CapabilityResult` | `EditorialTask.workflow` (JSON) `step_results` | Existing Phase 6 mechanism, first real production use |
| `IntelligenceCapability` `CapabilityResult` | Same as above | Same |
| Per-call cost/audit record (`AIExecution`) | **Not written** | Amendment B's mapping-only state (`services/ai_execution_mapper.py`) is unchanged by Phase 9 — not required, exactly as it was not required for Phase 8 |
| Cross-task/cross-event durable domain knowledge | **Not built** | Would be `research_reports`/`intelligence_reports`/a persistent intelligence graph — none is authorized by this Contract |

**Distinction, binding**: a `CapabilityResult` is a transient, in-memory runtime object; its
`structured_output` is persisted only as part of `EditorialTask.workflow`'s JSON snapshot, exactly
as `ScoringCapability`/`QualityCapability`'s output already is. Phase 9 does not require permanent,
independently-queryable persistence of every intermediate analytical field, since no existing
architecture does either.

### 14.1 Crash / Restart Limitation (binding disclosure)

**Verified, not hypothetical**: `workflows/runner.py` commits exactly three times in the whole
file — before any step of a `run()` call executes (`workflows/runner.py:123`), once at the end of
`_execute_steps` on full success (`workflows/runner.py:194-195`), and once inside `_fail()` on a
step failure (`workflows/runner.py:284-285`). **There is no commit between individual steps.**
Within one `_execute_steps` loop, `step_results` (`workflows/runner.py:156`) accumulates only in a
local, in-memory Python list until the loop finishes or fails.

**Binding consequences, frozen**:
1. Phase 9 does NOT change `WorkflowRunner`'s persistence semantics. This is a pre-existing Phase 5
   characteristic, unchanged and unchangeable by this Contract (P10).
2. The Research→Intelligence handoff through `step_results` (§9.1) is valid **only within the same,
   uninterrupted `WorkflowRunner.run()` execution context**. It is not a durable, cross-process
   handoff mechanism.
3. Phase 9 MUST NOT claim, document, or test that intermediate `ResearchCapability` output is
   durably recoverable after a process crash or restart occurring between the `research` and
   `intelligence` steps of one workflow run. If such a crash occurs, Research's output is lost; the
   owning `EditorialTask` remains `TaskStatus.RUNNING` (the last committed status) and cannot be
   resumed by a further `WorkflowRunner.run()` call (it raises `TaskAlreadyRunningError`) without a
   manual/out-of-band intervention this Contract does not define.
4. Phase 9 introduces no new per-step persistence model, checkpoint table, or migration to address
   this — P8 is unaffected.
5. `CapabilityExecutor`-level and synthetic-workflow integration proofs (§13, §16) remain
   sufficient for Phase 9's completion — they exercise the uninterrupted-execution case exactly,
   which is the case this Contract actually requires to work.
6. Full crash-safe, multi-step `NEWS_ANALYSIS` recovery (a durable, per-step checkpoint mechanism
   surviving a process restart mid-workflow) is explicitly DEFERRED — out of Phase 9 scope
   entirely, not merely unimplemented.
7. If a future phase requires durable Research output between steps (e.g. genuine crash recovery,
   or asynchronous/multi-process step execution), it MUST address this as a distinct
   **workflow-persistence** concern — extending or revising `WorkflowRunner`'s own commit
   discipline — rather than silently reinterpreting `ResearchCapability`'s or
   `IntelligenceCapability`'s Capability-level semantics (§8, §9) to compensate for it.

---

## 15. Observability

Binding minimums:

- Triage's explanation (§3) MUST be logged in structured form at the point a `TaskPriority` is
  recommended, including at minimum: the `NewsEvent` id, the `NewsSource` id, the Freshness input
  values and resulting tier, the Authority input value (or the default used per §6 rule 4), the
  resulting `TaskPriority`, and the `reference_now` used.
- A successful stale-recovery ownership acquisition (§7.6) MUST be logged, including the `NewsEvent`
  id and its observed claim age at the time of acquisition — the operational signal that the
  staleness-threshold configuration (§22) is actually being exercised, not merely theoretical.
- `ResearchCapability`/`IntelligenceCapability` MUST use the existing Phase 7/8 observability chain
  unchanged (`trace_id`/`capability_execution_id`/`request_id`, per §12 of this Contract's §11
  cross-reference) — no new identifier scheme, no Phase 9-specific logging framework.
- No prompt content, no provider credential, and no other sensitive value MAY be logged in a form
  that violates existing logging conventions already established in Phase 7/8 (e.g. `ProviderCredential`'s
  existing redaction discipline, unchanged).

This Contract does not introduce a new observability framework, dashboard, or metrics pipeline.

---

## 16. Testing Requirements

**Triage / Freshness**:
- Deterministic given a fixed `reference_now`; no network, no LLM, no DB access in the unit tier.
- Edge cases: `published_at` present, `published_at` null (`collected_at` fallback, flagged),
  future `published_at` (clamped, not negative), `reliability_score` null (default applied, not
  skipped).
- Every reachable `TaskPriority` outcome under the eventual configured policy MUST have at least
  one test.
- A test MUST prove the no-hard-drop invariant (§4): Triage never returns "no task."
- A test MUST prove the canonical business priority order (`S > A > B > C`, §3) using the explicit
  ordinal mapping directly — never by asserting on `sorted()`/`<`/`>` applied to `TaskPriority`
  members, which would only prove Python's inherited alphabetical order, not the business order.

**Triage Orchestrator**:
- The atomic claim (§7.2 step 1, §7.5) MUST be tested to prove that a `NewsEvent` already claimed
  (`status != NEW`) is not re-claimed, and that a claim's affected-row-count is checked, not
  assumed.
- The `create_task()` outcome handling (§7.5: success, `DuplicateActiveTaskError`, any other
  exception) MUST be tested for all three cases.
- **Stale-claim recovery (§7.6)** MUST be tested to prove, at minimum:
  1. A freshly-claimed `PROCESSING` event with no active task (age ≤ threshold) is NOT selected as
     a recovery candidate.
  2. A `PROCESSING` event with no active task whose age exceeds the threshold IS selected and its
     ownership successfully acquired.
  3. A `PROCESSING` event with an active task is never selected as a recovery candidate, regardless
     of its `updated_at` age.
  4. Two concurrent recovery-ownership-acquisition attempts against the same stale candidate result
     in exactly one success (affected-row-count 1) and the rest observing zero rows affected — no
     duplicate `EditorialTask` results.
  5. A successful ownership acquisition is immediately followed by `create_task()`'s own existing
     `_find_active_task()` check correctly preventing duplicate task creation (the TOCTOU re-check,
     §7.6) — this does not need its own separate mechanism-level test, since it exercises the same,
     already-tested `create_task()` code path.
  6. Boundary behavior at exactly the threshold is deterministic (not-yet-stale, §7.6 rule 3).
  7. A future/clock-skewed `updated_at` is deterministically treated as not stale (§7.6 rule 4).
  8. No test in this suite requires a migration, a new table, or new infrastructure to run.
- Uses the real `db_session` fixture pattern already established in Phase 8's own integration
  tests (`tests/test_capability_boot_wiring_e2e.py`) — this is integration-tier, not unit-tier,
  consistent with `docs/phase8_capability_contract.md` §15.6.

**`ResearchCapability`/`IntelligenceCapability`** (mirroring `docs/phase8_capability_contract.md`
§15's rules exactly, unchanged):
- Happy path against `FakeLLMGateway` + a fake `PromptRepository`.
- Structured-output validation floor enforcement.
- `GatewayError`→`CapabilityError` translation, using the existing centralized mechanism — no
  Phase-9-specific translation logic to test, since none is introduced.
- Repeated-invocation independence (no per-call state).
- If retry is implemented for either (optional, §11): retry-success and retry-exhaustion paths.

**Integration**:
- Both Capabilities reachable via `CapabilityRegistry`/`build_registry()`, coexisting correctly
  alongside `ScoringCapability`/`QualityCapability`.
- Step-chaining proof (§9.1, §13) via a synthetic `WorkflowDefinition`, within one uninterrupted
  `run()` call (§14.1) — no test simulates or claims to prove crash/restart recovery.
- **No test MAY claim or assert that the real `NEWS_ANALYSIS` `WorkflowType` reaches
  `TaskStatus.COMPLETED`.**

**Standard suite discipline, unchanged from Phase 7/8**: no real network call, no real provider
call, in the unit tier. `Capability`-level tests MUST NOT touch a real database or real Redis.

---

## 17. Forbidden Dependency Edges

Canonical table, to be mechanically encoded into `scripts/validate_architecture.py` by a future
implementation milestone (mirroring Phase 8 M0's precedent) — not implemented by this Contract
itself.

| Component | MUST NOT import/depend on |
|---|---|
| Freshness | `services.*`, any DB session, `LLMGateway`, the system clock |
| Triage | `LLMGateway`, provider adapters/SDKs, `Capability` implementations, `CapabilityRegistry`, `WorkflowRunner`/`WorkflowRegistry` internals, embeddings/vector infrastructure |
| Triage Orchestrator | Provider adapters/SDKs, `integrations.llm_gateway.*` internals, `CapabilityExecutor`, `CapabilityRegistry`, any second Workflow Engine abstraction, `ResearchCapability`/`IntelligenceCapability` directly |
| `ResearchCapability` | Provider SDKs, `database.session`/`sqlalchemy`, `services.budget_guard`, `services.cost_tracker`, `integrations.llm_gateway.{cache,rate_limit,fallback,routing,providers}`, `workflows.*`, **`IntelligenceCapability`** — all per the existing, mechanically-enforced Phase 8 M0 `capability-isolation` rule (`scripts/validate_architecture.py`), which already applies to any new file under `capabilities/` without modification |
| `IntelligenceCapability` | Same list, plus **`ResearchCapability`** directly (§9.1 — must go through `step_results`, never a direct import) |

Capabilities MUST NOT depend on one another directly, in either direction — restates Phase 6 P4,
already mechanically enforced by the existing validator for any new file placed under
`capabilities/`.

---

## 18. Failure Semantics

| Failure | Required behavior |
|---|---|
| `NewsEvent` claim failure (affected-row-count is 0) | Not an error — §7.2 step 1: another instance already claimed it; the orchestrator MUST skip the event silently (no error logged, this is expected under concurrency) |
| Recovery-ownership acquisition failure (affected-row-count is 0) | Not an error — §7.6: another instance already acquired ownership of this stale candidate (or the row otherwise changed) in the interim; the orchestrator MUST skip the event silently, identically to a lost `NEW` claim |
| Source/event loading failure, Triage calculation failure, or `EditorialTask` creation failure — **any** failure occurring after a successful claim/ownership-acquisition (§7.2 steps 2-3) | The event is left `PROCESSING` with no active task — the same residual, bounded state §7.5 describes for a `create_task()` failure specifically. The failure MUST be logged; other events in the same batch are unaffected (mirrors `services/collector.py`'s existing per-source isolation discipline, `_process_source`'s try/except). The event is automatically eligible for recovery on a future orchestrator pass once stale (§7.2's selection query, gated by §7.6) — never silently treated as processed. Triage itself MUST NOT raise for any well-formed input (§2.1, §2.2); if it somehow does, this is the failure path that applies, not a distinct one. |
| `ResearchCapability` failure | Handled entirely by existing Phase 8 `CapabilityExecutor`/`WorkflowRunner` semantics — a `RetryableCapabilityError` retries per `WorkflowStepDefinition.max_attempts`; a `PermanentCapabilityError`/`ValidationCapabilityError`/`CapabilityConfigurationError` fails the step; unchanged, no Phase 9-specific rule |
| `IntelligenceCapability` failure | Same as above |

No distributed transaction is introduced anywhere in this Contract. The `NewsEvent` claim itself,
and the stale-recovery-ownership acquisition that heals its one residual gap, both carry real,
DB-level atomic guarantees (§7.5, §7.6) — the narrow, remaining gap neither can cover (a failure
between acquiring the right to process an event and a successful `create_task()` call) is stated
explicitly, with a defined, staleness-gated recovery path — not disguised as a stronger guarantee
than actually exists, and not silently unhandled either.

---

## 19. Extension Rules

Future phases MAY add: `EngagementAnalysisCapability`, full Final Scoring/Ranking, event
clustering, semantic novelty, embeddings/vector search, richer source engagement collection, a
real Opportunity Score, or external research tools for `ResearchCapability`.

Adding any of these MUST NOT require rewriting:
1. Triage's core deterministic contract (§3-§6) — new signals, if ever added, MUST be additive
   (new fields Triage MAY optionally consult), never a breaking change to its existing three-signal
   contract.
2. `ResearchCapability`'s public `CapabilityDefinition`/output contract (§8) — a future tool
   integration MAY extend what `ResearchCapability` can do, but MUST NOT break existing consumers
   of its current output shape without a formal amendment.
3. `IntelligenceCapability`'s public contract (§9) — same principle.
4. Phase 8's Capability execution mechanics (§11) — unchanged by definition, since Phase 9 never
   forks them.

---

## 20. Explicit Non-Goals

Phase 9 does NOT deliver:

1. Full `NEWS_ANALYSIS` completion (§13).
2. `EngagementAnalysisCapability`.
3. Final Editorial Ranking or the complete original Scoring specification
   (`docs/08_Database_Schema_Data_Models.md` §14).
4. Opportunity Score, under any name.
5. Semantic event clustering.
6. True cross-source novelty detection.
7. Embeddings.
8. Qdrant or any vector-DB integration.
9. Dynamic source-reputation learning.
10. Engagement-data collection (Telegram views/reactions/forwards, HN score/descendants, or
    equivalent).
11. Autonomous research agents or agent loops of any kind.
12. Web browsing / external research tools.
13. A persistent intelligence graph or any new domain-knowledge table.
14. A new Workflow Engine.
15. A new scheduler (§7.4).
16. Any new database model or migration.
17. The title-overlap/republication check (`docs/phase9_final_decisions.md` §7 — deferred, not
    merely undecided).
18. Durable, crash-safe multi-step workflow checkpointing of any kind (§14.1) — the
    Research→Intelligence handoff remains valid only within one uninterrupted `WorkflowRunner.run()`
    call.
19. A heartbeat, lease, or distributed-lock subsystem for claim/ownership liveness — staleness is
    derived entirely from the existing `NewsEvent.updated_at` column (§7.6).

---

## 21. Canonical Rules

1. Triage MUST be deterministic and MUST NOT call an LLM, a provider, or perform embedding/vector
   operations.
2. Triage's allowed inputs are exactly `published_at`, `collected_at`, `NewsSource.reliability_score`
   — no others, without a Contract amendment.
3. Triage MUST NOT permanently discard a publication — every triaged `NewsEvent` gets exactly one
   `EditorialTask`, at some `TaskPriority`.
4. Triage's output type is the existing `TaskPriority` enum — no parallel vocabulary.
5. No component in this phase computes or names anything "Opportunity Score."
6. `ResearchCapability` and `IntelligenceCapability` remain two separate Capabilities; neither
   directly imports or calls the other; Intelligence consumes Research's output only via
   `step_results`.
7. Both Capabilities obey the frozen Phase 8 Capability contract in full — no forked execution,
   retry, or error-translation rule.
8. No claim, test, or documentation may assert that the real `NEWS_ANALYSIS` `WorkflowType`
   reaches `COMPLETED` in Phase 9.
9. No new database model or migration is introduced.
10. No provider-specific logic or provider SDK import exists outside
    `integrations/llm_gateway/providers/`.
11. No Phase 9 component depends on clustering, embeddings, engagement data, or any other
    explicitly-deferred system (§20) to function.
12. The Triage Orchestrator claims a `NewsEvent` via an atomic conditional update
    (`NEW`→`PROCESSING`, affected-row-count checked) **before** calling `create_task()`, never a
    read-then-write claim, and never the reverse order (§7.2, §7.5).
13. `TaskPriority` MUST NOT be compared via native `<`/`>`/`<=`/`>=`/`sorted()`/`min()`/`max()`;
    priority-ordering logic MUST use an explicit ordinal mapping matching the canonical order
    `S > A > B > C` (§3).
14. The Research→Intelligence `step_results` handoff is valid only within one uninterrupted
    `WorkflowRunner.run()` call; Phase 9 does not provide, claim, or test crash-safe recovery
    across a process restart mid-workflow (§14.1).
15. A `PROCESSING` `NewsEvent` with no active task is NOT a recovery candidate unless its
    processing claim is also stale (`reference_now - updated_at > staleness_threshold`); recovery
    ownership of a stale candidate MUST be acquired via an atomic conditional update guarded by the
    exact previously-observed `updated_at` value, affected-row-count checked, never assumed (§7.6).

---

## 22. Open / Provisional Items

| Item | Classification |
|---|---|
| Freshness tier boundaries and numeric weights | PRODUCT CONFIGURATION |
| Freshness→`TaskPriority` threshold mapping | PRODUCT CONFIGURATION |
| Default value used when `reliability_score` is null | PRODUCT CONFIGURATION |
| Exact `services/`/`scripts/` module names and file layout | IMPLEMENTATION DETAIL |
| Exact `ResearchCapability`/`IntelligenceCapability` output JSON Schema field names | IMPLEMENTATION DETAIL |
| Whether Triage's explanation becomes queryable persistence in a later phase | DEFERRED |
| Title-overlap/republication check, if ever revisited | DEFERRED |
| Production scheduling mechanism for the Triage Orchestrator | DEFERRED |
| `engagement_analysis`/`AIExecution` write-path/engagement-data collection | DEFERRED |
| Whether/how a future phase authorizes `required=False` or a new `WorkflowType` to let `NEWS_ANALYSIS` complete for real | DEFERRED |
| Durable, crash-safe multi-step workflow checkpointing / recovery across a process restart (§14.1) | DEFERRED |
| Stale-claim recovery threshold duration (§7.6) | PRODUCT CONFIGURATION |

**Frozen, not provisional** (restated from §3-§4, §7.5, §7.6, §14.1 for emphasis): the allowed
input-signal set, the deterministic/no-LLM requirement, the no-hard-drop invariant, the separation
between Triage and Final Ranking, the `NewsEvent` atomic-claim DB-level guarantee, the requirement
that a staleness guard MUST gate recovery eligibility (its exact duration is configuration, but its
existence and positivity are not), the atomic recovery-ownership-acquisition mechanism (§7.6), the
`TaskPriority` explicit-ordinal-mapping requirement, and the uninterrupted-execution scope of the
`step_results` handoff are all architecture-critical and are NOT configuration.

---

## 23. Contract Acceptance Checklist

Self-audited before declaring this Contract complete:

1. No contradiction with Phase 6 — confirmed (P4's Capability-isolation rule cited, not altered;
   §7's `PromptRepository` rules cited, not altered).
2. No contradiction with Phase 7 — confirmed (Gateway boundary, observability formula, cited
   unchanged).
3. No contradiction with Phase 8 — confirmed (§11 requires full compliance, no fork).
4. No redesign of the Phase 5 workflow — confirmed (§13: `NEWS_ANALYSIS` unmodified).
5. No assumption that `NEWS_ANALYSIS` completes — confirmed (§13, §21 rule 8, explicit prohibition).
6. No hidden clustering dependency — confirmed (§3's closed signal list excludes it; Opportunity
   Score dropped entirely, §20 item 4).
7. No Opportunity Score — confirmed (§3, §20, §21 rule 5).
8. No engagement-data assumption — confirmed (§3's closed signal list; §20 item 10).
9. No provider-specific Capability logic — confirmed (§1 P5/P6, §17).
10. No new persistence requirement — confirmed (§14, §20 item 16).
11. Triage ownership is explicit — confirmed (§2.2, §3).
12. Orchestration ownership is explicit — confirmed (§7, including real DB-level atomic guarantees
    for both claim (§7.5) and stale-recovery ownership acquisition (§7.6), and the one remaining,
    honestly-disclosed operational constraint on the staleness threshold's calibration, §7.6).
13. Research and Intelligence boundaries are distinct — confirmed (§8, §9, §9.1, §10).
14. Failure ordering/idempotency is explicit enough to implement safely — confirmed (§7.5, §7.6,
    §18), including the one honestly-disclosed residual limitation and its defined, staleness-gated
    recovery path.
15. All MUST/MUST NOT statements are internally consistent — confirmed on review, including after
    this revision's changes to §7/§14/§3 (§9.1, §13, §16, §18, §20, §21, §22 all cross-checked and
    updated to match); no rule in one section contradicts a rule in another.
16. No implementation plan or milestone sequencing leaked into this Contract — confirmed; this
    document defines boundaries and invariants only.
17. No wording anywhere implies crash-safe Research→Intelligence persistence beyond one
    uninterrupted `run()` call — confirmed (§9.1, §13, §14.1, §16, §21 rule 14).
18. No wording anywhere relies on `TaskPriority`'s natural comparison/sort order — confirmed (§3,
    §16, §21 rule 13).
19. No wording anywhere relies solely on "the orchestrator must not run concurrently with itself"
    as the primary safety mechanism against duplicate claims — confirmed (§7.5: the DB-level atomic
    claim is now primary; the scheduling deferral is explicitly demoted to a secondary safeguard).
20. No wording anywhere treats `PROCESSING` + no-active-task, by itself, as sufficient for recovery
    eligibility — confirmed (§7.2, §7.6: staleness is a required, additional condition); no new
    heartbeat/lease/distributed-lock infrastructure, new column, or migration was introduced to
    achieve this (§7.6, §20 item 19).
