# Phase 20 — Final Technical Report: Story Memory V2

**Status: Story Memory V2 remains 100% shadow-only.** `story_memory_mode=off` in the real `.env`
(unchanged default throughout all of Phase 20). No worker restarted, no Telegram message sent, no
paid LLM call made, no migration applied, no commit made as part of this phase's own work. This
report consolidates Checkpoints 1 through 5.

---

## 1. Checkpoint evolution (CP1 → CP2 → CP3 → CP4 → CP5)

- **Checkpoint 1** (M2–M5): candidate retrieval widened past the original category hard-gate;
  symmetric title-overlap scoring; word-boundary topic classification; `RELATED_STORY` outcome
  introduced. Fixed Kitesurf and AI-Olympiad-event-8 regressions in isolated single-candidate
  tests. Two partial fixes disclosed (AI Olympiad event 14, Moscow pair moved from silently-wrong
  `NEW_STORY` to `UNCERTAIN_MATCH` — a real but incomplete improvement).
- **Checkpoint 2** (M6–M11): Delta Engine (`services/story_delta_engine.py`), suppression proposal
  layer (`services/story_suppression.py`), confidence bands (`services/story_confidence.py`),
  Story Timeline observability fix, V6 prior-coverage serializer extension, shadow-column
  migration (created, unapplied), and the first real multi-day historical replay (3,774 events).
  That replay discovered two structural blockers invisible to isolated unit tests: **94.2%
  candidate-cap saturation** and a **Story Identity Gap** (non-`NEW_STORY` outcomes never create
  their own Story). Recommendation: NO-GO.
- **Checkpoint 3**: fixed both blockers. **M11.1** (Story Identity Invariant) — `RELATED_STORY`
  and low-entity-overlap `UNCERTAIN_MATCH` now create their own Story. **M11.2** (Retrieval V2) —
  two-stage retrieval (wide SQL fetch + cheap Python preselection) replacing the flat 150-candidate
  SQL limit; one new index migration. Same-dataset replay showed real wins (saturation 94.2%→
  43.8%, material-update detection +210%, Kitesurf converges) alongside a newly surfaced concern:
  AI Olympiad event 14 landed a high-confidence match that looked, from the available
  instrumentation, like it might be a false merge. Recommendation: NO-GO, flagged for
  investigation.
- **Checkpoint 4** (Precision Hardening): investigated the event-14 concern with full
  ranked-candidate + complete Story-detail instrumentation and found it was a **false alarm** —
  the match was correct, into a real 5-member cluster the calibration dataset simply hadn't fully
  captured. Found and fixed a **different, confirmed** false-positive risk instead (a
  template-headline delta-engine gap, evidence-grounded in a real suppression-packet case).
  `would_suppress` count dropped 263→173 (-34%) with zero change to retrieval or relationship
  classification. Two harder synthetic negative controls added. Story identity semantics formally
  defined; one schema limitation documented (not migrated). Recommendation: NO-GO, pending human
  suppression review.
- **Checkpoint 5** (this report): built the human suppression review packet (73 stratified
  would_suppress cases + 16 controls), performed full Story-cluster-context identity analysis for
  all 4 mandatory cases (one further reproducible defect found and disclosed, not fixed - out of
  this checkpoint's scope), resolved the schema-limitation question (does not block current
  production goals), and produced this consolidated report.

## 2. Current retrieval architecture

Two-stage, in `services/story_memory.py`:
- **Stage 1** (`_fetch_candidate_stories`): SQL, time-windowed (`settings.
  story_match_lookback_days`, default 14), safety-capped at `_RETRIEVAL_FETCH_SAFETY_CAP=10,000`
  (reasoned from real replay volume, not guessed), ordered by `updated_at DESC`. Requires
  `stories.updated_at` to be indexed (previously was not - fixed this phase, migration
  `3f37cf34109d`).
- **Stage 2** (`_preselect_candidates`, pure Python): two unioned tiers feeding the unchanged
  `STORY_MATCH_CANDIDATE_LIMIT=150` cap on full scoring - up to 150 candidates ranked by
  entity/keyword set-intersection relevance, plus up to 50 most-recent candidates unconditionally.
  No embeddings, no vector DB, no LLM, no new microservice.

Measured effect (3,774-event replay): mean Stage-1 pool size grew from ~146 (old flat SQL limit)
to ~1,265; Stage-2 (scoring-bound) cap saturation fell from 94.2% to 43.8%.

## 3. Current relationship classifier

`services/story_memory.py::score_candidate()` - unchanged core formula since Checkpoint 1:
`combined = 0.6·entity_jaccard + 0.4·symmetric_title_overlap + small category/topic bonuses
(0.05 each, capped)`. Outcome bands: `< 0.35` → `NEW_STORY` (or `RELATED_STORY` if
`entity_overlap >= 0.2`), `>= 0.65` → confident zone split by title overlap into
`SEMANTIC_DUPLICATE`/`SUPPORTING_SOURCE`/`STORY_UPDATE`, else `UNCERTAIN_MATCH`. **Not changed
this phase** - Checkpoint 4's investigation found no confirmed false positive here to justify a
change; the one candidate case (Event 14) was correct. `MatchResult` now also exposes
`entity_overlap` explicitly (new this phase, plumbing only) so the Story Identity dispatch can
use it.

