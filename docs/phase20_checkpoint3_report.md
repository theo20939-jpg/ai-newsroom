# PHASE 20 — CHECKPOINT 3: STORY IDENTITY + RETRIEVAL V2

**Status: reporting only. No enforce activation, no suppression activation, no `.env` changes, no
worker restarts, no Telegram sends, no paid calls, no Phase 21 work.** Story Memory V2 remains
fully shadow-only; the real `.env` still has `story_memory_mode=off`. This report is honest about
a genuinely mixed result: real, measured wins alongside a newly-discovered interaction between the
two fixes that itself needs review before any GO decision. **Recommendation: NO-GO, with a
specific new item to investigate before Checkpoint 4** (§13).

---

## 1. Root causes (recap, now with M11.1/M11.2 evidence)

Two independent, confirmed mechanisms explained Checkpoint 2's Kitesurf/AI-Olympiad regressions:

**A. Story Identity Gap** — `services/triage_orchestrator.py::_apply_story_memory()`'s dispatch,
unchanged since Phase 18.10, only ever created a fresh `Story` for the `NEW_STORY` outcome. Every
other outcome — including `UNCERTAIN_MATCH` and `RELATED_STORY`, neither of which is a confirmed
same-story match — attached the event to whatever existing candidate scored best, permanently
(`NewsEventStoryLink.news_event_id` is the table's primary key; nothing ever re-evaluates a link
once written). A genuinely new story's root event could therefore never become its own anchor if
its first comparison happened to be uncertain or loosely related.

**B. Candidate Retrieval Capacity** — `_fetch_candidate_stories()`'s SQL query capped at a flat
150 candidates ordered by recency, with `stories.updated_at` **entirely unindexed**. Measured at
94.2% cap saturation across a real 4-day/3,774-event replay — the true candidate was silently
displaced from the scored set by more-recently-touched, unrelated stories on the vast majority of
retrievals during ordinary production volume.

## 2. Exact Story Identity fix (M11.1)

Documented investigation: `docs/phase20_m11_1_story_identity_investigation.md`. Dispatch in
`_apply_story_memory()` now:

- `NEW_STORY` → creates its own Story (unchanged).
- `RELATED_STORY` → **now also creates its own Story** (previously attached to the unrelated
  candidate). `RELATED_STORY` is already, by construction in `services/story_memory.py`, a
  confident signal that this is a *different* story (`combined < 0.35`); the bug was never
  actually creating that different story.
- `UNCERTAIN_MATCH` → split by `entity_overlap` (a value `score_candidate()` already computed
  internally; now exposed on `MatchResult` for the first time) against the *already-existing*
  `_RELATED_STORY_ENTITY_FLOOR = 0.2` constant (not a new, uncalibrated threshold):
  - `>= 0.2` (real, substantial signal, e.g. Moscow's 0.4): unchanged — attach without bumping
    `event_count`.
  - `< 0.2` (weak/coincidental, e.g. a genuinely new cluster's root event crossing the low bar by
    chance): creates its own Story.
- `STORY_UPDATE`/`SUPPORTING_SOURCE`/`SEMANTIC_DUPLICATE` unchanged — always attach and bump.

No merge/convergence machinery was added. A later, more decisive event scored against a
fragmented provisional Story converges the cluster's *future* growth onto it normally via the
existing confirmed-outcome path — already-linked events are never retroactively re-parented (out
of scope as "more than the smallest fix").

Tests written *before* implementation, confirmed failing against the old dispatch, then passing
after (`tests/test_story_identity_invariant.py`, 5 tests, all passing): Kitesurf root
`RELATED_STORY` case, AI Olympiad root `UNCERTAIN_MATCH` case, unrelated-story-never-merged check,
later-strong-evidence-converges check, strong-entity-overlap-does-not-fragment check.

**Disclosed limitation** (known at design time, confirmed by M11.3's own replay — see §9): the
`entity_overlap >= 0.2` split is a heuristic, not a proof. It creates a new, unforeseen interaction
with the retrieval fix (§9).

## 3. Exact retrieval algorithm (M11.2)

Two-stage retrieval in `services/story_memory.py`:

- **Stage 1 (SQL)**: `_fetch_candidate_stories()` now fetches up to `_RETRIEVAL_FETCH_SAFETY_CAP =
  10,000` stories in the time window (was a flat `LIMIT 150`), ordered by `updated_at DESC`. This
  cap is a safety bound, not a quality lever — reasoned from the replay's own real data (~610 new
  stories/day → ~8,500/14-day window), not guessed.
- **Stage 2 (pure Python, `_preselect_candidates()`)**: two unioned tiers, feeding the unchanged
  `STORY_MATCH_CANDIDATE_LIMIT = 150` cap on what reaches full `score_candidate()` scoring:
  - up to 150 candidates with the highest `(entity_overlap_count, keyword_overlap_count)`
    set-intersection against the new event's own `StorySignature` (reuses already-extracted
    entities/keywords — no new extraction, no embeddings).
  - up to 50 most-recently-updated candidates, unconditionally (preserves today's behavior for a
    fresh, low-keyword-overlap corroboration).

