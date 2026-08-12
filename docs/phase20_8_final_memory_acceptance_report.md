# PHASE 20.8 — FINAL STORY MEMORY ACCEPTANCE REVIEW

**Status: consolidation and decision-making only. No code was changed to produce this report.**
Story Memory V2 remains fully shadow-only throughout.

---

## 1. Executive summary

Phase 20 built a deterministic Story Memory V2 (candidate retrieval, relationship classification,
delta detection, duplicate-suppression proposal) entirely in shadow mode, validated against real
historical data across 8 checkpoints (Checkpoints 1-6, plus 20.7). Every checkpoint measured
real, reproducible evidence from the same 3,774-event/4-day disposable-Postgres replay rather than
estimating. The system materially improved across the phase: candidate-cap saturation fell from
94.2% to 44.4%, Kitesurf now converges, `SEMANTIC_DUPLICATE` duplicate detection has held at 247
events with **zero regression** across every hardening pass, and `would_suppress` false-positive
risk was measurably reduced (263→173 candidates, -34%, with the one concretely confirmed
false-positive pattern eliminated from the suppression-eligible set entirely).

**None of Story Memory V2 is active in production.** `story_memory_mode=off` (unchanged default
throughout all of Phase 20). Suppression has no production toggle to even disable - it exists only
as a pure function (`services/story_suppression.py::compute_would_suppress()`) never called from
any live code path.

**Final recommendation** (detail in §9): Story Memory **shadow** is CONDITIONAL GO. Duplicate
suppression **enforce**, story-update **routing/enforce**, and Telegram newsroom integration are
all **NO-GO** - each blocked by a specific, named, disclosed gap (unreviewed suppression packet,
two confirmed false-match cases, the V6 Fact Safety schema mismatch), not by a vague "not ready."

## 2. Current architecture state

- **Retrieval** (`services/story_memory.py`): two-stage - a wide, indexed SQL fetch (Stage 1, up
  to 10,000 candidates, time-windowed) feeding a cheap Python preselection (Stage 2, entity/
  keyword-relevance tier + recency tier, capped at 150). No embeddings, no vector DB.
- **Relationship classification** (`services/story_memory.py::score_candidate()`/`match_story()`):
  a weighted entity/title-overlap score (`0.6·entity_jaccard + 0.4·symmetric_title_overlap` +
  small soft category/topic bonuses) banded into `NEW_STORY`/`RELATED_STORY`/`UNCERTAIN_MATCH`/
  `SUPPORTING_SOURCE`/`SEMANTIC_DUPLICATE`/`STORY_UPDATE`. Confident outcomes
  (`SUPPORTING_SOURCE`/`STORY_UPDATE`) additionally require a genuinely distinctive shared entity
  (Checkpoint 6) and a compatible editorial content type (Phase 20.7) - two independently-gated,
  evidence-driven precision guards, both deterministic.
- **Story identity dispatch** (`services/triage_orchestrator.py::_apply_story_memory()`):
  `RELATED_STORY` and low-entity-overlap `UNCERTAIN_MATCH` create their own Story (Checkpoint 3's
  M11.1 fix) rather than silently attaching to an unrelated candidate.
- **Delta Engine** (`services/story_delta_engine.py`): reuses `services/fact_safety.py::
  extract_claims()` and `extract_story_signature()` - no new extraction. `MATERIAL_UPDATE` is
  gated on the same distinctive-entity signal ("identity before delta", Checkpoint 6).
- **Suppression proposal** (`services/story_suppression.py`): a pure function, computed only in
  the offline replay harness - `SEMANTIC_DUPLICATE`/`SUPPORTING_SOURCE` + `HIGH` confidence + no
  material delta.
- **Editorial Content Type** (`services/editorial_content_type.py`, Phase 20.7): a pure,
  title-pattern classifier (13 types), computed at match time, never persisted, never a hard gate
  on its own - only a secondary check alongside the distinctive-entity requirement.
- **Schema**: two additive migrations created, **neither applied**: `3c22be05f4e5` (3 nullable
  shadow columns on `news_event_story_links`) and `3f37cf34109d` (an index on `stories.updated_at`,
  required for the wider Stage-1 retrieval to stay cheap). Real DB stays at `8faedf40f596`.

## 3. Phase 20 timeline