**One reproducible, disclosed-not-fixed defect** (M13, Checkpoint 5): generic, high-frequency
tokens (e.g. Russian *"российский"*, *"ии"*) can inflate a candidate's score enough to beat a
genuinely more-related candidate purely on keyword-overlap coincidence (AI Olympiad event 8's
exact case, full evidence in `docs/phase20_m13_identity_convergence_analysis.md`). Not addressed
this phase per explicit scope (human review + identity documentation only).

## 4. Current Delta Engine

`services/story_delta_engine.py::classify_delta()` - pure, reuses `services/
fact_safety.py::extract_claims()` (money/percentage/date/metric-quantity) and `services/
story_memory.py::extract_story_signature()` (keyword-set delta). Five outcomes: `MATERIAL_UPDATE`
→ `NO_NEW_FACTS` → `CONFIRMATION_ONLY` → `MINOR_DELTA` → `UNCERTAIN_DELTA` (first match wins).
**Checkpoint 4 fix**: `CONFIRMATION_ONLY` now additionally requires no new distinctive keywords
(previously: high title overlap alone was sufficient) - closes a real template-headline false-
positive risk, test-first, evidence-grounded.

## 5. Current identity semantics

Full definitions: `docs/phase20_m11_1_story_identity_semantics.md`. Four relations: **membership**
(confirmed same-story, bumps `event_count`), **provisional membership** (`UNCERTAIN_MATCH` + real
entity signal, attaches without bumping), **related-to** (transient, logged only, never
persisted), **provisional root** (Checkpoint 3's own new case - a fresh Story whose founding
evidence was itself uncertain/related). Dispatch in `services/triage_orchestrator.py::
_apply_story_memory()`.

## 6. Current suppression proposal logic

`services/story_suppression.py::compute_would_suppress()` - unchanged policy since Checkpoint 2:
`True` only for `SEMANTIC_DUPLICATE`/`SUPPORTING_SOURCE` + `HIGH` confidence band + delta in
`{NO_NEW_FACTS, CONFIRMATION_ONLY}`. `MINOR_DELTA`/`UNCERTAIN_DELTA`/`UNCERTAIN_MATCH` never
suppress. **Not enabled anywhere** - a shadow-only computed value, read by nothing in production.

## 7. Mandatory case results (full Story-cluster context, M13)

| Case | Result | Classification |
|---|---|---|
| **Kitesurf** | Both events converge onto one story - **but that story is not a dedicated "Kitesurf" story**; it's rooted at an adjacent Cloudflare OS announcement. Technically passes the literal acceptance test; qualitative nuance corrected this checkpoint. | IDENTITY_BOOTSTRAP_GAP + EXPECTED_UNCERTAINTY |
| **AI Olympiad** (4/8/14) | 3 real, independently-discovered article clusters exist for this event; the calibration set's own 3 events span 2 of them. Event 4: plausible, conservative. Event 8: **confirmed reproducible SCORING_MISS** (generic-token score inflation). Event 14: confirmed correct (Checkpoint 4). | Mixed - see §3 |
| **Moscow pair** | Does not converge with each other; each independently attached to a different, genuinely-adjacent real story. No false confident merge (mandatory invariant holds). | EXPECTED_UNCERTAINTY |
| **GTA negative control** | Remains separate (mandatory requirement holds); event 5's own adjacent match (a real GTA6/Netflix article) is plausible, not confirmed wrong. | NO_ISSUE |

## 8. Historical replay metrics (final state, Checkpoint 4)

3,774 real events, 2026-08-04→2026-08-07, disposable Postgres, reproduced byte-identically across
multiple runs (deterministic). `NEW_STORY` 1,503, `STORY_UPDATE` 150, `SUPPORTING_SOURCE` 17,
`SEMANTIC_DUPLICATE` 247, `UNCERTAIN_MATCH` 1,011 (26.8%), `RELATED_STORY` 852/853. Candidate-cap
saturation 43.8% (down from 94.2% pre-Checkpoint-3). Fragmented-story count 922. `would_suppress`
173 (down from 263 pre-Checkpoint-4 hardening, -34%). Full detail:
`artifacts/phase20_m11_replay_results.json`, `docs/phase20_checkpoint2_report.md`,
`docs/phase20_checkpoint3_report.md`, `docs/phase20_checkpoint4_report.md`.

## 9. Remaining known limitations

1. **AI Olympiad event 8's SCORING_MISS** (§3) - a real, reproducible, disclosed defect. Not
   fixed this phase (out of scope).
2. **Kitesurf's true identity is ambiguous** (§7) - whether "Kitesurf" and the adjacent
   "Cloudflare OS" story are the same real announcement cannot be resolved from headlines alone.
3. **Moscow pair does not converge** - each event independently, defensibly, attaches to a
   different adjacent real story; the pair's own true relationship remains `NEEDS_HUMAN_LABEL`
   (as the calibration dataset always disclosed).