No embeddings, pgvector, vector DB, LLM candidate retrieval, external NLP dependency, or new
microservice were added. Category/topic remain soft scoring bonuses only (unchanged since M3).

9 new unit tests (`tests/test_story_memory.py`), all passing.

## 4. Whether any schema/migration was required, and why

**Two new migrations, both additive, neither applied to the real database:**

1. `3f37cf34109d_add_stories_updated_at_index.py` — a plain btree index on `stories.updated_at`.
   **Required**: this column had **no index at all** (confirmed via direct `\d stories` against
   the real dev DB) despite being the sole predicate/sort key of `_fetch_candidate_stories()`'s
   query since Phase 18.10. Widening that query's effective fetch (Stage 1) without this index
   would make an already-unindexed full-table-scan-and-sort meaningfully worse as the `stories`
   table grows past its current near-empty state (26 real rows today). A plain index is not "new
   technology" — it is the same class of infrastructure `ix_stories_category` already uses.
   **Safe to declare on the ORM model immediately** (unlike a new column, an index never appears
   in a generated `INSERT`/`UPDATE` column list, so this has zero effect on inserts against a DB
   that has not been migrated yet — verified).
2. `3c22be05f4e5` (Checkpoint 2's M10 migration, already created, still unapplied) — unaffected by
   this corrective block; still pending.

No column-level schema change was needed for the Story Identity fix (§2) — `MatchResult.
entity_overlap` is an in-memory dataclass field, not a database column.

## 5. Retrieval observability

Offline-only (never persisted to any production hot-path table), added to
`scripts/phase20_story_memory_replay.py`:

- Stage 1 pool size and Stage 2 (post-preselection) pool size, recorded per event.
- Stage 2 cap-saturation flag, per event.
- For every event in the 4 labeled real cases with an earlier sibling in the same case: whether
  the sibling's own recorded Story is genuinely rooted at that sibling event
  (`prior_story_identity_ok`), present in Stage 1, present in Stage 2, its full score-component
  breakdown if scored (`combined`, `entity_overlap`, `title_overlap`, and each's weighted
  contribution), the actually-chosen outcome/story/score, and a classification into
  `RETRIEVAL_MISS` / `SCORING_MISS` / `IDENTITY_MISS` / converged (`None`).

Classification precedence: converged first, then `IDENTITY_MISS` (the sibling's own story isn't
really its story), then `RETRIEVAL_MISS` (absent from Stage 1 or Stage 2), then `SCORING_MISS`
(present but lost to scoring/classification). **Caveat, disclosed**: this precedence means a case
can have *both* an identity problem and an underlying retrieval/scoring problem, but only the
identity classification is reported — see §9's own discussion of why this matters this round.

## 6. BEFORE vs AFTER (Checkpoint 2 baseline → this replay)

Same dataset both times: 2026-08-04 → 2026-08-07, 3,774 real events, disposable Postgres, zero
production mutation, zero Telegram, zero paid calls. BEFORE = `artifacts/
phase20_checkpoint2_baseline_replay_results.json` (preserved). AFTER = `artifacts/
phase20_m11_replay_results.json` (this run; reproduced byte-identically across two consecutive
full runs, confirming determinism).

| # | Metric | BEFORE | AFTER | Change |
|---|---|---|---|---|
| 1 | Candidate retrieval recall (labeled set) | 1 of 4 real cases had every needed candidate present when checked (partial - see text) | Retrieval (Stage 1+2) presence succeeded for 5 of 6 pairwise sibling checks; the 6th (GTA) was absent from Stage 2 specifically | Retrieval-level recall improved, but is now entangled with identity issues (see row 8) |
| 2 | Candidate-cap saturation | **94.2%** (flat SQL `LIMIT 150`) | **43.8%** (Stage 2, post-preselection 150 cap); Stage 1 mean pool size 145.8 → **1,265** | Saturation roughly halved; raw candidate visibility grew ~8.7x |
| 3 | Correct-story avg/median retrieval rank | **not instrumented** | **not instrumented** | Gap disclosed, not fabricated - a real limitation of this round's instrumentation |
| 4 | Same-story precision (labeled set) | 0 confirmed false merges | 0 confirmed, **1 suspected, unconfirmed** (AI Olympiad event 14 → high-confidence `SEMANTIC_DUPLICATE`, 0.827, against a 3rd, unrelated story - see §9) | Possible new regression, flagged, not yet confirmed |
| 5 | Same-story recall (labeled set) | 1 of 2 "should-converge" pairs converged (Moscow) | 1 of 2 converged (**Kitesurf**, swapped in; **Moscow regressed**, swapped out) | Net flat on this tiny n=4 sample; composition changed, not a clean improvement |
| 6 | False-merge rate (labeled set) | 0/4 cases | 0/4 confirmed, 1/4 suspected | See row 4 |
| 7 | Missed-merge rate (labeled set) | 2/4 cases (Kitesurf, AI Olympiad) | 2/4 cases (AI Olympiad, **Moscow** - swapped) | Unchanged count, different composition |
| 8 | Identity-miss count (6 labeled pairwise checks) | n/a (metric didn't exist) | **5 of 6** | High - see §9, a genuinely surprising interaction with the retrieval fix |
| 9 | Retrieval-miss count (6 labeled pairwise checks, after identity precedence) | n/a | **0** | Retrieval itself is no longer the presenting blocker for this labeled set |
| 10 | Scoring-miss count (6 labeled pairwise checks, after identity precedence) | n/a | **0** | Same caveat as row 9 |
| 11 | Semantic-duplicate detection (full corpus) | 219 | 247 | +12.8% |
| 12 | Supporting-source detection (full corpus) | 4 | 17 | +325% |
| 13 | Material-update detection (full corpus) | 28 | 87 | **+210%**, a clear, substantial recall win on real reader-worthy updates |
| 14 | Uncertain rate (full corpus) | 7.4% (281/3,774) | **26.8%** (1,012/3,774) | Large increase - see §10 for interpretation |
| 15 | Fragmented-story count | n/a (metric didn't exist) | **923** | The real, measured fragmentation cost of the M11.1 fix - see §10 |
| 16 | `would_suppress` count (full corpus) | 222 | 263 | +18.5% |
| 17 | Duplicate-suppression precision | not computable (no ground truth) | not computable (263-case human-review packet built, not yet reviewed - see §11) | Unchanged - still cannot be claimed |
| 18 | Duplicate-suppression recall | not computable | not computable | Unchanged |
| 19 | `would_update` count (= `material_update`) | 28 | 87 | Same as row 13 |
| 20 | Review-queue count (= `uncertain_match` count, the only outcome landing in the MEDIUM confidence band) | 281 | 1,012 | Same as row 14 |

## 7. Every false merge

**Zero confirmed** in the labeled calibration set (10 events, 4 real cases). **One suspected,
unconfirmed**: AI Olympiad event 14 (`747aa0cc`) landed `SEMANTIC_DUPLICATE` at 0.827 combined
against a story not rooted at either of its true siblings (event 4 or event 8's own stories) - see
§9. Not confirmed as a genuine false merge because the disposable Postgres container (which held
that story's own title/content) was destroyed before this was noticed; flagged as the single most
important open item for Checkpoint 4 (§13).

No exhaustive false-merge audit of the full unlabeled 3,774-event corpus was performed (no ground
truth exists for it) - unchanged limitation from Checkpoint 2.

## 8. Every false suppression in the labeled/reviewed set

**Zero of the 4 labeled real cases ever reached `would_suppress=True`** (unchanged from Checkpoint
2 - none of the 10 real labeled events combine `SEMANTIC_DUPLICATE`/`SUPPORTING_SOURCE` + `HIGH`
confidence + no-material-delta simultaneously). The 263-case human-review packet
(`docs/phase20_m11_suppression_human_review_packet.md`) has **not yet been reviewed by a human** -
no false-suppression claim is made about it. A first-pass spot check while building the packet
found one plausible false-suppression candidate worth flagging to the reviewer: two "romance
walkthrough" guide pages (PC Gamer, Fields of Mistria) for apparently different NPCs ("Juniper"
vs. "March") scored `SEMANTIC_DUPLICATE` at 0.760 - possibly two genuinely different guide pages,
not a same-story rehash. Not resolved here; deferred to the actual human review.

## 9. Identity / retrieval / scoring miss breakdown, and the interaction it revealed

Of the 6 labeled-case pairwise sibling checks: **1 converged** (Kitesurf), **5 classified
`IDENTITY_MISS`**, **0 `RETRIEVAL_MISS`**, **0 `SCORING_MISS`**.

This is a genuinely important, unexpected finding, not a clean win: **M11.2's own retrieval
widening appears to increase the risk surface for M11.1's `entity_overlap >= 0.2` heuristic to
misfire.** With Stage 1 now surfacing ~1,265 candidates on average (vs. 145.8 before), an
`UNCERTAIN_MATCH`-band event has far more *opportunities* for *some* unrelated candidate to
incidentally clear the 0.2 entity-overlap floor purely by chance, causing it to attach to that
unrelated story (preserving today's `event_count`-safe behavior) rather than fragment into its own
story - which is precisely the failure mode M11.1 was built to close, now re-opened by a different
route. GTA's own root event (`15a5ff78`), for example, now lands `UNCERTAIN_MATCH` and attaches to
an existing candidate (identity-broken relative to a clean root) rather than the clean `NEW_STORY`
it was in both Checkpoint 2 and Checkpoint 1 - though the *specific, mandatory* GTA invariant
("must remain separate from its own real sibling") still holds (§12), so the required regression
test still passes.

**This was not visible in either M11.1's own tests (which use hand-picked, isolated candidate
pools) or M11.2's own tests (which test retrieval and identity mechanics separately) - only the
combined, full-scale replay surfaced it.** This is exactly the kind of finding the corrective
block's own replay requirement exists to catch, and is reported here rather than smoothed over.

Caveat on the miss counts themselves (disclosed in §5): the classification precedence means an
`IDENTITY_MISS` case may *also* have an underlying retrieval or scoring issue that this round's
instrumentation cannot see once identity has already been flagged first. Rows 9-10's "0" counts
should be read as "0 *presenting as* retrieval/scoring misses once identity is accounted for," not
"retrieval and scoring are provably perfect."

## 10. Fragmentation and uncertain-rate interpretation

**Fragmented-story count: 923** (RELATED_STORY + weak-`UNCERTAIN_MATCH` events that now create
their own Story under the M11.1 fix). This is a real, non-trivial cost - roughly 24% of all
`NEW_STORY`-equivalent creations this run were fragmentation-driven rather than genuine new
stories. Whether this is an acceptable cost depends on how many of those 923 later successfully
receive real convergence via the existing confirmed-outcome path (not measured this round) versus
sitting permanently as orphaned singletons.

**Uncertain rate rose from 7.4% to 26.8%.** The most likely explanation, consistent with the data:
retrieval used to silently exclude most real candidates (94.2% cap saturation), so many events
that *should* have landed `UNCERTAIN_MATCH` against a real (if ambiguous) candidate instead
defaulted to `NEW_STORY` because no candidate was ever found at all. Widening retrieval surfaces
that previously-hidden ambiguity rather than creating it from nothing - `material_update` and
`supporting_source` detection both improved substantially (§6 rows 12-13), which would not happen
if the extra `UNCERTAIN_MATCH` volume were pure noise. That said, this is an interpretation, not a
proof, and a 3.6x increase in the review-queue-equivalent volume is a real operational cost that
would need to be sized against actual human/Tier-3 review capacity before any activation.

## 11. Suppression human-review packet

`docs/phase20_m11_suppression_human_review_packet.md` - built from all 263 real `would_suppress=
True` cases in this replay (not a chronological-first sample), stratified into: highest-confidence
(8), threshold-edge (8, all within 0.65-0.656), cross-source (8 of 203 total), same-source
repetitions (8 of 60 total), cross-category (8 of 90 total), and a note on different-company/
product controls (none found in real data; covered by the existing 4-case permanent synthetic
suite instead). **Not yet reviewed by a human.** No suppression precision/recall number is or
should be claimed until that review happens.

## 12. Permanent regression cases

- **Kitesurf**: both events now land under the **same** story (`all_events_landed_under_same_story
  _id: true`) - a real improvement over Checkpoint 2 (previously two separate, unrelated stories).
  Caveat: neither event is that story's own root (§9) - it is very likely a real, related earlier
  Cloudflare/AI-agent-browser story (0.4 measured entity overlap), but this could not be
  independently confirmed since the disposable container was destroyed before the anomaly was
  noticed. **Directionally passes the "must converge" requirement; not a clean pass.**
- **AI Olympiad 4/8/14**: does **not** demonstrate stable Story identity across the chain - the
  three events land under three different stories, one of them (event 14) at a concerning
  high-confidence, unconfirmed match (§9). **Does not meet the "stable Story identity" bar.**
- **Moscow pair**: does **not** silently become a wrong confident merge (`related_story`/
  `uncertain_match`, never a `SAME_STORY` outcome) - the specific, mandatory invariant holds. It
  regressed from converging (Checkpoint 1/2) to not converging; still passes the literal
  requirement as worded.
- **GTA negative control**: remains separate (`all_events_landed_under_same_story_id: false`,
  never a `SAME_STORY` outcome) - **passes**, though via `UNCERTAIN_MATCH`-attach-to-an-unrelated-
  candidate now rather than a clean `NEW_STORY` as before (§9's own interaction).
- **Synthetic entity-overlap traps**: unaffected by replay (fixed synthetic IDs, not present in
  real historical data) - covered by the permanent pytest suite instead, all 4 still passing.

## 13. Recommended next step

Do **not** proceed to any activation discussion. Before Checkpoint 4:

1. **Investigate the AI Olympiad event 14 high-confidence match** (§7, §9) - re-run a narrow,
   targeted replay slice that preserves the disposable container (or logs the matched story's own
   title/entities at diagnostic time, which this round's instrumentation did not do for this kind
   of case) so the suspected false merge can actually be confirmed or ruled out.
2. **Instrument correct-story retrieval rank** (§6 row 3), not just presence/absence - needed for
   a real precision/recall picture next round.
3. **Re-examine the M11.1 entity_overlap heuristic** in light of §9's finding - the interaction
   with wider retrieval was not anticipated at design time and measurably reduces the fix's own
   effectiveness on this labeled set. A higher floor, a different signal, or a different dispatch
   rule may be needed; do not simply raise the floor without new replay evidence.
4. **Get the suppression human-review packet actually reviewed** by a human before any suppression
   precision/recall claim is made.

## 14. GO/NO-GO for Story Memory `enforce`

**NO-GO**, unchanged from Checkpoint 2, and for an expanded set of reasons. The two originally
identified blockers (candidate capacity, story identity) were addressed with real, working code
and measurably moved several metrics in the right direction (saturation roughly halved,
material-update detection more than tripled, Kitesurf now converges). But the combined replay
surfaced a new, more subtle problem — the identity fix and the retrieval fix interact in a way
that reintroduces identity loss through a different mechanism, and produced at least one
concerning, unconfirmed high-confidence match that needs direct investigation before it can be
ruled either a real finding or a false alarm. Shipping either fix to shadow activation alone,
without addressing item 1 in §13, would not resolve the underlying reliability question this
Checkpoint set out to answer.
