# PHASE 20 — CHECKPOINT 4: PRECISION HARDENING

**Status: reporting only. No enforce activation, no suppression activation, no `.env` changes, no
worker restarts, no Telegram sends, no paid calls, no Phase 21 work.** Story Memory V2 remains
fully shadow-only; `story_memory_mode=off` in the real `.env`, unchanged.

---

## 1. Exact Event-14 root cause (§1 of the corrective block)

**Reproduced with full state, not inferred from logs.** `scripts/phase20_story_memory_replay.py`
was extended to capture, for every labeled real case with a prior sibling: the full ranked
Stage-2 candidate list (score, entity/title overlap, rank), and a complete dump of both the
**winning** Story and the **true-sibling** Story it was compared against - id, root event, every
linked event, title, entities, keywords, topic, category (`docs/phase20_m11_1_story_identity_
investigation.md` §1 pattern, now extended for this purpose).

**Finding: this was a false alarm, not a false merge.** The Checkpoint 3 "suspected unrelated
Story" is real, correctly-clustered news content:

- **Winning Story** (`80f8925c…`): title *"Школьная сборная России третий год подряд стала
  абсолютным чемпионом на Международной олимпиаде по искусственному"* - already has **4 other
  real linked events**, all genuinely about the same Russian-team AI Olympiad win, from different
  Google News RU source variants. Event 14 (`747aa0cc`) is a **5th, correct** member of this
  cluster.
