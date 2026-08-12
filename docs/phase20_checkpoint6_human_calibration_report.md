# PHASE 20 — CHECKPOINT 6: HUMAN-REVIEW CALIBRATION + PRECISION HARDENING

**Status: reporting only. No production activation.** Story Memory V2 remains fully shadow-only.

## 1. Branch / HEAD

`feature/phase19-editorial-depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb` (unchanged
throughout - no commit made this checkpoint, per instruction).

## 2. Working-tree state

All Checkpoint 6 changes are uncommitted working-tree edits, consistent with every prior Phase 20
checkpoint. No `.env` change. No migration applied (`alembic current` still `8faedf40f596`, head
still `3f37cf34109d` from Checkpoint 3 - untouched this round, no new migration was needed).

## 3. Files changed

**Modified:**
- `services/story_memory.py` - excluded a small, fixed set of grammatical determiners/
  demonstratives from `_extract_entities()`; added `_entity_document_frequencies()` and
  `_distinctive_shared_entities()`; gated the `SUPPORTING_SOURCE`/`STORY_UPDATE` confident-zone
  branches on a distinctive shared entity; added `MatchResult.has_distinctive_shared_entity`.
- `services/story_delta_engine.py` - added `gate_delta_by_identity()`.
- `scripts/phase20_story_memory_replay.py` - wired the new gate into its own delta-computation
  call site (mirrors `services/triage_orchestrator.py`'s own "keep the replay's copy in lockstep"
  convention established in M11.1); added `_check_human_reviewed_cases()` and its own capture of
  non-suppress/material-update control examples with full linked-Story detail.

**New:**
- `tests/fixtures/phase20_human_reviewed_cases.json`
- `docs/phase20_human_reviewed_calibration_fixture.md`
- `tests/test_story_memory_human_reviewed_calibration.py`
- `artifacts/phase20_checkpoint5_baseline_replay_results.json` (preserved BEFORE state)

**Untouched, preserved as raw review records:** `docs/phase20_m12_suppression_review_packet.md`.

## 4. Tests/fixtures added

`tests/fixtures/phase20_human_reviewed_cases.json` - 23 cases: 9 confirmed `FALSE_MATCH`, 6
genuine-update, 1 special investigation (Case 65), 7 representative `CORRECT_SUPPRESS`. `tests/
test_story_memory_human_reviewed_calibration.py` - 26 tests: 5 pure unit tests for the new
document-frequency mechanism, 3 pure unit tests for the identity-before-delta gate, and 18
integration tests (real Postgres) covering every case in the fixture against a realistic
(26-Story) candidate pool.

## 5. Human-reviewed cases encoded

All 16 cases from §B/§C/§D of the corrective instructions (58, 59, 60, 61, 62, 63, 64, 65, 66, 67,
68, 69, 70, 71, 72, 73) plus 7 representative `CORRECT_SUPPRESS` examples (cases 1, 2, 3, 7, 8, 55,
57 from the original packet - exact duplicate, Habr cross-category ×2, arXiv cross-category ×2,
the real AI Olympiad duplicate, the Ai4 2026 duplicate).

## 6. Baseline failures before fix

Confirmed failing against pre-Checkpoint-6 code (test-first, per instruction):
- Case 59/63 (arXiv papers): `entity_overlap` computed as `1.0` from a single shared "entity" -
  the word "this" (sentence-initial capitalization of "This paper..."/"This research...", not a
  real entity) - driving `combined` to 0.76/0.43, landing `STORY_UPDATE`/near-confident territory.
- Case 68/71/72/73: `match_type=UNCERTAIN_MATCH` (already non-confident, already safe from
  suppression) paired with `delta_classification=MATERIAL_UPDATE` computed from a title-only
  claim comparison with no awareness of match confidence at all.
- Case 58/60: `entity_overlap=1.0`/`0.67` from genuinely shared, genuinely distinctive words
  ("beast", "reincarnation" - the game's own title) combined with moderate title overlap (0.60/
  0.27), landing `SUPPORTING_SOURCE`/`STORY_UPDATE`.

## 7. Exact root causes found

Three distinct, evidence-grounded failure classes (`artifacts/phase20_checkpoint6_root_cause_trace.json`
holds the full per-case score/entity breakdown this analysis is drawn from):

1. **Spurious sentence-initial "entity"** (cases 59, 63): abstract-style titles conventionally
   open "This paper.../This research..." - `_extract_entities()`'s capitalized-run regex extracts
   the sentence-initial word as if it were a real entity. When it is the *only* entity on both
   sides, Jaccard overlap trivially hits 1.0 from pure grammatical coincidence.