| Stage | Delivered |
|---|---|
| M2-M5 (Checkpoint 1) | Retrieval widened past the category hard-gate; symmetric title overlap; word-boundary topic classification; `RELATED_STORY` introduced |
| M6-M11 (Checkpoint 2) | Delta Engine, suppression proposal layer, confidence bands, first real 3,774-event replay - discovered 94.2% candidate-cap saturation + the Story Identity Gap |
| M11.1-M11.3 (Checkpoint 3) | Fixed both Checkpoint 2 blockers (two-stage retrieval, Story Identity dispatch); replay showed real wins alongside a new, unconfirmed concern (AI Olympiad event 14) |
| Checkpoint 4 | Investigated event 14 - found it was a **false alarm** (a correct match into a real 5-member cluster); found and fixed a **different**, confirmed false-positive class (template-headline delta-engine gap); `would_suppress` -34% |
| Checkpoint 5 | Built the 73-case stratified, fully-detailed human-review suppression packet; full Story-cluster-context identity analysis for all 4 mandatory cases; resolved the schema-limitation question (doesn't block current goals) |
| Checkpoint 6 | Human review of the packet surfaced 9 confirmed false-match cases and 6 genuine-update cases; 3 general root-cause classes found and 2 fixed (spurious-entity exclusion, identity-before-delta gate); `SEMANTIC_DUPLICATE`/`would_suppress` held exactly flat (zero regression) |
| Phase 20.7 | Editorial Content Type layer - fixed the 4 corrective block's own clean synthetic cases (A-D); **did not** resolve the original real-world motivating cases 58/60 (disclosed, not hidden) |
| Phase 20.8 (this report) | Consolidation - no code changed |

## 4. What changed (cumulative, Checkpoint 2 baseline → now)

| Metric | Checkpoint 2 (pre-fix) | Now | Change |
|---|---|---|---|
| Candidate-cap saturation | 94.2% | 44.4% | -49.8pp |
| `NEW_STORY` | 2,441 | 1,569 | -872 |
| `STORY_UPDATE` | 39 | 125 | +86 |
| `SUPPORTING_SOURCE` | 4 | 15 | +11 |
| `SEMANTIC_DUPLICATE` | 219 | 247 | +28 |
| `UNCERTAIN_MATCH` | 281 (7.4%) | 999 (26.5%) | +718 |
| `would_suppress` | 222 | 173 | -49 (-22%) |
| Kitesurf | Not converged | Converged | Fixed |
| GTA negative control | Separate (accidentally) | Separate (on the merits) | Preserved, now for the right reasons |

## 5. What was validated

- **8 full-corpus replays**, same 3,774-event/2026-08-04→2026-08-07 dataset, disposable Postgres,
  zero paid calls, zero Telegram, zero production mutation, every time. Results reproduced
  byte-identically across repeated runs of unchanged code, confirming determinism.
  `docker ps` and `alembic current` checked before and after every checkpoint - production state
  never moved.
- **242 targeted Phase 20 tests** (unit + integration, real Postgres via `db_session`), all
  passing at the time of this report. Ruff and Mypy clean on every touched file (2 pre-existing,
  disclosed, unrelated Mypy errors in `services/story_delta_engine.py`'s original M6 code, not
  introduced or touched by any later checkpoint).
- **AST-based shadow-isolation tests** (`tests/test_story_memory_v2_shadow_isolation.py`) - confirm
  no Story Memory V2 module is imported from `capabilities/executor.py`, `worker/content_cycle.py`,
  or `capabilities/copywriting_capability.py`. Live, effective (caught and required cleanup of a
  throwaway diagnostic script during Checkpoint 6's own work).
- **A human review pass** over a 73-case stratified sample of real suppression candidates plus 16
  false-match/genuine-update cases plus 7 duplicate-suppression controls - the only validation
  layer in Phase 20 that involved a person, not just automated replay.

## 6. Human review results

### 6a. Duplicate suppression scorecard (reviewed subset)

| | Count |
|---|---|
| Total reviewed (this report's own labeled subset) | 7 representative `CORRECT_SUPPRESS` cases + 173 real candidates sampled into the 73-case packet (unreviewed by a person beyond the 7 representative cases) |
| Correct suppress (of the 7 representative, human-labeled) | **7/7 (100%)** |
| False suppress (of the 7) | **0** |
| Uncertain (of the 7) | 0 |

Breakdown of the 7, all preserved through every hardening pass:
- **Exact duplicate** (Konstantin Tsiolkovsky arXiv paper, cs.CV/cs.CL) - `SEMANTIC_DUPLICATE`, suppressed.
- **Aggregator copy** (Motley Fool stock-picks, Google News wording variant) - `SUPPORTING_SOURCE`, suppressed.
- **Habr category duplicates** (×2 - GPT-5.6 roundup, RTX 5090 token-pricing piece, each appearing
  under both "Habr: Artificial Intelligence" and "Habr: Machine Learning") - `SEMANTIC_DUPLICATE`,
  suppressed.
- **arXiv duplicates** (×2 - Tsiolkovsky archive note across cs.CV/cs.CL; AKBC paper across
  cs.CL/cs.AI) - `SEMANTIC_DUPLICATE`, suppressed.
- **AI Olympiad duplicate** (the real Russian-team-champion story, exact-title repost via Google
  News RU) - `SEMANTIC_DUPLICATE`, suppressed.
- **Ai4 2026 duplicate** (conference press-release title, Google News aggregator repeat) -
  `SEMANTIC_DUPLICATE`, suppressed.

**Important scope caveat, stated plainly**: this 100% figure is over a small (7-case), deliberately
easy, representative sample chosen to confirm no regression - **it is not a general precision
claim over the full 173-case (or larger, unlabeled) suppression-eligible population**, which
remains unreviewed by a human. See §9's own explicit reasoning for why duplicate-suppression
enforce is still NO-GO despite this clean result.

## 7. Final false-match review (Cases 58-73)

| Case | Expected human verdict | Actual system behavior | Remaining risk |
|---|---|---|---|
| **58** (Beast of Reincarnation review/review) | FALSE_MATCH | **Unresolved** - `SUPPORTING_SOURCE`, 0.89, `minor_delta`. Both titles independently contain the word "review" (Phase 20.7's content-type gate treats same-type as compatible, by design) | **Medium** - would not be suppressed (`minor_delta`, not `no_new_facts`), but would be treated as a confirmed same-story update if update-routing existed |
| **60** (Beast of Reincarnation guide/review) | FALSE_MATCH | **Unresolved** - `STORY_UPDATE`, 0.81, `uncertain_delta`. Natural-language gameplay-tip phrasing carries no explicit "guide"/"how to" marker, defaults to neutral `NEWS` | **Medium** - same as 58; not suppressed but would be a confirmed update if routing existed |
| **59** (cislunar robotics paper vs. teleoperation paper) | FALSE_MATCH | **Fixed** - `NEW_STORY`. Root cause (a spurious shared "this" entity from "This paper...") eliminated at the extraction layer | **Low** - resolved |
| **63** (HRI motion-planning paper vs. teleoperation paper) | FALSE_MATCH | **Fixed** - `NEW_STORY`, same root cause and fix as 59 | **Low** - resolved |
| **64** (OpenAI/Apple lawsuit vs. Russia/Apple regulation) | FALSE_MATCH | Already safe pre-Checkpoint-6 and remains so - `UNCERTAIN_MATCH`, `uncertain_delta`, never suppressed | **Low** - never was a confident merge |
| **68** (Putin marketplace fines vs. crypto law) | FALSE_MATCH | **Partially fixed** - `UNCERTAIN_MATCH` (never confident, never suppressed), but the raw `delta_classification` label still reads `material_update` in the real candidate pool (the 5%-of-pool document-frequency threshold was too lenient for this real case) | **Low-Medium** - no unsafe *action* results (no suppression, no confident merge, no `event_count` bump), but the label itself is misleading if ever read downstream |
| **71** (9to5Mac Daily vs. Apple @ Work Podcast) | FALSE_MATCH | Same pattern as 68 - `UNCERTAIN_MATCH`/`material_update` | **Low-Medium**, same reasoning as 68 |
| **72** (iPhone 20 vs. iPhone 18) | FALSE_MATCH | Same pattern as 68 - `UNCERTAIN_MATCH`/`material_update` | **Low-Medium**, same reasoning as 68 |
| **73** (vc.ru "День N" digest template) | FALSE_MATCH | Same pattern as 68 - `UNCERTAIN_MATCH`/`material_update` | **Low-Medium**, same reasoning as 68 |

**Pattern across 68/71/72/73**: all four share the identical residual gap - the *safety-critical*
properties (no confident same-story claim, no suppression, no `event_count` bump) are fully
achieved; only the *secondary*, currently-unconsumed `material_update` delta label persists. This
is disclosed as a real, partial fix in Checkpoint 6's own report, not newly discovered here.

## 8. Final update review (Cases 61/62/66/67/69/70)

| Case | Same Story preserved? | Update preserved? | Suppressed? |
|---|---|---|---|
| **61** (Telegram App Store RU/EN) | `UNCERTAIN_MATCH` (matches the human reviewer's own `UNCERTAIN` verdict exactly - cross-language equivalence cannot be verified by a translation-blind deterministic pipeline) | `uncertain_delta` (no regression - never reached `material_update` even pre-Checkpoint-6) | No |
| **62** (Wildberries drone attack, location/responder update) | `UNCERTAIN_MATCH` | `uncertain_delta` - never reaches `material_update` (a disclosed, structural gap: location names and responder-status facts are not claim types `extract_claims()` recognizes; extending that vocabulary is out of Phase 20's scope) | No |
| **66** (Apple Telegram removal, confirmed date) | `UNCERTAIN_MATCH` | **`material_update` preserved** | No |
| **67** (Clipboard iPhone/Windows, autumn 2027 timeline) | `UNCERTAIN_MATCH` | **`material_update` preserved** | No |
| **69** (Anthropic/Volta $10B deal) | `UNCERTAIN_MATCH` | **`material_update` preserved** | No |
| **70** (SpaceX financial-AI-company story) | **`STORY_UPDATE`** (a confident, correct same-story classification) | **`material_update` preserved** | No |

**Zero regression** across all 6 - every genuine update case behaves identically after every
Checkpoint 6/20.7 hardening pass as it did when first labeled.

## 9. Final replay

**No new replay was executed for this report.** Reasoning, stated explicitly rather than assumed:
zero code changed between Phase 20.7's own final replay and this consolidation checkpoint (no
implementation work was authorized or performed this round). Every Story Memory V2 component is
100% deterministic, and replay determinism was independently confirmed across 8 separate runs this
phase (identical code → identical, or single-digit-noise-level identical, results every time - see
Checkpoint 3's own explicit reproducibility check). Re-running would consume ~15-20 minutes of
disposable-Postgres compute to reproduce a value already known with certainty. The Phase 20.7 final
replay (`artifacts/phase20_m11_replay_results.json`, run same-session, same dataset, same disposable
Postgres protocol) is reused as this report's own authoritative "final" state:

| Metric | Checkpoint 6 | Final (=Phase 20.7) | Change |
|---|---|---|---|
| `NEW_STORY` | 1,568 | 1,569 | +1 |
| `SUPPORTING_SOURCE` | 15 | 15 | 0 |
| `SEMANTIC_DUPLICATE` | 247 | 247 | **0** |
| `STORY_UPDATE` | 125 | 125 | **0** |
| `RELATED_STORY` | 833 | 833 | 0 |
| `UNCERTAIN_MATCH` | 999 | 999 | 0 |
| `would_suppress` | 173 | 173 | **0** |

Kitesurf, AI Olympiad, Moscow pair, and GTA negative control all confirmed byte-identical to
Checkpoint 6 in this same run (`known_case_results`, directly re-verified for this report).

## 10. Content Type Layer review (Phase 20.7)

**What it solved** (all confirmed via test-first, real-replay-validated cases): review vs.
announcement, guide vs. review (clean synthetic titles with explicit markers), analysis vs.
announcement, research vs. announcement. All 4 of the corrective block's own worked examples
(Cases A-D) fixed on first implementation, zero regression to duplicate suppression or genuine
updates (`SEMANTIC_DUPLICATE`/`would_suppress` exactly unchanged in the full replay).

**What it did not fully solve**: natural-language guides/tips without an explicit marker (Case 60
- "If you hate parrying, projectiles are ridiculously overpowered..." carries no "how to"/"guide"
phrase, defaults to neutral `NEWS`). Same content type but different editorial purpose (Case 58 -
two independent reviews of the same product are both literally `REVIEW`-typed, so "same type" does
not imply "same instance" - a fundamentally different, harder problem than type-mismatch
detection, not attempted this phase).

No new fixes were made in producing this section - documentation only, per instruction.

## 11. Remaining risks / blockers

1. **V6 Fact Safety** - `apply_fact_safety()` expects Copywriting V4's `body` field; V6's schema
   (`prompts/copywriting/v6.yaml`) is sectional with no `body` key, so the function structurally
   no-ops for V6 output regardless of `fact_safety_mode`. **Status: UNRESOLVED.** A hard blocker
   for any global V6 production activation - addressed in a separately-scoped future milestone,
   never opportunistically touched during any Story Memory checkpoint.
2. **Editorial Content Intent** - Content *type* exists (Phase 20.7); content *intent* (is this
   the SAME instance of a type, e.g. two different reviews of one product) does not. **Status:
   DEFERRED** - no low-risk general design was found this phase; forcing one risked exactly the
   kind of case-specific/overcomplicated fix every checkpoint's own instructions warned against.
3. **More real production shadow data required** - every Phase 20 checkpoint validated against
   the *same* 4-day, 3,774-event window. This proves internal consistency and determinism
   thoroughly, but not necessarily how the system behaves against a materially different volume,
   season, or news mix. A genuine shadow-mode activation (§9's own conditional GO) would be the
   first source of that broader evidence.
4. Carried forward, unresolved, from earlier checkpoints: cases 68/71/72/73's residual
   `material_update` label imprecision (§7); AI Olympiad events 4/8's own identity-bootstrap gap
   (why the calibration dataset's own hand-picked root events never found the real, larger cluster
   event 14 correctly joined - Checkpoint 5's own open question, never revisited); Moscow pair's
   non-convergence; the 173-case suppression packet's remaining, un-sampled cases never reviewed
   by a person.

## 12. Final Story Memory capability matrix

| # | Capability | Status | Evidence |
|---|---|---|---|
| 1 | Candidate retrieval | **CONDITIONAL GO** | Saturation 94.2%→44.4% (Checkpoint 3); two-stage design, indexed, deterministic, no embeddings. Not yet exercised at real production volume outside the 4-day replay window (§11 item 3) |
| 2 | Story identity matching | **CONDITIONAL GO** | Story Identity Gap fixed (Checkpoint 3 M11.1); Kitesurf converges; one confirmed, disclosed, unfixed scoring defect remains (AI Olympiad event 8, generic-token score inflation, Checkpoint 5) |
| 3 | Duplicate detection | **GO** (as a detection mechanism, distinct from *enforcement* - see #6) | `SEMANTIC_DUPLICATE` held at 247/247 exactly flat across every hardening pass; 7/7 representative duplicate types correctly detected (§6a) |
| 4 | Supporting-source detection | **CONDITIONAL GO** | Distinctive-entity + content-type gates added (Checkpoints 6, 20.7); 15/15 preserved in final replay; cases 58/60 (§7) remain a known, disclosed gap specifically for this outcome type |
| 5 | Material-update detection | **CONDITIONAL GO** | Identity-before-delta gate added (Checkpoint 6); 4/6 genuine updates retain `material_update` correctly; cases 68/71/72/73's label-only imprecision remains (§7); case 62's claim-vocabulary gap remains (§8) |
| 6 | Suppression decision | **NO-GO for enforce** | Policy itself well-tested (100% on the 7-case representative sample, §6a) and has no production toggle to even activate; the 173-case packet - the actual precision evidence needed before enforcement - remains unreviewed by a human |
| 7 | Telegram/editorial routing readiness | **NO-GO** | No routing implementation exists; blocked independently by the V6 Fact Safety gap (#11.1) and the unresolved identity edge cases (#11.4) even before considering routing-specific work |

## 13. Final decision matrix

**Story Memory shadow**: **CONDITIONAL GO**
Reason: shadow-safe by construction (AST-isolation tests pass; nothing in production reads any
Story Memory output today), extensively replay-validated, deterministic, reversible. Conditional
on: this being a genuinely separate, explicit authorization step (not a byproduct of this report),
and on `.env`/production changes being made deliberately, not silently.

**Duplicate suppression enforce**: **NO-GO**
Reason: the human-reviewed evidence that exists (7 cases) is clean, but is not remotely large
enough to generalize a production precision/recall claim from. The 173-case packet built
specifically to enable that review remains unreviewed.

**Story update routing**: **NO-GO**
Reason: blocked by two independent, disclosed gaps - the residual false-match label imprecision
(§7, cases 68/71/72/73) and the V6 Fact Safety schema mismatch (§11.1), which would make any
V6-routed update content unsafe regardless of Story Memory's own state.

**Telegram newsroom integration**: **NO-GO**
Reason: no implementation exists yet; independently blocked by both items above even before
considering integration-specific risk.

## 14. Next roadmap step

The single highest-leverage next step, per this report's own evidence, is **not** more Story
Memory precision tuning - diminishing returns are already visible (Phase 20.7 moved exactly 1
event in the full corpus). The two blockers gating everything downstream are:
1. A **human review pass over the 173-case suppression packet** (`docs/
   phase20_m12_suppression_review_packet.md`) - the one piece of evidence every enforce-level
   recommendation in this report is waiting on.
2. **V6 Fact Safety** - a separately-scoped fix to `apply_fact_safety()`'s schema assumption,
   already fully specified as a known blocker across every checkpoint this phase, never touched.

Both are explicitly out of scope for this report and are not begun here, per instruction.
