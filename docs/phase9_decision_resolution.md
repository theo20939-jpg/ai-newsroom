# Phase 9 — Product / Architecture Decision Resolution

**Status: analysis document. NOT a specification. NOT binding. Resolves the three open product
questions `docs/phase9_research_intelligence_discovery.md` left open, and re-evaluates that
document's proposed Phase 9 boundary.** No production code, migration, or frozen Phase 6–8
contract is touched by this document.

---

## 1. Executive Summary

All three product questions Discovery left open are resolvable now, from repository evidence
already gathered plus a small amount of additional, targeted inspection (`integrations/sources/telegram_source.py`,
`integrations/sources/hacker_news_source.py`, and confirming what currently calls
`workflow_service.create_task`). None required guessing.

The most consequential new finding is on Question 3: **no source adapter captures engagement
data today, for any source type — not even Telegram**, even though Telethon's `Message` object
exposes `.views`/`.forwards`/`.reactions` and the Hacker News API exposes `score`/`descendants`.
The gap is in `schemas/raw_news_item.py`'s narrow shape, not source-type capability. This
simplifies Question 3's answer considerably: Popularity Score cannot be computed for **anyone**
right now, so it is a uniform omission, not a per-source-type edge case to special-case around.

The second consequential finding is on the boundary re-evaluation: **"Ranking Engine" as
Discovery named it actually names two genuinely different things** — a deterministic *pre-filter/triage*
that must run *before* any `EditorialTask` exists (deciding whether AI spend happens at all), and
a *final ranking* that only makes sense *after* Research/Intelligence/Engagement Analysis have
run, which is exactly what the already-frozen `scoring` step (last in
`workflows/definitions/news_analysis.py`) is positioned for. Collapsing these into one component
would be a mistake. This narrows the recommended Phase 9 boundary relative to Discovery's original
proposal — see Section 7.

---

## 2. Decision 1 — Freshness

**Evidence**:
- `NewsEvent.published_at: datetime | None` (nullable), `NewsEvent.collected_at: datetime`
  (never null, `server_default=func.now()`) — both indexed
  (`database/models/news_event.py:52-57`).
- `docs/05_Scoring_Ranking_Specification.md` §10: *"Свежесть события является отдельной
  метрикой. Чем меньше времени прошло с момента публикации, тем выше потенциал... Однако влияние
  свежести уменьшается по мере старения новости"* — explicitly describes **decay with
  diminishing marginal impact**, not a step function, as the intended shape.
- `docs/05` §2 ("Explainable Ranking"): *"Для любой новости система должна уметь показать, из
  каких факторов сложилась итоговая оценка"* — every score component must be explainable to a
  human editor.
- `docs/05` §11: Editorial Priority (S/A/B/C) is itself an explicitly **discrete** downstream
  concept, derived from a continuous Raw Score via configured thresholds.

**Options**:
- **Continuous decay** (e.g. exponential half-life): mathematically matches §10's stated intent
  exactly, but a raw decay value ("0.63") is not directly explainable to a human editor without
  translation — conflicts with §2's explainability requirement unless paired with a label.
  **Not yet calibratable**: no real editorial feedback data exists yet to fit a defensible
  half-life constant (this document does not invent one).
- **Fixed buckets** (the six windows the task lists: 0–2h / 2–6h / 6–12h / 12–24h / 24–48h /
  48h+): trivially explainable ("this item is in the 2–6h bucket"), trivially testable
  deterministically, but a naive step function contradicts §10's "diminishing impact," not
  "impact drops off a cliff at each boundary."
- **Hybrid** (recommended): compute freshness as a small number of ordered tiers whose *assigned
  weights* are monotonically decreasing and can later be replaced by a smooth curve without
  changing the pipeline shape, while every score still carries its bucket label for §2's
  explainability requirement.

**Recommendation**: Hybrid, biased toward buckets for the MVP. Use the six stated windows as the
tier boundaries; assign each tier a **monotonically decreasing** weight (exact numeric weights are
Contract-phase work, not decided here — this document only fixes the *shape*: decreasing,
bounded, deterministic). Log both the raw bucket label and the numeric weight on every scored
`NewsEvent`, satisfying explainability without requiring curve-fitting before any real usage data
exists. A continuous decay function is an explicitly acceptable **future refinement**, not a
Phase 9 requirement.