- **The calibration dataset's own labeled events (4, 8) are the ones that failed** - neither
  ever reached this same, real cluster. Event 8's own "true sibling" comparison in this run
  points at `b2ac1bfc…`, titled *"Российский бигтех ужесточил правила защиты данных при работе с
  ИИ"* - a **completely unrelated** "Russian big tech tightens data-protection rules" story -
  confirming event 8 itself suffered an identity mis-attachment (score_gap 0.64 in the winning
  story's favor).

**Precise classification**: `IDENTITY_MISS`, but pointed the wrong direction from Checkpoint 3's
own assumption. The bug is not "event 14 confidently attached somewhere wrong" - it is "events 4
and 8 (the calibration dataset's own hand-picked root/sibling) never found or created the real,
larger cluster that other real-world articles about the same event already occupy." The
calibration dataset itself was incomplete (only 3 of at least 7 real articles about this event
were curated into it) - not a defect in the matcher's classification of event 14.

**Correction to Checkpoint 3, stated plainly**: the "suspected false merge... concerning new
finding" language in that report was wrong. No false merge occurred here. This is disclosed
explicitly rather than quietly dropped.

## 2. Exact false-positive mechanism (the one actually confirmed)

A **different**, independently confirmed false-positive-risk case was found while building the
suppression human-review packet (Checkpoint 3 deliverable, spot-checked before this checkpoint):
two PC Gamer "Fields of Mistria" romance-walkthrough guide pages, template-identical except for
the named subject (`Juniper`/`arrogant witch` vs. `March`/`grumpy blacksmith`). Verified
empirically: `entity_overlap=0.6`, `title_overlap=0.75`, `combined=0.76` - a real, moderately-high
combined score driven mostly by shared *template* phrasing plus the shared game-name entity
("Fields", "Mistria"), not by genuine same-event identity. **This is the real, evidence-grounded
false-positive risk this checkpoint hardens against** - not the Event-14 case.

Root cause, precisely: `services/story_delta_engine.py::_classify_from_signals()`'s
`CONFIRMATION_ONLY` branch fired on `title_overlap >= 0.55` **alone**, never checking whether real
new distinctive keywords (`"juniper"`, `"arrogant"`, `"witch"`) were present. A template match with
a swapped subject could reach `CONFIRMATION_ONLY` - which, combined with a `SEMANTIC_DUPLICATE`/
`SUPPORTING_SOURCE` match_type and a `HIGH` confidence band, is exactly the three-way combination
`compute_would_suppress()` treats as safe to suppress.

## 3. Relationship/classifier changes made

**One targeted fix, evidence-grounded, in `services/story_delta_engine.py`**:
`CONFIRMATION_ONLY` now additionally requires `not new_keywords` (previously: title-overlap alone
was sufficient). When real new distinctive keywords are present despite high title overlap, the
case now falls through to `MINOR_DELTA`/`UNCERTAIN_DELTA` instead - both of which `services/
story_suppression.py::compute_would_suppress()` already, correctly, never allows to suppress
(unchanged policy, tested in Checkpoint 2/3).

**Deliberately NOT changed**: `services/story_memory.py`'s own `SEMANTIC_DUPLICATE`/
`SUPPORTING_SOURCE` match_type classification (the entity/title-overlap-driven relationship
classifier itself). §1's investigation found no confirmed false positive there to ground a change
against - the one candidate case (Event 14) turned out to be correct. Adding speculative,
unvalidated stricter gates at that layer risked breaking the real, hard-won Kitesurf and Event-14
convergences without a concrete case motivating it, which is exactly what "use the actual
false-positive cases to determine the minimum necessary rule" warns against. The confirmed false
positive lives at the **delta/suppression** layer, so that is where the fix was made.

Test written *before* the fix, confirmed failing against old code, passing after:
`tests/test_story_delta_engine.py::test_template_headline_with_new_distinctive_subject_is_not_confirmation_only`.

## 4. Story identity semantics

Full explicit definitions: `docs/phase20_m11_1_story_identity_semantics.md`. Four relations now
named precisely: **membership** (confirmed same-story, bumps `event_count`), **provisional
membership** (`UNCERTAIN_MATCH` + real entity signal, attaches without bumping), **related-to**
(transient, logged, never persisted after M11.1), and **provisional root** (M11.1's own new case -
a fresh `Story` whose founding evidence was itself uncertain/related, not confidently new).

**Confirmed schema limitation, explicitly documented, no migration proposed**:
`NewsEventStoryLink` cannot represent both "belongs to Story X" and "related to Story Y"
simultaneously - `news_event_id` is the table's primary key (at most one row per event). After
M11.1, a `RELATED_STORY` event gets real membership in its own new Story, but the "related to Y"
fact is lost once the triage transaction commits - observable only in that cycle's own log line.
No migration is proposed to fix this: nothing downstream currently consumes `RELATED_STORY` data
beyond the `TriageCycleReport.story_related` counter, so there is no concrete consumer to justify
new schema against yet.

## 5. Any schema change proposed, and why

**None this checkpoint.** All CP4 changes are pure Python logic (`services/story_delta_engine.py`)
plus offline replay instrumentation (`scripts/phase20_story_memory_replay.py`). The schema
limitation in §4 is documented, not migrated, per explicit instruction and the "no concrete
consumer yet" reasoning above.

## 6. Replay metrics: Checkpoint 2 vs Checkpoint 3 vs Checkpoint 4

Same dataset all three times: 2026-08-04 → 2026-08-07, 3,774 real events, disposable Postgres.
CP3 and CP4's match_type-level outcome counts are **byte-identical** - expected and correct, since
CP4 touched only the delta/suppression layer, not retrieval or relationship classification.

| Metric | CP2 (pre-corrective) | CP3 (identity+retrieval fix) | CP4 (+ precision hardening) |
|---|---|---|---|
| `NEW_STORY` | 2,441 | 1,503 | 1,503 |
| `STORY_UPDATE` | 39 | 150 | 150 |
| `SUPPORTING_SOURCE` | 4 | 17 | 17 |
| `SEMANTIC_DUPLICATE` | 219 | 247 | 247 |
| `UNCERTAIN_MATCH` (uncertain rate) | 281 (7.4%) | 1,011 (26.8%) | 1,011 (26.8%) |
| `RELATED_STORY` | 793 | 852 | 852 |
| Candidate-cap saturation | 94.2% (SQL-level) | 43.8% (Stage 2) | **43.8% (unchanged - preserved)** |
| Fragmented-story count | n/a | 922 | 922 (unchanged) |
| Identity/retrieval/scoring miss (labeled) | n/a | 5 IDENTITY_MISS, 1 converged | 5 IDENTITY_MISS, 1 converged (unchanged - see §1: correctly reclassified as calibration-set incompleteness, not a new bug) |
| Relationship-classifier false positives (labeled) | n/a | 0 confirmed | **0 confirmed** (§1's investigation cleared the one suspect) |
| `would_suppress` count | 222 | 263 | **173 (-34% vs CP3, -22% vs CP2)** |
| `delta_classification=confirmation_only` | 96 | 158 | **3 (-98%)** |
| `delta_classification=minor_delta` | 27 | 96 | **235** (absorbed the reclassified cases) |
| Material-update detection | 28 | 87 | 87 (unchanged) |
| Kitesurf | Not converged | **Converged** | **Converged (preserved)** |
| GTA | Separate | Separate | **Separate (preserved)** |
| Moscow pair | Converged | Not converged (regressed) | Not converged (unchanged this round - not touched by CP4's fix) |

## 7. Every labeled false merge

**Zero**, all three checkpoints. Event 14 (§1) is confirmed not a false merge upon investigation.

## 8. All known false suppression candidates

**Labeled set (10 real events, 6 synthetic controls incl. 2 new CP4 hard controls)**: zero ever
reach `would_suppress=True` in any checkpoint.

**Real replay corpus**: the one concretely identified false-suppression-risk case (§2, romance
walkthrough) is now **excluded** from the `would_suppress=True` set (confirmed: 0 occurrences of
"Juniper romance"/"March romance" in the regenerated packet, was present before the fix). The
remaining 173 real candidates have **not been human-reviewed** - the enriched packet
(`docs/phase20_m11_suppression_human_review_packet.md`) now includes full new/root facts, the
exact delta reasoning and new-keywords/claims found, the precise suppression-policy rule that
fired, and a blank `HUMAN VERDICT` field per case (never auto-filled) - ready for that review, not
a substitute for it.

## 9. Kitesurf / Olympiad / Moscow / GTA results

- **Kitesurf**: **converges** (both events, same story) - preserved from Checkpoint 3, unaffected
  by CP4's delta-layer-only change, as required (acceptance condition A).
- **AI Olympiad**: event 14 correctly joins a real 5-member cluster (§1) - the calibration
  dataset's own events 4/8 do not yet reach it. Re-scoped as a calibration-dataset completeness
  issue plus a genuine, still-open identity/retrieval question about *why* events 4/8 don't find
  that cluster - not a false-positive/precision problem. Left for a future milestone, not
  papered over.
- **Moscow pair**: unchanged from Checkpoint 3 (does not converge; does not falsely merge either -
  the specific mandatory invariant "must not silently become a wrong confident merge" holds, per
  Checkpoint 3's own accepted finding). CP4 did not touch retrieval/classification, so no change
  was expected here and none occurred.
- **GTA negative control**: **remains separate** (acceptance condition B, preserved).

## 10. Suppression packet

`docs/phase20_m11_suppression_human_review_packet.md` - regenerated against the 173 CP4 candidates
(down from 263), stratified into highest-confidence (8), threshold-edge (8), cross-source (8 of
155), same-source repetitions (8 of 18), cross-category (8 of 48), each with new-event facts,
matched-Story-root facts, category/source match flags, the exact relationship+delta outcome, the
literal suppression-policy rule that fired, and a blank `HUMAN VERDICT` line. **Not yet reviewed by
a human** - no precision/recall number is or should be claimed.

## 11. Acceptance conditions (§11 of the corrective block)

| # | Condition | Result |
|---|---|---|
| A | Kitesurf remains fixed | **Met** |
| B | GTA remains separate | **Met** |
| C | Olympiad Event 14 no longer confidently attaches to an unrelated Story | **Reframed by investigation**: it never did - §1 found the "unrelated Story" premise itself was wrong; the match is correct. Nothing to fix at that layer; condition's underlying concern (a real false merge) does not exist. |
| D | False high-confidence same-story matches do not increase | **Met** - `SEMANTIC_DUPLICATE`/`SUPPORTING_SOURCE` counts unchanged (247/17); `would_suppress` (the practical proxy for "acted-upon" false-confidence risk) dropped 34% |
| E | Retrieval recall gain from Checkpoint 3 substantially preserved | **Met** - Stage 1/Stage 2 pool sizes and saturation rate byte-identical to Checkpoint 3 (CP4 did not touch retrieval) |
| F | Suppression remains disabled | **Met** - no `.env` change, no activation anywhere |

## 12. Recommended next step

1. Investigate *why* AI Olympiad events 4 and 8 fail to find/create the real cluster their own
   later corroborators (including event 14) do reach - this is now understood to be the actual
   open question, not a precision defect. Likely relates to the same entity/retrieval interaction
   Checkpoint 3 flagged, but should be re-diagnosed with the richer §1-style instrumentation now
   available rather than assumed.
2. Get the 173-case suppression packet actually human-reviewed before any suppression-precision
   claim.
3. Consider whether the calibration dataset itself should be expanded to include the other 4 real
   Russian-AI-Olympiad articles discovered in §1, now that they're known to exist.

## 13. GO/NO-GO for Story Memory `enforce`

**NO-GO**, unchanged. Checkpoint 4 resolved the one confirmed precision risk found so far (the
delta-engine template-headline gap) and, importantly, *cleared* a previously-reported concern that
turned out to be a false alarm - both are real progress. But `enforce` (or even suppression
shadow-activation) still requires: a human-reviewed suppression packet (§10, not done), resolution
of the Moscow-pair regression and the AI-Olympiad events-4/8 identity question (§12), and at least
one more replay confirming these hold at scale. Shadow-only observation remains the appropriate
state.