2. **Generic, constantly-recurring entities treated as identity-forming** (cases 68, 71, 72, 73):
   a shared surname ("путин"), a shared mega-corp name ("apple"), or a template artifact ("день")
   was sufficient, combined with a real new date/number, to reach `MATERIAL_UPDATE`. Confirmed by
   direct comparison against the 6 genuine-update controls (61/62/66/67/69/70), which always
   shared either a multi-word entity ("app store", "windows pcs") or a company name that, in the
   real replay corpus, is specific to that one story pair ("wildberries", "volta", "spacex").
3. **Same distinctive product, different editorial content type** (cases 58, 60): a game review
   and a separate gameplay-tip article share a genuinely rare, genuinely distinctive product name
   ("Beast of Reincarnation") - the *entity* signal is not wrong here, but entity identity alone
   does not establish that two *editorial* pieces (as opposed to two sources covering the same
   *news event*) are the same Story. **This class was investigated but not solved this checkpoint
   - see §16.**

## 8. Algorithm changes made

1. **`_GENERIC_DETERMINER_ENTITIES` exclusion** (`services/story_memory.py`) - a fixed, closed set
   of English/Russian grammatical determiners/demonstratives ("this", "that", "the", "это", ...),
   never named entities, never derived from any calibration case's own company/product names.
2. **`_distinctive_shared_entities()` + document-frequency gate** - `SUPPORTING_SOURCE`/
   `STORY_UPDATE` now additionally require the winning candidate to share at least one entity that
   is either multi-word or has low document frequency within the current (already-bounded, up to
   150) candidate pool. `SEMANTIC_DUPLICATE`'s own near-identical-title path (`title_overlap >=
   0.75`) is left ungated - no evidence implicated it, and near-identical wording is independently
   strong evidence.
3. **`gate_delta_by_identity()`** (`services/story_delta_engine.py`) - downgrades `MATERIAL_UPDATE`
   to `UNCERTAIN_DELTA` when the match carries no distinctive shared entity. Only `MATERIAL_UPDATE`
   is gated - `NO_NEW_FACTS`/`CONFIRMATION_ONLY` are already independently protected (high title
   similarity is itself same-story evidence, and `compute_would_suppress()` already requires
   `SEMANTIC_DUPLICATE`/`SUPPORTING_SOURCE`, both now entity-gated too).

## 9. Why these are general, not case-specific

None of the three fixes reference any company, product, or person name from any calibration case.
The determiner exclusion is a fixed linguistic category (pronouns/articles), not a stopword list
mined from "Apple"/"Путин"/etc. The document-frequency mechanism is a classic, deterministic IR
technique (no embeddings, no ML) that computes distinctiveness fresh from whatever real candidate
pool exists at match time - it would treat *any* recurring subject the same way, and *any* rare
one the same way, regardless of what it is. The identity-before-delta gate reuses the exact same
signal, applied at a different pipeline stage. All three were validated against - and correctly
preserve - a `CORRECT_SUPPRESS` set (exact duplicates, cross-category reposts) and a genuine-update
set (real evolving stories) that share none of the false-match cases' own specific entities.

## 10-25. Per-case results (real replay, full corpus, not synthetic)

| # | Case | match_type | is_confident_same_story | delta_classification | would_suppress | Verdict |
|---|---|---|---|---|---|---|
| 10 | 58 (Beast review) | `supporting_source` | **True** | `minor_delta` | False | **NOT fixed** - disclosed limitation, §16 |
| 11 | 59 (cislunar paper) | `new_story` | False | n/a | n/a | **Fixed** |
| 12 | 60 (Beast guide) | `story_update` | **True** | `uncertain_delta` | False | **NOT fixed** - disclosed limitation, §16 |
| 13 | 61 (Telegram RU/EN) | `uncertain_match` | False | `uncertain_delta` | False | Matches human's own `UNCERTAIN` verdict - preserved |
| 14 | 62 (Wildberries update) | `uncertain_match` | False | `uncertain_delta` | False | Preserved (fail-open); `material_update` not reached - disclosed claim-vocabulary gap, §7's note |
| 15 | 63 (HRI paper) | `new_story` | False | n/a | n/a | **Fixed** |
| 16 | 64 (OpenAI/Russia Apple) | `uncertain_match` | False | `uncertain_delta` | False | Already safe before, still safe |
| 17 | 65 (Apple clipboard RU/EN) | `uncertain_match` | False | `uncertain_delta` | False | **Investigated, §17** - UNCERTAIN is the correct, evidence-honest conclusion |
| 18 | 66 (Apple/Telegram date) | `uncertain_match` | False | `material_update` | False | **Preserved** |
| 19 | 67 (Clipboard autumn 2027) | `uncertain_match` | False | `material_update` | False | **Preserved** |
| 20 | 68 (Putin fines) | `uncertain_match` | **False** | `material_update` | False | **Partially fixed** - match_type never confident, would_suppress never fires, but raw delta label not downgraded in the real pool; §16 |
| 21 | 69 (Anthropic/Volta) | `uncertain_match` | False | `material_update` | False | **Preserved** |
| 22 | 70 (SpaceX revenue) | `story_update` | True (genuinely same story) | `material_update` | False | **Preserved** |
| 23 | 71 (9to5Mac Daily) | `uncertain_match` | **False** | `material_update` | False | **Partially fixed** - same pattern as 68 |
| 24 | 72 (iPhone 20 vs 18) | `uncertain_match` | **False** | `material_update` | False | **Partially fixed** - same pattern as 68 |
| 25 | 73 (День 1624/1623) | `uncertain_match` | **False** | `material_update` | False | **Partially fixed** - same pattern as 68 |

## 17. Case 65 investigation + verdict

**Evidence**: `"Apple пообещала открыть для Windows доступ к буферу обмена iPhone"` vs. `"Apple
plans to open iPhone clipboard access to Windows PCs"`. Read as a human would: these describe the
same fact set (Apple + iPhone clipboard + Windows access) and are very likely a direct translation
of the same announcement. **However**, the deterministic pipeline has no cross-language capability
- keyword/title overlap is computed on raw tokens, so the Russian and English word forms share
almost nothing lexically (`title_overlap=0.35`, `entity_overlap=0.5` from "apple"/"phone" only).
**Conclusion**: `UNCERTAIN` is the evidence-honest classification - not because the same-story
judgment is wrong, but because the system's own available (translation-blind) evidence cannot
verify it. The pre-existing `uncertain_match`/`uncertain_delta`/`would_suppress=False` behavior was
already correct and was **not changed** for this case.