**Proposed MVP rule** (safe to freeze now):
1. Freshness anchor = `published_at` when present; **fall back to `collected_at` when
   `published_at` is null**, and flag the fallback explicitly (e.g. a boolean or label on the
   score explanation) so a human reviewer can tell "measured from publish time" apart from
   "measured from collection time" — this is a deterministic, evidence-safe rule (not a product
   guess): `published_at` is genuinely nullable in the schema and not every adapter guarantees it
   (confirmed: Telegram and Hacker News both populate it reliably from their APIs; a generic RSS
   entry with a missing/malformed date is the realistic null case).
2. Six ordered tiers exactly as specified in the task, each with a placeholder decreasing weight
   to be finalized in the Architecture Contract.
3. Freshness is computed once, deterministically, at triage time (see Section 6) — it does not
   need to be recomputed later in the pipeline, since it is a fact about the publication, not
   about its analysis.

---

## 3. Decision 1B — Novelty

**This is explicitly a different concept from Freshness and must not be collapsed into it.**
Freshness asks "how old is this publication?" Novelty asks "is the underlying information new
relative to what the Newsroom already knows?" A same-day republication of yesterday's story is
maximally fresh (if freshness is measured from *this* publication's timestamp) but has zero
novelty.

**Evidence**:
- Discovery's Section 4 finding, re-confirmed here: `NewsEvent` is one publication from one
  source; there is no clustering/grouping construct linking publications about the same
  underlying story across sources.
- `NewsEvent.category` is unconditionally `UNKNOWN` at creation (`services/collector.py:156`) —
  **no category-scoped novelty check is possible today** without first solving classification,
  which is out of this document's scope and not part of Phase 9's proposed slice.
- Exact deduplication (`services/deduplication.py`) already solves "is this the *exact same*
  publication I've already stored" — that is **not** novelty, it is publication-identity
  detection, and the task is explicit that these must not be conflated.

**What is realistically possible before semantic clustering exists**:
A **deterministic, time-windowed, title-similarity check** (e.g. normalized-token Jaccard overlap
or trigram overlap) against recently-stored `NewsEvent` titles within a bounded window (the same
24–48h freshness window is a reasonable reuse, not a new concept to invent). At ~1000 items/day,
comparing a new title against a ≤48h rolling window (at most a few thousand rows, bounded and
indexed by `collected_at`) is computationally trivial — no LLM, no embeddings.

**What this deterministic check is, and is not**: it is an **extension of publication-level
near-duplicate detection** (catching near-verbatim republication or lightly-edited re-posts,
including across different sources using very similar wording) — it is **not** true cross-source
event-level novelty detection, which requires understanding that two *differently-worded*
publications describe the *same underlying happening*, and that genuinely requires either
semantic clustering (deferred, Discovery Section 11) or LLM judgment. Presenting a title-overlap
flag as "novelty" would repeat exactly the mistake the task warned against.

**Proposed MVP rule**:
1. Compute a deterministic `possible_republication` (or equivalently named) flag/score via
   title-token overlap against the recent window, at triage time. This flag feeds triage/pre-filter
   decisions (Section 6) — it may lower priority or defer AI spend on likely republications — but
   it is never presented to an editor as "novelty," and it never claims cross-source coverage.
2. Genuine novelty *judgment* ("is this angle/story actually new to our audience") is deferred to
   the **Intelligence Capability's own LLM reasoning** (already in Discovery's proposed scope) as
   one input among several it is asked to assess — this requires no new infrastructure beyond the
   Capability itself, since it is exactly the kind of judgment call `docs/13_1`'s original
   "Intelligence Capability = Определение ценности" (value determination) already describes.
3. True, clustering-backed cross-source novelty detection remains explicitly deferred, unchanged
   from Discovery.

---

## 4. Decision 2 — EditorialTask.priority

**Current semantics (FACT)**:
- `EditorialTask.priority: TaskPriority` (S/A/B/C) is a required, non-derived column
  (`database/models/editorial_task.py:41-43`).
- It is set exactly once, at creation, directly from caller input:
  `EditorialTask(..., priority=command.priority, ...)` (`services/workflow_service.py:65`), where
  `command: EditorialTaskCreate` requires `priority: TaskPriority` with no default
  (`schemas/editorial_task.py`).
