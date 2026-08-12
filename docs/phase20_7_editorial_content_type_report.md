# PHASE 20.7 — EDITORIAL CONTENT TYPE LAYER

**Status: reporting only. No production activation.** Story Memory V2 remains fully shadow-only.

## 1. Current branch / HEAD

`feature/phase19-editorial-depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb`
(unchanged - no commit made this milestone).

## 2. Working tree status

All Phase 20.7 changes are uncommitted working-tree edits, consistent with every prior Phase 20
checkpoint.

## 3. Production state verification

`story_memory_mode=off`, `copywriting_prompt_version=4` (both unchanged). Real DB revision
`8faedf40f596`, Alembic head `3f37cf34109d` (unchanged - **no migration was needed or created**
this milestone, per §7's own conclusion). No `.env` edit. No worker started. No Telegram sent
(structurally impossible). No paid call made (the new classifier is 100% deterministic, title-
pattern-based).

## 4. Architecture investigation

- **`NewsEvent` schema** (`database/models/news_event.py`): id, source_id, title, summary,
  content, url, category, published_at, collected_at, hash, status, engagement counts,
  timestamps. No editorial-type-shaped column exists, and none was added.
- **`Story` schema** (`database/models/story.py`): id, title, category, entities, keywords,
  topic_bucket, first_event_id, event_count, timestamps. `topic_bucket` is the closest existing
  precedent - a small, deterministic classification computed once and persisted alongside an
  already-existing column.
- **Scoring pipeline** (`services/story_memory.py::score_candidate()`/`match_story()`): `category`/
  `topic_bucket` are already soft, additive scoring signals, never hard gates (Phase 20 M3's own
  finding). Checkpoint 6 already added two identity-relevant gates inside the confident-zone
  branch (`SUPPORTING_SOURCE`/`STORY_UPDATE`) - a distinctive-shared-entity requirement.
- **Delta/relationship classification**: unaffected by this milestone - `services/
  story_delta_engine.py` was not touched.

**Answers**:
1. **Safest storage location**: none needed - see below.
2. **Should this live on `NewsEvent`**: no. `NewsEvent` has a documented, deliberate "no hot-path
   column for anything computable from the title" rule (the exact reasoning `services/
   story_memory.py`'s own `StorySignature` already follows - entities/keywords/topic_bucket are
   never stored on `NewsEvent` itself, only recomputed on demand or stored on `Story` once a
   Story exists).
3. **Should this be derived metadata**: yes, exactly like `topic_bucket`.
4. **Does it require a migration**: **no**. Unlike `topic_bucket` (persisted on `Story` because
   `Story` already has a `topic_bucket` column from Phase 18.10), content type needs no persistence
   at all - `match_story()` already recomputes `entity_overlap`/`title_overlap` fresh from
   `candidate.title` on every call; content type is computed the exact same way, from `title` and
   `candidate.title`, entirely in memory.
5. **Can it exist as computed runtime metadata**: yes - and does. `services/
   editorial_content_type.py::classify_content_type()` is a pure function of a title string, called
   fresh inside `match_story()` for both the new event and the winning candidate. Zero schema
   change, zero migration, zero new storage anywhere.

## 5. Why content type is needed

Confirmed by Checkpoint 6's own disclosed limitation (cases 58/60): a distinctive, genuinely rare
shared entity ("Beast of Reincarnation") is not, by itself, proof that two titles describe the
same editorial Story - a review and an unrelated review, or a review and a gameplay guide, share
the product but are different editorial objects. Entity distinctiveness answers "is this about the
same THING"; content type asks "is this the same KIND of coverage of that thing" - a genuinely
different, complementary signal.

## 6. Final taxonomy

13 types, exactly as specified: `NEWS` (default/neutral), `ANNOUNCEMENT`, `REVIEW`, `GUIDE`,
`TUTORIAL`, `ANALYSIS`, `INTERVIEW`, `LEAK`, `RUMOR`, `PATCH_NOTE`, `RESEARCH`, `REPORT`,
`OPINION`. Every keyword pattern was checked against the real Phase 20 replay corpus (2026-08-04→
2026-08-08, 3,788 real titles) before being chosen:

| Type | Real corpus hits (of 3,788) |
|---|---|
| `REVIEW` | 42 |
| `ANNOUNCEMENT` | 40 |
| `ANALYSIS` | 23 |
| `GUIDE` | 21 |
| `RESEARCH` | 20 |
| `LEAK` | 17 |
| `RUMOR` | 13 |
| `OPINION` | 10 |
| `INTERVIEW` | 7 |
| `REPORT` | 2 |
| `PATCH_NOTE` | 0 this window (kept - a reasonable category, just not present in this 4-day sample) |

Checked narrowest/most-specific first (mirrors `_classify_topic()`'s own established priority-
order convention), whole-word/phrase boundary matching (not raw substring), English + Russian.

## 7. Storage decision

**No storage. No migration.** Computed purely at `match_story()` call time from `title` (new
event) and `candidate.title` (already-available Story field) - see §4.

## 8. Files changed

**New**: `services/editorial_content_type.py`, `tests/test_editorial_content_type.py`.
**Modified**: `services/story_memory.py` (import + `new_content_type` computed once per
`match_story()` call + a mismatch gate inside the `SUPPORTING_SOURCE`/`STORY_UPDATE` branch,
alongside Checkpoint 6's own distinctive-entity gate - both must pass for a confident outcome).

## 9. Tests added

34 tests in `tests/test_editorial_content_type.py`: 24 pure `classify_content_type()` pattern
tests (real, corpus-checked titles), 3 pure `is_content_type_mismatch()` tests, 7 integration
tests (real Postgres) for Cases A-E (A/B/C/D confirmed false-collision cases + two E variants -
the negative-control "same story despite different wording" case and the "same specific type"
case).

## 10. Before/after test results

**Before** (confirmed failing, test-first, per instruction): `ModuleNotFoundError` - the module
did not exist. Once implemented, Cases A/B/C/D (clean, explicitly-marked synthetic titles - "...
guide" vs "... review", "Review of..." vs "... announcement", "... analysis..." vs "announces...",
"research paper..." vs "product launch") all correctly resolve to a non-confident outcome
(`not in {STORY_UPDATE, SUPPORTING_SOURCE}`) on first run after implementation - **no further
iteration was needed for these 4 cases**. 3 minor pattern-tuning misses were found and fixed
during initial pure-unit-test validation (a test-authoring bug expecting `GUIDE` for a title that
correctly matches `TUTORIAL`'s own "how to" pattern; `GUIDE`'s own "best build" pattern requiring
exact word adjacency, broadened to bare "guide"; `OPINION`'s "opinion:" pattern never matching due
to a word-boundary/punctuation regex edge case, fixed to bare "opinion").

## 11. Replay comparison (same 2026-08-04→2026-08-07, 3,774-event dataset)

| Metric | BEFORE (Checkpoint 6) | AFTER (Phase 20.7) | Change |
|---|---|---|---|
| `NEW_STORY` | 1,568 | 1,569 | +1 |
| `SUPPORTING_SOURCE` | 15 | 15 | **0** |
| `STORY_UPDATE` | 125 | 125 | **0** |
| `SEMANTIC_DUPLICATE` | 247 | 247 | **0** |
| `UNCERTAIN_MATCH` | 999 | 999 | **0** |
| `RELATED_STORY` | 833 | 833 | **0** |
| `would_suppress` count | 173 | 173 | **0** |
| `material_update` | 72 | 72 | **0** |

**Honest finding**: the content-type gate had a measurable effect on exactly **1 event** across
the entire 3,774-event corpus (a `+1` shift in `NEW_STORY`, everything else byte-identical). This
is not a bug - it reflects that real-world titles rarely combine a high-scoring entity/title match
*and* clearly-opposing, explicitly-marked content types simultaneously; most of the corpus's real
ambiguity does not hinge on explicit type markers the way the deliberately-clean Cases A-D do.
**Duplicate suppression, genuine updates, Kitesurf, AI Olympiad, Moscow pair, and GTA are all
exactly unchanged** (verified directly against `known_case_results`).

## 12. Cases A-E results

| Case | Result |
|---|---|
| A (Guide vs Review, synthetic) | **Fixed** - `not in {STORY_UPDATE, SUPPORTING_SOURCE}` |
| B (Review vs Announcement, synthetic) | **Fixed** |
| C (Analysis vs Announcement, synthetic) | **Fixed** |
| D (Research vs Announcement, synthetic) | **Fixed** |
| E (negative control, SpaceX genuine update) | **Preserved** - still `STORY_UPDATE` |
| E (negative control, same-type Kitesurf) | **Preserved** - still a confident outcome |

**Important, honest correction**: Checkpoint 6's own *original* motivating cases (58, 60 - the
real "Beast of Reincarnation" review/guide pair) were re-checked against the real full replay and
remain **unfixed**:
- **Case 58**: the second title ("Beast of Reincarnation review – a taxing reflection of
  human-made damage") itself contains the word "review" - it classifies as `REVIEW`, the *same*
  type as the root. Same type is never a mismatch by design (§ design principle: only *different*
  specific types are gated) - this is not a bug in the gate, it is a case the gate was never able
  to catch, because both titles genuinely are reviews (of the same game, by different sources).
- **Case 60**: the real title ("If you hate parrying, projectiles in Beast of Reincarnation are
  ridiculously overpowered if you focus on leveling them") contains no explicit "how to"/"guide"/
  "walkthrough"/"tips for" marker at all - natural, informal gameplay-tip phrasing that this
  milestone's deterministic pattern list does not recognize. It defaults to `NEWS` (the neutral
  type), which is never gated.

This is disclosed here explicitly, not smoothed over: **Cases A-D (the corrective block's own
clean, explicitly-marked synthetic examples) are fixed; the original real-world motivating cases
58/60 are not**, because real natural-language titles do not always carry the same clear markers
synthetic examples do. The content-type layer's real capability boundary is narrower than the
motivating problem statement's own example suggested.

## 13. Remaining limitations

1. Cases 58/60 remain unfixed (§12) - solving them would require either (a) recognizing that two
   *same-typed* pieces (two reviews) can still be different editorial works, which is a different,
   harder problem than content-type mismatch detection, or (b) a broader, less-precise "guide-ish"
   language detector risking false positives elsewhere - neither was attempted this milestone
   given the explicit "do not overcomplicate" instruction and lack of a low-risk general design.
2. The content-type taxonomy is pattern-based and English/Russian only, matching this codebase's
   existing bilingual scope - a title in a third language, or a genuinely novel phrasing, defaults
   to `NEWS` (safe, never over-blocks, but also never helps).
3. Real corpus-wide impact this round was minimal (1 event) - the mechanism is proven safe (zero
   regression) but has not yet been shown to meaningfully move the needle on real, unlabeled
   false-collision cases beyond the specific labeled examples already known.
4. All limitations carried forward from Checkpoint 6 (§40 there) that this milestone did not
   address: cases 68/71/72/73's raw `material_update` delta label still persists in the real
   pool despite the identity-before-delta gate (match_type/suppression remain safe); AI Olympiad
   events 4/8's own identity-bootstrap gap; Moscow pair non-convergence; the 173-case suppression
   packet remains unreviewed by a human; the V6 Fact Safety blocker remains unresolved.

## 14. Recommendation

- **Story Memory shadow**: Conditional GO, unchanged - shadow-safe by construction (isolation
  tests re-run and pass), not yet exercised, a separate decision.
- **Duplicate suppression enforce**: **NO-GO** - unchanged from Checkpoint 6 (packet still
  unreviewed by a human; `would_suppress` count and composition are exactly unchanged this round).
- **Story-update routing/enforce**: **NO-GO** - unchanged from Checkpoint 6; this milestone's own
  finding (§12) that the motivating real-world case remains unresolved is itself an argument for
  continued caution here, not a reason to relax it.