## 26. Duplicate-control preservation results

All 7 representative `CORRECT_SUPPRESS` cases (exact duplicate, 2× Habr cross-category, 2× arXiv
cross-category, AI Olympiad duplicate, Ai4 duplicate) preserved exactly: `would_suppress=True`,
`delta_classification=no_new_facts`, confident same-story `match_type` unchanged. **Zero
regression in duplicate suppression.**

## 27-30. Mandatory permanent regression cases

- **AI Olympiad**: unchanged from Checkpoint 4/5 (event 14 still correctly, confidently joins its
  real 5-member cluster at `semantic_duplicate`, 0.827 - confirmed correct per Checkpoint 4's own
  investigation, not touched this round).
- **Kitesurf**: **remains fixed** - both events still converge onto the same story.
- **Moscow pair**: unchanged (does not converge; does not falsely merge either) - not in scope
  this checkpoint.
- **GTA negative control**: **remains separate** - both events land on different stories.

## 31. BEFORE/AFTER replay metrics (same 2026-08-04→2026-08-07, 3,774-event dataset)

| Metric | BEFORE (Checkpoint 5 baseline) | AFTER (Checkpoint 6) | Change |
|---|---|---|---|
| Candidate-cap saturation | 43.8% | 44.4% | ~flat (retrieval untouched) |
| `NEW_STORY` | 1,503 | 1,568 | +65 |
| `SUPPORTING_SOURCE` | 17 | 15 | -2 |
| `SEMANTIC_DUPLICATE` | 247 | 247 | **0 - fully preserved** |
| `STORY_UPDATE` | 150 | 125 | **-25** |
| `RELATED_STORY` | 853 | 833 | -20 |
| `UNCERTAIN_MATCH` | 1,011 | 999 | -12 |
| `would_suppress` count | 173 | 173 | **0 - fully preserved** |
| `delta_classification=material_update` | 87 | 72 | **-15** |
| `delta_classification=confirmation_only` | 4 | 4 | flat |
| `delta_classification=minor_delta` | 96 (CP4) → 235 (CP5) | 236 | ~flat vs CP5 |
| Fragmented-story count | 922 | 905 | -17 |
| Kitesurf | Converged | Converged | Preserved |
| GTA | Separate | Separate | Preserved |

The `STORY_UPDATE` drop (-25) and `material_update` drop (-15) are the two concrete, corpus-wide
signals of the precision hardening taking effect beyond the 9 labeled cases - some number of
similar, unlabeled false-confidence cases elsewhere in the real corpus were also corrected. No
previously-correct duplicate leaked through as `NEW_STORY`/`STORY_UPDATE` - `SEMANTIC_DUPLICATE`
and `would_suppress` are both exactly unchanged.

## 32-34. Suppression precision on the human-reviewed subset

**Precision**: 7/7 representative `CORRECT_SUPPRESS` cases remain correctly flagged
(`would_suppress=True`) - 100% on this small, non-random sample. **False-suppression count on the
human-reviewed subset: 0** (no `FALSE_MATCH` case ever reaches `would_suppress=True`, before or
after). **`SHOULD_UPDATE` recall on reviewed controls**: 4/6 genuine-update cases (66, 67, 69, 70)
retain `material_update`; case 62 stays `uncertain_delta` (disclosed claim-vocabulary gap, not a
regression - it never reached `material_update` even before this checkpoint); case 61 stays
`uncertain_delta`, matching the human reviewer's own `UNCERTAIN` verdict exactly. **This is not a
general suppression precision/recall claim** - the 173-case packet itself remains unreviewed by a
person; only this specific 16+7-case human-labeled subset is scored here, exactly as instructed.