- **No code anywhere computes or later mutates this value.** Grep across the repository found no
  caller of `workflow_service.create_task` outside `services/workflow_service.py` itself and
  `tests/` — no bot handler, no API route, no scheduled job currently triggers `EditorialTask`
  creation from a collected `NewsEvent` at all. This is a pre-existing gap independent of Phase 9.

**Options**:
- **A — Ranking directly mutates `EditorialTask.priority`** after the row already exists. This
  implies an `UPDATE` pathway that does not exist today, and raises an unresolved question this
  document will not silently answer: what happens to a workflow already using the *old* priority's
  implied budget/retry policy if priority changes mid-flight? Nothing in the current
  `WorkflowRunner`/`CapabilityExecutor` design supports a priority change after task creation.
- **B — Ranking produces a score/priority *recommendation*; a separate orchestration/task-creation
  step decides `EditorialTask.priority`.** `EditorialTask.priority` stays exactly what it already
  is: a plain, immutable-after-creation input to `create_task()`. No schema change, no new
  mutation pathway, no new persistence model.
- **C — another architecture-implied solution**: not found. The Collector
  (`services/collector.py`) already deliberately contains "no AI, scoring, ranking or content
  generation logic — orchestration only" per its own module docstring — extending it to also
  decide priority would violate its own stated single responsibility.

**Recommendation: B**, with strong architectural support, not just a stated preference:
- `services/cost_estimator.py` (Discovery's own cited precedent for the Ranking Engine's shape) is
  a pure, stateless computation whose caller (`FallbackPolicy`) decides what to do with the
  result — it never writes anything itself. The Ranking Engine should follow the identical pattern.
- `workflow_service.create_task()` **already accepts `priority` as a required parameter today** —
  Option B requires zero change to this API. The Ranking Engine simply becomes a new,
  principled *caller* supplying a computed value, in place of whatever currently supplies it
  (nothing, in production, per the finding above).
- Option B cleanly separates "what score does this publication deserve" (deterministic,
  testable in isolation, no DB write) from "should we actually create work for it, and at what
  priority" (an orchestration decision that may reasonably also consider things the Ranking Engine
  itself should not know about — e.g. current AI budget consumption for the day, per `docs/05`
  §12's Editorial Budget table — which is `BudgetGuard`'s concern, not a scoring concern).

**Open, explicitly out of scope for this document**: what production trigger connects "a
`NewsEvent` was collected" to "call `create_task()` with a Ranking-Engine-derived priority" does
not exist today and this document does not design it — see Section 10.

---

## 5. Decision 3 — Engagement Data

**Evidence, re-verified directly against adapter source code (not assumed):**

**Telegram** (`integrations/sources/telegram_source.py:56-67`): `_to_raw_item()` extracts only
`message.id`, `message.text`, `message.date` — it does **not** read `message.views`,
`message.forwards`, or `message.reactions`, even though Telethon's `Message` object exposes all
three. **Engagement data is technically available from the API today and is simply not being
captured**, because `RawNewsItem` (`schemas/raw_news_item.py`) has no field to hold it. There is
no subscriber/reach denominator captured anywhere either (`NewsSource` has no subscriber-count
field).

**Hacker News** (`integrations/sources/hacker_news_source.py:72-94`), included here as
corroborating evidence beyond the task's named source types: the HN Firebase API item payload
includes `score` (points) and `descendants` (comment count), and `_to_raw_item()` reads neither —
same pattern as Telegram: available, uncaptured.

**RSS/Atom** (`integrations/sources/rss_source.py`, `feed_parsing.py`): the RSS/Atom formats have
no standard engagement fields at all (some feeds carry non-standard extensions like WordPress's
comment-count element, but nothing this codebase's generic `feedparser`-based adapter reads or
could read without per-feed special-casing). **Structurally unavailable in general**, not merely
uncollected.

**Web** (`web_page` `SourceKind`, per `schemas/source_definition.py`): raw HTML has no structured
engagement signal without site-specific scraping or an external analytics API — genuinely
unavailable without work this codebase does not currently do, consistent with the task's framing.

**Conclusion — this reframes the problem**: the honest current-state fact is not "Telegram has
engagement data and RSS/Web don't" — it is **"no source type has engagement data flowing through
today, because the shared ingestion schema (`RawNewsItem`) doesn't carry it for anyone."** This is
a uniform gap, not a per-source-type inconsistency to design elaborate fallback logic around
right now.