4. **Suppression precision/recall is not yet known** - the 173-case human-review packet
   (`docs/phase20_m12_suppression_review_packet.md`) has not been reviewed by a person.
5. **Correct-story retrieval rank was only added late** (Checkpoint 4's M13 pass) - not available
   for earlier checkpoints' own historical comparisons.

## 10. Suppression review packet

`docs/phase20_m12_suppression_review_packet.md` - 73 stratified `would_suppress=True` cases
(supporting-source, semantic-duplicate, highest-confidence, threshold-edge, cross-source,
cross-category, same-source, aggregator-repeat categories) + 16 controls (8 non-suppress, 8
material-update). Every case has full new-event and matched-Story facts (including every
previously-linked event's title/source), the exact decision/reason, and a blank, never-auto-filled
HUMAN VERDICT checkbox. **Not yet reviewed.**

## 11. Schema limitation

`NewsEventStoryLink` cannot represent both "belongs to Story X" and "related to Story Y"
simultaneously (`news_event_id` is the table's primary key). Full analysis: `docs/
phase20_m11_1_story_identity_semantics.md`.

**Resolution (Checkpoint 5)**: this limitation does **not** block Phase 20's actual production
goals. Same-story identity (membership) is fully representable without it - `RELATED_STORY` is,
by definition, a *non*-membership relation, so its own metadata gap cannot affect same-story
tracking. Future Telegram update-reply routing (`StoryTelegramDelivery`) would key off confirmed
membership outcomes only - a `RELATED_STORY` cross-reference should never drive reply-threading
into a different story's own thread, so this gap doesn't block that either. **Deferred, no
migration proposed** - revisit only if a future milestone needs genuine cross-story "see also"
functionality, which nothing currently consumes.

## 12. V6 Fact Safety compatibility blocker (preserved from Phase 19)

`services/fact_safety.py::apply_fact_safety()` reads `copywriting_output["body"]` (V4's schema
shape); V6's schema (`prompts/copywriting/v6.yaml`) is sectional (`opening`/`context`/
`why_it_matters`/...) with no `"body"` key - `apply_fact_safety()` structurally no-ops for V6
output regardless of `fact_safety_mode`. **Not fixed, not broadened into a Fact Safety redesign**,
per every checkpoint's own explicit instruction. This remains a real, disclosed **blocker to any
global V6 production activation** - do not claim V6 production-safe until this is resolved in a
separately-scoped Fact Safety milestone.

## 13. Migrations created / not applied

Two Phase 20 migrations, both additive, neither applied to the real database:
1. `3c22be05f4e5` - 3 nullable columns (`delta_classification`, `confidence_band`,
   `would_suppress`) on `news_event_story_links` (Checkpoint 2). ORM model deliberately does not
   yet declare these columns (see `database/models/story_link.py`'s own docstring - declaring
   them before application breaks every real insert, verified).
2. `3f37cf34109d` - one btree index on `stories.updated_at` (Checkpoint 3, required for the wider
   Stage-1 retrieval fetch to stay cheap). Safe to declare on the ORM model immediately (an index
   never appears in a generated INSERT/UPDATE, unlike a column).

Real DB revision: `8faedf40f596` (unchanged all phase). Alembic head: `3f37cf34109d`. Migration
application requires separate, explicit future authorization.

## 14. Production modes unchanged

`story_memory_mode=off` (default, real `.env` unchanged). No shadow activation requested or
performed this phase. No worker restarted. No Telegram message sent (structurally impossible -
the replay script imports no bot/Telegram module). No paid LLM call made (every Phase 20 component
- matcher, delta engine, confidence bands, suppression policy - is 100% deterministic; the replay
script imports no LLM gateway). No commit made as part of this phase's own work (per every
checkpoint's own scope).

## 15. Recommendations

### STORY MEMORY SHADOW
**Conditional GO**, but not yet exercised. All Phase 20 code is shadow-safe by construction
(isolation-tested: `tests/test_story_memory_v2_shadow_isolation.py`), and the AST-level guarantees
hold. Turning `story_memory_mode=shadow` on in the real `.env` would be a low-risk, easily-
reversible activation (writes shadow data only, changes no real behavior) - **but was not
requested or performed this phase**, and should be a separate, explicit decision, not a byproduct
of this report.

### DUPLICATE SUPPRESSION ENFORCE
**NO-GO.** The suppression policy itself is well-tested and its one confirmed false-positive
mechanism was fixed this phase, but **zero human review of real suppression candidates has
happened** - `docs/phase20_m12_suppression_review_packet.md` exists specifically to enable that
review and has not yet been used. No precision/recall number exists. Do not enable until reviewed.

### STORY UPDATE ENFORCE
**NO-GO.** Depends on both Story Memory shadow validation (not yet exercised in shadow mode) and
the still-open identity questions (§7, §9) - particularly the AI Olympiad event-8 scoring defect
and the general question of how often a "correct" Story exists but is lost to retrieval/scoring
noise at real production volume beyond the 4 labeled cases. Additionally blocked, independently,
by the V6 Fact Safety compatibility gap (§12) for any V6-routed update content specifically.