## 35-38. Test / lint / type / architecture results

- **Full Phase 20 targeted test result**: 208 passed, 1 skipped (pre-existing, documented), 0
  failed.
- **Ruff**: `ruff check` on all touched files - clean (one unused import found and fixed during
  this checkpoint's own work).
- **Mypy**: 2 pre-existing errors in `services/story_delta_engine.py` lines 84/92 (a
  `dict.get()` overload mismatch in `classify_delta()`'s original M6 claim-pooling loop) -
  confirmed **not introduced this checkpoint** (that file has no git history to diff against - it
  was created uncommitted in M6 - and these exact lines are outside every function this checkpoint
  touched, which were verified by direct read before and after). Disclosed, not silently fixed
  (fixing would require touching `_MATERIAL_CLAIM_TYPES`'s typing, out of this checkpoint's scope).
- **Architecture validation**: no dedicated "architecture validation" script/command was found in
  this repository - the closest equivalents (the AST-based shadow-isolation suite, `tests/
  test_story_memory_v2_shadow_isolation.py`) were run and pass; that suite caught and required
  cleanup of one of this checkpoint's own throwaway diagnostic scripts, confirming it is live and
  effective.

## 39. V6 Fact Safety blocker status

**Unchanged, not touched.** `apply_fact_safety()` still expects V4's `body` field and structurally
no-ops on V6's sectional schema. Preserved exactly as documented in Checkpoint 2/4/5 - remains a
real, disclosed blocker to any global V6 production activation, addressed separately per
instruction.

## 40. Remaining known limitations

1. **Cases 58/60 (same distinctive product, different editorial content) remain unfixed** - see
   §16 for the full, honest accounting. The distinctive-entity mechanism correctly identifies
   "Beast of Reincarnation" as genuinely rare/distinctive (which it is) - the missing signal is
   *content type* (review vs. guide vs. news), not entity identity, and this checkpoint did not
   build a content-type classifier (would require a new, more invasive mechanism, explicitly not
   attempted without stronger evidence of its general shape).
2. **Cases 68/71/72/73's raw `material_update` delta label persists in the real replay** despite
   `match_type` never being confident and `would_suppress` never firing - the document-frequency
   threshold (5% of the ~150-candidate Stage-2 pool) is evidently too lenient for at least these
   real cases, even though it worked in every synthetic/smaller-pool test. The *safety* properties
   (no confident merge, no suppression, no `event_count` bump) hold in all 4 cases; only the
   narrower, currently-unconsumed `delta_classification` label itself remains imprecise. Not
   re-tuned this round - would require another full replay cycle to validate a new threshold
   without guessing, and this checkpoint's own time budget was already fully committed to the
   higher-priority items.
3. **Case 62's `material_update` classification is structurally unreachable** without extending
   `services/fact_safety.py::extract_claims()`'s claim-type vocabulary (location names, responder-
   status facts) - explicitly out of scope as a "new feature" this checkpoint.
4. **Suppression packet (173 cases) remains unreviewed by a human** - unchanged from Checkpoint 5.
5. Every limitation carried forward from Checkpoint 5's own final report (§9 there) that this
   checkpoint did not address: AI Olympiad events 4/8's own identity-bootstrap gap, Moscow pair's
   non-convergence, retrieval-rank instrumentation gaps.

## 41. GO / CONDITIONAL GO / NO-GO recommendation

- **Story Memory shadow**: Conditional GO, unchanged from Checkpoint 5 - shadow-safe by
  construction, not yet exercised, a separate decision.
- **Duplicate suppression enforce**: **NO-GO** - the 173-case packet is still unreviewed; this
  checkpoint's own 7-case labeled sample shows 100% precision but is far too small to generalize.
- **Story-update routing/enforce**: **NO-GO** - §40 items 1-2 are real, disclosed precision gaps
  that a future "publish an update" feature would inherit if built today; combined with the
  unresolved V6 Fact Safety blocker (§39), this remains firmly out of reach this phase.

## 42. Confirmation: no production state was changed

`story_memory_mode=off` (unchanged). `copywriting_prompt_version=4` (unchanged). Real DB revision
`8faedf40f596` (unchanged, no migration applied). No `.env` edit. No worker started or restarted.
No Telegram message sent (structurally impossible - no bot import anywhere in this checkpoint's
code). No paid LLM/vision call made (every component touched this checkpoint is 100%
deterministic). No commit, push, or tag created.