**How the Ranking Engine should behave when engagement data is complete / partial / absent**:
- **Absent (the current, universal state)**: Popularity Score is not computed at all — it is
  omitted from the Raw Score sum entirely, not defaulted to zero. `Raw Score = Freshness +
  Opportunity + Authority` for the MVP, re-normalized over the components actually available,
  never silently zero-filling a missing one.
- **Partial** (a plausible future state once Telegram ingestion is extended but RSS/Web remain
  uncollected): the same re-normalization rule applies per-item — an item from a source with no
  engagement data is scored on Freshness/Opportunity/Authority alone, re-weighted, never penalized
  by an implicit zero for the missing Popularity term. This is the direct, load-bearing
  implementation of the task's explicit constraint: **"the ranking system MUST NOT systematically
  punish sources merely because their platform does not expose engagement metrics."**
- **Complete** (a future state, not this document's concern to design): standard weighted-sum
  Raw Score as `docs/05` §5 already specifies.

**Normalization strategy** (for when engagement data does eventually flow through — this document
does not design the ingestion-schema extension itself, only the scoring-side rule, which
`docs/05` already specifies and this document endorses rather than reinvents): normalize relative
to audience size/reach, not raw counts — `docs/05` §6 (*"просмотры нормализуются относительно
размера аудитории"*) and §9's worked example (a 100K-subscriber channel with 30% ER should
outrank a 1M-subscriber channel with 5% ER) already state this precisely; this document adds
nothing new here except confirming it is architecturally consistent with everything else found.

**Source-type-aware behavior (recommendation)**: the Ranking Engine's configuration should
distinguish two different flavors of "missing," so future ingestion work doesn't get silently
ignored — *"not yet collected but structurally possible"* (Telegram, Hacker News — a future
ingestion-schema extension could fill this) versus *"not structurally available for this source
type in general"* (RSS, generic Web) — but implementing this distinction is **not required for
the Phase 9 MVP**, since today every source type is in the first or second category identically
(zero engagement data, full stop). This is a forward-compatibility note for the Architecture
Contract, not an MVP requirement.

---

## 6. Pre-filter vs Final Ranking

**These are different concepts and must be kept separate. This is the most important finding in
this document.**

**Pre-filter / Triage**: *"Is this publication worth spending LLM resources on, and at what
priority?"* Runs **before** any `EditorialTask` exists, using only data available at or shortly
after collection time: Freshness, Authority (`NewsSource.reliability_score`), Opportunity
(age/source-count/growth, per `docs/05` §4.3), and the deterministic near-duplicate/title-overlap
flag from Section 3. It is purely deterministic — no LLM call has happened yet, because triage's
entire purpose is deciding whether one should. Its output feeds `create_task(priority=...)`
(Decision 2, Option B) — it decides *if and how much* AI work happens, mirroring `docs/05` §12's
Editorial Budget table exactly (Priority C = minimal/no Deep Research; S = full).

**Final Ranking**: *"How important is this fully-analyzed story, now that Research, Intelligence,
and Engagement Analysis have actually run?"* This can only happen **after** those steps produce
real output — it synthesizes LLM-derived judgments (Intelligence's importance/recommendation,
Research's confidence, Engagement Analysis's audience-reaction assessment) together with whatever
deterministic base signals remain relevant. This is precisely what the **already-frozen** `scoring`
step is positioned for — it is explicitly the *last* step in `workflows/definitions/news_analysis.py`'s
step order, downstream of `research → intelligence → engagement_analysis`. Phase 8's
`ScoringCapability` occupies this slot today but, per Discovery Section 5, does not yet consume
any prior step's output — it is a minimal mechanism proof, not a faithful Final Ranking
implementation.

**Are these the same thing? No — and forcing one component to do both jobs would be a genuine
design mistake**: triage must run on ~1000 items/day with zero LLM cost (that is its entire
reason to exist); final ranking, by construction, can only run on the subset of items that
already survived triage and paid for full analysis. A single "Ranking Engine" spanning both would
either force triage to wait for expensive analysis (defeating its cost-control purpose) or force
final ranking to ignore the analysis it exists to synthesize (defeating its purpose). They belong
at two different pipeline positions with two different inputs and two different consumers.

**Correct pipeline positions**:
- Triage: between publication-dedup and `EditorialTask` creation (a new, currently-nonexistent
  orchestration point — see Decision 2 and Section 10).
- Final Ranking: at/inside the existing `scoring` workflow step, consuming
  `CapabilityContext.business.workflow_state.step_results` from the three steps that precede it —
  no new pipeline position needed, since the frozen `NEWS_ANALYSIS` step order already reserves
  the right slot for it.

---

## 7. Phase 9 Boundary Re-evaluation

Discovery proposed: **Deterministic Ranking Engine + ResearchCapability + IntelligenceCapability**
in one Phase 9. Re-evaluated against Section 6's finding, this proposal conflated triage and final
ranking under one "Ranking Engine" label. Splitting them changes the answer.

1. **Is that still small enough for one phase?** Not quite as originally framed — "Ranking Engine"
   implied doing both triage and final-ranking work, which Section 6 shows are different jobs at
   different pipeline positions with different dependencies (final ranking depends on Research/
   Intelligence already existing; triage does not). Scoped correctly (triage only, see below), the
   phase is smaller and more coherent than Discovery's original framing, not larger.

2. **Should Ranking Engine come before Research/Intelligence as its own separate phase?** Only the
   *triage* half needs to exist before Research/Intelligence can run meaningfully at real volume
   (it is what decides whether they run at all) — but building triage with no Capability yet to
   gate would be untestable in any end-to-end sense and would not, by itself, produce the
   Newsroom-intelligence value the business goal cares about. Building them together, in one
   phase, still makes sense — Discovery's instinct to bundle was right; only the *scope of
   "Ranking"* needed correcting.

3. **Does Ranking logically operate before Research, after Intelligence, or at multiple stages?**
   **Both — but as two different mechanisms, not one.** Triage operates before Research (gating).
   Final Ranking operates after Intelligence/Engagement Analysis (synthesizing) — the frozen
   workflow's own step order already reflects this by placing `scoring` last.

4. **How does deterministic pre-filtering coexist with the frozen `research → intelligence →
   engagement_analysis → scoring` workflow without redesigning it?** Cleanly, because triage never
   enters that workflow at all — it is a gate *upstream* of `EditorialTask`/`WorkflowRunner`
   entirely, deciding whether/at what priority a `NEWS_ANALYSIS` run is even started. Nothing
   about the frozen step order needs to change; triage is architecturally invisible to it.

5. **Are we confusing pre-filter/triage with final editorial ranking?** Discovery's original
   framing risked exactly this by naming one "Ranking Engine." This document's answer: **yes, they
   must be treated as two separate concepts** — resolved in Section 6.

**Revised recommendation: D — a narrower boundary than Discovery's original proposal.**

**Phase 9 = deterministic Triage/Pre-filter (Freshness, Authority, Opportunity, the near-duplicate
title-overlap flag, feeding `EditorialTask.priority` via Decision 2's Option B) + ResearchCapability
+ IntelligenceCapability**, explicitly **excluding** any enhancement of `ScoringCapability` into a
real Final Ranking implementation. Final Ranking depends on Research and Intelligence already
producing real output to consume — attempting it in the same phase that builds them for the first
time risks designing its consumption contract against outputs that don't exist yet to validate
against. Enhancing `scoring` to actually read `step_results` is well-motivated **follow-up** work,
not this phase's job. This is not simply Discovery's option A (it explicitly narrows "Ranking" to
triage only and explicitly excludes Scoring enhancement), not option B (it still includes
Research+Intelligence), and not option C (deterministic triage stays in this phase, tightly
coupled to gating the Capabilities it's built alongside) — hence **D**.

---

## 8. Proposed End-to-End Data Flow

```
source ingestion            [WORKFLOW: none — Collector cycle]  [DETERMINISTIC]  [PERSISTENCE: NewsSource read]
   ↓
normalization                [DETERMINISTIC]  (services/cleaning.py)
   ↓
publication dedup            [DETERMINISTIC]  (services/deduplication.py)  [PERSISTENCE: NewsEvent write]
   ↓
near-duplicate / title-overlap flag   [DETERMINISTIC, NEW]  (Decision 1B)
   ↓
deterministic TRIAGE (Freshness + Authority + Opportunity → priority recommendation)
                              [DETERMINISTIC, NEW]  (Decision 1, 2, 6)
   ↓
EditorialTask creation with Ranking-derived priority
                              [WORKFLOW]  [PERSISTENCE: EditorialTask write]  (Decision 2, Option B)
   ↓
research                     [LLM Capability, NEW]  [WORKFLOW step]  [PERSISTENCE: EditorialTask.workflow JSON, via existing step_results mechanism]
   ↓
intelligence                 [LLM Capability, NEW, consumes research's step_results]  [WORKFLOW step]  [PERSISTENCE: same as above]
   ↓
engagement analysis          [OUT OF SCOPE for Phase 9 — Amendment A gap unresolved]  [WORKFLOW step, unregistered]
   ↓
scoring / final ranking      [EXISTING Capability (Phase 8), NOT enhanced this phase]  [WORKFLOW step]  [PERSISTENCE: same as above]
   ↓
editorial decision           [OUT OF SCOPE — no automation exists; currently would be manual/human]
```

---

## 9. Decisions Ready to Freeze

1. Freshness anchor = `published_at`, falling back to `collected_at` when null, with the fallback
   explicitly flagged.
2. Freshness is computed as ordered, monotonically-decreasing-weight tiers using the six windows
   named in this task (exact numeric weights deferred to Contract).
3. Novelty is **not** achievable pre-clustering; only a title-overlap **near-duplicate/republication**
   proxy is achievable, and it must never be labeled or presented as "novelty."
4. Genuine novelty *judgment* is an Intelligence Capability prompt concern, not a separate
   deterministic pipeline stage, for this phase.
5. `EditorialTask.priority` remains a plain, creation-time-only field (Option B) — no mutation
   pathway is added.
6. The Ranking Engine (triage) is a pure, stateless, non-persisting computation, architecturally
   identical in shape to `services/cost_estimator.py`.
7. Popularity Score is **omitted entirely** from the Phase 9 Raw Score — not defaulted to zero,
   not source-type-special-cased, simply absent from the formula until an ingestion-schema
   extension exists to feed it.
8. Raw Score re-normalizes over whatever components are actually available; missing components are
   never zero-filled.
9. Triage and Final Ranking are two separate mechanisms at two separate pipeline positions; this
   phase builds only Triage; Final Ranking enhancement is deferred follow-up work.
10. The revised Phase 9 boundary is: deterministic Triage + `ResearchCapability` +
    `IntelligenceCapability`, excluding Scoring enhancement and excluding Engagement Analysis.

## 10. Decisions Still Open

**BLOCKING BEFORE CONTRACT**:
- None identified. Every question Discovery flagged as blocking has a resolution above.

**CAN SAFELY DEFER** (Contract-phase detail, or genuinely later work):
- Exact numeric Freshness tier weights, Raw Score component weights, and Editorial Priority
  thresholds (config-driven per `docs/05` §14 — deliberately not fixed in code either).
- Exact title-similarity algorithm and threshold for the near-duplicate flag.
- What production trigger connects "`NewsEvent` collected" to "`create_task()` called" — this
  does not exist today for *any* priority-assignment mechanism, is independent of Phase 9's
  Capability work, and can remain a manual/test-only entry point through this phase without
  blocking Research/Intelligence from being built and proven.
- Whether/when to extend `RawNewsItem`/ingestion to actually carry engagement fields Telegram/HN
  already expose but currently discard — a well-scoped, independent future increment.
- Amendment A's `"engagement"` capability-name resolution (unchanged from Discovery).
- Whether/when `AIExecution` gets a real write path for Research/Intelligence's cost audit trail.

## 11. Final Verdict

**PHASE 9 BOUNDARY SHOULD BE CHANGED**

All three product questions Discovery raised are now resolved with concrete, evidence-grounded
recommendations, and no new blocking ambiguity was introduced in resolving them. However, the
process of resolving Decision 2 and the pre-filter/final-ranking distinction (Section 6) revealed
that Discovery's original one-phase "Ranking Engine + Research + Intelligence" framing bundled two
architecturally distinct mechanisms under one name. The corrected, narrower boundary in Section 7
— deterministic Triage (not "Ranking" broadly) + Research + Intelligence, excluding Scoring
enhancement and Engagement Analysis — is what should proceed to Architecture Contract drafting,
not the boundary exactly as Discovery first proposed it.
